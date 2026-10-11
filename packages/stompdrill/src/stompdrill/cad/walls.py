"""Which of a drilled enclosure's planar levels are its walls.

Separate from ``case.py``, which owns the drilled plate's own path and whose
bytes ADR-0011 locks: a second question in that file is a second reason to
edit it. A wall is discovered and never declared -- see ADR-0007's amendment,
and ``tools/measure_walls.py`` for the measured populations it reasons from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from stompgeom.levels import Direction, Level, levels
from stompgeom.shapes import compound
from stompgeom.step import StepSolid
from stompmodel.frames import CoordinateFrame, FaceFrame, cross, dot
from stompmodel.model import SURFACES, DrilledSurface
from stompmodel.units import Nanometre, nm_from_mm

from ..errors import StompdrillError
from .case import facing, plates

__all__ = [
    "LATERAL_LIMIT",
    "Wall",
    "build_wall_frame",
    "draft_degrees",
    "drilled_surface",
    "find_walls",
    "is_lateral",
    "lateral_plates",
    "nearest_axis",
    "surface_key",
    "wall_bounds_nm",
]

#: How much of a level's normal may lie along the drill axis and still be a
#: wall's. ``sin 45°``: a level is lateral or it is axial, and this is where
#: the two meanings meet -- not a tolerance fitted to a population, so no
#: measurement sets it and none can move it. Cast geometry tilts a lateral
#: level a few degrees off perpendicular at most, tens of degrees clear of
#: this boundary (ADR-0007).
LATERAL_LIMIT = math.sin(math.radians(45.0))

#: Components in a direction.
_COMPONENTS = 3

#: How many walls an enclosure this drills has. Four, and a fifth or a third
#: is refused rather than guessed at -- see ``find_walls``.
_WALLS = 4


def draft_degrees(direction: Direction, axis: Direction) -> float:
    """How far ``direction`` tilts out of the plane perpendicular to ``axis``.

    Zero for an untilted wall, 90 for the drilled face or the floor. Reported
    in degrees because that is how a casting's draft is published and how
    ``tools/measure_walls.py`` prints it; nothing decides anything on it.
    """
    return math.degrees(math.asin(min(1.0, abs(dot(direction, axis)))))


def is_lateral(level: Level, axis: Direction) -> bool:
    """Whether this level's outward normal is a wall's rather than a face's."""
    return abs(dot(level.direction, axis)) < LATERAL_LIMIT


def _axis_unit(index: int, sign: float) -> Direction:
    """The signed unit vector along one kernel axis."""
    unit = [0.0, 0.0, 0.0]
    unit[index] = 1.0 if sign > 0.0 else -1.0
    return (unit[0], unit[1], unit[2])


def lateral_plates(solid: StepSolid, axis: int) -> tuple[Level, ...]:
    """``solid``'s plate levels that are lateral to drill ``axis``.

    Unfiltered ``levels`` and then ``plates``, in that order and not the
    reverse: ``levels``' own axis filter keeps what faces *along* an axis,
    which is the opposite population, and ``plates`` judges a level by its
    aggregate area, so filtering faces first would split the aggregate.
    """
    along = _axis_unit(axis, 1.0)
    return tuple(
        level for level in plates(list(levels(solid))) if is_lateral(level, along)
    )


def nearest_axis(direction: Direction) -> Direction:
    """The signed kernel axis ``direction`` leans on most.

    Grouping a wall's outer and inner surfaces -- which lean oppositely out
    of the footprint plane, landing in different direction bins -- means
    grouping on the axis they share. An exact tie takes the lower index,
    reachable only by an in-plane 45° level no casting has. Which axes a
    wall may lean on is not this answer's business: ``_grouped_by_axis``
    owns that rule, and stating it twice would be two rules to keep in step.
    """
    lead = max(range(_COMPONENTS), key=lambda index: (abs(direction[index]), -index))
    return _axis_unit(lead, direction[lead])


@dataclass(frozen=True, slots=True)
class Wall:
    """One wall of a drilled solid: its two surfaces, and what stands behind it.

    ``inner`` carries only the inner level's own coplanar patches, never a
    companion's: ``_nearest_companion_level`` filters on facing alone, which
    a plate's whole-span population makes safe but a wall's narrower lateral
    one does not -- it can and measurably does pick up an unrelated feature
    that merely shares the wall's draft. A smaller ``inner`` only tightens
    the containment check a later stage runs, never loosens it.
    """

    outer: Level
    outer_faces: Any
    inner: Any
    plate_nm: Nanometre
    outward: Direction


