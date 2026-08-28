"""Clashes: what overlaps, by how much, against what, and what merely touches.

Kernel-backed but synthetic: the solids are built through OCP directly
because that is what a fixture is, while the package's own source reaches
the kernel only through ``stompgeom`` -- ``test_package_boundary.py`` is
what enforces that. Every scene here carries more than one board and more
than one case solid, and no common region is a cube, so an implementation
that checked only the first pair, or read the first axis rather than the
least, has somewhere to fail.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from stompcollider.clash import Clashes, placement_transform
from stompcollider.errors import StompcolliderError
from stompcollider.match import _apply
from stompcollider.model import Board, Clash, DockData, Placement
from stompcollider.seat import Seat, rank_key
from stompgeom.shapes import placed
from stompgeom.step import StepSolid, bounding_box_mm
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, StageRun
from stompmodel.protocols import Stage
from stompmodel.units import Nanometre, nm_from_mm

# --------------------------------------------------------------------------
# Kernel solids. Nothing here is a cube, and nothing is centred on the
# origin by accident: hazard 2 is that a cubical common region leaves
# "least extent" and "first axis" indistinguishable.
# --------------------------------------------------------------------------


def _box(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
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
    """A 40 x 40 x 3 plate bored through its centre -- a panel with one hole."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    return BRepAlgoAPI_Cut(
        _box((0.0, 0.0, 0.0), 40.0, 40.0, 3.0), _cylinder((20.0, 20.0, -5.0), radius, 13.0)
    ).Shape()


