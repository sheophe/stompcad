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
from stompcad.present import PlainWriter
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
    """``retry`` names only ``quantise`` and ``drill``; every other key is refused."""
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
