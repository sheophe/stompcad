"""Match: which face points at the panel, and which placements survive.

Fixtures are hand-built, per ``stompcollider-technical.md``'s "Match" and
"Candidates": no kernel, no fixture file. Positions are chosen to avoid
every vacuity hazard the task names -- see the module-level comment above
each fixture group for which hazard it targets.
"""

from __future__ import annotations

from stompcollider.match import Match
from stompcollider.match import _candidates as _raw_candidates
from stompcollider.model import (
    Board,
    Component,
    Correspondence,
    DockData,
    Profile,
    Protrusion,
)
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, Hole
from stompmodel.units import Nanometre, nm_from_mm

_TOLERANCE = Nanometre(1_270_000)  # half a 2.54 mm grid pitch


# --------------------------------------------------------------------------
# Shared builders
# --------------------------------------------------------------------------


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


def _profile() -> Profile:
    """Radius well under any hole radius used here, so every part passes
    fully (``insertion_nm`` is ``None``) -- rule 2 means Match never has to
    resolve fit, so no fixture below relies on a particular fit outcome."""
    return Profile(((Nanometre(1_000_000), Nanometre(0), Nanometre(5_000_000)),))


def _part(designator: str, x_nm: int, y_nm: int) -> Component:
    return Component(designator, Protrusion(designator, (Nanometre(x_nm), Nanometre(y_nm)), _profile()))


def _hole(index: int, x_nm: int, y_nm: int, diameter_nm: int = 3_000_000) -> Hole:
    return Hole.from_measurement(
        Nanometre(x_nm), Nanometre(y_nm), Nanometre(diameter_nm)
    ).with_number(index)


def _board(components: tuple[Component, ...], ordinal: int = 1) -> Board:
    designators = tuple(c.designator for c in components)
    return Board(ordinal, designators, _extent(), _identity_frame(), components)


# --------------------------------------------------------------------------
# Rule 1: pairing is a predicate, not a score.
#
# ``_board_pairing`` gives "front" parts a hole only when their axis is
# flipped (negated y) and "back" parts a hole only when read as exported --
# so counting which face wins is the only way either group can be
# recognised at all. Front and back holes sit far apart in x (a 1 m offset)
# so neither group's positions can be mistaken for the other's, and
# components/holes are stored reversed, not in designator/index order, per
# the repository's fixture rule.
# --------------------------------------------------------------------------

_ROW_NM = 5_000_000  # 5 mm
_SPACING_NM = 10_000_000  # 10 mm
_BACK_OFFSET_NM = 1_000_000_000  # 1 m


def _board_pairing(front: int, back: int) -> DockData:
    parts: list[Component] = []
    hole_list: list[Hole] = []
    index = 1
    for i in range(front):
        x = i * _SPACING_NM
        parts.append(_part(f"F{i + 1}", x, -_ROW_NM))
        hole_list.append(_hole(index, x, _ROW_NM))
        index += 1
    for j in range(back):
        x = _BACK_OFFSET_NM + j * _SPACING_NM
        parts.append(_part(f"B{j + 1}", x, _ROW_NM))
        hole_list.append(_hole(index, x, _ROW_NM))
        index += 1
    if not parts:
        # Board() needs at least one designator; this one matches nothing.
        parts.append(_part("D1", 999_000_000, 999_000_000))
    components = tuple(reversed(parts))
    holes = tuple(reversed(hole_list))
    return DockData(case=_case(), boards=(_board(components),), holes=holes)


def test_the_face_with_strictly_more_pairings_is_chosen() -> None:
    data = Match(_TOLERANCE).apply(_board_pairing(front=3, back=1))
    assert data.boards[0].panel_face == "-w"


def test_the_face_read_as_exported_can_also_win() -> None:
    """The predicate is symmetric: winning is about the count, not about
    which hypothesis (as-exported or flipped) happens to be tried first."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=1, back=3))
    assert data.boards[0].panel_face == "+w"


def test_equal_non_zero_pairings_on_both_faces_is_an_error() -> None:
    """Not broken by a majority, a fallback, or a preference for the front."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=2, back=2))
    assert [d.code for d in data.diagnostics] == ["both-faced-group"]


