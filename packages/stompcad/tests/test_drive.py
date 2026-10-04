"""The driver's own design: intermediates held, steps reported once, options replaceable.

Spec decision 7 says intermediates are what let plan C run a single step
again; these tests pin that design directly rather than only inferring it
from the byte-identity acceptance test in ``test_drive_drill.py``.
"""

from __future__ import annotations

import inspect
import io
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest

from stompcad import cli, drive, manifest
from stompcad.drive import _STEP_HOLDS, Driver, Project, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.present import Choice, PlainWriter, Presentation, Question
from stompcad.settings import Origin, Provenance, Resolved, Settings
from stompcollider.model import DockData
from stompcollider.sources import BoardGeometry, BoardScan
from stompdrill.cad import OcpCaseModel
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.quantise import RawDrillData
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, DrillData, ReferenceOutline, StageRun
from stompmodel.progress import NO_PROGRESS, Scope, track
from stompmodel.protocols import Pipeline
from stompmodel.units import Nanometre
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, NullSink, case_model

__all__: list[str] = []


def test_a_run_without_boards_takes_only_the_drill_half() -> None:
    """Decision 17's division, stated once for the driver and the roadmap alike.

    The workbench derives its stale set from the plan a run would take, so
    a second statement of where the halves divide is how the sidebar comes
    to wait on a step this project has no reason to run.
    """
    assert [step.key for step in drive.plan_for(()).steps] == [
        "read-panel", "quantise", "drill", "write-case",
    ]
    assert drive.plan_for((TAR_PCB,)) is DRILL_AND_DOCK


def _refuse_to_read(panel: object) -> object:
    """Stands in for the artwork reader, where reading again would be the defect."""
    raise AssertionError(f"the artwork was read again: {panel}")


