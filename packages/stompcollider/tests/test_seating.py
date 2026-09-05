"""Seating a real board: how deep the tar boards come to rest, and why there.

The path a run actually takes -- ``substrates``, ``group``, the board
reader, ``canonicalise``, ``Match``, ``Seat`` -- against the committed
fixture and the tar panel's own holes. ``Match`` and ``Seat`` are pure and
have their own unit tests; those were green while every real board still
came to rest flush against the panel, because no hand-built profile ever
stated a part's whole radial extent. Set up by ``tests.tar``, which
``test_registration`` shares.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from stompcollider.match import Match
from stompcollider.model import DockData
from stompcollider.seat import Seat
from stompmodel.model import Hole
from stompmodel.units import Nanometre, nm_from_mm
from tests import tar

#: What each board's own profile states, measured against each hole's own
#: radius with nothing added to it. Neither is where the board rests -- the
#: insertion search against the supplied enclosure fixes that -- and neither
#: is the standoff the operator's own assembly has, which stands the two
#: boards 10.000 and 17.000 mm below the drilled face. Written down because
#: they are the numbers the probe radius and the tip subtraction produce, so
#: a change to either moves one of them.
RV_PROFILE_NM = Nanometre(-15_816_266)
SW_PROFILE_NM = Nanometre(-16_892_748)


def _seated(dock: DockData) -> tuple[DockData, dict[str, Nanometre]]:
    """Both boards matched and seated, with each board's own depth beside it."""
    data = Seat().apply(Match(tar.TOLERANCE).apply(dock))
    depths = {
        "RV": tar.seating(
            data, tar.carrying(data.boards, "RV1"), tar.RV_CORRESPONDENCE
        ).z_nm,
        "SW": tar.seating(
            data, tar.carrying(data.boards, "SW1"), tar.SW_CORRESPONDENCE
        ).z_nm,
    }
    return data, depths


@pytest.mark.boards
def test_each_board_seats_into_the_cavity_rather_than_flush_with_the_face(
    tar_dock: DockData,
) -> None:
    """Both boards come to rest below the drilled face, and not at it.

    ``z = 0`` is the board's own origin plane lying in the drilled face --
    every component driven through a hole far too small to admit it. That
    is what a profile built from coaxial cylinders alone produced for both
    of these boards, so a strictly negative depth is the whole claim.
    """
    _data, depths = _seated(tar_dock)

    assert depths["RV"] < 0
    assert depths["SW"] < 0


@pytest.mark.boards
def test_the_switch_board_seats_deeper_than_the_board_carrying_the_pots(
    tar_dock: DockData,
) -> None:
    """Depth is each board's own fact, so two boards are coplanar by coincidence.

    A 3PDT body is the larger obstruction, so the switch board must come to
    rest further into the cavity than the pot column. Two boards seated by
    one shared depth -- the flush answer among them -- pass every other
    claim here and fail this one.
    """
    _data, depths = _seated(tar_dock)

    assert depths["SW"] < depths["RV"]


@pytest.mark.boards
def test_the_profile_alone_states_neither_boards_standoff(
    tar_dock: DockData,
) -> None:
    """What the hole geometry says here, and why it is reported not obeyed.

    The pot bushing measures 27 microns too fat for its ⌀7.000 hole and so
    binds at the plate; the 3PDT bush is exactly as wide as its ⌀12.000
    bore, so the radial cut states the material just past that radius, at
    16.893 mm. Against an assembly standing these boards 10 and 17 mm below
    the face, neither figure is the standoff, which is exactly why the
    enclosure and not the profile fixes the depth. No cavity is supplied
    here, so these are the profile's own answers.
    """
    _data, depths = _seated(tar_dock)

    assert depths["RV"] == RV_PROFILE_NM
    assert depths["SW"] == SW_PROFILE_NM


@pytest.mark.boards
def test_every_pairing_of_a_seated_board_states_the_depth_it_inserts_to(
    tar_dock: DockData,
) -> None:
    """The control for the depths above: they rest on measured insertions.

    A placement whose correspondences all report an unbounded insertion
    seats at zero, which is exactly the defect; one where a single pairing
    happens to be bounded would still seat somewhere plausible. This states
    that every one of the six pairings carries a depth of its own.
    """
    data, _depths = _seated(tar_dock)
    insertions = [
        correspondence.insertion_nm
        for board in data.boards
        for placement in data.placements.get(board.ordinal, ())
        for correspondence in placement.correspondence
    ]

    assert insertions
    assert all(insertion is not None for insertion in insertions)


@pytest.mark.boards
def test_a_hole_wide_enough_to_swallow_the_part_seats_the_board_flush(
    tar_dock: DockData,
) -> None:
    """The deliberate breach: nothing arrests, so the depth claims above fail.

    The same boards, the same registration, the same stages -- only the
    holes are drilled wide enough to pass a whole potentiometer body and a
    whole footswitch. Every insertion is then unbounded, both boards seat at
    ``z = 0``, and the three assertions above would be reading a constant.
    """
    swallowing = tuple(
        Hole.from_measurement(hole.x_nm, hole.y_nm, nm_from_mm(30.0)).with_number(
            hole.index
        )
        for hole in tar_dock.holes
        if hole.index is not None
    )

    _data, depths = _seated(replace(tar_dock, holes=swallowing))

    assert depths["RV"] == 0
    assert depths["SW"] == 0


@pytest.mark.boards
def test_a_bush_exactly_as_wide_as_its_hole_is_reported_rather_than_refused(
    tar_dock: DockData,
) -> None:
    """``zero-clearance``: the 3PDT bush measures 12.000 mm into a 12.000 mm hole.

    It passes -- comparison is strict -- and it is worth seeing, so it is an
    INFO finding rather than silence. The potentiometers are the control
    beside it: their bushings measure 7.054 mm across a 7.000 mm hole, so
    they are proud of it rather than exactly as wide, and earn nothing.
    """
    data, _depths = _seated(tar_dock)

    exact = [d for d in data.diagnostics if d.code == "zero-clearance"]
    assert {d.get("designator") for d in exact} == {"SW1", "SW2"}
