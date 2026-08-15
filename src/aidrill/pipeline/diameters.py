"""Diameter normalisation, and the strategies that decide what "nominal" means.

**Why this stage exists.** Measured diameters come back as 6.9998 and 7.0000 for
what the designer drew as one 7 mm hole. Without normalisation every downstream
consumer sees two sizes: the Excellon file loads the same bit twice, the hole
schedule shows two tools, and a part lookup misses. An earlier version of this
tool clustered diameters *inside the Excellon writer*, which meant the drawing
and the drill file could legitimately disagree about how many hole sizes
existed. Normalisation happens here, once, before any emitter sees the data.

**How it stays open for extension.** ``NormalizeDiameters`` knows nothing about
clustering, tables or anything else — it delegates to a ``DiameterStrategy`` and
turns the result into holes and diagnostics. A fourth strategy is a new class;
it requires no edit to this stage.
"""

from __future__ import annotations

import math
from typing import ClassVar, Mapping, Protocol, Sequence, runtime_checkable

from ..model import Diagnostic, DrillData, Hole, ParameterValue, StageRun
from ..tolerance import within

__all__ = [
    "DiameterStrategy",
    "ClusterDiameters",
    "TableDiameters",
    "NoNormalization",
    "NormalizeDiameters",
]


@runtime_checkable
class DiameterStrategy(Protocol):
    """Decides the nominal diameter for each measured diameter.

    The returned mapping is keyed by measured value. **A measured value that the
    strategy cannot resolve is simply absent from the mapping**; the stage then
    keeps the measured value and raises ``unknown-diameter``. That contract is
    what lets ``NormalizeDiameters`` report unresolved sizes without knowing
    which strategies can produce them.
    """

    def nominal(self, measured: Sequence[float]) -> Mapping[float, float]: ...


class ClusterDiameters:
    """Group measured values that are within ``tolerance`` of each other.

    Values are grouped in ascending order. A value joins the open group when it
    is within ``tolerance`` of that group's *representative* — the first (and so
    smallest) member — and not merely within ``tolerance`` of the previous
    member. Naive single-linkage would chain 5.00 → 5.04 → 5.08 into one group
    although its ends are 0.08 apart; measuring from the representative bounds
    every group's spread at ``tolerance``.

    The nominal assigned to a group is the mean of its members, rounded to a
    precision **derived from the tolerance**, so 6.9998 and 7.0000 become one
    7.0. The precision has to follow the tolerance: a fixed 2 dp quietly undid
    the grouping whenever the caller asked for something finer than a hundredth
    of a millimetre — at ``tolerance=0.001`` the three separate groups 7.000,
    7.002 and 7.004 all rounded to 7.0 and became one tool, the exact opposite of
    what was asked for, with no diagnostic. It also corrupted sizes that are
    genuinely three-decimal: 3.175 mm (1/8") became 3.17.
    """

    #: Never coarser than a hundredth: 6.9998 and 7.0000 must still land on 7.0
    #: at the default tolerance, which is the whole point of the stage.
    MIN_PRECISION: ClassVar[int] = 2
    #: Beyond this, rounding is noise on a float anyway.
    MAX_PRECISION: ClassVar[int] = 9

    def __init__(self, tolerance: float = 0.05) -> None:
        self.tolerance = float(tolerance)

    @property
    def precision(self) -> int:
        """Decimal places for the nominal, fine enough to keep groups distinct.

        Two groups are at least ``tolerance`` apart, so rounding to the first
        decimal place that resolves ``tolerance`` cannot merge them.
        """
        if self.tolerance <= 0.0:
            return self.MAX_PRECISION
        decimals = -math.floor(math.log10(self.tolerance))
        return max(self.MIN_PRECISION, min(self.MAX_PRECISION, decimals))

    def nominal(self, measured: Sequence[float]) -> Mapping[float, float]:
        groups: list[list[float]] = []
        for value in sorted(set(measured)):
            if groups and within(value, groups[-1][0], self.tolerance):
                groups[-1].append(value)
            else:
                groups.append([value])

        precision = self.precision
        return {
            value: round(sum(group) / len(group), precision)
            for group in groups
            for value in group
        }


class TableDiameters:
    """Snap each measured value to the nearest declared drill size.

    A value further than ``tolerance`` from every declared size is left
    unresolved — the stage keeps the measurement and reports
    ``unknown-diameter`` rather than silently pretending it was a stocked bit.
    Ties go to the smaller size, so the result never depends on table order.
    """

    def __init__(self, sizes: Sequence[float], tolerance: float = 0.15) -> None:
        self.sizes = tuple(sorted(float(s) for s in sizes))
        self.tolerance = float(tolerance)

    def nominal(self, measured: Sequence[float]) -> Mapping[float, float]:
        if not self.sizes:
            return {}
        resolved: dict[float, float] = {}
        for value in set(measured):
            nearest = min(self.sizes, key=lambda s: (abs(s - value), s))
            if within(nearest, value, self.tolerance):
                resolved[value] = nearest
        return resolved


class NoNormalization:
    """Identity strategy. Every measurement is its own nominal. For debugging."""

    def nominal(self, measured: Sequence[float]) -> Mapping[float, float]:
        return {value: value for value in measured}


class NormalizeDiameters:
    """Assign a nominal diameter to every hole, using ``strategy``."""

    name: ClassVar[str] = "normalize-diameters"

    def __init__(self, strategy: DiameterStrategy) -> None:
        self.strategy = strategy

    def describe(self) -> StageRun:
        """Report the strategy by name, plus whatever settings it exposes.

        Asked *of* the strategy, never decided by type: an ``isinstance`` ladder
        over ClusterDiameters / TableDiameters would put back the closed set of
        strategies this stage was written to avoid, and the fourth strategy — the
        one that lives in a caller's own module — would describe itself as
        nothing. A strategy that has a ``tolerance`` or a table of ``sizes`` gets
        them recorded; one that has neither reports neither, and a consumer sees
        the key absent rather than a default that was never applied.

        The corollary is worth stating: *any* strategy that exposes a sequence
        named ``sizes`` gets it stamped ``sizes_mm``, whatever that sequence
        actually means to it — the price of asking the object instead of its
        type, and the reason the attribute names here are part of the strategy
        contract rather than an implementation detail of two of them.
        """
        parameters: list[tuple[str, ParameterValue]] = [
            ("strategy", type(self.strategy).__name__)
        ]
        tolerance = getattr(self.strategy, "tolerance", None)
        if isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool):
            parameters.append(("tolerance_mm", float(tolerance)))
        sizes = getattr(self.strategy, "sizes", None)
        if isinstance(sizes, Sequence) and not isinstance(sizes, (str, bytes)):
            parameters.append(("sizes_mm", tuple(float(s) for s in sizes)))
        return StageRun(self.name, tuple(parameters))

    def apply(self, data: DrillData) -> DrillData:
        if not data.holes:
            return data

        resolved = self.strategy.nominal([h.diameter for h in data.holes])

        holes: list[Hole] = []
        diagnostics: list[Diagnostic] = []
        for hole in data.holes:
            nominal = resolved.get(hole.diameter)
            if nominal is None:
                diagnostics.append(
                    Diagnostic.warning(
                        "unknown-diameter",
                        f"⌀{hole.diameter:.4f} mm at ({hole.x:.3f}, {hole.y:.3f}) "
                        f"matched no nominal size; the measured value is kept",
                        location=(hole.x, hole.y),
                    )
                )
                nominal = hole.diameter
            holes.append(hole.with_diameter(nominal))

        return data.with_holes(holes).with_diagnostics(*diagnostics)
