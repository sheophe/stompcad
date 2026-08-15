# aidrill — specification

**Version:** 2.0 · **Status:** implemented

Version 2.0 records the enclosure-and-drill-quantisation work: diameters are quantised
onto a declared drill standard instead of being clustered, the reference outline is
identified against the Hammond 1590 catalogue, an unmatched diameter is now an ERROR that
drops the hole, and a run with any ERROR writes no artifacts at all. The reasoning is in
`docs/adr/0003-domain-quantisers.md`.

---

## 1. Purpose and single responsibility

`aidrill` extracts drill data from an Adobe Illustrator `.ai` file and emits it in a
chosen output format.

That is the whole responsibility. It does **not** model enclosures in 3D, read KiCad,
check clearances, or know what a potentiometer is. Those belong to the wider toolchain
and will consume `aidrill` as a library.

Stated as one sentence, which is the SRP test: *"aidrill turns panel artwork into drill
data."* Anything that doesn't serve that sentence goes elsewhere.

---

## 2. Architecture

Three roles, three abstractions, one direction of flow:

```
  ┌────────┐   RawGeometry   ┌──────────────────────┐   DrillData   ┌─────────┐
  │ Source │ ──────────────▶ │  Pipeline of Stages  │ ────────────▶ │ Emitter │ ──▶ artifact
  └────────┘                 └──────────────────────┘               └─────────┘
   .ai / PDF                  snap · snap-diameters ·                excellon
   (future: SVG,              dedupe · identify-enclosure ·          drawing-svg
    DXF, KiCad)               sort                                   json
                                                                     (future: dxf, ai)
```

**The pipeline is universal.** Snapping, diameter quantisation, deduplication and
enclosure identification happen **once**, before any emitter sees the data. No emitter may re-derive them. This is the
central constraint of the design: an earlier version clustered diameters inside the
Excellon writer, which meant the drawing and the Excellon file could legitimately
disagree about how many distinct hole sizes existed. Preprocessing is not an emitter
concern.

### 2.1 SOLID obligations

| Principle | How it binds here |
|---|---|
| **SRP** | One reason to change per module. A stage transforms; an emitter serializes; a source parses. A stage that formats output, or an emitter that rounds a number, is a bug. |
| **OCP** | Adding an emitter must require **zero** edits to `Pipeline`, the CLI dispatch or any sibling: emitters self-register and `--emit FORMAT=PATH` resolves through the registry. The claim holds in full only for an emitter that takes no options of its own — one needing its own CLI flags still forces a `cli.py` edit, and ADR-0001 records that limit honestly. A stage is different by design: order is the one thing a stage may not self-declare (LSP), so inserting it in `cli.build_pipeline` is the integration point, not a leak. |
| **LSP** | Every `Stage` is substitutable for any other; same for `Emitter` and `Source`. No stage may require a specific predecessor. |
| **ISP** | `Source`, `Stage` and `Emitter` are three separate protocols. Emitter-specific options live in emitter-specific dataclasses, never in a shared options bag. |
| **DIP** | `Pipeline` depends only on the `Stage` protocol. Only `cli.py` may name concrete classes. |

### 2.2 DRY obligations

- **One canonical frame.** Millimetres, Y-up, origin at the centre of the reference
  outline. Every emitter that wants something else converts on output via the shared
  `DrillData.with_origin()`; nobody hand-rolls the arithmetic.
- **One diagnostics list.** Stages append; emitters render. The drawing's NOTES block and
  the CLI's warnings are two renderings of the same data, not two computations.
- **One circle-fitting routine**, in `geometry`, used by every source.

---

## 3. Canonical data model

Immutable value objects. Every transform returns a new instance.

