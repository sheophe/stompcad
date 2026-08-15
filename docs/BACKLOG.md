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

**Status:** unblocked, not started · **Raised:** 2026-08-15

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

### Where the fuzzy search stopped, and who finished it

The search leaves two kinds of residue, and both were closed by hand rather than
by more machinery — which is the recommendation if a datasheet revision reopens
them:

1. **An ambiguous axis**, where more than one drawing value maps to the same
   catalogue value — `1590LB` 51 ← [50.55, 50.60]; `1590G2` 31 ← [31.00, 31.20];
   `1590CE` 65 ← [64.57, 64.60]; `1590P1` 83 ← [83.00, 83.10]; `1590BX`
   50 ← [49.50, 49.88, 50.00]. Five glances at five drawings.
   **Do not build more extraction machinery for this.**
2. **A value the text extraction cannot see.** `1590E`'s width renders as
   individual glyphs (`1 2 0 0 0`) rather than one text run, so word-level
   extraction misses it; the bracketed imperial beneath reads `[4.724]`, and
   120.00 ÷ 25.4 = 4.7244, so the two agree and the value is **120.00 mm**.

`docs/parts/dimensions.tsv` holds the result for all 37 parts, and its `source`
column records which route each value came by. **That file is the record — read
it rather than any prose count, including this one.**

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

### The principled alternative, deliberately not taken

Hammond publishes `.x_t` (Parasolid), `.dwg`, and `.igs`/`.stp` alongside each
drawing. A STEP or Parasolid file carries exact geometry, so a bounding box read
from it needs no rounding archaeology and no glyph grouping — it is the correct
answer if this ever had to scale, or to run against a manufacturer who publishes
no dimension table at all.

It is not worth it here: 37 parts, once, all resolved. A CAD-parsing pipeline adds
a dependency and a maintenance surface for a job that never repeats.

**What is worth keeping is the fault model, not the extractor.** That Hammond's
tables are double-converted, and that Hammond rounds half-up where Python rounds
half-even, is what makes the *next* discrepancy legible rather than mysterious.

### Represent catalogue dimensions as integer microns, not floats

**Decided 2026-08-15.** `docs/parts/dimensions.tsv` carries all 37 parts at
0.05 mm precision, so adoption is unblocked. Store them as **integer microns**,
not floats.

**Adoption moves no footprint, and that is what makes it safe to schedule.** Round
every TSV row with `decimal.ROUND_HALF_UP` and compare against `HAMMOND_1590`:
**all 37 parts agree on both length and width**, and the only two disagreements —
`1590XX` (H 39.30 → 39 against a catalogue 40) and `1590X` (H 55.00 → 55 against
56) — are in **height alone**. Matching is 2-D, against `Enclosure.footprint`, and
`Enclosure.height_mm` is stored but **read nowhere in `src/aidrill`**. So no
footprint changes, no tie is created or broken, and no panel that matches today
stops matching. What adoption buys is precision, not a different answer. (Both
claims are cheap to re-check and worth re-checking after any datasheet revision;
`docs/parts/README.md` records the same comparison.)

`112.40` is not exactly representable in binary floating point — it is
`112.40000000000000568…` — so equality on catalogue values is fragile and any
averaging accumulates error. `112400` is exact and stays exact. This is the
fixed-point discipline banks and exchanges use for prices, and for the same
reason: a specified quantity is not a measured one.

**The split is principled, and it is a real cost.** Measurements cannot be
integers — the PDF yields `113.00001388888887` from Bézier fitting, and that *is*
a measurement. So the codebase gains a second unit, which is exactly what SPEC
§2.2's "one canonical frame" rule exists to prevent. Accept it on these terms:

- **Measurements are floats in millimetres.** `ReferenceOutline.width`, `Hole.x`,
  everything the source produces. Unchanged.
- **Specifications are integers in microns.** `Enclosure`, `EnclosureMatch`, the
  drill standards' sizes. Exact, comparable with `==`, never averaged.
- **Every integer field carries a `_um` suffix**, and conversion happens only at
  named boundaries — the way `pt_to_mm` already marks the one place PDF points
  become millimetres. A unit error should be visible at the call site.