def find_walls(solid: StepSolid, axis: int) -> tuple[Wall, ...]:
    """``solid``'s four walls, each paired with the surface behind it.

    Ordered on the signed axis each leans on, so a caller may rely on the
    order and no kernel walk reaches an artefact (ADR-0006). Four or it is
    refused: a box with three lateral groups is not an enclosure this drills,
    and guessing which wall is missing would be worse than saying so.
    """
    slabs = plates(list(levels(solid)))
    groups = _grouped_by_axis(list(lateral_plates(solid, axis)), axis)
    found = []
    for along in sorted(groups):
        outer = max(
            groups[along], key=lambda level: level.offset_nm * dot(level.direction, along)
        )
        inner = _wall_inner_level(slabs, outer)
        found.append(
            Wall(
                outer=outer,
                outer_faces=compound(outer.faces),
                inner=compound(inner.faces),
                plate_nm=Nanometre(inner.offset_nm + outer.offset_nm),
                outward=outer.direction,
            )
        )
    return tuple(found)


def _grouped_by_axis(found: list[Level], axis: int) -> dict[Direction, list[Level]]:
    """Every lateral level under the signed kernel axis it leans on.

    Four groups or a refusal. A level leaning on the *drill* axis is refused
    rather than grouped: ``is_lateral`` admits a normal over 45° off that
    axis, while ``nearest_axis`` weighs one component against two, so one
    whose axial component still outweighs each of its in-plane pair passes
    that test and leans on the drill axis all the same, where it would pair
    with the drilled face. That takes tens of degrees off perpendicular;
    draft tilts a level by a few (ADR-0007).
    """
    along = _axis_unit(axis, 1.0)
    # An equality and not a threshold: both are signed unit kernel axes, so
    # "leans on the drill axis" is membership in the two signs of it.
    on_axis = {along, (-along[0], -along[1], -along[2])}
    groups: dict[Direction, list[Level]] = {}
    for level in found:
        leans = nearest_axis(level.direction)
        if leans in on_axis:
            raise StompdrillError(
                f"a lateral level facing {level.direction} leans on the drill axis, so "
                f"it belongs to no wall; this enclosure is not one this version drills"
            )
        groups.setdefault(leans, []).append(level)
    if len(groups) != _WALLS:
        raise StompdrillError(
            f"this solid has {len(groups)} lateral direction groups, not four walls; "
            f"an enclosure whose walls cannot be told apart is not one this drills"
        )
    return groups


def _opposed_axis(direction: Direction) -> Direction:
    """The signed kernel axis facing back along the one ``direction`` leans on."""
    axis = nearest_axis(direction)
    return (-axis[0], -axis[1], -axis[2])


def _level_draft(level: Level) -> float:
    """How far ``level`` is drafted off the signed axis it leans on, in degrees.

    ``draft_degrees`` answers the tilt *out of* the plane perpendicular to the
    axis handed in, so against a level's own leaning axis it returns a right
    angle less the draft. The complement is the quantity a casting's draft is
    published as, and the one a wall's two faces are compared by.
    """
    return 90.0 - draft_degrees(level.direction, nearest_axis(level.direction))


def _wall_inner_level(found: list[Level], outer: Level) -> Level:
    """The nearest level behind ``outer`` on the opposite signed axis, drafted no further.

    The equality is the one ``_grouped_by_axis`` tells one wall from another
    by, read again from the other side of one wall: a level leaning elsewhere
    backs no part of this wall however near it comes. The inequality turns
    away a nearer rival drafted steeper than the outer face -- a pocket or a
    chamfer land -- and the wall's own face, drafted the same or less where a
    box draws both out of the one footprint plane, is then what *nearest*
    reaches (ADR-0007). Only a wall whose every candidate it excludes refuses.
    """
    opposed = _opposed_axis(outer.direction)
    limit = _level_draft(outer)
    candidates = [
        level for level in found
        if facing(level, outer) < 0
        and level.offset_nm + outer.offset_nm > 0
        and nearest_axis(level.direction) == opposed
        and _level_draft(level) <= limit
    ]
    if not candidates:
        raise StompdrillError(
            "no level behind this wall leans on the opposite axis and drafts no "
            "more than the wall's outer face does"
        )
    return min(
        candidates,
        key=lambda level: (level.offset_nm + outer.offset_nm, -level.area_mm2),
    )


