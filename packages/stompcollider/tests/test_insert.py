"""The insertion search: where the enclosure stops a board on its way in.

Two halves, tested apart. ``contact_depth`` is pure -- a predicate over
depths -- so every claim about *how* the path is walked is made against a
synthetic blocked set with no kernel in sight, including the control that
tells this design from seat-then-retreat. ``beyond_cavity`` and
``CaseCavity`` read solids, and are exercised against boxes built here
rather than against the committed fixture, so they run in a standard suite.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from stompcollider.insert import (
    CaseCavity,
    Cavity,
    Insertion,
    beyond_cavity,
    contact_depth,
)
from stompcollider.model import Board, Correspondence, Placement
from stompgeom.step import StepSolid
from stompmodel.frames import CoordinateFrame
from stompmodel.units import Nanometre, nm_from_mm

# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _nm(millimetres: float) -> Nanometre:
    return nm_from_mm(millimetres)


def _banded(*bands: tuple[float, float]):
    """A predicate blocked exactly inside ``bands``, recording what it was asked.

    Half-open at the bottom, so a band's own lower edge is the last clear
    depth: that makes the exact contact depth expressible as the band's own
    number rather than one nanometre under it.
    """
    asked: list[tuple[Nanometre, bool]] = []

    def blocked(depth_nm: Nanometre) -> bool:
        answer = any(_nm(low) < depth_nm <= _nm(high) for low, high in bands)
        asked.append((depth_nm, answer))
        return answer

    blocked.asked = asked  # type: ignore[attr-defined]
    return blocked


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _box(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _solid(name: str, shape: Any) -> StepSolid:
    return StepSolid(name, shape)


def _board(extent_mm: tuple[float, float, float] = (20.0, 10.0, 1.6)) -> Board:
    return Board(
        ordinal=1,
        designators=("RV1",),
        extent_nm=(_nm(extent_mm[0]), _nm(extent_mm[1]), _nm(extent_mm[2])),
        carrier=_identity_frame(),
        components=(),
        panel_face="+w",
    )


def _placement(seat_mm: float) -> Placement:
    return Placement(
        rank=1,
        x_nm=Nanometre(0),
        y_nm=Nanometre(0),
        z_nm=_nm(seat_mm),
        theta_deg=0.0,
        correspondence=(
            Correspondence(
                designator="RV1",
                hole_index=1,
                hole_xy_nm=(Nanometre(0), Nanometre(0)),
                insertion_nm=_nm(1.0),
                offset_nm=Nanometre(0),
                seat_nm=_nm(seat_mm),
            ),
        ),
        clashes=(),
    )


# --------------------------------------------------------------------------
# ``contact_depth``: the path walk itself, over a synthetic blocked set.
# --------------------------------------------------------------------------


def test_a_clear_path_reaches_the_seat_the_holes_fix() -> None:
    """One pass, nothing found, and the hole geometry governs as before."""
    assert contact_depth(
        _banded(), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05)
    ) == _nm(-10.0)


def test_a_band_before_the_seat_stops_the_board_at_its_lower_edge() -> None:
    """The answer is the deepest reachable pose, exact to the nanometre."""
    found = contact_depth(
        _banded((-15.0849, -10.0)), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05)
    )

    assert found == _nm(-15.0849)


def test_the_search_finds_a_band_that_seating_then_retreating_misses() -> None:
    """The whole reason this is a search, stated as a control.

    The board is clear at the seat the holes fix and clear again on either
    side of a band it would have to cross to get there. Testing the seat and
    backing off until it clears -- which is what this design replaces --
    reports no correction at all, because the seat is already clear. The
    reachable depth is the near edge of the band, several millimetres away.
    """
    blocked = _banded((-15.0, -10.8))
    seat_nm = _nm(-10.0)

    assert not blocked(seat_nm)
    assert contact_depth(blocked, _nm(-40.0), seat_nm, _nm(2.0), _nm(0.05)) == _nm(-15.0)


def test_a_band_the_coarse_pitch_steps_over_is_found_by_the_fine_sweep() -> None:
    """What ``--seat-pitch-min`` buys, and the only thing it does.

    Two obstructions: a wide one the coarse pass lands in, and a 0.4 mm one
    lying between two coarse samples inside the bracket that pass leaves.
    Sweeping the bracket at 0.05 mm finds the narrow one; sweeping it at
    1 mm steps straight over it and reports the wide one's edge instead --
    two different answers from one geometry and one flag.
    """
    bands = ((-13.5, -13.1), (-12.5, -10.0))
    fine = contact_depth(_banded(*bands), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05))
    coarse = contact_depth(_banded(*bands), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(1.0))

    assert fine == _nm(-13.5)
    assert coarse == _nm(-12.5)


def test_a_band_narrower_than_the_coarse_pitch_and_outside_the_bracket_is_missed() -> None:
    """Stated plainly rather than left to be discovered.

    The bracket is what the fine sweep refines, so a band lying wholly
    between two coarse samples and *below* the first blocked one is never
    reached at any fine pitch. Silence about it is not evidence of
    clearance, exactly as ``nesting-truncated`` is not evidence about
    artwork below a refused form level.
    """
    missed = contact_depth(
        _banded((-14.6, -14.2)), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05)
    )

    assert missed == _nm(-10.0)


def test_the_seat_itself_is_always_sampled_however_the_pitch_divides() -> None:
    """A band ending exactly at the seat is the common case, and a scan that
    stopped one whole pitch short of it would report a clear path."""
    found = contact_depth(
        _banded((-10.083, -9.999)), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05)
    )

    assert found == _nm(-10.083)


def test_a_blocked_entry_pose_is_no_travel_rather_than_a_travel_of_zero() -> None:
    assert contact_depth(
        _banded((-41.0, -10.0)), _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05)
    ) is None


def test_nothing_beyond_the_first_blocked_sample_is_ever_sampled_again() -> None:
    """The interval shrinks rather than being rescanned: once a depth is
    known blocked it is an upper bound, so no later query may exceed it."""
    blocked = _banded((-20.5, -19.0), (-14.0, -10.0))
    contact_depth(blocked, _nm(-40.0), _nm(-10.0), _nm(2.0), _nm(0.05))

    asked = blocked.asked  # type: ignore[attr-defined]
    first = next(index for index, (_d, hit) in enumerate(asked) if hit)

    assert asked[first][0] == _nm(-20.0)
    assert max(depth for depth, _hit in asked[first + 1:]) <= asked[first][0]


def test_a_seat_at_or_below_the_entry_pose_needs_no_query_at_all() -> None:
    """Nothing can be met before the board is already home, so nothing is asked."""
    blocked = _banded((-41.0, 0.0))

    assert contact_depth(blocked, _nm(-10.0), _nm(-10.0), _nm(2.0), _nm(0.05)) == _nm(
        -10.0
    )
    assert blocked.asked == []  # type: ignore[attr-defined]


def test_a_pitch_finer_than_a_nanometre_is_one_nanometre() -> None:
    """The canonical representation states no finer depth, so a pitch below
    it is clamped rather than looping for ever."""
    found = contact_depth(
        _banded((-11.0, -10.0)), _nm(-12.0), _nm(-10.0), Nanometre(0), Nanometre(0)
    )

    assert found == _nm(-11.0)


# --------------------------------------------------------------------------
# ``beyond_cavity``: which case solid closes over the board, by geometry.
# --------------------------------------------------------------------------


def _shell() -> StepSolid:
    """A 100 x 50 open box 25 deep with a 3 mm drilled plate on top."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    outer = _box((-50.0, -25.0, -25.0), 100.0, 50.0, 28.0)
    cavity = _box((-48.0, -23.0, -25.0), 96.0, 46.0, 25.0)
    return _solid("BOX", BRepAlgoAPI_Cut(outer, cavity).Shape())


