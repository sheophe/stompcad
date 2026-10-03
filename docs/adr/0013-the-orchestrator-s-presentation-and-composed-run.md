# ADR-0013: The orchestrator's presentation and its composed run

**Status:** Accepted, amended by
[ADR-0014](0014-the-workbench-and-its-resolution.md) in five places, beside the
change to `retry` already recorded here and, with plan 3, its worker-thread
decision amended to a process, for decision 18's reason: the terminal
presentation's worker-thread mechanism now serves the workbench rather than
`InlineApp`, its inline screen and the detail level `v` cycled; a terminal's
settled step lines are now written as the workbench exits, so the byte
comparison against the same run piped is against those exit lines; an error
pauses a run and asks, a warning does not pause, and `promoted()` is deleted
rather than left unreachable, which retires `--promote-warnings`; `CI` present
in the environment, or `TERM=dumb`, now counts as no terminal even with a tty
attached; and `q` quits while `esc` stops a run, rather than `q` meaning stop
because the app exited with the run. `retry` still honours a revision where the
held intermediates allow it, and otherwise discards that step's own holds and
runs it again rather than refusing, because refusing was right while a resolver
alone called it mid-run and wrong once a builder in the workbench can call it
after simply changing their mind. Its worker-thread decision is amended to a
process, for decision 18's reason: only `call_from_thread` is unchanged; a
worker still crosses to the app, but now pumps events across a process boundary
instead of doing the run's own work; `ask` blocks in that process on its own
command pipe rather than a worker's `Event`; and a fault crosses as a value
re-raised on the far side rather than as the exception object carried to the
main thread. A further amendment, for wall drilling, makes the run eleven
steps rather than the nine its first decision lists: `drill walls` and `write
model` join after `clash`, and the drill half's JSON document and drilled model
commit at `write model`, after the walls are cut, while the Excellon and the
drawings still commit at `write case`. That commit is withheld on *either*
half's error, because it runs after docking and is derived from it, which the
per-half limit recorded below no longer covers. The decision's body below keeps
the nine as the record of what was first decided; the amendment placed before
the Rationale governs. This ADR's other decisions stand.

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
run's output directly. The workbench writes its settled step lines to the
terminal as it exits, so that byte comparison is against those exit lines.

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

### A gap is resolved between a step's work and its credit

Resolution sits inside the step: it produces its data, `Driver._settled` asks
about the first finding a picker can answer, the step runs again under that
answer, and only then is it credited with the outcome the successful run
earned. Decision 4 requires exactly that — a step that stops to ask credits
nothing — so a resolution loop outside the step would have to either report the
step twice or retract a line it had already written.

Two codes reach a picker: `ambiguous-enclosure`, whose candidates are the tied
parts and whose answer declares `case`, and `empty-group`, whose candidates are
a board's own designators and whose answer widens `panel_reference` rather than
replacing it. `stompcad.resolve.RESOLVABLE` is the whole list, and a code absent
from it stays a refusal. A third is a row there, a branch in `_candidates` and
`revision_for`, and a row in `_RETRY_INPUTS` — three small places rather than
one clever one.

What a step may honour on a *retry* is narrower than what it reads on a first
run, and the two are separate tables. `_STEP_INPUTS` records what a step reads;
`_RETRY_INPUTS` records what it can still honour when it runs again, because a
retry spends the intermediates the driver holds rather than inputs it re-reads.
A revision the named step cannot honour is refused, naming the step that would
have to run again for it to take effect, rather than accepted and ignored.

The dock half holds the boards as read separately from the boards as filtered,
so a revised filter re-runs without the temporary the parse needed. That is
also why a revised board list is refused: `read boards` re-runs its filter over
boards already scanned, and the files they were staged from are gone by then.

An error pauses the run and asks; a warning does not pause but stays
actionable once the run completes. `promoted()` is deleted rather than left
unreachable, because nothing has to stop for a warning once `Findings` is
the place a builder returns to.

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

### The composed run happens in a process of its own

The worker thread was chosen so a blocking kernel call could not freeze the
display, and that reason was right; it still holds for the pump that now
carries events across the wider boundary. It was not sufficient. A thread
and the interface share one interpreter, and the run's own Python between
kernel calls holds the interpreter lock as surely as a blocking kernel call
does; the display does not freeze, but it answers late, late enough to read
as a fault in the application.