def build_wall_frame(wall: Wall, drilled_outward: Direction) -> FaceFrame:
    """Right-handed ``(u, v, w)`` with ``w`` this wall's outward normal.

    ``v`` leans along ``drilled_outward``, so looking at the wall from outside
    -- along ``-w`` -- ``u`` runs right and ``v`` runs towards the drilled
    face, which is how a builder holds a pedal while marking its side. The
    ``u``/``v`` datum is the centre of the outer region's bounding box,
    because a wall carries no artwork to centre on and a box's centre is what
    a drawing dimensions from; depth zero is then carried to the inner plane,
    as ``FaceFrame`` states for every frame.
    """
    w = wall.outward
    # No tie-break is needed or possible: a lateral normal is never parallel
    # to the drill axis, so this cross product is never degenerate.
    u = _normalised(cross(drilled_outward, w))
    v = cross(w, u)
    provisional = CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)), u=u, v=v, w=w
    )
    box = _projected_box(wall.outer_faces, provisional)
    centre_u_nm = nm_from_mm((box[0] + box[3]) / 2.0)
    centre_v_nm = nm_from_mm((box[1] + box[4]) / 2.0)
    outer_depth_nm = nm_from_mm((box[2] + box[5]) / 2.0)
    origin = provisional.to_model(
        centre_u_nm, centre_v_nm, Nanometre(outer_depth_nm - wall.plate_nm)
    )
    return FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(
                nm_from_mm(origin[0]), nm_from_mm(origin[1]), nm_from_mm(origin[2])
            ),
            u=u,
            v=v,
            w=w,
        )
    )


def wall_bounds_nm(
    region: Any, frame: FaceFrame
) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre]:
    """``region``'s extent in ``frame``, stated symmetrically about its datum.

    Halved rather than measured twice: the datum is the box's own centre, and
    independent minima and maxima would let rounding put them a nanometre
    apart -- which ``DrilledSurface`` refuses, because a wall's artefacts are
    framed by that extent's size alone. An odd span therefore floors,
    narrowing the drillable region rather than widening it.
    """
    box = _projected_box(region, frame.basis)
    half_u = Nanometre(nm_from_mm(box[3] - box[0]) // 2)
    half_v = Nanometre(nm_from_mm(box[4] - box[1]) // 2)
    return (Nanometre(-half_u), Nanometre(-half_v), half_u, half_v)


def surface_key(wall: Wall, face_frame: FaceFrame) -> str:
    """Which of the four wall names this one carries.

    Read from the projection of the wall's outward direction onto the drilled
    face's own ``u`` and ``v``: the dominant component with its sign names it,
    so nothing is keyed by position in a list and the order the kernel
    enumerates faces in cannot change a name. The draft tilts out of the face
    plane, which this projection drops -- which is why a drafted wall and an
    undrafted one key alike.
    """
    along_u = dot(wall.outward, face_frame.basis.u)
    along_v = dot(wall.outward, face_frame.basis.v)
    if abs(along_u) >= abs(along_v):
        return "right" if along_u > 0.0 else "left"
    return "top" if along_v > 0.0 else "bottom"


def drilled_surface(
    wall: Wall, key: str, frame: FaceFrame, region: Any
) -> DrilledSurface:
    """This wall as the record a document carries, so a hole in it means something.

    ``region`` is the **outer** surface's: it is what a builder marks, what a
    printed template is taped to, and what a drill file's lower-left origin
    counts from, so it is the one rectangle the document can state. A hole is
    still checked against the inner region as well, at the point its own axis
    crosses that plane -- see ``pipeline.walls``.
    """
    if key not in SURFACES:
        raise StompdrillError(f"{key!r} is no surface of an enclosure")
    return DrilledSurface(
        key=key,
        frame=frame,
        thickness_nm=wall.plate_nm,
        bounds_nm=wall_bounds_nm(region, frame),
    )


def _projected_box(
    shape: Any, basis: CoordinateFrame
) -> tuple[float, float, float, float, float, float]:
    """``shape``'s extent on ``basis``'s own three axes, least first per axis.

    Every one of the model box's eight corners is projected, not the two
    measured extremes: a wall's plane is drafted, so the extreme corner there
    is not the extreme corner here. Exact for a rectangle tilted about one of
    its own in-plane axes, which is what a drafted wall is.
    """
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(shape)
    projected = [
        basis.to_canonical((x, y, z))
        for x in (box[0], box[3])
        for y in (box[1], box[4])
        for z in (box[2], box[5])
    ]
    lows = tuple(min(point[axis] for point in projected) for axis in range(3))
    highs = tuple(max(point[axis] for point in projected) for axis in range(3))
    return (lows[0], lows[1], lows[2], highs[0], highs[1], highs[2])


def _normalised(a: Direction) -> Direction:
    length = math.sqrt(dot(a, a))
    if length == 0.0:  # pragma: no cover - a lateral normal is never the drill axis
        raise StompdrillError("degenerate wall frame")
    return (a[0] / length, a[1] / length, a[2] / length)
