"""Derive the Hammond 1590 catalogue from the drawings the repo ships.

``src/aidrill/enclosures.py`` is *generated* by this script, never typed. The
values are physical constants: a wrong length means a panel drilled to fit a
case the operator does not own, discovered in aluminium rather than in a test.
Hand-transcribing 37 part numbers and 111 dimensions is exactly the task a human
gets wrong silently, so the drawings are the authority and this script is the
audit trail. A revision is a re-run of ``python tools/build_catalogue.py``, not a
re-typing, and ``test_enclosures.py`` re-derives on every suite run so a revision
shows up as a red test rather than as a quiet disagreement.

Two sources, and only one of them is the authority
--------------------------------------------------

``docs/parts/dimensions.tsv`` carries all 37 base parts at **0.05 mm**, read off
Hammond's per-part drawings; ``docs/parts/README.md`` records how each row was
arrived at. That file is what the catalogue is built from.

``docs/1590.pdf`` — the series datasheet — gives the same 37 parts at **whole
millimetres**, and stays here as an independent **coarse cross-check**:
`extract_series` reads it, and ``test_enclosures.py`` asserts that every fine
length and width, rounded half-up, reproduces the datasheet's own integer. Two
documents agreeing is a far stronger claim than one document read twice, which is
all a re-run of a single extractor ever proves. The two disagree in *height* on
``1590XX`` and ``1590X``, and only there; the test states that exception rather
than hiding it, because nothing in ``src/aidrill`` reads a height at all.

``pdfplumber`` is a **development** dependency and must stay one. Nothing under
``src/aidrill`` may import it: the shipped catalogue is a literal table, so the
runtime never opens a PDF.

Nanometres, through ``Decimal``, never through float multiplication
-------------------------------------------------------------------

The catalogue is emitted in exact integer nanometres, because that is the unit
every length in the model is held in and a millimetre seam at the catalogue's
edge is a factor of a million waiting to be applied twice or not at all.

The conversion goes through ``Decimal`` and the exactness is *checked*, not
assumed. ``float("64.60") * 1e6`` is ``64599999.99999999``: one of the 111 values
in the shipped TSV is already corrupted by the float spelling, and the fact that
it happens to be a height nothing reads is luck rather than a defence.
``Decimal("64.60") * 1_000_000`` is ``64600000`` exactly, and `_nanometres`
refuses anything that does not land on a whole nanometre rather than truncating
it — a future row quoted finer than 0.000001 mm is then a failed generation and
not a silently shortened case.

Reading the series table
------------------------

``page.extract_tables()`` yields 11-column rows. Column 0 is the part number of
the *standard, no-mounting-flange* version, column 6 is the colour, and columns
7, 8 and 9 are Length, Width and Height in whole millimetres.

Rows whose cells pdfplumber failed to split put the whole line in column 0 and
``None`` in columns 1-10, so column 0 is a sentence rather than a part number and
the row is rejected by the **part-number match**, before the digits are ever
looked at. Every enclosure in the datasheet is listed at least twice -- once per
colour -- so no size is lost to a merged row; the natural-finish row and the
black row carry identical dimensions.

The ``1590F`` collision
-----------------------

Collapsing colour, watertight and flange decorations to a base designator is
ambiguous by construction, because ``1590F`` is a real 188 x 188 x 67 enclosure
*and* is what "1590 with a flanged bottom plate" would be spelled. Stripping a
trailing ``F`` turns the real part into a bare ``1590``, which is a family name
and not a catalogue part at all. ``_base_designator`` therefore backs the flange
strip out when it lands on the bare family name. The datasheet settles the
question in the row itself: ``1590F``'s own flanged variants are listed
alongside it as ``1590FFL`` and ``1590FF``, and its watertight version as
``1590WF``.

That last name is why the watertight prefix is stripped *first*. Only the flange
step is ambiguous, so only the flange step may be undone; backing out to the raw
colour-stripped input would discard the ``1590W`` reduction too and leave
``1590WF`` uncollapsed.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator, Sequence
from decimal import Decimal
from pathlib import Path

__all__ = [
    "FAMILY",
    "read_drawings",
    "extract_series",
    "render_module",
    "main",
]

#: The family root. Not a part: no row of the datasheet gives it dimensions, and
#: a collapse that lands here has stripped one character too many.
FAMILY = "1590"

#: A part number cell, as opposed to a whole row pdfplumber failed to split.
_PART = re.compile(r"1590[A-Z0-9]*")

#: Colour suffixes, per the datasheet's own colour column.
_COLOR = re.compile(r"(BK|CB|GR|LG|OR|PR|RD|YL)$")

#: Flanged-lid and flanged-bottom-plate suffixes.
_FLANGE = re.compile(r"(FL|F)$")

#: The watertight versions carry a ``W`` immediately after the family root.
_WATERTIGHT = "1590W"

#: Columns 7, 8, 9 of the enclosure table. Column 6 is the colour, which never
#: reaches the catalogue: a finish cannot move a hole.
_LENGTH, _WIDTH, _HEIGHT = 7, 8, 9

#: The narrowest row we will look at. The screw-and-gasket tables later in the
#: datasheet are 10 columns wide and would put part numbers where dimensions
#: belong, so width alone does not qualify a row -- the digit test does.
_MIN_COLUMNS = 10

#: Spelled here rather than imported from ``aidrill.units``, on the same argument
#: ``tests/test_enclosure.py`` makes for spelling it a third time: a generator
#: that took the factor from the package it generates part of could not tell a
#: correct conversion from a consistently wrong one. It is also a definition, not
#: a decision -- there is nothing here for the two spellings to drift about.
_NM_PER_MM = 1_000_000

#: The TSV's own columns. The fifth, ``source``, records how the maintainer
#: arrived at the row and is provenance for a human: two values reached by
#: different routes are still the same length, so nothing here reads it.
_TSV_COLUMNS = 5


def _base_designator(part: str) -> str:
    """Reduce a catalogue part number to the designator that names its shape.

    Colour, watertight and flange variants of one enclosure share an outline, so
    they share a footprint and must collapse together.

    Order matters, and so does what the back-out undoes. The watertight prefix
    is removed *before* the flange suffix so that only the flange step is ever in
    doubt, and the back-out then returns the prefix-stripped name rather than the
    raw input -- an earlier version returned the colour-stripped string and threw
    away the ``1590W`` reduction along with the flange one, so ``1590WF`` stayed
    ``1590WF`` instead of collapsing to ``1590F``. ``1590WF`` is a real part,
    printed beside ``1590F`` in the datasheet; no column-0 cell in this revision
    is both watertight and flanged, so nothing caught it, but this function is a
    general collapse and a caller resolving an operator-typed part number would
    have been handed an enclosure that does not exist.

    The back-out itself is the ``1590F`` collision described above.
    """
    coloured = _COLOR.sub("", part)
    if coloured.startswith(_WATERTIGHT):
        coloured = FAMILY + coloured[len(_WATERTIGHT) :]
    without_flange = _FLANGE.sub("", coloured)
    return coloured if without_flange == FAMILY else without_flange


def _nanometres(millimetres: str) -> int:
    """A millimetre figure from a drawing, as exact whole nanometres.

    ``Decimal`` and not ``float``: ``float("64.60") * 1e6`` is 64 599 999.99999999
    and ``int()`` of it is 64 599 999, a case 0.4 microns short of the one Hammond
    casts. ``Decimal("64.60") * 1_000_000`` is 64 600 000, exactly, for that value
    and for the other 110.

    The remainder is refused rather than rounded because this is a *generator*
    and there is no measurement here to round: every figure it reads is a
    published constant, so one that does not land on a whole nanometre means the
    source now quotes finer than the unit can hold, and truncating it would ship
    a catalogue that silently disagrees with the drawing it was read from.
    """
    scaled = Decimal(millimetres) * _NM_PER_MM
    whole = scaled.to_integral_value()
    if scaled != whole:
        raise ValueError(
            f"{millimetres} mm is not a whole number of nanometres ({scaled})"
        )
    return int(whole)


def _drawing_row(line: str) -> tuple[str, int, int, int] | None:
    """``(part, length_nm, width_nm, height_nm)`` for a TSV data row, else ``None``.

    Pure, and separate from the file reading, for the reason `_dimensioned_row`
    is: this is where the file's shape is decided. Two things are skipped, and a
    third deliberately is not:

    * a ``#`` comment line, which the TSV uses for the header block explaining
      that these are backplate dimensions;
    * the column-name row, recognised by its first cell rather than by position,
      so that a comment added above it cannot shift which line is the header;
    * a row with the wrong number of columns is **not** skipped -- it raises. A
      malformed catalogue row is a defect in the one file this script trusts, and
      quietly dropping it would ship a catalogue missing an enclosure.
    """
    if line.startswith("#") or not line.strip():
        return None
    cells = line.split("\t")
    if cells[0] == "part":
        return None
    if len(cells) != _TSV_COLUMNS:
        raise ValueError(f"expected {_TSV_COLUMNS} tab-separated columns, got {line!r}")
    part, length, width, height, _source = cells
    return part, _nanometres(length), _nanometres(width), _nanometres(height)


def read_drawings(tsv_path: str | Path) -> set[tuple[str, int, int, int]]:
    """Every ``(part, length_nm, width_nm, height_nm)`` in the per-part drawings.

    The authority. A set, to match `extract_series`'s shape -- but unlike the
    datasheet, which lists each enclosure once per colour, this file holds one
    row per base part already, and `main` checks that nothing collapsed.
    """
    lines = Path(tsv_path).read_text(encoding="utf-8").splitlines()
    rows = (_drawing_row(line) for line in lines)
    return {row for row in rows if row is not None}


def _dimensioned_row(row: Sequence[str | None]) -> tuple[str, int, int, int] | None:
    """``(part, length, width, height)`` for an enclosure row, else ``None``.

    Whole millimetres, because that is what the series datasheet prints. Pure,
    and separate from the PDF reading, because this is where the extraction
    decides what counts as data. Three rejections, by three different tests --
    which is worth stating precisely, because a docstring here previously
    credited the wrong one and made a test look like it covered something it did
    not:

    * a row pdfplumber failed to split puts the whole line in column 0, so
      column 0 is a sentence and fails the **part-number match**;
    * the screw and gasket tables later in the datasheet are 10 columns wide and
      put *part numbers* where dimensions belong, so they pass the part-number
      match and fail the **digit test** on columns 7-9;
    * a part number outside the 1590 family passes both of the above and is
      rejected by the **family** part of the part-number match --
      ``HAMMOND_1590`` is a family catalogue, and a revision that appends another
      family must not quietly widen it.
    """
    if len(row) < _MIN_COLUMNS:
        return None
    part = row[0]
    if not part or not _PART.fullmatch(part):
        return None
    dimensions = row[_LENGTH : _HEIGHT + 1]
    if not all(cell and cell.isdigit() for cell in dimensions):
        return None
    length, width, height = (int(cell) for cell in dimensions)  # type: ignore[arg-type]
    return part, length, width, height


def _dimensioned_rows(pdf_path: Path) -> Iterator[tuple[str, int, int, int]]:
    """Yield every dimensioned row of every table in the datasheet.

    ``pdfplumber`` is imported lazily so that importing this module -- which the
    test suite does -- does not require it until a PDF is actually read.
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    dimensioned = _dimensioned_row(row)
                    if dimensioned is not None:
                        yield dimensioned