def test_zero_pairings_on_both_faces_is_a_different_error() -> None:
    """Distinct code: a wrong board and an undeclared side are different faults."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=0, back=0))
    assert [d.code for d in data.diagnostics] == ["no-correspondence"]


def test_fewer_than_two_correspondences_is_under_constrained() -> None:
    """One leaves the board free to turn about that point. Two is the rank of
    a rigid planar transform, not a threshold."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=1, back=0))
    assert "under-constrained-board" in {d.code for d in data.diagnostics}


# --------------------------------------------------------------------------
# Rule 1's third case: ambiguous pairing on the hole side.
# --------------------------------------------------------------------------


def _two_parts_one_hole() -> DockData:
    hole = _hole(1, 0, 0)
    c1 = _part("D1", 0, 0)
    c2 = _part("D2", 200_000, 0)  # 0.2 mm away: within tolerance of the same hole
    board = _board((c2, c1))
    return DockData(case=_case(), boards=(board,), holes=(hole,))


def test_two_protrusions_within_tolerance_of_one_hole_is_ambiguous() -> None:
    """Two parts cannot occupy one hole, and choosing between them would be
    the weighting the pre-spec refuses."""
    data = Match(_TOLERANCE).apply(_two_parts_one_hole())
    assert [d.code for d in data.diagnostics] == ["ambiguous-pairing"]


# --------------------------------------------------------------------------
# Rule 3 and 4: candidate generation, tested directly against
# ``stompcollider.match._candidates``.
#
# Recognition tolerance bounds any *single* part's offset from its own hole
# to <= tolerance (rule 2's gate, exercised above through ``Match.apply``).
# Every scenario below needs correspondences whose combined geometry a
# single-tolerance pairing gate could never produce on its own -- a 2.4 mm
# gap disagreement between two independently-recognised parts, a genuine
# mirror image, or a seed pair 100 mm from another that a real board could
# never confuse with it. Testing ``_candidates`` directly is what lets each
# of those scenarios be built without first satisfying a gate the rule under
# test does not govern. This is a deliberate, documented departure from the
# brief's literal ``Match(...).apply(...)`` wiring for these three cases --
# see the task report for the proof that the full pipeline cannot reach them.
# --------------------------------------------------------------------------


def _candidates(part_gap_mm: float, hole_gap_mm: float) -> int:
    axes = {
        "D1": (Nanometre(0), Nanometre(0)),
        "D2": (nm_from_mm(part_gap_mm), Nanometre(0)),
    }
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (nm_from_mm(hole_gap_mm), Nanometre(0)), None, Nanometre(0)),
    )
    return len(_raw_candidates(correspondences, axes, _TOLERANCE))


def test_a_pair_whose_separations_disagree_seeds_no_candidate() -> None:
    """|p1p2| must equal |h1h2| within TWICE the tolerance -- two independent
    recognition errors, not one."""
    assert _candidates(part_gap_mm=20.0, hole_gap_mm=20.0 + 3.0) == 0
    assert _candidates(part_gap_mm=20.0, hole_gap_mm=20.0 + 2.4) == 1


def _mirrored_layout() -> tuple[tuple[Correspondence, ...], dict[str, tuple[Nanometre, Nanometre]]]:
    """An L: two legs at right angles, reflected across one leg.

    ``D1``/``D2`` sit on the true leg (parts and holes agree exactly);
    ``D3`` is the reflected tip -- every candidate a rigid (non-reflective)
    fit could offer for ``D1``, ``D2`` places ``D3`` on the *other* side of
    that leg from where its hole actually is.
    """
    axes = {
        "D1": (Nanometre(0), Nanometre(0)),
        "D2": (Nanometre(10_000_000), Nanometre(0)),
        "D3": (Nanometre(0), Nanometre(-10_000_000)),
    }
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (Nanometre(10_000_000), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D3", 3, (Nanometre(0), Nanometre(10_000_000)), None, Nanometre(0)),
    )
    return correspondences, axes


