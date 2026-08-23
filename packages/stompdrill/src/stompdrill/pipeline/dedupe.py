"""Collapse holes with exactly equal nominal position and diameter.

The stage introduces no tolerance; quantisers own position and diameter
normalisation.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData, Hole, StageRun
from stompmodel.units import format_nm

__all__ = ["Deduplicate"]


class Deduplicate:
    """Collapse holes equal in ``x_nm``, ``y_nm`` and ``diameter_nm``.

    A coincident group's survivor is chosen by ``Hole.tie_break``, so no
    prior stage need sort the input for the choice to be order-independent —
    see ADR-0006, which that property is the one implementation of. Near
    misses are retained.
    """

    name: ClassVar[str] = "deduplicate"

    def describe(self) -> StageRun:
        """Record that parameter-free exact deduplication ran."""
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        groups: list[list[Hole]] = []

        for hole in data.holes:
            for group in groups:
                if self._same_hole(hole, group[0]):
                    group.append(hole)
                    break
            else:
                groups.append([hole])

        diagnostics = [self._report(group) for group in groups if len(group) > 1]
        survivors = [min(group, key=lambda h: h.tie_break) for group in groups]

        return data.with_holes(survivors).with_diagnostics(*diagnostics)

    def _report(self, group: list[Hole]) -> Diagnostic:
        """Report the place, the diameter, and how many holes were collapsed.

        Every member of a coincident group shares one nominal ``x_nm``,
        ``y_nm`` and ``diameter_nm`` by ``_same_hole``'s own definition, so
        which member is read here does not depend on which one survives.
        """
        sample, dropped = group[0], len(group) - 1
        plural = "" if dropped == 1 else "s"
        return Diagnostic.warning(
            "duplicate-hole",
            f"{len(group)} coincident ⌀{format_nm(sample.diameter_nm)} mm holes at "
            f"({format_nm(sample.x_nm)}, {format_nm(sample.y_nm)}); "
            f"{dropped} hole{plural} dropped",
            location_nm=(sample.x_nm, sample.y_nm),
            data=(
                ("diameter_nm", sample.diameter_nm),
                ("dropped", dropped),
            ),
        )

    def _same_hole(self, a: Hole, b: Hole) -> bool:
        return (
            a.diameter_nm == b.diameter_nm and a.x_nm == b.x_nm and a.y_nm == b.y_nm
        )
