"""Build the drillable region of a flat face and test holes against it.

A die-cast flat face is the locus of nominal wall thickness, so its outer
boundary already excludes every boss. A raised feature's hole in that face
is coplanar with the floor by construction, so its height is invisible from
the hole's own geometry; ``find_faces`` bundles each floor with candidate
companions so a hole pairs with the face carrying its height. Relief unless
a companion stands proud -- away from the drilled face, into the cavity --
past ``_STRUCTURE_HEIGHT_MM``; a receding companion removes material, never structure.
"""

from __future__ import annotations

from typing import Any

from stompmodel.frames import FaceFrame
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

from ..errors import StompdrillError

__all__ = [
    "classify_bounds", "build_region", "region_bbox_nm", "contains",
    "clearance_reason",
]

#: How close a companion's in-plane footprint must sit to a hole's own to
#: count as its match. Measured gaps top out at ~4e-7 mm across every cached
#: model (kernel-float noise); 0.01 mm is four orders of magnitude looser
#: than that and still far tighter than the spacing between distinct
#: features, so it cannot pair a hole with an unrelated patch.
_COMPANION_MATCH_MM = 0.01

#: How far a companion must stand proud of the floor -- away from the drilled
#: face, into the cavity -- before it is structure rather than cast relief.
#: Not a clearance: pedal builders drill straight through lettering, and on
#: many castings its background is flush or recessed, so height above the
#: floor -- not distance from a bit -- is what tells relief from a real boss.
#: Cast lettering measures 0.50 mm proud on the 1590BB
#: (``tests.hammond.BB_RELIEF_MM``) and is often flush or recessed; a moulded
#: boss or standoff is millimetres. 2.0 mm sits in that gap with 4x headroom
#: over the tallest lettering measured. No cached model's own structure needs
#: this exact value -- see the synthetic tests in
#: ``tests/test_cad_region_synthetic.py``.
_STRUCTURE_HEIGHT_MM = 2.0


def classify_bounds(face: Any, axis: int, outward: float) -> tuple[list[Any], list[Any]]:
    """Split the floor's inner wires into structure and cast relief.

    ``outward`` is the drilled face's own outward normal component along
    ``axis`` (``Faces.outward[axis]``): a companion further from the drilled
    face than the floor stands proud, one nearer it recedes and is never
    structure -- ``_proud_mm`` needs the sign to tell those apart, not just
    a distance. A hole with no companion is structure too, since an
    unmeasured depth is never safe to assume shallow.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from stompgeom.step import bounding_box_mm

    floor = _floor_face(face)
    companions = _companions(face, floor)
    outer = ShapeAnalysis.OuterWire_s(floor)
    plane_at = bounding_box_mm(floor)[axis]
    in_plane = [index for index in range(3) if index != axis]

    structure: list[Any] = []
    relief: list[Any] = []
    explorer = TopExp_Explorer(floor, TopAbs_ShapeEnum.TopAbs_WIRE)
    while explorer.More():
        wire = TopoDS.Wire_s(explorer.Current())
        if not wire.IsSame(outer):
            proud = _proud_mm(wire, companions, plane_at, axis, in_plane, outward)
            (structure if proud > _STRUCTURE_HEIGHT_MM else relief).append(wire)
        explorer.Next()
    return structure, relief


def build_region(face: Any, axis: int, outward: float) -> Any:
    """A face covering the drillable area: outer wire, minus structure wires."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeAnalysis import ShapeAnalysis
    from OCP.TopoDS import TopoDS

    floor = _floor_face(face)
    surface = BRep_Tool.Surface_s(floor)
    builder = BRepBuilderAPI_MakeFace(surface, ShapeAnalysis.OuterWire_s(floor), True)
    if not builder.IsDone():
        raise StompdrillError("could not rebuild the flat face's drillable area")
    region = builder.Face()

    structure, _ = classify_bounds(face, axis, outward)
    # No guard on the subtraction: ``BRepBuilderAPI_MakeFace.Add`` reports done
    # unconditionally, so a wire the kernel could not use is indistinguishable
    # here from one it took. A dropped structure wire would widen the drillable
    # region silently, and nothing at this point can detect it -- see
    # ``tests/test_cad_region_synthetic.py``'s hostile-wire test for the fact.
    for wire in structure:
        adder = BRepBuilderAPI_MakeFace(region)
        adder.Add(TopoDS.Wire_s(wire.Reversed()))
        region = adder.Face()
    return region