def _options() -> RunOptions:
    """A minimal, valid ``RunOptions``, at both tools' own CLI defaults throughout."""
    return RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case="1590B",
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
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
    options = replace(
        _options(), boards=(TAR_PCB,), case_model=model, panel_reference="RV*,SW*"
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run(scope)
    return driver


class _RecordingPresentation:
    """Records every ``finish_step``/``report`` call, in the order the driver made them."""

    def __init__(self) -> None:
        self.began: RunPlan | None = None
        self.finished: list[tuple[Step, str]] = []
        self.reported: list[Sequence[str]] = []

    def begin(self, plan: RunPlan) -> None:
        self.began = plan

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        self.finished.append((step, outcome))

    def ask(self, question: object) -> str:
        raise AssertionError("run_drill must not ask a question of its own")

    def report(self, lines: Sequence[str]) -> None:
        self.reported.append(lines)


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
        # Kept whole rather than rebuilt: a copy made field by field drops
        # whatever column the question gained since this line was written.
        assert isinstance(question, Choice), "the driver asks with ``resolve``'s own Choice"
        self._asked.append(question)
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
def test_a_revision_a_step_cannot_honour_re_runs_it_instead(
    drill_and_dock_run: Driver,
) -> None:
    """``title`` is read by ``read-boards`` itself, but not by its own retry.

    So it cannot be honoured from the scan already held, and the right
    answer is the parse -- not the refusal this replaces.
    """
    driver = drill_and_dock_run
    before = driver._scan
    revised = replace(driver._options, title="revised")
    with track(NullSink()) as scope:
        driver.retry("read-boards", revised, scope)
    assert driver._scan is not before, "the boards must have been scanned again"
    assert driver._options.title == revised.title


@pytest.mark.boards
@pytest.mark.hammond
def test_a_revision_a_step_can_honour_keeps_what_it_read(
    drill_and_dock_run: Driver,
) -> None:
    """A widened expression re-runs the filter, never the parse."""
    driver = drill_and_dock_run
    before = driver._scan
    widened = replace(
        driver._options, panel_reference=f"{driver._options.panel_reference},C1"
    )
    with track(NullSink()) as scope:
        driver.retry("read-boards", widened, scope)
    assert driver._scan is before, "boards already scanned are not read twice"


@pytest.mark.boards
@pytest.mark.hammond
def test_a_revised_board_list_reparses_rather_than_filters_a_stale_scan(
    drill_and_dock_run: Driver,
) -> None:
    """``boards`` is the field the comment above ``_RETRY_INPUTS`` names as
    the reason ``read-boards`` needs a narrower row at all -- the one the
    deleted refusal test covered, and the ``targets`` test above does not.

    A stale-scan filter could never grow the board count on its own; only a
    genuine second parse of the doubled list can, so that is what is proved
    rather than merely asserted.
    """
    driver = drill_and_dock_run
    before = driver._scan
    assert before is not None, "the control: a fixture with nothing scanned proves nothing"
    revised = replace(driver._options, boards=(TAR_PCB, TAR_PCB))

    with track(NullSink()) as scope:
        driver.retry("read-boards", revised, scope)

    assert driver._scan is not before, "the boards must have been scanned again"
    assert driver._options.boards == revised.boards
    assert driver._scan is not None
    assert len(driver._scan.raw.boards) == 2 * len(before.raw.boards), (
        "a filter over the stale scan could not have doubled the board count"
    )


@pytest.mark.boards
@pytest.mark.hammond
def test_every_step_in_the_plan_can_be_retried(drill_and_dock_run: Driver) -> None:
    """No step is refused any more; a revision it outgrew re-runs it."""
    driver = drill_and_dock_run
    for step in DRILL_AND_DOCK.steps:
        if step.key in {"match", "seat", "clash"}:
            continue
        with track(NullSink()) as scope:
            driver.retry(step.key, driver._options, scope)


@pytest.mark.boards
@pytest.mark.hammond
def test_match_seat_and_clash_are_not_retry_targets(drill_and_dock_run: Driver) -> None:
    """They read no field, so no change ever makes one of them the earliest."""
    driver = drill_and_dock_run
    for key in ("match", "seat", "clash"):
        with track(NullSink()) as scope, pytest.raises(ValueError, match=key):
            driver.retry(key, driver._options, scope)


def test_no_option_field_is_read_by_no_step() -> None:
    """Replaces the refusal: a field nothing reads would change nothing.

    A revision to a field no row names would invalidate no step, so a run
    could go stale under it and still look settled.
    """
    from dataclasses import fields

    from stompcad.drive import _STEP_INPUTS, RunOptions

    read = {name for names in _STEP_INPUTS.values() for name in names}
    assert {field.name for field in fields(RunOptions)} == read


def test_retry_inputs_never_exceed_step_inputs() -> None:
    from stompcad.drive import _RETRY_INPUTS, _STEP_INPUTS

    for key, honourable in _RETRY_INPUTS.items():
        assert honourable <= _STEP_INPUTS[key], key


def test_retrying_a_step_before_its_input_exists_names_the_missing_work() -> None:
    """An unrun driver refuses a retry, naming the work that has not happened.

    Each of ``_rerun``'s preconditions guards an intermediate a later step
    reads, so a driver that has already run satisfies all seven and cannot
    exercise any of them; only a freshly constructed one can. Each message
    names the missing work -- "the panel is read", "quantisation" -- rather
    than the attribute it would have set, so a person reading it knows what
    to do.
    """
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())

    with pytest.raises(ValueError, match="panel is read"):
        driver.retry("quantise", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="quantisation"):
        driver.retry("drill", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="panel is drilled"):
        driver.retry("write-case", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="panel is drilled"):
        driver.retry("read-boards", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="boards are docked"):
        driver.retry("drill-walls", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="walls are cut"):
        driver.retry("write-model", _options(), NO_PROGRESS)
    with pytest.raises(ValueError, match="boards are docked"):
        driver.retry("write-assembly", _options(), NO_PROGRESS)


def test_retrying_read_panel_also_credits_the_quantise_hold_it_refreshed() -> None:
    """``_STEP_HOLDS`` says ``quantise`` owns ``_quantised``. A retry of
    ``read-panel`` sets it too, because a read alone has nothing of
    ``DrillData``'s own shape to report -- so the presentation must be told
    ``quantise`` ran as well, or ``_STEP_HOLDS``'s claim about who assigns
    what is silently false the one time it is not this call's own key.
    """
    lines: list[str] = []
    driver = Driver(DRILL_AND_DOCK, _Recording(lines), _options())
    with track(NullSink()) as scope:
        driver.run_drill(scope)
    lines.clear()

    with track(NullSink()) as scope:
        driver.retry("read-panel", driver._options, scope)

    keys = [line.split(":", 1)[0] for line in lines]
    assert keys == ["read-panel", "quantise"], lines


def _uniquely_owned_holds() -> dict[str, str]:
    """Attributes ``_STEP_HOLDS`` assigns to exactly one step.

    ``_dock_data`` is excluded on purpose: ``match``, ``seat``, ``clash`` and
    ``read-boards`` (through ``_admit``) all legitimately rewrite it during a
    normal run, so which of them is responsible cannot be told apart from
    the attribute's identity alone -- unlike every other hold below, which
    only one step ever assigns.
    """
    owners: dict[str, list[str]] = {}
    for owner, attributes in _STEP_HOLDS.items():
        for attribute in attributes:
            owners.setdefault(attribute, []).append(owner)
    return {attribute: found[0] for attribute, found in owners.items() if len(found) == 1}


