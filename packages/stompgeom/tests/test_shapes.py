"""The compound builder: one idiom, one home."""

from __future__ import annotations

from typing import Any

import pytest

from stompgeom.shapes import compound


def _box(dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def _members(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_compound_holds_every_shape_given() -> None:
    """The whole set arrives, not the first or the last."""
    assert len(_members(compound([_box(1, 1, 1), _box(2, 2, 2), _box(3, 3, 3)]))) == 3


def test_compound_of_nothing_is_an_empty_compound() -> None:
    """A level with no faces is a value, not an error; see this task's Interfaces."""
    from OCP.TopAbs import TopAbs_ShapeEnum

    empty = compound([])
    assert empty.ShapeType() == TopAbs_ShapeEnum.TopAbs_COMPOUND
    assert _members(empty) == []


def test_compound_accepts_a_generator() -> None:
    """Callers pass generator expressions; a one-pass consumer must not break."""
    assert len(_members(compound(_box(n, n, n) for n in (1, 2)))) == 2


def _centre(shape: Any) -> tuple[float, float, float]:
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(shape)
    return tuple((box[i] + box[i + 3]) / 2 for i in range(3))  # type: ignore[return-value]


def _vertices(shape: Any) -> set[tuple[float, float, float]]:
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_VERTEX)
    found = set()
    while explorer.More():
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))
        found.add((round(point.X(), 9), round(point.Y(), 9), round(point.Z(), 9)))
        explorer.Next()
    return found


def test_placed_moves_the_shape() -> None:
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    moved = placed(_box(2, 2, 2), RigidTransform(identity, (10.0, 0.0, 0.0)))
    assert round(_centre(moved)[0], 9) == 11.0


def test_placed_rotates_as_well_as_translates() -> None:
    """A translation-only implementation passes the test above and fails this."""
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    quarter_turn = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    moved = placed(_box(4, 2, 2), RigidTransform(quarter_turn, (0.0, 0.0, 0.0)))
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(moved)
    assert round(box[4] - box[1], 9) == 4.0     # the long axis is now y


def test_placed_agrees_with_apply_point_on_a_named_vertex() -> None:
    """``placed`` must realise exactly the motion ``RigidTransform`` describes.

    The rotation above is checked only by bounding-box extent, which a
    transposed rotation matrix (the classic row/column mix-up feeding
    ``gp_Trsf.SetValues``) leaves unchanged: an axis-aligned box's extent
    is the same magnitude whichever way a 90-degree turn runs, so a
    transpose is invisible to an extent-only assertion, symmetric box or
    not. Naming one corner and comparing against the model-side
    ``RigidTransform.apply_point`` pins the rotation's direction as well
    as its magnitude, and pins the seam between the kernel and the model
    that Tasks 9, 19 and 21 depend on holding.
    """
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    quarter_turn = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    motion = RigidTransform(quarter_turn, (5.0, 7.0, 11.0))

    # (4, 2, 3): no repeated dimension, so no accidental symmetry masks a
    # transposed rotation the way a cube or a centred shape could.
    far_corner = (4.0, 0.0, 0.0)
    expected = tuple(round(c, 9) for c in motion.apply_point(far_corner))

    moved = placed(_box(4, 2, 3), motion)
    assert expected in _vertices(moved)


def test_placed_leaves_the_original_alone() -> None:
    """Value semantics: the workspace's transforms return replacements."""
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    original = _box(2, 2, 2)
    placed(original, RigidTransform(identity, (10.0, 0.0, 0.0)))
    assert round(_centre(original)[0], 9) == 1.0


def test_placed_returns_a_location_not_a_rebuild() -> None:
    """A location moves the placement, not the geometry underneath it.

    This is the test the brief warns is missing from the obvious version: a
    ``BRepBuilderAPI_Transform`` result also passes the two tests above, but
    it carries an identity ``TopLoc_Location`` because it baked the motion
    into fresh vertices instead. Only a genuine ``TopoDS_Shape.Moved`` result
    carries the motion in its location.
    """
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    moved = placed(_box(2, 2, 2), RigidTransform(identity, (10.0, 0.0, 0.0)))

    location = moved.Location()
    assert not location.IsIdentity()

    translation = location.Transformation().TranslationPart()
    assert round(translation.X(), 9) == 10.0
    assert round(translation.Y(), 9) == 0.0
    assert round(translation.Z(), 9) == 0.0


def test_placed_shares_the_original_topology() -> None:
    """A located copy is a partner of its original; a rebuild is not.

    ``TopoDS_Shape.IsPartner`` compares the underlying ``TShape``, which a
    location shares and a ``BRepBuilderAPI_Transform`` rebuild does not.
    """
    from stompgeom.shapes import placed
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    original = _box(2, 2, 2)
    moved = placed(original, RigidTransform(identity, (10.0, 0.0, 0.0)))

    assert moved.IsPartner(original)


def test_compound_preserves_the_order_shapes_were_given() -> None:
    """The member sequence must match the input sequence, not just its set.

    Three distinct-sized boxes give three distinguishable members; each
    box's own volume is a stable fingerprint that survives the trip through
    the kernel, whereas a raw ``TopoDS`` handle is not reliably comparable
    by identity across a build. Comparing volumes in traversal order proves
    ``compound`` neither reverses nor sorts what it was given -- the promise
    ``stompgeom.shapes.compound``'s docstring makes.
    """
    boxes = [_box(1, 1, 1), _box(2, 2, 2), _box(3, 3, 3)]
    recovered = [_volume(member) for member in _members(compound(boxes))]
    assert recovered == pytest.approx([1.0, 8.0, 27.0])