```python
Hole:
    x: float          # mm, canonical frame
    y: float          # mm, Y up
    diameter: float   # mm, nominal (a size the declared drill standard holds)
    raw: RawHole      # provenance: as-measured values, never mutated
    index: int        # stable identity, required, assigned in source order

RawHole:
    x: float; y: float; diameter: float

RawOutline:
    width: float; height: float

ReferenceOutline:
    width: float; height: float          # mm, nominal (post-snap to the catalogue)
    centre_x: float; centre_y: float     # mm, in source space
    raw: RawOutline                      # provenance: as-measured, never mutated

EnclosureMatch:
    family: str                          # "Hammond 1590"
    length_mm: int; width_mm: int        # the catalogue's own whole millimetres
    candidates: tuple[str, ...]          # every base part sharing the footprint
    rotated: bool                        # the panel is that footprint turned 90°
    selected_part: str | None            # only ever what the operator declared

Diagnostic:
    severity: Severity                   # INFO | WARNING | ERROR
    code: str                            # stable machine key, e.g. "duplicate-hole"
    message: str                         # human sentence, no trailing newline
    location: tuple[float, float] | None # canonical mm, if the finding has a place
    data: tuple[tuple[str, float|int|str], ...]   # machine-readable payload

StageRun:
    name: str                            # the stage's ClassVar name
    parameters: tuple[tuple[str, ParameterValue], ...]   # *effective* values

DrillData:
    holes: tuple[Hole, ...]
    reference: ReferenceOutline | None
    diagnostics: tuple[Diagnostic, ...]
    source: SourceInfo                   # path, layer names, producer string
    processing: tuple[StageRun, ...]     # what the pipeline actually did, in order
    enclosure: EnclosureMatch | None     # which catalogue case the panel is for
```

`DrillData` is frozen and exposes:

- `with_holes(holes)` → new instance
- `with_diagnostics(*diags)` → new instance, diagnostics appended
- `with_processing(*runs)` → new instance, stage records appended (never replaced)
- `with_enclosure(match)` → new instance, enclosure **replaced** (never appended)
- `with_origin(origin)` → new instance, holes translated; `Origin.CENTRE | LOWER_LEFT`
- `tools()` → ordered mapping `{diameter: tool_number}`, ascending, **1-based**
- `tool_counts()` → `{diameter: how many holes use it}`
- `rows(tolerance)` → holes grouped by Y, descending, for per-row chain dimensions
- `last_run(stage_name)` → the most recent `StageRun` for that stage, or `None`

`tools()` living on the model, not in the Excellon emitter, is deliberate: the drawing's
hole schedule and the Excellon tool table must never disagree.

Four fields exist purely to stop information going stale, and each was added after
something downstream had already re-derived it:

- **`Hole.index`** is the hole's identity. Diagnostics refer to holes by it. Coordinates
  go stale the moment a stage moves a hole, and `RawHole` cannot serve — two coincident
  circles, precisely the duplicate case, share identical raw geometry.
- **`ReferenceOutline.raw`** is the outline as measured. `IdentifyHammondFootprint`
  rewrites the nominal size; without `raw` nothing downstream can tell a 113 that was
  measured from a 113 that was snapped to.
- **`DrillData.processing`** is what each stage was configured to do, reported by its own
  `describe()` with *effective* values. The drawing reads the grid and the drill standard
  from here; it must never be handed a second copy through emitter options.
- **`DrillData.enclosure`** is a *conclusion*, which is why it is neither `SourceInfo`
  (where the bytes came from) nor a `StageRun` (what a stage was configured to do). A
  consumer asking "which enclosure is this panel?" gets one answer, or `None`.

`EnclosureMatch.length_mm`/`width_mm` are `int` deliberately: they are the datasheet's
whole millimetres, not a measurement, and emitting `112.0` beside a `reference.width` of
`112.0` would make the catalogue's nominal figure indistinguishable from the artwork's.
They stay in the catalogue's orientation even when `rotated` is set, so the footprint
remains findable in the datasheet it came from.

### 3.1 Units

Millimetres internally, always. Inch conversion happens **inside an emitter**, at the
last moment. No stage sees inches.

---

## 4. Protocols

```python
class Source(Protocol):
    def read(self) -> DrillData: ...

class Stage(Protocol):
    name: ClassVar[str]
    def apply(self, data: DrillData) -> DrillData: ...
    def describe(self) -> StageRun: ...

class Emitter(Protocol):
    name: ClassVar[str]
    media_type: ClassVar[str]
    extension: ClassVar[str]
    def emit(self, data: DrillData) -> str: ...
```

`Pipeline` is `Sequence[Stage]` with `run(data) -> DrillData`, folding left. It contains
no domain knowledge whatsoever: it appends `stage.describe()` after `apply` returns, so
a stage never sees provenance for itself in its own input, a stage that raises leaves no
claim that it ran, and the fold needs to know nothing about grids, diameters or
tolerances to record them.

---

## 5. Stages

