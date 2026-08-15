# Backlog

Work that is agreed and worth doing, but deliberately not scheduled yet. Each entry
records enough context to start cold.

---

## Paired redundancy review — target ~15% source reduction

**Status:** agreed, not started · **Raised:** 2026-08-15

A deep review by Claude paired with Codex, looking specifically for redundancy,
verbosity and code duplication, then fixing the findings. The realistic target is a
**~15% reduction in source lines with no loss of function**.

### Why the number is 15% and not 50%

An earlier 50% figure was an exaggeration, and both reviewers independently rejected
it. Source is ~4,200 lines, of which three modules are ~2,070:

| Module | Lines | What it actually does |
|---|---|---|
| `emitters/drawing_svg.py` | ~1,140 | A complete dimensioned engineering sheet |
| `sources/ai_pdf.py` | ~580 | A small PDF graphics interpreter |
| `geometry.py` | ~350 | Bézier circle fitting with rotation-invariant validation |

That is real behaviour, not padding. Halving the total would mean deleting features
or deleting documentation, and this codebase's module docstrings — the ones that name
the specific bug that motivated each design — have repeatedly proved load-bearing
during review. They are not the fat.

### Where the fat actually is

Concrete candidates already identified, with evidence:

- **`_draw_overall` is two ~40-line near-copies** (`drawing_svg.py`), differing only in
  axis: extension lines → dimension line → two arrowheads → label. The vertical branch
  adds `rotate(-90)` on the label and nothing else. One `_linear_dimension(parent,
  layout, a, b, offset, axis, label, cls)` helper collapses both.
- **`_draw_schedule` is ~127 lines** interleaving capacity arithmetic (`pitch`,
  `overflow`, `capacity`) with five-column rendering. Extracting
  `_schedule_metrics(...) -> ScheduleMetrics` separates the hard part from the drawing
  and makes the truncation rule unit-testable without parsing SVG.
- **Three competing number formatters in one file**: `format_mm` (imported), `_trim`
  (`.4f` + rstrip) and `_fmt` (`.6f` + rstrip + int passthrough). `_trim` is `_fmt`
  with a different precision and no type dispatch.
- **Magic numbers named only partially.** `drawing_svg.py` carefully names
  `_LEFT_ALLOWANCE`, `_ROW_PITCH`, `_GUTTER` … and then uses raw literals for the
  stroke-weight ladder (0.5/0.4/0.35/0.3/0.25/0.2/0.15) and the font ladder
  (2.2/2.4/2.6/3.2/4.4) throughout. Partial naming is worse than either extreme,
  because a reader assumes the convention holds.
- **`_PathBuilder.construct` repeats a six-branch guard verbatim** (`ai_pdf.py`):
  `values = _numbers(operands, N); if values is None: return`. A
  `_OPERAND_COUNTS = {"m": 2, "l": 2, "c": 6, "v": 4, "y": 4, "re": 4}` table plus one
  guard at the top replaces all six.
- **`_walk` is a 67-line operator dispatch** (`ai_pdf.py`) — readable today thanks to
  its section banners, but the shape that grows badly.
- **Test-side duplication**: the border-containment assertion block is written out five
  times in `test_drawing_svg.py` with the same magic `0.6` slack, and the
  `emitter → ET.fromstring → layout` preamble appears ~15 times. Helpers would remove
  roughly 80 lines from that file alone.

### Method

Pair the two reviewers rather than running one: they have already disagreed
productively on this codebase, and duplication findings are exactly where a second
opinion stops a "simplification" that quietly changes behaviour. Every change must be
covered by the existing suite plus a mutation check — a refactor that survives
mutation testing is a refactor; one that does not was a behaviour change wearing a
refactor's clothes.

### Explicitly not in scope

- Deleting module docstrings or the *why* they record.
- Splitting `drawing_svg.py` into a package. That is a separate call, and the current
  judgement is to defer it until a concrete boundary reduces real change friction.

---

## Adopt 0.05 mm catalogue values from the per-part drawings

**Status:** method proven, blocked on two residues · **Raised:** 2026-08-15

`src/aidrill/enclosures.py` carries whole-millimetre dimensions from
`docs/1590.pdf`. The per-part drawings in `docs/parts/` carry the real 0.05 mm
values. Adopting them makes the catalogue match what Hammond actually specifies.

### Why the obvious extraction does not work

A part drawing states 14–16 dimensions; only three are the external L/W/H, and
nothing in the extractable text labels which. Two approaches were tried:

- **Match against the coarse table under `ROUND_HALF_UP`.** Resolved 36/37, but
  the method is **circular**: it assumes the table is a faithful rounding, so it
  cannot detect a table that is wrong. It surfaced `1590XX` only because the
  damage there was too large for any drawing value to satisfy the assumption.
- **Pair metric with imperial by token adjacency.** Spurious — the drawing layout
  interleaves them, producing pairs like `27.00 [4.425]` that are not conversions.

