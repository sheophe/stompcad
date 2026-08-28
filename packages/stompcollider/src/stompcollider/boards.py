"""Finding the boards in a STEP assembly, and proving each one is a board.

The first module in this package to read geometry, and it reads it through
``stompgeom`` -- never through the kernel directly. Ruling 1 in
``docs/specs/foundation-docket-rulings.md`` fixes the rule: an unnamed solid
is a substrate *candidate*, and a candidate is a board only when its two
largest levels are one slab's two faces. Holedness plays no part; it was
measured and does not discriminate. See ADR-0008 for the layering.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from stompgeom.levels import Direction, Level, levels
from stompgeom.step import StepDocument, StepSolid, bounding_box_mm
from stompmodel.frames import CoordinateFrame
from stompmodel.units import Millimetre, Nanometre, mm_from_nm, nm_from_mm

from .errors import StompcolliderError

__all__ = ["is_slab", "carrier_frame", "substrates", "group"]

#: How nearly equal a slab's two faces must be in area, as the smaller over
#: the larger. It refuses a *degenerate pairing* -- a second level that is a
#: flange, a screw head or a shoulder rather than the body's far side -- and
#: it identifies nothing on its own: measured across every solid in
#: ``tests/fixtures/tar-pcb.stp`` and in the five cached Hammond models, the
#: two populations overlap completely, both substrates and fourteen of the
#: fixture's components measuring 1.000 exactly. The constant therefore sits
#: in the widest interval the measurement leaves empty of a genuine plate:
#: below it, an SC530 screw head at 0.282 and a 5 mm LED's flange at 0.267;
#: above it, every real plate, 1590LB's lid least equal at 0.707 and both
#: substrates at 1.000. A half is that interval's midpoint (0.495), the same
#: half ``stompdrill``'s ``_HOLED_FRACTION_LIMIT`` takes for the same reason.
#: Disclosed: Q1's tapered TO-92 body measures 0.597 inside that interval; it
#: is admitted here and refused by the criterion below, which is the
#: conjunction working rather than this criterion failing.
_SLAB_AREA_RATIO_FLOOR = 0.5

#: How thick a slab may be against its own extent -- the side of the square
#: with the larger carrier level's area. Calibrated from a four-fold gap
#: nothing occupies. Below it, every solid that is physically a plate: the
#: two board substrates at 0.0229 and 0.0476, and all ten Hammond box and
#: lid castings between 0.0198 and 0.0422. Above it, every solid that is
#: not: a 5 mm LED at 0.199 is the thinnest, then a footswitch at 0.315, a
#: TO-92 at 1.02 and an SC530 screw at 2.10. A tenth sits 2.1x above the
#: thickest plate and 2.0x below the thinnest non-plate, which is that
#: gap's geometric midpoint (0.0973) rather than a tuned value.
#: Named residual: it also refuses a board smaller than about 16 mm square,
#: whose 1.6 mm substrate is genuinely not thin against its own extent.
_SLAB_THICKNESS_FRACTION = 0.1


def is_slab(solid: StepSolid) -> bool:
    """Whether ``solid``'s two largest levels are one slab's two faces.

    Ruling 1's verification, and the whole of it: exactly opposed, of
    comparable area, and separated by a thickness small against the
    carrier's own extent.
    """
    return _carriers(solid) is not None


def carrier_frame(solid: StepSolid) -> CoordinateFrame | None:
    """``solid``'s carrier plane as a frame, or ``None`` when it is no slab.

    Built from the two carrier levels and nothing else. ``w`` is one of
    them, taken by the ``(direction, offset)`` key ``levels()`` already
    orders on so the choice is geometry's and not the walk's, and the
    origin is that level's plane at its signed offset along ``w``. Which
    of the two it is carries no meaning: which side faces the panel is
    ``Match``'s ``panel_face``, resolved as a sign along this normal.
    """
    carriers = _carriers(solid)
    if carriers is None:
        return None
    outer = max(carriers, key=lambda level: (level.direction, level.offset_nm))
    u, v = _basis_about(outer.direction)
    reach = mm_from_nm(outer.offset_nm)
    origin = tuple(nm_from_mm(Millimetre(component * reach)) for component in outer.direction)
    return CoordinateFrame(origin_nm=origin, u=u, v=v, w=outer.direction)  # type: ignore[arg-type]


def substrates(document: StepDocument) -> tuple[StepSolid, ...]:
    """Every unnamed solid in ``document`` that the slab test admits.

    The name rule selects candidates and the slab test verifies them, so an
    exporter that named nothing yields boards rather than 43 of them. A
    document leaving no verified substrate is refused, never guessed at.
    """
    candidates = tuple(solid for solid in document.solids if not solid.name)
    if not candidates:
        raise StompcolliderError(
            "no-substrate: every solid in the document is named, so none is a board body"
        )
    found = tuple(solid for solid in candidates if is_slab(solid))
    if not found:
        raise StompcolliderError(
            "no-substrate: no unnamed solid in the document measures a slab"
        )
    return found


def group(
    document: StepDocument, found: Sequence[StepSolid]
) -> tuple[tuple[StepSolid, tuple[StepSolid, ...]], ...]:
    """Pair each substrate with the named solids that belong to it.

    A component belongs to the substrate it contacts: among those whose
    footprint it overlaps in projection along the carrier normal, the
    nearest along that normal. Overlap is a preference and not a gate, so a
    part reaching no footprint falls to the nearest substrate rather than
    being dropped. An exact tie between two substrates is broken on their
    own bounding boxes and never on their position in ``found``, which
    would be the document's walk order (ADR-0006). Components come back
    sorted by designator, for the same reason.
    """
    if not found:
        raise StompcolliderError("no-substrate: there is no board to group these solids onto")
    boxes = [(solid, _frame_of(solid), bounding_box_mm(solid.shape)) for solid in found]
    assigned: list[list[StepSolid]] = [[] for _ in boxes]
    for part in document.solids:
        if not part.name:
            continue
        box = bounding_box_mm(part.shape)
        index = min(
            range(len(boxes)),
            key=lambda i: (_contact(boxes[i][1], boxes[i][2], box), boxes[i][2]),
        )
        assigned[index].append(part)
    return tuple(
        (solid, tuple(sorted(parts, key=lambda part: part.name)))
        for (solid, _frame, _box), parts in zip(boxes, assigned)
    )


def _carriers(solid: StepSolid) -> tuple[Level, Level] | None:
    """``solid``'s two carrier levels, or ``None`` when it is no slab."""
    pair = _two_largest(levels(solid))
    if pair is None:
        return None
    first, second = pair
    if not _opposed(first, second):
        return None
    if _area_ratio(first, second) < _SLAB_AREA_RATIO_FLOOR:
        return None
    thickness = _thickness_nm(first, second)
    if thickness <= 0:
        return None
    if mm_from_nm(thickness) > _SLAB_THICKNESS_FRACTION * _extent_mm(first, second):
        return None
    return first, second