Order matters and is fixed by the CLI, not by the stages themselves (LSP: no stage may
assert its position).

The CLI's order is **snap → snap-diameters → dedupe → identify-enclosure → sort**.
Diameters are quantised before deduplication because `Deduplicate` compares diameters
exactly and will not decide for itself that 6.9998 and 7.0002 are one size: that decision
is made once, upstream, or it gets made twice and differently.

| Stage | `name` | Responsibility | Diagnostics emitted |
|---|---|---|---|
| `SnapPositions(grid, warn_over=None)` | `snap` | Snap `x`, `y` to `grid`. `warn_over` defaults to `grid / 4`; `grid <= 0` is the identity and says nothing. | `off-grid` (WARNING) per hole exceeding `warn_over` |
| `SnapDiametersToDrillTable(standard, tolerance_mm=0.25)` | `snap-diameters` | Give every hole the nominal diameter of a bit the declared standard actually holds. A hole matching none is **dropped**. | `unknown-diameter` (**ERROR**) per dropped hole |
| `Deduplicate(tolerance=0.05)` | `deduplicate` | Collapse holes coincident within `tolerance` **and** of exactly equal nominal diameter. First in input order survives. | `duplicate-hole` (WARNING) per collapsed group |
| `IdentifyHammondFootprint(tolerance_mm=1.5, expected_part=None)` | `identify-enclosure` | Match the reference outline against the Hammond 1590 catalogue and snap it to the catalogue's whole millimetres. No reference outline → returns the data untouched, silently. | `unknown-enclosure` (WARNING), `ambiguous-enclosure` (ERROR), `wrong-enclosure` (ERROR) |
| `SortHoles(key=None)` | `sort` | Deterministic ordering. Default: descending Y, then ascending X. | none |
| `CheckReferenceSize(expected, tolerance=0.05)` | `check-reference-size` | **Not in the CLI pipeline.** Compares the outline against a declared `(width, height)`. Pure validator — returns the data unchanged. | `reference-size-mismatch` (WARNING), `no-reference-outline` (INFO) |

`CheckReferenceSize` remains a supported `Stage` for a library caller who has an outside
authority for the panel size, but `--true-size` is gone and `build_pipeline` no longer
wires it: an operator retyping a datasheet by hand is exactly the transcription this
tool now does from the catalogue, and having both would give a run two answers to "how
big is this panel?".

**Severity is the exit code, so it is a contract.** `unknown-diameter` was a WARNING in
version 1.0 and the hole kept its measured diameter; it is now an ERROR and the hole is
gone. A consumer that built its handling from the older spec would treat a **dropped
hole** as something merely worth logging.

### 5.1 Drill standards (a registry of real bits, not a strategy)

```python
@dataclass(frozen=True, slots=True)
class DrillStandard:
    name: str
    sizes_mm: tuple[float, ...]
    label: Callable[[float], str]

    def select(self, include=None, exclude=None) -> DrillStandard: ...

DRILL_STANDARDS: Mapping[str, DrillStandard]    # read-only; "metric", "fractional"
DEFAULT_STANDARD = "metric"
```

| Standard | Sizes | Built from | Label |
|---|---|---|---|
| `metric` (default) | **183**, 0.5–25.0 mm | `METRIC_BANDS`: 0.5–3.0 by 0.05, 3.0–14.0 by 0.1, 14.0–25.5 by 0.5 (`stop` exclusive) | `⌀3.20 mm` — unique *and* truthful at 2 dp |
| `fractional` | **64**, 1/64″–1″ | `n * 25.4 / 64` for `n` in 1…64, which is exact because the division is by a power of two | `⌀1/8"` — the fraction |

**Why a table of real bits, and not clustering.** Clustering answers "which of these
measurements are the same hole?", a question about the artwork. The question that gets a
panel drilled is "which bit do I put in the chuck?", and its answer set is fixed by a bit
series nobody here gets to invent. Clustering 5.02 and 5.04 into a nominal 5.03 produces
a size that exists in no drawer on earth, and it does so silently, in the number the
machinist reads.

**Why `label` is a function and not a decimal precision.** 1/64″ is 0.396875 mm. The
fractional series is unique at 2, 3 and 4 decimal millimetres and *truthful* at none, so
a `display_decimals: int` serves metric perfectly and cannot serve fractional at any
value. The drawing reads the standard's name back out of the recorded `snap-diameters`
run and spells each diameter the way the bit is stamped.

