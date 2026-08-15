# aidrill — specification

**Status:** implemented

---

## 1. Purpose and single responsibility

`aidrill` extracts drill data from an Adobe Illustrator `.ai` file and emits it in a
chosen output format.

That is the whole responsibility. It does **not** model enclosures in 3D, read KiCad,
check clearances, or know what a potentiometer is. Those belong to the wider toolchain
and will consume `aidrill` as a library. KiCad is therefore not a candidate future
`Source` either, which is why §2's diagram does not list it: a board file describes parts
and nets, which is the vocabulary this tool is defined by not having.

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
   (future: SVG, DXF)         dedupe · identify-enclosure ·          drawing-svg
                              sort                                   json
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
- `of_severity(severity)` → the diagnostics at exactly that severity, in order
- `worst_severity` → property; the highest severity present, or `None` for a clean run.
  **The exit-code contract of §8 is this property and nothing else**, so a caller wanting to
  know whether a run may be trusted asks it rather than counting diagnostics itself.

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
| `SnapDiametersToDrillTable(standard=DRILL_STANDARDS["metric"], tolerance_mm=0.25)` | `snap-diameters` | Give every hole the nominal diameter of a bit the declared standard actually holds. A hole matching none is **dropped**. | `unknown-diameter` (**ERROR**) per dropped hole |
| `Deduplicate(tolerance=0.05)` | `deduplicate` | Collapse holes coincident within `tolerance` **and** of exactly equal nominal diameter. First in input order survives. | `duplicate-hole` (WARNING) per collapsed group |
| `IdentifyHammondFootprint(tolerance_mm=1.5, expected_part=None)` | `identify-enclosure` | Match the reference outline against the Hammond 1590 catalogue and snap it to the catalogue's whole millimetres. With nothing declared, no reference outline returns the data untouched and silently. | `unknown-enclosure` (WARNING), `ambiguous-enclosure` (ERROR), `unverifiable-enclosure` (ERROR), `unmatched-enclosure` (ERROR), `wrong-enclosure` (ERROR) |
| `SortHoles(key=None)` | `sort` | Deterministic ordering. Default: descending Y, then ascending X. | none |
| `CheckReferenceSize(expected, tolerance=0.05)` | `check-reference-size` | **Not in the CLI pipeline.** Compares the outline against a declared `(width, height)`. Pure validator — returns the data unchanged. | `reference-size-mismatch` (WARNING), `no-reference-outline` (INFO) |

`CheckReferenceSize` is **library-only by design**: no CLI flag builds it and
`build_pipeline` does not wire it. It exists for the caller whose authority for the panel
size is outside this catalogue — a folded-aluminium box, a printed shell, anything the 22
Hammond footprints do not hold — for whom `IdentifyHammondFootprint` can say no more than
`unknown-enclosure`. The CLI's own size assertion is `--case`, which does strictly more:
it snaps the outline to the catalogue as well as checking it, and only a *catalogue*
footprint can be snapped to. Wiring both would give one run two answers to "how big is
this panel?" with nothing to reconcile them.

**Severity is the exit code, so it is a contract.** `unknown-diameter` is an ERROR and the
hole is **dropped**: if every nominal comes from the drill table, a retained measurement is
a tool for a bit that does not exist, and §8's withholding rule is what keeps the dropped
hole off a machine.

### 5.1 The five enclosure codes, and what gates each

`identify-enclosure` reports on two axes: whether the operator declared a `--case`, and
what the outline matched. A declaration is knowledge the catalogue does not hold, so it
changes what a given match *means* — and because a part belongs to exactly one footprint,
a declaration either resolves a tie or matches nothing at all.

| Declared | Outline | Outcome |
|---|---|---|
| no | absent | nothing; the data is returned untouched (a stage may not assume a predecessor ran) |
| no | unique match | silent; the outline is snapped to the catalogue's whole millimetres |
| no | no match | `unknown-enclosure` (WARNING) — a statement about *our* catalogue, so the run continues and the outline is left as drawn |
| no | tie | `ambiguous-enclosure` (ERROR) naming every footprint that fitted |
| yes | absent | `unverifiable-enclosure` (ERROR) — the one thing this stage was asked to check cannot be checked at all |
| yes | matches the declared part | silent; snapped. A tie containing the declared part is resolved this way |
| yes | one match, a different part | `wrong-enclosure` (ERROR) naming both the declared part and what was drawn |
| yes | no match, or a tie holding no declared part | `unmatched-enclosure` (ERROR) |

