"""Locate what a drilled enclosure side consists of.

The domain layer: which solid is the box, which axis the drill runs along,
which planar face is drilled, which flat face backs it, and the right-handed
frame that puts canonical coordinates on that face.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import AidrillError
from ..units import Nanometre, nm_from_mm
from .base import Frame
from .step import StepDocument, StepSolid, bounding_box_mm

__all__ = [
    "Faces", "drill_axis", "assembly_spans", "select_solid", "find_faces",
    "build_frame",
]

#: How far a measured span may differ from the catalogue and still match, in
#: millimetres. Hammond publishes to 0.1 mm; a tenth either way is generous
#: without letting a 1590B pass as a 1590BS.
_MATCH_TOLERANCE_MM = 0.6

_FACE_KEYWORDS = {"box": "BOX", "lid": "LID"}


@dataclass(frozen=True)
class Faces:
    """The two planar faces bounding a drilled plate, and its thickness."""

    drilled: Any
    inner: Any
    plate_nm: Nanometre
    outward: tuple[float, float, float]
    drilled_position_mm: float
    inner_position_mm: float


def drill_axis(document: StepDocument, footprint_nm: tuple[Nanometre, Nanometre]) -> int:
    """Return the index of the axis normal to the catalogue footprint plane."""
    spans = assembly_spans(document)
    wanted = sorted(float(nm) / 1_000_000 for nm in footprint_nm)
    for axis in range(3):
        plane = sorted(spans[other] for other in range(3) if other != axis)
        if all(abs(a - b) <= _MATCH_TOLERANCE_MM for a, b in zip(plane, wanted)):
            return axis
    raise AidrillError(
        f"no face of the model has the catalogue footprint "
        f"{wanted[1]:.2f} x {wanted[0]:.2f} mm; measured spans are "
        f"{spans[0]:.2f}, {spans[1]:.2f}, {spans[2]:.2f} mm"
    )


def assembly_spans(document: StepDocument) -> tuple[float, float, float]:
    """The bounding-box span of every solid together, per axis, in millimetres."""
    boxes = [bounding_box_mm(solid.shape) for solid in document.solids]
    lows = [min(b[axis] for b in boxes) for axis in range(3)]
    highs = [max(b[axis + 3] for b in boxes) for axis in range(3)]
    return (highs[0] - lows[0], highs[1] - lows[1], highs[2] - lows[2])


def select_solid(document: StepDocument, face: str) -> StepSolid:
    """Pick the box or lid solid, by name and then verified by thickness."""
    keyword = _FACE_KEYWORDS.get(face)
    if keyword is None:
        raise AidrillError(f"unknown case face {face!r}; expected 'box' or 'lid'")
    found = document.named(keyword)
    if len(found) != 1:
        raise AidrillError(
            f"the model names {len(found)} products containing {keyword!r}; "
            f"exactly one is needed to drill the {face}"
        )
    return found[0]


def find_faces(solid: StepSolid, axis: int) -> Faces:
    """Find the outermost planar face along ``axis`` and the flat face behind it."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    centre = sum(bounding_box_mm(solid.shape)[i] for i in (axis, axis + 3)) / 2.0

    planes: list[tuple[float, float, float, Any]] = []
    explorer = TopExp_Explorer(solid.shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            plane = adaptor.Plane()
            normal = plane.Axis().Direction()
            components = (normal.X(), normal.Y(), normal.Z())
            if abs(abs(components[axis]) - 1.0) < 1e-9:
                sign = -1.0 if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED else 1.0
                outward = components[axis] * sign
                position = bounding_box_mm(face)[axis]
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, props)
                planes.append((props.Mass(), position, outward, face))
        explorer.Next()

    if len(planes) < 2:
        raise AidrillError(
            f"{solid.name} has fewer than two planar faces normal to the drill axis"
        )

    outermost = _outermost(planes, centre, solid.name)
    inner = _facing(planes, outermost)
    thickness = abs(inner[1] - outermost[1])
    normal = [0.0, 0.0, 0.0]
    normal[axis] = outermost[2]
    return Faces(
        drilled=outermost[3],
        inner=_with_companions(planes, inner, axis),
        plate_nm=nm_from_mm(thickness),
        outward=(normal[0], normal[1], normal[2]),
        drilled_position_mm=outermost[1],
        inner_position_mm=inner[1],
    )


