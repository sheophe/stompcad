"""Finding the boards in an assembly, and proving each one is a board.

Ruling 1's verification has three criteria, so every one of them carries a
solid that fails *that* criterion and satisfies the other two -- a solid
failing all three would leave any of them free to be wrong. The synthetic
solids are built through OCP directly because that is what a fixture is;
the package's own source reaches the kernel only through ``stompgeom``,
which ``test_package_boundary.py`` is what enforces.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stompcollider.boards import (
    _area_ratio,
    _contact,
    _extent_mm,
    _opposed,
    _thickness_nm,
    _two_largest,
    carrier_frame,
    group,
    is_slab,
    substrates,
)
from stompcollider.errors import NoSubstrateError
from stompgeom.build import PlacedSolid, build_document
from stompgeom.levels import Level, levels
from stompgeom.step import (
    StepDocument,
    StepSolid,
    bounding_box_mm,
    read_step,
    read_step_document,
)
from stompmodel.frames import CoordinateFrame
from stompmodel.units import Nanometre, nm_from_mm

_FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"

#: The two footswitches, which sit on the fixture's smaller substrate. The
#: other 39 designators sit on the larger, so a grouping test can state the
#: partition rather than only its size.
_SWITCHES = {"SW1", "SW2"}


# --------------------------------------------------------------------------
# Synthetic solids. Each is built to isolate one criterion.
# --------------------------------------------------------------------------


def _block(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> Any:
    """A rectangular block, as a bare shape."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _box(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> StepSolid:
    """The same block as an unnamed solid, with unequal edges throughout.

    ``30 x 20 x 1`` has one 600 mm2 pair and no other level near it, unlike a
    cube, every pair of whose faces satisfies "opposed and equal in area".
    """
    return StepSolid(name="", shape=_block(dx, dy, dz, at))


def _leaning_plate() -> StepSolid:
    """A thin wedge: its two largest faces meet at an angle instead of opposing.

    A uniformly rotated slab would not do -- rotating both faces together
    keeps them exactly opposed. Only one face moves here.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeWedge

    return StepSolid(name="", shape=BRepPrimAPI_MakeWedge(100.0, 1.0, 100.0, 0.0).Shape())


def _tapered_plate() -> StepSolid:
    """A thin plate whose top face is 60 x 60 over a 100 x 100 base.

    Opposed and thin, but the two faces are nothing like the same size --
    the shape of a flange, a screw head or a countersink, which is what the
    area criterion exists to refuse.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeWedge

    return StepSolid(
        name="", shape=BRepPrimAPI_MakeWedge(100.0, 1.0, 100.0, 20.0, 20.0, 80.0, 80.0).Shape()
    )


def _gently_tapered_plate() -> StepSolid:
    """A thin plate whose top face is 85 x 85 over a 100 x 100 base.

    The draft a real casting carries: 0.7225, the same order as 1590LB's
    lid at 0.707, the least equal genuine plate the calibration measured.
    A floor raised past it would refuse a plate that is one.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeWedge

    return StepSolid(
        name="", shape=BRepPrimAPI_MakeWedge(100.0, 1.0, 100.0, 7.5, 7.5, 92.5, 92.5).Shape()
    )


def _leaning_slab() -> StepSolid:
    """A 30 x 20 x 1 plate turned 0.3 rad about x, so its normal is off axis.

    Every other solid here is axis aligned, which would leave the basis
    construction free to be wrong everywhere but on an axis.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    shape = BRepPrimAPI_MakeBox(30.0, 20.0, 1.0).Shape()
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), 0.3)
    return StepSolid(name="", shape=shape.Moved(TopLoc_Location(turn)))


def _document_of(*solids: tuple[str, Any]) -> StepDocument:
    """A real XCAF document holding ``(name, shape)`` pairs, read back.

    Built and read through ``stompgeom`` rather than assembled by hand, so
    an unnamed solid here is unnamed the way the reader decides it is.
    """
    return read_step_document(
        build_document(
            [PlacedSolid(shape=shape, name=name, colour=None, placement=None)
             for name, shape in solids]
        )
    )


