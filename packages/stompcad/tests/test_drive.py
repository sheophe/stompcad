"""The driver's own design: intermediates held, steps reported once, options replaceable.

Spec decision 7 says intermediates are what let plan C run a single step
again; these tests pin that design directly rather than only inferring it
from the byte-identity acceptance test in ``test_drive_drill.py``.
"""

from __future__ import annotations

import io
from dataclasses import replace

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.present import PlainWriter
from stompmodel.progress import track
from tests.conftest import PANEL_REFERENCE, TAR_AI, NullSink

__all__: list[str] = []


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
    """Spec decision 4: a step credits its span only once, on completion."""
    presentation = _RecordingPresentation()
    driver = Driver(DRILL_AND_DOCK, presentation, _options())

    with track(NullSink()) as scope:
        driver.run_drill(scope)

    assert presentation.began is DRILL_AND_DOCK
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