@pytest.mark.boards
@pytest.mark.hammond
def test_a_retry_credits_every_step_whose_hold_it_refreshed(drill_and_dock_run: Driver) -> None:
    """The general form of the ``read-panel``/``quantise`` guard above.

    A future branch that writes to a hold ``_STEP_HOLDS`` assigns to some
    *other* step, without also crediting that step, would leave the
    presentation believing a step never ran when it did -- this is true
    for any retryable step, not only ``read-panel``, so it is checked for
    all of them rather than pinned once.
    """
    driver = drill_and_dock_run
    unique_holds = _uniquely_owned_holds()

    for step in DRILL_AND_DOCK.steps:
        if step.key in {"match", "seat", "clash"}:
            continue
        before = {attribute: getattr(driver, attribute) for attribute in unique_holds}
        lines: list[str] = []
        driver._presentation = _Recording(lines)

        with track(NullSink()) as scope:
            driver.retry(step.key, driver._options, scope)

        credited = {line.split(":", 1)[0] for line in lines}
        for attribute, owner in unique_holds.items():
            after = getattr(driver, attribute)
            refreshed = after is not None and after is not before[attribute]
            if refreshed:
                assert owner in credited, f"{owner!r}'s hold changed but was not credited"


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
    return replace(_options(), case=None, panel_reference="RV*")


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


def _declaring(panel: Path, presentation: Presentation, case: str | None) -> Driver:
    """A driver over the tied fixture whose drill half commits a project file.

    ``case`` is what the project already declares, and also what the run is
    given: the tar fixture ties three parts only where neither says anything.
    """
    options = _undeclared() if case is None else replace(_undeclared(), case=case)
    settings = Settings.of_defaults(panel)
    if case is not None:
        settings = replace(
            settings,
            enclosure=replace(
                settings.enclosure, case=Resolved(case, Provenance(Origin.PROJECT))
            ),
        )
    driver = Driver(DRILL_AND_DOCK, presentation, options)
    driver._project = Project(panel=panel, settings=settings, held=manifest.Manifest())
    return driver


def test_an_answered_tie_is_declared_where_the_manifest_reads_it(tmp_path: Path) -> None:
    """Decision 8: the manifest records the values that produced the artefacts.

    The declarations are read from ``Project.settings``, so an answer that
    revised the options alone would be recorded as the ``null`` it started
    as -- and, being held, never corrected afterwards: the same question
    would be asked on every open.
    """
    panel = tmp_path / "tar.ai"
    driver = _declaring(panel, _Answering([], "1590B2"), case=None)

    with track(NullSink()) as scope:
        driver.run_drill(scope)

    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert recorded["enclosure"]["case"] == "1590B2"


def test_a_run_with_no_gap_records_the_case_it_ran_under(tmp_path: Path) -> None:
    """The control: a revision changes a declaration, a run happening does not."""
    panel = tmp_path / "tar.ai"
    asked: list[Choice] = []
    driver = _declaring(panel, _Answering(asked, "never asked"), case="1590B")

    with track(NullSink()) as scope:
        driver.run_drill(scope)

    assert asked == [], "the control: a declared case ties nothing"
    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert recorded["enclosure"]["case"] == "1590B"


def test_a_resume_under_a_revised_value_keeps_the_gap_the_run_answered(tmp_path: Path) -> None:
    """Decision 8: both the revision and the answer reach the file that describes them.

    ``declare`` is handed the workbench's own settings, where an answered
    tie was never recorded -- the answer went to the worker. Taking those
    settings whole would drop it, and the question would be asked on every
    open: exactly what recording it on ``Project.settings`` prevents.
    """
    panel = tmp_path / "tar.ai"
    driver = _declaring(panel, _Answering([], "1590B2"), case=None)
    with track(NullSink()) as scope:
        driver.resume(frozenset({"read-panel", "quantise"}), driver._options, scope)

    defaults = Settings.of_defaults(panel)
    edited = replace(
        defaults,
        drilling=replace(defaults.drilling, title=Resolved("Tar", Provenance(Origin.USER))),
    )
    driver.declare(edited)
    with track(NullSink()) as scope:
        driver.resume(frozenset({"drill", "write-case"}), driver._options, scope)

    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert recorded["enclosure"]["case"] == "1590B2"
    assert recorded["drilling"]["title"] == "Tar", "the resume's own revision was not declared"


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
    options = replace(_options(), boards=(TAR_PCB,), case_model=model, panel_reference="ZZ*")
    driver = Driver(DRILL_AND_DOCK, _AnsweringEach(lines, asked), options)

    with track(NullSink()) as scope:
        _drill, dock = driver.run(scope)

    assert asked != [], "the control: the expression must admit nothing to raise the gap"
    assert [line for line in lines if line.startswith("read-boards")] == ["read-boards: 2 board(s)"]
    assert dock is not None
    assert not [d for d in dock.diagnostics if d.code == "empty-group"]


