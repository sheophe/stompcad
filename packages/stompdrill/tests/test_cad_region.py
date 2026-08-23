"""The play area: relief versus structure, erosion, and containment."""

from __future__ import annotations

import pytest

from stompdrill.cad.case import build_frame, drill_axis, find_faces, select_solid
from stompdrill.cad.region import build_region, classify_bounds, contains, region_bbox_nm
from stompgeom.step import read_step
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre

pytestmark = pytest.mark.hammond

FOOTPRINT = (Nanometre(119_500_000), Nanometre(94_000_000))
MM = 1_000_000


def nm(value_mm: float) -> Nanometre:
    """A canonical-millimetre probe point as whole nanometres."""
    return Nanometre(round(value_mm * MM))


@pytest.fixture(scope="module")
def box(hammond_bb):
    document = read_step(hammond_bb)
    axis = drill_axis(document, FOOTPRINT)
    faces = find_faces(select_solid(document, CaseFace.BOX), axis)
    return axis, faces, build_frame(faces, axis)


def test_the_cast_lettering_is_always_relief(box):
    """13 letters stand 0.50 mm proud, far under the fixed 2.0 mm structure
    height (``region._STRUCTURE_HEIGHT_MM``) -- lettering is relief because
    it is lettering, not because of where a threshold sits (fix round 2:
    pedal builders drill straight through it, and margin is bit clearance
    now, unrelated to this decision).
    """
    axis, faces, _ = box

    structure, relief = classify_bounds(faces.inner, axis, faces.outward[axis])

    assert len(relief) == 13
    assert structure == []


def test_a_hole_over_the_cast_lettering_stays_open_at_every_margin(box):
    """The margin sweep that used to flip lettering to structure is gone --
    ``classify_bounds`` no longer takes a margin at all, so a hole over a
    letter stays open (``"relief"``) whatever bit clearance is asked for.
    """
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])
    x, y = BB_PROBES["relief"]

    for margin_mm in (0.1, 0.4, 0.6, 1.0):
        assert contains(region, frame, axis, nm(x), nm(y), Nanometre(1 * MM), nm(margin_mm))


def test_a_hole_in_clear_space_is_inside_the_region(box):
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])
    x, y = BB_PROBES["clear"]

    assert contains(region, frame, axis, nm(x), nm(y), Nanometre(3 * MM), Nanometre(1 * MM))


def test_a_hole_in_a_notched_corner_is_outside_the_region(box):
    """The bosses notch the flat face, so no computation has to exclude them."""
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])
    x, y = BB_PROBES["boss"]

    assert not contains(region, frame, axis, nm(x), nm(y), Nanometre(2 * MM), Nanometre(1 * MM))


def test_a_hole_off_the_floor_is_outside_the_region(box):
    """The fourth ``BB_PROBES`` entry, exercised where the other three are."""
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])
    x, y = BB_PROBES["off_face"]

    assert not contains(region, frame, axis, nm(x), nm(y), Nanometre(1 * MM), Nanometre(1 * MM))


def test_the_margin_and_not_only_the_radius_decides_the_edge(box):
    """A bit that fits geometrically must still be refused inside the margin.

    The floor's outline reaches x = 55.33; a 1 mm bit at x = 53.8 clears it by
    0.53 mm, so a 0.1 mm margin admits it and a 3 mm margin must not.
    """
    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])
    x = nm(53.8)

    generous = contains(region, frame, axis, x, Nanometre(0), Nanometre(1 * MM), nm(0.1))
    tight = contains(region, frame, axis, x, Nanometre(0), Nanometre(1 * MM), Nanometre(3 * MM))

    assert generous
    assert not tight


def test_region_bbox_nm_reports_the_real_floor_on_the_1590bb(box):
    """A sanity check against the measured 1590BB floor, not just a synthetic shape."""
    axis, faces, frame = box
    region = build_region(faces.inner, axis, faces.outward[axis])

    x0, y0, x1, y1 = region_bbox_nm(region, frame, axis)

    assert (x1 - x0) / MM == pytest.approx(110.66, abs=0.01)
    assert (y1 - y0) / MM == pytest.approx(85.16, abs=0.01)


