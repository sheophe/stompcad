"""Collapse holes with exactly equal nominal position and diameter.

The stage introduces no tolerance; quantisers own position and diameter
normalisation.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.units import format_nm

from ..model import Diagnostic, DrillData, Hole, StageRun

__all__ = ["Deduplicate"]


class Deduplicate:
    """Keep the first of holes equal in ``x_nm``, ``y_nm`` and ``diameter_nm``.

    Input order selects the survivor; near misses are retained.
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

        return data.with_holes([group[0] for group in groups]).with_diagnostics(*diagnostics)

    def _report(self, group: list[Hole]) -> Diagnostic:
        """Report the place, the diameter, and how many holes were collapsed."""
        survivor, dropped = group[0], group[1:]
        plural = "" if len(dropped) == 1 else "s"
        return Diagnostic.warning(
            "duplicate-hole",
            f"{len(group)} coincident ⌀{format_nm(survivor.diameter_nm)} mm holes at "
            f"({format_nm(survivor.x_nm)}, {format_nm(survivor.y_nm)}); "
            f"{len(dropped)} hole{plural} dropped",
            location_nm=(survivor.x_nm, survivor.y_nm),
            data=(
                ("diameter_nm", survivor.diameter_nm),
                ("dropped", len(dropped)),
            ),
        )

    def _same_hole(self, a: Hole, b: Hole) -> bool:
        return (
            a.diameter_nm == b.diameter_nm and a.x_nm == b.x_nm and a.y_nm == b.y_nm
        )