def _stacked_boards() -> StepDocument:
    """Two plates sharing a footprint at different heights, one part on each.

    The fixture's own boards are coplanar and disjoint in y, so it never
    exercises "the nearest along that normal". This does, and it is
    deliberately lopsided: the low plate is 200 mm long, so ``LOW`` sits
    90 mm from its centre and only 29 mm from the small high plate's.
    A rule reading centre distance instead of the gap places it wrongly.
    """
    return _document_of(
        ("", _block(200.0, 40.0, 1.5, (0.0, 0.0, 0.0))),
        ("", _block(30.0, 30.0, 1.5, (0.0, 0.0, 30.0))),
        ("LOW", _block(4.0, 4.0, 3.0, (8.0, 8.0, 1.5))),
        ("HIGH", _block(4.0, 4.0, 3.0, (8.0, 8.0, 31.5))),
    )


def _boards_side_by_side() -> StepDocument:
    """Two coplanar plates and one part over the far edge of the wider.

    ``EDGE``'s footprint reaches only the wide plate, but its centre is
    18 mm from the narrow plate's and 27 mm from the wide one's, and both
    plates lie in one plane so the gap along the normal ties. Only "whose
    footprint it overlaps" can place it.
    """
    return _document_of(
        ("", _block(60.0, 40.0, 1.5, (0.0, 0.0, 0.0))),
        ("", _block(20.0, 20.0, 1.5, (65.0, 10.0, 0.0))),
        ("EDGE", _block(4.0, 4.0, 3.0, (55.0, 18.0, 1.5))),
    )


def _boards_apart() -> StepDocument:
    """Two plates far apart, and a part whose footprint reaches neither.

    The fallback's own fixture: ``STRAY`` is 28 mm from the far plate's
    centre and 252 mm from the near one's, so "not dropped" is a real
    choice between two boards rather than the only board there is.
    """
    return _document_of(
        ("", _block(60.0, 40.0, 1.5, (0.0, 0.0, 0.0))),
        ("", _block(20.0, 20.0, 1.5, (300.0, 0.0, 0.0))),
        ("STRAY", _block(4.0, 4.0, 4.0, (280.0, 5.0, 0.0))),
    )


def _mirrored_boards() -> StepDocument:
    """Two identical plates mirrored about x = 0, and a part exactly between.

    The one arrangement that makes ``_contact`` tie outright: ``MID``
    overlaps neither footprint, touches neither along the normal, and its
    centre is the same distance from both. Nothing about the part can
    separate the plates, so only the tie-break can.
    """
    return _document_of(
        ("", _block(40.0, 40.0, 1.5, (-50.0, 0.0, 0.0))),
        ("", _block(40.0, 40.0, 1.5, (10.0, 0.0, 0.0))),
        ("MID", _block(4.0, 4.0, 3.0, (-2.0, 18.0, 0.0))),
    )


def _named(document: StepDocument, designator: str) -> StepSolid:
    return next(solid for solid in document.solids if solid.name == designator)


def _frame(solid: StepSolid) -> CoordinateFrame:
    """``solid``'s carrier frame, for a solid a test already knows is one."""
    frame = carrier_frame(solid)
    assert frame is not None
    return frame


def _pair(solid: StepSolid) -> tuple[Level, Level]:
    """``solid``'s two largest levels, for a test that names each criterion.

    Every solid in this module has at least two planar faces, so the
    ``None`` a solid with fewer would yield is an assertion, not a branch.
    """
    found = _two_largest(levels(solid))
    assert found is not None
    return found


def _partition(grouped) -> set[frozenset[str]]:
    """The designators each group holds, as a partition.

    Deliberately identity-free, for the tests that ask only whether the
    parts were split correctly. A test asking *which* board a part landed
    on must use :func:`_holder`: two boards holding one part each give the
    same partition however the two are swapped.
    """
    return {frozenset(part.name for part in components) for _substrate, components in grouped}


def _holder(grouped, designator: str) -> tuple[float, ...]:
    """The bounding box of the substrate ``designator`` was grouped onto.

    The box, not the position in the returned tuple: a test naming a board
    by its index would agree with itself whatever the grouping did.
    """
    return next(
        bounding_box_mm(substrate.shape)
        for substrate, components in grouped
        if any(part.name == designator for part in components)
    )


@pytest.fixture(scope="module")
def document() -> StepDocument:
    return read_step(_FIXTURE)


