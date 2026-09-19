"""The run as an event in the app: a runner, a pump, and what an event means.

Spec decision 18. The application composes nothing and holds no driver:
it tells a runner to start or resume, and reacts to what comes back. One
worker carries events across for the application's whole life, and a
thread is right for that where it was not right for the run -- this one
waits on a pipe, which is not work the interpreter has to be held for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from ..plan import DRILL_AND_DOCK, RunPlan
from ..present import Choice
from ..resolve import RESOLVABLE
from .keys import Place
from .session import PendingGap
from .wire import (
    Advanced,
    Asked,
    Began,
    Completed,
    Composed,
    Died,
    Event,
    Faulted,
    Reported,
    Settled,
)

if TYPE_CHECKING:
    from .app import Workbench

__all__ = ["Launch", "RunFailed", "may_resume", "start"]


class RunFailed(Exception):
    """A run that broke in a way the command line has no branch for.

    Deliberately not a ``StompError``: ``main`` catches those and prints a
    tidy line at exit `3`, which is the right treatment for a refusal and
    the wrong one for a defect. A defect still leaves a traceback.
    """


@dataclass(frozen=True, slots=True)
class Launch:
    """What the app needs to aim a run: the project, and how much of it."""

    panel: Path
    plan: RunPlan = DRILL_AND_DOCK


def may_resume(app: Workbench) -> bool:
    """Whether `Ctrl+R` resumes: a driver to spend, and something stale to spend it on.

    Asked twice -- once to bind the phase on the keypress, once to choose
    which command the runner gets -- so the two ask one question rather
    than two that happen to agree.
    """
    return app.composed and bool(app.session.stale())


def start(app: Workbench) -> None:
    """Begin a run, or resume what a change invalidated. Decision 10."""
    app.stopping = False
    app.resuming = may_resume(app)
    if app.resuming:
        app.runner.resume(app.session.stale(), app.session.settings)
    else:
        launch = app.launch
        assert launch is not None  # ``action_start_run`` refuses a run without one
        app.runner.start(launch.panel, launch.plan, app.session.settings)
    listen(app)


def listen(app: Workbench) -> None:
    """One worker for the app's whole life, blocked on the pipe between runs."""
    if app.listening:
        return
    app.listening = True
    app.run_worker(lambda: _pump(app), thread=True)


def _pump(app: Workbench) -> None:
    """Carry each event to the app's own thread, until the runner's end closes.

    The flag is cleared however this ends, so a run after a crash starts a
    listener again. Leaving it set would make one dead process the end of
    every run for the rest of the session.
    """
    try:
        for event in app.runner.events():
            _tell(app, apply, app, event)
    finally:
        app.listening = False


def apply(app: Workbench, event: Event) -> None:
    """One event, on the app's thread, turned into the change it names."""
    if isinstance(event, Began):
        app.show(event.plan)
    elif isinstance(event, Advanced):
        app.advance(event.position, event.path)
    elif isinstance(event, Settled):
        app.settle(event.step, event.outcome)
    elif isinstance(event, Reported):
        app.record(list(event.lines))
    elif isinstance(event, Asked):
        app.enquire(event.asked, gap_for(event.question))
    elif isinstance(event, Composed):
        app.composed = True
    elif isinstance(event, Completed):
        app.completed(event.code, event.diagnostics, event.written, event.designators)
    elif isinstance(event, Faulted):
        app.fault(_failure(event))
    elif isinstance(event, Died):
        # The driver went with the process, so there is nothing left to
        # resume: the next `Ctrl+R` composes rather than pretending an
        # intermediate is still held somewhere.
        app.composed = False
        app.fault(RunFailed(f"{event.reason} (exit {event.code})"))


def _failure(event: Faulted) -> BaseException:
    """The fault, rebuilt as the type ``main`` still chooses an exit code from.

    An exception is an object and a pipe carries values, so the class is
    named and remade here. A class that will not import, or will not take
    one string, becomes ``RunFailed`` carrying the remote traceback --
    which is worth more than the local one, since the local one names the
    line that re-raised.
    """
    module, _, name = event.kind.partition(":")
    try:
        kind = getattr(import_module(module), name)
        if not (isinstance(kind, type) and issubclass(kind, BaseException)):
            raise TypeError(event.kind)
        return kind(event.text)
    except (ImportError, AttributeError, TypeError, ValueError):
        return RunFailed(f"{event.kind}: {event.text}\n{event.detail}")


def gap_for(question: Choice) -> PendingGap:
    """Which place answers this question, from the code's own row.

    Read from the question rather than re-derived from its prompt, which
    is a sentence a tool wrote for a person. A question carrying no code
    names no place, which is a refusal rather than a guess.
    """
    if not question.code:
        raise KeyError("a question with no code names no place that can answer it")
    row = RESOLVABLE[question.code]
    return PendingGap(question.code, row.step, Place(row.place), question)


def _tell(app: Workbench, report: Callable[..., None], *carried: object) -> None:
    """Cross to the app thread, or give up because the crossing cannot be made.

    ``call_from_thread`` raises once the app has gone, which a confirmed
    quit during a run makes reachable -- and a raise on this worker ends
    nowhere at all.
    """
    try:
        app.call_from_thread(report, *carried)
    except RuntimeError:
        pass
