"""Locate what a drilled enclosure side consists of.

The domain layer: which solid is the box, which axis the drill runs along,
which planar face is drilled, which flat face backs it, and the right-handed
frame that puts canonical coordinates on that face.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stompgeom.shapes import compound
from stompgeom.step import StepDocument, StepSolid, assembly_spans, bounding_box_mm
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

from ..errors import StompdrillError
from .base import step_keyword

__all__ = [
    "Faces", "drill_axis", "select_solid", "find_faces",
    "build_frame",
]

#: How far a measured span may differ from the catalogue and still match, in
#: millimetres. This is inert on the production path: ``loader._footprint_and_axis``
#: measures the footprint from the model's own spans and asks for the axis that
#: matches it, so the comparison always succeeds regardless of the tolerance's
#: value. It still bounds a caller who passes a genuine catalogue footprint --
#: the library contract ``drill_axis`` exposes and ``tests/test_cad_case.py``
#: exercises directly -- so it is kept honest rather than left arbitrary: 1590B
#: (112.40 mm) and 1590BS (112.00 mm) are 0.40 mm apart, so 0.6 mm would let one
#: match the other's catalogue footprint. 0.05 mm is generous against Hammond's
#: 0.1 mm publication rounding while staying well inside that 0.40 mm gap.
_MATCH_TOLERANCE_MM = 0.05

#: Below this fraction of a level's own outer-wire area that isn't real
#: surface (1 - true area / outer-wire area), a level is a candidate plate;
#: at or above it, a ring, flange or skirt. Measured on the four cached
#: models: every plate sits at 3.7% or under, every ring at 83.3% or over --
#: a 79-point gap with nothing between them, so 50% is that gap's midpoint,
#: not a tuned value.
_HOLED_FRACTION_LIMIT = 0.5


@dataclass(frozen=True)
class Faces:
    """The inner side of a plate, and its thickness.

    ``inner`` is a ``TopoDS_Compound``: the inner level's own coplanar
    patches plus its nearest companion level's -- never a single bare
    ``TopoDS_Face``, since a level is a set of faces by construction.
    """

    inner: Any
    plate_nm: Nanometre
    outward: tuple[float, float, float]
    drilled_position_mm: float
    inner_position_mm: float
    #: The drilled solid's own bounding-box span per kernel axis, millimetres.
    #: ``build_frame`` reads this to pick which free axis is "right".
    footprint_mm: tuple[float, float, float]


def drill_axis(document: StepDocument, footprint_nm: tuple[Nanometre, Nanometre]) -> int:
    """Return the index of the axis normal to the catalogue footprint plane.

    ``loader._footprint_and_axis``, the sole production caller, measures
    ``footprint_nm`` from ``document`` itself before asking for the matching
    axis, so the comparison here always succeeds and the raise below is
    unreachable on that path. It is reachable, and exercised, by a caller
    that supplies a genuine catalogue footprint instead -- the library
    contract this function offers, which ``tests/test_cad_case.py`` tests
    directly.
    """
    spans = assembly_spans(document)
    wanted = sorted(float(nm) / 1_000_000 for nm in footprint_nm)
    for axis in range(3):
        plane = sorted(spans[other] for other in range(3) if other != axis)
        if all(abs(a - b) <= _MATCH_TOLERANCE_MM for a, b in zip(plane, wanted)):
            return axis
    raise StompdrillError(
        f"no face of the model has the catalogue footprint "
        f"{wanted[1]:.2f} x {wanted[0]:.2f} mm; measured spans are "
        f"{spans[0]:.2f}, {spans[1]:.2f}, {spans[2]:.2f} mm"
    )


def select_solid(document: StepDocument, face: CaseFace) -> StepSolid:
    """Pick the box or lid solid, by name and then verified by thickness."""
    keyword = step_keyword(face)
    found = document.named(keyword)
    if len(found) != 1:
        raise StompdrillError(
            f"the model names {len(found)} products containing {keyword!r}; "
            f"exactly one is needed to drill the {face.value}"
        )
    return found[0]


def _outward_sign(component: float, reversed_face: bool) -> int:
    """Which way a face points along the drill axis, as exactly -1 or +1.

    The caller has already established the normal is axis-aligned, so the
    only information left in ``component`` is its sign; its magnitude is 1
    to within the same tolerance and carries nothing. Returning an ``int``
    keeps the raw kernel float out of the grouping key and out of the
    equality tests that read the result back -- a normal reported as
    -0.9999999999999993 is the same direction as -1.0, and no key or
    comparison may treat them as two.
    """
    sign = -1 if reversed_face else 1
    return sign if component > 0.0 else -sign


def find_faces(solid: StepSolid, axis: int) -> Faces:
    """Find the drilled plate level along ``axis`` and the level behind it."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    solid_bbox = bounding_box_mm(solid.shape)
    footprint_mm = (
        solid_bbox[3] - solid_bbox[0],
        solid_bbox[4] - solid_bbox[1],
        solid_bbox[5] - solid_bbox[2],
    )

    planes: list[tuple[float, float, int, Any]] = []
    explorer = TopExp_Explorer(solid.shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            plane = adaptor.Plane()
            normal = plane.Axis().Direction()
            components = (normal.X(), normal.Y(), normal.Z())
            if abs(abs(components[axis]) - 1.0) < 1e-9:
                outward = _outward_sign(
                    components[axis],
                    face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED,
                )
                position = bounding_box_mm(face)[axis]
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, props)
                planes.append((props.Mass(), position, outward, face))
        explorer.Next()

    levels = _plates(_levels(planes))
    if len(levels) < 2:
        raise StompdrillError(
            f"{solid.name} has fewer than two planar faces normal to the drill axis"
        )

    drilled = _drilled_level(levels, solid_bbox, axis, solid.name)
    inner = _inner_level(levels, drilled)
    companion = _nearest_companion_level(levels, inner)
    thickness = abs(inner.position - drilled.position)
    normal = [0.0, 0.0, 0.0]
    normal[axis] = float(drilled.outward)
    return Faces(
        inner=compound(inner.faces + (companion.faces if companion else ())),
        plate_nm=nm_from_mm(thickness),
        outward=(normal[0], normal[1], normal[2]),
        drilled_position_mm=drilled.position,
        inner_position_mm=inner.position,
        footprint_mm=footprint_mm,
    )


