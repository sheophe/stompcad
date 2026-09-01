"""Match: registering a board into the panel frame, then recognising it.

Every fixture states a board in its **own** frame and, separately, the
registration a test expects ``Match`` to recover. A board authored in panel
coordinates is the mistake the registration defect hid behind, so
``_Registration`` refuses to express one; the two tests below it are that
gate's control and the control that it bites here. No kernel and no fixture
file -- the reader seam is ``test_registration.py``'s job, behind
``--boards``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pytest

from stompcollider.match import PANEL_FACE, Match
from stompcollider.match import _ambiguous as _raw_ambiguous
from stompcollider.match import _candidates as _raw_candidates
from stompcollider.match import _mm as _raw_mm
from stompcollider.match import _placement as _raw_placement
from stompcollider.model import (
    Board,
    Component,
    DockData,
    Profile,
    Protrusion,
)
from stompmodel.diagnostics import Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, Hole, StageRun
from stompmodel.protocols import Pipeline, Stage
from stompmodel.units import Nanometre, nm_from_mm

#: Half a 2.54 mm grid pitch, the derivation the command line performs.
_TOLERANCE = Nanometre(1_270_000)


# --------------------------------------------------------------------------
# Authoring a board that is not already docked
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Registration:
    """Where a board stands relative to the panel: the unknown Match solves.

    Never the identity, and never a pure turn or a pure shift either. A
    fixture whose board frame *is* the panel frame answers the question
    before it is asked, which is exactly how a pairing rule that could only
    recognise an already-docked board survived a careful suite.
    """

    x_mm: float
    y_mm: float
    theta_deg: float

    def __post_init__(self) -> None:
        if self.theta_deg % 360.0 == 0.0:
            raise ValueError(
                "a board fixture must be turned away from the panel frame, "
                f"not by {self.theta_deg} degrees"
            )
        if (self.x_mm, self.y_mm) == (0.0, 0.0):
            raise ValueError("a board fixture must sit away from the panel origin")

    def carries(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """Where this registration puts a point of the board on the panel."""
        theta = math.radians(self.theta_deg)
        cos, sin = math.cos(theta), math.sin(theta)
        return (
            self.x_mm + cos * x_mm - sin * y_mm,
            self.y_mm + sin * x_mm + cos * y_mm,
        )


#: The one registration every fixture below is stated against. The angle is
#: no multiple of a right angle, so a transform that dropped a sine or a
#: cosine term cannot reproduce it by symmetry.
_REGISTRATION = _Registration(x_mm=23.0, y_mm=-11.0, theta_deg=115.0)


@dataclass(frozen=True, slots=True)
class _Part:
    """Where a part sits **on the board**, in the board's own millimetres."""

    designator: str
    x_mm: float
    y_mm: float


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _case() -> CaseRegistration:
    return CaseRegistration("1590BB", CaseFace.BOX, "test.stp", FaceFrame(_identity_frame()))


def _extent() -> tuple[Nanometre, Nanometre, Nanometre]:
    return (Nanometre(1_000_000), Nanometre(1_000_000), Nanometre(300_000))


#: Where every hand-built part's tip stands above its board. Not zero, so a
#: seating that forgot to subtract it reads as a positive depth.
_TIP = Nanometre(7_000_000)


def _profile() -> Profile:
    """A radius well under any hole radius used here, so every part passes
    fully and no fixture below rests on a particular fit outcome."""
    return Profile(((Nanometre(1_000_000), Nanometre(0), Nanometre(5_000_000)),))


def _component(part: _Part) -> Component:
    return Component(
        part.designator,
        Protrusion(
            part.designator,
            (nm_from_mm(part.x_mm), nm_from_mm(part.y_mm)),
            _profile(),
            _TIP,
        ),
    )


def _board(parts: tuple[_Part, ...], *, extra: tuple[Component, ...] = (), ordinal: int = 1) -> Board:
    """One board's components, stored **reversed** per the fixture rule."""
    components = tuple(reversed([_component(part) for part in parts])) + extra
    designators = tuple(sorted(component.designator for component in components))
    return Board(ordinal, designators, _extent(), _identity_frame(), components)


