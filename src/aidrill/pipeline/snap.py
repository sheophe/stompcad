"""Position snapping.

A drawn hole centre comes back as −39.9906 when the designer meant −40. The
panel is manufactured on a grid, so the pipeline resolves that here, once,
and every emitter downstream sees the same numbers.

The raw measurement is never lost: ``Hole.raw`` keeps it, so a drawing can show
"−40.00 (raw −39.9906)" and any residual can be recomputed rather than
remembered.
"""

from __future__ import annotations

import math
from typing import ClassVar

from ..model import Diagnostic, DrillData, Hole, StageRun
from ..tolerance import within

__all__ = ["SnapPositions"]


class SnapPositions:
    """Snap every hole's ``x``/``y`` onto ``grid`` millimetres.

    ``warn_over`` defaults to ``grid / 4``: a hole that has to move further than
    a quarter of the grid pitch was probably not drawn on the grid at all, which
    is worth telling the operator about. ``grid <= 0`` disables the stage
    entirely — it becomes the identity and says nothing.
    """

    name: ClassVar[str] = "snap"

    def __init__(self, grid: float, warn_over: float | None = None) -> None:
        self.grid = float(grid)
        self.warn_over = (self.grid / 4.0) if warn_over is None else float(warn_over)

    def describe(self) -> StageRun:
        """Report the pitch the holes were really snapped to, and the threshold.

        ``warn_over`` is reported resolved: ``SnapPositions(grid=0.25)`` was
        constructed with ``None`` there but behaves as 0.0625, and a record of
        ``None`` would tell a reader nothing about what happened to the data.
        """
        return StageRun(
            self.name,
            (
                ("grid_mm", self.grid),
                ("warn_over_mm", self.warn_over),
                ("enabled", self.grid > 0),
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        if self.grid <= 0:
            return data

        holes: list[Hole] = []
        diagnostics: list[Diagnostic] = []
        for hole in data.holes:
            x, y = self._snap(hole.x), self._snap(hole.y)
            moved = math.hypot(x - hole.x, y - hole.y)
            # One tolerance idiom for the whole pipeline: a move of exactly
            # ``warn_over`` is within it and stays quiet, slack included.
            if not within(moved, 0.0, self.warn_over):
                diagnostics.append(
                    Diagnostic.warning(
                        "off-grid",
                        f"hole at ({hole.x:.4f}, {hole.y:.4f}) moved {moved:.4f} mm "
                        f"to ({x:.4f}, {y:.4f}) snapping to a {self.grid:g} mm grid",
                        location=(x, y),
                    )
                )
            holes.append(hole.moved_to(x, y))

        return data.with_holes(holes).with_diagnostics(*diagnostics)

    def _snap(self, value: float) -> float:
        # round() is half-to-even, which is arbitrary but deterministic; the
        # result is an exact multiple of the grid, so snapping again is a no-op.
        return round(value / self.grid) * self.grid