So the run happens in a process started with `spawn`. Never `fork`: a
forked child inherits the interface's memory, a live Textual application
included, at whatever moment the fork landed. The process outlives one run,
because the spec's resume, decision 10, spends intermediates the driver
still holds, and a process started per run would throw away the thing a
resume exists to reuse.

A quit never signals a run in flight. `_write` stages and then commits with
no cancellation point between, and both roll back by unwinding; a signal
does not unwind, so signalling there is how a half-written set of artefacts
is made. A quit asks the run to stop the way `esc` already does, and waits.
What may be ended outright is a process sitting in its command loop, where
nothing is in flight and there is nothing to roll back. A process that ends
without reporting is itself reported: every way a run can finish reaches the
session, because a session left believing a run is working holds every
place read-only with no way back.

That promise covers the interpreter's own exit as well as the quit, because
`multiprocessing` ends every daemon child from an exit handler of its own
and a run cut short there is cut short between the staging and the commit
as surely as one cut short by `q`. The residual risk is accepted rather than
removed: a run that never hears its stop delays the window's close for as
long as it takes, which is the deliberate trade against a half-written set
of artefacts.

What crosses is what a pipe already receives: step lines, positions,
diagnostics, the questions a pause asks, the answers it takes, a stop, and
the paths written. Nothing the kernel builds travels. `ask` no longer blocks
a worker on an `Event` and polls the app; it blocks in the run's own process
on its command pipe, where waiting costs the interface nothing.

A fault is no longer carried out as the exception object. An exception is an
object and the pipe carries values, so what crosses is its sentence and
whether `main` has a branch for its kind. A fault `main` would have mapped
is re-raised as a `StompError` with the same sentence, so the printed line
and the exit code are unchanged; anything else is re-raised as `RunFailed`,
which `main` does not catch, so a defect still leaves a traceback. Which of
the two it is, is decided in the run's own process, where the exception
still is. The class is named for a reader and never rebuilt from that name:
the interface would be importing whatever a pipe told it to — the kernel's
own module, for a fault the kernel raised, into the one interpreter kept
free of it — and a class that builds its message from its arguments would
build a second one around the first, so the instruction a tool wrote for a
builder would reach them wrapped around itself. The remote traceback
travels with a defect, because the traceback the interface could produce
names the line that re-raised. The
presentation boundary itself does not move: `Presentation` is the same
protocol with the same five methods, and what changed is that one
implementation of it now writes into a pipe.

`CI` present in the environment, or `TERM=dumb`, counts as no terminal even
with a tty attached, so a runner that allocates a pty gets the plain writer
rather than a full-screen application it cannot answer and would otherwise
hang against.

`q` quits, stopping any run first and confirming while one is in flight;
`esc` stops a run in flight instead. That replaces the earlier decision that
`q` meant stop because the app exited with the run: quitting and stopping
are different acts once the app stays open across runs, and need different
keys.

One further point came out of building this, not out of the spec. The
pump itself starts with the first run rather than from `on_mount`, because
`events()` reaches `_serving()`, which spawns the process: a worker started
at mount would spawn one merely to listen, and decision 1 forbids opening a
project from costing kernel work. The run's own process catches its fault
as `BaseException` — `Exception` would miss `Cancelled`, which derives from
it — and reports it across the pipe as a value; the pump hands that value
to the app, which keeps it as `app.failure` and re-raises it on the main
thread once `app.run()` returns, so `main`'s one exception-to-exit-code
mapping still serves the terminal path as well as the headless one instead
of drifting into two.

### Amendment: eleven steps, and the drill half's document and model commit last

**Accepted.** A run is eleven named steps — `read panel`, `quantise`, `drill`,
`write case`, `read boards`, `match`, `seat`, `clash`, **`drill walls`**, **`write model`**,
`write assembly`. A run naming no board still takes the first four: both new steps lie
inside the region `plan_for` prunes, so a drill-only run is untouched rather than merely
equivalent to what it was. A run with boards divides its span among all eleven.