def _hole(
    index: int,
    part: _Part,
    *,
    miss_mm: tuple[float, float] = (0.0, 0.0),
    registration: _Registration = _REGISTRATION,
    diameter_mm: float = 3.0,
) -> Hole:
    """The hole ``registration`` carries ``part`` onto, plus any deliberate miss."""
    x_mm, y_mm = registration.carries(part.x_mm, part.y_mm)
    return Hole.from_measurement(
        nm_from_mm(x_mm + miss_mm[0]),
        nm_from_mm(y_mm + miss_mm[1]),
        nm_from_mm(diameter_mm),
    ).with_number(index)


def _dock(board: Board, holes: tuple[Hole, ...]) -> DockData:
    return DockData(case=_case(), boards=(board,), holes=holes)


def _axes(board: Board) -> dict[str, tuple[Nanometre, Nanometre]]:
    return {
        component.designator: component.protrusion.axis_xy_nm
        for component in board.components
        if component.protrusion is not None
    }


def _paired(placement) -> set[tuple[str, int]]:  # type: ignore[no-untyped-def]
    return {(c.designator, c.hole_index) for c in placement.correspondence}


def _codes(data: DockData) -> list[str]:
    return [diagnostic.code for diagnostic in data.diagnostics]


# --------------------------------------------------------------------------
# The controls for the authoring rule itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x_mm, y_mm, theta_deg",
    [(0.0, 0.0, 0.0), (17.0, -4.0, 360.0), (0.0, 0.0, 115.0)],
)
def test_a_board_standing_in_panel_coordinates_cannot_be_stated(
    x_mm: float, y_mm: float, theta_deg: float
) -> None:
    """The control for this suite's own instrument: a deliberate breach of
    the authoring rule must fail, or "every fixture is undocked" is a claim
    nothing enforces. An untuned board, one merely shifted, and one merely
    turned are each refused."""
    with pytest.raises(ValueError):
        _Registration(x_mm=x_mm, y_mm=y_mm, theta_deg=theta_deg)


def test_no_fixture_part_starts_within_reach_of_any_hole() -> None:
    """And the control that the rule bites where it matters.

    Every axis of the registering fixture stands further from every hole
    than the recognition tolerance, so nothing below could pair by absolute
    proximity: a stage that compared positions before solving for the
    board's frame reaches ``no-correspondence`` on this fixture, which is
    what the real boards did.
    """
    board, holes = _three_parts()
    tolerance_mm = _raw_mm(_TOLERANCE)

    nearest = min(
        math.hypot(
            _raw_mm(axis[0] - hole.x_nm),
            _raw_mm(axis[1] - hole.y_nm),
        )
        for axis in _axes(board).values()
        for hole in holes
    )

    assert nearest > tolerance_mm


# --------------------------------------------------------------------------
# Registration: the transform is found before anything is paired
# --------------------------------------------------------------------------

#: Three parts, no two of them at a right angle about a third, so one
#: registration recognises all three and no other recognises more than two.
#: Their holes are numbered out of part order, per the fixture rule.
_D1 = _Part("D1", 0.0, 0.0)
_D2 = _Part("D2", 30.0, 0.0)
_D3 = _Part("D3", 6.0, 17.0)


def _three_parts() -> tuple[Board, tuple[Hole, ...]]:
    board = _board((_D1, _D2, _D3))
    holes = (_hole(2, _D3), _hole(3, _D1), _hole(1, _D2))
    return board, holes


def test_a_rotated_and_translated_board_registers_onto_its_holes() -> None:
    """The defect this stage was rewritten for: a board reaches Match in its
    own frame, and the registration is what puts its parts on holes."""
    board, holes = _three_parts()

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    (placement,) = data.placements[1]
    assert _paired(placement) == {("D1", 3), ("D2", 1), ("D3", 2)}
    assert data.diagnostics == ()
    assert data.boards[0].panel_face == PANEL_FACE
    assert data.unmatched_holes == ()


def test_the_recovered_transform_is_the_registration_the_fixture_was_stated_from() -> None:
    """Not merely *a* transform that pairs: the one the board actually stands
    at. Recognising the right holes through a wrong motion would place every
    solid wrongly downstream while every correspondence still read right."""
    board, holes = _three_parts()

    (placement,) = Match(_TOLERANCE).apply(_dock(board, holes)).placements[1]

    assert placement.x_nm == pytest.approx(nm_from_mm(_REGISTRATION.x_mm), abs=100)
    assert placement.y_nm == pytest.approx(nm_from_mm(_REGISTRATION.y_mm), abs=100)
    assert placement.theta_deg % 360.0 == pytest.approx(_REGISTRATION.theta_deg, abs=1e-5)
    assert [c.offset_nm for c in placement.correspondence] == [Nanometre(0)] * 3