def _backplate() -> StepSolid:
    return _solid("PLATE", _box((-49.0, -24.0, -29.0), 98.0, 48.0, 6.0))


def _fastener() -> StepSolid:
    """A screw at one corner, occupying exactly the depths the backplate does."""
    return _solid("SCREW", _box((-45.0, -20.0, -29.0), 4.0, 4.0, 12.0))


def test_a_plate_beyond_the_mouth_that_spans_the_board_closes_over_it() -> None:
    inside, beyond = beyond_cavity(
        (_shell(), _backplate()), _identity_frame(), _board().extent_nm
    )

    assert [solid.name for solid in inside] == ["BOX"]
    assert [solid.name for solid in beyond] == ["PLATE"]


def test_a_fastener_at_the_very_same_depths_is_not_what_closes_over_it() -> None:
    """The control the split needs: a screw occupies the backplate's own
    depths, so no plane alone tells them apart. It stays in the enclosure the
    board is fitted into, exactly as the spec requires of bosses and screws."""
    inside, beyond = beyond_cavity(
        (_shell(), _backplate(), _fastener()), _identity_frame(), _board().extent_nm
    )

    assert sorted(solid.name for solid in inside) == ["BOX", "SCREW"]
    assert [solid.name for solid in beyond] == ["PLATE"]


