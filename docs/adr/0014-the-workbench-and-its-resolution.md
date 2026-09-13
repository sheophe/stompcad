# ADR-0014: The workbench and its resolution

**Status:** Accepted

## Context

The current interface asks a builder to already know flags, exit codes and raw
diagnostics before typing a command.
[ADR-0013](0013-the-orchestrator-s-presentation-and-composed-run.md) decided
what the composed run looks like once every input to it is already settled;
this ADR decides how those inputs come to be settled at all, and what
a builder does with the result of a run once it exists.

On a terminal, `stompcad` opens a full-screen workbench and the user stays in
it. A run becomes an event inside that workbench, not the program's exit, and
that changes what "resolving an input" means. A command line invoked once and
then exited never had to reconcile a value it was told with a value it
remembered; a tool that stays open, over a project a builder returns to, does.
A value can now arrive from an argument on this invocation, from a project
declared earlier, from what the tool can discover about its own inputs, or
from a default matching what each tool already assumes on its own command
line — four sources where the product specification recognised three — and
every one of them can disagree with another. Once resolved, a value has to
say where it came from, because a workbench that shows every field for
editing must make a disagreement visible at the row that carries it, not
buried in a report read after the fact.

A gap-free run has to leave something behind for the next invocation to read,
and a builder who changes one value has to be able to re-run only the work
that value touches rather than walking a stale plan from the top. Both need
the same fact the driver already holds for a narrower purpose — what each
step consumes of what an earlier one produced — extended into a live stale
set the sidebar can point at, and into a `retry` that acts on a builder's
change of mind rather than only refusing what it cannot honour mid-run.

Finally, an interface that stays open needs a stated rule for when a run may
start, because a workbench that can spend minutes of kernel work and write
nothing, or silently skip docking because no board was ever found, is worse
than a command line's blunt refusal to start at all.

[docs/specs/stompcad-workbench.md](../specs/stompcad-workbench.md) argues
these decisions in full; it is not tracked in this repository, so the
decisions below restate what it settled rather than pointing at it. This ADR
records the ones that bind code, because CLAUDE.md requires the ADR accepted
before the architecture changes.

## Decision

### The workbench is the interface; the absent terminal is the only other path

On a terminal, `stompcad` opens full screen and the user stays inside it; a
run is an event the workbench drives, not the program's exit. There is no
batch flag and no batch concept. A command line that supplies every value
means "do not ask me": the run starts and is watched inside the workbench
rather than replacing it. An invocation that leaves a value unresolved opens
the workbench with that value shown as a gap and the run one keypress away,
never blocked on terminal input it could otherwise have asked for.

Automation reaches the opposite path by not having a terminal at all.
`PlainWriter`, `step_line` and `NoTerminal`, all from ADR-0013, keep serving
it unchanged: the same step lines stream, nothing is drawn, and a genuine gap
exits `3` naming what was missing. `CI` present in the environment, or
`TERM=dumb`, now counts as no terminal even with a tty attached, so a runner
that allocates a pty gets the plain writer rather than a full-screen
application it cannot answer and would otherwise hang against.

### Resolution has four ranks: argument, project, discovered, default

A value resolves from the strongest rank that supplies it: an argument on the
command line, then the project's manifest, then what the tool discovered
about its own inputs, then a default matching what each tool already assumes
on its own command line. Discovery sits between the manifest and the default
because it is stronger evidence than an assumption and weaker than a
declaration typed on purpose — the panel found beside the working directory,
the layers read from the artwork itself, the boards found in the project
directory, the case model found in the enclosure cache or named by a `.stp`
whose stem is a catalogue part, the panel-reference designators read from the
boards, and the match tolerance derived from the drill grid are none of them
guesses, but none of them is what the builder typed either.

The enclosure part is not among them, and a model's filename is discovery of
the model rather than of the part. `stompdrill` identifies the part from the
measured footprint, and where that measurement ties it may try a supplied
model's stem against the tie — a guess it reports as inferred and abandons
where it disagrees, leaving the tie standing for a picker to settle.
Resolving that same stem to `case` here would hand the guess to that stage as
a declaration, and a declared part that disagrees is an error. So `case`
resolves from the argument, the project or nothing at all; the model travels
beside it, and the stage that measures owns what the filename is worth.

A project value that discovery contradicts is a finding, not an override. If
the manifest names a drill layer the artwork no longer has, the run reports
that disagreement rather than silently re-picking the layer discovery would
otherwise choose. A manifest is a declaration, and a contradicted declaration
is news the builder needs, not noise a resolver quietly absorbs.

### Every value carries its origin, and a disagreement is shown, not summarised

Every resolved value states which rank supplied it, in words a builder can
act on rather than the rank's name: from the artwork, found beside it,
inferred from the model, from the project, from the command line, or a plain
default. Where two ranks disagree — an argument overriding a project value,
or a discovered value the project also states — both are shown together at
the row, not folded into one number with the other recorded elsewhere. An
artefact must never be quietly attributable to settings other than the ones
that produced it, and showing the disagreement at the point it applies is
what keeps that true without a summary a builder has to go looking for.

### The manifest fills gaps per half, with what produced artefacts, not on edit