def extract_series(pdf_path: str | Path) -> set[tuple[str, int, int, int]]:
    """Every distinct ``(base_part, length_mm, width_mm, height_mm)`` in the PDF.

    The coarse cross-check, in whole millimetres, and no longer what the shipped
    catalogue is built from. A set, because the datasheet lists each enclosure
    once per colour and those rows are the same enclosure. Two *different* parts
    may still share all three dimensions at this precision -- ``1590B2`` and
    ``1590BS`` both round to 112 x 61 x 38, and the drawings say they are
    112.40 x 60.50 x 37.50 and 112.00 x 60.50 x 38.00 -- so the part number stays
    in the tuple and the set holds one entry per part, not per size.
    """
    return {
        (_base_designator(part), length, width, height)
        for part, length, width, height in _dimensioned_rows(Path(pdf_path))
    }


_HEADER = '''"""The Hammond 1590 enclosure catalogue, as the reference outline to match.

**Generated by ``tools/build_catalogue.py`` from ``docs/parts/dimensions.tsv``.
Do not edit by hand.** These are physical constants, and a value that drifts from
the drawings is a panel drilled for a case that does not exist. Re-run the script
when Hammond revises them; ``tests/test_enclosures.py`` re-derives on every suite
run so a revision cannot land silently, and cross-checks the result against the
series datasheet in ``docs/1590.pdf``.

The reference outline an operator draws is measured artwork, off by a fraction of
a millimetre in both axes. Matching it against this catalogue turns "roughly
112 x 61" into a named footprint, and that footprint's dimensions are what the
drawing and the drill file then agree on.

Dimensions are exact integer **nanometres**, converted from the 0.05 mm figures
Hammond's per-part drawings publish. Hammond specifies in metric and derives
imperial -- the 1590B drawing prints ``112.40 [4.425]``, a clean metric value
producing an odd imperial one -- so 112.40 mm is the specified figure and
112 400 000 nm is it, exactly, where 112.4 as a float is not.

Heights **include the lid**, which the datasheet states is 0.16" (4 mm). An
internal-depth question therefore needs 4 mm taken off first -- not that aidrill
asks one, since it does not model enclosures in 3-D. Nothing in ``src/aidrill``
reads ``height_nm`` at all: a panel drawing carries no height, so it cannot
identify one.

A footprint, not a part, is what artwork can identify: parts differing only in
height share one outline. ``footprints()`` maps each L x W to every base part
that shares it, so a match names candidates and never guesses between them.

**At 0.05 mm, parts that shared a whole-millimetre outline stop sharing one.**
1590B and 1590B2 are 112.40 x 60.50 where 1590BS is 112.00 x 60.50: one footprint
when both rounded to 112 x 61, two here. Four such pairs sit closer together than
any tolerance that can also absorb the error in measured artwork, so a panel near
one of them is genuinely ambiguous from its outline alone and needs the operator
to declare a case. Reporting that is the honest answer; a coarser key would be
the tool deciding a 112.00 backplate is a 112.40 one on the operator's behalf.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = ["Enclosure", "HAMMOND_1590", "footprints"]


@dataclass(frozen=True, slots=True)
class Enclosure:
    """One catalogue part: a base designator and its outside dimensions in nanometres."""

    part: str
    length_nm: int
    width_nm: int
    height_nm: int

    @property
    def footprint(self) -> tuple[int, int]:
        """The 2-D outline, which is all a panel drawing can distinguish."""
        return (self.length_nm, self.width_nm)


#: Every base part in the drawings, ordered by footprint then height so that
#: parts sharing an outline sit together.
HAMMOND_1590: tuple[Enclosure, ...] = (
'''