def _two_largest(found: Sequence[Level]) -> tuple[Level, Level] | None:
    """The two levels of greatest area, or ``None`` when there are not two.

    Ties are broken on the same ``(direction, offset)`` key ``levels()``
    already orders by, so a solid whose two faces measure exactly equal --
    which every real board's do -- still yields one answer.
    """
    if len(found) < 2:
        return None
    ordered = sorted(found, key=lambda level: (-level.area_mm2, level.direction, level.offset_nm))
    return ordered[0], ordered[1]


def _opposed(first: Level, second: Level) -> bool:
    """Whether the two levels face exactly opposite ways.

    ``levels()`` publishes a direction that is a deterministic function of
    an integer key, and IEEE negation and division are exact and
    sign-symmetric, so one key's negation renormalises to the exact
    negation of the other's direction. Equality here is therefore exact,
    not a tolerance, and this reads the published direction rather than
    restating the granularity that produced it.
    """
    return first.direction == tuple(-component for component in second.direction)


def _area_ratio(first: Level, second: Level) -> float:
    """The smaller of two levels' areas over the larger."""
    return min(first.area_mm2, second.area_mm2) / max(first.area_mm2, second.area_mm2)


def _thickness_nm(first: Level, second: Level) -> Nanometre:
    """The material between two opposed levels.

    A sum and never a difference: each offset is signed along its own
    level's outward direction, so opposed offsets add to the slab between
    them. A non-positive result means the two planes coincide or invert,
    which is no slab at all.
    """
    return Nanometre(first.offset_nm + second.offset_nm)