### The method that works

Hammond's catalogue values are **double-converted**: the true metric goes to
inches at two decimals, then back to whole millimetres. Reproduce that fault and
invert it.

1. Extract every number from the part drawing (the model is in the filename, so
   no model detection is needed).
2. Apply the fault to each: `mm → inch (2 dp, ROUND_CEILING) → mm (whole,
   ROUND_HALF_UP)`. Build `{faulted: original_0.05mm}`.
3. Look up the coarse catalogue's three values in that map.

The transform was **fitted, not guessed** — all nine combinations of
half-up/ceil/floor at the two steps were tried; `ceil` then `half_up` reproduces
the most parts.

### Fuzzy search, and why it is cheap

The product pages follow the fault exactly; the series table mostly does but
sometimes misses by 1 mm, never more. So search offsets of −1/0/+1 per axis,
**ordered by how many axes are perturbed** — exact first, then one-of-three, then
two, then three. Measured over all 37 parts:

| | |
|---|---|
| Resolved | 36 / 37 |
| Exact, no perturbation | 29 parts |
| One axis perturbed | 7 parts |
| Two or three axes | **0 parts** |
| Candidates tried, max | 7 of a possible 27 |
| Candidates tried, mean | 1.7 |

The ordering is what makes it cheap: the worst case is never reached.

### The two residues, both needing a human

1. **Five parts have an ambiguous axis** — more than one drawing value maps to the
   same catalogue value: `1590LB` 51 ← [50.55, 50.60]; `1590G2` 31 ← [31.00,
   31.20]; `1590CE` 65 ← [64.57, 64.60]; `1590P1` 83 ← [83.00, 83.10]; `1590BX`
   50 ← [49.50, 49.88, 50.00]. Resolvable from the drawing geometry, or by
   preferring the value that is itself an exact match — but not by guessing.
2. **`1590E` has no width in its drawing's text.** Nothing between 115.40 and 188,
   where siblings `1590D` and `1590DD` carry 119.50 and 120.00. A gap in the
   source.

### What else changes

- `Enclosure` and `EnclosureMatch` dimensions are `int` deliberately — the JSON
  serialises them as ints, the drawing prints them as ints, and tests assert
  `isinstance(..., int)` to keep them distinct from the float `ReferenceOutline`.
  Floats ripple through the model, both emitters and their tests.
- **Use `decimal.ROUND_HALF_UP`, never the builtin.** Hammond rounds 60.50 up to
  61; Python's `round()` is banker's rounding and gives 60. Every other axis
  agrees under either mode, so a checker using `round()` sees exactly one axis of
  one part disagree and reads it as bad data rather than a rounding mode.

### The prize

Once the true values exist, a footprint can be matched against **every published
form of itself** — the true value, the series table's rounding, and the website's
double conversion. `tests/fixtures/tar.ai` measures 113.000 × 60.000 because it
was drawn from the product page; it would then match 1590B **exactly, with no
tolerance**, and the match could report which published form it recognised. That
removes the 1.5 mm tolerance rather than widening it, and shrinks the ambiguity
risk instead of growing it.

Note this does **not** address the draft-angle problem — see the backplate
convention in `CLAUDE.md`. That offset is depth-dependent and unpublished.

### Update: the residue is five numbers, not a pipeline

`1590E` is **resolved without further tooling**. Its width renders as individual
glyphs (`1 2 0 0 0`) rather than one text run, which is why word-level extraction
missed it — but the bracketed imperial beneath reads `[4.724]`, and
120.00 ÷ 25.4 = 4.7244. The two agree, so the value is known: **120.00 mm**.

That leaves **five ambiguous axes**, each a choice between candidates already
extracted:

| Part | Axis | Candidates |
|---|---|---|
| 1590LB | 51 | 50.55, 50.60 |
| 1590G2 | 31 | 31.00, 31.20 |
| 1590CE | 65 | 64.57, 64.60 |
| 1590P1 | 83 | 83.00, 83.10 |
| 1590BX | 50 | 49.50, 49.88, 50.00 |

Five glances at five drawings. **Do not build more extraction machinery for this.**

### The principled alternative, deliberately not taken

Hammond publishes `.x_t` (Parasolid), `.dwg`, and `.igs`/`.stp` alongside each
drawing. A STEP or Parasolid file carries exact geometry, so a bounding box read
from it needs no rounding archaeology and no glyph grouping — it is the correct
answer if this ever had to scale, or to run against a manufacturer who publishes
no dimension table at all.

It is not worth it here: 37 parts, once, with 97% already resolved. A CAD-parsing
pipeline adds a dependency and a maintenance surface for a job that never repeats,
and would cost more than the five numbers left.

**What is worth keeping is the fault model, not the extractor.** That Hammond's
tables are double-converted, and that Hammond rounds half-up where Python rounds
half-even, is what makes the *next* discrepancy legible rather than mysterious.
