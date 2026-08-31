"""stompcollider's pure domain values: dock data, before any kernel touches it.

Every class here is a frozen, slotted dataclass validated at construction --
the same shape ``stompmodel.model`` gives ``DrillData``. Nothing below
imports the kernel: ``Match`` and ``Seat`` fold over these values, never over
solids -- see ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.diagnostics import of_severity as _of_severity
from stompmodel.diagnostics import worst_severity as _worst_severity
from stompmodel.frames import CoordinateFrame
from stompmodel.model import CaseRegistration, Hole, StageRun
from stompmodel.units import Nanometre, check_nanometres

__all__ = [
    "admitting_radius",
    "Profile",
    "Protrusion",
    "Component",
    "Board",
    "Correspondence",
    "Clash",
    "Placement",
    "DockData",
]


def admitting_radius(diameter_nm: Nanometre, clearance_nm: Nanometre) -> Nanometre:
    """The radius a hole of ``diameter_nm`` admits, given a fit clearance.

    Stated once because two callers need the same number: the reader probes
    a solid at it and ``Match`` queries a profile with it, and two spellings
    of one rule would let a part be measured against one radius and judged
    against another. The clearance is a diameter, as every other size in
    this tool is, so it contributes half its value to a radius.
    """
    check_nanometres(
        "admitting_radius", diameter_nm=diameter_nm, clearance_nm=clearance_nm
    )
    if diameter_nm <= 0:
        raise ValueError(f"a hole has a positive diameter, not {diameter_nm}")
    if clearance_nm < 0:
        raise ValueError(f"a fit clearance is not negative, not {clearance_nm}")
    return Nanometre(diameter_nm // 2 + clearance_nm // 2)


@dataclass(frozen=True, slots=True)
class Profile:
    """A component's radius-versus-depth stack: how wide it is, and where.

    Each step is ``(radius_nm, depth_from_tip_min_nm, depth_from_tip_max_nm)``
    and states material *at least* that wide over those depths -- steps
    overlap freely, and the widest covering one is what a hole must admit
    there. A profile with no admissible cylinder has no representable
    profile at all -- see ``stompcollider-technical.md``'s "Protrusions".
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

    def meets(self, radius_nm: Nanometre) -> bool:
        """Whether some step states material at exactly ``radius_nm``.

        The interference fit the report names ``zero-clearance``: a bush
        measuring 12.000 mm into a 12.000 mm hole passes, because
        :meth:`insertion_through` is strict, and passes with nothing to
        spare. Exact equality of whole nanometres, never a tolerance --
        anything the canonical representation cannot state is not a fact.
        """
        return any(radius == radius_nm for radius, _low, _high in self.steps)


@dataclass(frozen=True, slots=True)
class Protrusion:
    """One component's protrusion: where its axis runs, and how wide it is.

    ``axis_xy_nm`` sits in the carrier plane and ``tip_nm`` on the carrier
    normal -- how far the part's tip stands along it, in the board's own
    exported frame. The tip is what turns a depth *through* a hole into a
    depth the board travels, so ``Seat`` cannot place the board without it.
    Only ``Match`` reads the axis; the profile is ``Seat``'s question -- see
    "Protrusions" in the spec.
    """

    designator: str
    axis_xy_nm: tuple[Nanometre, Nanometre]
    profile: Profile
    tip_nm: Nanometre

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError("a protrusion needs the designator of the component it came from")
        if len(self.axis_xy_nm) != 2:
            raise ValueError(
                f"Protrusion.axis_xy_nm must have exactly two components, "
                f"not {len(self.axis_xy_nm)}"
            )
        check_nanometres(
            "Protrusion",
            axis_x_nm=self.axis_xy_nm[0],
            axis_y_nm=self.axis_xy_nm[1],
            tip_nm=self.tip_nm,
        )


@dataclass(frozen=True, slots=True)
class Component:
    """One named solid: its designator, its protrusion, and whether it counts.

    ``protrusion`` is ``None`` for a component with no admissible cylinder
    *or* one the panel-reference filter does not admit, so having none says
    exactly "this part pairs with no hole". ``admitted`` separates the two
    causes, because ``unmatched-part`` names the first alone: a part the
    expression never meant to reach a hole is not a finding. It defaults to
    ``True`` -- nothing is withheld until the filter runs.
    """

    designator: str
    protrusion: Protrusion | None
    admitted: bool = True

    def __post_init__(self) -> None:
        if not self.designator:
            raise ValueError("a component needs the designator of the solid it was read from")
        if type(self.admitted) is not bool:
            raise TypeError(
                f"Component.admitted states whether the panel-reference filter "
                f"kept this part, not {self.admitted!r}"
            )