def test_every_recognised_hole_is_claimed_and_the_rest_are_not() -> None:
    """``unmatched_holes`` is the assembly's leftovers, not a board's."""
    board, holes = _three_parts()
    spare = Hole.from_measurement(
        nm_from_mm(-90.0), nm_from_mm(70.0), nm_from_mm(3.0)
    ).with_number(9)

    data = Match(_TOLERANCE).apply(_dock(board, holes + (spare,)))

    assert data.unmatched_holes == (9,)


# --------------------------------------------------------------------------
# Too little to register, and nothing that registers at all
# --------------------------------------------------------------------------


def test_one_admitted_protrusion_leaves_the_board_free_to_turn() -> None:
    """Two is the rank of a rigid planar transform, not a threshold: one
    point fixes no angle and none seeds nothing."""
    board = _board((_D1,))
    _, holes = _three_parts()

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert _codes(data) == ["under-constrained-board"]
    assert data.diagnostics[0].severity == Severity.WARNING
    assert data.placements == {}
    assert data.boards[0].panel_face is None


def test_a_second_protrusion_is_what_lifts_that_finding() -> None:
    """The control beside it: the finding is about the count, not about this
    board, so adding one part must place it and withdraw the warning."""
    board = _board((_D1, _D2))
    _, holes = _three_parts()

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert "under-constrained-board" not in _codes(data)
    assert data.placements[1] != ()


def test_a_board_no_rigid_motion_fits_is_the_wrong_board_for_this_case() -> None:
    """Every seed fails the separation test: the parts and this panel's holes
    do not stand in the same relation to one another under any motion."""
    board = _board((_D1, _D2))
    far = _Part("far", 400.0, 400.0)
    holes = (_hole(1, _D1), _hole(2, far))

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert _codes(data) == ["no-correspondence"]
    assert data.diagnostics[0].severity == Severity.ERROR
    assert data.placements == {}


def test_a_hole_pair_matching_the_part_pairs_separation_is_what_seeds_one() -> None:
    """The control: the same two parts against a hole pair whose separation
    does agree. Only the separation changed, so only the separation can be
    what the finding above was about. Two points are carried onto two holes
    by a half turn as well, so both seatings come back."""
    board = _board((_D1, _D2))
    holes = (_hole(1, _D1), _hole(2, _D2))

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert _codes(data) == ["ambiguous-placement"]
    assert len(data.placements[1]) == 2


def test_two_protrusions_at_one_position_fix_no_angle() -> None:
    """A seed pair that coincides has no separation vector to rotate, and is
    passed over rather than divided by. The holes sit 2 mm apart, inside
    twice the tolerance, so the separation gate does not reject the seed
    before the degenerate transform is even reached."""
    twin = _Part("D9", 0.0, 0.0)
    board = _board((_D1, twin))
    holes = (_hole(1, _D1), _hole(2, _D1, miss_mm=(2.0, 0.0)))

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert _codes(data) == ["no-correspondence"]
    assert data.placements == {}


# --------------------------------------------------------------------------
# unmatched-part, in both of its shapes
# --------------------------------------------------------------------------

#: Far enough outside the tolerance that no seed involving it recognises
#: more than the registration below, and near enough that the finding still
#: names a hole worth looking at.
_MISS_MM = 4.0


def _with_a_missing_part(miss_mm: float) -> DockData:
    stray = _Part("D4", -21.0, 8.0)
    board = _board((_D1, _D2, _D3, stray))
    holes = (
        _hole(2, _D3),
        _hole(3, _D1),
        _hole(1, _D2),
        _hole(4, stray, miss_mm=(miss_mm, 0.0)),
    )
    return _dock(board, holes)


def test_an_axis_no_candidate_places_names_the_hole_it_came_nearest() -> None:
    """The distance is the useful fact: a part a fraction of a millimetre out
    is a misplaced footprint, and one metres away was never a panel
    reference. Dropping it silently lets a real misalignment reach no
    artefact at all."""
    data = Match(_TOLERANCE).apply(_with_a_missing_part(_MISS_MM))

    assert _codes(data) == ["unmatched-part"]
    (found,) = data.diagnostics
    assert found.severity == Severity.WARNING
    assert found.data == (
        ("designator", "D4"),
        ("nearest_hole", 4),
        ("offset_nm", nm_from_mm(_MISS_MM)),
    )
    assert "4.000 mm from hole 4" in found.message
    assert _paired(data.placements[1][0]) == {("D1", 3), ("D2", 1), ("D3", 2)}


