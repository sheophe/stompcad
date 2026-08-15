"""Derive the Hammond 1590 catalogue from the datasheet the repo ships.

``src/aidrill/enclosures.py`` is *generated* by this script, never typed. The
values are physical constants: a wrong length means a panel drilled to fit a
case the operator does not own, discovered in aluminium rather than in a test.
Hand-transcribing 37 part numbers and 111 dimensions is exactly the task a human
gets wrong silently, so ``docs/1590.pdf`` is the authority and this script is the
audit trail. A datasheet revision is a re-run of ``python tools/extract_1590.py``,
not a re-typing, and ``test_enclosures.py`` re-extracts on every suite run so a
revision shows up as a red test rather than as a quiet disagreement.

``pdfplumber`` is a **development** dependency and must stay one. Nothing under
``src/aidrill`` may import it: the shipped catalogue is a literal table, so the
runtime never opens the PDF.

Reading the table
-----------------

``page.extract_tables()`` yields 11-column rows. Column 0 is the part number of
the *standard, no-mounting-flange* version, column 6 is the colour, and columns
7, 8 and 9 are Length, Width and Height in **whole millimetres**. Those whole
millimetres are rounded from the imperial originals by Hammond, and they are
what we snap to -- reconstructing "imperial-exact" values would invent precision
the datasheet does not claim.

Rows whose cells pdfplumber failed to split (the whole line lands in column 0
and columns 1-10 are ``None``) are skipped by the digit test on columns 7-9.
Every enclosure in the datasheet is listed at least twice -- once per colour --
so no size is lost to a merged row; the natural-finish row and the black row
carry identical dimensions.

The ``1590F`` collision
-----------------------

Collapsing colour, watertight and flange decorations to a base designator is
ambiguous by construction, because ``1590F`` is a real 188 x 188 x 67 enclosure
*and* is what "1590 with a flanged bottom plate" would be spelled. Stripping a
trailing ``F`` turns the real part into a bare ``1590``, which is a family name
and not a catalogue part at all. ``_base_designator`` therefore backs a
collapse out when it lands on the bare family name. The datasheet settles the
question in the row itself: ``1590F``'s own flanged variants are listed
alongside it as ``1590FFL`` and ``1590FF``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator, Sequence

__all__ = [
    "FAMILY",
    "extract",
    "render_module",
    "main",
]

#: The family root. Not a part: no row of the datasheet gives it dimensions, and
#: a collapse that lands here has stripped one character too many.
FAMILY = "1590"

#: A part number cell, as opposed to a whole row pdfplumber failed to split.
_PART = re.compile(r"1590[A-Z0-9]*")

#: Colour suffixes, per the datasheet's own colour column.
_COLOUR = re.compile(r"(BK|CB|GR|LG|OR|PR|RD|YL)$")

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


def _base_designator(part: str) -> str:
    """Reduce a catalogue part number to the designator that names its shape.

    Colour, watertight and flange variants of one enclosure share an outline, so
    they share a footprint and must collapse together. The collapse backs out
    if it reaches the bare family name -- see the ``1590F`` collision above.
    """
    collapsed = _COLOUR.sub("", part)
    without_decoration = _FLANGE.sub("", collapsed)
    if without_decoration.startswith(_WATERTIGHT):
        without_decoration = FAMILY + without_decoration[len(_WATERTIGHT) :]
    return collapsed if without_decoration == FAMILY else without_decoration


def _dimensioned_row(row: Sequence[str | None]) -> tuple[str, int, int, int] | None:
    """``(part, length, width, height)`` for an enclosure row, else ``None``.

    Pure, and separate from the PDF reading, because this is where the extraction
    decides what counts as data. Three rejections, each for a different reason:

    * a row pdfplumber failed to split puts the whole line in column 0 and
      ``None`` everywhere else, so columns 7-9 are not digits;
    * the screw and gasket tables later in the datasheet are 10 columns wide and
      put *part numbers* where dimensions belong, so they fail the same test;
    * a part number outside the 1590 family would pass both of the above and is
      rejected on its own name -- ``HAMMOND_1590`` is a family catalogue, and a
      revision that appends another family must not quietly widen it.
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