def _rectangle(at: tuple[float, float, float], dx: float, dy: float) -> Any:
    """A flat face: a region with no thickness at all, for the contact rule."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

    plane = gp_Pln(gp_Pnt(*at), gp_Dir(0.0, 0.0, 1.0))
    return BRepBuilderAPI_MakeFace(plane, 0.0, dx, 0.0, dy).Face()


def _solid(name: str, shape: Any) -> StepSolid:
    return StepSolid(name=name, shape=shape)


# --------------------------------------------------------------------------
# Pure values.
# --------------------------------------------------------------------------


def _nm(value: float) -> Nanometre:
    return nm_from_mm(value)


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _turned_frame() -> CoordinateFrame:
    """A face frame that is not the model frame: a quarter turn about ``w``."""
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(0.0, 1.0, 0.0),
        v=(-1.0, 0.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _case(frame: CoordinateFrame | None = None) -> CaseRegistration:
    return CaseRegistration(
        "1590BB", CaseFace.BOX, "case.stp", FaceFrame(frame or _identity_frame())
    )


def _board(
    ordinal: int = 1,
    carrier: CoordinateFrame | None = None,
    panel_face: str | None = "+w",
) -> Board:
    return Board(
        ordinal=ordinal,
        designators=(f"J{ordinal}",),
        extent_nm=(_nm(10.0), _nm(10.0), _nm(2.0)),
        carrier=carrier or _identity_frame(),
        components=(),
        panel_face=panel_face,
    )


def _placement(
    rank: int = 1,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    theta_deg: float = 0.0,
) -> Placement:
    return Placement(
        rank=rank,
        x_nm=_nm(x_mm),
        y_nm=_nm(y_mm),
        z_nm=_nm(z_mm),
        theta_deg=theta_deg,
        correspondence=(),
        clashes=(),
    )


def _dock(
    boards: tuple[Board, ...],
    placements: dict[int, tuple[Placement, ...]],
    frame: CoordinateFrame | None = None,
) -> DockData:
    return DockData(case=_case(frame), boards=boards, placements=placements)


# --------------------------------------------------------------------------
# One board against one case solid: the shape of a single clash.
# --------------------------------------------------------------------------


def _clashes_between(
    board_shape: Any, case_shape: Any, frame: CoordinateFrame | None = None
) -> tuple[Clash, ...]:
    """One board, one case solid, and a placement that moves neither.

    The board's carrier is the face frame itself, so ``placement_transform``
    is the identity here and the geometry is exactly what the fixture built.
    Which frame a clash is *stated* in is what varies.
    """
    board = _board(1, carrier=frame or _identity_frame())
    data = _dock((board,), {1: (_placement(),)}, frame=frame)
    stage = Clashes((_solid("CASE", case_shape),), {1: (_solid("", board_shape),)})
    return stage.apply(data).placements[1][0].clashes


def test_two_overlapping_solids_report_the_overlap() -> None:
    """The region itself, not either solid and not their union."""
    found = _clashes_between(
        _box((0, 0, 0), 10, 12, 14), _box((8, 0, 0), 10, 40, 40)
    )

    assert len(found) == 1
    assert found[0].bbox_nm == (
        _nm(8.0), _nm(0.0), _nm(0.0), _nm(10.0), _nm(12.0), _nm(14.0),
    )


def test_depth_is_the_least_extent_not_the_greatest() -> None:
    """The clause a ``max()`` implementation passes the test above and fails
    here: an overlap 2 mm deep and 14 mm wide is 2 mm of interference."""
    found = _clashes_between(
        _box((0, 0, 0), 10, 12, 14), _box((8, 0, 0), 10, 40, 40)
    )

    assert found[0].depth_nm == _nm(2.0)
    assert found[0].axis == "u"


def test_the_axis_is_the_axis_of_the_least_extent_when_that_is_not_the_first() -> None:
    """An implementation reading the first axis passes the test above. The
    region here is 14 x 2 x 10, so only reading the least extent's own axis
    answers ``v``."""
    found = _clashes_between(
        _box((0, 0, 0), 14, 10, 10), _box((0, 8, 0), 40, 10, 40)
    )

    assert found[0].depth_nm == _nm(2.0)
    assert found[0].axis == "v"


def test_the_axis_is_the_third_one_when_that_carries_the_least_extent() -> None:
    """And the third, so no axis is reachable only by an accident of order."""
    found = _clashes_between(
        _box((0, 0, 0), 14, 10, 10), _box((0, 0, 8), 40, 40, 10)
    )

    assert found[0].depth_nm == _nm(2.0)
    assert found[0].axis == "w"


def test_the_volume_is_the_bounding_box_volume_in_whole_nanometres() -> None:
    """``rank_key`` sums these, so the number is exact integer arithmetic on
    canonical lengths rather than a float the kernel measured."""
    found = _clashes_between(
        _box((0, 0, 0), 10, 12, 14), _box((8, 0, 0), 10, 40, 40)
    )

    assert found[0].volume_nm3 == 2_000_000 * 12_000_000 * 14_000_000


def test_the_bbox_is_stated_in_the_case_face_frame_not_in_model_coordinates() -> None:
    """One region, two frames. Under a quarter turn the same overlap reads
    along ``v``, so an implementation reading the kernel's own axes fails
    here while passing every test above."""
    found = _clashes_between(
        _box((0, 0, 0), 10, 12, 14), _box((8, 0, 0), 10, 40, 40), frame=_turned_frame()
    )

    assert found[0].bbox_nm == (
        _nm(0.0), _nm(-10.0), _nm(0.0), _nm(12.0), _nm(-8.0), _nm(14.0),
    )
    assert found[0].axis == "v"


# --------------------------------------------------------------------------
# Contact is not a clash, and needs no threshold.
# --------------------------------------------------------------------------


def test_solids_meeting_on_one_face_are_contact_not_a_clash() -> None:
    """Planar contact: they share a face and no region at all."""
    assert _clashes_between(_box((0, 0, 0), 10, 12, 14), _box((10, 0, 0), 10, 12, 14)) == ()


def test_a_shaft_exactly_filling_its_bore_is_contact_not_a_clash() -> None:
    """The named test the spec requires, not an assumption: a 12.000 shaft in
    a 12.000 bore. Curved contact rather than planar, which is the case a
    box-on-box fixture never reaches."""
    assert _clashes_between(_cylinder((20, 20, -10), 6.0, 20.0), _bored_plate(6.0)) == ()


def test_a_shaft_wider_than_its_bore_is_a_clash() -> None:
    """The innocent probe beside it. Without this, a contact rule that
    discarded everything would still pass both tests above. One micron of
    radial interference is 12.002 mm across and 3 mm through the plate."""
    found = _clashes_between(_cylinder((20, 20, -10), 6.001, 20.0), _bored_plate(6.0))

    assert found[0].depth_nm == _nm(3.0)
    assert found[0].axis == "w"


def test_a_one_nanometre_overlap_is_a_clash() -> None:
    """The resolution is the test, and this is the resolution: one whole
    nanometre survives the kernel's own boolean, so it is a fact and it is
    reported. Measured: the kernel answers ``None`` for every overlap below
    this, so no interference the canonical representation can express is
    lost between contact and here."""
    found = _clashes_between(
        _box((0, 0, 0), 10, 12, 14), _box((9.999999, 0, 0), 10, 12, 14)
    )

    assert found[0].depth_nm == Nanometre(1)


def test_a_region_with_no_thickness_is_contact_whatever_its_other_extents() -> None:
    """Zero-nanometre depth is contact. Stated over a region the kernel's
    solid-solid boolean does not currently produce -- it answers contact by
    returning nothing at all -- so the rule is carried here rather than left
    to rest on that. A 30 x 20 face is large in two axes and is still no
    interference.
    """
    found = _clashes_between(_rectangle((0, 0, 5), 30, 20), _box((0, 0, 0), 40, 40, 10))

    assert found == ()


# --------------------------------------------------------------------------
# The same claim on real geometry: the fixture the spec names.
# --------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"

#: Where ``tar-pcb.stp``'s two footswitch bushings sit, and the band of the
#: model their nominal 12.000 mm crest occupies. Read from the file, not
#: assumed: ``test_boards.py`` names the same two designators.
_SWITCH_AXES_MM = ((-35.0, -29.0), (35.0, -29.0))
_SWITCH_PLATE_Z_MM = -24.0


def _panel(bore_radius_mm: float) -> StepSolid:
    """A plate across both footswitch axes, bored to ``bore_radius_mm``."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    plate = _box((-60.0, -50.0, _SWITCH_PLATE_Z_MM), 120.0, 50.0, 3.0)
    for x_mm, y_mm in _SWITCH_AXES_MM:
        plate = BRepAlgoAPI_Cut(
            plate, _cylinder((x_mm, y_mm, _SWITCH_PLATE_Z_MM - 6.0), bore_radius_mm, 20.0)
        ).Shape()
    return _solid("PANEL", plate)