# --------------------------------------------------------------------------
# The slab test, criterion by criterion, on solids built to isolate one each.
# --------------------------------------------------------------------------


def test_a_thin_plate_placed_away_from_the_origin_is_a_slab() -> None:
    """The INNOCENT probe, and hazard 2's fixture: the plate spans z 5..6, so
    neither face sits on the origin and no face is symmetric about it."""
    assert is_slab(_box(30.0, 20.0, 1.0, (0.0, 0.0, 5.0))) is True


def test_the_thickness_is_the_offsets_sum_and_not_their_difference() -> None:
    """Offsets are signed along each level's own outward direction, so they
    sum. On a plate at z 5..6 the two readings genuinely disagree -- 1 mm
    against 11 mm -- which a plate with a face at z = 0 could never show."""
    lower, upper = _pair(_box(30.0, 20.0, 1.0, (0.0, 0.0, 5.0)))

    assert (lower.offset_nm, upper.offset_nm) == (Nanometre(-5_000_000), Nanometre(6_000_000))
    assert _thickness_nm(lower, upper) == Nanometre(1_000_000)
    assert abs(lower.offset_nm - upper.offset_nm) == 11_000_000


def test_a_block_of_the_same_footprint_is_too_thick_to_be_a_slab() -> None:
    """Fails thinness ALONE. The control below shows the other two criteria
    are satisfied, so the refusal can only be the thickness one."""
    block = _box(30.0, 20.0, 10.0, (0.0, 0.0, 5.0))
    lower, upper = _pair(block)

    assert _opposed(lower, upper) is True
    assert _area_ratio(lower, upper) == 1.0
    assert is_slab(block) is False


def test_a_wedge_whose_largest_faces_lean_together_is_not_a_slab() -> None:
    """Fails opposition ALONE: comparable in area to five decimals, and
    thinner against its own extent than the fixture's own boards are."""
    wedge = _leaning_plate()
    first, second = _pair(wedge)

    assert _area_ratio(first, second) > 0.99
    assert _thickness_nm(first, second) / nm_from_mm(_extent_mm(first, second)) < 0.05
    assert _opposed(first, second) is False
    assert is_slab(wedge) is False


def test_a_tapered_plate_of_unequal_faces_is_not_a_slab() -> None:
    """Fails comparable area ALONE: opposed, and thin on the same measure."""
    tapered = _tapered_plate()
    base, top = _pair(tapered)

    assert _opposed(base, top) is True
    assert _thickness_nm(base, top) / nm_from_mm(_extent_mm(base, top)) < 0.05
    assert _area_ratio(base, top) < 0.5
    assert is_slab(tapered) is False


def test_the_carrier_frame_registers_the_far_face_of_the_plate() -> None:
    """Built from the two carrier levels and nothing else: ``w`` is the level's
    own published direction, and the origin sits on that level's plane -- 6 mm,
    the far face of a plate spanning z 5..6, not its 5 mm near face."""
    frame = carrier_frame(_box(30.0, 20.0, 1.0, (0.0, 0.0, 5.0)))

    assert frame is not None
    assert frame.w == (0.0, 0.0, 1.0)
    assert frame.origin_nm == (Nanometre(0), Nanometre(0), Nanometre(6_000_000))


def test_a_gently_tapered_plate_is_still_a_slab() -> None:
    """The area floor's other side. Without this the floor could be raised
    to 0.99 and every refusal above would stay green -- a real casting's
    draft, and the 1590LB lid the calibration measured, both sit below it."""
    tapered = _gently_tapered_plate()
    base, top = _pair(tapered)

    assert round(_area_ratio(base, top), 4) == 0.7225
    assert is_slab(tapered) is True


def test_a_slab_turned_off_axis_still_registers_an_orthonormal_frame() -> None:
    """``CoordinateFrame`` validates unit length, orthogonality and
    right-handedness at construction, so a basis built badly for an off-axis
    normal raises rather than passing quietly. Every other solid here is
    axis aligned, where a wrong seed choice happens to work."""
    frame = carrier_frame(_leaning_slab())

    assert frame is not None
    assert round(frame.w[0], 12) == 0.0
    # levels() publishes a direction quantised to millionths and
    # renormalised, so the comparison is loosened by that granularity.
    assert math.isclose(abs(frame.w[1]), math.sin(0.3), abs_tol=1e-5)
    assert math.isclose(abs(frame.w[2]), math.cos(0.3), abs_tol=1e-5)
    # The origin lies on the carrier plane: its projection along w is the
    # level's own signed offset, whichever of the two w turned out to be.
    near, far = _pair(_leaning_slab())
    assert round(sum(o * c for o, c in zip(frame.origin_nm, frame.w))) in {
        int(near.offset_nm), int(far.offset_nm)
    }


