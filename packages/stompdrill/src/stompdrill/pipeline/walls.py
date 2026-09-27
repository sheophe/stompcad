"""Where a feature's ray crosses one wall's two planes, restated in its frame.

Frames and arithmetic here; the drillable region is the model's question, so
this module is testable against a fake one exactly as ``clearance.py`` is.
"""

from __future__ import annotations

from dataclasses import dataclass

from stompmodel.frames import CoordinateFrame, FaceFrame, dot
from stompmodel.model import DrilledSurface, WallFeature
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

from .diameters import DrillStandard

__all__ = ["Crossing", "crossing", "required_radius_nm", "stocked_diameter_nm"]


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

    ``None`` when the ray does not travel outward through this wall, which is
    the first test because it needs no division and settles most pairs: only a
    ray with a positive component along a wall's own outward normal can leave
    through it. Restated into the wall's frame rather than intersected in the
    case's, so the two answers are the coordinates a hole is stated in.
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
    here = basis.to_canonical(origin)
    thickness_mm = mm_from_nm(surface.thickness_nm)
    outer = _at(here, ray, basis, (thickness_mm - here[2]) / along)
    inner = _at(here, ray, basis, (0.0 - here[2]) / along)
    return Crossing(
        key=surface.key,
        outer_nm=(outer[0], outer[1]),
        inner_nm=(inner[0], inner[1]),
        span_nm=(outer[2], inner[2]),
    )


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
