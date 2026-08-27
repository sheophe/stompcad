"""stompcollider's pure domain values: dock data, before any kernel touches it.

Every class here is a frozen, slotted dataclass validated at construction --
the same shape ``stompmodel.model`` gives ``DrillData``. Nothing below
imports the kernel: ``Match`` and ``Seat`` fold over these values, never over
solids -- see ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.diagnostics import of_severity as _of_severity
from stompmodel.diagnostics import worst_severity as _worst_severity
from stompmodel.frames import CoordinateFrame
from stompmodel.model import CaseRegistration, StageRun
from stompmodel.units import Nanometre, check_nanometres

__all__ = [
    "Profile",
    "Protrusion",
    "Component",
    "Board",
    "Correspondence",
    "Clash",
    "Placement",
    "DockData",
]


@dataclass(frozen=True, slots=True)
class Profile:
    """A component's radius-versus-depth stack, one entry per cylinder.

    Each step is ``(radius_nm, depth_from_tip_min_nm, depth_from_tip_max_nm)``.
    A profile with no admissible cylinder has no representable profile at
    all -- see ``stompcollider-technical.md``'s "Protrusions".
    """

    steps: tuple[tuple[Nanometre, Nanometre, Nanometre], ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("a profile needs at least one step")
        for index, (radius_nm, low_nm, high_nm) in enumerate(self.steps):
            check_nanometres(
                f"Profile.steps[{index}]",
                radius_nm=radius_nm,
                low_nm=low_nm,
                high_nm=high_nm,
            )

    def radius_at(self, depth_nm: Nanometre) -> Nanometre:
        """The greatest radius of any step covering ``depth_nm``.

        Greatest rather than last: a stack's steps may overlap in depth, and
        the widest feature at a depth is what a hole must admit there.
        """
        covering = [
            radius for radius, low, high in self.steps if low <= depth_nm <= high
        ]
        return Nanometre(max(covering)) if covering else Nanometre(0)

    def insertion_through(self, radius_nm: Nanometre) -> Nanometre | None:
        """The least depth at which this profile exceeds ``radius_nm``.

        ``None`` when it never does: the part passes fully. Evaluated on the
        step boundaries alone, because the profile is piecewise constant.
        """
        beyond = sorted(low for radius, low, _high in self.steps if radius > radius_nm)
        return Nanometre(beyond[0]) if beyond else None


@dataclass(frozen=True, slots=True)
class Protrusion:
    """One component's admitted cylinder stack: its axis and its profile.

    ``axis_xy_nm`` sits in the carrier plane. Only ``Match`` reads the axis;
    the profile is ``Seat``'s question -- see "Protrusions" in the spec.
    """

    designator: str
    axis_xy_nm: tuple[Nanometre, Nanometre]
    profile: Profile

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError("a protrusion needs the designator of the component it came from")
        if len(self.axis_xy_nm) != 2:
            raise ValueError(
                f"Protrusion.axis_xy_nm must have exactly two components, "
                f"not {len(self.axis_xy_nm)}"
            )
        check_nanometres(
            "Protrusion", axis_x_nm=self.axis_xy_nm[0], axis_y_nm=self.axis_xy_nm[1]
        )


@dataclass(frozen=True, slots=True)
class Component:
    """One named solid: its designator, and its protrusion if it has one.

    ``protrusion`` is ``None`` for a component with no admissible cylinder --
    reported as ``unmatched-part``, never inferred as absent geometry.
    """

    designator: str
    protrusion: Protrusion | None

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError("a component needs the designator of the solid it was read from")


@dataclass(frozen=True, slots=True)
class Board:
    """One substrate and the components attached to it, numbered by geometry.

    ``ordinal`` is assigned by sorting on position, never on input order --
    see "Board ordinals" in the spec and ADR-0006.
    """

    ordinal: int
    designators: tuple[str, ...]
    extent_nm: tuple[Nanometre, Nanometre, Nanometre]
    carrier: CoordinateFrame
    components: tuple[Component, ...]

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError(f"boards are numbered from 1, not {self.ordinal}")
        if not self.designators:
            raise ValueError("a board needs at least one designator")
        if len(self.extent_nm) != 3:
            raise ValueError(
                f"Board.extent_nm must have exactly three components, "
                f"not {len(self.extent_nm)}"
            )
        check_nanometres(
            "Board",
            extent_x_nm=self.extent_nm[0],
            extent_y_nm=self.extent_nm[1],
            extent_z_nm=self.extent_nm[2],
        )


@dataclass(frozen=True, slots=True)
class Correspondence:
    """One matched pair: a component's protrusion and the hole it fits.

    ``offset_nm`` is the recognition miss -- a field, not a message, so a
    near-fit is reported rather than silently discarded.
    """

    designator: str
    hole_index: int
    hole_xy_nm: tuple[Nanometre, Nanometre]
    insertion_nm: Nanometre
    offset_nm: Nanometre

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError("a correspondence needs the designator of the component it pairs")
        if self.hole_index < 1:
            raise ValueError(f"holes are numbered from 1, not {self.hole_index}")
        if len(self.hole_xy_nm) != 2:
            raise ValueError(
                f"Correspondence.hole_xy_nm must have exactly two components, "
                f"not {len(self.hole_xy_nm)}"
            )
        check_nanometres(
            "Correspondence",
            hole_x_nm=self.hole_xy_nm[0],
            hole_y_nm=self.hole_xy_nm[1],
            insertion_nm=self.insertion_nm,
            offset_nm=self.offset_nm,
        )


@dataclass(frozen=True, slots=True)
class Clash:
    """One interference region: what it is against, and its extent.

    ``bbox_nm`` is the common region's axis-aligned bounding box in the
    case's face frame; ``depth_nm`` is its least extent and ``axis`` that
    axis -- see "Clashes" in the spec.
    """

    with_: str
    kind: str
    bbox_nm: tuple[Nanometre, ...]
    depth_nm: Nanometre
    axis: str
    volume_nm3: int

    def __post_init__(self) -> None:
        if not self.with_:
            raise ValueError("a clash names the solid it is against")
        if not self.kind:
            raise ValueError("a clash states its kind")
        if not self.axis:
            raise ValueError("a clash states its axis")
        check_nanometres(
            "Clash",
            **{f"bbox_nm[{index}]": value for index, value in enumerate(self.bbox_nm)},
            depth_nm=self.depth_nm,
        )


@dataclass(frozen=True, slots=True)
class Placement:
    """One candidate seating: its transform, correspondences, and clashes.

    ``rank`` orders placements per "Ranking" in the spec; it is a reported
    field, not a verdict, because a symmetric hole pattern can genuinely
    admit more than one seating.
    """

    rank: int
    x_nm: Nanometre
    y_nm: Nanometre
    z_nm: Nanometre
    theta_deg: float
    correspondence: tuple[Correspondence, ...]
    clashes: tuple[Clash, ...]

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError(f"placements are ranked from 1, not {self.rank}")
        check_nanometres("Placement", x_nm=self.x_nm, y_nm=self.y_nm, z_nm=self.z_nm)
        if type(self.theta_deg) is not float or not math.isfinite(self.theta_deg):
            raise TypeError(
                f"Placement.theta_deg must be a finite number of degrees, "
                f"not {self.theta_deg!r}"
            )


@dataclass(frozen=True, slots=True)
class DockData:
    """The single value that travels stompcollider's whole pipeline.

    Mirrors ``stompmodel.model.DrillData``'s shape and protocol conformance:
    ``Match`` and ``Seat`` fold over this exactly as stompdrill's stages fold
    over ``DrillData`` -- one shared ``Processable``/``Diagnosable`` pair,
    not a second copy of either.
    """

    case: CaseRegistration
    boards: tuple[Board, ...] = ()
    placements: dict[int, tuple[Placement, ...]] = field(default_factory=dict)
    unmatched_holes: tuple[int, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    processing: tuple[StageRun, ...] = ()

    def __post_init__(self) -> None:
        for hole_index in self.unmatched_holes:
            if hole_index < 1:
                raise ValueError(f"holes are numbered from 1, not {hole_index}")

    def with_processing(self, *runs: StageRun) -> DockData:
        """Append completed stage records in execution order."""
        if not runs:
            return self
        return replace(self, processing=self.processing + tuple(runs))

    def with_diagnostics(self, *diagnostics: Diagnostic) -> DockData:
        if not diagnostics:
            return self
        return replace(self, diagnostics=self.diagnostics + tuple(diagnostics))

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        """Delegate to the published reduction so there is one implementation."""
        return _of_severity(self.diagnostics, severity)

    @property
    def worst_severity(self) -> Severity | None:
        """Delegate to the published reduction so there is one implementation."""
        return _worst_severity(self.diagnostics)