# --------------------------------------------------------------------------
# Decision 10: resume runs a whole stale set without discarding what it did
# not touch. These stand-ins name the driver's own tables rather than real
# geometry, so a resume can be driven with no kernel and no board fixture.
# --------------------------------------------------------------------------


def _identity_frame() -> FaceFrame:
    """A registration frame with no measured or kernel-backed geometry behind it."""
    return FaceFrame(
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )


def _stand_in_dock_data() -> DockData:
    """An otherwise empty ``DockData``, valid enough to be held without a real dock read."""
    return DockData(case=CaseRegistration("1590B", CaseFace.BOX, "case.stp", _identity_frame()))


class _MatchStub:
    """A dock stage whose ``apply`` returns its input, standing in for ``Match``."""

    name: ClassVar[str] = "match"
    weight: ClassVar[float] = 1.0

    def apply(self, data: DockData, scope: Scope = NO_PROGRESS) -> DockData:
        return data

    def describe(self) -> StageRun:
        return StageRun(self.name)


class _SeatStub(_MatchStub):
    """Stands in for ``Seat``, beside ``_MatchStub``."""

    name: ClassVar[str] = "seat"


class _ClashStub(_MatchStub):
    """Stands in for ``Clash``, beside ``_MatchStub``."""

    name: ClassVar[str] = "clash"


class _CountingStage(_MatchStub):
    """Counts each ``apply`` call, so a resumed stage step is proven to have run."""

    def __init__(self) -> None:
        self.calls = 0

    def apply(self, data: DockData, scope: Scope = NO_PROGRESS) -> DockData:
        self.calls += 1
        return data


#: Three stand-in stages in ``_STAGE_ORDER``'s own order, so a resumed stage
#: step has something to index into without running real board matching.
_STAND_IN_PIPELINE: Pipeline[DockData] = Pipeline([_MatchStub(), _SeatStub(), _ClashStub()])


def _driver_and_presentation_with_held_intermediates(
    tmp_path: Path,
) -> tuple[Driver, _RecordingPresentation]:
    """A driver whose held intermediates are stand-ins, so a resume needs no kernel.

    ``_scan``/``_geometry``/``_case_model`` are cast placeholders: no test here
    asks for a ``report``/``assembly`` target, so ``_write_dock`` returns before
    any is read -- the early exit ``test_drive_dock.py``'s withhold test
    justifies. ``_cut`` is the panel document unchanged, which is what ``drill
    walls`` leaves a run naming no wall. ``boards`` is a never-opened path, only
    truthy so a resume keeps the dock half; ``targets`` names an absolute path
    under ``tmp_path`` so a write step commits nowhere else.
    """
    presentation = _RecordingPresentation()
    options = replace(
        _options(),
        boards=(Path("stand-in-board.stp"),),
        targets=(("excellon", tmp_path / "case.drl"), ("json", tmp_path / "case.json")),
    )
    driver = Driver(DRILL_AND_DOCK, presentation, options)
    driver._raw = cast(RawDrillData, object())
    driver._quantised = DrillData()
    driver._drilled = _outlined_document()
    driver._cut = driver._drilled
    driver._case_model = cast(OcpCaseModel, object())
    driver._scan = cast(BoardScan, object())
    driver._geometry = cast(dict[int, BoardGeometry], {})
    driver._docked = _stand_in_dock_data()
    driver._dock_pipeline = _STAND_IN_PIPELINE
    driver._dock_data = _stand_in_dock_data()
    return driver, presentation


def _driver_with_held_intermediates(tmp_path: Path) -> Driver:
    driver, _presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    return driver


def _errored_dock_data() -> DockData:
    """A dock result carrying an error, for the write step's own withhold guard."""
    return _stand_in_dock_data().with_diagnostics(Diagnostic.error("stand-in-error", "stand-in"))