def test_the_same_part_inside_the_tolerance_earns_no_finding() -> None:
    """The control: only the distance changed, so only the distance can be
    what the finding above was about -- and the part now pairs."""
    data = Match(_TOLERANCE).apply(_with_a_missing_part(0.5))

    assert data.diagnostics == ()
    assert _paired(data.placements[1][0]) == {("D1", 3), ("D2", 1), ("D3", 2), ("D4", 4)}


def test_an_admitted_part_with_no_axis_carries_neither_hole_nor_offset() -> None:
    """The code's second shape. A part yielding no admissible cylinder has no
    distance to any hole under any motion, so the reader tells the two apart
    by the keys present rather than by a second code."""
    board, holes = _three_parts()
    bare = replace(board, components=board.components + (Component("D9", None),))

    data = Match(_TOLERANCE).apply(_dock(bare, holes))

    assert _codes(data) == ["unmatched-part"]
    assert data.diagnostics[0].severity == Severity.WARNING
    assert data.diagnostics[0].data == (("designator", "D9"),)


def test_a_part_the_filter_withheld_is_not_a_finding() -> None:
    """The control beside it, and the distinction the field exists for: the
    panel-reference expression choosing not to admit a part is not a fault
    in the board, and reporting one per unadmitted component would bury the
    real finding under every capacitor on the substrate."""
    board, holes = _three_parts()
    withheld = replace(
        board, components=board.components + (Component("D9", None, admitted=False),)
    )

    data = Match(_TOLERANCE).apply(_dock(withheld, holes))

    assert data.diagnostics == ()


def test_a_part_with_no_axis_is_reported_even_when_nothing_registers() -> None:
    """It needs no registration to be true, so it survives the two findings
    that end a board's story early."""
    board = _board((_D1,), extra=(Component("D9", None),))
    _, holes = _three_parts()

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert _codes(data) == ["under-constrained-board", "unmatched-part"]


# --------------------------------------------------------------------------
# ambiguous-pairing, judged over every registration that survives
# --------------------------------------------------------------------------


def _two_parts_one_hole(gap_mm: float) -> DockData:
    """``D3`` with a twin ``gap_mm`` away on the board, and no hole of its own."""
    twin = _Part("D5", _D3.x_mm + gap_mm, _D3.y_mm)
    board = _board((_D1, _D2, _D3, twin))
    holes = (_hole(2, _D3), _hole(3, _D1), _hole(1, _D2))
    return _dock(board, holes)


def test_two_protrusions_within_tolerance_of_one_hole_is_ambiguous() -> None:
    """Two parts cannot occupy one hole, and choosing between them would be
    the weighting the pre-spec refuses."""
    data = Match(_TOLERANCE).apply(_two_parts_one_hole(0.4))

    assert "ambiguous-pairing" in _codes(data)
    (found,) = [d for d in data.diagnostics if d.code == "ambiguous-pairing"]
    assert found.severity == Severity.ERROR
    assert found.data == (("hole", 2),)


def test_a_twin_outside_the_tolerance_claims_nothing() -> None:
    """The control: only the twin's distance changed, so the conviction above
    is about reach and not about there being a fourth part."""
    data = Match(_TOLERANCE).apply(_two_parts_one_hole(3.0))

    assert "ambiguous-pairing" not in _codes(data)


#: A pair one millimetre apart, standing where the registration below leaves
#: them near no hole at all -- and where a *dominated* seed piles both onto
#: one. See ``test_a_dominated_seed_piling_parts_onto_one_hole_convicts_nobody``.
_P1 = _Part("P1", 60.0, 40.0)
_P2 = _Part("P2", 61.0, 40.0)
_D4 = _Part("D4", -14.0, -9.0)
_D5 = _Part("D5", 18.0, -20.0)

#: ``D1`` and ``D2`` swapped about their own midpoint: the half turn that
#: takes each onto the other's hole, which is a rigid motion this panel
#: really does admit. ``P1`` lands here under it.
_HALF_TURNED_P1 = _Part("", 2 * 15.0 - _P1.x_mm, -_P1.y_mm)