def _extent_mm(first: Level, second: Level) -> float:
    """The carrier's own extent: the side of the square of its larger area."""
    return math.sqrt(max(first.area_mm2, second.area_mm2))


def _frame_of(solid: StepSolid) -> CoordinateFrame:
    """``solid``'s carrier frame, refusing a solid that is not a slab.

    Grouping needs a carrier normal to project along, and a solid that
    measures no slab has none. Reachable only from a caller that grouped
    onto something :func:`substrates` never selected.
    """
    frame = carrier_frame(solid)
    if frame is None:
        raise StompcolliderError(
            "no-substrate: a solid grouped onto measures no slab, so it has no carrier"
        )
    return frame


def _contact(
    frame: CoordinateFrame,
    substrate_box: tuple[float, float, float, float, float, float],
    part_box: tuple[float, float, float, float, float, float],
) -> tuple[bool, float, float]:
    """How well ``part_box`` belongs to the substrate ``frame`` registers.

    Least is nearest: footprints that overlap first, then the gap along the
    carrier normal, then the distance between the two boxes' centres so
    that a part over no footprint at all still lands somewhere. Three
    measurements of one part against one substrate and nothing else, so
    two substrates can tie -- mirrored ones do. :func:`group` breaks that
    tie; nothing here may, because nothing here can see the other.
    """
    substrate = _projected(substrate_box, frame)
    part = _projected(part_box, frame)
    # Strictly positive: a part merely touching an edge overlaps nothing.
    overlaps = all(_span(substrate[axis], part[axis]) > 0.0 for axis in (0, 1))
    gap = max(-_span(substrate[2], part[2]), 0.0)
    apart = math.sqrt(
        sum(
            (_midpoint(substrate[axis]) - _midpoint(part[axis])) ** 2 for axis in range(3)
        )
    )
    return (not overlaps, gap, apart)


def _midpoint(interval: tuple[float, float]) -> float:
    return (interval[0] + interval[1]) / 2.0


def _projected(
    box: tuple[float, float, float, float, float, float], frame: CoordinateFrame
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """``box``'s eight corners as ``(low, high)`` along each of ``frame``'s axes.

    Every corner, not only the two measured extremes: the carrier frame may
    be turned relative to the model frame, so the extreme corner there is
    not necessarily the extreme corner here.
    """
    corners = [
        (x, y, z)
        for x in (box[0], box[3])
        for y in (box[1], box[4])
        for z in (box[2], box[5])
    ]
    spans = []
    for axis in (frame.u, frame.v, frame.w):
        reach = [_dot(axis, corner) for corner in corners]
        spans.append((min(reach), max(reach)))
    return spans[0], spans[1], spans[2]


def _span(first: tuple[float, float], second: tuple[float, float]) -> float:
    """How far two intervals overlap; negative when they are apart."""
    return min(first[1], second[1]) - max(first[0], second[0])


def _basis_about(w: Direction) -> tuple[Direction, Direction]:
    """A right-handed ``(u, v)`` completing ``w``, chosen without a search.

    Seeded from the world axis ``w`` leans on least, so the cross product
    never approaches zero; ``v = w x u`` then makes ``u x v`` equal ``w``
    exactly, which is what ``CoordinateFrame`` checks at construction.
    """
    seed_axis = min(range(3), key=lambda index: (abs(w[index]), index))
    seed = tuple(1.0 if index == seed_axis else 0.0 for index in range(3))
    u = _normalised(_cross(seed, w))  # type: ignore[arg-type]
    return u, _cross(w, u)


def _cross(a: Direction, b: Direction) -> Direction:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Direction, b: Direction) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalised(a: Direction) -> Direction:
    length = math.sqrt(_dot(a, a))
    return (a[0] / length, a[1] / length, a[2] / length)