def extract(pdf_path: str | Path) -> set[tuple[str, int, int, int]]:
    """Every distinct ``(base_part, length_mm, width_mm, height_mm)`` in the PDF.

    A set, because the datasheet lists each enclosure once per colour and those
    rows are the same enclosure. Two *different* parts may still share all three
    dimensions -- ``1590B2`` and ``1590BS`` are both 112 x 61 x 38 -- so the part
    number stays in the tuple and the set holds one entry per part, not per size.
    """
    return {
        (_base_designator(part), length, width, height)
        for part, length, width, height in _dimensioned_rows(Path(pdf_path))
    }


_HEADER = '''"""The Hammond 1590 enclosure catalogue, as the reference outline to match.

**Generated by ``tools/extract_1590.py`` from ``docs/1590.pdf``. Do not edit by
hand.** These are physical constants, and a value that drifts from the datasheet
is a panel drilled for a case that does not exist. Re-run the script when the
datasheet is revised; ``tests/test_enclosures.py`` re-extracts on every suite run
so a revision cannot land silently.

The reference outline an operator draws is measured artwork, off by a fraction of
a millimetre in both axes. Matching it against this catalogue turns "roughly
112 x 61" into a named enclosure, and the named enclosure's whole millimetres are
what the drawing and the drill file then agree on.

Dimensions are the datasheet's own **whole millimetres**, rounded by Hammond from
imperial originals. They are not converted back: reconstructing an inch-exact
value would invent precision the datasheet does not claim, and the whole
millimetre is the number the operator reads off the box.

Heights **include the lid**, which the datasheet states is 0.16" (4 mm). An
internal-depth question therefore needs 4 mm taken off first -- not that aidrill
asks one, since it does not model enclosures in 3-D.

A footprint, not a part, is what artwork can identify: parts differing only in
height share one outline. ``footprints()`` maps each L x W to every base part
that shares it, so a match names candidates and never guesses between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

__all__ = ["Enclosure", "HAMMOND_1590", "footprints"]


@dataclass(frozen=True, slots=True)
class Enclosure:
    """One catalogue part: a base designator and its outside dimensions."""

    part: str
    length_mm: int
    width_mm: int
    height_mm: int

    @property
    def footprint(self) -> tuple[int, int]:
        """The 2-D outline, which is all a panel drawing can distinguish."""
        return (self.length_mm, self.width_mm)


#: Every base part in the datasheet, ordered by footprint then height so that
#: parts sharing an outline sit together.
HAMMOND_1590: tuple[Enclosure, ...] = (
'''

_FOOTER = ''')


def footprints() -> Mapping[tuple[int, int], tuple[str, ...]]:
    """Each L x W outline mapped to every base part that has it, sorted.

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
    """The full text of ``src/aidrill/enclosures.py`` for a given extraction."""
    ordered = sorted(catalogue, key=lambda e: (e[1], e[2], e[3], e[0]))
    rows = "".join(
        f'    Enclosure("{part}", {length}, {width}, {height}),\n'
        for part, length, width, height in ordered
    )
    return _HEADER + rows + _FOOTER


def main(argv: list[str] | None = None) -> int:
    """Regenerate the catalogue module in place.

    Prints the counts it derived, because they are the check the operator
    actually cares about: a revision that changes how many footprints exist is a
    revision that changes what artwork can be matched against.
    """
    args = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parent.parent
    pdf_path = Path(args[0]) if args else root / "docs" / "1590.pdf"
    destination = Path(args[1]) if len(args) > 1 else root / "src" / "aidrill" / "enclosures.py"

    catalogue = extract(pdf_path)
    destination.write_text(render_module(catalogue), encoding="utf-8")

    outlines = {(length, width) for _, length, width, _ in catalogue}
    sizes = {(length, width, height) for _, length, width, height in catalogue}
    print(f"{pdf_path}: {len(catalogue)} base parts, {len(sizes)} distinct sizes, "
          f"{len(outlines)} distinct footprints -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
