"""The run's own process: one driver, held across runs, reporting down a pipe.

Spec decision 18. Everything here happens on the far side of the boundary,
which is why nothing here knows what a place is, what a sidebar is or that
a screen exists: it is handed values and it sends values back. The driver
is kept between runs because decision 10's resume spends intermediates it
holds, and a process started per run would throw away the thing a resume
exists to reuse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from importlib import import_module
from multiprocessing.connection import Connection
from pathlib import Path
from traceback import format_exception
from typing import Any, Protocol

from stompmodel.diagnostics import exit_for_severity
from stompmodel.errors import StompError
from stompmodel.progress import Sink, track

from .. import manifest
from ..cancel import EXIT_CANCELLED, Cancelled, CancellingSink
from ..drive import Driver, Project, RunOptions
from ..plan import RunPlan, Step
from ..present import Choice, Question
from .wire import (
    Advanced,
    Answer,
    Asked,
    Began,
    Close,
    Command,
    Completed,
    Composed,
    Faulted,
    Reported,
    Resume,
    Settled,
    Start,
    command_of,
)

__all__ = ["COMPOSE", "TICK", "Shutdown", "serve"]

#: Where the run's process finds the function that composes a run. A dotted
#: name rather than the function itself, because ``spawn`` inherits nothing
#: and imports what it is told to -- which is also the one seam a test can
#: put a composer of its own through.
COMPOSE = "stompcad.drive:compose"

#: How often a paused run looks up from its wait. Polling here is free of
#: the cost that made it wrong before: it is the run that waits, and the
#: interface that draws.
TICK = 0.05

class Shutdown(BaseException):
    """The interface has finished with this process, mid-run or otherwise.

    Not an ``Exception`` and not ``Cancelled``: a ``Close`` that arrives
    while a run is paused must leave the server rather than become that
    run's outcome, because the command loop is waiting for the very
    message the paused run would have consumed.
    """


class _Stopping(Protocol):
    """Whatever carries the stop: a process event, or a thread's in a test."""

    def is_set(self) -> bool: ...


class _Flag(Protocol):
    """Whatever carries "a run is in flight": the interface reads it to quit."""

    def set(self) -> None: ...
    def clear(self) -> None: ...


def serve(
    commands: Connection,
    events: Connection,
    stopping: _Stopping,
    entry: str | Callable[..., Any] = COMPOSE,
    busy: _Flag | None = None,
) -> None:
    """Obey commands until told to close, keeping one driver across runs.

    ``entry`` is a dotted name for a process, which can be given nothing
    else, and may be the function itself for a caller in this interpreter.
    ``busy`` is set for exactly as long as a run is in flight, so the
    interface can tell a process it may end from one it must wait for.
    """
    try:
        runs = _Runs(_composer(entry), commands, events, stopping, busy)
        while True:
            command = command_of(commands.recv())
            if isinstance(command, Close):
                return
            runs.obey(command)
    except (Shutdown, EOFError):
        # ``Shutdown`` is a ``Close`` that reached a paused run instead of
        # this loop. Both mean the interface has finished with us, and
        # neither is a fault worth reporting to a pipe nobody is reading.
        return
    except BaseException as failure:  # noqa: BLE001 - reported, not printed
        # Reached when the entry cannot be imported, or when the loop
        # itself breaks. Nothing has been sent yet, so without this the
        # interface sees only a closed pipe and a session stuck RUNNING.
        with suppress(OSError):
            events.send(_faulted(failure))
    finally:
        events.close()


def _composer(entry: str | Callable[..., Any]) -> Callable[..., Any]:
    """The composing function, imported where only its name could cross."""
    if not isinstance(entry, str):
        return entry
    module, _, name = entry.partition(":")
    composer: Callable[..., Any] = getattr(import_module(module), name)
    return composer


