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

import pytest

pytest.importorskip("OCP", reason="needs stompdrill[step]")

from stompdrill.cad import Rejection  # noqa: E402
from stompdrill.cad.base import Frame  # noqa: E402
from stompdrill.cad.loader import OcpCaseModel  # noqa: E402
from stompdrill.cad.region import build_region, classify_bounds, contains  # noqa: E402
from stompmodel.units import Nanometre  # noqa: E402

AXIS = 1
MM = 1_000_000
#: The floor faces built below face -y (towards more negative y), matching
#: ``Faces.outward``'s convention: a companion nearer that direction than
#: the floor is proud, one further away recedes.
OUTWARD = -1.0


def nm(value_mm: float) -> Nanometre:
    return Nanometre(round(value_mm * MM))


def _rectangle(y: float, corners):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    polygon = BRepBuilderAPI_MakePolygon()
    for x, z in corners:
        polygon.Add(gp_Pnt(x, y, z))
    polygon.Close()
    return polygon.Wire()


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

    frame = Frame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
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
    own_frame = Frame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
    )
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    own_wire = _rectangle(0.0, [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)])
    own_floor = BRepBuilderAPI_MakeFace(own_wire).Face()
    own_region = build_region(own_floor, AXIS, OUTWARD)

    box_face = _floor_with_companion(3.0)
    box_region = build_region(box_face, AXIS, OUTWARD)

    model = OcpCaseModel(
        part="synthetic", face="lid",
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
    reframe (``region.reframe``) still runs before the box's own region is
    consulted, rather than checking the lid's raw coordinate against it.
    """
    own_frame = Frame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, -1.0, 0.0),
    )
    # Mirrored in x, like a real lid viewed from the opposite side to its box.
    box_frame = Frame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(-1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, 1.0, 0.0),
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
        part="synthetic", face="lid",
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
