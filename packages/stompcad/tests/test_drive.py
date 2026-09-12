"""The driver's own design: intermediates held, steps reported once, options replaceable.

Spec decision 7 says intermediates are what let plan C run a single step
again; these tests pin that design directly rather than only inferring it
from the byte-identity acceptance test in ``test_drive_drill.py``.
"""

from __future__ import annotations

import inspect
import io
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad import drive
from stompcad.drive import _STEP_HOLDS, Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.present import Choice, PlainWriter, Question
from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData
from stompmodel.progress import NO_PROGRESS, track
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, NullSink, case_model

__all__: list[str] = []


def _refuse_to_read(panel: object) -> object:
    """Stands in for the artwork reader, where reading again would be the defect."""
    raise AssertionError(f"the artwork was read again: {panel}")


def _options() -> RunOptions:
    """A minimal, valid ``RunOptions``: no case model, no emitted targets."""
    return RunOptions(
        panel=TAR_AI,
        boards=(),
        case="1590B",
        case_model=None,
        panel_reference=PANEL_REFERENCE,
        targets=(),
    )


@pytest.fixture
def drill_and_dock_run() -> Driver:
    """A driver that has run both halves, so its intermediates are populated.

    Gated behind the same flags the rest of the dock tests use, because it
    reads the board fixture and the cached enclosure model.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    options = RunOptions(
        panel=TAR_AI,
        boards=(TAR_PCB,),
        case="1590B",
        case_model=model,
        panel_reference="RV*,SW*",
        targets=(),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run(scope)
    return driver


class _RecordingPresentation:
    """Records every ``finish_step`` call, in the order the driver made it."""

    def __init__(self) -> None:
        self.began: RunPlan | None = None
        self.finished: list[tuple[Step, str]] = []

    def begin(self, plan: RunPlan) -> None:
        self.began = plan

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        self.finished.append((step, outcome))

    def ask(self, question: object) -> str:
        raise AssertionError("run_drill must not ask a question of its own")

    def report(self, lines: object) -> None:
        return None


class _Recording(PlainWriter):
    """A writer that keeps the step lines rather than printing them."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__(io.StringIO())
        self._lines = lines

    def finish_step(self, step: Step, outcome: str) -> None:
        self._lines.append(f"{step.key}: {outcome}")


class _Answering(PlainWriter):
    """A writer that answers every question with one prepared candidate.

    The answer defaults to nothing, so a subclass that picks from the
    question itself passes no value its own ``ask`` would ignore.
    """

    def __init__(self, asked: list[Choice], answer: str = "") -> None:
        super().__init__(io.StringIO())
        self._asked = asked
        self._answer = answer

    def ask(self, question: Question) -> str:
        self._asked.append(Choice(prompt=question.prompt, candidates=question.candidates))
        return self._answer


class _AnsweringRecorder(_Answering):
    """As above, and keeping the step lines so a double report would show."""

    def __init__(self, lines: list[str], answer: str) -> None:
        super().__init__([], answer)
        self._lines = lines

    def finish_step(self, step: Step, outcome: str) -> None:
        self._lines.append(f"{step.key}: {outcome}")


class _AnsweringEach(_Answering):
    """Answers every question with one of the candidates that question offered.

    ``empty-group`` is raised per board, so a run over a file holding two
    of them asks twice and one prepared answer would leave the second gap
    exactly as it was -- which is a stub that never terminates, not a
    driver that failed to resolve anything.
    """

    def __init__(self, lines: list[str], asked: list[Choice]) -> None:
        super().__init__(asked)
        self._lines = lines

    def ask(self, question: Question) -> str:
        super().ask(question)
        return question.candidates[0]

    def finish_step(self, step: Step, outcome: str) -> None:
        self._lines.append(f"{step.key}: {outcome}")