def test_region_bbox_nm_transforms_through_the_frame_not_kernel_axes():
    """A floor off the kernel origin must still report canonical extents.

    Every cached Hammond floor happens to be centred on the kernel origin
    with ``u``/``v`` axis-aligned, which would let a bug that read the
    kernel bounding box straight through -- ignoring ``frame`` entirely --
    pass unnoticed. This builds a synthetic, off-centre face directly, with
    no downloaded model involved, to catch exactly that bug.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    axis = 1
    polygon = BRepBuilderAPI_MakePolygon()
    for x, z in ((90.0, 40.0), (110.0, 40.0), (110.0, 60.0), (90.0, 60.0)):
        polygon.Add(gp_Pnt(x, 0.0, z))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()

    # Origin sits at kernel x = 50, so a bug reading kernel bounds straight
    # through would report (90, 40, 110, 60) instead of the shifted extent.
    frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(nm(50.0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0), w=(0.0, 1.0, 0.0),
        )
    )

    assert region_bbox_nm(face, frame, axis) == (nm(40.0), nm(40.0), nm(60.0), nm(60.0))


def test_classify_bounds_ignores_a_companion_too_far_from_the_hole():
    """A companion whose footprint sits nowhere near a hole must not pair with it.

    Synthetic, no downloaded model: a floor with one hole, and a companion
    face positioned far from that hole's own footprint. ``_COMPANION_MATCH_MM``
    exists to keep this from pairing -- setting it to ``inf`` would let any
    companion pair with any hole regardless of distance, and no cached
    model's gaps (all measured under ~1e-7 mm) can exercise that guard.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS, TopoDS_Compound

    axis = 1

    def rectangle(y, corners):
        polygon = BRepBuilderAPI_MakePolygon()
        for x, z in corners:
            polygon.Add(gp_Pnt(x, y, z))
        polygon.Close()
        return polygon.Wire()

    outer = rectangle(0.0, [(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)])
    hole = rectangle(0.0, [(-20.0, -20.0), (-10.0, -20.0), (-10.0, -10.0), (-20.0, -10.0)])
    builder = BRepBuilderAPI_MakeFace(outer)
    builder.Add(TopoDS.Wire_s(hole.Reversed()))
    floor = builder.Face()

    # Proud (y = 0.4), but 60 mm from the hole's own footprint -- far beyond
    # any plausible companion match.
    companion_wire = rectangle(0.4, [(30.0, 30.0), (40.0, 30.0), (40.0, 40.0), (30.0, 40.0)])
    companion = BRepBuilderAPI_MakeFace(companion_wire).Face()

    compound = TopoDS_Compound()
    compound_builder = BRep_Builder()
    compound_builder.MakeCompound(compound)
    compound_builder.Add(compound, floor)
    compound_builder.Add(compound, companion)

    structure, relief = classify_bounds(compound, axis, 1.0)

    assert len(structure) == 1
    assert relief == []


def test_classify_bounds_accepts_a_bare_face_not_only_a_compound():
    """``_floor_face``/``_companions`` explicitly support a bare face too.

    ``find_faces`` always hands ``region.py`` a compound in practice, so
    this path is otherwise reachable only in principle; a plain, holeless
    face proves the documented flexibility is real rather than unexercised.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    axis = 1
    polygon = BRepBuilderAPI_MakePolygon()
    for x, z in ((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)):
        polygon.Add(gp_Pnt(x, 0.0, z))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()

    structure, relief = classify_bounds(face, axis, 1.0)

    assert structure == []
    assert relief == []


def test_floor_face_rejects_a_compound_with_no_planar_face():
    """An empty compound must raise, not silently return nothing at all."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from stompdrill.cad.region import _floor_face
    from stompdrill.errors import StompdrillError

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)

    with pytest.raises(StompdrillError, match="no planar face"):
        _floor_face(compound)


@pytest.fixture(scope="module")
def bb_box(hammond_bb):
    from stompdrill.cad import load_case_model

    return load_case_model(hammond_bb, face=CaseFace.BOX, margin_nm=Nanometre(1 * MM))


@pytest.fixture(scope="module")
def bb_lid(hammond_bb):
    from stompdrill.cad import load_case_model

    return load_case_model(hammond_bb, face=CaseFace.LID, margin_nm=Nanometre(1 * MM))


def test_the_loaded_model_satisfies_the_protocol(bb_box):
    from stompdrill.cad import CaseModel

    assert isinstance(bb_box, CaseModel)


def test_the_loaded_box_reports_its_plate_and_footprint(bb_box):
    assert bb_box.plate_nm == 2_250_000
    assert sorted(bb_box.footprint_nm) == [94_000_000, 119_500_000]


def test_the_loaded_lid_reports_its_own_thinner_plate(bb_lid):
    """Box and lid are different plates; a shared constant would hide it."""
    assert bb_lid.plate_nm == 2_000_000


