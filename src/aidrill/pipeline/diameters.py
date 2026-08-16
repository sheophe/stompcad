"""Drill standards and measured-diameter quantisation.

Standards are separate exact nanometre tables. Measurements are compared
unrounded with the selected table; unmatched holes produce an ERROR and are
dropped rather than becoming nominal sizes no stocked bit represents.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import ClassVar

from ..formatting import format_mm
from ..model import Diagnostic, ParameterValue, RawHole, StageRun
from ..units import Nanometre, format_nm, nm_from_mm, scaled_nm

__all__ = [
    "METRIC_BANDS",
    "FRACTIONAL_SIXTY_FOURTHS",
    "DrillStandard",
    "DRILL_STANDARDS",
    "DEFAULT_STANDARD",
    "SnapDiametersToDrillTable",
]

#: Metric: ``(start_mm, stop_mm, step_mm)`` bands, ``stop`` exclusive, so each
#: band runs up to — and not including — the first size of the next. Sources
#: disagree about where the pitch changes, which is exactly why this is data:
#: switching to another preferred series is editing this tuple. Millimetres,
#: because that is how a drill series is published and how the operator adopting
#: another one would write it down; they cross the unit boundary once, in
#: :func:`_metric_sizes`.
METRIC_BANDS: tuple[tuple[float, float, float], ...] = (
    (0.5, 3.0, 0.05),
    (3.0, 14.0, 0.1),
    (14.0, 25.5, 0.5),
)

#: Fractional inch: 1/64" steps from 1/64" to a full inch.
FRACTIONAL_SIXTY_FOURTHS = range(1, 65)

#: 1/64" in nanometres, and the pitch of the whole fractional series. Exact: an
#: inch is 25.4 mm by definition, so 25 400 000 nm, and 64 divides it.
_SIXTY_FOURTH_NM: Nanometre = Nanometre(396_875)


def _metric_sizes(bands: Iterable[tuple[float, float, float]]) -> tuple[Nanometre, ...]:
    """Generate ascending sizes with ``(stop_nm - start_nm) // step_nm`` rows."""
    sizes: list[Nanometre] = []
    for start, stop, step in bands:
        start_nm, stop_nm, step_nm = nm_from_mm(start), nm_from_mm(stop), nm_from_mm(step)
        for index in range((stop_nm - start_nm) // step_nm):
            sizes.append(Nanometre(start_nm + index * step_nm))
    return tuple(sizes)


def _fractional_sizes(sixty_fourths: Iterable[int]) -> tuple[Nanometre, ...]:
    """Generate exact sizes as ``n * 396_875`` nanometres."""
    return tuple(Nanometre(n * _SIXTY_FOURTH_NM) for n in sixty_fourths)


def _whole_nanometres(name: str, value: object) -> Nanometre:
    """Require a plain ``int`` nanometre length, excluding floats and booleans."""
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return Nanometre(value)


def _metric_label(size_nm: Nanometre) -> str:
    """``⌀3.20 mm``. Unique *and* truthful at 2 dp across all 183 sizes."""
    return f"⌀{format_nm(size_nm, 2)} mm"


def _fractional_label(size_nm: Nanometre) -> str:
    """Label an exact fractional-inch bit, such as ``⌀1/8\"``."""
    return f'⌀{Fraction(size_nm, _SIXTY_FOURTH_NM * 64)}"'


@dataclass(frozen=True, slots=True)
class DrillStandard:
    """One bit drawer, with exact sizes and a standard-specific label function."""

    name: str
    sizes_nm: tuple[Nanometre, ...]
    label: Callable[[Nanometre], str]

    def __post_init__(self) -> None:
        """Require a non-empty table of positive plain-integer nanometre sizes."""
        if not self.sizes_nm:
            raise ValueError(f"the {self.name} drill standard has no sizes in it")
        for position, size in enumerate(self.sizes_nm):
            _whole_nanometres(f"the {self.name} drill standard's size[{position}]", size)
            if size <= 0:
                raise ValueError(
                    f"the {self.name} drill standard holds {size} nm at position "
                    f"{position}, and no bit is nothing across"
                )

    def select(
        self,
        include: Sequence[Nanometre] | None = None,
        exclude: Sequence[Nanometre] | None = None,
    ) -> DrillStandard:
        """Copy this standard with exact included or excluded stocked sizes.

        Unknown requests raise; the shared registry entry is never mutated.
        """
        sizes = self.sizes_nm
        if include is not None:
            self._reject_unknown(include, "included")
            wanted = set(include)
            sizes = tuple(s for s in sizes if s in wanted)
        if exclude is not None:
            self._reject_unknown(exclude, "excluded")
            unwanted = set(exclude)
            sizes = tuple(s for s in sizes if s not in unwanted)
        # An empty result raises from ``__post_init__``, where the same rule is
        # enforced for a hand-built standard. One rule, one place.
        return replace(self, sizes_nm=sizes)

    def _reject_unknown(self, requested: Sequence[Nanometre], verb: str) -> None:
        held = set(self.sizes_nm)
        missing = [r for r in requested if r not in held]
        if missing:
            named = ", ".join(format_nm(m) for m in missing)
            raise ValueError(
                f"{named} mm cannot be {verb}: no such size in the {self.name} drill "
                f"standard, which runs {format_nm(self.sizes_nm[0])}–"
                f"{format_nm(self.sizes_nm[-1])} mm"
            )


#: Every standard the operator may declare. A mapping proxy, because a registry
#: one run can rewrite is a registry the next run cannot trust.
DRILL_STANDARDS: Mapping[str, DrillStandard] = MappingProxyType(
    {
        "metric": DrillStandard(
            name="metric",
            sizes_nm=_metric_sizes(METRIC_BANDS),
            label=_metric_label,
        ),
        "fractional": DrillStandard(
            name="fractional",
            sizes_nm=_fractional_sizes(FRACTIONAL_SIXTY_FOURTHS),
            label=_fractional_label,
        ),
    }
)

#: What a panel is drilled with unless the operator says otherwise.
DEFAULT_STANDARD = "metric"


class SnapDiametersToDrillTable:
    """Map each measurement to its nearest stocked bit within inclusive tolerance.

    The default tolerance is 250_000 nm. An unmatched hole is dropped with an
    ``unknown-diameter`` ERROR naming its identity, measurement and nearest bit.
    """

    name: ClassVar[str] = "snap-diameters"

    def __init__(
        self,
        standard: DrillStandard = DRILL_STANDARDS[DEFAULT_STANDARD],
        tolerance_nm: Nanometre = Nanometre(250_000),
    ) -> None:
        self.standard = standard
        self.tolerance_nm = _whole_nanometres("tolerance_nm", tolerance_nm)
        # Negative is refused rather than clamped, and it is the failure that
        # says nothing at all: a bound no measurement can be inside of makes
        # every hole on the panel an ``unknown-diameter`` ERROR, so the report
        # names forty findings and none of them names the number that caused
        # them. Zero is a real bound — "this measurement is exactly a size in
        # the table" — and is left alone.
        if self.tolerance_nm < 0:
            raise ValueError(
                f"tolerance_nm cannot be a negative distance, got {tolerance_nm!r}"
            )

    def describe(self) -> StageRun:
        """Record effective standard, tolerance and count, plus non-registry sizes."""
        parameters: list[tuple[str, ParameterValue]] = [
            ("standard", self.standard.name),
            ("tolerance_nm", self.tolerance_nm),
            ("size_count", len(self.standard.sizes_nm)),
        ]
        if self._narrowed():
            parameters.append(("sizes_nm", self.standard.sizes_nm))
        return StageRun(self.name, tuple(parameters))

    def _narrowed(self) -> bool:
        """Return whether the effective table cannot be rebuilt from its name."""
        return self.standard != DRILL_STANDARDS.get(self.standard.name)

    def quantise(self, hole: RawHole) -> tuple[Nanometre | None, tuple[Diagnostic, ...]]:
        """Return the nearest table size or ``None`` with an ERROR.

        Compare the unrounded ``Decimal`` measurement at an inclusive boundary.
        """
        measurement_nm = scaled_nm(hole.diameter)
        nearest_nm = self._nearest(measurement_nm)
        if abs(measurement_nm - nearest_nm) > self.tolerance_nm:
            return None, (self._unknown(hole, nearest_nm),)
        return nearest_nm, ()

    def _nearest(self, measurement_nm: Decimal) -> Nanometre:
        """Return the closest table size, choosing the smaller bit on a tie."""
        return min(self.standard.sizes_nm, key=lambda size: (abs(measurement_nm - size), size))

    def _unknown(self, hole: RawHole, nearest_nm: Nanometre) -> Diagnostic:
        """Report the hole, measured diameter, nearest bit and effective drawer."""
        stocked = len(self.standard.sizes_nm)
        if self._narrowed():
            refused = (
                f"no size in the drawer — the {self.standard.name} standard narrowed "
                f"to {stocked} size{'' if stocked == 1 else 's'}; the nearest stocked "
                f"bit is {self.standard.label(nearest_nm)}"
            )
        else:
            refused = (
                f"no {self.standard.name} drill size — the nearest is "
                f"{self.standard.label(nearest_nm)}"
            )
        return Diagnostic.error(
            "unknown-diameter",
            f"⌀{format_mm(hole.diameter, 4)} mm at ({format_mm(hole.x)}, "
            f"{format_mm(hole.y)}) is within {format_nm(self.tolerance_nm)} mm of "
            f"{refused}; the hole has been dropped and appears in no artifact",
            location_nm=(nm_from_mm(hole.x), nm_from_mm(hole.y)),
            data=(
                ("hole_index", hole.index),
                ("diameter_nm", nm_from_mm(hole.diameter)),
                ("nearest_nm", nearest_nm),
                ("standard", self.standard.name),
                ("stocked_size_count", stocked),
                ("tolerance_nm", self.tolerance_nm),
            ),
        )