class _Runs:
    """This project's runs, and the driver whose intermediates they share."""

    __slots__ = ("_asked", "_busy", "_commands", "_compose", "_driver", "_events", "_stopping")

    def __init__(
        self,
        compose: Callable[..., Any],
        commands: Connection,
        events: Connection,
        stopping: _Stopping,
        busy: _Flag | None = None,
    ) -> None:
        self._compose = compose
        self._commands = commands
        self._events = events
        self._stopping = stopping
        self._busy = busy
        self._driver: Driver | None = None
        # Questions are numbered so an answer can name the one it answers.
        # A run pauses more than once and a boundary delays everything, so
        # an answer to a question already closed must be recognisable as
        # stale rather than taken for the answer to the one now open.
        self._asked = 0

    def obey(self, command: Command) -> None:
        """Start or resume, marked busy throughout.

        An ``Answer`` reaching here answers nothing: ``ask`` takes its own,
        so one arriving between runs is a stale answer to a question that
        has already been closed, and dropping it is the whole point of
        numbering them.
        """
        if not isinstance(command, (Start, Resume)):
            return
        if self._busy is not None:
            self._busy.set()
        try:
            if isinstance(command, Start):
                self._guarded(lambda: self._start(command))
            else:
                self._guarded(lambda: self._resume(command))
        finally:
            if self._busy is not None:
                self._busy.clear()

    def _guarded(self, work: Callable[[], None]) -> None:
        """Report what happened into the pipe rather than out of the process.

        A run ending is not the process ending. The driver this run leaves
        is what the next `Ctrl+R` spends, so a fault escaping here would
        cost a resume the whole reason it is cheaper than starting over.
        """
        try:
            work()
        except Cancelled:
            self._events.send(Completed(EXIT_CANCELLED, None, self._written(), {}))
        except Shutdown:
            # The interface has gone. Let it leave the server rather than
            # becoming this run's outcome: a ``Close`` swallowed here is a
            # ``Close`` the command loop will wait for and never receive.
            raise
        except BaseException as failure:  # noqa: BLE001 - sent, not raised
            self._events.send(_faulted(failure))

    def _written(self) -> tuple[Path, ...]:
        """What a stopped run had already committed, where there is a driver to ask.

        A stop is heard at the next reported leaf, so a write may have
        committed before it. A first run hands its driver back as it
        returns, so a stop before then has nobody to ask.
        """
        return () if self._driver is None else self._driver.written

    def _start(self, command: Start) -> None:
        """Compose the whole plan, and keep the driver a later resume spends."""
        options = RunOptions.of(command.settings)
        project = Project(command.panel, command.settings, manifest.read(command.panel))
        driver, drill, dock = self._compose(
            command.plan, self._down(), options, project, self._stopping.is_set
        )
        self._driver = driver
        self._events.send(Composed())
        halves = [drill] + ([] if dock is None else [dock])
        found = [half.worst_severity for half in halves if half.worst_severity is not None]
        self._events.send(
            Completed(
                exit_for_severity(max(found) if found else None),
                tuple(found_ for half in halves for found_ in half.diagnostics),
                driver.written,
                driver.designators,
            )
        )

    def _resume(self, command: Resume) -> None:
        """Run the stale set against the intermediates this process still holds."""
        driver = self._driver
        assert driver is not None  # ``may_resume`` is what chose this path
        driver.declare(command.settings)
        sink: Sink = CancellingSink(self._down(), self._stopping.is_set)
        with track(sink) as scope:
            driver.resume(command.stale, RunOptions.of(command.settings), scope)
        self._events.send(
            Completed(
                exit_for_severity(
                    max((found.severity for found in driver.findings), default=None)
                ),
                tuple(driver.findings),
                driver.written,
                driver.designators,
            )
        )

    @property
    def asked(self) -> int:
        """The number of the question now open, which an answer must name."""
        return self._asked

    def numbered(self) -> None:
        """Open a new question, closing whatever number came before it."""
        self._asked += 1

    def _down(self) -> _Down:
        return _Down(self, self._commands, self._events, self._stopping)


class _Down:
    """``Presentation``, written into a pipe instead of onto a screen."""

    __slots__ = ("_commands", "_events", "_runs", "_stopping")

    def __init__(self, runs: _Runs, commands: Connection, events: Connection,
                 stopping: _Stopping) -> None:
        self._runs = runs
        self._commands = commands
        self._events = events
        self._stopping = stopping

    def begin(self, plan: RunPlan) -> None:
        self._events.send(Began(plan))

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self._events.send(Advanced(position, path))

    def finish_step(self, step: Step, outcome: str) -> None:
        self._events.send(Settled(step, outcome))

    def report(self, lines: Sequence[str]) -> None:
        self._events.send(Reported(tuple(lines)))

    def ask(self, question: Question) -> str:
        """Report the gap, then wait here until it is answered or stopped.

        Waiting on this side is the whole point: the interface is not
        blocked, it is drawing. A picker abandoned leaves the run paused
        and the picker reopenable, so only a stop ends a wait unanswered.
        """
        choice = _choice(question)
        self._runs.numbered()
        self._events.send(Asked(self._runs.asked, choice))
        while True:
            if self._stopping.is_set():
                raise Cancelled("the gap was left unanswered")
            if not self._commands.poll(TICK):
                continue
            command = command_of(self._commands.recv())
            if isinstance(command, Close):
                raise Shutdown("the interface closed on an open gap")
            if isinstance(command, Answer) and command.asked == self._runs.asked:
                return _offered(choice, command.text)


def _choice(question: Question) -> Choice:
    """The question as a value, refusing one no place can be found for.

    ``Presentation.ask`` takes a protocol, and an object satisfying it may
    carry no code. The app finds the place that answers a gap from that
    code, so a question without one strands this run waiting for an answer
    no screen will ever be shown. Refused here, where the refusal becomes
    this run's fault, rather than there, where it becomes the app's.
    """
    if not isinstance(question, Choice) or not question.code:
        raise StompError(f"a question with no code cannot be answered: {question.prompt}")
    return question


def _offered(choice: Choice, text: str) -> str:
    """The answer, if it is one this question offered. Decision 11.

    A picker chooses between answers a tool computed, and the boundary
    must not become the hole in that rule: an answer arriving over a pipe
    is checked against the question that is open, not trusted for having
    arrived. The empty string is the free-edit continuation, which answers
    by having changed a value rather than by naming a candidate.
    """
    if text == "":
        return text
    chosen = text.split(",") if choice.multiple else [text]
    unoffered = [one for one in chosen if one not in choice.candidates]
    if unoffered:
        raise StompError(f"{', '.join(unoffered)}: not among the answers offered")
    return text


def _faulted(failure: BaseException) -> Faulted:
    """A fault with enough of itself left for ``main`` to treat it as one.

    The class path travels so the far side can rebuild the type ``main``
    branches on; the traceback travels because the one the interface could
    produce would name the line that re-raised, which is this plan's own
    plumbing rather than anything that went wrong.
    """
    kind = type(failure)
    return Faulted(
        f"{kind.__module__}:{kind.__qualname__}",
        str(failure),
        "".join(format_exception(type(failure), failure, failure.__traceback__)),
    )