def _outlined_document() -> DrillData:
    """A document the Excellon emitter accepts: it refuses one with no outline."""
    return DrillData(reference=ReferenceOutline(Nanometre(30_000_000), Nanometre(20_000_000)))


def _driver_writing_into(
    tmp_path: Path,
    *,
    worst: Severity | None = None,
    targets: tuple[tuple[str, Path], ...] | None = None,
    boards: tuple[Path, ...] | None = None,
) -> tuple[Driver, Path]:
    """A driver over ``tmp_path`` with a real ``Project``, so a write step declares.

    Built on ``_driver_and_presentation_with_held_intermediates`` rather than
    a second set of fakes: the same stand-in intermediates and options, plus
    the ``Project`` this task's declarations are staged and re-read through.
    ``boards``, when given, overrides both the options and the settings the
    project declares from, so ``Half.DRILL_ONLY`` is reachable with an empty
    list read back as the confirmed answer it is, not an unresolved default.
    """
    panel = tmp_path / "tar.ai"
    driver, _presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    if targets is not None:
        driver._options = replace(driver._options, targets=targets)
    if worst is not None:
        driver._drilled = DrillData().with_diagnostics(Diagnostic(worst, "stand-in", "stand-in"))
    settings = Settings.of_defaults(panel)
    if boards is not None:
        driver._options = replace(driver._options, boards=boards)
        settings = replace(
            settings,
            boards=replace(settings.boards, boards=Resolved(boards, Provenance(Origin.PROJECT))),
        )
    driver._project = Project(panel=panel, settings=settings, held=manifest.Manifest())
    return driver, panel


def _commit_the_model(driver: Driver) -> None:
    """The drill half's later commit, which carries its declaration when there are boards.

    ``write case`` no longer declares on a run with boards: decision 16 puts
    the declaration on the commit that follows the walls.
    """
    assert driver._drilled is not None
    with track(NullSink()) as scope:
        driver._write_model(driver._drilled, scope)


class _Recorder:
    """A sink appending each reported position to the list it was given."""

    def __init__(self, seen: list[float]) -> None:
        self._seen = seen

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self._seen.append(position)


def test_a_resume_of_the_write_steps_keeps_every_dock_intermediate(tmp_path: Path) -> None:
    """Decision 10: a filename must not cost the seating search again.

    The finding that forced the design. ``retry`` discards everything after
    the step it runs, so driving a two-write stale set through it would drop
    the scan the second write needs.
    """
    driver = _driver_with_held_intermediates(tmp_path)
    held_scan, held_geometry, held_dock_data = driver._scan, driver._geometry, driver._dock_data
    revised = replace(driver._options, targets=(("json", tmp_path / "other.json"),))

    driver.resume(frozenset({"write-case", "write-assembly"}), revised, NO_PROGRESS)

    # Identity, not equality: a rebuilt-but-equal value would still mean the
    # scan or the dock data was computed again, which is the cost decision 10
    # exists to avoid -- see finding 1 of the fix round for the failure mode.
    assert driver._scan is held_scan
    assert driver._geometry is held_geometry
    assert driver._dock_data is held_dock_data


def test_a_resume_discards_only_what_the_changed_step_cannot_honour(tmp_path: Path) -> None:
    """A revised board list needs the parse ``read boards`` no longer performs."""
    driver = _driver_with_held_intermediates(tmp_path)
    revised = replace(driver._options, boards=(Path("other-pcb.stp"),))

    driver._adopt(revised, frozenset({"read-boards"}))

    assert driver._docked is None
    assert driver._drilled is not None  # an earlier step's hold is untouched


def test_a_resume_honours_a_revision_the_step_can_take_from_what_it_holds(
    tmp_path: Path,
) -> None:
    """The control: a revised filter re-runs the filter, never the parse."""
    driver = _driver_with_held_intermediates(tmp_path)
    revised = replace(driver._options, panel_reference="RV*")

    driver._adopt(revised, frozenset({"read-boards"}))

    assert driver._docked is not None


def test_a_resume_runs_the_stale_steps_in_the_plan_s_own_order(tmp_path: Path) -> None:
    driver, presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    driver.resume(frozenset({"write-assembly", "write-case"}), driver._options, NO_PROGRESS)
    assert [step.key for step, _outcome in presentation.finished] == [
        "write-case", "write-assembly"
    ]


def test_a_resume_reports_no_step_it_was_not_given(tmp_path: Path) -> None:
    """The stale set is the whole instruction; a fresh step is not run for free."""
    driver, presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    assert [step.key for step, _outcome in presentation.finished] == ["write-case"]


