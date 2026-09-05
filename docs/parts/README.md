# Hammond 1590 catalogue data

[dimensions.tsv](dimensions.tsv) records one row per base part using Hammond's
published metric dimensions. Hammond's product website is the upstream source.
The `source` column records provenance for readers and does not affect catalogue
generation. Manufacturer drawings may be present in a maintainer's local working
copy; they are ignored and are not redistributed.

Length and width describe the published top view or backplate. The drilled face
is smaller. The catalogue contains 26 distinct footprints, and some are close
enough to make a match ambiguous. Use `--case` to identify the intended part
when this happens.

After editing the TSV, regenerate the catalogue from the repository root:

```bash
.venv/bin/python tools/build_catalogue.py
```

The [generator](../../tools/build_catalogue.py) checks that every dimension is an
exact number of nanometres and writes
[enclosures.py](../../packages/stompdrill/src/stompdrill/enclosures.py). Edit the
TSV when changing dimensions; the Python module is generated.
