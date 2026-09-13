# Command-line reference

See the [README](../README.md) for installation and a complete workflow. Both
commands also provide `--help` and `-v` / `--verbose`; verbose output shows what
each processing stage did.

## stompdrill

```bash
stompdrill PANEL.ai --emit excellon=out.drl --emit drawing-svg=out.svg
```

`PANEL.ai` is an Illustrator file containing drill circles and a panel outline.
Repeat `--emit FORMAT=PATH` to request several outputs in one run.

### Artwork and grid

| Option | Meaning | Default |
| --- | --- | --- |
| `--drill-layer NAME` | Layer containing the drill circles | `Drill` |
| `--reference-layer NAME` | Layer containing the panel outline | `Background` |
| `--grid MM` | Grid pitch for snapping hole positions | `0.25` mm |
| `--grid-warn MM` | Warn when snapping moves a hole further than this distance | One quarter of the grid pitch |
| `--form-depth N` | Number of nested PDF Form XObject levels to read | `12` |

Grid lengths are in millimetres. The grid pitch must be a whole number of
microns. A pitch finer than one micron is clamped to one micron and produces a
`grid-too-fine` warning. If the reader reaches the form-depth limit with more
artwork below it, it reports `nesting-truncated`; the deeper artwork is omitted.

### Drill sizes

| Option | Meaning | Default |
| --- | --- | --- |
| `--drill-standard NAME` | `metric` or `fractional` (sixty-fourths of an inch) | `metric` |
| `--drill-sizes CSV` | Use only these sizes from the selected standard | All sizes in the standard |
| `--no-drill-sizes CSV` | Exclude these sizes from the selected standard | No exclusions |

Supply comma-separated sizes in millimetres, including when using the
fractional standard. Each size must belong to the selected standard. Invalid
standards or sizes are usage errors, reported before the artwork is opened.

### Enclosure

| Option | Meaning | Default |
| --- | --- | --- |
| `--case PART` | Hammond 1590 base part number, such as `1590B` | Identify from the outline |
| `--case-model PATH` | Supplied STEP enclosure model; enables clearance checks and STEP output | No model |
| `--case-face SIDE` | Drill the `box` or `lid` | `box` |
| `--case-margin MM` | Clearance between the bit and the nearest non-flat feature | `1.0` mm |

The margin must be positive. The face and margin are validated even when no
model is supplied. The tool checks a declared part against the artwork; use
published top-view or backplate dimensions for the outline. A footprint can
match several parts, and the part is then either declared with `--case` or, when
nothing is declared, inferred from the `--case-model` filename.

Inference takes the model's stem, removes delimiters, uppercases it and accepts
the result only when it names one of the tied parts: `1590BB.stp` gives
`1590BB`. It passes the same verification a declared part does, though only on
the tie it was read to resolve, and a filename is a guess: where a declared
part that disagrees is an error, an inferred one leaves the ambiguity standing.

For example, the repository's `tar.ai` fixture matches both `1590B`/`1590B2`
(112.40 × 60.50 mm) and `1590BS` (112.00 × 60.50 mm). Use `--case 1590B` for
that fixture, or supply `--case-model 1590B.stp` and let the filename settle it;
the run then reports `inferred-enclosure`, naming the file it read the part
from. With neither a declaration nor a model whose filename names a tied part,
the tool reports `ambiguous-enclosure`.

Get a published Hammond model with:

```bash
python tools/fetch_case_model.py 1590BB
```

This repository helper downloads the model and prints its cached path. It is
separate from the installed packages. You can supply another existing STEP
model directly.

### Output formats

| Format | Output |
| --- | --- |
| `excellon` | Drill program |
| `drawing-svg` | Dimensioned SVG drawing |
| `drawing-pdf` | Dimensioned PDF drawing at 1:1 scale |
| `json` | Drill document for library use or `stompcollider` |
| `step` | Supplied enclosure model with the holes cut; requires `--case-model` |

Use `--title TEXT` to set the title in drawings and headers. It defaults to an
empty string.

PDF output uses the smallest ISO 5457 sheet that fits the panel: A4 portrait,
then A3, A2, A1 or A0 landscape. SVG output fits the drawing to its sheet.
There is no CLI `--scale` option; explicit drawing scales are a library feature.

## stompcollider