**Why a registry, and never one merged table.** 3.175 mm (1/8″) and 3.2 mm are 0.025 mm
apart — a tenth of the matching tolerance — and 1/2″ *is* 12.7 mm, the same physical bit
under two names. Merged, the choice between neighbours would be decided by float ordering
rather than by anything real. A panel is drilled with one set of bits; the operator
declares which set.

**Why both series are generative rules rather than transcribed lists.** A rule cannot
carry a transcription typo, and it is auditable by reading five lines instead of checking
183 values. Sources genuinely disagree about the metric breakpoints, so the bands are
*data*: adopting another preferred series is editing a tuple.

**What `tolerance_mm=0.25` really catches.** Within the metric series' range, nothing:
the widest gap anywhere is the 0.5 mm step between 14.0 and 14.5, so the furthest any
measurement in 0.5–25.0 mm can sit from a size is exactly 0.25, which `within` treats as
inclusive. What protects a panel in that range is the *density of the table*. The bound
exists for measurements **outside** the series — a 30 mm cut-out wanting a step drill, a
0.2 mm speck, a rounded rectangle the circle fitter mistook for a circle — where
unbounded nearest-neighbour matching would turn a malformed shape into a plausible wrong
drill that nothing downstream could tell from a real one.

**Why an unmatched hole is dropped rather than kept.** If every nominal comes from the
table, a retained 30.0 is a nominal that came from nowhere, and the drill file would
define a tool for a bit that does not exist. Everything needed to find the hole is in the
diagnostic: its `hole_index`, what it measured, and the nearest bit there is. Because the
finding is an ERROR, the run writes no artifacts at all (§8), so the dropped hole cannot
reach a machine.

**Narrowing is the operator's job.** `select(include=, exclude=)` returns a copy holding
only the bits actually in the drawer; a requested size the standard does not have raises
rather than being quietly dropped, because `--drill-sizes 3.33` is a typo whose silent
reading makes every hole on the panel an `unknown-diameter` error with nothing pointing
at the cause. A narrowed standard publishes its whole size list through `describe()`; an
unnarrowed one publishes only its name and `size_count`, because a consumer that cannot
expand `"metric"` into 183 sizes cannot interpret them either.

---

## 6. Sources

### `AiPdfSource(path, drill_layer="Drill", reference_layer="Background")`

Reads the PDF-compatible stream of a native `.ai` save with `pikepdf`. Illustrator is not
required to be running.

Contract and known constraints, all verified against a real file (Illustrator 30.7):

1. Layers are recovered from `/OCProperties` → `/OCGs` (`/Name`), mapped to content via
   `/Resources/Properties` → `/MCn`. **Top-level Illustrator layers only** — sublayers fold
   into the parent OCG.
2. Paths with neither fill nor stroke are absent from the PDF stream. If the drill layer
   yields nothing, raise `EmptyLayerError` naming this as the likely cause.
3. Clip paths (`W`/`W*` followed by `n`) must be discarded, not treated as geometry.
4. Circles are 4 cubic Béziers, κ ≈ 0.5522847498. Recover centre and diameter from the
   bounding box of the four on-curve anchors; validate with `|w−h| ≤ tol·max(w,h)` and a
   κ-consistency check on control points.
5. The CTM from `cm` must be applied, including inside Form XObjects.
6. PDF user space is 1/72″, Y-up from `/MediaBox` bottom-left. The artboard is **not**
   guaranteed to match the enclosure (the reference file is A4), so the frame origin comes
   from the reference layer's largest non-circular path bounding box, **never** the
   MediaBox.
7. Object names are **not** recoverable — `.ai` files carry no structure tree. Do not
   design around them.

Raises `LayerNotFoundError` (naming the layers that do exist) and `EmptyLayerError`.

### 6.1 The reference outline, and what happens to it

What the source measures is not what the pipeline ends up using. The bounding box of a
stroked path in a PDF comes back a fraction of a millimetre out in both axes, and
`IdentifyHammondFootprint` turns "roughly 112 × 61" into a named footprint and snaps the
outline to the catalogue's whole millimetres through `ReferenceOutline.resized`, which
keeps `raw` as the artwork's own measurement. `ReferenceOutline(112.0, 61.0)` is legal
code whose `raw` defaults to its own dimensions, so constructing a fresh outline would
quietly assert that the panel was *measured* at 112 × 61.

