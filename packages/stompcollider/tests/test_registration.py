"""Registering a real board into the panel frame, before ``Match`` pairs it.

``Match`` pairs by absolute proximity, but a board's axes reach it in the
board file's own frame, so nothing has put its parts near the holes. The
suite never saw it: ``Match`` ran only on hand-built ``DockData`` whose
parts sat on their holes already, and the files reading the committed
fixture never run it. Here that fixture's own geometry goes through the real
path, set up by ``tests.tar`` so that ``test_seating`` reasons about the
same panel.
"""

from __future__ import annotations

import pytest

from stompcollider.match import Match
from stompcollider.model import DockData
from tests import tar


@pytest.mark.boards
def test_the_filter_admits_the_panel_references_it_names(tar_dock: DockData) -> None:
    """The control for the test below, which claims two parts pair with nothing.

    A part the expression withheld also pairs with nothing, so without this
    the diodes' absence from the correspondences would be evidence about the
    filter rather than about the distance. It states positively that the two
    diodes reach ``Match`` with an axis, that the fifth pot does not, and
    that every admitted part was measured one -- the reader finding no
    cylinder would empty the pairing just as quietly.
    """
    admitted = {
        component.designator
        for board in tar_dock.boards
        for component in board.components
        if component.protrusion is not None
    }

    assert admitted == tar.ADMITTED


@pytest.mark.boards
def test_both_boards_register_onto_the_holes_they_were_drilled_for(
    tar_dock: DockData,
) -> None:
    """Real axes, real holes: each board seats on the holes its parts pass through.

    The pot column turns a quarter turn and drops 10.25 mm, the switch board
    the same turn and rises as far, and every one of those six pairings is an
    exact hit -- a recognition that merely came within tolerance would be a
    weaker claim than the geometry supports. The two diodes sit 0.495 mm from
    holes 1 and 2, four times the tolerance, so they pair with nothing.
    """
    matched = Match(tar.TOLERANCE).apply(tar_dock)
    rv = tar.carrying(matched.boards, "RV1")
    sw = tar.carrying(matched.boards, "SW1")

    for board, expected, seated in (
        (rv, tar.RV_CORRESPONDENCE, tar.RV_SEATING),
        (sw, tar.SW_CORRESPONDENCE, tar.SW_SEATING),
    ):
        placement = tar.seating(matched, board, expected)
        assert board.panel_face == "+w"
        assert [c.offset_nm for c in placement.correspondence] == [0] * len(expected)
        assert (placement.x_nm, placement.y_nm) == seated
        assert placement.theta_deg == pytest.approx(tar.THETA_DEG, abs=1e-9)


@pytest.mark.boards
def test_the_second_seating_of_each_board_is_reported_rather_than_dropped(
    tar_dock: DockData,
) -> None:
    """The ambiguity above is stated, not left for a reader to notice.

    Both boards are symmetric enough that a second rigid motion puts as many
    parts through holes as the first, so each earns ``ambiguous-placement``
    -- and the two indicator diodes, loose under both seatings, are named
    once each with the smaller of the two misses they suffer.
    """
    matched = Match(tar.TOLERANCE).apply(tar_dock)

    ambiguous = [d for d in matched.diagnostics if d.code == "ambiguous-placement"]
    assert [d.get("placements") for d in ambiguous] == [2, 2]
    loose = [d for d in matched.diagnostics if d.code == "unmatched-part"]
    assert {(d.get("designator"), d.get("offset_nm")) for d in loose} == {
        ("D3", 495_000),
        ("D4", 495_000),
    }
