"""The work tree ``BoardSource.scan`` reports, seen through a recording sink.

Written per package because each package's tests run in their own process;
``stompdrill`` has its own copy for the same reason. Only the *file* reader
is stubbed, matching ``test_source.py``: what it hands back is a real
kernel document, built the same way, so the geometry beneath the division
is never in question here -- only how the division counts the files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stompcollider.insert import Insertion
from stompcollider.match import Match
from stompcollider.model import DockData
from stompcollider.seat import Seat
from stompcollider.sources import BoardSource
from stompcollider.sources import step as source_step
from stompgeom.build import PlacedSolid, build_document
from stompgeom.step import StepDocument, read_step_document
from stompmodel.codec import to_document
from stompmodel.model import DrillData
from stompmodel.progress import track
from tests import tar
from tests.test_seat import _Stopping

__all__: list[str] = []


class Recorder:
    """Every update in order, for a test to read back."""

    def __init__(self) -> None:
        self.updates: list[tuple[float, tuple[str, ...]]] = []

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self.updates.append((position, path))

    @property
    def paths(self) -> list[tuple[str, ...]]:
        return [path for _position, path in self.updates]

    @property
    def positions(self) -> list[float]:
        return [position for position, _path in self.updates]


# --------------------------------------------------------------------------
# Synthetic geometry, built exactly as ``test_source.py`` builds it.
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
    return read_step_document(build_document(solids))


def _case_document() -> StepDocument:
    """A small block, standing in for a case model nobody measures here."""
    return _document(
        [PlacedSolid(shape=_block(10.0, 10.0, 10.0, (0.0, 0.0, 0.0)), name="BOX",
                     colour=None, placement=None)]
    )


def _board_document(designator: str) -> StepDocument:
    """One slab and one pin, named so a board file reads as one board."""
    return _document(
        [
            PlacedSolid(shape=_block(30.0, 20.0, 1.0, (0.0, 0.0, 0.0)), name="",
                        colour=None, placement=None),
            PlacedSolid(shape=_cylinder(3.0, 12.0, (10.0, 8.0, -11.0)), name=designator,
                        colour=None, placement=None),
        ]
    )


def _drill_document(path: Path) -> Path:
    """A real drill document with no case and no holes: nothing this suite reads."""
    path.write_text(json.dumps(to_document(DrillData())), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Harness.
# --------------------------------------------------------------------------


def _prepared(tmp_path: Path, *names: str) -> tuple[BoardSource, dict[Path, StepDocument]]:
    """A source over ``names`` board files, plus a drill document and a case."""
    drill = _drill_document(tmp_path / "drill.json")
    case_path = tmp_path / "case.stp"
    boards = [tmp_path / name for name in names]
    prepared = {case_path: _case_document()}
    prepared.update(
        {path: _board_document(f"RV{i}") for i, path in enumerate(boards, start=1)}
    )
    return BoardSource(drill, boards, case_path), prepared


def _stub(monkeypatch, prepared: dict[Path, StepDocument]) -> None:
    def reader(path: Path) -> StepDocument:
        return prepared[Path(path)]

    monkeypatch.setattr(source_step, "read_step", reader)


# --------------------------------------------------------------------------
# One labelled child per input file, boards in sorted order.
# --------------------------------------------------------------------------


def test_scan_labels_one_child_per_input_file_in_sorted_order(tmp_path, monkeypatch) -> None:
    """The drill document, the case model, then each board file, sorted.

    The board files are constructed here in reverse alphabetical order so
    that the order they were listed cannot be mistaken for the order
    ``scan`` reads them in: ADR-0006 requires the read order to come from
    the paths themselves, and this is what proves it against the labels.
    """
    source, prepared = _prepared(tmp_path, "b.stp", "a.stp")
    _stub(monkeypatch, prepared)

    recorder = Recorder()
    with track(recorder) as scope:
        source.scan(scope)

    labelled = [path[0] for path in recorder.paths if len(path) == 1]
    assert labelled == ["drill document", "case model", "a.stp", "b.stp"]
    assert recorder.positions == sorted(recorder.positions)


def test_a_slot_does_not_race_to_the_runs_own_end(tmp_path, monkeypatch) -> None:
    """The control: labelling a slot must not itself close it early.

    Every update stays below 1.0 until the run's own exit forces it there --
    a slot drawn and closed back to back with no work between (Task 2's
    original defect) would instead jump every position to the end at once.
    """
    source, prepared = _prepared(tmp_path, "only.stp")
    _stub(monkeypatch, prepared)

    recorder = Recorder()
    with track(recorder) as scope:
        source.scan(scope)
        settled = list(recorder.updates)

    assert any(position < 1.0 for position, _path in settled)


# --------------------------------------------------------------------------
# The count follows the file count: Step 4's discrimination.
# --------------------------------------------------------------------------


def test_the_board_child_count_follows_the_file_count(tmp_path, monkeypatch) -> None:
    """Two board files divide into two labelled children, not a fixed number.

    Not a set: two board files could in principle share a name (they cannot
    here, but a rule that happened to pass by coincidence of a set collapsing
    duplicates would prove nothing) -- this counts recorded events.
    """
    two_source, two_prepared = _prepared(tmp_path, "one.stp", "two.stp")
    _stub(monkeypatch, two_prepared)
    two_recorder = Recorder()
    with track(two_recorder) as scope:
        two_source.scan(scope)
    two_boards = [
        path[0] for path in two_recorder.paths
        if len(path) == 1 and path[0] not in ("drill document", "case model")
    ]
    assert len(two_boards) == 2

    three_dir = tmp_path / "three"
    three_dir.mkdir()
    three_source, three_prepared = _prepared(three_dir, "one.stp", "two.stp", "three.stp")
    _stub(monkeypatch, three_prepared)
    three_recorder = Recorder()
    with track(three_recorder) as scope:
        three_source.scan(scope)
    three_boards = [
        path[0] for path in three_recorder.paths
        if len(path) == 1 and path[0] not in ("drill document", "case model")
    ]
    assert len(three_boards) == 3


# --------------------------------------------------------------------------
# Exhaustion: the top-level division must not reopen after the run is done.
# --------------------------------------------------------------------------


def test_no_labelled_phase_reopens_after_the_run_reports_done(tmp_path, monkeypatch) -> None:
    """The division ``scan`` draws with bare ``next()`` must be exhausted.

    A division left suspended stays open at its last slot; its own
    ``finally`` fires only when the generator is collected, which would
    show up here as a labelled or root path appearing again after the run's
    own closing updates -- what this reads for directly.
    """
    source, prepared = _prepared(tmp_path, "a.stp", "b.stp")
    _stub(monkeypatch, prepared)

    recorder = Recorder()
    with track(recorder) as scope:
        source.scan(scope)
        settled = list(recorder.updates)

    empty_path_indices = [i for i, (_position, path) in enumerate(settled) if path == ()]
    assert empty_path_indices, "the run never closed its root division"
    last_root_close = empty_path_indices[-1]
    assert all(path == () for _position, path in settled[last_root_close:])


# --------------------------------------------------------------------------
# ``Match`` divides by board: Task 6.
# --------------------------------------------------------------------------


@pytest.mark.boards
def test_match_reports_one_step_per_board(tar_dock: DockData) -> None:
    """The count is ``data.boards``, known when the stage opens.

    Labels the slot itself before calling ``apply``, standing in for what
    ``Pipeline.run`` does at its call site -- that labelling is the
    pipeline's job, not ``Match``'s, so it must not move back into
    ``Match.apply``.
    """
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Match.weight):
            slot.label(Match.name)
            Match(tar.TOLERANCE).apply(tar_dock, slot)

    under_match = {p[1] for p in recorder.paths if len(p) > 1 and p[0] == "match"}
    assert len(under_match) == len(tar_dock.boards)
    assert recorder.positions == sorted(recorder.positions)


# --------------------------------------------------------------------------
# ``Seat`` divides boards, then placements, then the insertion search's own
# three phases: Task 7.
# --------------------------------------------------------------------------


@pytest.mark.boards
def test_seat_reports_boards_then_placements(tar_matched: DockData, tar_cavity) -> None:
    """Both counts are known at entry: boards from the input, placements
    from ``Match``. Labelled the way a pipeline would, per Decision 3 --
    ``Seat`` never labels its own top slot."""
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Seat.weight):
            slot.label(Seat.name)
            Seat(tar_cavity).apply(tar_matched, slot)

    boards = {p[1] for p in recorder.paths if len(p) > 1 and p[0] == "seat"}
    assert len(boards) == len(tar_matched.placements)
    for ordinal, placements in tar_matched.placements.items():
        under = {
            p[2]
            for p in recorder.paths
            if len(p) > 2 and p[0] == "seat" and p[1] == f"board {ordinal}"
        }
        assert len(under) == len(placements)


@pytest.mark.boards
def test_the_insertion_search_divides_into_its_three_phases(
    tar_matched: DockData, tar_cavity
) -> None:
    """Coarse, fine and bisection, weighted by shape rather than duration."""
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Seat.weight):
            slot.label(Seat.name)
            Seat(tar_cavity).apply(tar_matched, slot)

    phases = {p[3] for p in recorder.paths if len(p) > 3 and p[0] == "seat"}
    assert {"coarse", "fine", "bisect"} <= phases


@pytest.mark.boards
def test_a_search_that_stops_early_still_closes_its_placement(
    tar_matched: DockData,
) -> None:
    """The counts are upper bounds, so a node must not stall short of its end.

    ``_Stopping`` answers every query with a single fixed ``Insertion`` and
    never touches the ``scope`` it is handed -- the cheapest possible
    stand-in for a search that returns almost at once. The parent's own
    advance is what still carries each placement's position to its span's
    end, and this is the branch where that rule earns its place.
    """
    recorder = Recorder()
    stopping = _Stopping(Insertion(None, obstruction="wall"))  # blocked at entry
    with track(recorder) as scope:
        for slot in scope.parts(Seat.weight):
            slot.label(Seat.name)
            Seat(stopping).apply(tar_matched, slot)

    assert recorder.positions[-1] == 1.0
    assert recorder.positions == sorted(recorder.positions)