`drill walls` sits after `clash` because it works from the ranking that survived re-ranking,
which is the only ranking that will not change under it. It is an ordinary `Stage` appended
only here; `stompdrill`'s own `build_pipeline` is untouched, so no stage asserts that another
ran and the standalone command line cannot reach it.

The drill half's commit divides. `write case` keeps its name, its position and — in a run
with no boards — its behaviour, committing every drill-half target byte for byte as it does
now. With boards it commits only what is already complete without the walls: the panel's
Excellon and its two drawings, whose hole numbers are independent of wall drilling. The JSON
document and the drilled model describe the whole job, so they belong to `write model`, after
the walls are cut.

This amends the deliberate limit recorded above. Its purpose survives: a dock-half failure
still leaves a builder the files to go drill the panel with, because the Excellon and the
drawings are committed before a board is read. What changes is that the two artefacts which
would be *wrong* if written early are no longer written early. The cost is unchanged — drill
artefacts are still no evidence the run succeeded, and the exit code is still the only status.

The manifest declaration joins the **last** drill-half commit: `write model` where the run
has one, `write case` otherwise. A project file never sits beside an artefact that was never
written, which is ADR-0014's decision holding under a split.

**The per-half partition does not reach `write model`.** The limit recorded above divides the
run by half and lets each half's completed commit stand, and that was sound while every
drill-half commit happened *before* a board was read. `write model` happens after, and its
bytes are derived from the dock half: a wall hole's position, its surface and its diameter
all come from the features the clash settled. So an error in the dock half withholds `write
model`'s **artefacts** as well as `write assembly`'s, and a builder told a designator is
claimed by two expressions is not handed a document whose wall holes were resolved from
features that run just declared undecidable. `write case` is unaffected, which is what keeps
the limit's purpose: the Excellon and the drawings are already on disk, and nothing about them
depends on a board. The cost is that a dock-half error now withholds two artefacts a run
before this amendment would have written — which is the point, because those two would have
been wrong.

Its **declaration** still commits, and names only the formats that produced a file. It
commits because, in a run with boards, this is the drill half's *only* carrier — `write case`
declares no format there — so withholding it would leave exactly what ADR-0014's decision 8
forbids: committed files beside no project file, or beside defaults that did not make them.
It is narrowed because `output.targets` is a per-format map, and naming a format this very
commit withheld would point a row at a file nobody wrote. That is not a new rule but the one
`payload_for` already applies to a format another commit owns, read here for a format no
commit will reach. The run's other places — artwork, enclosure, drilling — declare values
rather than files, and those values are exactly the ones that produced the Excellon and the
drawings now on disk, so they are recorded in full. An error on the cut document itself is a
different matter and withholds the whole commit, because then the values are what is in doubt.

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
either half can render, the two facts docking has no default for, the five exit
codes, and which gaps a run on a terminal offers to resolve.

A phase added to either tool is a step added to `stompcad.plan`, a weight
recounted with the command recorded there, and a step line in the presentation.
The step list is data, so nothing else changes with it.

`serve._Down`, in `stompcad/workbench/serve.py`, is the implementation of
`Presentation`, written into a pipe instead of onto a screen, having
replaced `WorkbenchPresentation` once the run moved to its own process.
`ask` pushes `PickerScreen`, the workbench's own modal, where the inline
app once pushed `ChoiceScreen`.
The interactive resolver has landed for both resolvable codes, so the spec's
decisions 6, 8 and 10 are decided in code. What the resolver drives is `_rerun`,
which runs one step again and returns its outcome without reporting it, because
a loop answering gap after gap must not credit the step in between. `retry` is
the same work with the step credited, kept as the public way to run one step
alone; it has no caller in production yet, and remains an entry point rather
than a use.

What is left undone is the one gap decision 6 gestured at and this design
declines: `ambiguous-placement` records a count rather than candidates, and no
stage applies an explicit placement, so a picker there would ask a question no
answer could be honoured for. The spec states that limit in its own decision 6.

`stompcad`'s suite gates the tests that read the board fixture and the cached
enclosure model behind `--boards` and `--hammond`, mirroring both tools rather
than inventing a third convention. The composed dock run is minutes of kernel
work, and it is the acceptance test for the dock half.