def _a_wrong_seed_that_would_convict() -> DockData:
    board = _board((_D1, _D2, _D3, _D4, _D5, _P1, _P2))
    holes = (
        _hole(1, _D3),
        _hole(2, _D5),
        _hole(3, _D1),
        _hole(4, _D4),
        _hole(5, _D2),
        _hole(6, _HALF_TURNED_P1),
    )
    return _dock(board, holes)


def _half_turn() -> tuple[float, float, float]:
    """The dominated registration: the board put down turned half a turn
    about ``D1`` and ``D2``'s own midpoint, which is a rigid motion this
    panel really does admit. Composed from the fixture's own registration by
    plain arithmetic, so nothing under test is used to build it."""
    x_mm, y_mm = _REGISTRATION.carries(2 * 15.0, 0.0)
    return (x_mm, y_mm, math.radians(_REGISTRATION.theta_deg + 180.0))


def test_a_dominated_seed_piling_parts_onto_one_hole_convicts_nobody() -> None:
    """A seed recognising fewer parts than another is not a candidate at all.

    It is strictly dominated -- a motion demonstrably exists putting more of
    this board through holes -- so it is no claim about where the board sits,
    and convicting a board over one would refuse nearly every real input.
    Here the half-turned seed puts both ``P1`` and ``P2`` inside hole 6 while
    reaching four parts against the surviving registration's five.
    """
    data = Match(_TOLERANCE).apply(_a_wrong_seed_that_would_convict())

    assert "ambiguous-pairing" not in _codes(data)
    (placement,) = data.placements[1]
    assert _paired(placement) == {
        ("D1", 3), ("D2", 5), ("D3", 1), ("D4", 4), ("D5", 2)
    }


def test_that_dominated_hypothesis_really_would_have_convicted() -> None:
    """The control for the test above, which otherwise passes by finding
    nothing. The dominated motion is judged on its own terms and does claim
    hole 6 twice, so the silence above is the maximality rule biting, not an
    absence of evidence."""
    data = _a_wrong_seed_that_would_convict()
    axes = _axes(data.boards[0])

    convictions = _raw_ambiguous(
        1, axes, data.holes, (_half_turn(),), _raw_mm(_TOLERANCE)
    )

    assert [d.get("hole") for d in convictions] == [6]


def test_ambiguity_under_any_surviving_candidate_convicts_not_just_the_first() -> None:
    """Two parts within one tolerance of one hole stand closer together than
    the grid pitch, so the pathology is in the input rather than in whichever
    equally-good seating happens to reveal it. The clean registration is
    offered first here, so a check that stopped at the first says nothing."""
    data = _a_wrong_seed_that_would_convict()
    axes = _axes(data.boards[0])
    clean = _raw_placement(
        _raw_candidates(axes, data.holes, _TOLERANCE)[0],
        axes,
        {c.designator: c for c in data.boards[0].components},
    )[1]

    convictions = _raw_ambiguous(
        1, axes, data.holes, (clean, _half_turn()), _raw_mm(_TOLERANCE)
    )

    assert [d.get("hole") for d in convictions] == [6]


# --------------------------------------------------------------------------
# Candidates: identity, deduplication, and the anchor a transform comes from
# --------------------------------------------------------------------------


def test_every_seed_reaching_one_correspondence_set_is_one_candidate() -> None:
    """Three corresponded parts give three seed pairs in each of two hole
    orderings; the set they all reach must appear once."""
    board, holes = _three_parts()

    candidates = _raw_candidates(_axes(board), holes, _TOLERANCE)
    whole = [c for c in candidates if len(c) == 3]

    assert len(whole) == 1


def test_two_registrations_reaching_different_sets_stay_two_candidates() -> None:
    """The control: deduplication is on the set, so a fixture with two real
    registrations must not collapse to one. Two parts alone are carried onto
    their own two holes by a half turn as well as by the registration they
    were stated from."""
    board = _board((_D1, _D2))
    holes = (_hole(1, _D1), _hole(2, _D2))

    candidates = _raw_candidates(_axes(board), holes, _TOLERANCE)

    assert {tuple(sorted((d, h.index) for d, h in c)) for c in candidates} == {
        (("D1", 1), ("D2", 2)),
        (("D1", 2), ("D2", 1)),
    }


