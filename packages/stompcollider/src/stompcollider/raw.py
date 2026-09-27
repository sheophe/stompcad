"""The float-millimetre side of the canonicalisation boundary.

Every length here is a measurement, not yet a canonical fact -- see ADR-0003
and ADR-0004. ``stompcollider.sources`` builds these and ``canonicalise``
consumes them; nothing past that boundary may hold a float length again.
"""

from __future__ import annotations

from dataclasses import dataclass

from stompmodel.diagnostics import Diagnostic, Severity, of_severity
from stompmodel.frames import check_unit_direction
from stompmodel.units import check_millimetres

__all__ = ["RawCylinder", "RawComponent", "RawBoard", "RawBoards", "RawWallFeature"]


@dataclass(frozen=True, slots=True)
class RawCylinder:
    """One measured band of a part's radial extent: a radius over a depth range.

    A cylinder in the sense of the band the part fills, not necessarily a
    cylindrical face of it: a coaxial face states one directly, and a cut
    against the whole solid states one for the material too wide to pass a
    given radius. Depths are measured from the protrusion's tip, per
    "Protrusions" in ``stompcollider-technical.md``. Millimetre floats,
    upstream of the exact decimal scaling ``canonicalise`` applies -- and
    upstream of the ordering and the one-step-per-feature rule it applies
    with it, so a stack's own order and any repeat within it both carry no
    meaning here.
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

    ``axis_xy_mm``, ``tip_mm`` and ``stack`` are all present or all absent:
    a component the filter admitted but which yielded no admissible cylinder
    has none of them, reported downstream as ``unmatched-part`` -- never
    guessed at here. ``tip_mm`` is where the part's tip stands along the
    carrier normal, which every depth in ``stack`` is measured back from.
    """

    designator: str
    axis_xy_mm: tuple[float, float] | None
    stack: tuple[RawCylinder, ...] = ()
    tip_mm: float | None = None
    #: Its in-plane wall features, one per sign of the axis. Empty unless the
    #: wall-reference filter admitted the part: measuring an envelope costs one
    #: exact boolean per stocked size per sign, and an unnamed part will never
    #: be drilled for, so the filter reaches this read rather than its result.
    wall: tuple[RawWallFeature, ...] = ()

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError(
                "a raw component needs the designator of the solid it was read from"
            )
        if self.axis_xy_mm is None:
            if self.stack:
                raise ValueError("a raw component with no axis can carry no cylinder stack")
            if self.tip_mm is not None:
                raise ValueError("a raw component with no axis has no tip to measure from")
            return
        x_mm, y_mm = self.axis_xy_mm
        check_millimetres(
            "RawComponent", axis_x_mm=x_mm, axis_y_mm=y_mm, tip_mm=self.tip_mm
        )
        if not self.stack:
            raise ValueError("a raw component with an axis needs at least one cylinder")


@dataclass(frozen=True, slots=True)
class RawBoard:
    """One substrate's measured geometry and the components grouped onto it.

    ``corner_a_mm``/``corner_b_mm`` are the two extreme corners of the
    substrate's axis-aligned bounding box in the model frame, in either
    order -- ``canonicalise`` takes their per-axis min and max itself, so
    corner order carries no meaning. ``carrier_*`` is the substrate's own
    plane, ``w`` signed the way its parts protrude; only the origin is a
    length, the basis vectors are already unitless.
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
    """A source's whole result: every measured board, and what it found reading them.

    A scan with no board at all is admitted only when an error diagnostic
    says why -- an unreadable file is a reported finding, not a silently
    empty result, and an error withholds every artefact anyway. A warning
    does not buy the exemption: nothing that still exits 1 may leave a
    caller with no board and no error.
    """

    boards: tuple[RawBoard, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not self.boards and not of_severity(self.diagnostics, Severity.ERROR):
            raise ValueError("a raw scan needs at least one board, or the error explaining none")


@dataclass(frozen=True, slots=True)
class RawWallFeature:
    """One in-plane cylindrical feature, measured in its board file's own frame.

    ``tip_mm`` is the far end of the feature along ``direction``, and every
    depth in ``stack`` is measured back from it -- the same convention
    ``RawComponent`` states for a protrusion, so one profile rule serves
    both. The board file's own coordinates and not the carrier frame's,
    because ``solids.placement_transform`` carries a point from exactly
    these into the assembly's. ``bore_mm`` is the largest concave coaxial
    radius, absent where the part has none.
    """

    designator: str
    tip_mm: tuple[float, float, float]
    direction: tuple[float, float, float]
    stack: tuple[RawCylinder, ...]
    bore_mm: float | None = None

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError(
                "a raw wall feature needs the designator of the solid it was read from"
            )
        if not self.stack:
            raise ValueError(
                "a raw wall feature needs at least one cylinder: its axis came from one"
            )
        check_millimetres(
            "RawWallFeature",
            **{f"tip_mm[{i}]": v for i, v in enumerate(self.tip_mm)},
        )
        check_unit_direction("RawWallFeature.direction", self.direction)
        if self.bore_mm is not None:
            check_millimetres("RawWallFeature", bore_mm=self.bore_mm)
            if self.bore_mm <= 0.0:
                raise ValueError(
                    f"a bore a plug passes through has a positive radius, not {self.bore_mm!r}"
                )
