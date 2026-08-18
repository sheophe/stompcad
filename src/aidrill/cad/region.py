"""Build the drillable region of a flat face and test holes against it.

A die-cast flat face is the locus of nominal wall thickness, so its outer
boundary already excludes every boss. A raised feature's hole in that face
is exactly coplanar with the floor by construction, so its height is
invisible from the hole's own geometry; ``find_faces`` bundles each floor
with candidate companions so a hole pairs with the face that actually
carries its height. A hole is relief unless its companion stands proud by
more than the margin, in which case it is structure.
"""

from __future__ import annotations

from typing import Any

from ..errors import AidrillError
from ..units import Nanometre, mm_from_nm, nm_from_mm
from .base import Frame

__all__ = ["classify_bounds", "build_region", "region_bbox_nm", "contains"]

#: How close a companion's in-plane footprint must sit to a hole's own to
#: count as its match. Measured gaps top out at ~4e-7 mm across every cached
#: model (kernel-float noise); 0.01 mm is four orders of magnitude looser
#: than that and still far tighter than the spacing between distinct
#: features, so it cannot pair a hole with an unrelated patch.
_COMPANION_MATCH_MM = 0.01


def classify_bounds(
    face: Any, axis: int, margin_nm: Nanometre
) -> tuple[list[Any], list[Any]]:
    """Split the floor's inner wires into structure and cast relief.

    A hole whose companion face stands proud of the floor by more than the
    margin is structure; a hole with no companion is structure too, since an
    unmeasured depth is never safe to assume shallow.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from .step import bounding_box_mm

    floor = _floor_face(face)
    companions = _companions(face, floor)
    outer = ShapeAnalysis.OuterWire_s(floor)
    plane_at = bounding_box_mm(floor)[axis]
    limit = mm_from_nm(margin_nm)
    in_plane = [index for index in range(3) if index != axis]

    structure: list[Any] = []
    relief: list[Any] = []
    explorer = TopExp_Explorer(floor, TopAbs_ShapeEnum.TopAbs_WIRE)
    while explorer.More():
        wire = TopoDS.Wire_s(explorer.Current())
        if not wire.IsSame(outer):
            proud = _proud_mm(wire, companions, plane_at, axis, in_plane)
            (structure if proud > limit else relief).append(wire)
        explorer.Next()
    return structure, relief


def build_region(face: Any, axis: int, margin_nm: Nanometre) -> Any:
    """A face covering the drillable area: outer wire, minus structure wires."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeAnalysis import ShapeAnalysis
    from OCP.TopoDS import TopoDS

    floor = _floor_face(face)
    surface = BRep_Tool.Surface_s(floor)
    builder = BRepBuilderAPI_MakeFace(surface, ShapeAnalysis.OuterWire_s(floor), True)
    if not builder.IsDone():
        raise AidrillError("could not rebuild the flat face's drillable area")
    region = builder.Face()

    structure, _ = classify_bounds(face, axis, margin_nm)
    for wire in structure:
        adder = BRepBuilderAPI_MakeFace(region)
        adder.Add(TopoDS.Wire_s(wire.Reversed()))
        if adder.IsDone():
            region = adder.Face()
    return region


def region_bbox_nm(
    region: Any, frame: Frame, axis: int
) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre]:
    """The region's extent in canonical face coordinates, as nanometres.

    Every Hammond floor happens to sit centred on the kernel origin with
    ``u``/``v`` axis-aligned, which would let a bbox read straight off the
    kernel axes pass unnoticed; each in-plane corner is projected through
    ``frame`` instead, so an off-centre or rotated floor is handled too.
    """
    from .step import bounding_box_mm

    box = bounding_box_mm(region)
    in_plane = [index for index in range(3) if index != axis]
    corners = []
    for a in (box[in_plane[0]], box[in_plane[0] + 3]):
        for b in (box[in_plane[1]], box[in_plane[1] + 3]):
            point = [0.0, 0.0, 0.0]
            point[in_plane[0]] = a
            point[in_plane[1]] = b
            point[axis] = box[axis]
            corners.append(_to_canonical(frame, (point[0], point[1], point[2])))
    xs = [corner[0] for corner in corners]
    ys = [corner[1] for corner in corners]
    return (
        nm_from_mm(min(xs)),
        nm_from_mm(min(ys)),
        nm_from_mm(max(xs)),
        nm_from_mm(max(ys)),
    )


