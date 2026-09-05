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
match several parts, in which case `--case` is required to choose one.

For example, the repository's `tar.ai` fixture matches both `1590B`/`1590B2`
(112.40 × 60.50 mm) and `1590BS` (112.00 × 60.50 mm). Use `--case 1590B` for
that fixture. Without it, the tool reports `ambiguous-enclosure`.

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

## Output files and failures

| Exit code | Meaning |
| --- | --- |
| `0` | No warnings or errors |
| `1` | Warnings or clash findings; requested outputs may be written |
| `2` | Processing errors; no requested outputs are written |
| `3` | Invalid arguments or an input/output failure |

Both tools validate the requested paths together before rendering. Two outputs
cannot refer to the same file, including paths that resolve through symlinks or
match after case and Unicode normalisation. Existing targets must be regular
files.

All requested outputs are rendered and staged before any target is replaced.
If a later write fails, previously replaced files are restored from their saved
bytes, and newly created targets are removed. Temporary files are cleaned up.

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

A hole extending beyond the reference outline is a warning. A hole extending
beyond the actual drilled face is an error and requires a supplied case model
to detect. Raised lettering can be drilled through; it is not treated as an
obstruction.

For an empty drill layer, check its name, top-level position and circle strokes.
The error reports how many paths were found, helping distinguish missing shapes
from shapes that weren't recognised as circles.