def test_the_loaded_box_classifies_a_corner_as_through_boss(bb_box):
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["boss"]

    assert bb_box.classify(nm(x), nm(y), Nanometre(2 * MM)) is Rejection.THROUGH_BOSS


def test_the_loaded_box_classifies_an_overhanging_hole_as_off_face(bb_box):
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["off_face"]

    assert bb_box.classify(nm(x), nm(y), Nanometre(2 * MM)) is Rejection.OFF_FACE


def test_the_two_rejections_are_told_apart_by_where_the_hole_is(bb_box):
    """Both refuse the hole; a rule collapsing them would still pass each alone."""
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    boss = bb_box.classify(*(nm(v) for v in BB_PROBES["boss"]), Nanometre(2 * MM))
    edge = bb_box.classify(*(nm(v) for v in BB_PROBES["off_face"]), Nanometre(2 * MM))

    assert boss is Rejection.THROUGH_BOSS
    assert edge is Rejection.OFF_FACE
    assert boss is not edge


def test_the_loaded_box_accepts_a_hole_in_clear_space(bb_box):
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["clear"]

    assert bb_box.classify(nm(x), nm(y), Nanometre(3 * MM)) is None


def test_the_loaded_box_accepts_a_hole_over_the_cast_lettering(bb_box):
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["relief"]

    assert bb_box.classify(nm(x), nm(y), Nanometre(1 * MM)) is None


def test_the_lid_corner_relief_is_refused_by_its_own_face_not_the_box(bb_lid):
    """The lid has its own corner relief for the box's screw posts too.

    Measured (see ``tests.hammond.BB_PROBES``'s module comment): the lid's
    own corner arc (r=5.94 about canonical (55.00, 42.25)) sits only ~0.35 mm
    from the box's own mirrored one (r=5.17) and is 0.77 mm wider -- wide
    enough to contain it entirely, at any margin. ``"boss"`` is always
    refused by the lid's own boundary before the box is ever consulted.
    """
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["boss"]

    assert bb_lid.classify(nm(x), nm(y), Nanometre(2 * MM)) is Rejection.THROUGH_BOSS


def test_the_lid_accepts_a_hole_in_clear_space(bb_lid):
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["clear"]

    assert bb_lid.classify(nm(x), nm(y), Nanometre(3 * MM)) is None


def test_the_lid_rejects_a_hole_off_its_own_face(bb_lid):
    """The lid's own boundary, not the box's, decides ``OFF_FACE`` for it."""
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["off_face"]

    assert bb_lid.classify(nm(x), nm(y), Nanometre(2 * MM)) is Rejection.OFF_FACE


def test_the_lid_accepts_a_hole_over_its_own_clear_metal(bb_lid):
    """``"relief"`` is a box coordinate, but read as the lid's own it lands
    on plain, feature-free lid metal -- nowhere near a lid corner relief."""
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["relief"]

    assert bb_lid.classify(nm(x), nm(y), Nanometre(1 * MM)) is None


def test_obstructed_is_unreachable_on_the_cached_1590bb(bb_lid):
    """Fix round 2: lettering is never structure, so it can never obstruct;
    the corner notches are always caught by the lid's own face first (see
    ``test_the_lid_corner_relief_is_refused_by_its_own_face_not_the_box``
    above). Every probe this module has clears the box, or is refused by
    the lid's own face before the box is ever consulted -- ``OBSTRUCTED``
    genuinely does not occur on this model. It is demonstrated synthetically
    in ``tests/test_cad_region_synthetic.py`` instead.
    """
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    for name in ("clear", "boss", "off_face", "relief"):
        x, y = BB_PROBES[name]
        assert bb_lid.classify(nm(x), nm(y), Nanometre(2 * MM)) is not Rejection.OBSTRUCTED


def test_the_rejection_code_does_not_change_with_drill_size(bb_box):
    """``OFF_FACE`` vs ``THROUGH_BOSS`` names a place, not a drill size.

    A bbox-inset check flips code with radius at the same point (the bug
    this guards against); naming the boundary element responsible cannot.
    """
    from stompdrill.cad import Rejection
    from tests.hammond import BB_PROBES

    radii_mm = (0.1, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0)

    edge_x, edge_y = BB_PROBES["off_face"]
    edge_codes = {bb_box.classify(nm(edge_x), nm(edge_y), nm(r)) for r in radii_mm}
    assert edge_codes == {Rejection.OFF_FACE}

    boss_x, boss_y = BB_PROBES["boss"]
    boss_codes = {bb_box.classify(nm(boss_x), nm(boss_y), nm(r)) for r in radii_mm}
    assert boss_codes == {Rejection.THROUGH_BOSS}