def test_two_equally_good_seatings_are_both_returned_and_reported() -> None:
    """Nothing chooses between them. A symmetric hole pattern genuinely
    admits both, ranking them is ``Seat``'s and ``Clashes``' job, and handing
    back one silently is how a pedal gets assembled mirror-imaged --
    ``ambiguous-placement`` is what tells the operator there is a choice."""
    board = _board((_D1, _D2))
    holes = (_hole(1, _D1), _hole(2, _D2))

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert {frozenset(_paired(p)) for p in data.placements[1]} == {
        frozenset({("D1", 1), ("D2", 2)}),
        frozenset({("D1", 2), ("D2", 1)}),
    }
    (found,) = [d for d in data.diagnostics if d.code == "ambiguous-placement"]
    assert found.severity == Severity.WARNING
    assert found.data == (("board", 1), ("placements", 2))


def test_one_registration_alone_earns_no_ambiguity_finding() -> None:
    """The control: three parts fix a unique seating, so the finding above is
    about there being a choice and not about a board having a placement."""
    board, holes = _three_parts()

    data = Match(_TOLERANCE).apply(_dock(board, holes))

    assert len(data.placements[1]) == 1
    assert "ambiguous-placement" not in _codes(data)


def test_the_result_survives_the_input_being_stated_in_another_order() -> None:
    """ADR-0006: two inputs representing one geometry agree, whatever their
    element order. Both the components and the holes are reversed here, and
    the fixture asserts they really were."""
    board, holes = _three_parts()
    turned = replace(board, components=tuple(reversed(board.components)))
    assert turned.components != board.components
    assert tuple(reversed(holes)) != holes

    first = Match(_TOLERANCE).apply(_dock(board, holes))
    second = Match(_TOLERANCE).apply(_dock(turned, tuple(reversed(holes))))

    assert first.placements[1] == second.placements[1]
    assert first.diagnostics == second.diagnostics


def _widest_pair_is_not_the_first_pair() -> DockData:
    """``D1``-``D3`` are 20 mm apart and fit exactly; ``D2`` is 0.05 mm out.

    Designator-sorted pairs run ``(D1,D2)`` at 11.18 mm, ``(D1,D3)`` at
    20 mm, ``(D2,D3)`` at 18.03 mm, so the widest pair is neither the first
    nor the last -- and anchoring on either of the others reports an angle
    the fixture's own registration does not have.
    """
    near = _Part("D2", 10.0, 5.0)
    tall = _Part("D3", 0.0, 20.0)
    board = _board((_D1, near, tall))
    holes = (_hole(3, tall), _hole(1, _D1), _hole(2, near, miss_mm=(0.05, 0.0)))
    return _dock(board, holes)


def test_the_reported_transform_comes_from_the_widest_corresponded_pair() -> None:
    """The best-conditioned anchor available, and the only choice that makes
    the reported motion independent of which seed found the set."""
    data = Match(_TOLERANCE).apply(_widest_pair_is_not_the_first_pair())

    (placement,) = data.placements[1]
    assert len(placement.correspondence) == 3
    assert placement.x_nm == pytest.approx(nm_from_mm(_REGISTRATION.x_mm), abs=100)
    assert placement.y_nm == pytest.approx(nm_from_mm(_REGISTRATION.y_mm), abs=100)
    # A quarter of a degree is what anchoring on either narrower pair would
    # report here, so this bound is four thousand times tighter than the
    # error it has to see.
    assert placement.theta_deg % 360.0 == pytest.approx(_REGISTRATION.theta_deg, abs=1e-4)


# --------------------------------------------------------------------------
# Match's own contract beyond the algorithm: the Stage protocol
# --------------------------------------------------------------------------


def test_match_satisfies_the_stage_protocol() -> None:
    """Runtime presence check, mirroring stompdrill's own
    ``test_every_stage_satisfies_the_stage_protocol``."""
    stage = Match(_TOLERANCE)
    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str)
    assert type(stage).name


def test_match_satisfies_stage_dockdata_under_mypy() -> None:
    """A static conformance assignment: ``isinstance`` alone cannot see that
    ``describe()`` returns a ``StageRun`` rather than a ``str`` -- a runtime
    Protocol checks attribute presence, not signatures. mypy checks this
    line; nothing here needs to run for the check to matter."""
    _conforms: Stage[DockData] = Match(_TOLERANCE)
    assert _conforms is not None


def test_describe_returns_a_stage_run_naming_the_tolerance() -> None:
    """The one thing this stage is configured with, and the only number a
    reader can check a registration against."""
    assert Match(_TOLERANCE).describe() == StageRun(
        "match", (("tolerance_nm", 1_270_000),)
    )