The catalogue is `src/aidrill/enclosures.py`: **37 base parts collapsing into 22 distinct
footprints**, generated from `docs/1590.pdf` by `tools/extract_1590.py` and re-extracted
on every test run. A 2-D outline identifies a footprint and never a part — 112 × 61 is
1590B, 1590B2 *and* 1590BS, which differ only in height — so a match names candidates and
`selected_part` is filled in only from what the operator declared with `--case`.

The default `tolerance_mm=1.5` is bounded by the catalogue, not chosen for the fixture:
two footprints both match one outline once they are within twice the tolerance of each
other, and the closest approach in the 22 footprints is 4 mm (1590B3 116 × 77 against
1590T 120 × 80). Anything below 2 mm is therefore unambiguous everywhere.

### 6.2 The backplate convention — draw the Background layer to backplate size

**The `Background` layer must be drawn to the enclosure's BACKPLATE dimensions, which are
the dimensions the catalogue holds.** This is not a preference; it is the only size the
tool can match, and an operator who carefully measures the face they are about to drill
gets `unknown-enclosure` for being more careful.

The reason is that a Hammond 1590 is a die-cast box with tapered walls — the datasheet
calls out a "low side wall draft angle (2° or less)" — so the drilled face is *smaller*
than the backplate by `2 · d · tan θ` per axis, where `d` is the internal wall depth
(catalogue heights include the 4 mm lid). At the datasheet's 2° that is 1.5 mm on the
shallowest part (1590LLB, 25 mm), **1.9 mm on a 1590B** (31 mm) and 6.3 mm on the deepest
(1590V, 94 mm).

No tolerance can accept a face-drawn outline:

- A face-drawn 1590B measures about 110.5 × 58.6 against a catalogue 112 × 61, so
  matching it needs a per-axis tolerance of **at least 2.4 mm** — and that is the
  shallowest common part, before any drawing error of the operator's own. Deeper cases
  need several times more.
- Two footprints tie at `2 × tolerance ≥ separation`, and the closest separation is
  4 mm, so the ambiguity ceiling is **below 2.0 mm**. (`tests/test_pipeline.py` pins it:
  2.0 mm reports `ambiguous-enclosure`, 1.99 mm does not.)

Required ≥ 2.4, permitted < 2.0. There is no value, so the convention is the fix, and
`unknown-enclosure`'s message names it so the failure teaches it.

---

## 7. Emitters

Self-registering via `@register_emitter`. The registry is the only thing the CLI consults,
so a new emitter needs no CLI edit.

### `excellon`

```
ExcellonOptions(origin=Origin.LOWER_LEFT, units=Units.METRIC, decimals=3)
```

- Header `M48`, `FMAT,2`, `METRIC,TZ` / `INCH,TZ`, `;FORMAT=` comment, tool definitions,
  `%`, then `G90` `G05`, tool-grouped coordinates, `T0`, `M30`.
- Tool numbers come from `DrillData.tools()`. **One tool per nominal diameter — this is an
  invariant and must be asserted in tests.**
- Holes are written in the order they arrive. The sequence is `SortHoles`' decision; this
  emitter once carried its own copy of the reading-order key, so a custom sort reached the
  sheet and not the drill file.

**Declining to write a file is permitted; repairing one is not.** Three refusals, each
raising `EmitterError` rather than emitting something plausible:

1. `LOWER_LEFT` without a reference outline — there is no defensible lower-left corner.
2. Two nominal diameters that print as the same `C…` token at the configured precision:
   3.02 and 3.03 mm are two unmistakable tools in millimetres and one `0.119` at three
   decimals in inches, and a file that loads the same tool twice is the founding defect of
   ADR-0001. Merging them is the pipeline's call, never this file's.
3. A hole that reframes to a negative coordinate under `LOWER_LEFT`, checked against the
   *rendered token* so a hole a fraction of a print unit outside the outline is not
   reported. `LOWER_LEFT` promises positive coordinates, so a negative one means the hole
   lies outside the reference outline.

### `drawing-svg`

```
DrawingOptions(sheet=A4_LANDSCAPE, scale=None, title="", drawing_no="",
               company="ARTIFACT INSTRUMENTS")
```

