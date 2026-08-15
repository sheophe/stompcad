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