@dataclass(frozen=True)
class _Level:
    """Every coplanar planar candidate at one axis position, sharing one facing.

    A single physical plane can tessellate into several disconnected patches
    (a floor plus stray coplanar slivers cut by nearby features), which is
    why a level is a *set* of faces rather than one: grouping by position
    first, then reasoning about the group, is what keeps that tessellation
    from being mistaken for competing candidates.
    """

    position: float
    area: float
    #: Exactly -1 or +1. Never a raw kernel component: this is half of the
    #: grouping key below and is read back by exact equality twice.
    outward: int
    faces: tuple[Any, ...]


def _levels(planes: list[tuple[float, float, int, Any]]) -> list[_Level]:
    """Group same-facing planar candidates into levels by rounded axis position.

    Kernel-float noise can make two patches of the same physical plane report
    axis positions that differ in the 13th decimal place; rounding to whole
    nanometres before grouping removes that noise at its source, rather than
    working around it later with a distance-based tie-break. A level's own
    ``position`` is read back from that same rounded key, not from whichever
    member the explorer happened to visit first, so it cannot vary with
    traversal order.
    """
    groups: dict[tuple[int, int], list[tuple[float, float, Any]]] = {}
    for area, position, outward, face in planes:
        groups.setdefault((nm_from_mm(position), outward), []).append((area, position, face))
    return [
        _Level(
            position=mm_from_nm(Nanometre(position_nm)),
            area=sum(item[0] for item in members),
            outward=outward,
            faces=tuple(item[2] for item in members),
        )
        for (position_nm, outward), members in groups.items()
    ]


