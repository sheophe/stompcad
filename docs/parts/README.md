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
`src/aidrill/enclosures.py` — which is generated from this file — each with L, W and H at
0.05 mm. Nothing here is
open, and no extraction remains to be run — the numbers in that file are the
answer, and the `source` column says how each was arrived at:

| `source` | Rows | Meaning |
|---|---|---|
| `extracted` | 25 | read from the drawing's text by the double-conversion fault model in `docs/BACKLOG.md` |
| `extracted(offset (…))` | 6 | the same, where the fault search had to perturb one axis of the coarse value by ±1 mm to land a match |
| `extracted+glyph` | 1 | `1590E`'s width, which the drawing renders as separate glyphs (`1 2 0 0 0`); confirmed against the bracketed imperial `[4.724]`, since 120.00 ÷ 25.4 = 4.7244 |
| `maintainer` | 5 | extraction was genuinely ambiguous — more than one drawing value rounds to the coarse one — so the value was read off the drawing by hand |

The five `maintainer` rows are `1590LB`, `1590G2`, `1590CE`, `1590P1` and
`1590BX` — exactly the five parts `docs/BACKLOG.md` names as carrying an axis the
extraction could not disambiguate. **The TSV is the record; read it rather than
any prose count, including this one.**

## Status: adopted

`src/aidrill/enclosures.py` is generated from `dimensions.tsv` by
`tools/build_catalogue.py`, in exact integer **nanometres**. `docs/1590.pdf` is no longer
the authority — it is the coarse cross-check `tests/test_enclosures.py` runs on every
suite run, asserting that every fine length and width rounded half-up reproduces the
datasheet's own whole millimetre.

Two decisions the adoption settled, both recorded here because both are cheap to write
down and expensive to rediscover:

1. **Nanometres, not microns and not floats.** `docs/BACKLOG.md` had ruled integer
   microns; the unit migration settled the question independently, since every length in
   the model is nanometres and a catalogue in a second unit reintroduces the conversion
   seam the migration exists to remove. `112.40` is not exactly representable in binary;
   `112_400_000` is.
2. **`Decimal`, never float multiplication.** `float("64.60") * 1e6` is
   `64599999.99999999`, so `int()` of it is a 1590CE 0.4 microns short. One of the 111
   values in this file is corrupted by the float spelling, and its being a height nothing
   reads is luck rather than a defence. The generator refuses any figure that is not a
   whole nanometre rather than truncating it.

## Where the fine values disagree with the series datasheet

Round every row with `ROUND_HALF_UP` and compare against `docs/1590.pdf`. **Thirty-five of
the 37 parts agree on all three axes. Two disagree, and only in height:**

| Part | Series datasheet (`docs/1590.pdf`) | Drawing → `ROUND_HALF_UP` |
|---|---|---|
| `1590XX` | H 40 | 39.30 → **39** |
| `1590X` | H 56 | 55.00 → **55** |

One of the two documents is wrong in each case and the PDFs alone cannot say which.
**Neither disagreement can move a match:** a match is against `Enclosure.footprint`, which
is L × W, and `Enclosure.height_nm` is read nowhere in `src/aidrill` at all.
`tests/test_enclosures.py` names both exceptions in a test of their own rather than
carving them out of the cross-check unremarked.

**Use `decimal.ROUND_HALF_UP`, not the builtin,** to reproduce any of this. Hammond rounds
60.50 up to 61; Python's `round()` is banker's rounding and gives 60. Every other axis
agrees under either mode, so a checker using the builtin sees exactly one axis of one part
disagree and reads it as bad data rather than a rounding mode.

## What adoption cost: four footprints split into eight

Every one of the 37 parts agrees with the old coarse table on both L and W *after
rounding* — so it is tempting to conclude that adoption moves no footprint. It does not
follow, and an earlier revision of this file said otherwise and was wrong. The catalogue
is keyed on the **unrounded** figures now, and four outlines that coincided only because
both members rounded to the same whole millimetre no longer coincide:

| Coarse | Fine | Apart |
|---|---|---|
| 51 × 51 | `1590LLB` 50.50 × 50.50, `1590LB` 50.55 × 50.60 | 0.10 mm |
| 125 × 125 | `1590KK` 124.80 × 124.80, `1590K` 125.00 × 125.00 | 0.20 mm |
| 112 × 61 | `1590BS` 112.00 × 60.50, `1590B`/`1590B2` 112.40 × 60.50 | 0.40 mm |
| 188 × 120 | `1590D` 187.75 × 119.50, `1590DD`/`1590E` 188.00 × 120.00 | 0.50 mm |

**22 footprints become 26**, and all four pairs sit inside the 1.5 mm match tolerance, in
both axes. No tolerance separates a 0.10 mm pair while still admitting artwork measured a
millimetre off — which is what a panel drawing is — so a panel near one of them is
genuinely ambiguous from its outline alone and needs an explicit `--case`. That includes
`tests/fixtures/tar.ai`, which measures 113.000 × 60.000 and fits both halves of the
112 × 61 split.

That is the honest answer rather than a regression: the enclosures really do differ, and a
coarser key would be the tool deciding on the operator's behalf that a 112.00 backplate is
a 112.40 one. `docs/adr/0002-domain-quantisers.md` carries the ruling and the amended
arithmetic.

## How the fine values were validated

Matching each drawing's numbers against the coarse table's `ROUND_HALF_UP` disambiguates
which figures are the external dimensions without any layout heuristics, and the match is
itself the check. It is also **circular** — it assumes the coarse table is a faithful
rounding, so it cannot detect a coarse table that is simply wrong. It surfaced `1590XX`
only because the damage there exceeded what any drawing value could satisfy. It confirmed
that `1590B2` and `1590BS` are genuinely different parts (112.40 × 60.50 × 37.50 against
112.00 × 60.50 × 38.00) despite both rounding to 112 × 61 × 38.