def _candidates_from(
    scenario: tuple[tuple[Correspondence, ...], dict[str, tuple[Nanometre, Nanometre]]]
) -> int:
    correspondences, axes = scenario
    return len(_raw_candidates(correspondences, axes, _TOLERANCE))


def test_a_transform_fitting_only_under_reflection_is_rejected() -> None:
    """A board cannot be mirrored in its own plane."""
    assert _candidates_from(_mirrored_layout()) == 0


def _three_collinear_parts() -> DockData:
    """Three parts, unevenly spaced along one line, exactly matching three
    holes only once the board is read from its flipped face."""
    parts = (
        _part("D3", 30_000_000, -_ROW_NM),
        _part("D1", 0, -_ROW_NM),
        _part("D2", 10_000_000, -_ROW_NM),
    )
    holes = (
        _hole(3, 30_000_000, _ROW_NM),
        _hole(1, 0, _ROW_NM),
        _hole(2, 10_000_000, _ROW_NM),
    )
    return DockData(case=_case(), boards=(_board(parts),), holes=holes)


def test_two_seed_pairs_validating_one_set_are_one_candidate() -> None:
    """The deduplication is on the SET, exactly and discretely. Three
    corresponded parts give three seed pairs and must give one placement."""
    data = Match(_TOLERANCE).apply(_three_collinear_parts())
    assert len(data.placements[1]) == 1
    assert len(data.placements[1][0].correspondence) == 3


def _two_fold_symmetric_board() -> tuple[
    tuple[Correspondence, ...], dict[str, tuple[Nanometre, Nanometre]]
]:
    """Two independent, exactly-fitting pairs 100 mm apart: one fits as
    measured (0 degrees), the other only once turned end for end (180
    degrees) -- the genuinely correct, order-free answer for a symmetric
    hole pattern is both, not whichever a caller happens to try first."""
    axes = {
        "D1": (Nanometre(0), Nanometre(0)),
        "D2": (Nanometre(10_000_000), Nanometre(0)),
        "D3": (Nanometre(100_000_000), Nanometre(0)),
        "D4": (Nanometre(110_000_000), Nanometre(0)),
    }
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (Nanometre(10_000_000), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D3", 3, (Nanometre(110_000_000), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D4", 4, (Nanometre(100_000_000), Nanometre(0)), None, Nanometre(0)),
    )
    return correspondences, axes


def test_a_symmetric_pattern_returns_both_placements() -> None:
    """Every distinct placement is returned. Handing back one silently is how
    a pedal gets assembled mirror-imaged."""
    correspondences, axes = _two_fold_symmetric_board()
    placements = _raw_candidates(correspondences, axes, _TOLERANCE)
    assert len(placements) == 2
    assert {round(p.theta_deg, 6) for p in placements} == {0.0, 180.0}


# --------------------------------------------------------------------------
# Vacuity hazard 2 and rule 4: with only two correspondences, "the two most
# widely separated" is indistinguishable from "the first two" or "the last
# two". This needs three, with the widest pair -- D1,D3 -- in the *middle*
# of designator-sorted ``combinations`` order (D1,D2 first; D2,D3 last), and
# a deliberate inconsistency at D2 so an anchor choice is observable: seeding
# from D1,D3 (the true widest pair) reports the identity transform: from
# D1,D2 or D2,D3 -- either "wrong" anchor -- it would not.
# --------------------------------------------------------------------------


def _widest_pair_is_not_first_two() -> tuple[
    tuple[Correspondence, ...], dict[str, tuple[Nanometre, Nanometre]]
]:
    axes = {
        "D1": (Nanometre(0), Nanometre(0)),
        "D2": (Nanometre(1_000_000), Nanometre(500_000)),
        "D3": (Nanometre(0), Nanometre(20_000_000)),
    }
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (Nanometre(1_300_000), Nanometre(500_000)), None, Nanometre(300_000)),
        Correspondence("D3", 3, (Nanometre(0), Nanometre(20_000_000)), None, Nanometre(0)),
    )
    return correspondences, axes