Two consequences a consumer may rely on: `ambiguous-enclosure` and `unknown-enclosure` are
reachable **only from an undeclared run**, and a declared run therefore ends in a confirmed
match or an ERROR — never in silence it could mistake for confirmation.

`unmatched-enclosure` is deliberately not `wrong-enclosure`: with nothing identified, the
accusation would be unfounded, and by §6.2's backplate convention the likeliest panel here
is the declared case measured across its drilled face. It is not `unknown-enclosure`
either — one `code` at two severities meaning two things is a key nobody can route on.

Payloads, so a consumer need not re-read the catalogue:

| `code` | `data` keys |
|---|---|
| `unknown-enclosure` | `width_mm`, `height_mm`, `tolerance_mm`, `catalogue` |
| `ambiguous-enclosure` | `footprints`, `candidates`, `tolerance_mm` |
| `unverifiable-enclosure` | `requested_part`, `expected_length_mm`, `expected_width_mm`, `catalogue` |
| `unmatched-enclosure` | `requested_part`, `expected_length_mm`, `expected_width_mm`, `width_mm`, `height_mm`, `tolerance_mm`, `catalogue`, `footprints`, `candidates` |
| `wrong-enclosure` | `requested_part`, `identified_parts`, `length_mm`, `width_mm` |

`expected_length_mm` / `expected_width_mm` are **absent**, never zero, when the declared
part is in no catalogue — reachable only from a library caller, since `cli.parse_case`
refuses such a part before the file is opened. `footprints` and `candidates` are present
and empty on an `unmatched-enclosure` where nothing fitted, so the payload has one shape
however the confirmation failed.

### 5.2 Drill standards (a registry of real bits, not a strategy)

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

**What `tolerance_mm=0.25` really catches.** Within the metric series' range, nothing: the
widest gap anywhere is 0.5 mm, and it is not one gap but the whole top band — every step
from 14.0 to 25.0 is 0.5 mm, so the widest gap occurs 22 times. The furthest any
measurement in 0.5–25.0 mm can therefore sit from a size is exactly 0.25, which `within`
treats as inclusive. What protects a panel in that range is the *density of the table*.
The bound exists for measurements **outside** the series — a 30 mm cut-out wanting a step drill, a
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
at the cause. Every run publishes the standard's `name`, the matching `tolerance_mm` and
its `size_count` through `describe()`; a *narrowed* standard additionally publishes
`sizes_mm`, the whole list, because a run-specific drawer is small and a consumer computing
"the nearest available size" gets it wrong without the actual set. An unnarrowed one does
not, because a consumer that cannot expand `"metric"` into 183 sizes cannot interpret them
either. The test is equality against the registry, not a flag set by `select`, so a
hand-built standard wearing a registry name also writes its sizes out.

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
4. Circles are 4 cubic Béziers, κ ≈ 0.5522847498. Recover the centre as the **centroid of
   the four on-curve anchors** and the radius as their **mean distance from that centroid**.
   Validate three things, each of which rules out a shape a panel drawing genuinely
   contains: that the fourth curve's end returns to the first anchor (rejects arcs); that
   all four anchors are equidistant from the centroid (rejects ellipses, including a circle
   squashed by a non-uniform CTM); and that every control offset is κ-consistent — `κ·r`
   long, perpendicular to its own radius, and pointing the way the path travels (rejects the
   four-cubic rounded square, a control rotated onto the radius, and the inward cusp drawn
   on the very same anchors). The tolerance is **relative to the radius**, because the
   absolute error of a PDF's two decimals scales with the size of the shape.

   **The bounding box of the anchors is not an acceptable substitute, and never was the
   implementation.** The two agree only on axis-aligned input. A `cm` may rotate a circle,
   and on one turned 45° the anchors' bounding box is `√2·r` across: a bounding-box fit
   reports a ⌀7 mm hole as ⌀9.9 mm — a size the metric standard actually stocks, so
   `snap-diameters` accepts it without a diagnostic — or refuses a perfectly good hole on an
   aspect test that was never a property of circles in the first place. `geometry.fit_circle`
   fits from the centroid for that reason, and a second `Source` must do the same.
5. The CTM from `cm` must be applied, including inside Form XObjects.
6. PDF user space is 1/72″, Y-up from `/MediaBox` bottom-left. The artboard is **not**
   guaranteed to match the enclosure (the reference file is A4), so the frame origin comes
   from the reference layer's largest non-circular path bounding box, **never** the
   MediaBox.
7. Object names are **not** recoverable — `.ai` files carry no structure tree. Do not
   design around them.