def test_a_solid_that_is_no_slab_registers_no_carrier_frame() -> None:
    assert carrier_frame(_box(30.0, 20.0, 10.0, (0.0, 0.0, 5.0))) is None


# --------------------------------------------------------------------------
# Selection and refusal.
# --------------------------------------------------------------------------


def test_a_document_with_no_unnamed_solid_is_refused() -> None:
    """``no-substrate`` stays live under Ruling 1: an exporter that names
    everything gets a refusal rather than a guess."""
    named = _document_of(("U1", _block(30.0, 20.0, 1.0, (0.0, 0.0, 0.0))))

    with pytest.raises(NoSubstrateError, match="every solid in the document is named"):
        substrates(named)


def test_a_document_whose_unnamed_solids_are_no_slab_is_refused_too() -> None:
    """The other half of the same refusal: an unnamed solid that fails the
    verification leaves no substrate, which is not guessed at either."""
    blocks = _document_of(("", _block(30.0, 20.0, 10.0, (0.0, 0.0, 0.0))))

    with pytest.raises(NoSubstrateError, match="measures a slab"):
        substrates(blocks)


def test_an_unnamed_slab_beside_an_unnamed_block_selects_only_the_slab() -> None:
    """Ruling 1's first failure mode -- an exporter that names nothing -- is
    what verification exists to survive. Two unnamed solids, one substrate."""
    mixed = _document_of(
        ("", _block(30.0, 20.0, 10.0, (0.0, 0.0, 0.0))),
        ("", _block(30.0, 20.0, 1.0, (0.0, 0.0, 40.0))),
    )

    found = substrates(mixed)

    assert len(found) == 1
    assert is_slab(found[0]) is True


# --------------------------------------------------------------------------
# Grouping.
# --------------------------------------------------------------------------


def test_a_part_is_grouped_onto_the_nearer_of_two_stacked_boards() -> None:
    """Both parts overlap both plates in projection, so only "the nearest
    along that normal" can separate them -- the rule the coplanar fixture
    never exercises, on an arrangement where centre distance disagrees."""
    stacked = _stacked_boards()
    grouped = group(stacked, substrates(stacked))

    # Named by each plate's own length, so a swap of the two shows up:
    # the low plate is 200 mm long and the high one 30 mm.
    assert _holder(grouped, "LOW")[3] == 200.0
    assert _holder(grouped, "HIGH")[3] == 30.0


def test_a_part_goes_to_the_board_it_overlaps_not_the_board_it_is_near() -> None:
    """Footprint overlap is a preference over distance, not a synonym for it."""
    apart = _boards_side_by_side()
    grouped = group(apart, substrates(apart))

    # The wide plate reaches x = 60, the narrow one x = 85. EDGE overlaps
    # only the wide plate and is nearer the narrow one's centre.
    assert _holder(grouped, "EDGE")[3] == 60.0
    assert _partition(grouped) == {frozenset({"EDGE"}), frozenset()}


def test_a_part_over_no_board_at_all_is_still_grouped() -> None:
    """None dropped: a part whose footprint reaches no substrate falls to the
    nearest one rather than vanishing from the report."""
    stray = _boards_apart()
    grouped = group(stray, substrates(stray))

    assert _partition(grouped) == {frozenset({"STRAY"}), frozenset()}
    # The control: it landed on the far plate by choice, not by there being
    # one plate to land on. That plate starts at x = 300.
    assert _holder(grouped, "STRAY")[0] == 300.0