def test_the_reported_transform_uses_the_widest_corresponded_pair() -> None:
    correspondences, axes = _widest_pair_is_not_first_two()
    placements = _raw_candidates(correspondences, axes, _TOLERANCE)
    full = [p for p in placements if len(p.correspondence) == 3]
    assert len(full) == 1
    # D1-D3 (20 mm apart) is the widest pair and fits exactly (0, 0, 0 deg).
    # D1-D2 or D2-D3 (~1.1-19.5 mm) would report a different, nonzero angle.
    assert full[0].x_nm == Nanometre(0)
    assert full[0].y_nm == Nanometre(0)
    assert round(full[0].theta_deg, 6) == 0.0


# --------------------------------------------------------------------------
# Vacuity hazard 4: two genuinely different seed pairs reaching the same set.
# All three of D1, D2, D3 fit one consistent transform exactly, so seeding
# from (D1,D2), (D1,D3) or (D2,D3) must each reach the identical set -- the
# case ``test_two_seed_pairs_validating_one_set_are_one_candidate`` already
# covers through the full pipeline; this is the same claim, isolated.
# --------------------------------------------------------------------------


def test_deduplication_collapses_every_seed_reaching_the_same_set() -> None:
    axes = {
        "D1": (Nanometre(0), Nanometre(0)),
        "D2": (Nanometre(10_000_000), Nanometre(0)),
        "D3": (Nanometre(30_000_000), Nanometre(0)),
    }
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (Nanometre(10_000_000), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D3", 3, (Nanometre(30_000_000), Nanometre(0)), None, Nanometre(0)),
    )
    placements = _raw_candidates(correspondences, axes, _TOLERANCE)
    assert len(placements) == 1
    assert len(placements[0].correspondence) == 3


# --------------------------------------------------------------------------
# Match's own contract beyond the four rules: describe() and StageRun.
# --------------------------------------------------------------------------


def test_describe_names_the_tolerance() -> None:
    assert "1270000" in Match(_TOLERANCE).describe()


def test_apply_records_a_stage_run() -> None:
    data = Match(_TOLERANCE).apply(_board_pairing(front=1, back=1))
    assert [run.name for run in data.processing] == ["match"]


def test_a_component_with_no_protrusion_is_simply_not_a_candidate() -> None:
    """``unmatched-part`` territory: a component the filter admitted but
    which never yielded an axis takes no part in pairing, on either face."""
    data = _board_pairing(front=3, back=1)
    board = data.boards[0]
    bare = Board(
        board.ordinal,
        board.designators + ("D9",),
        board.extent_nm,
        board.carrier,
        board.components + (Component("D9", None),),
    )
    data = DockData(case=data.case, boards=(bare,), holes=data.holes)
    result = Match(_TOLERANCE).apply(data)
    assert result.boards[0].panel_face == "-w"


def test_a_seed_pair_at_one_position_seeds_no_transform() -> None:
    """Two corresponded protrusions that coincide fix no angle -- the
    degenerate case ``_transform`` reports as ``None`` rather than dividing
    by a zero-length separation. Holes close enough together (0.5 mm, under
    twice tolerance) that the gap-agreement gate does not reject the seed
    before ``_transform`` is even reached."""
    correspondences = (
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), None, Nanometre(0)),
        Correspondence("D2", 2, (Nanometre(500_000), Nanometre(0)), None, Nanometre(0)),
    )
    axes = {
        "D1": (Nanometre(5_000_000), Nanometre(5_000_000)),
        "D2": (Nanometre(5_000_000), Nanometre(5_000_000)),  # coincides with D1
    }
    assert _raw_candidates(correspondences, axes, _TOLERANCE) == ()