def test_a_resumed_position_never_retreats(tmp_path: Path) -> None:
    """Decision 8 of ADR-0013 continues to bind across a resume."""
    driver = _driver_with_held_intermediates(tmp_path)
    seen: list[float] = []
    with track(_Recorder(seen)) as scope:
        driver.resume(frozenset({"write-case", "write-assembly"}), driver._options, scope)
    assert seen == sorted(seen)


def test_a_stage_step_is_runnable_by_a_resume_though_no_revision_names_it(
    tmp_path: Path,
) -> None:
    """``match``, ``seat`` and ``clash`` read no field, so only consumption makes them stale.

    ``_dock_data`` being non-``None`` alone would pass even if ``match``
    were silently skipped, since the stand-in already sets it -- so this
    checks the stage actually ran: once, and credited.
    """
    driver, presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    counting = _CountingStage()
    driver._dock_pipeline = Pipeline([counting, _SeatStub(), _ClashStub()])

    driver.resume(frozenset({"match"}), driver._options, NO_PROGRESS)

    assert counting.calls == 1
    assert [step.key for step, _outcome in presentation.finished] == ["match"]


def test_a_retry_still_refuses_a_stage_step(tmp_path: Path) -> None:
    """The control: a retry is driven by a revision, and no revision names these."""
    driver = _driver_with_held_intermediates(tmp_path)
    with pytest.raises(ValueError, match="reads no field"):
        driver.retry("seat", driver._options, NO_PROGRESS)


def test_the_driver_names_every_artefact_it_committed(tmp_path: Path) -> None:
    """The `Output` place labels a file it wrote differently from one it found."""
    driver, _presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)
    assert driver.written


# --------------------------------------------------------------------------
# Fix round 1: five findings against the design above.
# --------------------------------------------------------------------------


def test_a_resume_re_parses_boards_stale_only_by_an_earlier_steps_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1: ``read-boards`` is stale only by consumption of a re-drilled panel.

    A grid change invalidates the whole plan but names no field ``read
    boards`` itself reads, so the old rule kept its scan. The assembly
    would then disagree with the case this very resume just rewrote.
    """
    driver = _driver_with_held_intermediates(tmp_path)
    # The stale set reaches ``drill-walls``, whose premise is that a board was
    # seated inside a model, and the stub below replaces the step that opens
    # one. Only its name is read: the stand-in dock data measured no wall
    # feature, so ``DrillWalls`` returns before it asks the model anything.
    driver._case_model = cast(OcpCaseModel, SimpleNamespace(model_name="stand-in"))
    calls = {"read_boards": 0}

    def _stub_quantise(scope: Scope) -> DrillData:
        return _outlined_document()

    def _stub_drill(data: DrillData, scope: Scope) -> DrillData:
        return _outlined_document()

    def _stub_read_boards(drill: DrillData, scope: Scope) -> None:
        calls["read_boards"] += 1
        # ``_run_step`` reports ``len(self._scan.raw.boards)``, so the stand-in
        # needs that one shape rather than an opaque, never-touched cast.
        driver._scan = cast(BoardScan, SimpleNamespace(raw=SimpleNamespace(boards=())))
        driver._geometry = {}
        driver._docked = _stand_in_dock_data()
        driver._dock_pipeline = _STAND_IN_PIPELINE

    monkeypatch.setattr(driver, "_quantise", _stub_quantise)
    monkeypatch.setattr(driver, "_drill", _stub_drill)
    monkeypatch.setattr(driver, "_read_boards", _stub_read_boards)
    revised = replace(driver._options, grid_mm=driver._options.grid_mm / 2)
    stale = drive.invalidated(frozenset({"grid_mm"}))

    driver.resume(stale, revised, NO_PROGRESS)

    assert calls["read_boards"] == 1


def test_a_resume_of_read_panel_and_quantise_credits_each_step_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 2: a resume must not cascade ``read-panel`` into ``quantise``.

    A retry pays for ``quantise`` from inside ``read-panel`` because it has
    nothing of ``DrillData``'s own shape to report. A resume runs ``quantise``
    as its own stale step instead, or it would be credited -- and, with an
    unanswered gap, possibly credited before that gap was resolved.
    """
    presentation = _RecordingPresentation()
    driver = Driver(DRILL_AND_DOCK, presentation, _options())
    calls = {"quantise": 0}
    real_quantise = Driver._quantise

    def _counting_quantise(self: Driver, scope: Scope) -> DrillData:
        calls["quantise"] += 1
        return real_quantise(self, scope)

    monkeypatch.setattr(Driver, "_quantise", _counting_quantise)

    driver.resume(frozenset({"read-panel", "quantise"}), driver._options, NO_PROGRESS)

    assert [step.key for step, _outcome in presentation.finished] == ["read-panel", "quantise"]
    assert calls["quantise"] == 1