def contains(
    region: Any,
    frame: Frame,
    axis: int,
    x_nm: Nanometre,
    y_nm: Nanometre,
    radius_nm: Nanometre,
    margin_nm: Nanometre,
) -> bool:
    """Is the drill circle, grown by the margin, wholly inside ``region``?

    ``frame`` is only ever seated on the *drilled* face, never re-derived for
    ``region``'s own plane. ``region`` sits on a parallel plane offset along
    ``axis``, so the incoming point is projected onto that plane before
    classification, rather than requiring a second, region-specific frame
    from every caller.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_State

    from .step import bounding_box_mm

    point = list(_to_model(frame, x_nm, y_nm))
    plane_at = bounding_box_mm(region)[axis]
    point[axis] = plane_at

    classifier = BRepClass_FaceClassifier(region, gp_Pnt(*point), 1e-7)
    if classifier.State() != TopAbs_State.TopAbs_IN:
        return False

    clearance = mm_from_nm(Nanometre(radius_nm + margin_nm))
    vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
    distance = BRepExtrema_DistShapeShape(vertex, _boundary(region))
    if not distance.IsDone():
        raise AidrillError("could not measure clearance to the region boundary")
    return distance.Value() >= clearance


def _floor_face(face: Any) -> Any:
    """The largest planar face in ``face``, which may be a bare face or a compound.

    ``find_faces`` bundles the floor with candidate companion faces into a
    compound, so callers here must first pick the floor back out by area,
    exactly as ``case._outermost`` picks the drilled face.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if face.ShapeType() == TopAbs_ShapeEnum.TopAbs_FACE:
        return face

    best: Any = None
    best_area = -1.0
    explorer = TopExp_Explorer(face, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        candidate = TopoDS.Face_s(explorer.Current())
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(candidate, props)
        if props.Mass() > best_area:
            best_area, best = props.Mass(), candidate
        explorer.Next()
    if best is None:
        raise AidrillError("the play area's compound has no planar face")
    return best


def _companions(face: Any, floor: Any) -> list[Any]:
    """Every other face bundled alongside ``floor`` in ``face``."""
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if face.ShapeType() == TopAbs_ShapeEnum.TopAbs_FACE:
        return []

    found: list[Any] = []
    explorer = TopExp_Explorer(face, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        candidate = TopoDS.Face_s(explorer.Current())
        if not candidate.IsSame(floor):
            found.append(candidate)
        explorer.Next()
    return found


def _proud_mm(
    wire: Any, companions: list[Any], plane_at: float, axis: int, in_plane: list[int]
) -> float:
    """How far the hole's best-matching companion stands from the floor plane.

    The companion whose in-plane footprint is closest to the hole's own is
    its true feature, but only within ``_COMPANION_MATCH_MM``: with no
    companion close enough — including none at all — the height is
    unmeasured, so this reports it as unboundedly proud rather than
    assuming it is shallow.
    """
    from .step import bounding_box_mm

    box = bounding_box_mm(wire)
    best_gap: float | None = None
    best_position: float | None = None
    for candidate in companions:
        other = bounding_box_mm(candidate)
        gap = sum(abs(box[index] - other[index]) + abs(box[index + 3] - other[index + 3])
                  for index in in_plane)
        if best_gap is None or gap < best_gap:
            best_gap, best_position = gap, other[axis]
    if best_position is None or best_gap is None or best_gap > _COMPANION_MATCH_MM:
        return float("inf")
    return abs(best_position - plane_at)


def _boundary(region: Any) -> Any:
    """Every wire of ``region`` as one compound, for distance measurement."""
    from OCP.BRep import BRep_Builder
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    explorer = TopExp_Explorer(region, TopAbs_ShapeEnum.TopAbs_WIRE)
    while explorer.More():
        builder.Add(compound, explorer.Current())
        explorer.Next()
    return compound


def _to_model(frame: Frame, x_nm: Nanometre, y_nm: Nanometre) -> tuple[float, float, float]:
    """Map canonical face coordinates into model millimetres."""
    x, y = mm_from_nm(x_nm), mm_from_nm(y_nm)
    origin = tuple(mm_from_nm(value) for value in frame.origin_nm)
    return (
        origin[0] + x * frame.u[0] + y * frame.v[0],
        origin[1] + x * frame.u[1] + y * frame.v[1],
        origin[2] + x * frame.u[2] + y * frame.v[2],
    )


def _to_canonical(frame: Frame, point_mm: tuple[float, float, float]) -> tuple[float, float]:
    """The inverse of ``_to_model``: project a model point onto ``frame``'s own axes."""
    origin = tuple(mm_from_nm(value) for value in frame.origin_nm)
    relative = tuple(p - o for p, o in zip(point_mm, origin))
    x = sum(r * c for r, c in zip(relative, frame.u))
    y = sum(r * c for r, c in zip(relative, frame.v))
    return (x, y)
