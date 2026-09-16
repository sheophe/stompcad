"""The run as an event inside the app: a worker, a presentation, an exit code.

ADR-0013's mechanism, unchanged: the app owns the main thread, the composed
run happens on a Textual worker because a blocking kernel call would
otherwise freeze the display for minutes, and every presentation method
crosses back through ``call_from_thread``. What is new is that the app
outlives the run, so a fault is reported into the app rather than carried
out of it, and the exit code is kept until somebody quits.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from stompmodel.diagnostics import Diagnostic, Severity, exit_for_severity
from stompmodel.progress import Sink, track
from stompmodel.protocols import Diagnosable

from .. import manifest
from ..cancel import EXIT_CANCELLED, Cancelled, CancellingSink
from ..drive import Driver, Project, RunOptions, compose
from ..plan import DRILL_AND_DOCK, RunPlan, Step
from ..present import Choice, Question
from ..resolve import RESOLVABLE
from .keys import Place
from .session import PendingGap

if TYPE_CHECKING:
    from .app import Workbench

__all__ = ["Launch", "WorkbenchPresentation", "may_resume", "start"]

#: What a composed run hands back: the driver that held it, and each half's
#: data. Typed by what the outcome reads rather than by either tool's own
#: value, so a test can drive every rule about a run without a kernel.
Composed = tuple[Driver, Diagnosable, "Diagnosable | None"]


@dataclass(frozen=True, slots=True)
class Launch:
    """What the app needs to start a run, without composing one itself.

    ``compose`` is injected so a test can drive every rule about starting,
    stopping and crediting a run without minutes of kernel work -- and so
    the application never learns what a phase is.
    """

    panel: Path
    plan: RunPlan = DRILL_AND_DOCK
    compose: Callable[..., Composed] = compose


class WorkbenchPresentation:
    """The boundary ADR-0013 pinned, forwarded to an app on another thread."""

    __slots__ = ("_app",)

    def __init__(self, app: Workbench) -> None:
        self._app = app

    def begin(self, plan: RunPlan) -> None:
        self._app.call_from_thread(self._app.show, plan)

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self._app.call_from_thread(self._app.advance, position, path)

    def finish_step(self, step: Step, outcome: str) -> None:
        self._app.call_from_thread(self._app.settle, step, outcome)

    def ask(self, question: Question) -> str:
        """Pause the run on this gap, and block until somebody answers it.

        The wait happens after the crossing, never during it: the app thread
        must not be blocked on the thread that is waiting for it. A picker
        abandoned without an answer leaves the run paused and the picker
        reopenable rather than parking this worker forever -- the loop
        notices a stop, which is the only thing that ends a wait unanswered.
        """
        answered = Event()
        box: list[str] = []

        def chosen(answer: str) -> None:
            box.append(answer)
            answered.set()

        self._app.call_from_thread(self._app.enquire, _gap_for(question), chosen)
        while not answered.wait(0.05):
            if self._app.stopping or not self._app.is_running:
                raise Cancelled("the gap was left unanswered")
        return box[0]

    def report(self, lines: Sequence[str]) -> None:
        self._app.call_from_thread(self._app.record, list(lines))


def _gap_for(question: Question) -> PendingGap:
    """Which place answers this question, from the code's own row.

    Read from the question rather than re-derived from its prompt, which is
    a sentence a tool wrote for a person. A question carrying no code names
    no place, so this narrows to the ``Choice`` ``resolve`` builds instead
    of guessing at one.
    """
    if not isinstance(question, Choice):
        raise KeyError("a question with no code names no place that can answer it")
    row = RESOLVABLE[question.code]
    return PendingGap(question.code, row.step, Place(row.place), question)


def may_resume(app: Workbench) -> bool:
    """Whether `Ctrl+R` resumes: a driver to spend, and something stale to spend it on.

    Asked twice -- once to bind the phase on the keypress, once to choose
    the worker's path -- so the two ask one question rather than two that
    happen to agree.
    """
    return app.driver is not None and bool(app.session.stale())


def start(app: Workbench) -> None:
    """Begin a run, or resume what a change invalidated. Decision 10."""
    app.stopping = False
    app.resuming = may_resume(app)
    app.run_worker(lambda: _attempt(app), thread=True)


def _attempt(app: Workbench) -> None:
    """Run, and report whatever happened into the app rather than out of it.

    A run ending is not the app ending, so a fault becomes something the
    user can see and act on rather than a traceback on a dead terminal.
    ``Cancelled`` is caught here because it is a stop the user asked for,
    and decision 14 reserves its own code for exactly that.
    """
    try:
        if app.resuming:
            _resume(app)
        else:
            _first(app)
    except Cancelled:
        _finish(app, EXIT_CANCELLED, None, _committed(app), {})
    except BaseException as failure:  # noqa: BLE001 - shown in the app, not raised
        _tell(app, app.fault, failure)


def _committed(app: Workbench) -> tuple[Path, ...]:
    """What a stopped run had already written, where a driver holds the answer.

    A stop is heard at the next reported leaf, so a write may have committed
    before it: decision 2 keeps "already on disk" for a file this session did
    not make, and denying one it did make is that same claim backwards. A
    first run hands its driver back as it returns, so a stop before then has
    nobody to ask.
    """
    return () if app.driver is None else app.driver.written


def _first(app: Workbench) -> None:
    """Compose the whole plan, and keep the driver a later `Ctrl+R` spends."""
    launch = app.launch
    assert launch is not None  # ``action_start_run`` refuses a run without one
    options = RunOptions.of(app.session.settings)
    project = Project(launch.panel, app.session.settings, manifest.read(launch.panel))
    driver, drill, dock = launch.compose(
        launch.plan,
        WorkbenchPresentation(app),
        options,
        project,
        lambda: app.stopping,
    )
    _tell(app, app.keep, driver)
    severities = [drill.worst_severity] + ([] if dock is None else [dock.worst_severity])
    found = [severity for severity in severities if severity is not None]
    diagnostics = list(drill.diagnostics) + ([] if dock is None else list(dock.diagnostics))
    _finish(
        app,
        exit_for_severity(max(found) if found else None),
        diagnostics,
        driver.written,
        driver.designators,
    )


def _resume(app: Workbench) -> None:
    """Run the stale set against the intermediates the driver still holds.

    The driver is the one the first run left rather than a fresh one: its
    project is where an answered gap was recorded, and its intermediates
    are the whole reason a resume costs less than starting over.
    """
    driver = app.driver
    assert driver is not None  # ``may_resume`` is what chose this path
    driver.declare(app.session.settings)
    sink: Sink = CancellingSink(WorkbenchPresentation(app), lambda: app.stopping)
    with track(sink) as scope:
        driver.resume(app.session.stale(), RunOptions.of(app.session.settings), scope)
    _finish(
        app,
        exit_for_severity(_worst(driver.findings)),
        list(driver.findings),
        driver.written,
        driver.designators,
    )


def _worst(diagnostics: Sequence[Diagnostic]) -> Severity | None:
    """The worst severity among these findings, or ``None`` where there is none."""
    return max((found.severity for found in diagnostics), default=None)


def _finish(
    app: Workbench,
    code: int,
    diagnostics: Sequence[Diagnostic] | None,
    written: Sequence[Path],
    designators: dict[int, tuple[str, ...]],
) -> None:
    """Cross to the app thread with everything the places need to draw."""
    _tell(app, app.completed, code, diagnostics, written, designators)


def _tell(app: Workbench, report: Callable[..., None], *carried: object) -> None:
    """Cross to the app thread, or give up because the crossing cannot be made.

    ``call_from_thread`` raises once the app has gone, which a confirmed
    quit during a run makes reachable on either crossing -- and a raise on
    the worker ends nowhere at all.
    """
    try:
        app.call_from_thread(report, *carried)
    except RuntimeError:
        pass