class _PositionLog:
    """Every position a run reported, tagged with the questions asked by then.

    A sink sees nothing of the resolution loop, so the count of questions
    already asked is what puts each update on one side of an answer or the
    other. ``NullSink`` discards the same calls.
    """

    def __init__(self, asked: list[Choice]) -> None:
        self._asked = asked
        self.updates: list[tuple[int, float, tuple[str, ...]]] = []

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self.updates.append((len(self._asked), position, path))


def test_run_options_survives_replace() -> None:
    """Plan C's stated mechanism for feeding an answer back: ``dataclasses.replace``."""
    original = _options()

    changed = replace(original, case="1590B2")

    assert changed.case == "1590B2"
    assert original.case == "1590B"  # frozen: replace never mutates the source
    assert changed.panel == original.panel
    assert changed.boards == original.boards
    assert changed.case_model == original.case_model
    assert changed.panel_reference == original.panel_reference
    assert changed.targets == original.targets


def test_presentation_sees_each_drill_step_finish_once_in_plan_order() -> None:
    """Spec decision 4: a step credits its span only once, on completion.

    The plan announced is the one about to run, not the nine-step plan the
    driver was built with: a drill half divides the span among its own four
    steps, so the bar is not weighed against five it never intends to take.
    """
    presentation = _RecordingPresentation()
    driver = Driver(DRILL_AND_DOCK, presentation, _options())

    with track(NullSink()) as scope:
        driver.run_drill(scope)

    assert presentation.began is not None
    assert presentation.began.steps == DRILL_AND_DOCK.steps[:4]
    finished_keys = [step.key for step, _outcome in presentation.finished]
    assert finished_keys == ["read-panel", "quantise", "drill", "write-case"]


def test_the_driver_holds_its_intermediates() -> None:
    """The reason for the attribute design, enforced rather than only described."""
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())

    assert driver._raw is None
    assert driver._quantised is None
    assert driver._drilled is None

    with track(NullSink()) as scope:
        result = driver.run_drill(scope)

    assert driver._raw is not None
    assert driver._quantised is not None
    assert driver._drilled is result


