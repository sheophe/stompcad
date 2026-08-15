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

    Both numbers are checked once, in the constructor, on the precedent
    ``DrillStandard.__post_init__`` sets and for its reason: the alternative is
    noticing at every use, or — as happened here — not noticing at all. ``grid``
    must be finite, and ``warn_over`` finite and not negative. Neither rule is
    belt and braces over ``grid <= 0``, because every comparison against NaN is
    False and the disable gate let NaN straight through: ``round(x / nan)``
    raised ``ValueError`` from ``apply``, which nothing catches, so the process
    exited **1** — the code the CLI reserves for "warnings present", read by a
    wrapper as a run worth trusting. ``inf`` did not even raise: ``round(x /
    inf) * inf`` is ``0 * inf``, so every hole snapped to ``nan`` and a drill
    file was written with ``XnanYnan`` in it. A negative or NaN ``warn_over``
    fails the other way, reporting every hole on the panel as off-grid
    including the ones that did not move.
    """

    name: ClassVar[str] = "snap"

    def __init__(self, grid: float, warn_over: float | None = None) -> None:
        self.grid = _finite("grid", grid)
        # Only an explicitly given threshold is checked: the default is derived
        # from a grid that has already been vetted, and for a disabling grid it
        # is a number nothing ever consults.
        self.warn_over = (self.grid / 4.0) if warn_over is None else _threshold(warn_over)

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
                diagnostics.append(self._off_grid(hole, x, y, moved))
            holes.append(hole.moved_to(x, y))

        return data.with_holes(holes).with_diagnostics(*diagnostics)

    def _off_grid(self, hole: Hole, x: float, y: float, moved: float) -> Diagnostic:
        """Name the hole, both of its coordinates and the pitch that moved it.

        This was the one hole-level diagnostic with no ``data`` at all, and it
        is the worst place in the pipeline for that gap: this is the stage that
        *moves* coordinates, so a consumer keying on position — the only thing
        the finding offered — is keying on the number this stage has just
        changed. The drawing rings the holes named by ``hole_index`` and could
        therefore ring no off-grid hole at all, while the CLI report and the
        JSON both carried the finding.

        The message states both coordinates and says which is which, because one
        diagnostic here honestly spans two moments: the message opens where the
        hole was drawn, ``location`` holds where it now is, and a reader given
        only one of them cannot tell which they have. ``moved_mm`` travels as
        well as being printed so that nobody has to recompute a distance from
        two rounded pairs.
        """
        return Diagnostic.warning(
            "off-grid",
            f"hole {hole.index} drawn at ({hole.x:.4f}, {hole.y:.4f}) moved "
            f"{moved:.4f} mm to ({x:.4f}, {y:.4f}) snapping to a "
            f"{self.grid:g} mm grid",
            location=(x, y),
            data=(
                ("hole_index", hole.index),
                ("moved_mm", moved),
                ("grid_mm", self.grid),
            ),
        )

    def _snap(self, value: float) -> float:
        # round() is half-to-even, which is arbitrary but deterministic; the
        # result is an exact multiple of the grid, so snapping again is a no-op.
        return round(value / self.grid) * self.grid


def _finite(name: str, value: float) -> float:
    """A millimetre value that is a number. ``nan`` and ``inf`` are neither."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number of millimetres, got {value!r}")
    return number


def _threshold(value: float) -> float:
    """A warning distance: finite, and not one no hole can be inside of."""
    number = _finite("warn_over", value)
    if number < 0:
        raise ValueError(f"warn_over cannot be a negative distance, got {value!r}")
    return number