@lru_cache(maxsize=1)
def _switches() -> tuple[StepSolid, ...]:
    """Cached: the fixture is 9.6 MB and both tests below read the same two."""
    from stompgeom.step import read_step

    document = read_step(_FIXTURE)
    return tuple(solid for solid in document.solids if solid.name in {"SW1", "SW2"})


def _through(bore_radius_mm: float) -> tuple[Clash, ...]:
    data = _dock((_board(1),), {1: (_placement(),)})
    stage = Clashes((_panel(bore_radius_mm),), {1: _switches()})
    return stage.apply(data).placements[1][0].clashes


@pytest.mark.boards
def test_the_fixtures_own_switches_pass_a_nominal_bore_without_clashing() -> None:
    """The claim the spec requires be tested rather than assumed, on the
    geometry it names: ``tar-pcb.stp``'s two 12.000 mm footswitch bushings
    through 12.000 mm bores. Real threaded crests, not an ideal cylinder,
    and the exact boolean still answers contact."""
    assert _through(6.0) == ()


@pytest.mark.boards
def test_the_same_switches_in_an_undersize_bore_do_clash() -> None:
    """The innocent probe beside it, so the test above cannot pass by the
    stage finding nothing anywhere. A 0.1 mm undersize bore is a fact."""
    found = _through(5.9)

    assert found[0].with_ == "PANEL"
    assert found[0].kind == "case"
    assert found[0].depth_nm > Nanometre(0)


# --------------------------------------------------------------------------
# Rule 1: the whole of the rest of the assembly.
# --------------------------------------------------------------------------


def _enclosure() -> tuple[StepSolid, ...]:
    """Four named case solids, listed so no one of them is the first or last
    thing a board meets."""
    return (
        _solid("FLOOR", _box((-50, -50, -30), 100, 100, 3)),
        _solid("WALL", _box((20, -50, -30), 4, 100, 40)),
        _solid("LID", _box((-50, -50, 8), 100, 100, 3)),
        _solid("BOSS", _box((-40, -40, -27), 6, 6, 30)),
    )


