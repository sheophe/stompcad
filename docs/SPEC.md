# aidrill — specification

**Version:** 1.0 · **Status:** implementable

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
   .ai / PDF                  snap · normalize ·                     excellon
   (future: SVG,              dedupe · validate                      drawing-svg
    DXF, KiCad)                                                      json
                                                                     (future: dxf, ai)
```

**The pipeline is universal.** Snapping, diameter normalization and deduplication happen
**once**, before any emitter sees the data. No emitter may re-derive them. This is the
central constraint of the design: an earlier version clustered diameters inside the
Excellon writer, which meant the drawing and the Excellon file could legitimately
disagree about how many distinct hole sizes existed. Preprocessing is not an emitter
concern.

### 2.1 SOLID obligations

| Principle | How it binds here |
|---|---|
| **SRP** | One reason to change per module. A stage transforms; an emitter serializes; a source parses. A stage that formats output, or an emitter that rounds a number, is a bug. |
| **OCP** | Adding an emitter or a stage must require **zero** edits to `Pipeline`, the CLI dispatch, or any sibling. New emitters self-register. |
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
    diameter: float   # mm, nominal (post-normalization)
    raw: RawHole      # provenance: as-measured values, never mutated

RawHole:
    x: float; y: float; diameter: float

RawOutline:
    width: float; height: float

ReferenceOutline:
    width: float; height: float          # mm, nominal (post-snap)
    centre_x: float; centre_y: float     # mm, in source space
    raw: RawOutline                      # provenance: as-measured, never mutated

Diagnostic:
    severity: Severity                   # INFO | WARNING | ERROR
    code: str                            # stable machine key, e.g. "duplicate-hole"
    message: str                         # human sentence, no trailing newline
    location: tuple[float, float] | None # canonical mm, if the finding has a place

DrillData:
    holes: tuple[Hole, ...]
    reference: ReferenceOutline | None
    diagnostics: tuple[Diagnostic, ...]
    source: SourceInfo                   # path, layer names, producer string
```

`DrillData` is frozen and exposes:

- `with_holes(holes)` → new instance
- `with_diagnostics(*diags)` → new instance, diagnostics appended
- `with_origin(origin)` → new instance, holes translated; `Origin.CENTRE | LOWER_LEFT`
- `tools()` → ordered mapping `{diameter: tool_number}`, ascending, **1-based**

`tools()` living on the model, not in the Excellon emitter, is deliberate: the drawing's
hole schedule and the Excellon tool table must never disagree.

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

class Emitter(Protocol):
    name: ClassVar[str]
    media_type: ClassVar[str]
    def emit(self, data: DrillData) -> str: ...
```

`Pipeline` is `Sequence[Stage]` with `run(data) -> DrillData`, folding left. It contains
no domain knowledge whatsoever.

---

## 5. Stages

Order matters and is fixed by the CLI, not by the stages themselves (LSP: no stage may
assert its position).

| Stage | Responsibility | Diagnostics emitted |
|---|---|---|
| `SnapPositions(grid, warn_over=None)` | Snap `x`, `y` to `grid`. `warn_over` defaults to `grid / 4`. | `off-grid` (WARNING) per hole exceeding `warn_over` |
| `NormalizeDiameters(strategy)` | Assign a nominal diameter to each hole. | `unknown-diameter` (WARNING) when a table strategy finds nothing in tolerance |
| `Deduplicate(tolerance)` | Collapse holes coincident within `tolerance` **and** of equal nominal diameter. | `duplicate-hole` (WARNING) per collapsed group |
| `CheckReferenceSize(expected)` | Compare the reference outline to a declared true size. Pure validator — returns data unchanged. | `reference-size-mismatch` (WARNING) |
| `SortHoles(key)` | Deterministic ordering. Default: descending Y, then ascending X. | none |

### 5.1 Diameter strategies (Strategy pattern — OCP)

```python
class DiameterStrategy(Protocol):
    def nominal(self, measured: Sequence[float]) -> Mapping[float, float]: ...
