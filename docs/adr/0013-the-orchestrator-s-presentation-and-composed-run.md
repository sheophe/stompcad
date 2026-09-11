# ADR-0013: The orchestrator's presentation and its composed run

**Status:** Accepted

## Context

`stompcad` composes `stompdrill` and `stompcollider` in one process.
[ADR-0012](0012-progress-protocol-and-optional-kernel-capability.md) gave it the
protocol a run reports through; this decides what the orchestrator does with
that report, and what the composed run may and may not change about either
tool's behaviour.

Run by hand, the two tools are two invocations: two reports, two exit codes, and
a drill document carried between them on disk. Composed, they are one record,
one position and one status. Nothing about that composition may change a byte
either tool writes, because a user who reaches for the orchestrator is asking
for the same artefacts with less ceremony.

The terminal is not always there. A pipe, a CI runner and a dumb terminal get
the same run, and must get the same record of it.

[docs/specs/stompcad-tui.md](../specs/stompcad-tui.md) argues these decisions in
full. This ADR records the ones that bind code, because CLAUDE.md requires the
ADR accepted before the architecture changes.

## Decision

### One step list serves both a terminal and a pipe

A run is nine named steps — `read panel`, `quantise`, `drill`, `write case`,
`read boards`, `match`, `seat`, `clash`, `write assembly` — declared once, in
`stompcad.plan`, as data. A run naming no board takes the first four.

`stompcad.present.Presentation` is what a run drives: `begin`, `update`,
`finish_step`, `ask` and `report`. `PlainWriter` implements it for a run with no
terminal, streaming each step's line as that step completes and drawing no bar.
A terminal implementation renders the same step list live and settles into the
same lines, which is what lets a terminal's scrollback be compared with a piped
run's output directly.

`ask` raises `NoTerminal` rather than prompting. A genuine gap with no terminal
to answer on is a usage failure naming what was missing, not a prompt nobody
will see.

### A step credits its span only when it succeeds

Position advances on completion, never on entry. A run stands at zero until its
first step finishes, and `track()` leaves the position where an abandoned run
reached rather than completing the bar over output that does not exist.

A step that stops to ask has not completed, so it credits nothing and running it
again cannot retreat a reported position. That is what makes ADR-0012's
monotonicity a property of this design rather than of the maximum `_Run.advance`
happens to take.

### The run's span is divided once, among the steps it intends to take

One `begin` and one division per run. A drill-only run divides its span among
its own four steps, and a run with boards divides among all nine; the two halves
then draw from the one division. Dividing the same scope twice would leave
monotonicity resting on that maximum, and would weigh a run against five steps
it never intended to take.

### The driver calls each phase, and holds what each one produced

`stompcad` calls `quantise()`, `Pipeline.run` and the emitters directly, in the
same order both command lines call them, rather than one entry point per tool.
Neither tool gains a flag, an option or a callback for this.

Each phase's result stays on the driver: the raw artwork, the quantised data,
the drilled data, the case model. `Driver.retry(key, options, scope)` is the
published way back in: it replaces the run's options and runs that one step
again over what is already held. Only a step whose input the driver holds can be
retried; naming another is refused rather than quietly re-read, because a driver
that silently re-parsed the artwork would spend exactly what holding the
intermediates was for.

### The composition adds no second mechanism, and no second rule

Both write steps render every target, then stage and commit the whole set
through `stompmodel.protocols` — `stage_all` and `commit_all`, the workspace's
one write mechanism and the transaction
[ADR-0001](0001-pipeline-and-emitter-adapters.md) and
[ADR-0005](0005-binary-emitter-payloads.md) define. A commit loop of the
orchestrator's own would replace each target in turn and abandon the rollback
that makes the set one transaction.

An error binds the whole run, as CLAUDE.md requires: each write step withholds
every one of its own targets and names them, and a drill half that errored stops
the run before a board is read. Nothing is rendered on that path, because an
emitter may legitimately refuse data this broken.

That rule binds each half's target set, not the run's whole timeline. The drill
half's write step commits when that step completes, before a board is read, so a
run whose dock half errors leaves the drill artefacts on disk beside a report of
the failure. This is a deliberate limit. A completed step has written what it
computed, and the drill artefacts describe exactly that, so the set left behind
is incomplete rather than inconsistent. Byte identity does not require it: the
dock half reads the drill document from a private temporary and never from a
committed target, so one transaction spanning both halves would be feasible. It
is declined because deferring would hold every drill payload through minutes of
kernel work only to report a write that had already been decided, and would
leave the `write case` step line describing something not yet on disk. The cost
is that drill artefacts are no evidence the run succeeded; the exit code, which
reduces both halves, is the only status.

The acceptance criterion is byte identity. Every artefact the composed run
writes is compared against what the wrapped tool's own command line writes from
the same inputs, and the comparison stands as a test rather than as a claim.