An engineering drawing, not an artwork render: sheet border, reference outline,
centrelines, origin symbol, hole circles with centre marks, numbered balloons, chain
dimensions per hole row, overall dimensions, a hole schedule keyed to the same tool
numbers, a title block, and the diagnostics rendered as numbered notes (warnings and
errors in red).

The title block states the enclosure —
`HAMMOND 1590  112 × 61 mm  CANDIDATES B / B2 / BS`, or `PART 1590B` when the operator
declared one, or `ENCLOSURE NOT IDENTIFIED` when nothing matched. The catalogue footprint
is printed, never the measured outline: 112 × 61 is the number on the datasheet the
operator orders the box by. `ROTATED` is stated because the match keeps the catalogue's
orientation while the drawing dimensions the artwork's, so a turned 1590B is dimensioned
61 × 112 beside an enclosure line reading 112 × 61.

The `true_size` option and its dashed overlay are **gone**. Once the pipeline identifies
the enclosure itself, the overlay draws a rectangle exactly on top of the normalised
reference on every run that matched — two identical outlines, one presented as a check on
the other — and on a run that did *not* match, what is worth having is which case was
asked for and which one the artwork is. Those are a title-block line and a diagnostic.

It must not attempt to render the Graphics layer. Substitute fonts and bbox-only text
metrics make that misleading, and it isn't drill data.

`scale=None` fits the drawing to the available area.

Four things on the sheet are pipeline facts and are read as such, never re-derived and
never passed in a second time through the options:

- **Which holes are duplicates** comes from each `duplicate-hole` diagnostic's `hole_index`.
  Matching on coordinates is wrong: `Pipeline([Deduplicate, SnapPositions])` is a legal
  order, and under it the survivor moves after the diagnostic was written.
- **The grid** comes from the recorded `snap` run (`DrillData.last_run("snap")`). A positive
  pitch is printed, a recorded `0` prints `GRID OFF`, and data that never met a pipeline
  prints `GRID NOT RECORDED`. There is no default to fall back to — a sheet stamped with a
  pitch the holes were never snapped to is exactly the silent disagreement this spec exists
  to prevent.
- **How a diameter is spelled** comes from the drill standard the recorded
  `snap-diameters` run names, through `DrillStandard.label`. A millimetre spelling is
  honest for the metric drawer and not for the fractional one.
- **Which enclosure the panel is** comes from `DrillData.enclosure`, including the
  candidate order, which belongs to whoever built the match.

### `json`

The full `DrillData` including raw provenance and diagnostics. This is the integration
surface for the wider toolchain and the easiest thing to assert against in tests.

Document shape, **version 4**:

```
{
  "format": "aidrill-drill-data",
  "version": 4,
  "units": "mm",                     # always; canonical frame, never inches
  "origin": "centre",
  "source":      {"path", "drill_layer", "reference_layer", "layers_found", "producer"},
  "reference":   {"width", "height", "centre_x", "centre_y",
                  "raw": {"width", "height"}} | null,
  "tools":      [{"number", "diameter", "count"}, …],        # ascending diameter
  "holes":      [{"x", "y", "diameter", "tool",
                  "raw": {"x", "y", "diameter"}, "index"}, …],   # pipeline order
  "diagnostics":[{"severity", "code", "message", "location", "data"}, …],
  "processing": [{"name", "parameters": {…}}, …],            # in the order run
  "enclosure":   {"family", "length_mm", "width_mm", "candidates",
                  "rotated", "selected_part"} | null
}
```

Each version added something a consumer would otherwise have had to reconstruct from
geometry — the founding bug of this project, displaced one layer out into the toolchain.
v2 added `Hole.index`, `Diagnostic.data` and `processing`; v3 added `reference.raw`, whose
absence sent a *snapped* outline out as though it were what the artwork said; v4 added
`enclosure`, without which the only route back to "which enclosure is this panel?" was to
re-implement the matcher's tolerance rule against the catalogue.

Key order is fixed and part of the contract, and new keys are appended, so a v1 reader
indexing by position sees the shape it knows before the additions. `enclosure` is `null`
rather than absent when nothing matched, and never an object naming no candidates.

---

## 8. CLI

