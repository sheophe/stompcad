"""Where a feature's ray crosses a wall, how wide its hole is, and the stage.

Frames and arithmetic here; the drillable region is the model's question, so
the stage below is testable against a fake one exactly as ``clearance.py`` is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, FaceFrame, dot
from stompmodel.model import DrillData, DrilledSurface, Hole, StageRun, WallFeature
from stompmodel.progress import NO_PROGRESS, Scope
from stompmodel.units import Nanometre, format_nm, mm_from_nm, nm_from_mm

from ..cad import Rejection, WallModel
from ..errors import StompdrillError
from .diameters import DrillStandard

__all__ = [
    "WALL_REASON",
    "Crossing",
    "DrillWalls",
    "crossing",
    "grazes",
    "required_radius_nm",
    "stocked_diameter_nm",
]

#: What each refusal means on a wall, in the clause a finding reads. A sibling
#: of ``clearance.REASON`` rather than a reuse of it: every clause there names
#: the drilled plate, and ``docs/GLOSSARY.md`` keeps "face" and "surface"
#: apart, so a builder told a wall hole left the drilled face would go and
#: look at the wrong surface. Each clause here takes the surface that follows
#: it, so one sentence serves all four walls.
WALL_REASON: dict[Rejection, str] = {
    Rejection.OFF_FACE: "lies outside the drillable part of",
    Rejection.THROUGH_BOSS: "meets a boss or rib in",
    Rejection.OBSTRUCTED: "is obstructed by what stands behind",
}

#: The furthest a ray may run to reach a wall and still be running *at* it.
#: Two measured figures fix it and it sits between them: the widest catalogued
#: enclosure is under 200 mm across, so nothing inside this bound is answered
#: differently from how the region would answer it, and ``nm_from_mm`` scales
#: through ``Decimal``, whose context refuses about 1e22 mm outright -- which a
#: ray a whisker off parallel to a wall reaches easily. A kilometre is three
#: orders above the first and sixteen below the second, so it is loose against
#: both rather than tuned to either.
_REACH_MM: float = 1e6


@dataclass(frozen=True, slots=True)
class Crossing:
    """Where one ray meets one wall, in that wall's own canonical frame.

    ``outer_nm`` and ``inner_nm`` differ whenever the ray is not normal to the
    wall, which decision 8 guarantees it is not: the cut runs along the
    component's own axis so a plug cannot bind, and the wall is drafted.
    ``span_nm`` is ``(outer, inner)`` as depths from the feature's tip, and the
    outer one is negative for a part whose tip stops short of the wall.
    """

    key: str
    outer_nm: tuple[Nanometre, Nanometre]
    inner_nm: tuple[Nanometre, Nanometre]
    span_nm: tuple[Nanometre, Nanometre]


def crossing(
    surface: DrilledSurface, feature: WallFeature, case_frame: FaceFrame
) -> Crossing | None:
    """Where ``feature``'s ray crosses ``surface``'s two planes, or ``None``.

    ``None`` when the ray does not travel outward through this wall. Restated
    into the wall's frame rather than intersected in the case's, so the two
    answers are the coordinates a hole is stated in. How far the ray had to
    run to get there is not this function's question -- see ``grazes``.
    """
    approach = _approach(surface, feature, case_frame)
    if approach is None:
        return None
    here, ray, basis, along = approach
    thickness_mm = mm_from_nm(surface.thickness_nm)
    outer = _at(here, ray, basis, (thickness_mm - here[2]) / along)
    inner = _at(here, ray, basis, (0.0 - here[2]) / along)
    return Crossing(
        key=surface.key,
        outer_nm=(outer[0], outer[1]),
        inner_nm=(inner[0], inner[1]),
        span_nm=(outer[2], inner[2]),
    )


def grazes(
    surface: DrilledSurface, feature: WallFeature, case_frame: FaceFrame
) -> bool:
    """Whether the ray runs so nearly along ``surface`` that it meets no place on it.

    Asked before ``crossing`` states a meeting in nanometres, because that is
    where the bound has to be: a ray a whisker off parallel meets the plane
    arbitrarily far away, and past 1e22 mm the canonical scaling refuses the
    magnitude rather than handing back a point a region test could refuse.
    Not the drillable region, which is the model's question -- only whether
    there is a place on this wall to ask about.
    """
    approach = _approach(surface, feature, case_frame)
    if approach is None:
        return False
    here, _ray, _basis, along = approach
    thickness_mm = mm_from_nm(surface.thickness_nm)
    return max(abs(thickness_mm - here[2]), abs(here[2])) / along > _REACH_MM


def _approach(
    surface: DrilledSurface, feature: WallFeature, case_frame: FaceFrame
) -> (
    tuple[tuple[float, float, float], tuple[float, float, float], CoordinateFrame, float]
    | None
):
    """The ray and the wall's own frame, worked out once for both questions.

    ``None`` when the ray does not travel outward through this wall, which is
    the first test because it needs no division and settles most pairs: only a
    ray with a positive component along a wall's own outward normal can leave
    through it.
    """
    basis = surface.frame.basis
    origin = case_frame.basis.to_model(
        feature.origin_nm[0], feature.origin_nm[1], feature.origin_nm[2]
    )
    ray = (
        case_frame.basis.u[0] * feature.direction[0]
        + case_frame.basis.v[0] * feature.direction[1]
        + case_frame.basis.w[0] * feature.direction[2],
        case_frame.basis.u[1] * feature.direction[0]
        + case_frame.basis.v[1] * feature.direction[1]
        + case_frame.basis.w[1] * feature.direction[2],
        case_frame.basis.u[2] * feature.direction[0]
        + case_frame.basis.v[2] * feature.direction[1]
        + case_frame.basis.w[2] * feature.direction[2],
    )
    along = dot(ray, basis.w)
    if along <= 0.0:
        return None
    return basis.to_canonical(origin), ray, basis, along


def _at(
    here: tuple[float, float, float],
    ray: tuple[float, float, float],
    basis: CoordinateFrame,
    distance_mm: float,
) -> tuple[Nanometre, Nanometre, Nanometre]:
    """The ray's ``u``/``v`` at one distance from the tip, and the depth there.

    The depth is ``-distance``: ``distance`` runs along the ray, away from the
    board, and a profile's depths run back from the tip -- which is the one
    sign this whole module turns on.
    """
    projected_u = here[0] + distance_mm * dot(ray, basis.u)
    projected_v = here[1] + distance_mm * dot(ray, basis.v)
    return (
        nm_from_mm(projected_u),
        nm_from_mm(projected_v),
        nm_from_mm(-distance_mm),
    )


def required_radius_nm(
    feature: WallFeature, span_nm: tuple[Nanometre, Nanometre]
) -> Nanometre:
    """The radius a hole must admit: the material in the wall, or the bore.

    Over the wall's own span and not the whole part, because a part is
    assembled *through* a wall rather than pushed through it: a modelled nut
    sits outside and is fitted afterwards, and sizing a hole to admit it would
    drill half again as wide as the bushing needs. The profile is piecewise
    constant, so the span's ends and every step boundary inside it are the
    only depths worth asking about. The bore is a floor rather than a step: a
    plug enters it however little material surrounds it there.
    """
    low, high = span_nm
    depths = {low, high} | {
        boundary
        for _radius, first, last in feature.profile.steps
        for boundary in (first, last)
        if low < boundary < high
    }
    material = max(feature.profile.radius_at(Nanometre(depth)) for depth in sorted(depths))
    return Nanometre(max(material, feature.bore_nm or 0))


def stocked_diameter_nm(
    required_nm: Nanometre, standard: DrillStandard
) -> Nanometre | None:
    """The smallest stocked size admitting a part ``required_nm`` in radius.

    A bound and not a nearest: ``SnapDiametersToDrillTable`` snaps a
    *measurement*, where rounding either way is honest, and this is a
    requirement, where rounding down leaves the part not fitting. The answer
    set is the operator's own selected standard, exactly as ADR-0002 states
    it. ``None`` where the standard stocks nothing wide enough, which the
    caller reports as the existing unstocked refusal.
    """
    wanted = Nanometre(required_nm * 2)
    admitting = [size for size in standard.sizes_nm if size >= wanted]
    return min(admitting) if admitting else None


class DrillWalls:
    """Cut the holes a seating puts in the walls, and refuse what cannot be made.

    An ordinary ``Stage``, appended only by the orchestrator: it assumes
    nothing about which stages ran and reads only what a document already
    carries. The orchestrator appends it after the clash so it works from the
    ranking that survived re-ranking, which is the only ranking that will not
    change under it. Holes leave here unnumbered, because ``RouteHoles`` alone
    assigns ``Hole.index``.
    """

    name: ClassVar[str] = "drill-walls"
    #: One point test per feature per wall, then one sized test for the wall it
    #: reached -- the same shape of work ``CheckCaseClearance`` does per hole,
    #: so it carries that stage's weight rather than a figure timed on one
    #: machine.
    weight: ClassVar[float] = 8.0

    def __init__(
        self,
        model: WallModel,
        features: Sequence[WallFeature],
        standard: DrillStandard,
    ) -> None:
        self.model = model
        self.standard = standard
        # Sorted here and not at every read: the order features arrive in is
        # the dock half's, and a hole's provenance must not depend on it
        # (ADR-0006).
        self._features: tuple[WallFeature, ...] = tuple(
            sorted(features, key=lambda f: (f.board, f.designator, f.direction))
        )

    def describe(self) -> StageRun:
        """Record the answer set and how many rays it was asked about."""
        return StageRun(
            self.name,
            (("standard", self.standard.name), ("features", len(self._features))),
        )

    def apply(self, data: DrillData, scope: Scope = NO_PROGRESS) -> DrillData:
        if not self._features:
            return data
        if data.case is None:
            raise StompdrillError(
                "this document registers no case model, so its wall features carry no "
                "frame to be resolved in"
            )
        face = data.case.frame
        holes: list[Hole] = []
        diagnostics: list[Diagnostic] = []
        drilled: dict[str, DrilledSurface] = {}
        by_component = _by_component(self._features)
        slots = scope.steps(len(by_component))
        for ((board, designator), rays), slot in zip(
            by_component.items(), slots, strict=True
        ):
            slot.label(f"board {board} {designator}")
            hit = self._hit(rays, face)
            if hit is None:
                diagnostics.append(
                    _unreachable(
                        board,
                        designator,
                        "its axis reaches no drillable part of any wall of this "
                        "enclosure",
                    )
                )
                continue
            feature, found, surface = hit
            radius_nm = required_radius_nm(feature, found.span_nm)
            if radius_nm == 0:
                # Asked before the standard is: every stocked size admits a
                # requirement of nothing, so the smallest one would be cut for
                # a part that stands clear of the wall its axis crosses.
                diagnostics.append(
                    _unreachable(
                        board,
                        designator,
                        f"no material or bore of it lies inside the {found.key} wall "
                        f"its axis reaches",
                    )
                )
                continue
            diameter_nm = stocked_diameter_nm(radius_nm, self.standard)
            if diameter_nm is None:
                diagnostics.append(self._unstocked(board, designator, radius_nm))
                continue
            # Ceiling, not floor: an odd-nanometre diameter must round the bit
            # radius up, as ``CheckCaseClearance`` does for the same reason --
            # floor division biases a marginal hole towards passing, which is
            # the wrong direction for a check that stops metal being cut.
            rejection = self.model.classify_wall(
                found.key, found.outer_nm, found.inner_nm, Nanometre(-(-diameter_nm // 2))
            )
            if rejection is not None:
                diagnostics.append(_refused(board, designator, found, diameter_nm, rejection))
                continue
            drilled.setdefault(surface.key, surface)
            holes.append(
                Hole.from_measurement(
                    found.outer_nm[0], found.outer_nm[1], diameter_nm, surface=found.key
                )
            )
        cut = data.with_holes(tuple(data.holes) + tuple(holes))
        if drilled:
            # Only where a wall took a hole: a document registering no surface
            # and one registering an empty list are different claims, and the
            # codec states them differently.
            cut = cut.with_surfaces(tuple(data.surfaces or ()) + tuple(drilled.values()))
        return cut.with_diagnostics(*diagnostics)

    def _hit(
        self, rays: Sequence[WallFeature], face: FaceFrame
    ) -> tuple[WallFeature, Crossing, DrilledSurface] | None:
        """The one wall this component's axis reaches, or ``None`` for none.

        Two refusals, told apart by whether the hits share a direction. One ray
        in two regions is decision 13's ambiguity, unreachable while
        perpendicular wall levels stay millimetres apart, so an enclosure where
        it happens is outside this version. Two *signs* each reaching a wall is
        routine, because a part inside a box points at one wall forwards and
        another backwards; which sign carries the hole is undecided, so it says
        so rather than preferring one.
        """
        found = []
        for feature in rays:
            for surface in self.model.walls:
                if grazes(surface, feature, face):
                    continue
                met = crossing(surface, feature, face)
                if met is None:
                    continue
                if self.model.admits(met.key, met.outer_nm[0], met.outer_nm[1]):
                    found.append((feature, met, surface))
        if len(found) > 1:
            reached = ", ".join(sorted(met.key for _f, met, _s in found))
            if len({feature.direction for feature, _met, _s in found}) == 1:
                raise StompdrillError(
                    f"one ray of board {rays[0].board}'s {rays[0].designator} axis lands "
                    f"inside more than one wall's drillable region ({reached}); this "
                    f"enclosure is not one this version drills"
                )
            raise StompdrillError(
                f"both measured signs of board {rays[0].board}'s {rays[0].designator} "
                f"axis reach a wall ({reached}), and which of the two carries the hole "
                f"is not a choice this version makes"
            )
        return found[0] if found else None

    def _unstocked(self, board: int, designator: str, radius_nm: Nanometre) -> Diagnostic:
        """The existing unstocked refusal, on a requirement rather than a measurement."""
        return Diagnostic.error(
            "unknown-diameter",
            f"board {board}'s {designator} needs a hole admitting "
            f"⌀{format_nm(Nanometre(radius_nm * 2))} mm, which the {self.standard.name} "
            f"drill standard does not stock: its widest is "
            f"⌀{format_nm(max(self.standard.sizes_nm))} mm",
            data=(("designator", designator), ("required_nm", Nanometre(radius_nm * 2))),
        )


def _by_component(
    features: Sequence[WallFeature],
) -> dict[tuple[int, str], tuple[WallFeature, ...]]:
    """One entry per component, in board-then-designator order.

    Both signs of one axis belong to one component, so a component reaching no
    wall earns one finding rather than two.
    """
    grouped: dict[tuple[int, str], list[WallFeature]] = {}
    for feature in features:
        grouped.setdefault((feature.board, feature.designator), []).append(feature)
    return {key: tuple(grouped[key]) for key in sorted(grouped)}


def _unreachable(board: int, designator: str, because: str) -> Diagnostic:
    """A hole was asked for and none can be made, so this is an error.

    An error and not a warning: decision 12 has already stopped ``clash``
    from mentioning this component, so a warning would let the fact that
    nothing was cut for it go entirely unseen. One code for two causes --
    an axis reaching no wall, and an axis reaching one with nothing of the
    part inside it -- because the remedy is the same seating or the same
    named part either way, and a finding is matched by its code rather than
    its clause.
    """
    return Diagnostic.error(
        "wall-feature-unreachable",
        f"board {board}'s {designator} was named as a wall reference, but {because} "
        f"in the seating that was chosen, so no hole can be cut for it",
        data=(("board", board), ("designator", designator)),
    )


def _refused(
    board: int,
    designator: str,
    found: Crossing,
    diameter_nm: Nanometre,
    rejection: Rejection,
) -> Diagnostic:
    """An existing refusal, restated on a wall. Matched by code, never by message."""
    return Diagnostic.error(
        rejection.value,
        f"⌀{format_nm(diameter_nm)} mm hole for board {board}'s {designator} at "
        f"({format_nm(found.outer_nm[0])}, {format_nm(found.outer_nm[1])}) "
        f"{WALL_REASON[rejection]} the {found.key} wall",
        location_nm=found.outer_nm,
        data=(
            ("diameter_nm", diameter_nm),
            ("surface", found.key),
            ("designator", designator),
        ),
    )
