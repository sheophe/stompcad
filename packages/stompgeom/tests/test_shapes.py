"""The compound builder: one idiom, one home."""

from __future__ import annotations

import math
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
    """A level with no faces is a value, not an error."""
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
    ``gp_Trsf.SetValues``) leaves unchanged: an axis-aligned box's extent is
    the same magnitude whichever way a 90-degree turn runs. Naming one corner
    and comparing against the model-side ``RigidTransform.apply_point`` pins
    the rotation's direction as well as its magnitude, which is the seam every
    kernel-side placement in this workspace rests on.
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

    This is the test the obvious version of this check is missing: a
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


# --------------------------------------------------------------------------
# ``common``: the exact intersection of two shapes.
# --------------------------------------------------------------------------


def _box_at(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _cylinder(at: tuple[float, float, float], radius: float, height: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*at), gp_Dir(0.0, 0.0, 1.0)), radius, height
    ).Shape()


def _bored_plate(radius: float) -> Any:
    """A 40 x 40 x 3 plate with one bore of ``radius`` through its centre."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    plate = _box_at((0.0, 0.0, 0.0), 40.0, 40.0, 3.0)
    bore = _cylinder((20.0, 20.0, -5.0), radius, 13.0)
    return BRepAlgoAPI_Cut(plate, bore).Shape()


def test_common_is_the_region_two_shapes_share() -> None:
    """Not one of the arguments, and not their union: the shared region alone."""
    from stompgeom.shapes import common
    from stompgeom.step import bounding_box_mm

    region = common(_box_at((0, 0, 0), 10, 10, 10), _box_at((8, 0, 0), 10, 40, 40))

    assert region is not None
    assert tuple(round(v, 9) for v in bounding_box_mm(region)) == (
        8.0, 0.0, 0.0, 10.0, 10.0, 10.0,
    )


def test_common_of_two_disjoint_shapes_is_none() -> None:
    """``None`` rather than an empty compound, whose bounding box cannot be read."""
    from stompgeom.shapes import common

    assert common(_box_at((0, 0, 0), 10, 10, 10), _box_at((11, 0, 0), 10, 10, 10)) is None


def test_common_of_two_shapes_meeting_on_one_face_is_none() -> None:
    """Planar contact shares a face and no volume, so there is no region."""
    from stompgeom.shapes import common

    assert common(_box_at((0, 0, 0), 10, 10, 10), _box_at((10, 0, 0), 10, 10, 10)) is None


def test_common_of_a_shaft_exactly_filling_its_bore_is_none() -> None:
    """Curved contact, not planar: a 12.000 shaft in a 12.000 bore.

    The kernel's own answer for an interference fit at exactly nominal, and
    the fact ``stompcollider``'s contact rule rests on. A cylindrical face
    is shared, so a boolean returning shared *faces* would hand back a
    region 12 mm across and 3 mm deep here -- a clash where there is none.
    """
    from stompgeom.shapes import common

    assert common(_bored_plate(6.0), _cylinder((20.0, 20.0, -10.0), 6.0, 20.0)) is None


def test_common_of_a_shaft_wider_than_its_bore_is_a_region() -> None:
    """The innocent probe beside it: a rule returning ``None`` for everything
    would pass every test above. One micron of radial interference is a region."""
    from stompgeom.shapes import common
    from stompgeom.step import bounding_box_mm

    region = common(_bored_plate(6.0), _cylinder((20.0, 20.0, -10.0), 6.001, 20.0))

    assert region is not None
    assert round(bounding_box_mm(region)[3] - bounding_box_mm(region)[0], 9) == 12.002


def test_common_refuses_a_boolean_the_kernel_could_not_evaluate() -> None:
    """A failed boolean is a failure, never an empty answer: silently
    reporting "no shared region" for a shape the kernel choked on would read
    as clearance."""
    from OCP.TopoDS import TopoDS_Shape

    from stompgeom.errors import StompgeomError
    from stompgeom.shapes import common

    with pytest.raises(StompgeomError):
        common(TopoDS_Shape(), _box_at((0, 0, 0), 10, 10, 10))


def test_common_leaves_its_arguments_fit_to_be_asked_again() -> None:
    """The pair a search asks repeatedly is the pair a clash check measures.

    A destructive boolean rewrites the ``TShape`` its arguments share with
    every located copy of them, so a later query of those same solids reads
    geometry an earlier one produced -- and a board resting at contact then
    answers one way before its clash region is measured and another way
    after. Two shapes, three questions, one answer each time.
    """
    from stompgeom.shapes import common, interferes, volume_mm3

    plate, shaft = _bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.001, 13.0)
    before = interferes(plate, shaft)
    volumes = [volume_mm3(common(plate, shaft)) for _ in range(2)]

    assert before is True
    assert interferes(plate, shaft) is True
    assert volumes[0] == pytest.approx(volumes[1])


def test_common_is_symmetric_in_its_arguments() -> None:
    """Neither argument is privileged; the same pair either way round is one region."""
    from stompgeom.shapes import common
    from stompgeom.step import bounding_box_mm

    first = _box_at((0, 0, 0), 10, 10, 10)
    second = _box_at((8, 1, 2), 10, 10, 10)

    assert bounding_box_mm(common(first, second)) == pytest.approx(
        bounding_box_mm(common(second, first)), abs=1e-9
    )


# --------------------------------------------------------------------------
# ``volume_mm3``: how much material a region actually holds.
# --------------------------------------------------------------------------


def test_volume_mm3_is_the_material_a_shape_holds() -> None:
    """A box of known size, in cubic millimetres."""
    from stompgeom.shapes import volume_mm3

    assert volume_mm3(_box_at((3, 5, 7), 2.0, 3.0, 4.0)) == pytest.approx(24.0)


def test_volume_mm3_is_not_the_volume_of_the_bounding_box() -> None:
    """The whole reason this exists beside a box: a cylinder fills pi/4 of the
    box around it, so a rule reading the box back would answer 8.0 here."""
    from stompgeom.shapes import volume_mm3

    measured = volume_mm3(_cylinder((0.0, 0.0, 0.0), 1.0, 2.0))

    assert measured == pytest.approx(2.0 * math.pi)
    assert measured < 8.0


def test_volume_mm3_of_a_common_region_measures_that_region_alone() -> None:
    """The call ``Clashes`` makes: the material two solids share, not either
    solid's own and not the box around what they share."""
    from stompgeom.shapes import common, volume_mm3

    region = common(_box_at((0, 0, 0), 10, 10, 10), _box_at((8, 0, 0), 10, 40, 40))

    assert volume_mm3(region) == pytest.approx(2.0 * 10.0 * 10.0)