def _reaching_board() -> tuple[StepSolid, ...]:
    """A board that reaches into WALL by 1 mm and up into LID by 2 mm."""
    return (_solid("", _box((0, 0, 0), 21, 14, 10)),)


def test_every_case_solid_is_checked_not_only_the_first() -> None:
    """Rule 1. Two of the four are met; an implementation stopping at the
    first hit, or checking only one named solid, reports fewer."""
    data = _dock((_board(1),), {1: (_placement(),)})
    found = Clashes(_enclosure(), {1: _reaching_board()}).apply(data).placements[1][0].clashes

    assert [clash.with_ for clash in found] == ["LID", "WALL"]
    assert {clash.kind for clash in found} == {"case"}


def test_the_lid_is_checked_like_any_other_solid() -> None:
    """No part of the enclosure is privileged or exempt; the lid is named in
    the report for emphasis, which is not a narrowing of the check."""
    data = _dock((_board(1),), {1: (_placement(),)})
    found = Clashes(_enclosure(), {1: _reaching_board()}).apply(data).placements[1][0].clashes
    lid = [clash for clash in found if clash.with_ == "LID"]

    assert lid[0].kind == "case"
    assert lid[0].depth_nm == _nm(2.0)
    assert lid[0].axis == "w"


def _three_boards() -> tuple[DockData, Clashes]:
    """Three boards over an enclosure none of them touches.

    Board 1 and board 3 overlap each other; board 2 merely touches board 1
    on a face and sits nowhere near board 3, so the bounding-box filter and
    the exact boolean each get a pair to refuse. Any clash found here is a
    clash between two boards and can be nothing else, which is the scene a
    single-board fixture cannot state.
    """
    data = _dock(
        (_board(1), _board(2), _board(3)),
        {1: (_placement(),), 2: (_placement(),), 3: (_placement(),)},
    )
    solids = {
        1: (_solid("", _box((0, 0, 0), 12, 14, 5)),),
        2: (_solid("", _box((-12, 0, 0), 12, 6, 8)),),
        3: (_solid("", _box((10, 0, 0), 9, 14, 5)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_a_clash_with_another_board_is_kinded_board() -> None:
    """So a consumer never parses the ``with`` string to learn what it is."""
    data, stage = _three_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert found[0].kind == "board"
    assert found[0].with_ == "board:3"


def test_a_board_is_checked_against_every_other_board_not_only_its_neighbour() -> None:
    """Rule 1 again, over boards: board 1 meets board 3 with board 2 sitting
    between them in ordinal order and touching neither."""
    data, stage = _three_boards()
    placements = stage.apply(data).placements

    assert [clash.with_ for clash in placements[1][0].clashes] == ["board:3"]
    assert placements[2][0].clashes == ()
    assert [clash.with_ for clash in placements[3][0].clashes] == ["board:1"]


def test_an_inter_board_clash_is_measured_the_same_way_a_case_clash_is() -> None:
    """The overlap is 2 x 14 x 5, so depth is 2 mm along ``u`` -- the same
    reduction, not a second one written for boards."""
    data, stage = _three_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert found[0].depth_nm == _nm(2.0)
    assert found[0].axis == "u"
    assert found[0].volume_nm3 == 2_000_000 * 14_000_000 * 5_000_000


def test_clashes_sort_by_kind_then_with_then_depth() -> None:
    """Determinism: every traversal is over an explicitly sorted sequence."""
    data = _dock(
        (_board(1), _board(2)),
        {1: (_placement(),), 2: (_placement(),)},
    )
    solids = {
        1: (_solid("", _box((0, 0, 0), 21, 14, 10)),),
        2: (_solid("", _box((20, 0, 0), 6, 6, 6)),),
    }
    found = Clashes(_enclosure(), solids).apply(data).placements[1][0].clashes

    assert len(found) == 3
    assert found == tuple(
        sorted(found, key=lambda clash: (clash.kind, clash.with_, int(clash.depth_nm)))
    )


def test_the_case_solids_own_order_reaches_no_result() -> None:
    """ADR-0006 over this stage: two spellings of one assembly agree."""
    data = _dock((_board(1),), {1: (_placement(),)})
    forward = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)
    backward = Clashes(tuple(reversed(_enclosure())), {1: _reaching_board()}).apply(data)

    assert forward.placements[1][0].clashes == backward.placements[1][0].clashes


# --------------------------------------------------------------------------
# The placement is applied, and it is the transform Match fitted.
# --------------------------------------------------------------------------


def test_the_placement_moves_the_board_before_anything_is_intersected() -> None:
    """A stage reading the board's exported position reports the same clash
    for both placements here; only one of them reaches the wall."""
    at_origin = _dock((_board(1),), {1: (_placement(),)})
    moved = _dock((_board(1),), {1: (_placement(x_mm=200.0),)})
    stage = Clashes(_enclosure(), {1: _reaching_board()})

    assert stage.apply(at_origin).placements[1][0].clashes != ()
    assert stage.apply(moved).placements[1][0].clashes == ()


def test_the_placement_transform_agrees_with_the_transform_match_fitted() -> None:
    """``Match`` solves ``(x, y, theta)`` in the carrier plane and this stage
    must realise exactly that motion, not a second convention. The expected
    position is read from ``match``'s own ``_apply``, so the two cannot drift.
    """
    placement = _placement(x_mm=7.0, y_mm=-3.0, theta_deg=35.0)
    marker = _cylinder((11.0, 4.0, 0.0), 0.5, 2.0)

    motion = placement_transform(_board(1), placement, _identity_frame())
    box = bounding_box_mm(placed(marker, motion))
    centre = ((box[0] + box[3]) / 2, (box[1] + box[4]) / 2)

    expected = _apply((7.0, -3.0, math.radians(35.0)), (11.0, 4.0))
    assert centre == pytest.approx(expected, abs=1e-9)


def test_a_board_seated_on_its_other_face_is_turned_over() -> None:
    """``panel_face`` is a sign along the board's own carrier normal, and
    ``Match`` negates one in-plane coordinate for the flipped hypothesis. A
    transform ignoring it places the board's back where its front belongs."""
    placement = _placement()
    marker = _cylinder((11.0, 4.0, 1.0), 0.5, 2.0)

    motion = placement_transform(_board(1, panel_face="-w"), placement, _identity_frame())
    box = bounding_box_mm(placed(marker, motion))

    assert round((box[1] + box[4]) / 2, 9) == -4.0
    assert round((box[2] + box[5]) / 2, 9) == -2.0


def test_a_board_with_no_resolved_face_is_placed_as_exported() -> None:
    """``panel_face`` is ``None`` until ``Match`` resolves it, and a stage may
    not assert that another stage ran first."""
    placement = _placement()
    marker = _cylinder((11.0, 4.0, 1.0), 0.5, 2.0)

    motion = placement_transform(_board(1, panel_face=None), placement, _identity_frame())
    box = bounding_box_mm(placed(marker, motion))

    assert round((box[1] + box[4]) / 2, 9) == 4.0
    assert round((box[2] + box[5]) / 2, 9) == 2.0


# --------------------------------------------------------------------------
# Rule 4: ranked against the case alone, then the assembly formed once.
# --------------------------------------------------------------------------


def _reranking_scene() -> tuple[DockData, Clashes]:
    """Two candidates whose clash-free order is not their clash-aware order.

    Clean, ``rank_key`` falls through to ``(theta, x_nm, y_nm)``, which puts
    the placement at ``x = 0`` first. That one fouls the wall; the one at
    ``x = 200`` is clear, so filling the clash fields must move it to rank 1.
    """
    data = _dock((_board(1),), {1: (_placement(rank=1), _placement(rank=2, x_mm=200.0))})
    return data, Clashes(_enclosure(), {1: _reaching_board()})


def test_the_clash_free_ranking_this_scene_starts_from() -> None:
    """The control for the test below: without clashes the order is the other
    way round, so the re-rank is doing the work rather than agreeing by luck."""
    data, _stage = _reranking_scene()
    ranked = Seat().apply(data).placements[1]

    assert [int(placement.x_nm) for placement in ranked] == [0, 200_000_000]


def test_a_placement_is_reranked_once_its_clashes_are_known() -> None:
    """Hazard 4: the clean placement takes rank 1 although the fouling one
    sorts first on the transform."""
    data, stage = _reranking_scene()
    ranked = stage.apply(data).placements[1]

    assert [placement.rank for placement in ranked] == [1, 2]
    assert int(ranked[0].x_nm) == 200_000_000
    assert ranked[0].clashes == ()
    assert ranked[1].clashes != ()


def test_the_rerank_goes_through_seat_rank_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evidence rather than inference: replace the key this module imported
    and the order follows it.

    Three candidates, so the patched order differs from the order they were
    handed in *and* from the order ``rank_key`` itself gives -- a stage that
    kept input order, or one with a second comparator of its own, answers
    neither of the two orders this test and the one above assert.
    """
    data = _dock(
        (_board(1),),
        {1: (
            _placement(rank=3, x_mm=400.0),
            _placement(rank=1),
            _placement(rank=2, x_mm=200.0),
        )},
    )
    stage = Clashes(_enclosure(), {1: _reaching_board()})

    assert [int(p.x_nm) for p in stage.apply(data).placements[1]] == [
        200_000_000, 400_000_000, 0,
    ]

    monkeypatch.setattr(
        "stompcollider.clash.rank_key", lambda placement: -int(placement.x_nm)
    )
    assert [int(p.x_nm) for p in stage.apply(data).placements[1]] == [
        400_000_000, 200_000_000, 0,
    ]


def test_the_ranked_order_is_the_order_rank_key_gives() -> None:
    """And the ranks themselves are 1..n over that order, not carried over."""
    data, stage = _reranking_scene()
    ranked = stage.apply(data).placements[1]

    assert list(ranked) == sorted(ranked, key=rank_key)
    assert [placement.rank for placement in ranked] == [1, 2]


def _assembly_scene() -> tuple[DockData, Clashes]:
    """Board 1 has two candidates. The one at ``x = 0`` is clear of the case
    but fouls board 2 by the greater volume; the one at ``x = 36`` fouls the
    wall by the lesser.
    Ranked against the case alone, the first wins; ranked against the whole
    assembly it would lose, which is what makes this scene state rule 4.
    """
    data = _dock(
        (_board(1), _board(2)),
        {1: (_placement(rank=1), _placement(rank=2, x_mm=36.0)), 2: (_placement(),)},
    )
    solids = {
        1: (_solid("", _box((-14, 0, 0), 12, 20, 5)),),
        2: (_solid("", _box((-10, 0, 0), 16, 26, 3)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_each_board_is_ranked_against_the_case_alone() -> None:
    """Rule 4. Board 1's rank-1 candidate is the one with no case clash,
    although it is the one that fouls board 2 by the greater volume."""
    data, stage = _assembly_scene()
    chosen = stage.apply(data).placements[1][0]

    assert int(chosen.x_nm) == 0
    assert [clash.with_ for clash in chosen.clashes] == ["board:2"]
    assert chosen.clashes[0].depth_nm == _nm(3.0)


def test_inter_board_clashes_reach_the_chosen_placement_only() -> None:
    """The assembly is formed once, from each board's rank-1 placement; the
    Cartesian product of every board's candidates never appears."""
    data, stage = _assembly_scene()
    placements = stage.apply(data).placements[1]

    assert {clash.kind for clash in placements[0].clashes} == {"board"}
    assert {clash.kind for clash in placements[1].clashes} == {"case"}


def test_a_board_clash_carries_no_rank_of_its_own() -> None:
    """Adding the inter-board clashes must not re-rank: the ranks the case
    fixed stand, or rule 4's independence is lost at the last step."""
    data, stage = _assembly_scene()
    ranked = stage.apply(data).placements[1]

    assert [placement.rank for placement in ranked] == [1, 2]
    assert int(ranked[0].x_nm) == 0


# --------------------------------------------------------------------------
# What the stage reports, and what it refuses.
# --------------------------------------------------------------------------


def test_a_clashing_board_is_still_reported_and_still_drawn() -> None:
    """Matching and fitting fail differently. A matched board whose every
    candidate clashes is the RIGHT board with a misaligned design: exit 1,
    every candidate reported. Withholding it would defeat the tool."""
    data = _dock((_board(1),), {1: (_placement(), _placement(rank=2, y_mm=1.0))})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert len(result.placements[1]) == 2
    assert max(finding.severity for finding in result.diagnostics).name == "WARNING"
    assert {finding.code for finding in result.diagnostics} == {"clash"}


def test_a_clash_is_reported_once_per_clash_of_the_chosen_placement() -> None:
    """One finding per clash, so the report says what fouls what rather than
    that something did."""
    data = _dock((_board(1),), {1: (_placement(),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert len(result.of_severity(Severity.WARNING)) == 2
    assert {dict(finding.data)["with"] for finding in result.diagnostics} == {"LID", "WALL"}


def test_a_clean_assembly_raises_nothing() -> None:
    """The innocent probe: a stage warning unconditionally passes the two
    tests above."""
    data = _dock((_board(1),), {1: (_placement(x_mm=200.0),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert result.diagnostics == ()


def test_the_incoming_diagnostics_survive() -> None:
    """A stage appends; it never replaces what earlier stages found."""
    earlier = Diagnostic.warning("unmatched-part", "RV5 has no hole")
    data = _dock((_board(1),), {1: (_placement(),)}).with_diagnostics(earlier)
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert result.diagnostics[0] is earlier


def test_a_board_with_placements_and_no_solids_is_refused() -> None:
    """Rule 1 is a claim about the whole assembly, so a board the stage was
    handed no geometry for is a failure rather than a board with no clashes.
    """
    data = _dock((_board(1),), {1: (_placement(),)})

    with pytest.raises(StompcolliderError):
        Clashes(_enclosure(), {}).apply(data)


def test_placements_ranked_for_a_board_the_data_does_not_hold_are_refused() -> None:
    """The other half of the same claim: an ordinal with no board is not a
    board with nothing to check, and the transform cannot be built without one.
    """
    data = _dock((_board(1),), {2: (_placement(),)})

    with pytest.raises(StompcolliderError):
        Clashes(_enclosure(), {2: _reaching_board()}).apply(data)


def test_a_board_with_no_placement_at_all_is_left_alone() -> None:
    """``Match`` may find no placement for a board. There is then nothing to
    seat in the assembly and nothing to warn about, and the other boards are
    still checked against each other."""
    data = _dock(
        (_board(1), _board(2)),
        {1: (), 2: (_placement(),)},
    )
    solids = {1: _reaching_board(), 2: _reaching_board()}
    result = Clashes(_enclosure(), solids).apply(data)

    assert result.placements[1] == ()
    assert {clash.kind for clash in result.placements[2][0].clashes} == {"case"}


def test_the_placements_mapping_that_comes_back_is_read_only() -> None:
    """``DockData.placements`` is a ``MappingProxyType``; the stage builds a
    new mapping rather than mutating the one it was given."""
    data = _dock((_board(1),), {1: (_placement(),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    with pytest.raises(TypeError):
        result.placements[2] = ()  # type: ignore[index]
    assert data.placements[1][0].clashes == ()


# --------------------------------------------------------------------------
# The stage contract.
# --------------------------------------------------------------------------


def test_clashes_is_a_stage() -> None:
    stage = Clashes((), {})

    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str)


def test_clashes_conforms_to_the_stage_protocol_statically() -> None:
    """A static conformance assignment: ``isinstance`` alone cannot see that
    ``describe()`` returns a ``StageRun`` rather than a ``str`` -- a runtime
    protocol check reads names and arity, never a return type."""
    _conforms: Stage[DockData] = Clashes((), {})

    assert _conforms is not None


def test_describe_names_the_stage() -> None:
    assert Clashes((), {}).describe() == StageRun("clashes")


def test_apply_does_not_record_its_own_stage_run() -> None:
    """``Pipeline.run`` appends ``describe()`` after ``apply`` returns, so a
    stage recording itself would be recorded twice."""
    data = _dock((_board(1),), {1: (_placement(),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert result.processing == ()