def test_a_board_wider_than_the_plate_reads_it_as_an_obstruction() -> None:
    """A closure narrower than the board it covers is not one: the finding
    becomes a shortfall rather than a case that will not close, which is a
    different statement about the same overlap and never silence."""
    _inside, beyond = beyond_cavity(
        (_shell(), _backplate()), _identity_frame(), _board((200.0, 10.0, 1.6)).extent_nm
    )

    assert beyond == ()


def test_a_case_carrying_no_drilled_face_states_no_mouth_and_nothing_is_beyond() -> None:
    inside, beyond = beyond_cavity(
        (_backplate(),), _identity_frame(), _board().extent_nm
    )

    assert [solid.name for solid in inside] == ["PLATE"]
    assert beyond == ()


# --------------------------------------------------------------------------
# ``CaseCavity``: the same walk over real solids.
# --------------------------------------------------------------------------


def _cavity(*case: StepSolid, board_solids: tuple[StepSolid, ...]) -> CaseCavity:
    return CaseCavity(case, {1: board_solids}, _nm(2.0), _nm(0.05))


def _slab(at_z: float, dx: float = 20.0, dy: float = 10.0) -> StepSolid:
    return _solid("", _box((-dx / 2, -dy / 2, at_z - 1.6), dx, dy, 1.6))


def test_the_case_carries_a_board_past_the_seat_its_own_profile_fixed() -> None:
    """The search is what fixes the depth; the profile only bounds nothing.

    This slab's holes state -5 mm and the drilled plate stands at 0, so
    there is a clear path 5 mm beyond the profile's answer and the board
    travels it. Measured on the tar fixture, a profile that governed put the
    footswitch board 11 mm out on a tangency its own boolean mishandled,
    which the exact geometry on this path does not repeat.
    """
    cavity = _cavity(_shell(), board_solids=(_slab(0.0),))

    found = cavity.insertion(_board(), _placement(-5.0), _identity_frame())

    # Within a fuzz of the plate, not on it: the predicate treats geometry
    # within 0.0001 mm as coincident, so the last depth it calls clear lies
    # that much beyond true contact.
    assert found.depth_nm is not None
    assert _nm(0.0) <= found.depth_nm <= _nm(0.001)
    assert found.obstruction == "BOX"


