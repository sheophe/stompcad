"""Position quantisation and midpoint review.

Measurements are compared unrounded with exact grid multiples; only the
quotient is rounded, half-to-even. ``ReviewGridTies`` reports midpoint choices
for the surviving holes after quantisation.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN
from typing import ClassVar

from ..formatting import format_mm
from ..model import Diagnostic, DrillData, Hole, RawHole, StageRun
from ..tolerance import within
from ..units import (
    NM_PER_MICRON,
    Micron,
    Millimetre,
    Nanometre,
    format_nm,
    nm_from_mm,
    scaled_nm,
)

__all__ = ["SnapPositions", "ReviewGridTies"]

#: The key ``SnapPositions`` records its effective pitch under, and the key
#: `ReviewGridTies` reads it back from. Spelled once, because the two are one
#: conversation: a reader looking under a name the writer stopped using would
#: find no pitch and silently review nothing.
_GRID_PARAMETER: str = "grid_nm"

#: The finest grid a drilled panel can be described on. The drill file and the
#: drawing both print three decimals of a millimetre, so below a micron the
#: rendering stops being injective: two grid points the model holds apart can
#: come out as one coordinate on the sheet a machinist reads. (Not every
#: sub-micron pair collides — a finer grid merely *admits* collisions, which is
#: enough, because nothing here can tell which panel is about to be drawn.)
MICRON_NM: Nanometre = Nanometre(NM_PER_MICRON)


class SnapPositions:
    """Snap centres to a whole-micron grid, clamped to a 1_000 nm floor.

    The pitch arrives in nanometres so a sub-micron request stays expressible
    and can be clamped; ``grid_micron`` is the effective pitch, whole by
    construction. ``warn_over_nm`` defaults to a quarter of that pitch.
    """

    name: ClassVar[str] = "snap"

    def __init__(self, grid_nm: Nanometre, warn_over_nm: Nanometre | None = None) -> None:
        self.requested_grid_nm = _whole("grid_nm", grid_nm)
        self.grid_nm = Nanometre(max(self.requested_grid_nm, MICRON_NM))
        # Only the pitch that is actually coarse enough to be used is held to
        # whole microns: a clamped one is not the pitch anything is snapped to,
        # and refusing 500 nm for not being a whole micron would refuse it for
        # the wrong reason and with the wrong remedy.
        if self.grid_nm % MICRON_NM:
            raise ValueError(
                f"grid must be a whole number of microns, got {grid_nm} nm"
            )
        #: The effective pitch in the unit its wholeness is stated in.
        self.grid_micron = Micron(self.grid_nm // NM_PER_MICRON)
        self.diagnostics = () if self.grid_nm == self.requested_grid_nm else (self._clamped(),)
        # Only an explicitly given threshold is checked: the default is derived
        # from a grid that has already been vetted.
        self.warn_over_nm = (
            Nanometre(self.grid_nm // 4) if warn_over_nm is None else _threshold(warn_over_nm)
        )

    def describe(self) -> StageRun:
        """Record the effective pitch and resolved warning threshold."""
        return StageRun(
            self.name,
            ((_GRID_PARAMETER, self.grid_nm), ("warn_over_nm", self.warn_over_nm)),
        )

    def quantise(
        self, hole: RawHole
    ) -> tuple[tuple[Nanometre, Nanometre], tuple[Diagnostic, ...]]:
        """Snap one centre and warn when squared movement exceeds the squared bound.

        ``moved_nm`` is ``isqrt(dx_nm**2 + dy_nm**2)`` and is therefore floored.
        """
        x_nm, y_nm = self._snap(hole.x), self._snap(hole.y)
        dx_nm = x_nm - nm_from_mm(hole.x)
        dy_nm = y_nm - nm_from_mm(hole.y)
        distance_sq = dx_nm * dx_nm + dy_nm * dy_nm

        # One tolerance idiom for the whole pipeline: a move of exactly
        # ``warn_over_nm`` is within it and stays quiet, slack included. Squares
        # are monotone in a non-negative distance, so sitting on the boundary
        # here is sitting on the same boundary the operator typed.
        if within(distance_sq, 0, self.warn_over_nm * self.warn_over_nm):
            return (x_nm, y_nm), ()
        moved_nm = Nanometre(math.isqrt(distance_sq))
        return (x_nm, y_nm), (self._off_grid(hole, x_nm, y_nm, moved_nm),)

    def _clamped(self) -> Diagnostic:
        """Warn once that the requested pitch was clamped to the rendering floor."""
        return Diagnostic.warning(
            "grid-too-fine",
            f"grid {format_nm(self.requested_grid_nm, 6)} mm is below the "
            f"{format_nm(self.grid_nm)} mm floor and was snapped to it: below a "
            f"micron the drill file and the drawing cannot print two grid points "
            f"apart",
            data=(
                ("requested_grid_nm", self.requested_grid_nm),
                ("grid_nm", self.grid_nm),
            ),
        )

    def _off_grid(
        self, hole: RawHole, x_nm: Nanometre, y_nm: Nanometre, moved_nm: Nanometre
    ) -> Diagnostic:
        """Warn with stable identity, raw and snapped positions, pitch and movement."""
        return Diagnostic.warning(
            "off-grid",
            f"hole {hole.index} drawn at "
            f"({format_mm(hole.x, 4)}, {format_mm(hole.y, 4)}) moved "
            f"{format_nm(moved_nm, 4)} mm to "
            f"({format_nm(x_nm, 4)}, {format_nm(y_nm, 4)}) snapping to a "
            f"{format_nm(self.grid_nm)} mm grid",
            location_nm=(x_nm, y_nm),
            data=(
                ("hole_index", hole.index),
                ("moved_nm", moved_nm),
                ("grid_nm", self.grid_nm),
            ),
        )

    def _snap(self, mm: Millimetre) -> Nanometre:
        """Round only the exact grid quotient, choosing half-to-even on ties."""
        quotient = scaled_nm(mm) / self.grid_nm
        multiple = int(quotient.to_integral_value(rounding=ROUND_HALF_EVEN))
        return Nanometre(multiple * self.grid_nm)


class ReviewGridTies:
    """Warn when surviving holes lie exactly midway on either grid axis.

    Run after ``Deduplicate`` so identities describe emitted holes. The effective
    pitch comes from processing; without a snap record the stage changes nothing.
    """

    name: ClassVar[str] = "review-grid-ties"

    def describe(self) -> StageRun:
        """Record a parameter-free review whose effective pitch comes from data."""
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        grid_nm = self._pitch(data)
        if grid_nm is None:
            return data
        tied = tuple(hole.index for hole in data.holes if _is_tied(hole, grid_nm))
        return data.with_diagnostics(*((_ambiguous(tied, grid_nm),) if tied else ()))

    def _pitch(self, data: DrillData) -> Nanometre | None:
        """Read the effective snap pitch, or ``None`` when none was recorded."""
        run = data.last_run(SnapPositions.name)
        pitch = None if run is None else run.get(_GRID_PARAMETER)
        return Nanometre(pitch) if isinstance(pitch, int) else None


def _is_tied(hole: Hole, grid_nm: Nanometre) -> bool:
    """Return whether either per-axis residual is exactly half a pitch."""
    dx_nm, dy_nm, _ = hole.residual_nm
    return _axis_tied(dx_nm, grid_nm) or _axis_tied(dy_nm, grid_nm)


def _axis_tied(moved_nm: Nanometre, grid_nm: Nanometre) -> bool:
    """Test the exact whole-nanometre relation ``2 * abs(move) == pitch``."""
    return 2 * abs(moved_nm) == grid_nm


def _ambiguous(tied: tuple[int, ...], grid_nm: Nanometre) -> Diagnostic:
    """Report all tied identities and the declared grid, without a denominator."""
    return Diagnostic.warning(
        "grid-ambiguous",
        f"{len(tied)} hole(s) sat exactly halfway between two "
        f"{format_nm(grid_nm)} mm grid points and were placed by the "
        f"tie-break rather than by the artwork: the declared grid is "
        f"probably not the one the panel was drawn on",
        data=(("tied_indices", tied),),
    )


def _whole(name: str, value: Nanometre) -> Nanometre:
    """Require a plain ``int`` nanometre length, excluding floats and booleans."""
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return value


def _threshold(value: Nanometre) -> Nanometre:
    """A warning distance: whole nanometres, and not one no hole can be inside of."""
    number = _whole("warn_over_nm", value)
    if number < 0:
        raise ValueError(f"warn_over_nm cannot be a negative distance, got {value!r}")
    return number
