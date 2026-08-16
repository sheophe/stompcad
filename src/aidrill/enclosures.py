"""The Hammond 1590 enclosure catalogue, as the reference outline to match.

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
    Enclosure("1590LLB", 50_500_000, 50_500_000, 25_000_000),
    Enclosure("1590LB", 50_550_000, 50_600_000, 31_000_000),
    Enclosure("1590H", 52_500_000, 38_000_000, 31_000_000),
    Enclosure("1590Y", 92_000_000, 92_000_000, 42_000_000),
    Enclosure("1590A", 92_600_000, 38_500_000, 31_000_000),
    Enclosure("1590G", 100_000_000, 50_000_000, 25_500_000),
    Enclosure("1590G2", 100_000_000, 50_000_000, 31_000_000),
    Enclosure("1590S", 110_500_000, 82_400_000, 44_000_000),
    Enclosure("1590BS", 112_000_000, 60_500_000, 38_000_000),
    Enclosure("1590B", 112_400_000, 60_500_000, 31_000_000),
    Enclosure("1590B2", 112_400_000, 60_500_000, 37_500_000),
    Enclosure("1590B3", 116_000_000, 77_000_000, 37_500_000),
    Enclosure("1590BB", 119_500_000, 94_000_000, 34_000_000),
    Enclosure("1590BB2", 119_500_000, 94_000_000, 37_750_000),
    Enclosure("1590BBS", 119_500_000, 94_000_000, 42_100_000),
    Enclosure("1590C", 119_500_000, 94_000_000, 56_500_000),
    Enclosure("1590T", 120_000_000, 80_000_000, 59_000_000),
    Enclosure("1590Q", 120_000_000, 120_000_000, 34_000_000),
    Enclosure("1590U", 120_000_000, 120_000_000, 58_600_000),
    Enclosure("1590V", 120_000_000, 120_000_000, 93_800_000),
    Enclosure("1590CE", 120_400_000, 100_400_000, 64_600_000),
    Enclosure("1590N1", 121_200_000, 65_500_000, 39_800_000),
    Enclosure("1590KK", 124_800_000, 124_800_000, 57_000_000),
    Enclosure("1590K", 125_000_000, 125_000_000, 79_000_000),
    Enclosure("1590J", 145_000_000, 95_000_000, 49_100_000),
    Enclosure("1590XX", 145_200_000, 121_200_000, 39_300_000),
    Enclosure("1590X", 145_200_000, 121_200_000, 55_000_000),
    Enclosure("1590P1", 153_000_000, 83_100_000, 50_400_000),
    Enclosure("1590D", 187_750_000, 119_500_000, 56_000_000),
    Enclosure("1590DD", 188_000_000, 120_000_000, 37_000_000),
    Enclosure("1590E", 188_000_000, 120_000_000, 82_000_000),
    Enclosure("1590F", 188_000_000, 188_000_000, 67_000_000),
    Enclosure("1590R1", 191_800_000, 111_600_000, 61_000_000),
    Enclosure("1590DE", 200_200_000, 120_200_000, 64_300_000),
    Enclosure("1590EE", 200_200_000, 120_200_000, 84_500_000),
    Enclosure("1590BX2", 254_000_000, 70_000_000, 34_500_000),
    Enclosure("1590BX", 254_000_000, 70_000_000, 49_500_000),
)


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
