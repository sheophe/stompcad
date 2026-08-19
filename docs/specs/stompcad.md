# stompcad — product-level specification

**Status:** pre-spec. Describes what `stompcad` is and is responsible for.
Libraries, interfaces and internal architecture are decided from this document,
not in it.

## Purpose

`stompcad` is the user-facing tool. It turns one Illustrator file into everything
needed to build a pedal: a drill programme for the CNC, a drawing to work from,
a model of the drilled enclosure, an assembled model with the boards seated, and
a machine-readable record of the run.

`stompdrill` and `stompcollider` are deliberately not user-facing. They are precise,
they refuse ambiguous input, and they expect their arguments to be correct.
`stompcad` is the layer that makes that pleasant — it resolves what it can, asks
about what it cannot, and remembers the answers.

The target is a single argument:

```
stompcad tar.ai
```

Everything else is optional, and anything missing is either taken from the
project's manifest or asked for.

## Scope

`stompcad` orchestrates, configures and reports. It computes nothing about
geometry. Every geometric decision belongs to `stompdrill` or `stompcollider`, and
`stompcad` must not develop opinions about drill sizes, hole positions, clearances
or placements.

## Command surface

| | |
| --- | --- |
| `stompcad PANEL.ai` | The whole pipeline. The happy path. |
| `stompcad drill` | Drilling only. |
| `stompcad dock` | Docking only, against an existing drilled case. |
| `stompcad cache` | Manage the enclosure model cache. |
| `stompcad doctor` | Check and repair the environment. |
| `stompcad help`, `--help` | Commands and arguments. |

`drill` and `dock` exist because only part of the input usually moves — a board
gets re-exported, artwork does not. They are not optimisations `stompcad` applies
on its own: **an assertion by the caller is a decision, an inference by the tool
would be state.**

There is deliberately no `init`. The bare form fills manifest gaps as it goes, so
a separate initialiser would be a second way to do one thing. Inspecting the
resolved configuration is `--dry-run` on the bare form.

## Configuration

**Precedence: argument, then manifest, then default.** An explicitly supplied
argument is expected to win. A manifest exists so that its values beat defaults
and suppress prompting — that is the whole reason for it.

**The manifest fills gaps and is never overwritten.** A value absent from it and
supplied by argument or prompt is written in; otherwise the manifest never
populates and the one-argument invocation never arrives. A value already present
and contradicted by an argument is used for that run and left untouched, so a
one-off `--grid 0.5` cannot permanently redefine a project.

**Every run reports where each value came from** — `grid 0.5 from the command
line, manifest says 0.25`. Artefacts must never be quietly attributable to the
wrong settings.

The manifest holds declared intent only: no hashes, no timestamps, no record of
previous runs.

## Files

One project, one `.ai` file, one manifest beside it. Artefacts are written to
the same directory, named from the source stem.

| | |
| --- | --- |
| `tar.ai` | input — artwork |
| `tar-pcb.stp` | input — board, one or more |
| `tar.stompcad.json` | the manifest |
| `tar-case.drl` | Excellon, for the CNC |
| `tar-case.pdf` | drawing sheet, ISO 5457 at 1:1 |
| `tar-case.stp` | the drilled enclosure |
| `tar-assembly.stp` | boards seated in the enclosure |
| `tar.stompcad` | the run record |

Two rules generate this, and both matter because these names share a directory
with files other tools produce:

- **A suffix names the subject** — `-case` for everything about the enclosure,
  `-assembly` for the docked result, `-pcb` for a board. Never the operation:
  mixing subject and operation leaves the next artefact with no rule to follow.
- **Suffix only where the extension would be ambiguous.** `.stp` appears three
  times, and `.pdf` and `.drl` collide with KiCad's own exports —
  `tar-schematic.pdf`, `tar.drl` from a Gerber bundle. `.stompcad` and `.stompcad.json`
  are ours alone and stay bare.

All of these are defaults. Any path may be given by argument or prompt, and the
answer goes into the manifest.

`tar.stompcad` is one file for the whole run, internally sectioned, with every
section optional so any kind of run can be recorded in it. The protocol is a
technical-spec question. **No consumer is built for it yet** — it is written
because a run should leave a machine-readable trace, not because something reads
it today.

