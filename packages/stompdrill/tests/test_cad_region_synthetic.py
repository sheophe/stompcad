"""Synthetic region.py tests that need OCP but no downloaded Hammond model.

Unmarked deliberately, like ``tests/test_cad_case_synthetic.py``:
``tests/test_cad_region.py`` carries a module-level ``pytestmark =
pytest.mark.hammond`` that would skip these by default, but nothing here
needs a cached model, so they belong in the default suite. They guard
``_STRUCTURE_HEIGHT_MM`` and the sign ``_proud_mm`` now carries: no cached
Hammond model's own structure exercises either (see ``region.py``'s module
comment and fix-round-2 report), so only synthetic geometry can.
"""

from __future__ import annotations

from stompdrill.cad import Rejection
from stompdrill.cad.loader import OcpCaseModel
from stompdrill.cad.region import build_region, classify_bounds, contains
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre

AXIS = 1
MM = 1_000_000
#: The floor faces built below face -y (towards more negative y), matching
#: ``Faces.outward``'s convention: a companion set the other way from the
#: floor -- away from the drilled face, into the cavity -- stands proud, one
#: displaced towards that direction recedes.
OUTWARD = -1.0


def nm(value_mm: float) -> Nanometre:
    return Nanometre(round(value_mm * MM))


def _polyline(points, close: bool = True):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    polygon = BRepBuilderAPI_MakePolygon()
    for point in points:
        polygon.Add(gp_Pnt(*point))
    if close:
        polygon.Close()
    return polygon.Wire()


def _rectangle(y: float, corners):
    return _polyline([(x, y, z) for x, z in corners])