def test_a_board_too_wide_for_the_cavity_is_stopped_at_its_mouth() -> None:
    """It meets the box's rim rather than its walls, so the answer is the
    mouth itself -- and the finding names both solids that met."""
    wide = _slab(0.0, dx=99.0, dy=49.0)
    cavity = _cavity(_shell(), board_solids=(wide,))

    found = cavity.insertion(
        _board((99.0, 49.0, 1.6)), _placement(-5.0), _identity_frame()
    )

    # Within a fuzz of the mouth, not on it: the predicate treats geometry
    # within 0.0001 mm as coincident, so the last depth it calls clear lies
    # that much beyond true contact. The bound is what is asserted, because
    # the slack is a property of the predicate rather than of this board.
    assert found.depth_nm is not None
    assert _nm(-25.0) <= found.depth_nm <= _nm(-24.999)
    assert found.obstruction == "BOX"
    assert found.part is not None


def _open_shell() -> StepSolid:
    """The same shell with an aperture a 20 x 10 board passes clean through.

    What the closure tests need is a board the *cavity* never touches, so
    that the backplate is the only thing left to explain the answer; a
    drilled face solid across its whole footprint stops every board on it
    eventually, which would confound that.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    return _solid(
        "BOX",
        BRepAlgoAPI_Cut(
            _shell().shape, _box((-15.0, -7.5, -1.0), 30.0, 15.0, 6.0)
        ).Shape(),
    )


def test_a_board_meeting_only_the_backplate_seats_and_says_the_case_is_shallow() -> None:
    """The lid takes no part in the travel and every part of the finding.

    The board reaches the depth its holes fix -- the backplate is not on the
    path it is inserted along, and the cavity's own aperture lets it through
    -- and the overlap with it is reported as the case not closing, which is
    what an operator runs this tool to discover.
    """
    deep = _solid("", _box((-10.0, -5.0, -30.0), 20.0, 10.0, 4.0))
    cavity = _cavity(_open_shell(), _backplate(), board_solids=(_slab(0.0), deep))

    found = cavity.insertion(_board(), _placement(-2.0), _identity_frame())

    assert found.depth_nm == _nm(-2.0)
    assert found.obstruction is None
    assert found.lid_solid == "PLATE"
    assert found.lid_nm is not None and found.lid_nm > 0


def test_a_board_nothing_on_its_path_touches_rests_where_its_holes_fix_it() -> None:
    """The one case the profile still decides, and the control beside the
    test above it: an enclosure that says nothing about a board leaves the
    hole geometry as the only statement of where it comes to rest, which is
    also what a run with no case model at all does."""
    cavity = _cavity(_open_shell(), board_solids=(_slab(0.0),))

    assert cavity.insertion(_board(), _placement(-2.0), _identity_frame()) == Insertion(
        _nm(-2.0)
    )


def test_a_board_no_case_solid_can_ever_reach_needs_no_query() -> None:
    """The prefilter's own claim: a board standing outside the case's
    footprint meets nothing at any depth, so the hole geometry governs."""
    aside = _solid("", _box((400.0, 400.0, -1.6), 20.0, 10.0, 1.6))
    cavity = _cavity(_shell(), board_solids=(aside,))

    assert cavity.insertion(_board(), _placement(-5.0), _identity_frame()) == Insertion(
        _nm(-5.0)
    )


def test_a_board_with_no_solids_at_all_is_governed_by_its_holes() -> None:
    cavity = _cavity(_shell(), board_solids=())

    assert cavity.insertion(_board(), _placement(-5.0), _identity_frame()) == Insertion(
        _nm(-5.0)
    )


def test_the_pitches_are_reported_for_the_stage_that_ran_the_search() -> None:
    assert _cavity(_shell(), board_solids=()).parameters() == (
        ("seat_pitch_max_nm", 2_000_000),
        ("seat_pitch_min_nm", 50_000),
    )


def test_case_cavity_satisfies_the_cavity_protocol() -> None:
    assert isinstance(_cavity(_shell(), board_solids=()), Cavity)


# --------------------------------------------------------------------------
# ``Insertion``: the three states, and the two it refuses to conflate.
# --------------------------------------------------------------------------


def test_a_board_that_reached_no_depth_names_what_stopped_it() -> None:
    with pytest.raises(ValueError, match="stopped by something"):
        Insertion(None)


def test_a_board_meeting_the_lid_names_the_solid_it_met() -> None:
    with pytest.raises(ValueError, match="names the solid"):
        Insertion(Nanometre(0), lid_nm=Nanometre(1))


def test_arrested_is_a_depth_beside_an_obstruction_and_nothing_else() -> None:
    assert not Insertion(Nanometre(0)).arrested
    assert not Insertion(None, "RV1", "BOX").arrested
    assert Insertion(Nanometre(0), "RV1", "BOX").arrested


def test_a_placement_seated_by_its_holes_is_the_one_this_module_reads() -> None:
    """The guard the search rests on: ``placement.z_nm`` is where the holes
    put the board, so a caller handing it an unseated placement would be
    answered about a board resting at the panel surface. ``Seat`` passes the
    reduced placement, never the raw one."""
    cavity = _cavity(_open_shell(), board_solids=(_slab(0.0),))
    raw = replace(_placement(-5.0), z_nm=Nanometre(0))

    assert cavity.insertion(_board(), raw, _identity_frame()).depth_nm == Nanometre(0)
    assert cavity.insertion(
        _board(), _placement(-5.0), _identity_frame()
    ).depth_nm == _nm(-5.0)


def _sphere(at: tuple[float, float, float], radius: float) -> Any:
    """A sphere: the shape whose bounding box holds the most empty corner."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeSphere(gp_Pnt(*at), radius).Shape()


