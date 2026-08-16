"""Generate the Hammond 1590 catalogue from the distributed TSV authority.

``docs/parts/dimensions.tsv`` supplies exact dimensions, rendered as integer
nanometres in ``src/aidrill/enclosures.py``. Regenerate that module after a TSV
revision; do not edit it by hand.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

__all__ = ["read_drawings", "render_module", "main"]

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


def _nanometres(millimetres: str) -> int:
    """Convert a TSV millimetre value to exact whole nanometres."""
    scaled = Decimal(millimetres) * _NM_PER_MM
    whole = scaled.to_integral_value()
    if scaled != whole:
        raise ValueError(
            f"{millimetres} mm is not a whole number of nanometres ({scaled})"
        )
    return int(whole)


def _drawing_row(line: str) -> tuple[str, int, int, int] | None:
    """Return dimensions for one TSV row, skipping comments and its header."""
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
    """Read unique catalogue rows from the TSV authority."""
    lines = Path(tsv_path).read_text(encoding="utf-8").splitlines()
    rows = (_drawing_row(line) for line in lines)
    return {row for row in rows if row is not None}


_HEADER = '''"""The Hammond 1590 enclosure catalogue, as the reference outline to match.

Generated from ``docs/parts/dimensions.tsv`` by ``tools/build_catalogue.py``;
do not edit by hand. Dimensions are exact integer nanometres.

A footprint, not a part, is what artwork identifies. ``footprints()`` maps each
length-width outline to all matching base parts in deterministic order.
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

    def __post_init__(self) -> None:
        """Refuse anything but a plain ``int`` for a dimension.

        The three ``_nm`` names are a promise -- 112 400 000 exactly, where the
        float 112.4 is not -- and the generator above keeping that promise is
        not what makes it true of the class. A caller builds an ``Enclosure``
        directly: ``tools/`` renders one per drawing, a test states a footprint
        by hand, and a consumer of the library may hold a catalogue of its own.
        Every one of them can hand over ``112.4``, and the value would then flow
        through ``footprint`` into a match and out to a drawing that quotes it,
        with nothing between the mistake and the sheet to say the number never
        crossed ``units``.

        ``type(value) is int`` and not ``isinstance``, because ``bool`` is a
        subclass of ``int`` in Python: ``True`` reaching a width is a
        one-nanometre case that no report would make look wrong.

        Refused rather than converted, on the same reasoning as the rest of the
        model: a float here is a figure that has not been through the unit
        boundary, and rounding it at the point of use would put the conversion
        in a second place.
        """
        for name in ("length_nm", "width_nm", "height_nm"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(
                    f"Enclosure.{name} must be a whole number of nanometres, "
                    f"not {value!r}"
                )

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
    """Render ``src/aidrill/enclosures.py`` for the given TSV catalogue."""
    ordered = sorted(catalogue, key=lambda e: (e[1], e[2], e[3], e[0]))
    rows = "".join(
        f'    Enclosure("{part}", {length:_}, {width:_}, {height:_}),\n'
        for part, length, width, height in ordered
    )
    return _HEADER + rows + _FOOTER


def main(argv: list[str] | None = None) -> int:
    """Regenerate the catalogue module and report its counts."""
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
