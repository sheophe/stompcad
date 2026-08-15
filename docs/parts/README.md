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

## Status: not yet adopted into the catalogue

`enclosures.py` still carries the whole-millimetre values derived from
`docs/1590.pdf` by `tools/extract_1590.py`. Adopting these finer values is agreed
but needs care, not a data swap:

1. **8 axes across 6 parts are ambiguous** — more than one number on the drawing
   rounds to the coarse value. `1590LB` L/W (50.55 vs 50.60), `1590G2` H (31.0 vs
   31.2), `1590CE` W (100.0 vs 100.41) and H (64.57 vs 64.60), `1590P1` W (83.0 vs
   83.1) and H (50.0 vs 50.4), `1590BX` H (49.5 vs 49.88 vs 50.0). "Largest is
   external" is a plausible heuristic, not a fact — a flange can exceed the body.
   These want resolving against the drawing layout.
2. **`1590XX` conflicts outright.** `docs/1590.pdf` says its height is 40; the
   part drawing's only nearby figure is 39.3, which rounds to 39. One of the two
   documents is wrong and the PDFs alone cannot say which.
3. **The dimensions are `int` deliberately.** `Enclosure` and `EnclosureMatch`
   both use whole millimetres, the JSON serialises them as ints, the drawing
   prints them as ints, and tests assert `isinstance(..., int)` to keep them
   distinct from the float `ReferenceOutline`. Adopting floats ripples through
   the model, both emitters, and their tests.
4. **Use `decimal.ROUND_HALF_UP`, not the builtin.** Hammond rounds 60.50 up to
   61; Python's `round()` is banker's rounding and gives 60. Every other axis
   agrees under either mode, so a checker using the builtin will see exactly one
   axis of one part disagree and read it as bad data rather than a rounding mode.

The round-trip validation that produced this list is worth keeping: matching each
drawing's numbers against the coarse table's `ROUND_HALF_UP` disambiguates which
figures are the external dimensions without any layout heuristics, and the match
is itself the check. It confirmed that `1590B2` and `1590BS` are genuinely
different parts (112.40 × 60.50 × 37.50 against 112.00 × 60.50 × 38.00) despite
both rounding to 112 × 61 × 38.
