# Per-part Hammond 1590 drawings

Downloaded from `https://www.hammfg.com/files/parts/pdf/<PART>.pdf`, one per base
designator in `src/aidrill/enclosures.py`.

These carry the **0.05 mm** dimensions that `docs/1590.pdf` rounds to whole
millimetres. `docs/1590.pdf` contains exactly two decimal numbers in the entire
document (both `0.16`, the lid-height note), so it cannot supply them.

**Metric is primary here, imperial is derived.** The drawings print
`112.40 [4.425]` — a clean 0.05 mm value producing an odd imperial one. If
imperial were the source you would see `4.4` or `4.5` producing odd metric.

**"Top View" in these drawings is the lid** — what a pedal builder calls the
backplate, the plate the screws go through. The face that gets drilled for a
pedal is the opposite end of the box, and is *smaller* than the lid because the
walls are drafted at roughly 85°. Hammond does not publish the face dimensions.

## What `dimensions.tsv` holds

**All 37 parts, every axis resolved.** The same 37 base designators as
`src/aidrill/enclosures.py`, each with L, W and H at 0.05 mm. Nothing here is
open, and no extraction remains to be run — the numbers in that file are the
answer, and the `source` column says how each was arrived at:

| `source` | Rows | Meaning |
|---|---|---|
| `extracted` | 25 | read from the drawing's text by the double-conversion fault model in `docs/BACKLOG.md` |
| `extracted(offset (…))` | 6 | the same, where the fault search had to perturb one axis of the coarse value by ±1 mm to land a match |
| `extracted+glyph` | 1 | `1590E`'s width, which the drawing renders as separate glyphs (`1 2 0 0 0`); confirmed against the bracketed imperial `[4.724]`, since 120.00 ÷ 25.4 = 4.7244 |
| `maintainer` | 5 | extraction was genuinely ambiguous — more than one drawing value rounds to the coarse one — so the value was read off the drawing by hand |

The five `maintainer` rows are `1590LB`, `1590G2`, `1590CE`, `1590P1` and
`1590BX` — exactly the five parts `docs/BACKLOG.md` lists as carrying an ambiguous
axis, now decided. Earlier revisions of this file described those axes, and
`1590E`'s missing width, as open questions. They are not open. **The TSV is the
record; read it rather than any prose count, including this one.**

## Status: not adopted into the catalogue

Having the numbers is not the same as shipping them. `src/aidrill/enclosures.py`
still carries the whole-millimetre values `tools/extract_1590.py` derives from
`docs/1590.pdf`, and **nothing under `src/aidrill` reads this directory at all**.
Adoption is agreed and unblocked; what it costs is a decision, not a data hunt:

1. **The dimensions are `int` deliberately.** `Enclosure` and `EnclosureMatch`
   both use whole millimetres, the JSON serialises them as ints, the drawing
   prints them as ints, and tests assert `isinstance(..., int)` to keep them
   distinct from the float `ReferenceOutline`. Adopting floats ripples through
   the model, both emitters, and their tests — which is why `docs/BACKLOG.md`
   rules that the adopted values are stored as **integer microns**, not floats:
   `112.40` is not exactly representable in binary, `112400` is.
2. **Use `decimal.ROUND_HALF_UP`, not the builtin.** Hammond rounds 60.50 up to
   61; Python's `round()` is banker's rounding and gives 60. Every other axis
   agrees under either mode, so a checker using the builtin will see exactly one
   axis of one part disagree and read it as bad data rather than a rounding mode.

## Where the fine values disagree with the shipped catalogue

Round every row of the TSV with `ROUND_HALF_UP` and compare against
`HAMMOND_1590`. **Thirty-five of the 37 parts agree on all three axes. Two
disagree, and only in height:**

| Part | Catalogue (`docs/1590.pdf`) | Drawing → `ROUND_HALF_UP` |
|---|---|---|
| `1590XX` | H 40 | 39.30 → **39** |
| `1590X` | H 56 | 55.00 → **55** |

One of the two documents is wrong in each case, and the PDFs alone cannot say
which. **Neither disagreement can move a match**, and that is worth stating
plainly rather than leaving to be rediscovered: a match is against
`Enclosure.footprint`, which is L × W, and `Enclosure.height_mm` is stored but
read nowhere in `src/aidrill` at all. The disagreement is confined to height, and
**every one of the 37 parts agrees with the catalogue on both L and W** — so no
footprint changes and no tie is created or broken. What adoption buys is
precision, not a different answer.

The round-trip validation that produced these values is worth keeping: matching
each drawing's numbers against the coarse table's `ROUND_HALF_UP` disambiguates
which figures are the external dimensions without any layout heuristics, and the
match is itself the check. It is also **circular** — it assumes the coarse table
is a faithful rounding, so it cannot detect a coarse table that is simply wrong.
It surfaced `1590XX` only because the damage there exceeded what any drawing
value could satisfy. It confirmed that `1590B2` and `1590BS` are genuinely
different parts (112.40 × 60.50 × 37.50 against 112.00 × 60.50 × 38.00) despite
both rounding to 112 × 61 × 38.
