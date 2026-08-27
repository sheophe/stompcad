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

from stompmodel.units import Nanometre, check_nanometres

__all__ = ["Enclosure", "HAMMOND_1590", "footprints"]


@dataclass(frozen=True, slots=True)
class Enclosure:
    """One catalogue part: a base designator and its outside dimensions in nanometres."""

    part: str
    length_nm: Nanometre
    width_nm: Nanometre
    height_nm: Nanometre

    def __post_init__(self) -> None:
        """Require each dimension to be a plain integer number of nanometres.

        The published guard rejects both floats and ``bool``, an ``int``
        subclass, so values cannot bypass the unit boundary before a footprint
        is matched or printed.
        """
        check_nanometres(
            "Enclosure",
            length_nm=self.length_nm,
            width_nm=self.width_nm,
            height_nm=self.height_nm,
        )

    @property
    def footprint(self) -> tuple[Nanometre, Nanometre]:
        """The 2-D outline, which is all a panel drawing can distinguish."""
        return (self.length_nm, self.width_nm)


#: Every base part in the drawings, ordered by footprint then height so that
#: parts sharing an outline sit together.
HAMMOND_1590: tuple[Enclosure, ...] = (
    Enclosure("1590LLB", Nanometre(50_500_000), Nanometre(50_500_000), Nanometre(25_000_000)),
    Enclosure("1590LB", Nanometre(50_550_000), Nanometre(50_600_000), Nanometre(31_000_000)),
    Enclosure("1590H", Nanometre(52_500_000), Nanometre(38_000_000), Nanometre(31_000_000)),
    Enclosure("1590Y", Nanometre(92_000_000), Nanometre(92_000_000), Nanometre(42_000_000)),
    Enclosure("1590A", Nanometre(92_600_000), Nanometre(38_500_000), Nanometre(31_000_000)),
    Enclosure("1590G", Nanometre(100_000_000), Nanometre(50_000_000), Nanometre(25_500_000)),
    Enclosure("1590G2", Nanometre(100_000_000), Nanometre(50_000_000), Nanometre(31_000_000)),
    Enclosure("1590S", Nanometre(110_500_000), Nanometre(82_400_000), Nanometre(44_000_000)),
    Enclosure("1590BS", Nanometre(112_000_000), Nanometre(60_500_000), Nanometre(38_000_000)),
    Enclosure("1590B", Nanometre(112_400_000), Nanometre(60_500_000), Nanometre(31_000_000)),
    Enclosure("1590B2", Nanometre(112_400_000), Nanometre(60_500_000), Nanometre(37_500_000)),
    Enclosure("1590B3", Nanometre(116_000_000), Nanometre(77_000_000), Nanometre(37_500_000)),
    Enclosure("1590BB", Nanometre(119_500_000), Nanometre(94_000_000), Nanometre(34_000_000)),
    Enclosure("1590BB2", Nanometre(119_500_000), Nanometre(94_000_000), Nanometre(37_750_000)),
    Enclosure("1590BBS", Nanometre(119_500_000), Nanometre(94_000_000), Nanometre(42_100_000)),
    Enclosure("1590C", Nanometre(119_500_000), Nanometre(94_000_000), Nanometre(56_500_000)),
    Enclosure("1590T", Nanometre(120_000_000), Nanometre(80_000_000), Nanometre(59_000_000)),
    Enclosure("1590Q", Nanometre(120_000_000), Nanometre(120_000_000), Nanometre(34_000_000)),
    Enclosure("1590U", Nanometre(120_000_000), Nanometre(120_000_000), Nanometre(58_600_000)),
    Enclosure("1590V", Nanometre(120_000_000), Nanometre(120_000_000), Nanometre(93_800_000)),
    Enclosure("1590CE", Nanometre(120_400_000), Nanometre(100_400_000), Nanometre(64_600_000)),
    Enclosure("1590N1", Nanometre(121_200_000), Nanometre(65_500_000), Nanometre(39_800_000)),
    Enclosure("1590KK", Nanometre(124_800_000), Nanometre(124_800_000), Nanometre(57_000_000)),
    Enclosure("1590K", Nanometre(125_000_000), Nanometre(125_000_000), Nanometre(79_000_000)),
    Enclosure("1590J", Nanometre(145_000_000), Nanometre(95_000_000), Nanometre(49_100_000)),
    Enclosure("1590XX", Nanometre(145_200_000), Nanometre(121_200_000), Nanometre(39_300_000)),
    Enclosure("1590X", Nanometre(145_200_000), Nanometre(121_200_000), Nanometre(55_000_000)),
    Enclosure("1590P1", Nanometre(153_000_000), Nanometre(83_100_000), Nanometre(50_400_000)),
    Enclosure("1590D", Nanometre(187_750_000), Nanometre(119_500_000), Nanometre(56_000_000)),
    Enclosure("1590DD", Nanometre(188_000_000), Nanometre(120_000_000), Nanometre(37_000_000)),
    Enclosure("1590E", Nanometre(188_000_000), Nanometre(120_000_000), Nanometre(82_000_000)),
    Enclosure("1590F", Nanometre(188_000_000), Nanometre(188_000_000), Nanometre(67_000_000)),
    Enclosure("1590R1", Nanometre(191_800_000), Nanometre(111_600_000), Nanometre(61_000_000)),
    Enclosure("1590DE", Nanometre(200_200_000), Nanometre(120_200_000), Nanometre(64_300_000)),
    Enclosure("1590EE", Nanometre(200_200_000), Nanometre(120_200_000), Nanometre(84_500_000)),
    Enclosure("1590BX2", Nanometre(254_000_000), Nanometre(70_000_000), Nanometre(34_500_000)),
    Enclosure("1590BX", Nanometre(254_000_000), Nanometre(70_000_000), Nanometre(49_500_000)),
)


def footprints() -> Mapping[tuple[Nanometre, Nanometre], tuple[str, ...]]:
    """Each L x W outline in nanometres, mapped to every base part that has it, sorted.

    Sorted, and read-only, because a matcher reports these candidates to the
    operator: an order that depended on catalogue order would make the drawing's
    text change when an unrelated part was added, and a caller that mutated the
    mapping would corrupt every later match in the process.
    """
    return _FOOTPRINTS


def _build_footprints() -> Mapping[tuple[Nanometre, Nanometre], tuple[str, ...]]:
    grouped: dict[tuple[Nanometre, Nanometre], list[str]] = {}
    for enclosure in HAMMOND_1590:
        grouped.setdefault(enclosure.footprint, []).append(enclosure.part)
    return MappingProxyType(
        {outline: tuple(sorted(parts)) for outline, parts in grouped.items()}
    )


_FOOTPRINTS = _build_footprints()
