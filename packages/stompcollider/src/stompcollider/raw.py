"""The float-millimetre side of the canonicalisation boundary.

Every length here is a measurement, not yet a canonical fact -- see ADR-0003
and ADR-0004. ``canonicalise`` is these types' only consumer; nothing past
that boundary may hold a float length again.
"""

from __future__ import annotations

from dataclasses import dataclass

from stompmodel.units import check_millimetres

__all__ = ["RawCylinder", "RawComponent", "RawBoard", "RawBoards"]


@dataclass(frozen=True, slots=True)
class RawCylinder:
    """One measured cylinder in a protrusion stack: radius and depth range.

    Depths are measured from the protrusion's tip, per "Protrusions" in
    ``stompcollider-technical.md``. Millimetre floats, upstream of the exact
    decimal scaling ``canonicalise`` applies.
    """

    radius_mm: float
    depth_from_tip_min_mm: float
    depth_from_tip_max_mm: float

    def __post_init__(self) -> None:
        check_millimetres(
            "RawCylinder",
            radius_mm=self.radius_mm,
            depth_from_tip_min_mm=self.depth_from_tip_min_mm,
            depth_from_tip_max_mm=self.depth_from_tip_max_mm,
        )


@dataclass(frozen=True, slots=True)
class RawComponent:
    """One named solid, as measured: its designator and its protrusion stack.

    ``axis_xy_mm`` and ``stack`` are both present or both absent: a
    component the filter admitted but which yielded no admissible cylinder
    has neither, reported downstream as ``unmatched-part`` -- never guessed
    at here.
    """

    designator: str
    axis_xy_mm: tuple[float, float] | None
    stack: tuple[RawCylinder, ...] = ()

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError(
                "a raw component needs the designator of the solid it was read from"
            )
        if self.axis_xy_mm is None:
            if self.stack:
                raise ValueError("a raw component with no axis can carry no cylinder stack")
            return
        x_mm, y_mm = self.axis_xy_mm
        check_millimetres("RawComponent", axis_x_mm=x_mm, axis_y_mm=y_mm)
        if not self.stack:
            raise ValueError("a raw component with an axis needs at least one cylinder")


@dataclass(frozen=True, slots=True)
class RawBoard:
    """One substrate's measured geometry and the components grouped onto it.

    ``corner_a_mm``/``corner_b_mm`` are the two extreme corners of the
    substrate's axis-aligned bounding box in the model frame, in either
    order -- ``canonicalise`` takes their per-axis min and max itself, so
    corner order carries no meaning. ``carrier_*`` is the substrate's own
    plane as ``stompgeom.levels()`` finds it upstream (a later task); only
    the origin is a length, the basis vectors are already unitless.
    """

    corner_a_mm: tuple[float, float, float]
    corner_b_mm: tuple[float, float, float]
    carrier_origin_mm: tuple[float, float, float]
    carrier_u: tuple[float, float, float]
    carrier_v: tuple[float, float, float]
    carrier_w: tuple[float, float, float]
    components: tuple[RawComponent, ...]

    def __post_init__(self) -> None:
        if not self.components:
            raise ValueError("a raw board needs at least one component")
        for label, corner in (("corner_a_mm", self.corner_a_mm), ("corner_b_mm", self.corner_b_mm)):
            check_millimetres(
                f"RawBoard.{label}", x_mm=corner[0], y_mm=corner[1], z_mm=corner[2]
            )
        check_millimetres(
            "RawBoard.carrier_origin_mm",
            x_mm=self.carrier_origin_mm[0],
            y_mm=self.carrier_origin_mm[1],
            z_mm=self.carrier_origin_mm[2],
        )


@dataclass(frozen=True, slots=True)
class RawBoards:
    """A source's whole result: every measured board, before canonicalisation."""

    boards: tuple[RawBoard, ...]

    def __post_init__(self) -> None:
        if not self.boards:
            raise ValueError("a raw scan needs at least one board")