_FOOTER = ''')


def footprints() -> Mapping[tuple[int, int], tuple[str, ...]]:
    """Each L x W outline in nanometres, mapped to every base part that has it, sorted.

    Sorted, and read-only, because a matcher reports these candidates to the
    operator: an order that depended on catalogue order would make the drawing's
    text change when an unrelated part was added, and a caller that mutated the
    mapping would corrupt every later match in the process.
    """
    return _FOOTPRINTS


def _build_footprints() -> Mapping[tuple[int, int], tuple[str, ...]]:
    grouped: dict[tuple[int, int], list[str]] = {}
    for enclosure in HAMMOND_1590:
        grouped.setdefault(enclosure.footprint, []).append(enclosure.part)
    return MappingProxyType(
        {outline: tuple(sorted(parts)) for outline, parts in grouped.items()}
    )


_FOOTPRINTS = _build_footprints()
'''


def render_module(catalogue: set[tuple[str, int, int, int]]) -> str:
    """The full text of ``src/aidrill/enclosures.py`` for a given extraction.

    Nanometres are grouped with underscores -- ``112_400_000`` -- because nine
    digits in a row is where a table stops being readable and a transposed pair
    stops being visible, and this is a file whose whole job is to be checked
    against a drawing by eye.
    """
    ordered = sorted(catalogue, key=lambda e: (e[1], e[2], e[3], e[0]))
    rows = "".join(
        f'    Enclosure("{part}", {length:_}, {width:_}, {height:_}),\n'
        for part, length, width, height in ordered
    )
    return _HEADER + rows + _FOOTER


def main(argv: list[str] | None = None) -> int:
    """Regenerate the catalogue module in place.

    Prints the counts it derived, because they are the check the operator
    actually cares about: a revision that changes how many footprints exist is a
    revision that changes which panels can be matched without a declared case.
    """
    args = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parent.parent
    tsv_path = Path(args[0]) if args else root / "docs" / "parts" / "dimensions.tsv"
    destination = Path(args[1]) if len(args) > 1 else root / "src" / "aidrill" / "enclosures.py"

    catalogue = read_drawings(tsv_path)
    destination.write_text(render_module(catalogue), encoding="utf-8")

    outlines = {(length, width) for _, length, width, _ in catalogue}
    sizes = {(length, width, height) for _, length, width, height in catalogue}
    print(f"{tsv_path}: {len(catalogue)} base parts, {len(sizes)} distinct sizes, "
          f"{len(outlines)} distinct footprints -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