def test_volume_mm3_of_a_region_that_is_not_a_box_is_far_under_its_box() -> None:
    """The measured claim the spec states: a shaft through a plate shares a
    cylinder, whose box overstates the material by a fixed factor."""
    from stompgeom.shapes import common, volume_mm3
    from stompgeom.step import bounding_box_mm

    region = common(
        _box_at((15.0, 15.0, 0.0), 10.0, 10.0, 3.0),
        _cylinder((20.0, 20.0, -5.0), 2.0, 13.0),
    )
    box = bounding_box_mm(region)
    boxed = (box[3] - box[0]) * (box[4] - box[1]) * (box[5] - box[2])

    assert volume_mm3(region) == pytest.approx(math.pi * 4.0 * 3.0)
    assert boxed == pytest.approx(4.0 * 4.0 * 3.0)


def test_volume_mm3_of_a_flat_face_is_nothing() -> None:
    """A region with no thickness holds no material; contact is not a clash."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

    from stompgeom.shapes import volume_mm3

    plane = gp_Pln(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    assert volume_mm3(BRepBuilderAPI_MakeFace(plane, 0.0, 4.0, 0.0, 5.0).Face()) == (
        pytest.approx(0.0)
    )


# --------------------------------------------------------------------------
# ``interferes``: whether two shapes share positive volume, asked repeatedly.
# --------------------------------------------------------------------------


def test_interferes_is_true_of_two_shapes_that_overlap() -> None:
    from stompgeom.shapes import interferes

    assert interferes(_box_at((0, 0, 0), 10, 10, 10), _box_at((8, 0, 0), 10, 40, 40))


def test_interferes_is_false_of_two_disjoint_shapes() -> None:
    from stompgeom.shapes import interferes

    assert not interferes(_box_at((0, 0, 0), 10, 10, 10), _box_at((30, 0, 0), 10, 10, 10))


def test_two_shapes_meeting_on_a_face_do_not_interfere() -> None:
    """Contact is not interference: the board may advance to that pose.

    Rule 3 of "Contact is not a clash" applied to a path rather than to a
    resting place -- two boxes sharing a whole face share no material, so a
    search using this predicate is not stopped by touching.
    """
    from stompgeom.shapes import interferes

    assert not interferes(_box_at((0, 0, 0), 10, 10, 10), _box_at((10, 0, 0), 10, 10, 10))


def test_a_shaft_exactly_filling_its_bore_does_not_interfere() -> None:
    """The curved case beside the planar one: a 12.000 mm shaft in a
    12.000 mm bore touches over a whole cylinder and passes anyway."""
    from stompgeom.shapes import interferes

    assert not interferes(_bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.0, 13.0))


def test_one_micron_of_radial_interference_is_interference() -> None:
    """The control beside the two above: a predicate answering ``False`` to
    everything would pass them both and fail here."""
    from stompgeom.shapes import interferes

    assert interferes(_bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.001, 13.0))


def test_several_shapes_that_overlap_each_other_are_asked_of_as_a_sequence() -> None:
    """A sequence is several operands; a compound is one shape.

    Handed *one* shape holding parts that intersect each other the kernel
    reads a self-intersecting argument and answers nothing at all, silently,
    for a pair that really does share a region. A caller whose bundle may
    meet itself passes a sequence, and both booleans then answer it.
    """
    from stompgeom.shapes import common, compound, interferes

    board = _box_at((0, 0, 0), 21, 14, 10)
    wall = _box_at((20, -50, -30), 4, 100, 40)
    lid = _box_at((-50, -50, 8), 100, 100, 3)

    assert interferes(board, [wall, lid])
    assert common(board, [wall, lid]) is not None
    assert not interferes(board, compound([wall, lid]))


def test_the_members_of_that_bundle_do_overlap_each_other() -> None:
    """The control beside it: the fixture states the condition it is about,
    so the sequence form is being tested on the case that needs it rather
    than on two disjoint solids that any spelling would answer."""
    from stompgeom.shapes import interferes

    assert interferes(
        _box_at((20, -50, -30), 4, 100, 40), _box_at((-50, -50, 8), 100, 100, 3)
    )


def test_a_sequence_holding_nothing_shares_nothing_rather_than_raising() -> None:
    """No operands is a legitimate value -- a level with no faces, a board
    whose boxes reach no solid -- and the answer is that nothing is shared."""
    from stompgeom.shapes import common, interferes

    assert not interferes(_box_at((0, 0, 0), 10, 10, 10), [])
    assert common([], _box_at((0, 0, 0), 10, 10, 10)) is None


def test_interferes_leaves_its_arguments_fit_to_be_asked_again() -> None:
    """Non-destructive: the same pair, asked twice, answers the same twice.

    A destructive boolean modifies the ``TShape`` its arguments share with
    every located copy of them, so the second query of a search reads
    geometry the first one rewrote. The search asks one pair at many poses,
    which is the only use that reaches this.
    """
    from stompgeom.shapes import interferes

    plate, shaft = _bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.001, 13.0)
    answers = [interferes(plate, shaft) for _ in range(3)]

    assert answers == [True, True, True]


def test_the_same_shapes_moved_apart_and_back_answer_the_same() -> None:
    """The control for non-destructiveness: located copies of one solid, asked
    in a sequence, must not have their shared topology consumed by an
    earlier query -- so an interleaved sequence reads the same as a plain one."""
    from stompgeom.shapes import interferes, placed
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    plate, shaft = _bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.001, 13.0)
    offsets = (0.0, 40.0, 0.0, 40.0, 0.0)
    answers = [
        interferes(placed(shaft, RigidTransform(identity, (offset, 0.0, 0.0))), plate)
        for offset in offsets
    ]

    assert answers == [True, False, True, False, True]


# --------------------------------------------------------------------------
# ``centre_of_mass_mm``: where a solid's material sits.
# --------------------------------------------------------------------------


def test_centre_of_mass_of_a_box_is_its_middle() -> None:
    from stompgeom.shapes import centre_of_mass_mm

    centre = centre_of_mass_mm(_box_at((2.0, 4.0, 6.0), 10.0, 20.0, 30.0))

    assert tuple(round(value, 9) for value in centre) == (7.0, 14.0, 21.0)


def test_centre_of_mass_is_not_the_centre_of_the_bounding_box() -> None:
    """The distinction a caller reaches for this to draw: a lopsided solid
    holds its material away from the middle of the box that bounds it."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    from stompgeom.shapes import centre_of_mass_mm
    from stompgeom.step import bounding_box_mm

    heavy = _box_at((0.0, 0.0, 0.0), 10.0, 10.0, 10.0)
    thin = _box_at((0.0, 0.0, 10.0), 1.0, 1.0, 30.0)
    lopsided = BRepAlgoAPI_Fuse(heavy, thin).Shape()
    box = bounding_box_mm(lopsided)

    assert centre_of_mass_mm(lopsided)[2] < (box[2] + box[5]) / 2.0


def test_the_fuzzy_predicate_agrees_with_the_exact_one_about_contact() -> None:
    """The control the fuzzy value needs, and the claim it must not break.

    A shaft exactly filling its bore is contact, and ``common`` -- the exact
    intersection every measured quantity in this workspace is read from --
    says so by returning nothing. :func:`interferes` runs a tolerant boolean
    and must reach the same verdict, or the tolerance would have turned an
    interference fit into a fault. Measured on the tar assembly at every
    depth of a 12.000 mm bush through a 12.000 mm hole; stated here on the
    same geometry the two rules above use.
    """
    from stompgeom.shapes import common, interferes

    plate, shaft = _bored_plate(6.0), _cylinder((20.0, 20.0, -5.0), 6.0, 13.0)

    assert common(plate, shaft) is None
    assert not interferes(plate, shaft)
