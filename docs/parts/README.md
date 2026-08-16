# Hammond 1590 catalogue data

- Hammond's product website is the upstream source for the published dimensions.
- Manufacturer drawings may exist in a maintainer's local working copy, but they are
  ignored and are not redistributed.
- `dimensions.tsv` contains one row per base part in Hammond's published metric
  dimensions.
- The `source` column records human-readable provenance only; it does not affect catalogue
  generation.
- Length and width are the published top-view/backplate dimensions, not the smaller
  drilled-face dimensions.
- `tools/build_catalogue.py` validates that every dimension is an exact number of
  nanometres and regenerates `src/aidrill/enclosures.py`.
- The fine dimensions produce 26 distinct footprints. Some neighbouring footprints are
  geometrically ambiguous, so an operator must use `--case` to disambiguate them.