def _with_companions(
    planes: list[tuple[float, float, float, Any]],
    inner: tuple[float, float, float, Any],
    axis: int,
) -> Any:
    """The inner face bundled with nearby same-facing planar faces, as one compound.

    A raised feature's own flat top never shows up in the inner face's own
    wire boundary: the hole cut for it is, by construction, exactly coplanar
    with the floor around it, so its true height is invisible from the hole's
    own geometry. Bundling every other candidate flat patch within the
    floor's own footprint lets ``region.py`` pair each hole with the face
    that actually carries its height, without ``find_faces`` guessing which
    hole is which.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, inner[3])

    footprint = bounding_box_mm(inner[3])
    in_plane = [index for index in range(3) if index != axis]
    for _area, position, outward, face in planes:
        if outward != inner[2] or nm_from_mm(position) == nm_from_mm(inner[1]):
            continue
        box = bounding_box_mm(face)
        if all(
            footprint[index] - 0.01 <= box[index] and box[index + 3] <= footprint[index + 3] + 0.01
            for index in in_plane
        ):
            builder.Add(compound, face)
    return compound


def _outermost(
    planes: list[tuple[float, float, float, Any]], centre: float, name: str
) -> tuple[float, float, float, Any]:
    """The drilled face: the largest outward-facing planar face on the axis.

    Orientation filters rather than breaks ties: a candidate must sit on the
    far side of the solid's own centre in the direction its own normal
    claims (``(position - centre) * outward > 0``), so an internal floor or
    boss pad can never masquerade as the drilled face by facing the wrong
    way. Area then picks among survivors, since a lid's skirt tip can sit
    further along the axis than its actual cap plate, which is always the
    biggest flat surface a casting offers.
    """
    candidates = [item for item in planes if (item[1] - centre) * item[2] > 0]
    if not candidates:
        raise AidrillError(f"{name} has no planar face along this axis that faces outward")
    return max(candidates, key=lambda item: item[0])


def _facing(
    planes: list[tuple[float, float, float, Any]], drilled: tuple[float, float, float, Any]
) -> tuple[float, float, float, Any]:
    """The nearest parallel face that looks back at ``drilled``, ties broken by area.

    A cast floor with holes for raised lettering can tessellate into many small
    coplanar patches alongside the true floor; kernel-float noise then makes
    their distances differ below nanometre precision. Rounding the distance to
    whole nanometres before comparing collapses that noise so the tie is broken
    by area, as ``_outermost`` already does, rather than by explorer order.
    """
    inward = -drilled[2]
    candidates = [
        item
        for item in planes
        if item[2] == inward and abs(item[1] - drilled[1]) > 1e-9
    ]
    if not candidates:
        raise AidrillError("no flat face backs the drilled face")
    return min(
        candidates,
        key=lambda item: (abs(nm_from_mm(item[1]) - nm_from_mm(drilled[1])), -item[0]),
    )


def build_frame(faces: Faces, axis: int) -> Frame:
    """Right-handed ``(u, v, w)`` with ``w`` the outward normal.

    Seen from outside the face — that is, looking along ``-w`` — ``u`` runs
    right and ``v`` up, which is what the panel drawing shows. ``u`` is built
    from the higher-indexed axis of the two the drill axis leaves free, so it
    lands on the lower-indexed one: a reference chosen from the axis ``u``
    must avoid, rather than a fixed guess, needs no near-parallel guard and
    keeps which kernel axis is "right" a function of the model, not luck.
    """
    w = faces.outward
    other = max(index for index in range(3) if index != axis)
    reference = [0.0, 0.0, 0.0]
    reference[other] = 1.0
    u = _normalise(_cross(tuple(reference), w))
    v = _cross(w, u)
    origin = [0.0, 0.0, 0.0]
    origin[axis] = faces.drilled_position_mm
    return Frame(
        origin_nm=(nm_from_mm(origin[0]), nm_from_mm(origin[1]), nm_from_mm(origin[2])),
        u=u,
        v=v,
        w=w,
    )


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalise(a: tuple[float, float, float]) -> tuple[float, float, float]:
    length = sum(c * c for c in a) ** 0.5
    if length == 0:
        raise AidrillError("degenerate face frame")
    return (a[0] / length, a[1] / length, a[2] / length)