def test_apply_alone_records_no_processing() -> None:
    """A stage records nothing about itself -- ``Pipeline.run`` appends
    ``describe()`` only after ``apply`` returns, per
    ``stompmodel.protocols.Pipeline.run``. A bare ``apply()`` call, as every
    test above makes, must not have silently duplicated that bookkeeping."""
    board, holes = _three_parts()
    data = Match(_TOLERANCE).apply(_dock(board, holes))
    assert data.processing == ()


def test_pipeline_run_records_matchs_stage_run() -> None:
    board, holes = _three_parts()
    data = Pipeline([Match(_TOLERANCE)]).run(_dock(board, holes))
    assert [run.name for run in data.processing] == ["match"]


# --------------------------------------------------------------------------
# Fit: the seating each pairing implies, and an exact fit
# --------------------------------------------------------------------------


def _stepped_board(radius_nm: int) -> Board:
    """The three parts, each a shaft of ``radius_nm`` from 4 mm down the tip.

    One profile for all three, so the fit rules below are read off the
    hole's diameter rather than off which part it was.
    """
    profile = Profile(((Nanometre(radius_nm), Nanometre(4_000_000), Nanometre(9_000_000)),))
    components = tuple(
        Component(
            part.designator,
            Protrusion(
                part.designator,
                (nm_from_mm(part.x_mm), nm_from_mm(part.y_mm)),
                profile,
                _TIP,
            ),
        )
        for part in (_D1, _D2, _D3)
    )
    designators = tuple(sorted(c.designator for c in components))
    return Board(1, designators, _extent(), _identity_frame(), components)


def _fitted(radius_nm: int) -> DockData:
    board = _stepped_board(radius_nm)
    holes = (_hole(2, _D3), _hole(3, _D1), _hole(1, _D2))
    return Match(_TOLERANCE).apply(_dock(board, holes))


def test_a_part_wider_than_its_hole_states_the_depth_it_reaches() -> None:
    """The hole's own radius exactly, with nothing added to it: through a
    3 mm hole a 1.505 mm shaft is 5 microns proud on radius and is arrested
    where its shoulder begins, while a 1.495 mm one passes fully.

    A reported measurement, not a seat: where the board really comes to rest
    is what the insertion search finds against the drilled plate.
    """
    proud = _fitted(1_505_000).placements[1][0]
    clear = _fitted(1_495_000).placements[1][0]

    assert {c.insertion_nm for c in proud.correspondence} == {Nanometre(4_000_000)}
    assert {c.insertion_nm for c in clear.correspondence} == {None}


def test_each_pairing_states_the_seating_its_own_insertion_implies() -> None:
    """The insertion is measured from the part's tip and a placement's ``z``
    from the board's own origin plane, so the travel is the one less the
    other: negative, into the cavity. A seating equal to the insertion, or
    to its negation, means the tip was never subtracted."""
    placement = _fitted(1_505_000).placements[1][0]

    assert {c.seat_nm for c in placement.correspondence} == {
        Nanometre(4_000_000 - _TIP)
    }


def test_a_part_exactly_as_wide_as_its_hole_is_reported_as_zero_clearance() -> None:
    """It passes -- comparison is strict -- and it is worth seeing, so it is
    an INFO finding naming the part and the hole rather than silence. The
    control is beside it: a shaft five microns narrower fits with room to
    spare and earns nothing."""
    exact = _fitted(1_500_000)
    clear = _fitted(1_495_000)

    findings = [d for d in exact.diagnostics if d.code == "zero-clearance"]
    assert {d.severity for d in findings} == {Severity.INFO}
    assert {(d.get("designator"), d.get("hole")) for d in findings} == {
        ("D1", 3), ("D2", 1), ("D3", 2)
    }
    assert [d for d in clear.diagnostics if d.code == "zero-clearance"] == []


def test_an_exact_fit_is_the_hole_radius_and_nothing_within_a_hair_of_it() -> None:
    """``zero-clearance`` is exact equality of whole nanometres: a shaft
    fifty microns wider than half the hole's diameter is not it, and neither
    is one fifty microns narrower."""
    assert [
        d for d in _fitted(1_550_000).diagnostics if d.code == "zero-clearance"
    ] == []
    assert [
        d for d in _fitted(1_450_000).diagnostics if d.code == "zero-clearance"
    ] == []