def region_bbox_nm(
    region: Any, frame: FaceFrame, axis: int
) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre]:
    """The region's extent in canonical face coordinates, as nanometres.

    Every Hammond floor happens to sit centred on the kernel origin with
    ``u``/``v`` axis-aligned, which would let a bbox read straight off the
    kernel axes pass unnoticed; each in-plane corner is projected through
    ``frame`` instead, so an off-centre or rotated floor is handled too.
    """
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(region)
    in_plane = [index for index in range(3) if index != axis]
    corners = []
    for a in (box[in_plane[0]], box[in_plane[0] + 3]):
        for b in (box[in_plane[1]], box[in_plane[1] + 3]):
            point = [0.0, 0.0, 0.0]
            point[in_plane[0]] = a
            point[in_plane[1]] = b
            point[axis] = box[axis]
            corners.append(frame.basis.to_canonical((point[0], point[1], point[2])))
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
    frame: FaceFrame,
    axis: int,
    x_nm: Nanometre,
    y_nm: Nanometre,
    radius_nm: Nanometre,
    margin_nm: Nanometre,
) -> bool:
    """Is the drill circle, grown by the margin, wholly inside ``region``?

    ``frame`` is never re-derived for ``region``'s own plane: ``region`` sits
    on a parallel plane offset along ``axis``, so the incoming point's
    ``axis`` component is overwritten with that plane before classification,
    whichever surface ``frame``'s own origin registers -- rather than
    requiring a second, region-specific frame from every caller.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_State

    from stompgeom.step import bounding_box_mm

    point: list[float] = list(frame.basis.to_model(x_nm, y_nm))
    plane_at = bounding_box_mm(region)[axis]
    point[axis] = plane_at

    classifier = BRepClass_FaceClassifier(region, gp_Pnt(*point), 1e-7)
    if classifier.State() != TopAbs_State.TopAbs_IN:
        return False

    clearance = mm_from_nm(Nanometre(radius_nm + margin_nm))
    vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
    distance = BRepExtrema_DistShapeShape(vertex, _boundary(region))
    if not distance.IsDone():
        raise StompdrillError("could not measure clearance to the region boundary")
    return distance.Value() >= clearance


def clearance_reason(
    region: Any, frame: FaceFrame, axis: int, x_nm: Nanometre, y_nm: Nanometre
) -> str:
    """Which kind of boundary is nearest a point that failed ``contains``.

    ``region``'s own inner wires are exactly the structure wires
    ``build_region`` subtracted, so wire membership alone names
    ``"structure"``. An outer-wire arc is ``"concave"`` (a boss bitten
    straight into the boundary -- see ``case._plates``) when its centre
    lies outside the region, else ``"convex"``. These partition every edge
    ``contains`` measured, so whichever is nearest is the true reason.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.GeomAbs import GeomAbs_CurveType
    from OCP.gp import gp_Pnt
    from OCP.ShapeAnalysis import ShapeAnalysis
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_State
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Compound

    from stompgeom.step import bounding_box_mm

    def edge_group(edge: Any, on_outer: bool) -> str:
        if not on_outer:
            return "structure"
        adaptor = BRepAdaptor_Curve(edge)
        if adaptor.GetType() == GeomAbs_CurveType.GeomAbs_Circle:
            centre = adaptor.Circle().Location()
            classifier = BRepClass_FaceClassifier(region, centre, 1e-7)
            if classifier.State() != TopAbs_State.TopAbs_IN:
                return "concave"
        return "convex"

    def nearest_mm(vertex: Any, edges: list[Any]) -> float:
        if not edges:
            return float("inf")
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        for edge in edges:
            builder.Add(compound, edge)
        distance = BRepExtrema_DistShapeShape(vertex, compound)
        if not distance.IsDone():
            raise StompdrillError("could not measure clearance to a boundary edge group")
        return distance.Value()

    point: list[float] = list(frame.basis.to_model(x_nm, y_nm))
    plane_at = bounding_box_mm(region)[axis]
    point[axis] = plane_at
    vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()

    outer = ShapeAnalysis.OuterWire_s(region)
    groups: dict[str, list[Any]] = {"structure": [], "concave": [], "convex": []}
    wires = TopExp_Explorer(region, TopAbs_ShapeEnum.TopAbs_WIRE)
    while wires.More():
        wire = TopoDS.Wire_s(wires.Current())
        on_outer = wire.IsSame(outer)
        edges = TopExp_Explorer(wire, TopAbs_ShapeEnum.TopAbs_EDGE)
        while edges.More():
            edge = TopoDS.Edge_s(edges.Current())
            groups[edge_group(edge, on_outer)].append(edge)
            edges.Next()
        wires.Next()

    return min(groups, key=lambda key: nearest_mm(vertex, groups[key]))


def _floor_face(face: Any) -> Any:
    """The largest planar face in ``face``, which may be a bare face or a compound.

    ``find_faces`` bundles the floor with candidate companion faces into a
    compound, so the floor is picked back out here by **one face's own**
    area -- not by ``case._inner_level``'s aggregate over a whole level,
    which would merge the floor with the very companions the bundle exists
    to keep separable. Exactly equal areas break on the candidates' own
    bounding boxes in whole nanometres, greatest first, minima before
    maxima; alike on both keys they are interchangeable and either wins.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from stompgeom.step import bounding_box_mm

    if face.ShapeType() == TopAbs_ShapeEnum.TopAbs_FACE:
        return face

    best: Any = None
    best_key: tuple[float, tuple[Nanometre, ...]] | None = None
    explorer = TopExp_Explorer(face, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        candidate = TopoDS.Face_s(explorer.Current())
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(candidate, props)
        key = (props.Mass(), tuple(nm_from_mm(value) for value in bounding_box_mm(candidate)))
        if best_key is None or key > best_key:
            best_key, best = key, candidate
        explorer.Next()
    if best is None:
        raise StompdrillError("the play area's compound has no planar face")
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
    wire: Any, companions: list[Any], plane_at: float, axis: int, in_plane: list[int],
    outward: float,
) -> float:
    """How far the hole's best-matching companion stands proud of the floor.

    The companion whose in-plane footprint is closest to the hole's own is
    its true feature, but only within ``_COMPANION_MATCH_MM``: with no
    match -- including none at all -- the height is unmeasured, reported as
    unboundedly proud rather than assumed shallow. Signed, not a distance:
    standing proud of the floor is positive; receding into the material is
    negative and never structure. An exactly equal gap breaks towards the
    most proud candidate, so the number cannot vary with arrival order.
    """
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(wire)
    best: tuple[float, float] | None = None
    for candidate in companions:
        other = bounding_box_mm(candidate)
        gap = sum(abs(box[index] - other[index]) + abs(box[index + 3] - other[index + 3])
                  for index in in_plane)
        key = (gap, -((plane_at - other[axis]) * outward))
        if best is None or key < best:
            best = key
    if best is None or best[0] > _COMPANION_MATCH_MM:
        return float("inf")
    return -best[1]


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
