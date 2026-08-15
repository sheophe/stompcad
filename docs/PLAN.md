# aidrill — implementation plan (SUPERSEDED)

> **Status: historical, as of 2026-08-15. Do not implement from this file.**
>
> This is the task breakdown for the original v1.0 build, kept because it records the
> interfaces that were agreed up front and the order the work was done in. It was never a
> normative document — SPEC has always been — and it has not been rewritten, because
> editing a plan after the fact destroys the only thing it is now good for: what was
> agreed, before the code had an opinion.
>
> What it says that is no longer true:
>
> - **Task B.2** describes `NormalizeDiameters` and the `ClusterDiameters` /
>   `TableDiameters` / `NoNormalization` strategies. All four are gone. Diameters now snap
>   to a registry of drill standards — see SPEC §5.1 and `docs/adr/0003-domain-quantisers.md`.
> - **Task B.4**'s `CheckReferenceSize` still exists but is no longer in the CLI pipeline;
>   `IdentifyHammondFootprint` took over the question it answered.
> - **Task E**'s `DrawingOptions.true_size` and its dashed overlay are gone.
> - **Task F**'s stage order is now snap → snap-diameters → dedupe → identify-enclosure →
>   sort, and the flags it implies (`--diameters`, `--diameter-tolerance`, `--true-size`)
>   no longer exist.
> - The model listed as "frozen" has since gained `RawOutline`, `EnclosureMatch`,
>   `StageRun`, `Hole.index`, `Diagnostic.data`, `ReferenceOutline.raw`,
>   `DrillData.processing` and `DrillData.enclosure`.
>
> For current work, read `docs/SPEC.md` and `docs/adr/`.

Read `docs/SPEC.md` first. It is normative; this file only slices it into tasks.

**Already written and frozen — depend on these, do not edit them:**

- `src/aidrill/model.py` — `Hole`, `RawHole`, `DrillData`, `Diagnostic`, `Severity`,
  `Origin`, `Units`, `ReferenceOutline`, `SourceInfo`
- `src/aidrill/protocols.py` — `Source`, `Stage`, `Emitter`, `Pipeline`
- `src/aidrill/errors.py` — exception hierarchy
- `src/aidrill/emitters/base.py` — `@register_emitter`, `get_emitter`, `available`

**Method: TDD.** Write the failing test first, then the smallest implementation that
passes, then refactor. Every task ships `tests/test_<module>.py` alongside its module.

---

## Interface contracts agreed up front

These are fixed so tasks can proceed in parallel without waiting on each other.

### `aidrill.geometry` (task A — task C codes against this without waiting)

```python
Matrix = tuple[float, float, float, float, float, float]   # PDF cm order: a b c d e f

IDENTITY: Matrix
def multiply(m: Matrix, n: Matrix) -> Matrix          # m applied, then n
def transform(m: Matrix, x: float, y: float) -> tuple[float, float]

@dataclass(frozen=True)
class Circle:
    cx: float; cy: float; diameter: float

@dataclass(frozen=True)
class SubPath:
    """A closed or open path in device space."""
    segments: tuple[Segment, ...]
    @property
    def anchors(self) -> tuple[tuple[float, float], ...]   # on-curve points only
    @property
    def bbox(self) -> tuple[float, float, float, float]     # x0, y0, x1, y1

def fit_circle(path: SubPath, tolerance: float = 0.01) -> Circle | None
    """Four cubics, kappa-consistent controls, square bbox -> Circle, else None."""

KAPPA: float = 0.5522847498
PT_PER_MM: float = 72.0 / 25.4
def pt_to_mm(v: float) -> float
```

`Segment` is a small tagged union: `MoveTo(point)`, `LineTo(point)`, `CurveTo(c1, c2, end)`,
`ClosePath()`. Task A chooses the exact representation; task C only uses `SubPath.anchors`,
`SubPath.bbox` and `fit_circle`.

### Emitter shape (tasks D and E)

```python
@register_emitter
class XEmitter:
    name: ClassVar[str]          # registry key, also the --emit token
    media_type: ClassVar[str]
    extension: ClassVar[str]
    def __init__(self, options: XOptions | None = None) -> None: ...
    def emit(self, data: DrillData) -> str: ...
```

---

## Task A — `geometry.py`

Pure math, no I/O, no PDF knowledge.

1. `Matrix` helpers. Tests: identity is neutral; multiplication order matches PDF `cm`
   semantics (a `cm` concatenates *before* the existing CTM); translation then scale
   composes correctly.
2. `Segment` union and `SubPath` with `anchors` and `bbox`.
3. `fit_circle`. Tests:
   - a synthetically generated 4-cubic circle of ⌀7 at (−40, 18) recovers to <1e-9
   - the same circle under a translation + uniform scale CTM recovers correctly
   - an ellipse (w ≠ h beyond tolerance) returns `None`
   - a 4-segment rounded square returns `None` (kappa check must reject it)
   - a 3-cubic or 5-cubic path returns `None`
   - a degenerate zero-size path returns `None`
4. `pt_to_mm` / `PT_PER_MM`.

## Task B — `pipeline/` stages

Files: `pipeline/snap.py`, `pipeline/diameters.py`, `pipeline/dedupe.py`,
`pipeline/validate.py`, `pipeline/sort.py`. Each class satisfies `Stage`.

1. `SnapPositions(grid: float, warn_over: float | None = None)`
   - `warn_over` defaults to `grid / 4`; `grid == 0` is identity with no diagnostics
   - emits `off-grid` WARNING per hole whose move exceeds `warn_over`, message stating
     the raw position, the delta and the grid
   - **property test: snapping is idempotent**