## Orchestration

`stompcad` imports `stompdrill` and `stompcollider` as **libraries**. It never shells out
and never parses their output.

This is not a preference. `stompdrill` reports ambiguity as structured data — an
`ambiguous-enclosure` diagnostic carrying its candidate footprints — and that
structure is precisely what makes an interactive picker possible. Through a
subprocess it would be flattened to a string and a number, and `stompcad` would be
reconstructing by regex the answer it had been handed.

The hole pattern passes from `stompdrill` to `stompcollider` in memory. It remains
available as an explicit artefact for anyone running `stompcollider` standalone, but
`stompcad` has no reason to write a file it immediately reads back.

`stompcad` depends on `stompgeom` only for lengths it reports. It does no geometry.

## Interaction

**A picker resolves ambiguity; it never overrides a refusal.**

Pickers appear where a tool has identified a finite candidate set and genuinely
cannot choose:

- an ambiguous enclosure footprint — the case that motivated the whole layer;
- which face is drilled;
- several valid placements from `stompcollider`;
- an empty or both-faced panel-reference group.

No picker appears where a tool has *rejected* something — `unknown-diameter`,
`hole-off-face`, `hole-through-boss`. Those are faults in the design, and a
prompt offering "no drill matches ⌀6.9 mm; use ⌀7.0?" would let the friendly
layer quietly undo a refusal `stompdrill` made deliberately, at the exact moment
that refusal is protecting a piece of aluminium. The distinction is that a
picker chooses between answers the tool computed; an override invents one the
tool declined to give.

**Non-interactive is first-class, not a fallback.** A manifest-complete run
proceeds to completion without prompting. A genuine gap with no terminal exits
with the usage code and names what was missing, rather than prompting into the
void. Interactivity is how gaps get filled when a human is present — it is not a
property of the tool.

"Without prompting" does not mean without output. Every run states what it did
and what it produced.

## The cache

`stompcad` owns the enclosure model cache outright. `tools/fetch_case_model.py`
moves here from `stompdrill`, and no copy is left behind — acquiring a model was
never `stompdrill`'s job.

Models are cached in an XDG-aware location, keyed by part designator, and
**never evicted automatically**. They are large and cheap to keep; deleting
someone's cache to reclaim disk is not a service a build tool should perform.

A cache miss with no network is a usage-code exit naming the part and the URL, so
the model can be fetched by hand on a machine that has one.

## doctor

`stompcad doctor` checks the environment and repairs it. Run inside a virtual
environment it verifies and installs dependencies there; run outside one it
creates a virtual environment first.

This exists because `stompgeom` depends on OpenCASCADE unconditionally, which
pulls vtk and matplotlib transitively. "Just install it" stopped being a
one-liner a user could be expected to get right, so environment setup became
part of the tool's job.

It is the only part of `stompcad` that reaches outside the project directory and
modifies the machine. That authority is deliberately confined to one subcommand
that must be asked for by name.

## Constraints

**State is project configuration, never historic recall.** `stompdrill` and
`stompcollider` are stateless input-to-output pipelines. `stompcad` is a stateful
orchestrator, and its only state is the manifest. This rules out build caches,
artefact provenance chains, undo, and "what changed since last time".

**No change detection. Every run runs the whole pipeline.** A baseline for
comparison would be derived state. If docking proves slow, the answer is faster
docking or an explicit `drill`/`dock` invocation — not a cache.

**Artefacts are overwritten freely.** No refusal, no versioning, no run record
beyond `tar.stompcad`. The user has version control and decides what belongs in it.

**The exit-code contract is shared:** `0` clean, `1` findings, `2` error, `3`
usage or IO. `stompcad` reports the most severe outcome of the stages it ran.

**Installs and tests alone.**

## Out of scope

- **KiCad project stubs from Illustrator artwork.** A real `stompcad`
  responsibility, but it shares no machinery with the drill-and-dock route and
  belongs to a separate effort.
- **Any geometric decision.** Those belong to `stompdrill` and `stompcollider`.
- **Overriding a refusal**, by any route, including a flag.

## Left to the technical specification

- The manifest's schema.
- The `tar.stompcad` section protocol.
- The prompt and picker presentation.
- What `doctor` checks, and how it reports a repair it cannot make.