```

- `ClusterDiameters(tolerance=0.05)` — greedy single-linkage grouping over sorted values;
  representative is the mean of the group rounded to 2 dp. Default.
- `TableDiameters(sizes, tolerance=0.15)` — snap to the nearest declared drill size;
  values outside tolerance keep their measured value and raise `unknown-diameter`.
- `NoNormalization()` — identity. For debugging.

**Why this exists at all:** measured diameters come back as 6.9998 and 7.0000 for what the
designer drew as one 7 mm hole. Without normalization every downstream consumer sees two
sizes — the Excellon file loads the same bit twice, the hole schedule shows two tools, and
a part lookup misses. This must be resolved once, in the pipeline.

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
- `LOWER_LEFT` keeps every coordinate positive; requires a reference outline, else raise.

### `drawing-svg`

```
DrawingOptions(sheet=A4_LANDSCAPE, scale=None, title="", drawing_no="", true_size=None)
```

An engineering drawing, not an artwork render: sheet border, reference outline, true-size
outline overlay when supplied, centrelines, origin symbol, hole circles with centre marks,
numbered balloons, chain dimensions per hole row, overall dimensions, a hole schedule
keyed to the same tool numbers, a title block, and the diagnostics rendered as numbered
notes (warnings in red).

It must not attempt to render the Graphics layer. Substitute fonts and bbox-only text
metrics make that misleading, and it isn't drill data.

`scale=None` fits the drawing to the available area.

Two things on the sheet are pipeline facts and are read as such, never re-derived and never
passed in a second time through the options:

- **Which holes are duplicates** comes from each `duplicate-hole` diagnostic's `hole_index`.
  Matching on coordinates is wrong: `Pipeline([Deduplicate, SnapPositions])` is a legal
  order, and under it the survivor moves after the diagnostic was written.
- **The grid** comes from the recorded `snap` run (`DrillData.last_run("snap")`). A positive
  pitch is printed, a recorded `0` prints `GRID OFF`, and data that never met a pipeline
  prints `GRID NOT RECORDED`. There is no default to fall back to — a sheet stamped with a
  pitch the holes were never snapped to is exactly the silent disagreement this spec exists
  to prevent.

### `json`

The full `DrillData` including raw provenance and diagnostics. This is the integration
surface for the wider toolchain and the easiest thing to assert against in tests.

---

## 8. CLI

```
aidrill PANEL.ai [options]

  --drill-layer NAME          default: Drill
  --reference-layer NAME      default: Background
  --grid MM                   default: 0.25   (0 disables)
  --grid-warn MM              default: grid/4
  --diameters cluster|table|none   default: cluster
  --diameter-tolerance MM     default: 0.05 (cluster) / 0.15 (table)
  --drill-sizes CSV           required by --diameters table
  --dedupe-tolerance MM       default: 0.05
  --true-size WxH             enables CheckReferenceSize
  --emit FORMAT=PATH          repeatable; FORMAT from the registry
  --title TEXT
  -v/--verbose
```

Exit codes: `0` clean, `1` warnings present, `2` errors, `3` usage/IO failure.

`--emit` being repeatable and registry-driven is the OCP proof: `--emit dxf=out.dxf` must
work the day a DXF emitter is added, with no change to `cli.py`.

---

## 9. Testing

TDD throughout — test first, then implementation.

- **Unit tests** for every stage, strategy, emitter and geometry helper, with no I/O.
- **Property tests** where cheap: snapping is idempotent; dedupe is idempotent; `tools()`
  is stable under hole reordering.
- **Fixture test** against `tests/fixtures/tar.ai`, whose expected output is known:

  | | |
  |---|---|
  | Layers | `Background`, `Drill`, `Graphics`, `Hardware` |
  | Reference outline | 113.000 × 60.000 mm |
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