def test_a_resume_reports_undocked_and_skips_dock_steps_when_drilled_has_errors(
    tmp_path: Path,
) -> None:
    """Finding 3: ``run`` never docks against an errored drill half, and neither must resume."""
    driver, presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    driver._drilled = DrillData().with_diagnostics(
        Diagnostic.error("synthetic-error", "forced for the undocked guard")
    )

    driver.resume(frozenset({"write-case", "write-assembly"}), driver._options, NO_PROGRESS)

    assert [step.key for step, _outcome in presentation.finished] == ["write-case"]
    assert any("read no board" in line for lines in presentation.reported for line in lines)
    assert any("case.json" in line for lines in presentation.reported for line in lines), (
        "the model's deferred targets are named beside the dock half's"
    )


def test_a_resume_drops_the_dock_half_when_there_are_no_boards(tmp_path: Path) -> None:
    """Finding 4: ``run`` skips the dock half with no boards, and so must resume."""
    driver, presentation = _driver_and_presentation_with_held_intermediates(tmp_path)
    driver._options = replace(driver._options, boards=())

    driver.resume(frozenset({"write-case", "write-assembly"}), driver._options, NO_PROGRESS)

    assert [step.key for step, _outcome in presentation.finished] == ["write-case"]


def test_a_refused_retry_leaves_options_and_holds_untouched() -> None:
    """Finding 5: a refusal must not run ``_accept`` before its own precondition is checked."""
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())
    before = driver._options
    revised = replace(before, case="1590BB")

    with pytest.raises(ValueError, match="panel is read"):
        driver.retry("quantise", revised, NO_PROGRESS)

    assert driver._options is before


def test_a_retry_of_an_unknown_key_names_it() -> None:
    """Finding 5: an unknown key must not reach ``_discard_after``'s ``list.index`` instead."""
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())

    with pytest.raises(ValueError, match="not a step this driver can run again"):
        driver.retry("bogus", driver._options, NO_PROGRESS)


def test_a_resume_of_a_step_whose_precondition_fails_names_the_missing_work() -> None:
    """Fix round 2: ``_run_step``'s one guard path must be reachable from resume too.

    A retry reaches this guard through ``_rerun``'s own call, ahead of
    ``_accept``; a resume never goes through ``_rerun`` at all, so this is
    the only test that proves ``_run_step``'s internal call to
    ``_precondition`` fires on that path.
    """
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())

    with pytest.raises(ValueError, match="panel is read"):
        driver.resume(frozenset({"quantise"}), driver._options, NO_PROGRESS)


# --------------------------------------------------------------------------
# Task 5: the manifest inside each half's own transaction.
# --------------------------------------------------------------------------


def test_a_half_commits_its_declarations_with_its_own_artefacts(tmp_path: Path) -> None:
    """Decision 8: an artefact never sits beside a project file that misses it."""
    driver, panel = _driver_writing_into(tmp_path)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)
    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert recorded["drilling"]["grid_mm"] == driver._options.grid_mm
    assert "boards" not in recorded, "the control: boards is the dock half's place with any boards"


def test_a_drill_only_half_declares_the_confirmed_empty_board_list(tmp_path: Path) -> None:
    """Spec decision 17, through the driver: no boards selects ``Half.DRILL_ONLY``."""
    driver, panel = _driver_writing_into(tmp_path, boards=())
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert recorded["boards"]["boards"] == []


def test_a_withheld_half_records_nothing(tmp_path: Path) -> None:
    """The control: a half that wrote no artefact declares nothing about them."""
    driver, panel = _driver_writing_into(tmp_path, worst=Severity.ERROR)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    assert not manifest.manifest_path(panel).exists()