- The existing `isinstance(..., int)` tests keep their job: they now pin
  microns-vs-millimetres rather than ints-vs-floats, which is a stronger claim.

**It also makes the published-variant idea exact.** With integer microns, every
published form of a footprint — true value, series-table rounding, website double
conversion — is an integer, so matching `tests/fixtures/tar.ai`'s 113 × 60 against
a generated variant is `==` with no tolerance and no epsilon in the comparison at
all. That is the version of variant matching worth building.

**Scope.** Touches `Enclosure`, `EnclosureMatch`, `IdentifyHammondFootprint`, both
emitters and their tests. In the JSON document `length_mm: 112` becomes
`length_um: 112400`; bump the document's `version` field with it, so the two keys
can never be read as the same unit under one number.

---

## Adopt mypy `strict` on `src/aidrill`

**Status:** agreed, not started · **Raised:** 2026-08-15

`[tool.mypy]` was configured with `python_version = "3.10"`, `warn_unused_ignores`,
`warn_redundant_casts` and `warn_unreachable`, and the tree is clean under it.
`strict` was deliberately not adopted, because it is not a setting so much as a
piece of work: measured at the time of writing, it is **18 further errors**, and a
gate that arrives red is the thing that configuration was fixing.

The delta is narrow and boring, which is why it is worth doing rather than
arguing about:

- **~14 `no-untyped-def`**, all on definitions that were never annotated rather
  than annotated wrongly: `model.py`'s alternate constructors (`Diagnostic.warning`
  / `.info` / `.error`, the `get` helpers) and six internal helpers in
  `sources/ai_pdf.py`, plus `protocols.py`'s `Pipeline.__getitem__` and one
  function in `emitters/drawing_svg.py`.
- The remainder is `no-untyped-call` and `no-any-return` falling out of those, and
  one `unused-ignore` where a suppression stops matching once its neighbours are
  typed.

`Pipeline.__getitem__` is the one that needs a decision rather than a signature:
typing it properly means overloads for `int` and `slice`, since `Sequence`
declares both and this returns `self._stages[index]` for either.

**Do it in one commit per module, not one for the flag**, so that a test failure
has one file to look at.

---

## `import aidrill` now costs a pikepdf import

**Status:** noted, no action agreed · **Raised:** 2026-08-15

Exporting `AiPdfSource` from the package root — which is what makes the only
`Source` findable, since there is no source registry — means `import aidrill`
imports `.sources`, and therefore `pikepdf`, which it did not before.

This is defensible: `pikepdf` is the sole runtime dependency, so nothing new is
*installed*, and a consumer that reads a `.ai` file was always going to pay it.
But it is a real change in import cost for the wider pedal-design toolchain,
whose interest in this library may be no more than `DrillData` and the `json`
emitter, and which now pays a C-extension import to get them.

If it ever matters, the fix is a module-level `__getattr__` in
`src/aidrill/__init__.py` resolving `AiPdfSource` lazily (PEP 562). Do not do it
speculatively — it trades a measurable cost for an invisible one, and `__all__`
would then name something `dir()` does not.

---

## Chain-dimension segments are unmeasured by any test

**Status:** found during review, not scheduled · **Raised:** 2026-08-15

`_draw_row_chains`'s loop over consecutive station pairs in `emitters/drawing_svg.py`
can be made to skip its first pair — the whole first chain segment — with the
suite still fully green. Verified by mutation: replacing the iteration with one
that drops the first element leaves **732 passed**.

`test_chain_dimension_values_are_hole_to_hole_distances` does die when the row
*grouping* underneath it is broken, so rows are covered; what is not covered is
that every consecutive pair in a row actually gets a dimension drawn. A row whose
first gap is silently undimensioned is precisely the "holes with no dimension
beside them" failure the module docstring says the `_allot` work was done to stop,
so this one has form.

The test to write asserts the *count* of `dim-line` elements per row against
`len(stations) - 1`, on a fixture with at least three holes in one row — two holes
make one pair, where dropping the first and dropping the last are the same bug.