```
aidrill PANEL.ai [options]

  --drill-layer NAME          default: Drill
  --reference-layer NAME      default: Background
  --grid MM                   default: 0.25   (0 disables)
  --grid-warn MM              default: grid/4
  --drill-standard NAME       default: metric   (metric | fractional)
  --drill-sizes CSV           narrow the standard to these of its sizes
  --no-drill-sizes CSV        narrow the standard by removing these of its sizes
  --dedupe-tolerance MM       default: 0.05
  --case PART                 the Hammond 1590 base designator the panel is drawn for
  --emit FORMAT=PATH          repeatable; FORMAT from the registry
  --title TEXT
  -v/--verbose
```

Removed in 2.0: `--diameters`, `--diameter-tolerance`, `--true-size`. `--drill-sizes`
survives the name but not the meaning — it used to *be* the whole table and was ignored
unless `--diameters table` was also passed, and it now narrows the declared standard and
is never ignored. **An old invocation that carried it as a no-op will now take bits out
of the drawer.**

Every one of `--drill-standard`, `--drill-sizes`, `--no-drill-sizes` and `--case` is
resolved *before* the input file is opened, and a bad value is a usage error (exit 3). A
size the standard does not stock, and a part number in no catalogue, are both facts about
the command line — nothing has been measured, no file need even be read. `--case 1590BBBK`
is a real order code (BB body, BK black finish) and the single most likely thing an
operator types; checked against footprints it would report `wrong-enclosure` on a
*correct* 1590BB panel, so it is refused up front with the base designator it is built on
in the message. `wrong-enclosure`, by contrast, took a parse, a measurement and a
catalogue lookup, and belongs in the report.

Exit codes: `0` clean, `1` warnings present, `2` errors, `3` usage/IO failure.

**Exit 2 is now reachable.** In version 1.0 no stage produced an ERROR. Three do now:
`unknown-diameter`, `ambiguous-enclosure` and `wrong-enclosure`.

**A run with any ERROR writes no artifacts.** Not one file, and the emitters are not even
asked for their bytes. The CLI instead prints every path it did *not* write, so nothing
looks stale. The failure this prevents is a drill file **missing a hole**: a hole whose
diameter matches no bit is dropped by `snap-diameters`, and the Excellon format renders no
diagnostics at all, so the file that actually goes to the machine would carry a shorter
panel and look perfectly well-formed. Only ERROR withholds — an enclosure this tool does
not stock is a WARNING and must still produce a drill file.

Where several artifacts are requested, all of them are rendered before any of them reaches
the disk. An emitter may legitimately refuse (§7), and writing as we went left the first
target on disk and not the second.

`--emit` being repeatable and registry-driven is the OCP proof: `--emit dxf=out.dxf` must
work the day a DXF emitter is added, with no change to `cli.py` — as long as that emitter
needs no flags of its own (§2.1).

---

## 9. Testing

TDD throughout — test first, then implementation.

- **Unit tests** for every stage, drill standard, emitter and geometry helper, with no I/O.
- **Property tests** where cheap: snapping is idempotent; dedupe is idempotent; `tools()`
  is stable under hole reordering.
- **Catalogue test:** `tests/test_enclosures.py` re-extracts `docs/1590.pdf` on every
  suite run, so a datasheet revision shows up as a red test rather than as a quiet
  disagreement between the shipped table and the PDF beside it.
- **Fixture test** against `tests/fixtures/tar.ai`, whose expected output is known:

  | | |
  |---|---|
  | Layers | `Background`, `Drill`, `Graphics`, `Hardware` |
  | Reference outline, as measured | 113.000 × 60.000 mm |
  | Reference outline, after `identify-enclosure` | 112 × 61 mm (1590B / 1590B2 / 1590BS) |
  | Circles read | 8 |
  | Unique holes after dedupe | 7 |
  | ⌀7.00 | 5, at y = +18.00, x = −40 −20 0 +20 +40 |
  | ⌀5.00 | 2, at y = −18.75, x = ∓19.00 |
  | Duplicate | 1 group at (−40.00, +18.00) |
  | Distinct tools | **exactly 2** |
  | Warnings at grid 0.25 | none beyond the duplicate |

- **Regression test:** at `--grid 0.5` the two ⌀5 holes must raise `off-grid`, each moving
  0.25 mm. This guards the residual-reporting behaviour.
- **Invariant test:** no emitter output ever contains two tools of equal diameter.

Coverage target: 90% of `src/aidrill`, and 100% of the stages and emitters.