```bash
stompcollider drill.json board.stp \
  --case-model drilled.stp \
  --panel-reference 'RV*,SW*,D(3..4),!RV5' \
  --report report.json --assembly assembled.stp
```

The first argument is the drill document used to cut the enclosure. Follow it
with one or more board STEP files. Each file may contain several boards.

| Option | Meaning | Default |
| --- | --- | --- |
| `--case-model PATH` | Drilled enclosure STEP model | Required |
| `--panel-reference EXPR` | Designators of components that mount through the panel | Required |
| `--match-tolerance MM` | Tolerance for matching components to holes | Half the grid pitch recorded in the drill document |
| `--seat-pitch-max MM` | Coarse insertion-search step | `2.0` mm |
| `--seat-pitch-min MM` | Fine insertion-search step | `0.05` mm |
| `--report PATH` | Write the JSON report of placements and clashes | No report file |
| `--assembly PATH` | Write the STEP assembly | No assembly file |

The match tolerance and both search steps must be positive. The coarse step
must be at least as large as the fine step. If the drill document has no usable
grid pitch, supply `--match-tolerance`; the error message names the option. The
terminal report's `CASE` block shows the tolerance used.

The drill document carries the drilled face, so `stompcollider` has no
`--case-face` option. It also has no `--fit-clearance` option: drilling tolerance
belongs in the artwork and drilled model.

### Select panel components

Quote the filter expression so your shell passes it unchanged:

```bash
--panel-reference 'RV*,SW*,D(3..4),!RV5'
```

Terms are separated by commas and applied from left to right, starting with
nothing selected:

| Term | Selects |
| --- | --- |
| `RV1` | The exact designator `RV1` |
| `RV*` | Designators matching the glob, such as `RV1` and `RV12` |
| `D(3..4)` | `D3` and `D4`, including both ends of the range |
| `!RV5` | Removes `RV5` from the selection |

A later term can add a designator back. Empty terms, malformed or descending
ranges, and ranges larger than 10,000 values are usage errors.

### Placement and clashes

The tool matches the panel components to holes, then searches for an insertion
path from outside the open back. The board stops at its first contact with the
enclosure. The search uses the coarse step to find a bracket, then the fine step
to refine it; features below the search resolution may be missed.

Each board's placements are ranked by insertion shortfall, then by the number,
volume and depth of clashes with the enclosure. Among the best-seated
placements that clear the cavity, the assembly search chooses the combination
with the least interference between boards. Boards that never enter the
enclosure do not influence that choice. The lid does not affect insertion or
ranking, but interference with it is reported as a `closure` clash.

`--place N=X,Y,THETA` and `--pin N=RANK` appear in the parser but aren't supported
by this build. Both are validated and then rejected with a usage error. No
stage implements explicit placement, and clash processing can change placement
ranks.

## stompcad

```bash
stompcad PANEL.ai BOARD.stp --case 1590B --case-model 1590B.stp \
    --panel-reference 'RV*,SW*' --emit excellon=out.drl --emit report=report.json
```

`stompcad` runs `stompdrill` and `stompcollider` together as one invocation. It
drills `PANEL.ai`, then seats each `BOARD.stp` inside the case it has just
drilled and reports the clashes. Naming no board and finding none beside the
panel does not run the drill half alone: it leaves the run refusing to
start, because a question nobody has answered is not the same as an answer
of none. A drill-only run is declared, not merely omitted, by recording an
empty board list in the project file described below. Each of the run's steps
prints one line as it completes, so a piped run reads as a log of what
happened.

On a terminal, the run is instead drawn inline above the prompt. `--progress`
picks the starting level of detail -- `bar` draws one progress bar and the
deepest live branch, `steps` draws the nine steps and their outcomes, `tree`
expands each step into the divisions it reports. Pressing `v` cycles the
level while the run continues, without restarting anything. Pressing `q`
stops the run, which then exits `130`. While a question is on screen, `q`
abandons it instead -- the picker binds its own `q` -- and abandoning a
question likewise stops the run. `--progress` is ignored without a
terminal; a piped or redirected run always gets the plain step-line log.