Raises `LayerNotFoundError` (naming the layers that do exist), `EmptyLayerError`, and
`SourceError` for a file `pikepdf` cannot open or one carrying no pages. All three derive
from `AidrillError`; `LayerNotFoundError` and `EmptyLayerError` derive from `SourceError`,
so a caller that wants "the file was unusable" catches the one.

**A source emits diagnostics too, and one of them moves the exit code.** Two findings are
facts about the artwork rather than reasons to refuse it, so they are reported and the read
continues. They are part of the diagnostic inventory a consumer must handle even though
they come from no stage, which brings the codes this tool can emit to **twelve**:

| `code` | Severity | Raised when | Consequence |
|---|---|---|---|
| `non-circular-path` | INFO | the drill layer holds paths that are not circles — a rounded rectangle, an arc, a stroke cap | they are ignored; the count is in the message |
| `reference-outline-not-found` | WARNING | the reference layer holds no non-circular path to use as the panel outline | there is no frame to centre on, so hole positions stay page-relative, measured from the MediaBox corner, and `reference` is `None` |

The other ten are in §5's stage table. `non-circular-path` is INFO and leaves a clean run
at exit 0; `reference-outline-not-found` is a WARNING and takes it to 1, so a CI gate built
from §5 alone meets an exit code it has never heard of.

`reference-outline-not-found` is deliberately **not** `no-reference-outline`:
`CheckReferenceSize` already uses that key at INFO for a different finding — that there was
nothing to check a declared size against. One key meaning two things at two severities
defeats the point of matching on `code`, the more so because only the WARNING moves the
exit code.

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
ExcellonOptions(origin=Origin.LOWER_LEFT, units=Units.MILLIMETRES, decimals=3, title="")
```

The member is `Units.MILLIMETRES`, not `Units.METRIC`: `"metric"` is the enum's *value*,
because it is the word the Excellon header carries. `title` is the only field the CLI sets
(from `--title`), and it falls back to the source path.

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

There is no declared-size overlay, and there must not be one. The pipeline identifies the
enclosure itself, so an overlay would draw a rectangle exactly on top of the normalised
reference on every run that matched — two identical outlines, one presented as a check on
the other — and on a run that did *not* match, what is worth having is which case was asked
for and which one the artwork is. Those are a title-block line and a diagnostic.

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

```
JsonOptions(indent=2)
```

The full `DrillData` including raw provenance and diagnostics. This is the integration
surface for the wider toolchain and the easiest thing to assert against in tests. `indent`
goes straight to `json.dumps`, so `None` is the compact form.

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

Every key here exists so that a consumer never has to reconstruct a pipeline fact from
geometry — the founding bug of this project, displaced one layer out into the toolchain.
`index`, `data` and `processing` carry identity, payload and provenance; `reference.raw`
keeps a *snapped* outline from going out as though it were what the artwork said; and
`enclosure` is the only route to "which enclosure is this panel?" that does not
re-implement the matcher's tolerance rule against the catalogue.

Key order is fixed and part of the contract, and new keys are appended rather than
inserted, so a reader indexing by position is not moved by an addition. `enclosure` is
`null` rather than absent when nothing matched, and never an object naming no candidates.

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
  --case PART                 the Hammond 1590 base designator the panel is drawn for
  --emit FORMAT=PATH          repeatable; FORMAT from the registry
  --title TEXT
  -v/--verbose
```

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

**Five codes reach exit 2:** `unknown-diameter` from `snap-diameters`, and
`ambiguous-enclosure`, `unverifiable-enclosure`, `unmatched-enclosure` and
`wrong-enclosure` from `identify-enclosure` (§5.1).

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

**Withholding does not delete, and a file already at the target path survives a failed
run.** This is a deliberate ruling, recorded here rather than fixed. The CLI names every
path it did not write, but it does not touch them: if a previous run wrote `out.drl` and
the next one exits 2, `out.drl` is still there, byte for byte, and still loads as a
perfectly well-formed drill file **for the previous panel**. In a `make` rule or a manual
rerun that stale file is the obvious one to hand to the machine, and nothing in it says
so. Two consequences bind a caller:

- **Never treat the presence of an artifact as evidence a run succeeded.** The exit code is
  the only thing that says so. `0` and `1` wrote every requested path; `2` wrote none of
  them; `3` is an `OSError` or a usage error and may have got part-way — an emitter refusal
  writes nothing, but a disk that fills on the second of three targets leaves the first.
- **A build rule must delete its targets before invoking `aidrill`, or on failure**, so a
  broken run cannot leave a plausible answer behind. `aidrill` will not do it for you:
  deleting a file the operator named is a destructive act on the strength of a finding
  about *this* run's data, and a truncate-then-fail would be worse than either.

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
