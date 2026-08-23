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

    A coincident group's survivor is chosen by its own raw measurement, total
    on geometry (ADR-0006) rather than on arrival: no prior stage need sort
    the input for the choice to be order-independent. Near misses are
    retained.
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
        survivors = [min(group, key=_measurement_key) for group in groups]

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


def _measurement_key(hole: Hole) -> tuple[float, float, float]:
    """Tie-break within a coincident group: the measurement each hole came from.

    Nominal position and diameter already tie by the group's own definition
    (``Deduplicate._same_hole``); this is what is left to choose a survivor
    by, so no arrival order is consulted. Compared as raw ``x``, then raw
    ``y``, then raw ``diameter`` -- an arbitrary but total order over three
    independent measurements, not a priority among them. If the measurement
    also ties exactly, every field a caller can observe already agrees, so
    the pick between them is unconstrained.
    """
    return (hole.raw.x, hole.raw.y, hole.raw.diameter)