| Option | Meaning | Default |
| --- | --- | --- |
| `--case PART` | Base designator the panel is drawn for, e.g. `1590B` | Identified from the footprint |
| `--case-model PATH` | STEP model of the enclosure; required to dock a board | None |
| `--panel-reference EXPR` | Which designators are panel references, e.g. `'RV*,SW*,D(3..4),!RV5'` | None |
| `--emit FORMAT=PATH` | Write an artifact; repeatable | Nothing is written |
| `--progress bar\|steps\|tree` | Starting detail level for the inline run; `v` cycles it | `bar` |
| `--promote-warnings` | Raise every warning to an error, so a resolvable one can be asked about | Off |

`--emit` accepts either half's formats: `drawing-pdf`, `drawing-svg`,
`excellon`, `json` and `step` from the drill half, `report` and `assembly`
from the dock half. Every requested target is validated together before
anything is opened for writing, whether it was typed here or declared in the
project file: a name neither half can render is a usage error naming it, and
two targets naming one file are refused exactly as both tools refuse them.

Neither fact docking needs has a default. `--panel-reference` names the
components chosen for this particular pedal, and `--case-model` supplies the
enclosure the boards are seated in; naming a board without either is a usage
error rather than a guess.

When the footprint matches more than one part, no `--case` is declared and a
`--case-model` is supplied, the part may be inferred from the model's filename:
a model named `1590B.stp` settles a tie the artwork alone leaves open, provided
that name is one of the tied parts. A run that inferred the part records an
informational finding naming the model it took the name from, and asking for
`--case` to state it instead, so an enclosure nobody declared is never
chosen silently.

An error anywhere stops the whole run. The drill half's errors withhold its
artefacts and leave the boards unread, and the dock half's withhold the report
and the assembly. Both halves name what they did not write.

A run stopped before it finishes exits `130`, and nothing it was about to write
survives. Every artefact is rendered before any target is touched, so at the
moment a run can be stopped there is nothing half-written on disk to remove.

### The project file

A pedal is a project, and the values that describe it belong to the panel
rather than to one invocation. `stompcad` reads them from a file beside the
artwork, named from its stem: `tar.ai` is described by `tar.stompcad.json`.
Moving the pair together moves the project; there is no other state, and
nothing outside that directory is consulted.

The file is a JSON object holding a schema `version` and one object per group
of settings — `artwork`, `enclosure`, `drilling`, `boards` and `output` — each
naming the same values the options above do:

```json
{
  "version": 1,
  "enclosure": { "case": "1590B", "case_model": "1590B.stp" },
  "boards": { "boards": ["tar-pcb.stp"], "panel_reference": "RV*,SW*" },
  "output": { "targets": { "excellon": "tar-case.drl" } }
}
```

Paths are stored relative to the file, so a project that is copied or shared
still works. A declared value beats a default and beats anything the run
works out for itself; an option typed on the command line beats the file. A
value the file already holds is used and left untouched — a one-off
invocation cannot quietly redefine the project — and where the two disagree
the run says so rather than choosing silently.

The empty declaration matters as much as a full one. `"boards": {"boards": []}`
states that this pedal has no board to dock, which is what a drill-only run
needs: finding no board beside the panel is not the same answer as being told
there is none, so a run given neither refuses to start rather than quietly
drilling alone.

A key this build does not recognise is reported and ignored, and left in the
file, so a project written by a later version still opens here. A file that
cannot be read at all — malformed JSON, or something that is not an object —
is a usage error naming the file: a project whose declarations cannot be read
must never be run under values that look like the builder's own.

A key this build does recognise must hold the shape that key takes — a string,
a number, a whole number, a list of paths, or the `targets` object of format
name to path — and one that does not is the same usage error, naming the key
and the shape it wants. It is reported before the artwork is opened, so a
mistyped value never stops a run part-way through. A boolean is not a number
here: `"form_depth": true` is refused rather than read as `1`, and `null` is
refused where the key holds no null — omitting a key is how a project declares
nothing about it.

A value of the right shape must also be one the tool that consumes it accepts.
The grid and its warning distance, the clearance margin, the match tolerance
and the two seat steps are checked by the same code `stompdrill` and
`stompcollider` run from their own command lines, so a project cannot start a
run under a number either tool would refuse. These are reported before the
artwork is opened too, naming the key that carried the value.

This build does not yet write the file. Until it does, a project is
hand-authored.

### Pickers