def test_retry_runs_one_step_again_over_the_intermediates_already_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 4's retry, and the reason the driver holds its intermediates.

    Plan C feeds an answer back through ``dataclasses.replace`` and asks for
    the step that stopped. A fresh ``Driver`` over the replaced options would
    re-parse the artwork and reload the case model instead -- the cost these
    attributes exist to avoid -- so reading the artwork again is made a
    failure here rather than merely unexpected.
    """
    presentation = _RecordingPresentation()
    driver = Driver(DRILL_AND_DOCK, presentation, _options())
    with track(NullSink()) as scope:
        driver.run_drill(scope)
    raw, quantised = driver._raw, driver._quantised
    presentation.finished.clear()
    monkeypatch.setattr(drive, "AiPdfSource", _refuse_to_read)

    with track(NullSink()) as scope:
        again = driver.retry("quantise", replace(_options(), case="1590BB"), scope)

    assert [step.key for step, _outcome in presentation.finished] == ["quantise"]
    assert driver._raw is raw, "the artwork was parsed again"
    assert again is driver._quantised and again is not quantised
    # The revised option was consumed, not merely accepted: the tar footprint
    # is no 1590BB, and only the retried quantiser could say so.
    assert [finding.code for finding in again.diagnostics] == ["unmatched-enclosure"]


def test_retry_refuses_a_step_whose_input_the_driver_does_not_hold() -> None:
    """``retry`` names ``quantise``, ``drill`` and ``read-boards``; other keys are refused."""
    driver = Driver(DRILL_AND_DOCK, _RecordingPresentation(), _options())

    with pytest.raises(ValueError):
        driver.retry("seat", _options(), NO_PROGRESS)

    with pytest.raises(ValueError):
        driver.retry("quantise", _options(), NO_PROGRESS)


def test_retry_refuses_a_revised_field_the_named_step_cannot_honour() -> None:
    """A revision the step cannot apply is a usage error, not a silent no-op.

    ``retry`` takes a whole ``RunOptions`` but one step reads only part of
    it: ``drill`` never looks at ``case_model``, so accepting a revised one
    would leave plan C believing an answer took effect when nothing read it.
    Refused the way ``stompcollider`` refuses ``--place`` -- parsed, judged,
    rejected with the reason -- and the driver is left exactly as it was.
    """
    presentation = _RecordingPresentation()
    driver = Driver(DRILL_AND_DOCK, presentation, _options())
    with track(NullSink()) as scope:
        driver.run_drill(scope)
    held, drilled = driver._options, driver._drilled
    presentation.finished.clear()

    with pytest.raises(ValueError) as refusal:
        driver.retry("drill", replace(_options(), case_model=Path("enclosure.stp")), NO_PROGRESS)

    assert "case_model" in str(refusal.value)
    assert "read-panel" in str(refusal.value), "the refusal must name the step that reads it"
    assert driver._options is held, "the refused options replaced the ones the driver holds"
    assert driver._drilled is drilled
    assert presentation.finished == [], "a refused retry reported a step as finished"


def test_retrying_a_step_discards_what_a_later_step_produced() -> None:
    """Re-running a step supersedes every intermediate computed after it.

    ``_drilled`` was computed from the options this retry replaces, so a
    later ``run_dock`` reading it would dock boards against a drill document
    the revised options contradict. Dropping it makes the staleness a
    missing value rather than a wrong one.
    """
    driver = Driver(DRILL_AND_DOCK, _RecordingPresentation(), _options())
    with track(NullSink()) as scope:
        driver.run_drill(scope)
    assert driver._drilled is not None, "the control: run_drill must leave one to discard"

    with track(NullSink()) as scope:
        driver.retry("quantise", replace(_options(), case="1590BB"), scope)

    assert driver._drilled is None, "the drilled data still describes the superseded options"


@pytest.mark.boards
@pytest.mark.hammond
def test_the_dock_half_holds_what_a_retry_would_need(drill_and_dock_run: Driver) -> None:
    """Decision 8: the filter runs again over boards already scanned.

    Everything that reads a file is gone with the temporary directory by
    the time the read step finishes, so what is held must be enough to
    re-run the filter without one.
    """
    driver = drill_and_dock_run

    assert driver._docked is not None
    assert driver._scan is not None
    assert driver._dock_pipeline is not None
    assert driver._dock_data is not None


@pytest.mark.boards
@pytest.mark.hammond
def test_every_dock_hold_is_cleared_by_a_retry_of_an_earlier_step(
    drill_and_dock_run: Driver,
) -> None:
    """A value computed under superseded options must not outlive them."""
    driver = drill_and_dock_run

    driver._discard_after("quantise")

    for attribute in _STEP_HOLDS["read-boards"]:
        assert getattr(driver, attribute) is None, attribute


def test_the_filter_is_not_applied_before_it_is_held() -> None:
    """``_docked`` is the boards as read, so a revised filter starts from them."""
    source = inspect.getsource(Driver._read_boards)
    assert "admit(" not in source, "the filter belongs after the parse, not inside it"


@pytest.mark.boards
@pytest.mark.hammond
def test_the_read_step_runs_again_over_the_boards_already_scanned(
    drill_and_dock_run: Driver,
) -> None:
    """Decision 8: the filter runs again, the parse does not.

    The temporary the boards were read from is long gone, so a retry that
    reached for a file would fail rather than merely be slow.
    """
    driver = drill_and_dock_run
    before = driver._scan

    with track(NullSink()) as scope:
        retried = driver.retry(
            "read-boards", replace(driver._options, panel_reference="RV*,SW*,D1"), scope
        )

    assert driver._scan is before, "the boards were read again"
    assert retried is driver._dock_data


@pytest.mark.boards
@pytest.mark.hammond
def test_a_retry_of_the_read_step_refuses_a_revised_board_list(
    drill_and_dock_run: Driver, tmp_path: Path
) -> None:
    """Accepted and ignored is the one outcome a revision may not have."""
    driver = drill_and_dock_run

    with track(NullSink()) as scope, pytest.raises(ValueError, match="boards"):
        driver.retry(
            "read-boards", replace(driver._options, boards=(tmp_path / "other.stp",)), scope
        )


@pytest.mark.boards
@pytest.mark.hammond
def test_a_retried_step_reports_once_and_a_rerun_reports_not_at_all(
    drill_and_dock_run: Driver,
) -> None:
    """Decision 4: a step credits its span only when it succeeds."""
    driver = drill_and_dock_run
    lines: list[str] = []
    driver._presentation = _Recording(lines)
    revised = replace(driver._options, panel_reference="RV*,SW*,D1")

    with track(NullSink()) as scope:
        driver._rerun("read-boards", revised, scope)
    assert lines == []

    with track(NullSink()) as scope:
        driver.retry("read-boards", revised, scope)
    assert len(lines) == 1


def _undeclared() -> RunOptions:
    """Options the tar fixture ties three parts under: no case is declared."""
    return RunOptions(
        panel=TAR_AI,
        boards=(),
        case=None,
        case_model=None,
        panel_reference="RV*",
        targets=(),
    )


def test_a_tie_is_asked_about_and_the_answer_runs_quantise_again() -> None:
    """The tar fixture ties three parts when no case is declared.

    Decision 6's first row: the candidates are the tied parts, and the
    answer declares the case that ends the tie.
    """
    asked: list[Choice] = []
    driver = Driver(DRILL_AND_DOCK, _Answering(asked, "1590B"), _undeclared())

    with track(NullSink()) as scope:
        drill, _ = driver.run(scope)

    assert len(asked) == 1
    assert "1590B" in asked[0].candidates
    assert not [d for d in drill.diagnostics if d.code == "ambiguous-enclosure"]


def test_a_step_that_stops_to_ask_credits_nothing_until_it_answers() -> None:
    """Decision 4: one line per step, reported only once it has succeeded."""
    lines: list[str] = []
    driver = Driver(DRILL_AND_DOCK, _AnsweringRecorder(lines, "1590B"), _undeclared())

    with track(NullSink()) as scope:
        driver.run(scope)

    quantise_lines = [line for line in lines if line.startswith("quantise")]
    assert len(quantise_lines) == 1, f"quantise reported {len(quantise_lines)} times"
    assert quantise_lines[0] == "quantise: 8 holes, 2 tools", quantise_lines[0]


def test_a_gap_is_raised_before_its_step_credits_a_leaf() -> None:
    """Decision 8: the step that stopped to ask has credited nothing when it does.

    A retried step is given the same span a second time, so a leaf counted
    before the question would have to be either counted twice or taken back.
    Only the sink witnesses that: ``finish_step`` says a step ended, while a
    position says work inside one was counted.
    """
    asked: list[Choice] = []
    log = _PositionLog(asked)
    driver = Driver(DRILL_AND_DOCK, _Answering(asked, "1590B"), _undeclared())

    with track(log) as scope:
        driver.run(scope)

    assert len(asked) == 1, "the control: an undeclared tie must raise the gap"
    positions = [position for _asked, position, _path in log.updates]
    assert positions == sorted(positions), f"a reported position retreated: {positions}"
    label = DRILL_AND_DOCK.steps[1].label
    entered = next(
        position for count, position, path in log.updates if count == 0 and path == (label,)
    )
    unanswered = [position for count, position, _path in log.updates if count == 0]
    assert max(unanswered) == entered, "quantise credited a leaf before its gap was answered"


def test_a_run_that_declares_its_case_asks_nothing() -> None:
    """A control: no gap, no question, and the same lines as before."""
    asked: list[Choice] = []
    options = replace(_undeclared(), case="1590B")
    driver = Driver(DRILL_AND_DOCK, _Answering(asked, "unused"), options)

    with track(NullSink()) as scope:
        driver.run(scope)

    assert asked == []


@pytest.mark.hammond
def test_the_case_model_s_filename_ends_the_tie_the_drill_half_alone() -> None:
    """``_quantise`` must thread ``case_model`` through, not merely accept it.

    The tar fixture ties three parts undeclared; the cached model's own
    filename resolves it, and the run reports the part as inferred rather
    than declared -- proof this path reaches ``IdentifyHammondFootprint``
    rather than being silently dropped.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    options = replace(_undeclared(), case_model=model)
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)

    with track(NullSink()) as scope:
        drill = driver.run_drill(scope)

    assert drill.enclosure is not None
    assert drill.enclosure.selected_part == "1590B"
    assert "inferred-enclosure" in [d.code for d in drill.diagnostics]


