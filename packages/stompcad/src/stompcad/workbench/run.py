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
from typing import TYPE_CHECKING

from stompmodel.diagnostics import Diagnostic, exit_for_severity
from stompmodel.protocols import Diagnosable

from .. import manifest
from ..cancel import EXIT_CANCELLED, Cancelled
from ..drive import Driver, Project, RunOptions, compose
from ..plan import DRILL_AND_DOCK, RunPlan, Step
from ..present import Question

if TYPE_CHECKING:
    from .app import Workbench

__all__ = ["Launch", "WorkbenchPresentation", "start"]

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
        """Pause for a gap. Task 9 is the whole of this method."""
        raise NotImplementedError

    def report(self, lines: Sequence[str]) -> None:
        self._app.call_from_thread(self._app.record, list(lines))


def start(app: Workbench) -> None:
    """Begin a run on a worker, and hand its outcome back to the app."""
    app.stopping = False
    app.run_worker(lambda: _attempt(app), thread=True)


def _attempt(app: Workbench) -> None:
    """Run, and report whatever happened into the app rather than out of it.

    A run ending is not the app ending, so a fault becomes something the
    user can see and act on rather than a traceback on a dead terminal.
    ``Cancelled`` is caught here because it is a stop the user asked for,
    and decision 14 reserves its own code for exactly that.
    """
    launch = app.launch
    assert launch is not None  # ``action_start_run`` refuses a run without one
    try:
        options = RunOptions.of(app.session.settings)
        project = Project(launch.panel, app.session.settings, manifest.read(launch.panel))
        driver, drill, dock = launch.compose(
            launch.plan,
            WorkbenchPresentation(app),
            options,
            project,
            lambda: app.stopping,
        )
    except Cancelled:
        _finish(app, EXIT_CANCELLED, None, (), {})
        return
    except BaseException as failure:  # noqa: BLE001 - shown in the app, not raised
        _tell(app, app.fault, failure)
        return
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
