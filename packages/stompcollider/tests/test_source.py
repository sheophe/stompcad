"""``BoardSource``: board files, the case model and the drill document, read.

The synthetic solids are built through OCP directly because that is what a
fixture is; the package's own source reaches the kernel only through
``stompgeom``, which ``test_package_boundary.py`` enforces. Only the *file*
reader is stubbed, and only where a test needs a document a written STEP file
cannot carry: the writer names every product, so an unnamed substrate survives
no round trip. What the stub hands back is a real kernel document, so every
measurement below is the kernel's own.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from stompcollider.boards import basis_about
from stompcollider.errors import StompcolliderError
from stompcollider.raw import RawBoards
from stompcollider.sources import BoardSource
from stompcollider.sources import step as source_step
from stompgeom.build import PlacedSolid, build_document
from stompgeom.step import StepDocument, read_step, read_step_document
from stompmodel.codec import to_document
from stompmodel.diagnostics import Severity
from stompmodel.model import DrillData, EnclosureMatch
from stompmodel.units import Nanometre

_FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"

#: A 1590B: 112.40 x 60.50 mm, 31 mm deep. The catalogue states it larger
#: first and the model measures it in whatever order its axes fall, which is
#: what makes it the pair worth comparing.
_1590B_NM = (Nanometre(112_400_000), Nanometre(60_500_000))

#: A footprint the drill document states smaller first, which the catalogue
#: really does -- ``1590LB`` is printed 50.55 x 50.60. Not that row's own
#: numbers, though: near-square, they would agree sorted or unsorted and so
#: could not test the reduction at all. These two differ by 62 mm.
_SMALLER_FIRST_NM = (Nanometre(50_000_000), Nanometre(112_400_000))


# --------------------------------------------------------------------------
# Synthetic geometry.
# --------------------------------------------------------------------------


def _block(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _cylinder(radius: float, height: float, at: tuple[float, float, float]) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*at), gp_Dir(0.0, 0.0, 1.0)), radius, height
    ).Shape()


def _document(solids: list[PlacedSolid]) -> StepDocument:
    """An in-memory XCAF document, read back exactly as a file would be."""
    return read_step_document(build_document(solids))


def _case_spanning(dx: float, dy: float, dz: float) -> StepDocument:
    """A case model measuring exactly ``dx x dy x dz`` and nothing else."""
    return _document(
        [PlacedSolid(shape=_block(dx, dy, dz, (0.0, 0.0, 0.0)), name="BOX", colour=None,
                     placement=None)]
    )


def _substrate(at: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> PlacedSolid:
    """An unnamed 30 x 20 x 1 slab -- ``is_slab``'s three criteria all met."""
    return PlacedSolid(shape=_block(30.0, 20.0, 1.0, at), name="", colour=None, placement=None)


def _board_document(*, towards: float = -1.0) -> StepDocument:
    """One slab with one pin, protruding 11 mm along ``towards`` and 0 the other way.

    Mirror-symmetric in ``towards`` on purpose: the pin's geometry is the
    only thing that differs between the two, so a reader that assumed a
    constant normal answers one of them wrongly.
    """
    base = -11.0 if towards < 0.0 else 0.0
    return _document(
        [
            _substrate(),
            PlacedSolid(shape=_cylinder(3.0, 12.0, (10.0, 8.0, base)), name="RV1",
                        colour=None, placement=None),
        ]
    )


def _two_board_document() -> StepDocument:
    """Two slabs, side by side, each with its own pin."""
    return _document(
        [
            _substrate(),
            PlacedSolid(shape=_cylinder(3.0, 12.0, (10.0, 8.0, -11.0)), name="RV1",
                        colour=None, placement=None),
            _substrate((50.0, 0.0, 0.0)),
            PlacedSolid(shape=_cylinder(3.0, 12.0, (60.0, 8.0, -11.0)), name="RV2",
                        colour=None, placement=None),
        ]
    )


# --------------------------------------------------------------------------
# Harness.
# --------------------------------------------------------------------------