def test_promote_warnings_reaches_the_gap_finding_path() -> None:
    """The flag travels from ``__init__`` to ``_gap_in``, not only into ``resolve``.

    Both resolvable codes are raised at ERROR today, so promotion changes no
    live run; this proves the wire the constructor argument is for, ahead of
    a warning-level resolvable code ever existing.
    """
    tied = Diagnostic.warning(
        "ambiguous-enclosure", "tied", data=(("candidates", "1590B, 1590B2"),)
    )
    data = DrillData(diagnostics=(tied,))
    passed_over = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())
    promoting = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options(), True)

    assert passed_over._gap_in(data) is None
    assert promoting._gap_in(data) is not None


@pytest.mark.boards
@pytest.mark.hammond
def test_a_board_admitting_nothing_is_asked_about_and_the_read_step_credits_once(
    drill_and_dock_run: Driver,
) -> None:
    """Decision 6's second row, and decision 4 over the dock half's own gap.

    ``empty-group`` offers the board its own designators, and the answer
    widens the expression rather than replacing it -- so the filter runs
    again over boards already scanned, and the step is credited once
    however many gaps were answered in turn.
    """
    driver = drill_and_dock_run
    lines: list[str] = []
    asked: list[Choice] = []
    driver._presentation = _AnsweringEach(lines, asked)
    driver._options = replace(driver._options, panel_reference="ZZ*")
    empty = driver._admit()
    assert "empty-group" in [d.code for d in empty.diagnostics], "the control: no gap to resolve"
    assert driver._docked is not None

    with track(NullSink()) as scope:
        settled = driver._settled("read-boards", empty, "the unresolved outcome", scope)

    assert len(asked) == len(driver._docked.boards), "each board admitting nothing asks once"
    assert lines == ["read-boards: 2 board(s)"], "the credited outcome is the successful run's"
    assert not [d for d in settled.diagnostics if d.code == "empty-group"]


@pytest.mark.boards
@pytest.mark.hammond
def test_a_whole_run_resolves_the_dock_half_s_gap_and_credits_the_read_step_once() -> None:
    """The same gap, through the run rather than the loop it is raised in.

    Decision 4 binds where the hook sits, so the dock half's own step must
    reach it: a run that asks and answers still leaves the read step one
    line, and no ``empty-group`` behind it.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    lines: list[str] = []
    asked: list[Choice] = []
    options = RunOptions(
        panel=TAR_AI,
        boards=(TAR_PCB,),
        case="1590B",
        case_model=model,
        panel_reference="ZZ*",
        targets=(),
    )
    driver = Driver(DRILL_AND_DOCK, _AnsweringEach(lines, asked), options)

    with track(NullSink()) as scope:
        _drill, dock = driver.run(scope)

    assert asked != [], "the control: the expression must admit nothing to raise the gap"
    assert [line for line in lines if line.startswith("read-boards")] == ["read-boards: 2 board(s)"]
    assert dock is not None
    assert not [d for d in dock.diagnostics if d.code == "empty-group"]