def _floor_with_companion(companion_y: float):
    """A 100 x 100 mm floor with a 10 x 10 mm hole, and a companion over it.

    The hole wire is added un-reversed: ``build_region`` reverses whatever
    wire it finds on the floor exactly once, the same as a wire read back
    from a genuine STEP face's own topology needs.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopoDS import TopoDS

    outer = _rectangle(0.0, [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)])
    hole = _rectangle(0.0, [(5.0, 0.0), (15.0, 0.0), (15.0, 10.0), (5.0, 10.0)])
    builder = BRepBuilderAPI_MakeFace(outer)
    builder.Add(TopoDS.Wire_s(hole))
    floor = builder.Face()

    companion_wire = _rectangle(companion_y, [(5.0, 0.0), (15.0, 0.0), (15.0, 10.0), (5.0, 10.0)])
    companion = BRepBuilderAPI_MakeFace(companion_wire).Face()
    return _compound(floor, companion)


def _compound(*faces):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    return compound


def test_a_companion_above_the_structure_height_is_structure():
    """2.5 mm proud clears ``_STRUCTURE_HEIGHT_MM`` (2.0 mm); relief cannot."""
    face = _floor_with_companion(2.5)

    structure, relief = classify_bounds(face, AXIS, OUTWARD)

    assert len(structure) == 1
    assert relief == []


def test_a_recessed_companion_is_never_structure_at_any_margin():
    """A companion 10 mm the *other* side of the floor removes material --
    it can never be structure, however far it recedes, and a hole there
    stays open regardless of the clearance margin used against it.
    """
    face = _floor_with_companion(-10.0)

    structure, relief = classify_bounds(face, AXIS, OUTWARD)
    assert structure == []
    assert len(relief) == 1

    frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
        )
    )
    region = build_region(face, AXIS, OUTWARD)
    for margin_mm in (0.1, 1.0, 5.0):
        assert contains(region, frame, AXIS, nm(10.0), nm(5.0), nm(1.0), nm(margin_mm))


def test_obstructed_is_reachable_with_a_genuine_raised_boss():
    """Two solids: a plain floor accepts a hole its own face has no problem
    with, but the companion solid behind it -- a floor with a >2.0 mm
    raised boss right there -- refuses it once assembled. This is the
    ``OBSTRUCTED`` path with a real boss, not lettering (which, since
    fix-round-2, never blocks a hole): model-free, because it is otherwise
    unreachable on any cached Hammond model (see the fix-round-2 report).
    """
    own_frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
        )
    )
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    own_wire = _rectangle(0.0, [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)])
    own_floor = BRepBuilderAPI_MakeFace(own_wire).Face()
    own_region = build_region(own_floor, AXIS, OUTWARD)

    box_face = _floor_with_companion(3.0)
    box_region = build_region(box_face, AXIS, OUTWARD)

    model = OcpCaseModel(
        part="synthetic", face=CaseFace.LID, model_name="synthetic.stp",
        footprint_nm=(nm(100.0), nm(100.0)), plate_nm=nm(2.0),
        play_area_nm=(nm(-50.0), nm(-50.0), nm(50.0), nm(50.0)),
        frame=own_frame, margin_nm=Nanometre(0), axis=AXIS,
        own_region=own_region, own_frame=own_frame,
        box_region=box_region, box_frame=own_frame,
        drilled_position_mm=0.0, inner_position_mm=0.0,
        document=None, target_shape=None, document_timestamp="",
    )

    assert model.classify(nm(10.0), nm(5.0), nm(1.0)) is Rejection.OBSTRUCTED
    assert model.classify(nm(-30.0), nm(-30.0), nm(1.0)) is None


def test_the_box_check_still_reframes_through_mirrored_frames():
    """Fix-round-1 regression, now synthetic: cast lettering used to prove
    the box-check transforms a lid-canonical point into the box's own
    orientation before testing it, by flipping structure at a low margin.
    Lettering can never do that again (fix round 2), so a mirrored frame
    pair with an off-centre boss -- not lettering -- is what proves the
    reframe (``CoordinateFrame.reframe``) still runs before the box's own
    region is consulted, rather than checking the lid's raw coordinate
    against it.
    """
    own_frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
        )
    )
    # Mirrored in x, like a real lid viewed from the opposite side to its box.
    box_frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(-1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, 1.0, 0.0),
        )
    )
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    own_wire = _rectangle(0.0, [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)])
    own_floor = BRepBuilderAPI_MakeFace(own_wire).Face()
    own_region = build_region(own_floor, AXIS, OUTWARD)

    # The box's own solid boss sits at kernel x in [5, 15] -- one side only,
    # unrelated to either frame; frames only relabel it, they cannot move it.
    box_face = _floor_with_companion(3.0)
    box_region = build_region(box_face, AXIS, OUTWARD)

    model = OcpCaseModel(
        part="synthetic", face=CaseFace.LID, model_name="synthetic.stp",
        footprint_nm=(nm(100.0), nm(100.0)), plate_nm=nm(2.0),
        play_area_nm=(nm(-50.0), nm(-50.0), nm(50.0), nm(50.0)),
        frame=own_frame, margin_nm=Nanometre(0), axis=AXIS,
        own_region=own_region, own_frame=own_frame,
        box_region=box_region, box_frame=box_frame,
        drilled_position_mm=0.0, inner_position_mm=0.0,
        document=None, target_shape=None, document_timestamp="",
    )

    # own_frame is the identity, so own-canonical x is kernel x directly: +10
    # sits in the boss's [5, 15], -10 does not. A reframe that used box_frame's
    # mirrored u on the raw own coordinate, instead of converting through
    # model space first, would get these two the wrong way round.
    over_boss = model.classify(nm(10.0), nm(5.0), nm(1.0))
    clear_metal = model.classify(nm(-10.0), nm(5.0), nm(1.0))

    assert over_boss is Rejection.OBSTRUCTED
    assert clear_metal is None


def _hostile_wires(region):
    """Wires that cannot sensibly bound a hole in the 100 x 100 mm floor.

    Each breaks a different precondition ``BRepBuilderAPI_MakeFace.Add``
    might plausibly have checked: closure, planarity, coplanarity with the
    face's own surface, non-self-intersection, containment within the outer
    boundary, and non-degeneracy. A null wire is excluded deliberately -- it
    segfaults the kernel outright rather than reporting anything, and
    ``classify_bounds`` only ever yields wires read off a real face.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis

    return {
        "open, unclosed polyline": _polyline(
            [(-20.0, 0.0, -20.0), (-10.0, 0.0, -20.0), (-10.0, 0.0, -10.0)], close=False),
        "self-intersecting figure-eight": _rectangle(
            0.0, [(-40.0, -40.0), (-20.0, -20.0), (-40.0, -20.0), (-20.0, -40.0)]),
        "closed, but on a parallel plane 25 mm off the face": _rectangle(
            25.0, [(-40.0, 20.0), (-30.0, 20.0), (-30.0, 30.0), (-40.0, 30.0)]),
        "on a plane perpendicular to the face": _polyline(
            [(-40.0, 0.0, -40.0), (-30.0, 0.0, -40.0),
             (-30.0, 10.0, -40.0), (-40.0, 10.0, -40.0)]),
        "non-planar skew quadrilateral": _polyline(
            [(-40.0, 0.0, 30.0), (-30.0, 0.0, 30.0),
             (-30.0, 5.0, 40.0), (-40.0, -5.0, 40.0)]),
        "wholly outside the outer boundary": _rectangle(
            0.0, [(200.0, 200.0), (210.0, 200.0), (210.0, 210.0), (200.0, 210.0)]),
        "enclosing the whole outer boundary": _rectangle(
            0.0, [(-200.0, -200.0), (200.0, -200.0), (200.0, 200.0), (-200.0, 200.0)]),
        "straddling the outer boundary": _rectangle(
            0.0, [(40.0, -5.0), (60.0, -5.0), (60.0, 5.0), (40.0, 5.0)]),
        "degenerate two-point wire enclosing no area": _polyline(
            [(-45.0, 0.0, -45.0), (-35.0, 0.0, -45.0)]),
        "the region's own outer wire, added a second time": ShapeAnalysis.OuterWire_s(region),
    }


def test_add_reports_done_for_every_hostile_wire():
    """``build_region`` cannot detect a structure wire the kernel refused.

    Its subtraction loop carries no guard because there is nothing to guard
    on: ``Add`` sets ``FaceDone`` unconditionally. Reversing that decision --
    restoring ``if adder.IsDone():`` as a live check -- needs this to fail
    for at least one wire below. The builder's state *before* ``Add`` is
    asserted too, so the test cannot pass by finding a flag that is simply
    always true: it is false until ``Add`` forces it.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopoDS import TopoDS

    region = build_region(_floor_with_companion(3.0), AXIS, OUTWARD)
    hostile = _hostile_wires(region)
    assert len(hostile) >= 9, "too few hostile wires to call this evidence"

    before, after = {}, {}
    for name, wire in hostile.items():
        adder = BRepBuilderAPI_MakeFace(region)
        before[name] = adder.IsDone()
        adder.Add(TopoDS.Wire_s(wire.Reversed()))
        after[name] = adder.IsDone()

    assert before == dict.fromkeys(hostile, False)
    assert after == dict.fromkeys(hostile, True)
