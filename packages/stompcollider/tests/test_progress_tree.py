"""The work tree ``BoardSource.scan`` reports, seen through a recording sink.

Written per package because each package's tests run in their own process;
``stompdrill`` has its own copy for the same reason. Only the *file* reader
is stubbed, matching ``test_source.py``: what it hands back is a real
kernel document, built the same way, so the geometry beneath the division
is never in question here -- only how the division counts the files.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from stompcollider import clash
from stompcollider.clash import Clashes
from stompcollider.insert import Insertion, contact_depth
from stompcollider.match import Match
from stompcollider.model import Board, DockData, Placement
from stompcollider.seat import Seat
from stompcollider.sources import BoardSource
from stompcollider.sources import step as source_step
from stompgeom.build import PlacedSolid, build_document
from stompgeom.step import StepDocument, StepSolid, read_step_document
from stompmodel.codec import to_document
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, DrillData
from stompmodel.progress import NO_PROGRESS, Scope, track
from stompmodel.units import Nanometre, nm_from_mm
from tests import tar
from tests.conftest import _Stopping

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


# --------------------------------------------------------------------------
# ``contact_depth``'s own per-sample subdivision, exercised directly and
# without a kernel: each bound phase's slot count comes from its own
# materialised sample list, so a wrong count is a ``ValueError`` from
# ``strict=True`` before any assertion runs, never a silent miscount.
# --------------------------------------------------------------------------


def _blocked_partway(depth: Nanometre) -> bool:
    return depth >= Nanometre(5_000_000)


def _never_blocked(_depth: Nanometre) -> bool:
    return False


def _always_blocked(_depth: Nanometre) -> bool:
    return True


def test_contact_depth_closes_its_own_span_whichever_phase_stops_it() -> None:
    """Each of the search's early exits still reaches the call's own end.

    Proved directly against ``contact_depth`` rather than through ``Seat``:
    ``_Stopping`` never calls it at all, so it cannot speak to whether the
    phases *this* function now subdivides still close correctly. The three
    rows are the three exits the brief names, in the same order.
    """
    cases = (
        ("entry at the limit", _never_blocked, Nanometre(10_000_000), Nanometre(10_000_000)),
        ("blocked entry pose", _always_blocked, Nanometre(0), Nanometre(10_000_000)),
        ("clear path", _never_blocked, Nanometre(0), Nanometre(10_000_000)),
        ("runs all three phases", _blocked_partway, Nanometre(0), Nanometre(10_000_000)),
    )
    for label, blocked, entry_nm, limit_nm in cases:
        recorder = Recorder()
        with track(recorder) as scope:
            contact_depth(
                blocked, entry_nm, limit_nm, Nanometre(2_000_000), Nanometre(50_000), scope
            )
        assert recorder.positions[-1] == 1.0, label
        assert recorder.positions == sorted(recorder.positions), label


def test_a_full_search_still_visits_all_three_phases_directly() -> None:
    """The control beside it: the run above must actually reach every phase,
    not merely finish -- a call that skipped ``fine``/``bisect`` outright
    would still satisfy "closes at 1.0" for the wrong reason."""
    recorder = Recorder()
    with track(recorder) as scope:
        contact_depth(
            _blocked_partway,
            Nanometre(0),
            Nanometre(10_000_000),
            Nanometre(2_000_000),
            Nanometre(50_000),
            scope,
        )

    names = {p[0] for p in recorder.paths if len(p) == 1}
    assert {"coarse", "fine", "bisect"} <= names


class _ShortYieldingScope:
    """A ``Scope`` double whose ``steps`` starves any loop needing more than one slot.

    ``parts`` and ``label`` behave exactly like ``NullScope``; only ``steps``
    under-yields. A progress observer is not allowed to change the geometric
    answer, so a search driven by "does the scope still have slots left"
    rather than by its own convergence would be shortened by this double.
    """

    def steps(self, count: int) -> Iterator[Scope]:
        return iter([self] * min(count, 1))

    def parts(self, *weights: float) -> Iterator[Scope]:
        return iter([self] * len(weights))

    def label(self, name: str) -> None:
        return None


def _blocked_above_one_million(depth: Nanometre) -> bool:
    return depth >= Nanometre(1_000_000)


def test_a_short_yielding_scope_cannot_shorten_the_bisection() -> None:
    """The bisection's own convergence must bound its iterations, not ``steps``.

    ``bracket_nm.bit_length()`` is only ever an upper bound on the halvings
    needed; the loop must keep halving until ``found - clear <= 1`` however
    many scopes the observer handed back. The fixture gives coarse and fine
    exactly one sample each, so ``min(count, 1)`` still matches what they
    ask for; only bisect needs more than this double's single scope.
    """
    args = (
        _blocked_above_one_million,
        Nanometre(0),
        Nanometre(10_000_000),
        Nanometre(10_000_000),
        Nanometre(6_000_000),
    )
    baseline = contact_depth(*args, NO_PROGRESS)
    starved = contact_depth(*args, _ShortYieldingScope())
    assert starved == baseline


# --------------------------------------------------------------------------
# ``Clashes`` divides both its stages: Task 8. Stage one is boards then
# placements, exactly as ``Seat``'s own division reads; stage two is the
# subtle one -- the *distinct* board-pair seatings ``candidates`` admits,
# not the combinations the product tries, because ``_between`` memoises
# and most of those are cache hits.
# --------------------------------------------------------------------------


def _clashes_leaves(dock: DockData, solids) -> list[tuple[str, ...]]:
    """Every path recorded under a pipeline-style ``clashes`` slot."""
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Clashes.weight):
            slot.label(Clashes.name)
            Clashes(*solids).apply(dock, slot)
    return [p for p in recorder.paths if len(p) > 1 and p[0] == "clashes"]


@pytest.mark.boards
def test_clashes_reports_boards_then_placements(tar_seated: DockData, tar_solids) -> None:
    """Stage one: both counts are known at entry, exactly as ``Seat``'s are."""
    paths = _clashes_leaves(tar_seated, tar_solids)

    boards = {p[1] for p in paths if "×" not in p[1]}
    assert len(boards) == len(tar_seated.placements)
    for ordinal, placements in tar_seated.placements.items():
        under = {p[2] for p in paths if len(p) > 2 and p[1] == f"board {ordinal}"}
        assert len(under) == len(placements)