def test_two_mirrored_boards_really_do_tie() -> None:
    """The control for the test below, and the reason it is not coverage
    theatre: without a genuine tie the tie-break is never reached and any
    rule at all would look correct. Bit-identical, not merely close."""
    mirrored = _mirrored_boards()
    part = bounding_box_mm(_named(mirrored, "MID").shape)

    scores = [
        _contact(_frame(solid), bounding_box_mm(solid.shape), part)
        for solid in substrates(mirrored)
    ]

    assert scores[0] == scores[1]


def test_a_tied_part_is_placed_by_geometry_not_by_the_documents_order() -> None:
    """ADR-0006 where it actually bites. ``_contact`` measures one part
    against one substrate and cannot see the other, so a tie is broken on
    the substrates' own bounding boxes -- the left plate starts at x = -50
    and the right at x = 10, so the left one wins whichever way the
    document is walked."""
    mirrored = _mirrored_boards()
    walked = StepDocument(
        solids=tuple(reversed(mirrored.solids)),
        document=mirrored.document,
        timestamp=mirrored.timestamp,
    )

    forward = group(mirrored, substrates(mirrored))
    backward = group(walked, substrates(walked))

    assert _holder(forward, "MID")[0] == -50.0
    assert _holder(backward, "MID")[0] == -50.0


def test_grouping_onto_no_board_at_all_is_refused() -> None:
    """An empty substrate list is a caller's mistake, not an empty answer:
    silently returning nothing would drop every designator."""
    document = _document_of(("U1", _block(30.0, 20.0, 1.0, (0.0, 0.0, 0.0))))

    with pytest.raises(NoSubstrateError, match="no board to group"):
        group(document, ())


def test_grouping_onto_a_solid_that_is_no_slab_is_refused() -> None:
    """Grouping projects along a carrier normal, and a block has none. A
    caller that skipped the verification is refused rather than served a
    normal picked from whichever face happened to be biggest."""
    document = _document_of(("U1", _block(4.0, 4.0, 4.0, (0.0, 0.0, 0.0))))
    block = _box(30.0, 20.0, 10.0, (0.0, 0.0, 0.0))

    with pytest.raises(NoSubstrateError, match="has no carrier"):
        group(document, (block,))


# --------------------------------------------------------------------------
# The committed fixture. Real geometry, opt-in behind --boards.
# --------------------------------------------------------------------------


@pytest.mark.boards
def test_the_fixture_holds_two_substrates(document: StepDocument) -> None:
    """41 named solids carry reference designators; 2 are unnamed. Both
    unnamed solids are real boards, not one board in two pieces -- they are
    disjoint in y by 4.25 mm at the same z."""
    assert len(document.solids) == 43
    assert len(substrates(document)) == 2


@pytest.mark.boards
def test_a_real_board_passes_the_slab_test(document: StepDocument) -> None:
    """The INNOCENT probe on real geometry. Without it the two thresholds
    could refuse everything and every GUILTY probe would still be green."""
    assert all(is_slab(solid) for solid in substrates(document))


@pytest.mark.boards
def test_a_footswitch_is_not_a_substrate(document: StepDocument) -> None:
    """The GUILTY probe on real geometry: a switch body is a named solid, but
    feeding it to the verification directly must refuse it. Refused for
    thickness -- 5.60 mm against a 17.79 mm extent -- not for area, whose
    0.934 sits above the floor."""
    switch = _named(document, "SW1")
    first, second = _pair(switch)

    assert round(_area_ratio(first, second), 3) == 0.934
    assert is_slab(switch) is False


@pytest.mark.boards
def test_a_potentiometer_whose_opposed_faces_coincide_is_not_a_substrate(
    document: StepDocument,
) -> None:
    """A magnitude is not a thickness. RV1's two largest levels are exactly
    opposed and exactly equal in area, and lie in the same plane: their
    offsets sum to zero. Any test reading |offset sum| as "small" admits it."""
    pot = _named(document, "RV1")
    first, second = _pair(pot)

    assert _opposed(first, second) is True
    assert _area_ratio(first, second) == 1.0
    assert _thickness_nm(first, second) == Nanometre(0)
    assert is_slab(pot) is False


@pytest.mark.boards
def test_the_carrier_normal_is_the_levels_own_direction(document: StepDocument) -> None:
    """Not searched for and not swept: it falls out of the partition's key."""
    for solid in substrates(document):
        frame = carrier_frame(solid)
        assert frame is not None
        assert frame.w == (0.0, 0.0, 1.0)
        assert frame.origin_nm == (Nanometre(0), Nanometre(0), Nanometre(1_510_000))