def _write_drill(path: Path, enclosure: tuple[Nanometre, Nanometre] | None) -> Path:
    """A real drill document, written through stompmodel's own codec."""
    match = (
        None
        if enclosure is None
        else EnclosureMatch(
            family="1590", length_nm=enclosure[0], width_nm=enclosure[1],
            candidates=("1590B",), selected_part="1590B",
        )
    )
    path.write_text(json.dumps(to_document(DrillData(enclosure=match))), encoding="utf-8")
    return path


def _stub_reader(monkeypatch: pytest.MonkeyPatch, prepared: dict[Path, StepDocument]) -> None:
    """Serve ``prepared`` by path; anything else goes to the real reader.

    The fallback is what lets an unreadable file be a genuinely unreadable
    file rather than a stub raising on cue.
    """

    def reader(path: Path) -> StepDocument:
        found = prepared.get(Path(path))
        return found if found is not None else read_step(Path(path))

    monkeypatch.setattr(source_step, "read_step", reader)


def _read_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enclosure: tuple[Nanometre, Nanometre] | None,
    model_spans: tuple[float, float, float],
    board: StepDocument | None = None,
) -> RawBoards:
    drill = _write_drill(tmp_path / "drill.json", enclosure)
    case, board_path = tmp_path / "case.stp", tmp_path / "board.stp"
    _stub_reader(
        monkeypatch,
        {case: _case_spanning(*model_spans),
         board_path: board if board is not None else _board_document()},
    )
    return BoardSource(drill, [board_path], case).read()


def test_a_run_with_no_board_model_to_read_is_refused(tmp_path) -> None:
    """Resolved at construction, before a file opens: there is nothing to dock."""
    with pytest.raises(StompcolliderError, match="at least one board model"):
        BoardSource(tmp_path / "drill.json", [], tmp_path / "case.stp")


def _codes(raw: RawBoards) -> list[str]:
    return [d.code for d in raw.diagnostics]


# --------------------------------------------------------------------------
# wrong-case-model.
# --------------------------------------------------------------------------


def test_a_case_model_matching_the_enclosure_raises_nothing(tmp_path, monkeypatch) -> None:
    """The model reports 60.50 x 112.40 and the catalogue 112.40 x 60.50.

    Opposite orders, so the reduction is what makes them the same footprint;
    without it this pair is refused and the comparison rejects everything.
    """
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=_1590B_NM,
                             model_spans=(60.50, 112.40, 31.00))) == []


def test_a_case_model_of_the_wrong_footprint_is_refused(tmp_path, monkeypatch) -> None:
    """112.40 x 50.00 is not 112.40 x 60.50, in any order."""
    raw = _read_with(tmp_path, monkeypatch, enclosure=_1590B_NM,
                     model_spans=(112.40, 50.00, 31.00))
    assert _codes(raw) == ["wrong-case-model"]
    assert raw.diagnostics[0].severity is Severity.ERROR


def test_the_enclosure_pair_is_reduced_as_well_as_the_model(tmp_path, monkeypatch) -> None:
    """A catalogue row printed smaller first still matches its own model.

    The mirror of the test above: there the model reported the pair the
    other way round, here the drill document does.
    """
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=_SMALLER_FIRST_NM,
                             model_spans=(112.40, 50.00, 31.00))) == []


def test_the_footprint_is_the_two_spans_across_the_shallowest_axis(
    tmp_path, monkeypatch
) -> None:
    """Depth takes no part: a 31 mm deep 1590B is not a 112.40 x 31.00 case."""
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=(Nanometre(112_400_000),
                                                              Nanometre(31_000_000)),
                             model_spans=(112.40, 60.50, 31.00))) == ["wrong-case-model"]


def test_a_drill_document_naming_no_enclosure_skips_the_check(tmp_path, monkeypatch) -> None:
    """Skipped, not guessed at: no footprint to compare is not a mismatch."""
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=None,
                             model_spans=(1.0, 2.0, 3.0))) == []