A gap the run can resolve asks instead of refusing. On a terminal, an error
carrying a resolvable code puts a picker on screen: the prompt is the
diagnostic's own message, the candidates are the finite set the tool itself
computed, and the step that stopped runs again under the answer. That step is
credited once it succeeds, so it leaves one line in the record rather than two.

Two gaps ask. A tie between enclosure parts offers the tied parts, the same
answer `--case` would have given. A board whose `--panel-reference` expression
admits none of its designators offers that board's own designators, and the
answer widens the expression rather than replacing it, so resolving one board
cannot empty another. Every other error remains a refusal: a code with no
picker is never turned into a question.

`--promote-warnings` raises every warning to an error before that check runs,
which is what would let a warning reach a picker at all. Being an error is
necessary and not sufficient, and both resolvable codes are errors already, so
the flag has nothing to promote into a question until a warning carries one.

Without a terminal there is nobody to ask. Rather than prompting where no
answer can arrive, the run exits `3` naming the question it needed answered --
on a pipe, a redirect, a dumb terminal or a CI runner alike.

### Exit codes

| Exit code | Meaning |
| --- | --- |
| `0` | No warnings or errors |
| `1` | Warnings or clash findings; requested outputs may be written |
| `2` | Processing errors; no requested outputs are written |
| `3` | Invalid arguments, an unrecognised `--emit` format, an input/output failure, or a question with no terminal to ask it on |
| `130` | The run was cancelled |

The code is the worse of the two halves' findings, so one run reports one
status. `130` is the shell's own convention for a process ended by `SIGINT`:
`128` plus the signal number `2`, the same code a shell reports for any command
stopped with Ctrl-C — so a script already checking for that convention needs no
special case for `stompcad`. It is reserved for a run the user stopped; no
other path produces it. On a terminal that status is now also reachable by
pressing `q`, not only by the signal.

## Output files and failures

| Exit code | Meaning |
| --- | --- |
| `0` | No warnings or errors |
| `1` | Warnings or clash findings; requested outputs may be written |
| `2` | Processing errors; no requested outputs are written |
| `3` | Invalid arguments or an input/output failure |

All three commands validate the requested paths together before rendering. Two outputs
cannot refer to the same file, including paths that resolve through symlinks or
match after case and Unicode normalisation. Existing targets must be regular
files.

All requested outputs are rendered and staged before any target is replaced.
If a later write fails, previously replaced files are restored from their saved
bytes, and newly created targets are removed. Temporary files are cleaned up.
`stompcad` writes through the same mechanism, so a run of either tool and the
same run under `stompcad` fail the same way.

Under `stompcad`, exit `2` binds each half's own outputs. The drill half commits
its targets when its write step completes, before a board is read, so a run
whose dock half errors exits `2` having written the drill artefacts and none of
the dock ones. Those artefacts describe what the drill half computed; the exit
code, not the contents of the output directory, is the run's status. See
[ADR-0013](adr/0013-the-orchestrator-s-presentation-and-composed-run.md).

Recovery can fail if another process changes a target during the run or if a
restoring write fails. The tools do not lock the output set or guarantee
recovery after power loss. See [ADR-0001](adr/0001-pipeline-and-emitter-adapters.md)
and [ADR-0005](adr/0005-binary-emitter-payloads.md) for the write protocol and its
limits.

### stompdrill diagnostics

Processing errors include `unknown-diameter`, `ambiguous-enclosure`,
`unverifiable-enclosure`, `unmatched-enclosure`, `wrong-enclosure`,
`hole-off-face`, `hole-through-boss`, `hole-obstructed` and `wrong-case-model`.

Warnings include `grid-too-fine`, `grid-ambiguous`, `hole-outside-outline`,
`nesting-truncated`, `case-orientation-unverifiable` and `off-size`.

Informational findings include `inferred-enclosure`, which names the case model
a tied part was taken from and asks for `--case` to state it instead. They
describe what the tool decided rather than anything to fix, so they change
neither the exit code nor what is written.

A hole extending beyond the reference outline is a warning. A hole extending
beyond the actual drilled face is an error and requires a supplied case model
to detect. Raised lettering can be drilled through; it is not treated as an
obstruction.

For an empty drill layer, check its name, top-level position and circle strokes.
The error reports how many paths were found, helping distinguish missing shapes
from shapes that weren't recognised as circles.