@pytest.mark.boards
def test_the_two_substrates_measure_the_thickness_the_docket_recorded(
    document: StepDocument,
) -> None:
    """The docket's figure carried as an assertion, so it fails a suite rather
    than quietly staling: 0.000 + 1.510, a sum and never a difference."""
    for solid in substrates(document):
        first, second = _pair(solid)
        assert {first.offset_nm, second.offset_nm} == {Nanometre(0), Nanometre(1_510_000)}
        assert _thickness_nm(first, second) == Nanometre(1_510_000)


@pytest.mark.boards
def test_every_named_solid_is_grouped_onto_exactly_one_board(
    document: StepDocument,
) -> None:
    """41 designators across two boards, none dropped and none doubled."""
    grouped = group(document, substrates(document))
    assigned = [part.name for _substrate, components in grouped for part in components]

    assert len(assigned) == len(set(assigned)) == 41


@pytest.mark.boards
def test_the_two_boards_take_the_switches_and_the_rest(document: StepDocument) -> None:
    """The partition itself, not only its size: one board carries the two
    footswitches and the other carries the remaining 39. A grouping that
    put every part on one board would still satisfy a count."""
    parts = _partition(group(document, substrates(document)))

    assert _SWITCHES in parts
    assert len(parts) == 2
    assert sum(len(part) for part in parts) == 41


@pytest.mark.boards
def test_each_board_lists_its_parts_in_designator_order(document: StepDocument) -> None:
    """The walk order does not survive into the result."""
    walked = [solid.name for solid in document.solids if solid.name]

    # The control: the document's own order is not already sorted, so
    # agreement below is a sort and not a coincidence.
    assert walked != sorted(walked)

    for _substrate, components in group(document, substrates(document)):
        listed = [part.name for part in components]
        assert listed == sorted(listed)


@pytest.mark.boards
def test_grouping_does_not_depend_on_the_documents_own_order(
    document: StepDocument,
) -> None:
    """ADR-0006: no rule may consult input order."""
    reversed_document = StepDocument(
        solids=tuple(reversed(document.solids)),
        document=document.document,
        timestamp=document.timestamp,
    )

    # The control: the two documents really do present the solids in
    # opposite orders, so agreement below is not agreement about one walk.
    assert [s.name for s in reversed_document.solids] != [s.name for s in document.solids]

    assert _partition(
        group(reversed_document, substrates(reversed_document))
    ) == _partition(group(document, substrates(document)))


@pytest.mark.boards
def test_no_component_of_the_fixture_measures_a_slab(document: StepDocument) -> None:
    """The verification is what would survive an exporter that named nothing:
    every one of the 41 named solids must fail it, or the 43-substrate
    failure mode is not actually caught."""
    assert [solid.name for solid in document.solids if solid.name and is_slab(solid)] == []


@pytest.mark.boards
def test_the_thinnest_refused_solid_and_the_thickest_admitted_one_bracket_the_limit(
    document: StepDocument,
) -> None:
    """The thickness constant's measured gap, as an assertion rather than a
    comment: every substrate lies below 0.05 of its own extent and the
    thinnest solid the rule must refuse lies above 0.19, so a tenth sits in
    a gap nothing occupies. A constant tuned to one side would break this."""
    def fraction(solid: StepSolid) -> float:
        first, second = _pair(solid)
        return _thickness_nm(first, second) / nm_from_mm(_extent_mm(first, second))

    def measurable(solid: StepSolid) -> bool:
        """Only a solid the first two criteria already admit has a thickness
        fraction worth comparing; the rest are refused before it is read."""
        found = _two_largest(levels(solid))
        return found is not None and _opposed(*found) and _thickness_nm(*found) > 0

    admitted = [fraction(solid) for solid in substrates(document)]
    refused = [
        fraction(solid)
        for solid in document.solids
        if solid.name and measurable(solid)
    ]

    assert max(admitted) < 0.05
    assert min(refused) > 0.19
    assert math.isclose(max(admitted), 0.04758, abs_tol=5e-5)
    assert math.isclose(min(refused), 0.19879, abs_tol=5e-5)