def test_the_skipped_check_would_have_fired_on_that_very_model(tmp_path, monkeypatch) -> None:
    """The control for the test above: the same model, now with an enclosure.

    Without it, "no diagnostic" could mean the model happened to match
    rather than that the comparison was skipped.
    """
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=_1590B_NM,
                             model_spans=(1.0, 2.0, 3.0))) == ["wrong-case-model"]


def test_the_comparison_is_exact_to_the_nanometre(tmp_path, monkeypatch) -> None:
    """One micron under is a different case, not a tolerated one."""
    assert _codes(_read_with(tmp_path, monkeypatch, enclosure=_1590B_NM,
                             model_spans=(112.399, 60.50, 31.00))) == ["wrong-case-model"]


# --------------------------------------------------------------------------
# multiple-boards.
# --------------------------------------------------------------------------


def test_two_boards_in_one_file_is_a_warning_not_an_info(tmp_path, monkeypatch) -> None:
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=_two_board_document())
    found = [d for d in raw.diagnostics if d.code == "multiple-boards"]
    assert [d.severity for d in found] == [Severity.WARNING]


def test_one_board_is_not_reported_as_multiple(tmp_path, monkeypatch) -> None:
    """The control: a rule that always warns would pass the test above."""
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0))
    assert len(raw.boards) == 1
    assert "multiple-boards" not in _codes(raw)


# --------------------------------------------------------------------------
# unreadable-board.
# --------------------------------------------------------------------------


def test_a_file_that_is_not_step_at_all_is_unreadable_board(tmp_path, monkeypatch) -> None:
    broken = tmp_path / "broken.stp"
    broken.write_bytes(b"this is not a STEP file\n")
    assert _codes(_read_with_boards(tmp_path, monkeypatch, [broken])) == ["unreadable-board"]


def test_a_step_file_holding_no_solids_is_unreadable_board(tmp_path, monkeypatch) -> None:
    """The rule's second arm: readable, conforming, and empty of shapes."""
    empty = tmp_path / "empty.stp"
    empty.write_text(_EMPTY_STEP, encoding="utf-8")
    assert _codes(_read_with_boards(tmp_path, monkeypatch, [empty])) == ["unreadable-board"]


def test_a_readable_board_beside_an_unreadable_one_still_yields_its_boards(
    tmp_path, monkeypatch
) -> None:
    """One bad file does not withhold the geometry of a good one."""
    broken = tmp_path / "broken.stp"
    broken.write_bytes(b"not STEP\n")
    good = tmp_path / "good.stp"
    raw = _read_with_boards(tmp_path, monkeypatch, [broken, good],
                            prepared={good: _board_document()})
    assert _codes(raw) == ["unreadable-board"]
    assert len(raw.boards) == 1
    # Asserted here rather than beside a scan of nothing but bad files: with a
    # board present, RawBoards' own guard cannot fail first and stand in for
    # the severity this line is the only statement of.
    assert raw.diagnostics[0].severity is Severity.ERROR


def test_a_board_file_that_is_not_there_is_unreadable_board(tmp_path, monkeypatch) -> None:
    """The likeliest operator error of all: a path that names nothing.

    Diagnosed like any other unreadable board rather than crashing, and it
    is the one arm no other test here reaches.
    """
    raw = _read_with_boards(tmp_path, monkeypatch, [tmp_path / "absent.stp"])
    assert _codes(raw) == ["unreadable-board"]
    assert raw.diagnostics[0].get("model") == "absent.stp"


def test_where_a_board_file_sits_reaches_no_diagnostic(tmp_path, monkeypatch) -> None:
    """One board read from two directories must not make two artefacts.

    Both the payload and the message: the reader states its reason against
    the path it was handed, so an absolute spelling would carry a whole
    directory into the document the report emitter serialises.
    """
    here, there = tmp_path / "here", tmp_path / "there"
    for directory in (here, there):
        directory.mkdir()
        (directory / "board.stp").write_bytes(b"not STEP\n")

    first = _read_with_boards(here, monkeypatch, [here / "board.stp"])
    monkeypatch.chdir(there)
    second = _read_with_boards(there, monkeypatch, [Path("board.stp")])

    assert first.diagnostics[0].data == second.diagnostics[0].data
    assert first.diagnostics[0].message == second.diagnostics[0].message
    assert str(here) not in first.diagnostics[0].message


