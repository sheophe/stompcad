# stompcad

Turn guitar-pedal panel artwork into fabrication artefacts, then check that the
boards actually fit inside the enclosure you plan to drill.

[![CI](https://github.com/sheophe/stompcad/actions/workflows/ci.yml/badge.svg)](https://github.com/sheophe/stompcad/actions/workflows/ci.yml)

Two command-line tools, sharing one geometry kernel:

- **`stompdrill`** reads drill geometry from an Adobe Illustrator file and emits
  an Excellon program, a dimensioned drawing, a JSON drill document, and — given
  a model of the enclosure — a STEP file of that enclosure with the holes cut.
- **`stompcollider`** takes that drill document, the drilled enclosure and one or
  more board models, seats each board on the holes its panel-mounted parts pass
  through, and reports every place something clashes.

The output is used to drill aluminium, so every artefact from one invocation
must agree with every other. That constraint shapes most of the design.

## Status

A personal project, built around Hammond's 1590 enclosure family. It does real
work on real pedals, but it is not a general-purpose CAD package and makes no
attempt to be one. Interfaces change when the domain argues for it.

## Installing

Python 3.10 or later.

```bash
git clone https://github.com/sheophe/stompcad.git
cd stompcad
uv venv
uv sync --all-packages
source .venv/bin/activate
```

That is the whole install — there is no optional extra. The `cadquery-ocp`
geometry kernel is an unconditional dependency, so the STEP features arrive with
the command above. It is a large install: vtk and matplotlib come along
transitively.

## Preparing the artwork

`stompdrill` reads an ordinary Illustrator file, but it only recognises geometry
drawn a particular way. Two layers matter:

| Layer | Default name | Holds |
| --- | --- | --- |
| drill | `Drill` | one circle per hole, at the position and diameter you want drilled |
| reference | `Background` | the panel outline, which fixes the coordinate frame and origin |

Rename them with `--drill-layer` and `--reference-layer` if you prefer.

Four things decide whether your artwork reads:

**Give the drill circles a stroke.** Illustrator omits paths with neither fill
nor stroke from the PDF stream entirely, so an unpainted circle is not merely
ignored — it never reaches the file. This is the single most common reason a
layer comes back empty.

**Draw true circles.** A hole must be four cubic Béziers with equal radii and
consistent control-point placement — what the Ellipse tool produces with Shift
held, or with an equal width and height typed into its dialog. Rounded
rectangles, ellipses, compound shapes and traced outlines all read as
non-circular and are refused rather than guessed at. Recognition is
rotation-invariant, so a rotated circle is still a circle.

**Keep both layers at the top level.** Illustrator's sublayers are not
recoverable from the saved file, so a drill layer nested inside another layer
cannot be found. Object names are not recoverable either — the layer is the only
channel through which artwork tells the tool what a shape is for.

**Draw the outline at published enclosure dimensions.** The reference outline is
the largest non-circular path on its layer, and it is matched against a
catalogue of Hammond footprints to identify which enclosure you drew for. Use
the published top-view or backplate dimensions, not the smaller drilled face.

Save as `.ai` in Illustrator's normal way — its native save embeds the
PDF-compatible stream that gets read, and Illustrator need not be running.

If something is wrong, the error says which of the above it was: a layer that
was found but held no circles reports how many paths it did hold, which
distinguishes "nothing was painted" from "nothing was circular".

## Drilling a panel

Draw your holes as circles on one layer and the panel outline on another, then:

```bash
stompdrill PANEL.ai \
  --emit excellon=out.drl \
  --emit drawing-svg=out.svg \
  --emit json=out.json
```

Positions snap to a declared grid, diameters snap to a drill standard (metric or
fractional sixty-fourths), and the outline is matched against a catalogue of
Hammond footprints so the tool knows which enclosure you drew for. Anything it
cannot resolve is a diagnostic rather than a guess.

To cut the holes into a real enclosure and check clearance against its ribs,
bosses and lettering, supply a model:

```bash
python tools/fetch_case_model.py 1590BB     # downloads and prints the cached path
stompdrill PANEL.ai --case 1590BB \
  --case-model ~/.cache/stompcad/cases/1590BB.stp \
  --emit step=drilled.stp --emit json=drill.json
```

`stompdrill` never synthesises an enclosure. It reads one you supply, to verify
clearance and to cut holes it has already decided on. `tools/fetch_case_model.py`
fetches published Hammond models; it is a convenience, not part of the package.

## Seating the boards

```bash
stompcollider drill.json board.stp \
  --case-model drilled.stp \
  --panel-reference 'RV*,SW*,D(3..4),!RV5' \
  --report report.txt --assembly assembled.stp
```

`--panel-reference` names the designators that mount through the panel — the
pots, switches and jacks whose shafts pass through your holes. There is no
default, because which parts those are is a fact about your pedal.

Each board is then inserted the way you would insert it by hand: aligned outside
the open back, advanced along the panel normal, and stopped where it first meets
metal. Where several seatings are possible, the one that goes furthest in wins,
and among those the one whose boards foul each other least.

**It resolves nothing.** A clash is the output, not a failure — seeing the
interference is the entire point. If a bushing is drawn wider than the bore it
must pass, `stompcollider` reports the board stopping short rather than quietly
letting it through. Drilling tolerance belongs in your artwork, not in an
allowance the tool applies to a model it is measuring.

## Exit codes

Both tools use the same contract:

| Code | Meaning |
| --- | --- |
| `0` | clean |
| `1` | warnings present |
| `2` | errors |
| `3` | usage or IO failure |

Any error withholds **every** requested artefact. A run that fails leaves each
existing output exactly as it was.

## How it fits together

```
PANEL.ai ──▶ AiPdfSource ──▶ quantise() ──▶ DrillData ──▶ Pipeline ──▶ Emitters
                                                             │
                                             drill.json ◀────┘
                                                  │
BOARD.stp ──────────────────────────────────▶ stompcollider ──▶ report, assembly
```

Four packages, in dependency order:

| Package | Holds |
| --- | --- |
| `stompmodel` | the values every tool exchanges: branded lengths, drill data, diagnostics, protocols |
| `stompgeom` | the OpenCASCADE layer — reading, writing, intersecting and measuring solids |
| `stompdrill` | artwork to fabrication artefacts |
| `stompcollider` | boards into a drilled enclosure |

Each installs and passes its own tests alone. `stompcollider` reaches the kernel
only through `stompgeom`, and a test enforces it.

Measurements enter as millimetre floats and become integer nanometres at one
boundary; every canonical length is exact from there on. Two inputs describing
the same geometry produce byte-identical artefacts whatever order their elements
appear in — no rule consults input order.

## Documentation

- **[`docs/adr/`](docs/adr/)** — the authority for every architectural decision.
  Start with [ADR-0001](docs/adr/0001-pipeline-and-emitter-adapters.md) for the
  processing boundaries and [ADR-0003](docs/adr/0003-quantisation-boundary-and-ordering.md)
  for why quantisation happens where it does.
- **[`docs/FOUNDATION.md`](docs/FOUNDATION.md)** — the abstract model every tool
  here is an instance of, so that correctness obligations can be derived rather
  than listed.
- **[`docs/GLOSSARY.md`](docs/GLOSSARY.md)** — the domain vocabulary, for terms
  two people could reasonably read two ways.
- **[`CLAUDE.md`](CLAUDE.md)** — the rules binding contributions, and the fullest
  description of the command-line contract.

Some documents referenced from commit messages are working records kept out of
this repository: implementation plans, the backlog, and internal specifications.
The ADRs carry the decisions that survived.

## Development

No single command proves everything — the root `testpaths` covers only
`stompdrill`, and four test packages cannot share one interpreter:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
```

Lint and types:

```bash
ruff check packages tools
mypy packages
cd packages/stompgeom && uv run --no-sync mypy      # and likewise for the others
```

Two suites are opt-in. `--hammond` runs `stompdrill`'s kernel tests against real
Hammond models fetched at run time; `--boards` runs `stompcollider`'s against a
committed board fixture. Neither is a kernel-availability switch — the kernel is
always required, so failing to import it is a failure rather than a skip.

Tests are written first, and a test that cannot fail is not evidence: a check
that could pass by finding nothing has to be shown failing on a deliberate breach
before it counts. `CLAUDE.md` states the rest.

## Licence

MIT — see [LICENSE](LICENSE).

Hammond enclosure models fetched by `tools/fetch_case_model.py` are published by
Hammond Manufacturing and are not part of this project. Dimensional data in
`docs/parts/` is transcribed from their public datasheets.