def test_a_second_commit_leaves_what_the_first_one_recorded(tmp_path: Path) -> None:
    """Decision 8: a value the manifest holds is used and left untouched.

    Changed on ``_project.settings``, not ``driver._options``: the payload
    is derived from the former, so only a revised held manifest -- read back
    after the first commit -- can be what stops the second payload differing.
    """
    driver, panel = _driver_writing_into(tmp_path)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)
    first = manifest.manifest_path(panel).read_text(encoding="utf-8")

    assert driver._project is not None
    driver._project = replace(
        driver._project,
        settings=replace(
            driver._project.settings,
            drilling=replace(
                driver._project.settings.drilling,
                grid_mm=Resolved(0.5, Provenance(Origin.USER)),
            ),
        ),
    )
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)

    assert manifest.manifest_path(panel).read_text(encoding="utf-8") == first


def test_a_failed_dock_half_leaves_the_drill_declarations_and_not_its_own(tmp_path: Path) -> None:
    """Decision 8: gap-filling follows each half's commit, not the whole run.

    The drill half commits real case files before docking begins, so
    recording the declarations only on a whole-run success would leave those
    files beside defaults that did not make them.
    """
    driver, panel = _driver_writing_into(tmp_path)
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)
    driver._dock_data = _errored_dock_data()
    driver.resume(frozenset({"write-assembly"}), driver._options, NO_PROGRESS)

    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert "drilling" in recorded
    assert "boards" not in recorded


def test_a_drill_half_never_declares_a_target_only_the_dock_half_could_commit(
    tmp_path: Path,
) -> None:
    """Decision 8, through the driver: ``write case`` must not pre-declare a dock format.

    A dock format in the resolved targets is real ahead of the dock half --
    a run may ask for both in one go -- so the guard has to be the half a
    format belongs to, not merely whether the run intends to render it.
    """
    driver, panel = _driver_writing_into(tmp_path)
    assert driver._project is not None
    driver._project = replace(
        driver._project,
        settings=replace(
            driver._project.settings,
            output=replace(
                driver._project.settings.output,
                targets=Resolved(
                    (("json", tmp_path / "tar.json"), ("assembly", tmp_path / "tar-assembly.step")),
                    Provenance(Origin.USER),
                ),
            ),
        ),
    )

    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)

    recorded = json.loads(manifest.manifest_path(panel).read_text(encoding="utf-8"))
    assert "assembly" not in recorded["output"]["targets"]
    assert "json" in recorded["output"]["targets"]


def test_a_run_that_writes_nothing_still_records_what_it_ran_under(tmp_path: Path) -> None:
    """A check-only run is a run; decision 17 permits one and decision 8 remembers it."""
    driver, panel = _driver_writing_into(tmp_path, targets=())
    driver.resume(frozenset({"write-case"}), driver._options, NO_PROGRESS)
    _commit_the_model(driver)
    assert manifest.manifest_path(panel).exists()


@pytest.mark.parametrize(
    "spell",
    [
        lambda project: project,
        lambda project: project.parent / "sub" / ".." / project.name,
        lambda project: project.parent / project.name.upper(),
    ],
    ids=["exact", "dotdot", "case"],
)
def test_the_manifest_is_never_one_of_the_artefacts(
    tmp_path: Path, spell: Callable[[Path], Path]
) -> None:
    """Two writers for one path is what `check_target_set` exists to refuse.

    Compared through ``target_key`` rather than ``==``: a ``..`` segment and
    a case variant both name the same file on the filesystems this runs on,
    and a mismatch there would let the declaration silently overwrite an
    artefact spelled differently from the manifest's own path.
    """
    panel = tmp_path / "tar.ai"
    project = manifest.manifest_path(panel)
    targets = Resolved[tuple[tuple[str, Path], ...]](
        (("excellon", spell(project)),), Provenance(Origin.PROJECT)
    )
    with pytest.raises(cli.UsageError, match="project file"):
        cli._validate_output(targets, panel)


def test_the_manifest_is_refused_under_a_relative_spelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control's own control: ``parse_emit`` hands a bare ``FORMAT=name`` through unresolved."""
    panel = tmp_path / "tar.ai"
    project = manifest.manifest_path(panel)
    monkeypatch.chdir(tmp_path)
    targets = Resolved[tuple[tuple[str, Path], ...]](
        (("excellon", Path(project.name)),), Provenance(Origin.PROJECT)
    )
    with pytest.raises(cli.UsageError, match="project file"):
        cli._validate_output(targets, panel)


def test_an_ordinary_artefact_path_is_accepted(tmp_path: Path) -> None:
    """The control: a target that is not the project file, under any spelling, passes."""
    panel = tmp_path / "tar.ai"
    targets = Resolved[tuple[tuple[str, Path], ...]](
        (("excellon", tmp_path / "tar.drl"),), Provenance(Origin.PROJECT)
    )
    cli._validate_output(targets, panel)