def test_the_order_the_files_were_listed_reaches_no_diagnostic(tmp_path, monkeypatch) -> None:
    """ADR-0006 over the command line: two spellings of one input agree."""
    first, second = tmp_path / "a.stp", tmp_path / "b.stp"
    first.write_bytes(b"not STEP\n")
    second.write_bytes(b"not STEP either\n")
    forwards = _read_with_boards(tmp_path, monkeypatch, [first, second])
    backwards = _read_with_boards(tmp_path, monkeypatch, [second, first])
    assert len(forwards.diagnostics) == 2
    assert forwards == backwards


_EMPTY_STEP = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('empty','1970-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""


def _read_with_boards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boards: list[Path],
    *,
    prepared: dict[Path, StepDocument] | None = None,
) -> RawBoards:
    drill = _write_drill(tmp_path / "drill.json", None)
    case = tmp_path / "case.stp"
    serve = {case: _case_spanning(1.0, 2.0, 3.0)}
    serve.update(prepared or {})
    _stub_reader(monkeypatch, serve)
    return BoardSource(drill, boards, case).read()


# --------------------------------------------------------------------------
# The carrier normal's sign.
# --------------------------------------------------------------------------


def test_the_carrier_normal_points_the_way_the_parts_protrude(tmp_path, monkeypatch) -> None:
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=_board_document(towards=-1.0))
    assert raw.boards[0].carrier_w == (0.0, 0.0, -1.0)


def test_the_same_board_with_its_pin_the_other_way_gets_the_other_normal(
    tmp_path, monkeypatch
) -> None:
    """The control that makes the sign derived rather than assumed.

    ``carrier_frame`` publishes ``+z`` for both of these slabs, so a reader
    taking the frame's own sign passes the test above and fails this one; a
    reader hard-coding ``-z`` does the reverse.
    """
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=_board_document(towards=1.0))
    assert raw.boards[0].carrier_w == (0.0, 0.0, 1.0)


def test_a_pin_reaching_equally_both_ways_leaves_the_frames_own_normal(
    tmp_path, monkeypatch
) -> None:
    """Determinism at the tie: a symmetric part points at neither face.

    Nothing about the geometry prefers a side, so the answer must still be
    one answer -- the carrier frame's own published normal.
    """
    document = _document(
        [
            _substrate(),
            PlacedSolid(shape=_cylinder(3.0, 21.0, (10.0, 8.0, -10.0)), name="RV1",
                        colour=None, placement=None),
        ]
    )
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=document)
    assert raw.boards[0].carrier_w == (0.0, 0.0, 1.0)


def test_a_board_with_no_admissible_cylinder_at_all_keeps_that_normal_too(
    tmp_path, monkeypatch
) -> None:
    """Nothing protrudes, so nothing votes, and the answer is still defined."""
    document = _document(
        [
            _substrate(),
            PlacedSolid(shape=_block(2.0, 2.0, 2.0, (2.0, 2.0, -2.0)), name="U1",
                        colour=None, placement=None),
        ]
    )
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=document)
    assert raw.boards[0].carrier_w == (0.0, 0.0, 1.0)
    assert raw.boards[0].components[0].axis_xy_mm is None


def test_a_flipped_normal_carries_no_negative_zero(tmp_path, monkeypatch) -> None:
    """``-0.0`` equals ``0.0`` and serialises differently, so it never appears.

    Two spellings of one board would otherwise state two bases, which is
    the byte-identity ADR-0006 requires of geometrically equal inputs.
    """
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=_board_document(towards=-1.0))
    flipped = raw.boards[0].carrier_w
    assert flipped == (0.0, 0.0, -1.0)
    assert [math.copysign(1.0, value) for value in flipped[:2]] == [1.0, 1.0]