2. `NormalizeDiameters(strategy: DiameterStrategy)` plus the three strategies in the spec.
   - `ClusterDiameters(0.05)`: 6.9998 and 7.0000 collapse to a single nominal 7.0 —
     assert `len(data.tools()) == 1`
   - `ClusterDiameters` must **not** merge 5.0 with 7.0, nor chain 5.00→5.04→5.08 into one
     group beyond the tolerance from the group representative
   - `TableDiameters([3.2, 5.0, 6.35, 7.0], 0.15)`: 6.98 → 7.0; 4.1 stays 4.1 and emits
     `unknown-diameter`
   - `NoNormalization` is identity
3. `Deduplicate(tolerance: float = 0.05)`
   - collapses only holes that coincide within tolerance **and** share a nominal diameter
   - keeps the first in input order; emits one `duplicate-hole` WARNING per group with the
     collapsed count and location
   - **property test: dedupe is idempotent**
4. `CheckReferenceSize(expected: tuple[float, float], tolerance: float = 0.05)`
   - pure validator, returns holes untouched
   - emits `reference-size-mismatch` WARNING stating total and per-side deltas
   - no reference outline present → emits `no-reference-outline` INFO, does not raise
5. `SortHoles(key=None)` — default descending Y then ascending X; deterministic.

Also: a test that `Pipeline([...]).run()` is a left fold and that stage order is
observable (snap-then-dedupe collapses a near-duplicate that dedupe-then-snap does not).

## Task C — `sources/ai_pdf.py`

`AiPdfSource(path, drill_layer="Drill", reference_layer="Background")` implementing `Source`.

1. Layer discovery from `/OCProperties` → `/OCGs` `/Name`, mapped through
   `/Resources/Properties` to `/MCn`. Populate `SourceInfo.layers_found`.
2. Content-stream walk with `pikepdf.parse_content_stream`: maintain a CTM stack over
   `q`/`Q`/`cm`; track marked-content nesting via `BDC`/`BMC`/`EMC`; collect path
   construction ops `m l c v y h re`; flush on paint ops. **`v` and `y` are the shorthand
   curve forms and must be expanded correctly** — `v` reuses the current point as the first
   control, `y` reuses the endpoint as the second.
3. **Discard clip paths**: a `W` or `W*` before the painting op means the path is a clip,
   not geometry.
4. Reference frame: largest non-circular path bbox on the reference layer; its centre is
   the canonical origin. Never use the MediaBox — the fixture's artboard is A4.
5. Produce `Hole.from_measurement(...)` in millimetres, Y up, relative to that centre.
6. Raise `LayerNotFoundError` / `EmptyLayerError` per the spec.

Tests use `tests/fixtures/tar.ai` and must assert the table in SPEC §9, plus:
`LayerNotFoundError` names the four real layers; the two full-MediaBox clip rectangles do
not appear as geometry.

## Task D — `emitters/excellon.py` and `emitters/json_out.py`

1. `ExcellonEmitter` / `ExcellonOptions(origin=Origin.LOWER_LEFT, units=Units.METRIC, decimals=3)`.
   Tests:
   - header, `FMAT,2`, `METRIC,TZ`, `%`, `G90`, `G05`, `T0`, `M30` all present and ordered
   - **invariant: no two `T..C..` lines share a diameter** — this is the regression that
     motivated the rewrite, assert it explicitly
   - tool numbers equal `DrillData.tools()`; the emitter must not renumber
   - `LOWER_LEFT` yields only non-negative coordinates for the fixture
   - `LOWER_LEFT` without a reference outline raises `EmitterError`
   - `Units.INCHES` divides by 25.4 and writes `INCH,TZ`
   - coordinates are grouped under their tool, tool blocks ascending by diameter
2. `JsonEmitter` — full round trip including `raw` provenance and diagnostics; stable key
   order; parses back with `json.loads`.

## Task E — `emitters/drawing_svg.py`

`DrawingSvgEmitter` / `DrawingOptions(sheet=..., scale=None, title="", drawing_no="", true_size=None)`.

Engineering drawing per SPEC §7. Must render: sheet border, reference outline, optional
true-size overlay, centrelines, origin symbol, hole circles with centre marks, numbered
balloons, per-row chain dimensions via `DrillData.rows()`, overall width/height dimensions,
hole schedule using `DrillData.tools()`, title block, diagnostics as numbered notes with
warnings in red.

Tests: output parses as XML; one `<circle>` per hole at the expected transformed position;
schedule row count equals hole count; every WARNING diagnostic appears in the notes; tool
numbers in the schedule match `data.tools()`; no Graphics-layer rendering is attempted;
vertical dimension text is rotated (no unrotated label may extend past the sheet border).

**Note on SVG text colour:** a CSS rule in `<style>` beats a `fill=` presentation
attribute. Use inline `style="fill:…"` for any text that needs a colour other than the
stylesheet default, or the notes will silently render black.

## Task F — `cli.py` (integration, done last)

Argument surface per SPEC §8. Builds the pipeline in the fixed order
snap → normalize → dedupe → validate → sort, resolves `--emit` through the registry,
writes each artifact, prints a report, returns the documented exit code.

Tests: `--emit` dispatches to a dummy emitter registered only inside the test (the OCP
proof); exit codes; end-to-end on the fixture producing both a `.drl` and an `.svg`.