# --------------------------------------------------------------------------
# Stage two needs a scene where a board pair genuinely recurs. The tar
# fixture cannot give one: two boards is one pair, and product() over one
# pair's own candidates never repeats a request, so every ``_between`` call
# there is a first-ever (a miss) -- gating on the miss would look identical
# to labelling every call. Three boards with two candidates each gives
# three pairs and eight combinations; pair (1, 2) is asked again by every
# combination that only varies board 3, which is what makes a hit real.
# Built the same kernel-backed-but-synthetic way test_clash.py's own scenes
# are (small OCP boxes, no STEP file, no --boards): with an empty case
# tuple neither board ever meets the case, so every placement is cavity-
# clean and both of a board's candidates tie on shortfall (rank_key falls
# through to the transform, both at z = 0), which is what admits both.
# --------------------------------------------------------------------------


def _three_board_two_candidate_scene() -> (
    tuple[DockData, tuple[StepSolid, ...], dict[int, tuple[StepSolid, ...]]]
):
    """Three boards, two tied-shortfall candidates each, spaced apart on
    ``y`` so no pair of boards ever shares a box -- what is counted is the
    division, not which pairs happen to clash. Returns the raw solids
    rather than a built ``Clashes``, because ``Clashes`` memoises: two
    measurements against one instance would answer the second from cache
    alone, with nothing left to label."""
    frame = CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )
    boards = tuple(
        Board(
            ordinal=ordinal,
            designators=(f"J{ordinal}",),
            extent_nm=(nm_from_mm(10.0), nm_from_mm(10.0), nm_from_mm(2.0)),
            carrier=frame,
            components=(),
        )
        for ordinal in (1, 2, 3)
    )
    placements = {
        ordinal: tuple(
            Placement(
                rank=rank,
                x_nm=nm_from_mm(x_mm),
                y_nm=Nanometre(0),
                z_nm=Nanometre(0),
                theta_deg=0.0,
                correspondence=(),
                clashes=(),
            )
            for rank, x_mm in enumerate((0.0, 50.0), start=1)
        )
        for ordinal in (1, 2, 3)
    }
    data = DockData(
        case=CaseRegistration("1590BB", CaseFace.BOX, "case.stp", FaceFrame(frame)),
        boards=boards,
        placements=placements,
    )
    board_solids: dict[int, tuple[StepSolid, ...]] = {
        ordinal: (StepSolid(f"B{ordinal}", _clash_box((0.0, 300.0 * ordinal, 0.0), 10, 10, 4)),)
        for ordinal in (1, 2, 3)
    }
    case_solids: tuple[StepSolid, ...] = ()
    return data, case_solids, board_solids


def _clash_box(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _distinct_pair_leaves(
    data: DockData,
    case_solids: tuple[StepSolid, ...],
    board_solids: dict[int, tuple[StepSolid, ...]],
) -> set[str]:
    """A fresh ``Clashes`` every call: its memo must not leak between
    measurements, or a second call answers entirely from cache."""
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Clashes.weight):
            slot.label(Clashes.name)
            Clashes(case_solids, board_solids).apply(data, slot)
    return {
        p[1]
        for p in recorder.paths
        if len(p) > 1 and p[0] == "clashes" and "×" in p[1]
    }


def test_the_assembly_leaves_match_the_distinct_candidate_pairs() -> None:
    """Three boards, two candidates each, three pairs: 3 x (2 x 2) = 12.

    Pinned against the independently-derived formula, not the fixture's own
    ``_between`` call count (24, below) -- a wrong formula that still
    happens to gate correctly would otherwise pass unnoticed.
    """
    data, case_solids, board_solids = _three_board_two_candidate_scene()

    assert len(_distinct_pair_leaves(data, case_solids, board_solids)) == 12