def test_the_carrier_basis_is_the_one_the_protrusion_axes_were_measured_in(
    tmp_path, monkeypatch
) -> None:
    """``u`` and ``v`` complete the outward normal, not the frame's own.

    A board reporting one basis while its axes were projected into another
    would place every part somewhere it is not.
    """
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0))
    board = raw.boards[0]
    u, v = basis_about(board.carrier_w)
    assert (board.carrier_u, board.carrier_v) == (u, v)
    axis = board.components[0].axis_xy_mm
    assert axis is not None
    assert axis == pytest.approx((_dot((10.0, 8.0, 0.0), u), _dot((10.0, 8.0, 0.0), v)))


def test_the_stack_is_measured_from_the_tip_along_that_normal(tmp_path, monkeypatch) -> None:
    """A 12 mm pin whose far end is the tip reads 0 to 12, not 12 to 0."""
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0))
    stack = raw.boards[0].components[0].stack
    assert [(c.radius_mm, c.depth_from_tip_min_mm, c.depth_from_tip_max_mm) for c in stack] == [
        (3.0, 0.0, 12.0)
    ]


def test_a_part_with_no_admissible_cylinder_has_no_axis(tmp_path, monkeypatch) -> None:
    """Never guessed at: it is reported downstream as ``unmatched-part``."""
    document = _document(
        [
            _substrate(),
            PlacedSolid(shape=_cylinder(3.0, 12.0, (10.0, 8.0, -11.0)), name="RV1",
                        colour=None, placement=None),
            PlacedSolid(shape=_block(2.0, 2.0, 2.0, (2.0, 2.0, 1.0)), name="U1",
                        colour=None, placement=None),
        ]
    )
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0),
                     board=document)
    by_name = {c.designator: c for c in raw.boards[0].components}
    assert by_name["U1"].axis_xy_mm is None and by_name["U1"].stack == ()
    assert by_name["RV1"].axis_xy_mm is not None


def test_the_board_box_is_the_substrate_and_not_the_whole_assembly(
    tmp_path, monkeypatch
) -> None:
    """The pin reaches to z = -11; the board's own box stops at z = 0."""
    raw = _read_with(tmp_path, monkeypatch, enclosure=None, model_spans=(1.0, 2.0, 3.0))
    board = raw.boards[0]
    low = tuple(min(a, b) for a, b in zip(board.corner_a_mm, board.corner_b_mm))
    high = tuple(max(a, b) for a, b in zip(board.corner_a_mm, board.corner_b_mm))
    assert low == pytest.approx((0.0, 0.0, 0.0))
    assert high == pytest.approx((30.0, 20.0, 1.0))


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Deliberately not ``stompmodel.frames.dot``, which the source uses.

    The test above predicts an axis this arithmetic computes; borrowing the
    production one would let a wrong dot product agree with itself and pass.
    The three copies in ``src/`` were consolidated; this fourth is the
    independent instrument that keeps the prediction a real one.
    """
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# --------------------------------------------------------------------------
# The committed fixture, through the real file reader.
# --------------------------------------------------------------------------


@pytest.mark.boards
def test_the_fixture_reads_end_to_end(tmp_path) -> None:
    """No stub anywhere: real files, the real reader, the real fixture."""
    drill = _write_drill(tmp_path / "drill.json", _1590B_NM)
    case = tmp_path / "case.stp"
    case.write_bytes(_written_case(112.40, 60.50, 31.00))
    raw = BoardSource(drill, [_FIXTURE], case).read()
    assert len(raw.boards) == 2
    assert _codes(raw) == ["multiple-boards"]
    assert [board.carrier_w for board in raw.boards] == [(0.0, 0.0, -1.0)] * 2
    assert {"SW1", "SW2"} <= {c.designator for b in raw.boards for c in b.components}


def _written_case(dx: float, dy: float, dz: float) -> bytes:
    from stompgeom.writer import render_step

    return render_step(
        build_document(
            [PlacedSolid(shape=_block(dx, dy, dz, (0.0, 0.0, 0.0)), name="BOX",
                         colour=None, placement=None)]
        ),
        title="case",
        timestamp="1970-01-01T00:00:00+00:00",
        originating_system="stompcollider tests",
    )