def test_a_pair_the_boxes_admit_and_the_geometry_clears_costs_one_query() -> None:
    """The prefilter is a negative filter and nothing more.

    A sphere low in the cavity reaches the board's own box at one corner and
    holds no material there, so the pair is sampled and cleared; nothing
    else in this case reaches the board at any travel, and beyond the band
    where that one could no boolean is run. The board reaches the seat its
    holes fix either way, which is the claim: a filter that discarded the
    pair and one that ran it must agree.
    """
    low = _solid("BEAD", _sphere((-14.0, -9.0, -19.95), 5.0))
    cavity = _cavity(low, board_solids=(_slab(0.0),))

    assert cavity.insertion(
        _board(), _placement(-0.5), _identity_frame()
    ) == Insertion(_nm(-0.5))


def test_a_closure_the_seated_board_never_reaches_is_measured_and_says_nothing() -> None:
    """Two backplates, one of them 40 mm below the other.

    The far one is beyond every box the board occupies at rest, so it earns
    no finding; the near one does. A rule that reported the first plate it
    found beyond the mouth would name the wrong solid here.
    """
    far = _solid("FAR", _box((-49.0, -24.0, -70.0), 98.0, 48.0, 6.0))
    deep = _solid("", _box((-10.0, -5.0, -30.0), 20.0, 10.0, 4.0))
    cavity = _cavity(_open_shell(), far, _backplate(), board_solids=(_slab(0.0), deep))

    found = cavity.insertion(_board(), _placement(-2.0), _identity_frame())

    assert found.lid_solid == "PLATE"


def test_a_closure_whose_box_the_board_reaches_but_whose_material_it_misses() -> None:
    """Boxes admit the pair; the exact intersection clears it.

    A dome beyond the mouth, and a board solid standing in the empty corner
    of its bounding box and clear of the cavity's own footprint: the filter
    sends the pair to the boolean, which finds nothing shared. Silence about
    a case that does close is the right answer, and a rule reading the box
    rather than the material would say the enclosure is too shallow.
    """
    dome = _solid("DOME", _sphere((0.0, 0.0, -40.0), 30.0))
    corner = _solid("", _box((22.0, 26.0, -62.0), 8.0, 8.0, 8.0))
    cavity = _cavity(_open_shell(), dome, board_solids=(_slab(0.0), corner))

    found = cavity.insertion(_board(), _placement(-2.0), _identity_frame())

    assert found == Insertion(_nm(-2.0))
