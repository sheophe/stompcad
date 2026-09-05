# stompcad

Create drill files and drawings from your guitar-pedal artwork, then check
whether your boards fit inside the enclosure.

[![CI](https://github.com/sheophe/stompcad/actions/workflows/ci.yml/badge.svg)](https://github.com/sheophe/stompcad/actions/workflows/ci.yml)

stompcad includes two command-line tools:

- **`stompdrill`** reads Adobe Illustrator artwork and creates an Excellon drill
  file, dimensioned drawings and a JSON drill document. With a STEP model of your
  enclosure, it can also check hole clearance and create a drilled model.
- **`stompcollider`** positions your board models inside the drilled enclosure
  and reports clashes.

This is a personal project built around Hammond's 1590 enclosure family. It's
used on real pedals, and the command-line interface is still evolving.

## Install

You need Python 3.10 or later and `uv`. From a terminal:

```bash
git clone https://github.com/sheophe/stompcad.git
cd stompcad
uv venv
uv sync --all-packages
source .venv/bin/activate
```

STEP support is included. The geometry libraries make this a large installation;
`cadquery-ocp` also brings in vtk and matplotlib.

## Prepare your artwork

In Illustrator, create two top-level layers:

| Layer name | What to draw |
| --- | --- |
| `Drill` | One circle per hole, at the position and diameter you want drilled |
| `Background` | The panel outline, at the enclosure's published top-view or backplate dimensions |

Use `--drill-layer` and `--reference-layer` if your layers have different names.

**Give the drill circles a stroke.** Shapes with neither fill nor stroke are
left out of the saved PDF data, so the tool cannot read them.

**Use the Ellipse tool to draw each hole.** Hold Shift, or enter equal width and
height values, to make a circle. Rotated circles work too. Ellipses, rounded
rectangles, compound shapes and traced outlines aren't recognised as holes.

**Keep both layers at the top level.** The reader cannot recover sublayers or
object names from the saved file. It uses layer names to identify the holes and
outline.

**Use the enclosure's published outline dimensions.** The smaller drilled face
has different dimensions. The tool uses the largest non-circular path on the
reference layer to identify the enclosure and set the coordinate origin.

Save the file as `.ai` with PDF compatibility enabled. Illustrator doesn't need
to be running when you use `stompdrill`.

## Generate drill files

```bash
stompdrill PANEL.ai \
  --emit excellon=out.drl \
  --emit drawing-svg=out.svg \
  --emit json=out.json
```

This creates a drill program, an SVG drawing and a JSON drill document. Add
`--emit drawing-pdf=out.pdf` for a drawing at 1:1 scale.

Hole positions snap to a grid, which defaults to 0.25 mm. Diameters snap to the
selected drill standard: metric by default, or fractional sixty-fourths of an
inch with `--drill-standard fractional`. The panel outline is matched against
the Hammond catalogue. If several enclosures match, specify the intended part
with `--case`, for example `--case 1590B`.

## Check hole clearance and create a drilled model

Supply a STEP model to check the holes against the enclosure's walls, ribs and
screw bosses. The repository includes a helper for downloading Hammond models:

```bash
python tools/fetch_case_model.py 1590BB
stompdrill PANEL.ai --case 1590BB \
  --case-model ~/.cache/stompcad/cases/1590BB.stp \
  --emit step=drilled.stp --emit json=drill.json
```

The helper prints the cached model's path. You can also supply a model you
already have. `stompdrill` cuts the holes into that model; it doesn't generate
the enclosure itself.

Without `--case-model`, you can still create drill files and drawings, but hole
clearance against the enclosure's solid geometry isn't checked.

## Check whether the boards fit

Use the drill document and drilled model from the previous step, along with a
STEP model of your board:

```bash
stompcollider drill.json board.stp \
  --case-model drilled.stp \
  --panel-reference 'RV*,SW*,D(3..4),!RV5' \
  --report report.json --assembly assembled.stp
```

`--panel-reference` selects the components that mount through the panel, such as
pots, switches and jacks. Choose these for your pedal; there is no default. The
example includes `RV*`, `SW*`, `D3` and `D4`, then excludes `RV5`. See the
[filter syntax](docs/CLI.md#select-panel-components) for details.

The tool aligns each board outside the open back and moves it towards the panel
until it first meets the enclosure. When several placements are possible, it
prefers the ones that insert furthest, then those with the least interference
between boards. The lid is excluded during insertion, but clashes with it are
reported afterwards.

The terminal shows the findings. `report.json` records the placements and
clashes, and `assembled.stp` lets you inspect the assembly in a CAD viewer. Pass
several board files after `drill.json` to check them together.

Use the findings to adjust your design. If a bushing is wider than its hole, the
board stops short. Include the required drilling tolerance in your artwork;
the tool measures the supplied geometry without adding an allowance.

## Understand the result

Both tools use these exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Completed without warnings or errors |
| `1` | Completed with warnings or clash findings |
| `2` | Processing errors; no requested output files are written |
| `3` | Invalid arguments or an input/output failure |

Warnings allow output files to be written. Processing errors prevent all
requested outputs. If a write fails, the tools attempt to restore any files
already replaced; see [output handling](docs/CLI.md#output-files-and-failures)
for the limits of that recovery.

If the drill layer comes back empty, check that its circles have a stroke and
that the layer is at the top level. An error that reports paths but no circles
usually means the shapes weren't recognised as circular.

## More documentation

- [Command-line reference](docs/CLI.md): options, output formats and diagnostics.
- [Glossary](docs/GLOSSARY.md): enclosure, drilling and board-fit terminology.
- [Architecture overview](docs/ARCHITECTURE.md): packages and processing steps.
- [Contributing](CONTRIBUTING.md): development commands and testing guidance.
- [Architecture decisions](docs/adr/): decisions and their reasons.
- [Foundation](docs/FOUNDATION.md): the formal model behind the processing and
  output checks.

## Licence

MIT. See [LICENSE](LICENSE).

Downloaded Hammond enclosure models are published by Hammond Manufacturing and
aren't part of this project. The [catalogue data](docs/parts/README.md) comes
from their public datasheets.