Editing a value writes nothing to the manifest. A gap in the project's
manifest is filled only when a run completes, and only with the values that
actually produced artefacts — never with a value that was typed and then
abandoned. A value the manifest already holds is used and left untouched
unless the builder confirms replacing it, so a one-off invocation cannot
permanently redefine a project by accident.

Gap-filling follows each half's commit, not the whole run. ADR-0013 already
commits the drill half's artefacts when `write case` completes, independently
of whether the dock half that follows succeeds; the manifest records the
drill half's declarations at that same commit, and the dock half's at `write
assembly`'s. Recording only on a whole-run success would leave real artefacts
on disk beside a manifest still holding defaults that did not make them —
exactly the misattribution the previous decision exists to prevent.

The manifest holds declared intent alone: no hashes, no timestamps, no record
of a previous run. Its schema mirrors the workbench's places, one object per
place plus a schema `version`, so a place and its manifest section always
name the same thing; an unknown key is reported and ignored rather than
rejected, so a manifest written by a later version still opens; and a
manifest that cannot be read must never fall back to silent defaults, because
a project whose declarations cannot be read must not be run under values that
look like the user's own.

### Invalidation propagates by data dependency, not position

Changing a value marks stale every step that reads it, and every step that
consumes what a stale step produced; resuming re-runs exactly that set
against the intermediates the driver still holds. Propagation follows what a
later step actually consumes of an earlier one's output, not a step's
position in the plan's ordered list. `targets` is read by `write case` at
position four and again by `write assembly` at position nine; a frontier
keyed to position rather than to consumption would mark `read boards`,
`match`, `seat` and `clash` stale too, and re-run all four — minutes of
kernel work — for a changed output filename that none of them reads. A write
step produces no intermediate any later step consumes, so marking one stale
propagates nowhere.

This needs a second table beside `_STEP_INPUTS`, naming what each step
consumes of what earlier steps held. A step is stale if it reads a changed
field directly, or if any step whose holds it consumes is stale; a step added
to the plan is a row added to both tables. Resuming is explicit, never
automatic: kernel work takes minutes, and a run starting on a keystroke would
be hostile.

### `retry` honours a revision where it can, and discards what it can't

ADR-0013's `retry` refuses a revision naming a step that cannot honour it,
because a retry spends the intermediates the driver holds rather than
re-reading an input — a revised board list needs a parse `read boards` no
longer performs. That refusal is correct for a resolver that must not credit
a step while still asking a question mid-run, and wrong for a builder in the
workbench who has simply changed their mind. `retry` therefore generalises:
it honours a revision where the held intermediates allow it, and otherwise
discards that step's holds and runs the step again as a first run would.
`_RETRY_INPUTS` stays narrower than `_STEP_INPUTS` for the reason it always
was; what changes is what happens when a revision falls outside it, from
refusal to invalidation. A position may never retreat: discarding a step's
holds discards the span it had already credited, so running it again cannot
report a position behind the one already announced.

### A run starts only when the readiness matrix allows it

Whether a run may start is a stated matrix, not an inference from whichever
values happen to be present. No panel blocks a start. Boards neither
discovered nor declared block it too — an unresolved question about the
pedal's boards is not the same as a decision that this pedal has none, and
the driver's own "skip docking" behaviour cannot tell those two apart, so the
workbench must. An explicitly confirmed empty board list is itself declared
intent: it is written to the manifest, means drill-only, and is never asked
again. Selecting boards requires a case model and a panel-reference
expression; selecting the assembly or report artefact requires at least one
board; and selecting no artefact at all requires an explicit confirmation
that the run checks only and writes nothing, because a run that quietly
writes nothing must not be indistinguishable from one that failed to.

## Consequences

`RunOptions` grows: four-rank resolution needs to carry not only each value
but the rank that supplied it, for every value the workbench exposes rather
than only the handful of flags the current command line has.

Two invalidation tables must now stay in step with the plan's steps, not one.
`_STEP_INPUTS` already records what a step reads; the new table records what
each step consumes of what earlier steps held. A step added to the plan is a
row added to both, and the two must agree with each other as much as either
agrees with the code, or the stale set — and the roadmap derived from it —
will disagree with what a retry actually does.

The manifest becomes a second thing a write step can fail at. Where a write
step previously either committed its targets or withheld all of them, it must
now also record, or fail to record, the declarations that produced them, per
half, at that same commit. A write that lands but whose manifest write does
not is a failure mode distinct from the artefact failures
[ADR-0001](0001-pipeline-and-emitter-adapters.md) and
[ADR-0005](0005-binary-emitter-payloads.md) already cover, and the driver and
its tests must account for it separately.

## Alternatives considered

A single frontier — marking every step after the earliest one a change
touches, by position rather than by consumption — was rejected. `targets` is
read at position four (`write case`) and again at position nine (`write
assembly`), so a frontier keyed to position would re-run every kernel step
between them — `read boards`, `match`, `seat`, `clash` — for a changed output
filename alone, none of which those steps read. That is minutes of kernel
work to answer a question no step downstream of the write steps ever asked,
and it costs exactly what the data-dependency table above exists to avoid.