#: The one legal value of ``Board.panel_face``: a sign along the board's own
#: carrier normal, as exported. Only ``+w``, because which face points at the
#: panel is derived rather than searched -- a board is seatable only when its
#: components protrude out through the drilled face. See "Match" and "The
#: report" in the technical spec.
_PANEL_FACES = frozenset({"+w"})


@dataclass(frozen=True, slots=True)
class Board:
    """One substrate and the components attached to it, numbered by geometry.

    ``ordinal`` is assigned by sorting on position, never on input order --
    see "Board ordinals" in the spec and ADR-0006. ``panel_face`` is ``None``
    until ``Match`` resolves which side of the carrier plane points at the
    panel; it is never guessed at construction.
    """

    ordinal: int
    designators: tuple[str, ...]
    extent_nm: tuple[Nanometre, Nanometre, Nanometre]
    carrier: CoordinateFrame
    components: tuple[Component, ...]
    panel_face: str | None = None

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
        if self.panel_face is not None and self.panel_face not in _PANEL_FACES:
            raise ValueError(
                f"Board.panel_face must be '+w' or None, not {self.panel_face!r}"
            )


@dataclass(frozen=True, slots=True)
class Correspondence:
    """One matched pair: a component's protrusion and the hole it fits.

    ``offset_nm`` is the recognition miss -- a field, not a message, so a
    near-fit is reported rather than silently discarded. ``insertion_nm`` is
    ``None`` for a part the hole admits entirely -- a real geometric fact
    (nothing stops it), not a missing measurement -- see "Protrusions" in the
    technical spec. ``seat_nm`` is where this pairing alone brings the board
    to rest along the face normal, negative into the cavity: the insertion
    depth is measured from the part's tip, so the travel is that depth less
    the tip's own stand-off, and ``Seat`` reduces one number per pairing
    rather than looking a protrusion back up.
    """

    designator: str
    hole_index: int
    hole_xy_nm: tuple[Nanometre, Nanometre]
    insertion_nm: Nanometre | None
    offset_nm: Nanometre
    seat_nm: Nanometre | None

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
        lengths = {
            "hole_x_nm": self.hole_xy_nm[0],
            "hole_y_nm": self.hole_xy_nm[1],
            "offset_nm": self.offset_nm,
        }
        if self.insertion_nm is not None:
            lengths["insertion_nm"] = self.insertion_nm
        if self.seat_nm is not None:
            lengths["seat_nm"] = self.seat_nm
        check_nanometres("Correspondence", **lengths)
        if (self.insertion_nm is None) != (self.seat_nm is None):
            raise ValueError(
                "a correspondence states an insertion depth and the seating it "
                "implies together, or neither: nothing stops a part the hole "
                "admits entirely, so it seats the board nowhere"
            )


@dataclass(frozen=True, slots=True)
class Clash:
    """One interference region: what it is against, and its extent.

    ``bbox_nm`` is the common region's axis-aligned bounding box in the
    case's face frame, ``(xmin, ymin, zmin, xmax, ymax, zmax)``; ``depth_nm``
    is its least extent and ``axis`` that axis -- see "Clashes" in the spec.
    """

    with_: str
    kind: str
    bbox_nm: tuple[Nanometre, Nanometre, Nanometre, Nanometre, Nanometre, Nanometre]
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
        if len(self.bbox_nm) != 6:
            raise ValueError(
                f"Clash.bbox_nm must have exactly six components, not {len(self.bbox_nm)}"
            )
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
    holes: tuple[Hole, ...] = ()
    placements: Mapping[int, tuple[Placement, ...]] = field(default_factory=dict)
    unmatched_holes: tuple[int, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    processing: tuple[StageRun, ...] = ()

    def __post_init__(self) -> None:
        # A copy, not a wrapped alias: a caller's dict mutated after
        # construction must not reach back through this value object, the
        # same guarantee every tuple field here gets for free.
        object.__setattr__(self, "placements", MappingProxyType(dict(self.placements)))
        for hole_index in self.unmatched_holes:
            if hole_index < 1:
                raise ValueError(f"holes are numbered from 1, not {hole_index}")
        for hole in self.holes:
            if hole.index is None:
                raise ValueError(
                    "DockData.holes carries the drilled hole set: every hole "
                    "needs the drill number the document already assigned it"
                )

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