### Cancellation is the sink raising

`Cancelled` derives from `BaseException`, for the reason `KeyboardInterrupt`
does, and `CancellingSink` wraps the sink a run already had. A cancelled run
exits `130`, reserved for a stop the user asked for.

A cancelled run leaves neither artefact nor temporary — but because nothing is
staged at any moment a sink can raise, not because rollback removes one. Both
write steps report progress once per rendered target and begin staging only once
every target is rendered. ADR-0001's rollback covers a fault *during* staging,
which a raising sink cannot cause.

### One run reports one status

The four exit codes both tools share are reduced from the worse of the two
halves' findings, so the record and the status cannot disagree. `130` is the
fifth, and no other path produces it.

### The terminal presentation runs the composed run on a worker thread

`InlineApp` owns the main thread and its event loop; the composed run happens
on a Textual worker thread, so a blocking kernel call cannot freeze the
display for as long as it holds that thread. Every `TerminalPresentation`
method crosses back to the app through `call_from_thread`, and nothing on the
worker touches a widget directly. `ask` blocks its own worker on an `Event`
the modal's callback sets, because the answer is a keypress that arrives only
after the crossing that pushed the modal has already returned. The detail
level `v` cycles is kept on the app alone and is never persisted, matching
decision 3.

Three further points came out of building this, not out of the spec.
`InlineApp.drive` only stores the callable it is given; the worker itself
starts from `on_mount`, because `run_worker` needs a running app and `drive`
is called before `run()` supplies one — starting it at `drive` time raises
`RuntimeError` and every terminal run would crash. Any fault on the worker is
caught as `BaseException`, kept as `app.failure`, and re-raised on the main
thread once `app.run()` returns, so `main`'s one exception-to-exit-code
mapping serves the terminal path as well as the headless one instead of
drifting into two; `BaseException` rather than `Exception` is required
because `Cancelled` derives from it. And `q` abandons a question the same way
it stops a run, because the picker binds its own `q` — `OptionList` swallows
the app's binding — and because `App.pop_screen` can discard a pending
screen's result callback without ever invoking it, `ask`'s wait is bounded
rather than open-ended, or an abandoned screen would park the worker forever.

## Rationale

**A protocol rather than printing.** Two audiences read a run: a person watching
a terminal, and a file or a script reading a pipe. Both need the same facts and
different drawing. A protocol keeps the one line format in one place; printing
from the driver would fix the audience at the point the work happens.

**Weights derived, not guessed.** ADR-0012 requires declared weights and forbids
deriving one from a clock. `stompcad.plan` derives each step's weight from the
leaves that step reports on the reference fixture, counting a leaf that performs
a kernel operation ten times a plain one. The multiplier is the scheme's one
judgement and is stated beside the counts; the counting command sits with them,
so the figures can be reproduced rather than trusted.

**Intermediates held rather than recomputed.** Feeding an answer back by
constructing a second driver over revised options would re-read the artwork and
reload the case model — minutes of work to change one enclosure name. Holding
each phase's result is the whole reason the driver is an object rather than a
function, and `retry` is what makes that reason reachable from outside it.

**Byte identity as the acceptance test.** An orchestrator's failure mode is
subtle divergence: a default resolved differently, a setting not carried across,
a timestamp read from a clock. None of those show in a report. All of them show
in a byte comparison, which is why one exists for each half and one for the
command line itself.

**The kernel constraint binds what `stompcad` reaches for.** Importing the
driver loads the kernel transitively, through `stompdrill`'s own emitters. That
is not a leak: `stompcad` imports neither the kernel nor the geometry package,
which a test enforces by parsing every import in the package. `stompcad.plan`
additionally imports neither tool, because a terminal renders it.

## Consequences

Neither tool's command-line contract changes. Both keep their flags, their
reports and their exit codes, and both remain usable alone.

[docs/CLI.md](../CLI.md) documents a third command: its arguments, the formats
either half can render, the two facts docking has no default for, and the five
exit codes.

A phase added to either tool is a step added to `stompcad.plan`, a weight
recounted with the command recorded there, and a step line in the presentation.
The step list is data, so nothing else changes with it.

`TerminalPresentation`, in `stompcad/inline.py`, is the terminal implementation
of `Presentation`; decision 3's three levels of detail, `--progress` and the
`v` key that cycles them are decided in code alongside it. `ask` is
implemented there too, drawn as the modal decision 6 will pick from, but it
still has no caller, so it remains exercised only by tests. An interactive
resolver is still later work, and `retry` still has no caller either. The
spec's decisions 6, 8 and 10 remain undecided in code.

`stompcad`'s suite gates the tests that read the board fixture and the cached
enclosure model behind `--boards` and `--hammond`, mirroring both tools rather
than inventing a third convention. The composed dock run is minutes of kernel
work, and it is the acceptance test for the dock half.