def test_the_assembly_search_labels_only_cache_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The product tries 8 combinations across 3 pairs -- 24 pairwise
    checks -- but 12 of those requests repeat a pair already answered.
    Counting every call, not only the miss, would report 24 rather than the
    12 this module's other test pins."""
    data, case_solids, board_solids = _three_board_two_candidate_scene()
    calls = 0
    original = Clashes._between

    def counting(self: Clashes, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Clashes, "_between", counting)
    leaves = _distinct_pair_leaves(data, case_solids, board_solids)

    assert calls == 24
    assert len(leaves) == 12


def test_the_assembly_search_advances_fewer_slots_when_the_product_is_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``distinct`` is computed from ``candidates`` before the search runs
    and does not depend on the limit; the *advances* do, because a
    truncated product asks fewer of its 12 possible pairs. A limit of 4
    (below the 8 possible combinations) tries only the four combinations
    that fix board 1's first candidate, which touch 8 of the 12 pairs --
    fewer, not the same 12, and not the 24 raw calls either."""
    data, case_solids, board_solids = _three_board_two_candidate_scene()
    baseline = len(_distinct_pair_leaves(data, case_solids, board_solids))
    assert baseline == 12

    monkeypatch.setattr(clash, "_COMBINATION_LIMIT", 4)
    truncated = len(_distinct_pair_leaves(data, case_solids, board_solids))

    assert truncated == 8
    assert truncated < baseline


class _StepsRecordingScope:
    """A pass-through ``Scope`` that records every ``steps(n)`` call's ``n``.

    Recording rather than inferring: a mutant can size a division wrongly
    and still land on the same *observed* leaf count on one particular
    scene (a truncated product can coincidentally touch as many distinct
    pairs as a correctly-sized-but-truncated search leaves undrawn), so
    the size fed to ``scope.steps(...)`` has to be read directly, not
    guessed back from how many labels happened to land.
    """

    def __init__(self, inner: Scope, calls: list[int]) -> None:
        self._inner = inner
        self._calls = calls

    def steps(self, count: int) -> Iterator[Scope]:
        self._calls.append(count)
        return (_StepsRecordingScope(child, self._calls) for child in self._inner.steps(count))

    def parts(self, *weights: float) -> Iterator[Scope]:
        return (
            _StepsRecordingScope(child, self._calls) for child in self._inner.parts(*weights)
        )

    def label(self, name: str) -> None:
        self._inner.label(name)


def _stage_two_division_size(
    data: DockData,
    case_solids: tuple[StepSolid, ...],
    board_solids: dict[int, tuple[StepSolid, ...]],
) -> int:
    """The ``n`` stage two's own ``scope.steps(n)`` call was opened with.

    The *last* recorded ``steps()`` call: ``apply`` always finishes stage
    one's board division (one call, size 3) and every board's placement
    division (three calls, size 2 each) before stage two ever calls
    ``steps`` at all, so the final entry in call order is always this one,
    whatever value it carries.
    """
    calls: list[int] = []
    recorder = Recorder()
    with track(recorder) as scope:
        for slot in scope.parts(Clashes.weight):
            wrapped = _StepsRecordingScope(slot, calls)
            wrapped.label(Clashes.name)
            Clashes(case_solids, board_solids).apply(data, wrapped)
    return calls[-1]


def test_the_assembly_divisions_size_is_fixed_by_candidates_not_by_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The division's size -- what ``scope.steps(...)`` is opened with, 3 x
    (2 x 2) = 12 -- must come from ``candidates`` alone and stay the same
    whether or not the product is truncated; only the *advances* (proved
    above) may differ. A mutant that sizes the division from the truncated
    ``tried`` list instead reproduces this scene's 12-then-8 leaf counts
    exactly, which is why the size itself has to be read directly rather
    than inferred from how many labels landed."""
    data, case_solids, board_solids = _three_board_two_candidate_scene()

    untruncated = _stage_two_division_size(data, case_solids, board_solids)
    monkeypatch.setattr(clash, "_COMBINATION_LIMIT", 4)
    truncated = _stage_two_division_size(data, case_solids, board_solids)

    assert untruncated == truncated == 12


@pytest.mark.boards
def test_the_assembly_search_reaches_the_tar_fixtures_one_real_pair(
    tar_seated: DockData, tar_solids
) -> None:
    """The control against real geometry: the tar fixture has one board
    pair with two admitted candidates each, so it cannot exercise a cache
    hit (see the module note above) -- it can only show the formula still
    gives 2 x 2 = 4 on real boards, not only on the synthetic scene."""
    pairs = {p[1] for p in _clashes_leaves(tar_seated, tar_solids) if "×" in p[1]}
    assert len(pairs) == 4