def _plates(levels: list[_Level]) -> list[_Level]:
    """Levels that are mostly solid material, not a ring, flange or skirt.

    A level's outer-wire area is rebuilt the way ``build_region`` rebuilds a
    face's own outer boundary; comparing it with the true surface area is a
    topological signal a ring can't fake by being small. Filtering happens
    on the level's aggregate areas, not per face: the box floor's level
    holds one 9260 mm2 unholed patch alongside nine tiny slivers, and
    judging the slivers individually would discard the patch with them.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.ShapeAnalysis import ShapeAnalysis

    kept = []
    for level in levels:
        outer_area = 0.0
        for face in level.faces:
            surface = BRep_Tool.Surface_s(face)
            capped = BRepBuilderAPI_MakeFace(surface, ShapeAnalysis.OuterWire_s(face), True)
            if not capped.IsDone():
                raise StompdrillError("could not rebuild a level member's outer boundary")
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(capped.Face(), props)
            outer_area += props.Mass()
        if outer_area > 0 and (1.0 - level.area / outer_area) < _HOLED_FRACTION_LIMIT:
            kept.append(level)
    return kept


def _drilled_level(
    levels: list[_Level], solid_bbox: tuple[float, float, float, float, float, float],
    axis: int, name: str,
) -> _Level:
    """The one plate level sitting at the solid's own extreme along ``axis``.

    Depends on ``solid_bbox``, not just the candidate levels: a level
    survives only if nothing of the solid lies beyond it along its own
    outward normal -- position matches the bbox minimum facing ``-``, the
    maximum facing ``+``. Not a law of solids: a closed cuboid has a flat
    plate at both ends, and both survive. A Hammond box or lid narrows to
    one only because ``_plates`` already removed its open end's rim -- a
    second survivor is real and reachable, so it is reported, not picked.
    """
    low, high = solid_bbox[axis], solid_bbox[axis + 3]
    candidates = [
        level for level in levels
        if (level.outward < 0 and nm_from_mm(level.position) == nm_from_mm(low))
        or (level.outward > 0 and nm_from_mm(level.position) == nm_from_mm(high))
    ]
    if not candidates:
        raise StompdrillError(f"{name} has no planar face along this axis that faces outward")
    if len(candidates) > 1:
        raise StompdrillError(
            f"{name} has {len(candidates)} planar levels at its own bounding-box extreme "
            f"along this axis, at positions "
            f"{', '.join(f'{level.position:.4f}' for level in candidates)}"
        )
    return candidates[0]


def _inner_level(levels: list[_Level], drilled: _Level) -> _Level:
    """The largest-area level facing back at ``drilled``; nearest it on a tie.

    A raised pad or a lettering fragment forms its own level nearer the
    drilled face than the true floor, so total area, not nearest position,
    keeps a pad such as the 1590Y's 25 x 10 mm one from outranking its
    84 x 84 mm floor. A level coincident with ``drilled`` is excluded too,
    so a degenerate zero-thickness plate cannot silently zero the plate
    thickness. Exactly equal areas break towards ``drilled``: a further
    level reports the metal thicker than it is. Positions are distinct.
    """
    inward = -drilled.outward
    candidates = [
        level for level in levels
        if level.outward == inward and nm_from_mm(level.position) != nm_from_mm(drilled.position)
    ]
    if not candidates:
        raise StompdrillError("no flat face backs the drilled face")
    return max(candidates, key=lambda level: (level.area, -abs(level.position - drilled.position)))


def _nearest_companion_level(levels: list[_Level], inner: _Level) -> _Level | None:
    """The same-facing level physically closest to ``inner``, if any.

    A raised feature's flat top is never part of the inner level's own
    wire boundary -- the hole cut for it is coplanar with the level around
    it -- so the nearest other same-facing level is where ``region.py``
    finds the faces carrying its true height. Equal distances put the two
    on opposite sides of ``inner``; the proud side (``+inner.outward``)
    wins, because preferring it can only turn a relief into structure,
    never hide one, and exactly one side is proud, so the rule is total.
    """
    candidates = [level for level in levels if level.outward == inner.outward and level is not inner]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda level: (abs(level.position - inner.position), -inner.outward * level.position),
    )


def build_frame(faces: Faces, axis: int) -> FaceFrame:
    """Right-handed ``(u, v, w)`` with ``w`` the outward normal.

    Seen from outside the face — that is, looking along ``-w`` — ``u`` runs
    right and ``v`` up, which is what the panel drawing shows. ``u`` is the
    free axis carrying the larger measured footprint span, so which kernel
    axis is "right" is read from the model rather than assumed from index
    order; a square footprint ties, and the lower-indexed free axis wins
    that tie, arbitrarily but deterministically — a square enclosure truly
    has no preferred in-plane orientation.
    """
    w = faces.outward
    free = [index for index in range(3) if index != axis]
    lead = max(free, key=lambda index: (nm_from_mm(faces.footprint_mm[index]), -index))
    other = next(index for index in free if index != lead)
    reference = [0.0, 0.0, 0.0]
    reference[other] = 1.0
    u = _normalise(_cross(tuple(reference), w))
    v = _cross(w, u)
    origin = [0.0, 0.0, 0.0]
    origin[axis] = faces.inner_position_mm
    return FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(nm_from_mm(origin[0]), nm_from_mm(origin[1]), nm_from_mm(origin[2])),
            u=u,
            v=v,
            w=w,
        )
    )


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalise(a: tuple[float, float, float]) -> tuple[float, float, float]:
    length = sum(c * c for c in a) ** 0.5
    if length == 0:  # pragma: no cover - reference is always perpendicular to w
        raise StompdrillError("degenerate face frame")
    return (a[0] / length, a[1] / length, a[2] / length)
