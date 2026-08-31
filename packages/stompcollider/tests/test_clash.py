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


def _skew_frame() -> CoordinateFrame:
    """A face frame turned an eighth about ``w``, not a quarter.

    Every frame ``stompdrill`` produces today is a quarter turn about a
    model axis, and under one of those a model-frame box and a face-frame
    box coincide -- so a quarter-turn fixture cannot tell a region's own box
    from the box of its model box. This one can: a circle 10 mm across has a
    model box 10 mm square whose corners reach 14.142 mm once projected.
    """
    half = math.sqrt(2) / 2
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(half, half, 0.0),
        v=(0.0 - half, half, 0.0),
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

    assert found[0].bbox_volume_nm3 == 2_000_000 * 12_000_000 * 14_000_000


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


def test_the_bbox_is_the_regions_own_box_in_that_frame_not_the_box_of_its_model_box() -> None:
    """The measurement, not merely the frame. A cylinder 10 mm across is
    10 mm across in every frame; boxing it on the model axes first and
    reprojecting that box's corners answers 14.142 mm under this one -- a
    41% overstatement of the number this tool exists to report. Only a
    non-quarter-turn frame separates the two, which is why this fixture is
    an eighth turn.
    """
    found = _clashes_between(
        _cylinder((0, 0, 0), 5.0, 30.0),
        _box((-40, -40, 0), 80, 80, 30),
        frame=_skew_frame(),
    )

    assert found[0].depth_nm == _nm(10.0)
    assert found[0].bbox_nm == (
        _nm(-5.0), _nm(-5.0), _nm(0.0), _nm(5.0), _nm(5.0), _nm(30.0),
    )


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
        1: (_solid("P", _box((0, 0, 0), 12, 14, 5)),),
        2: (_solid("Q", _box((-12, 0, 0), 12, 6, 8)),),
        3: (_solid("R", _box((10, 0, 0), 9, 14, 5)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_a_clash_with_another_board_is_kinded_board() -> None:
    """So a consumer never parses the ``with`` string to learn what it is.

    ``with`` names the other board's *solid*, under the very name the
    assembly model writes it as, so a reader can find it in the file.
    """
    data, stage = _three_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert found[0].kind == "board"
    assert found[0].with_ == "board:3:R"
    assert found[0].part == "board:1:P"


def test_a_board_is_checked_against_every_other_board_not_only_its_neighbour() -> None:
    """Rule 1 again, over boards: board 1 meets board 3 with board 2 sitting
    between them in ordinal order and touching neither.

    The pair is stated once, on the lower ordinal, so board 3 carries no
    second copy of the one fact -- see the stated-once test below.
    """
    data, stage = _three_boards()
    placements = stage.apply(data).placements

    assert [clash.with_ for clash in placements[1][0].clashes] == ["board:3:R"]
    assert placements[2][0].clashes == ()
    assert placements[3][0].clashes == ()


def test_an_inter_board_clash_is_measured_the_same_way_a_case_clash_is() -> None:
    """The overlap is 2 x 14 x 5, so depth is 2 mm along ``u`` -- the same
    reduction, not a second one written for boards."""
    data, stage = _three_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert found[0].depth_nm == _nm(2.0)
    assert found[0].axis == "u"
    assert found[0].bbox_volume_nm3 == 2_000_000 * 14_000_000 * 5_000_000
    assert found[0].common_volume_nm3 == pytest.approx(found[0].bbox_volume_nm3, rel=1e-12)


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


def _unnamed_enclosure() -> tuple[StepSolid, ...]:
    """Two case solids the model never named, in the way of one board."""
    return (
        _solid("", _box((20, -50, -30), 4, 100, 40)),
        _solid("", _box((-50, -50, 8), 100, 100, 3)),
    )


def test_a_case_solid_the_model_never_named_is_still_reported() -> None:
    """``StepSolid.name`` is empty exactly when nobody named the solid, and a
    supplied enclosure may hold such a solid. ``Clash`` refuses an empty
    name, so without a fallback this run raises instead of reporting."""
    data = _dock((_board(1),), {1: (_placement(),)})
    found = Clashes(_unnamed_enclosure(), {1: _reaching_board()}).apply(data).placements[1][0].clashes

    assert len(found) == 2
    assert {clash.kind for clash in found} == {"case"}


def test_two_unnamed_case_solids_are_told_apart_by_their_own_geometry() -> None:
    """A single fallback spelling would collapse both into one entry."""
    data = _dock((_board(1),), {1: (_placement(),)})
    found = Clashes(_unnamed_enclosure(), {1: _reaching_board()}).apply(data).placements[1][0].clashes

    assert [clash.with_ for clash in found] == [
        "case:unnamed@-50000000,-50000000,8000000",
        "case:unnamed@20000000,-50000000,-30000000",
    ]


def test_an_unnamed_case_solids_identifier_does_not_depend_on_the_order_supplied() -> None:
    """ADR-0006: an index into the supplied sequence would fail this."""
    data = _dock((_board(1),), {1: (_placement(),)})
    solids = _unnamed_enclosure()
    forward = Clashes(solids, {1: _reaching_board()}).apply(data)
    backward = Clashes(tuple(reversed(solids)), {1: _reaching_board()}).apply(data)

    assert forward.placements[1][0].clashes == backward.placements[1][0].clashes


def test_a_named_case_solid_keeps_its_own_name() -> None:
    """The innocent probe: a fallback applied unconditionally passes the
    three tests above and renames every enclosure the catalogue ships."""
    data = _dock((_board(1),), {1: (_placement(),)})
    found = Clashes(_enclosure(), {1: _reaching_board()}).apply(data).placements[1][0].clashes

    assert [clash.with_ for clash in found] == ["LID", "WALL"]


def test_a_sub_micron_clash_does_not_read_as_zero_millimetres() -> None:
    """Rule 3 says one nanometre is a fact and contact is not. A message
    saying "0.000 mm" for the smallest thing the tool can honestly assert
    erases that distinction in the half of the report a person acts on."""
    data = _dock((_board(1),), {1: (_placement(),)})
    stage = Clashes(
        (_solid("WALL", _box((9.999999, 0, 0), 10, 12, 14)),),
        {1: (_solid("", _box((0, 0, 0), 10, 12, 14)),)},
    )
    finding = stage.apply(data).diagnostics[0]

    assert "0.000001 mm" in finding.message
    assert dict(finding.data)["depth_nm"] == 1


def test_a_clash_of_ordinary_size_is_still_stated_at_three_decimals() -> None:
    """The control beside it: the fallback is for what three decimals cannot
    say, not a new default for everything."""
    data = _dock((_board(1),), {1: (_placement(),)})
    finding = Clashes(_enclosure(), {1: _reaching_board()}).apply(data).diagnostics[0]

    assert "2.000 mm" in finding.message


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


def test_a_board_with_no_resolved_face_is_placed_as_exported() -> None:
    """``panel_face`` is ``None`` until ``Match`` resolves it, and a stage may
    not assert that another stage ran first. There is nothing else it can be:
    which face points at the panel is derived rather than searched, so the
    only value ``Match`` writes is the one this transform already assumes.
    """
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
        1: (_solid("P", _box((-14, 0, 0), 12, 20, 5)),),
        2: (_solid("Q", _box((-10, 0, 0), 16, 26, 3)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_each_board_is_ranked_against_the_case_alone() -> None:
    """Rule 4. Board 1's rank-1 candidate is the one with no case clash,
    although it is the one that fouls board 2 by the greater volume."""
    data, stage = _assembly_scene()
    chosen = stage.apply(data).placements[1][0]

    assert int(chosen.x_nm) == 0
    assert [clash.with_ for clash in chosen.clashes] == ["board:2:Q"]
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
    assert {finding.code for finding in result.of_severity(Severity.WARNING)} == {
        "clash"
    }


def test_a_clash_is_reported_once_per_clash_of_the_chosen_placement() -> None:
    """One finding per clash, so the report says what fouls what rather than
    that something did."""
    data = _dock((_board(1),), {1: (_placement(),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert len(result.of_severity(Severity.WARNING)) == 2
    assert {
        dict(finding.data)["with"] for finding in result.of_severity(Severity.WARNING)
    } == {"LID", "WALL"}


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


# --------------------------------------------------------------------------
# A clash carries its true volume as well as its box.
# --------------------------------------------------------------------------


def test_a_clash_states_the_exact_volume_of_the_region_beside_its_box() -> None:
    """The box answers how far to move; the region answers how much is in the
    way, and over a curved region the two differ by a fixed factor.

    A shaft 4 mm across through a 3 mm plate shares a cylinder: pi * 4 * 3
    cubic millimetres of material inside a box of 4 * 4 * 3.
    """
    found = _clashes_between(
        _cylinder((20.0, 20.0, -5.0), 2.0, 13.0), _box((15, 15, 0), 10, 10, 3)
    )

    assert len(found) == 1
    assert found[0].bbox_volume_nm3 == 4_000_000 * 4_000_000 * 3_000_000
    assert found[0].common_volume_nm3 == pytest.approx(
        math.pi * 4.0 * 3.0 * 10**18, rel=1e-6
    )
    assert found[0].common_volume_nm3 < found[0].bbox_volume_nm3


def test_the_two_volumes_agree_exactly_where_the_region_really_is_its_box() -> None:
    """The control beside it: a rule reporting the box for both would pass the
    equality here and fail the inequality above, and one reporting nothing for
    the exact volume would pass above and fail here."""
    found = _clashes_between(_box((0, 0, 0), 10, 12, 14), _box((8, 0, 0), 10, 40, 40))

    assert found[0].common_volume_nm3 == pytest.approx(found[0].bbox_volume_nm3, rel=1e-12)
    assert found[0].common_volume_nm3 == pytest.approx(
        2_000_000 * 12_000_000 * 14_000_000, rel=1e-12
    )


# --------------------------------------------------------------------------
# Between two boards: per solid, and stated once.
# --------------------------------------------------------------------------


def _meeting_boards() -> tuple[DockData, Clashes]:
    """Two boards whose solids meet in two places, clear of every case solid.

    Board 1 carries two named parts and board 2 one; each of board 1's meets
    board 2's, in 2 x 10 x 4 mm of material apiece. A rule reporting one
    finding per board pair states one clash here where there are two.
    """
    data = _dock((_board(1), _board(2)), {1: (_placement(),), 2: (_placement(),)})
    solids = {
        1: (_solid("A", _box((0, 0, 0), 10, 10, 4)),
            _solid("B", _box((0, 20, 0), 10, 10, 4))),
        2: (_solid("C", _box((8, 0, 0), 6, 30, 4)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_an_inter_board_finding_names_the_two_solids_that_meet() -> None:
    """Not the two boards: "board 1 clashes with board 2" is not something a
    person can act on."""
    data, stage = _meeting_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert [(clash.part, clash.with_) for clash in found] == [
        ("board:1:A", "board:2:C"), ("board:1:B", "board:2:C"),
    ]
    assert {clash.kind for clash in found} == {"board"}


def test_each_meeting_pair_of_solids_states_its_own_volume() -> None:
    """Two pairs, each 2 x 10 x 4 mm of material: the detail a person acts on."""
    data, stage = _meeting_boards()
    found = stage.apply(data).placements[1][0].clashes

    assert [clash.common_volume_nm3 for clash in found] == pytest.approx(
        [2_000_000 * 10_000_000 * 4_000_000] * 2, rel=1e-12
    )


def test_an_unordered_pair_of_boards_is_stated_once_and_not_from_both_sides() -> None:
    """The same interference recorded against both boards is one fact printed
    twice, and a reader counting findings would count it twice."""
    data, stage = _meeting_boards()
    placements = stage.apply(data).placements

    assert len(placements[1][0].clashes) == 2
    assert placements[2][0].clashes == ()


def test_the_pair_is_summarised_beside_the_per_solid_detail() -> None:
    """An assembly of many parts needs a line saying *these two boards
    interfere* without reading every pair; it is a summary over the detail
    rather than the only statement."""
    data, stage = _meeting_boards()
    findings = stage.apply(data).diagnostics
    summary = [f for f in findings if "solids" in dict(f.data)]

    assert len(summary) == 1
    stated = dict(summary[0].data)
    assert stated["board"] == 1
    assert stated["with"] == "board:2"
    assert stated["kind"] == "board"
    assert stated["solids"] == 2
    assert stated["common_volume_nm3"] == pytest.approx(
        2 * 2_000_000 * 10_000_000 * 4_000_000, rel=1e-12
    )


def test_the_detail_findings_name_the_solids_the_summary_counts() -> None:
    """The control on the summary: it must not be the only board finding, or
    the per-solid rule above reaches no report."""
    data, stage = _meeting_boards()
    detail = [
        dict(f.data)["part"]
        for f in stage.apply(data).diagnostics
        if "part" in dict(f.data)
    ]

    assert detail == ["board:1:A", "board:1:B"]


def _meeting_substrates() -> tuple[DockData, Clashes]:
    """The same meeting between two solids nobody named: two substrates."""
    data = _dock((_board(1), _board(2)), {1: (_placement(),), 2: (_placement(),)})
    solids = {
        1: (_solid("", _box((0, 0, 0), 10, 10, 4)),),
        2: (_solid("", _box((8, 0, 0), 6, 30, 4)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_a_finding_calls_a_solid_nobody_named_a_substrate_on_either_side() -> None:
    """A least corner identifies a solid but does not read as one. The message
    says what it is, on both sides of the pair; the finding's own keys keep the
    exact identity, which is the name the assembly writes that solid under."""
    data, stage = _meeting_substrates()
    found = [f for f in stage.apply(data).diagnostics if "part" in dict(f.data)]

    assert len(found) == 1
    assert found[0].message.startswith(
        "board 1's substrate clashes with board 2's substrate by "
    )
    stated = dict(found[0].data)
    assert str(stated["part"]).startswith("board:1:unnamed@")
    assert str(stated["with"]).startswith("board:2:unnamed@")


def test_a_named_board_solid_keeps_its_designator_in_the_message() -> None:
    """The control beside it: only a solid nobody named is restated, so a rule
    rewriting every name would fail here."""
    data, stage = _meeting_boards()
    found = [f for f in stage.apply(data).diagnostics if "part" in dict(f.data)]

    assert [f.message.split(" clashes with ")[0] for f in found] == [
        "board:1:A",
        "board:1:B",
    ]
    assert all(
        f.message.split(" clashes with ")[1].startswith("board:2:C by ") for f in found
    )


# --------------------------------------------------------------------------
# Two-stage seating selection.
# --------------------------------------------------------------------------


def _two_stage_scene() -> tuple[DockData, Clashes]:
    """Board 1 has two seatings that both clear the case, and one of them
    fouls board 2.

    Stage one ranks on the transform alone, which puts the fouling one at
    ``x = 25`` first. Stage two must move the clear one at ``x = 100`` to
    rank 1, on mutual interference alone.
    """
    data = _dock(
        (_board(1), _board(2)),
        {1: (_placement(rank=1, x_mm=25.0), _placement(rank=2, x_mm=100.0)),
         2: (_placement(),)},
    )
    solids = {
        1: (_solid("A", _box((0, 0, 0), 10, 10, 4)),),
        2: (_solid("C", _box((30, 0, 0), 10, 10, 4)),),
    }
    return data, Clashes(_enclosure(), solids)


def test_stage_one_alone_would_choose_the_seating_that_fouls_its_neighbour() -> None:
    """The control for the test below: with no clash to read, the ranking key
    falls through to the transform and puts ``x = 25`` first."""
    data, _stage = _two_stage_scene()
    ranked = Seat().apply(data).placements[1]

    assert [int(placement.x_nm) for placement in ranked] == [25_000_000, 100_000_000]


def test_stage_two_chooses_the_assembly_of_least_inter_board_volume() -> None:
    """Both of board 1's seatings clear the case, so the case has already been
    answered and mutual interference alone decides between them."""
    data, stage = _two_stage_scene()
    ranked = stage.apply(data).placements[1]

    assert int(ranked[0].x_nm) == 100_000_000
    assert ranked[0].rank == 1
    assert ranked[0].clashes == ()


def test_the_seating_stage_two_rejected_is_still_reported() -> None:
    """Every distinct placement is returned; rank is a reported field and
    never a verdict that withholds one."""
    data, stage = _two_stage_scene()
    ranked = stage.apply(data).placements[1]

    assert [int(p.x_nm) for p in ranked] == [100_000_000, 25_000_000]
    assert [p.rank for p in ranked] == [1, 2]


def test_a_seating_that_fouls_the_case_takes_no_part_in_stage_two() -> None:
    """A seating that fouls the enclosure is not a seating, so it cannot be
    improved by anything a neighbouring board does.

    Board 1's ``x = 0`` candidate is clear of every other board and would win
    stage two outright; it fouls the wall, so stage one discards it and the
    clean candidate at ``x = 100`` is chosen although it is not rank 1 by the
    transform.
    """
    data = _dock(
        (_board(1),),
        {1: (_placement(rank=1), _placement(rank=2, x_mm=100.0))},
    )
    stage = Clashes(_enclosure(), {1: (_solid("A", _box((0, 0, 0), 21, 14, 10)),)})
    ranked = stage.apply(data).placements[1]

    assert int(ranked[0].x_nm) == 100_000_000
    assert ranked[0].clashes == ()


def test_a_board_no_seating_clears_the_case_for_says_so() -> None:
    """Otherwise a reader could not tell a chosen seating from a defaulted one."""
    data = _dock((_board(1),), {1: (_placement(), _placement(rank=2, y_mm=1.0))})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert [f.code for f in result.of_severity(Severity.INFO)] == [
        "every-seating-clashes"
    ]
    assert dict(result.of_severity(Severity.INFO)[0].data) == {"board": 1}


def test_that_board_keeps_its_stage_one_rank_one_and_is_still_written() -> None:
    """The assembly is written at its stage-one rank 1: withholding the model
    would take away the very artefact that shows what to fix."""
    data = _dock((_board(1),), {1: (_placement(), _placement(rank=2, y_mm=1.0))})
    ranked = Clashes(_enclosure(), {1: _reaching_board()}).apply(data).placements[1]

    assert [p.rank for p in ranked] == [1, 2]
    assert int(ranked[0].y_nm) == 0


def test_a_board_with_a_clean_seating_earns_no_such_finding() -> None:
    """The control: a stage raising it unconditionally passes both tests above."""
    data = _dock((_board(1),), {1: (_placement(x_mm=200.0),)})
    result = Clashes(_enclosure(), {1: _reaching_board()}).apply(data)

    assert [f.code for f in result.diagnostics] == []


def test_the_combination_count_is_bounded_and_the_bound_is_stated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never truncated silently: a run that could not try every assembly says
    so, and says how many there were."""
    monkeypatch.setattr("stompcollider.clash._COMBINATION_LIMIT", 1)
    data, stage = _two_stage_scene()
    result = stage.apply(data)
    notes = [f for f in result.diagnostics if f.code == "seating-search-bounded"]

    assert len(notes) == 1
    assert dict(notes[0].data) == {"limit": 1, "combinations": 2}
    assert int(result.placements[1][0].x_nm) == 25_000_000


def test_an_unbounded_search_states_no_bound_and_reaches_the_better_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control beside it: with room for both combinations the note is
    absent and the assembly chosen is the one the bound cut off."""
    monkeypatch.setattr("stompcollider.clash._COMBINATION_LIMIT", 2)
    data, stage = _two_stage_scene()
    result = stage.apply(data)

    assert [f.code for f in result.diagnostics if f.code == "seating-search-bounded"] == []
    assert int(result.placements[1][0].x_nm) == 100_000_000


def test_a_sub_millicubic_clash_does_not_read_as_zero_cubic_millimetres() -> None:
    """The volume half of rule 3: a region a person should see must not print
    as nothing, and cubic nanometres shrink far faster than nanometres do.

    Two boards overlapping by one nanometre over 12 by 14 millimetres hold
    0.000168 mm3 of shared material, which three decimals erase entirely.
    """
    data = _dock((_board(1), _board(2)), {1: (_placement(),), 2: (_placement(),)})
    stage = Clashes(
        (),
        {
            1: (_solid("P", _box((0, 0, 0), 10, 12, 14)),),
            2: (_solid("Q", _box((9.999999, 0, 0), 10, 12, 14)),),
        },
    )
    detail = [
        f for f in stage.apply(data).diagnostics if "part" in dict(f.data)
    ]

    assert len(detail) == 1
    assert "0.000168" in detail[0].message
    assert "by 0.000 mm³" not in detail[0].message


def test_an_ordinary_clash_volume_is_still_stated_at_three_decimals() -> None:
    """The control beside it: the fallback is for what three decimals cannot
    state, and a rule applying it always would print every volume long."""
    data, stage = _meeting_boards()
    detail = [
        f for f in stage.apply(data).diagnostics if "part" in dict(f.data)
    ]

    assert "by 80.000 mm³" in detail[0].message
