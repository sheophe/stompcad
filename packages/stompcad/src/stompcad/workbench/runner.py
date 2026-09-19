"""The interface's end of the boundary: a process, and the events it sends.

Spec decision 18. The only module that knows a process exists. It is
spawned rather than forked -- a forked child would inherit the interface's
own memory, a live application included, at whatever moment the fork landed
-- and it is spawned once and kept, because the driver it holds is what
decision 10's resume spends.

Nothing here is built until the first run asks for it; see ``_serving``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnContext
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from typing import Protocol

from ..plan import RunPlan
from ..settings import Settings
from .child import child
from .wire import Answer, Close, Died, Event, Resume, Start, event_of

__all__ = ["COMPOSE", "GRACE", "SETTLE", "ProcessRunner", "Runner"]

#: Where the run's process finds the function that composes a run. Repeated
#: here rather than imported from ``serve``, because importing ``serve`` is
#: exactly what this module must not do.
COMPOSE = "stompcad.drive:compose"

#: How long a closing runner waits for a process with nothing in flight.
#: It has only to notice a message and return, so this is generous.
GRACE = 2.0

#: How long it waits for a process that is still running something. A stop
#: is heard at the next reported leaf, and a leaf may sit behind a long
#: kernel call, so this is long enough to cover one and still end.
SETTLE = 30.0


class Runner(Protocol):
    """Somewhere a run happens, and the events it sends back while it does."""

    def start(self, panel: Path, plan: RunPlan, settings: Settings) -> None: ...
    def resume(self, stale: frozenset[str], settings: Settings) -> None: ...
    def answer(self, asked: int, text: str) -> None: ...
    def stop(self) -> None: ...
    def events(self) -> Iterator[Event]: ...
    def close(self) -> None: ...


class ProcessRunner:
    """A run in a process of its own, spawned on the first run and kept.

    ``entry`` names the composing function rather than being one: a
    spawned process inherits nothing and imports what it is told to, so a
    name is the only kind of instruction that crosses.
    """

    __slots__ = (
        "_busy", "_closing", "_context", "_entry", "_from_run",
        "_process", "_stopping", "_to_run",
    )

    def __init__(self, entry: str = COMPOSE) -> None:
        self._entry = entry
        self._context: SpawnContext | None = None
        self._stopping: EventType | None = None
        self._busy: EventType | None = None
        self._process: BaseProcess | None = None
        self._to_run: Connection | None = None
        self._from_run: Connection | None = None
        self._closing = False

    @property
    def running(self) -> bool:
        """Whether there is a live process at the far end."""
        return self._process is not None and self._process.is_alive()

    def start(self, panel: Path, plan: RunPlan, settings: Settings) -> None:
        self._send(Start(panel, plan, settings))

    def resume(self, stale: frozenset[str], settings: Settings) -> None:
        self._send(Resume(stale, settings))

    def answer(self, asked: int, text: str) -> None:
        """Answer the question of that number; the run checks it is the open one."""
        assert self._to_run is not None  # only a paused run can be answered
        self._to_run.send(Answer(asked, text))

    def stop(self) -> None:
        """Ask the run to stop; it is heard at the next reported leaf."""
        if self._stopping is not None:
            self._stopping.set()

    def events(self) -> Iterator[Event]:
        """Every event the run sends, ending only when it has said why.

        Consumed by one worker for the application's whole life, which is
        why it outlasts a run: between runs it is simply blocked on a
        pipe, and blocking on a pipe is not work the interpreter is held
        for. An end of pipe nobody asked for is a ``Died`` rather than a
        quiet return, because a run that stops being reported is a run the
        workbench still believes is working.
        """
        self._serving()
        from_run = self._from_run
        assert from_run is not None  # ``_serving`` makes both ends
        # Captured locally rather than read from ``self`` each turn: this
        # generator is one worker held across a ``close()``, and ``close``
        # nulls ``self._from_run`` from underneath it. The connection
        # itself is still the one ``_forget`` closes, so ``recv`` still
        # raises once it does -- only the attribute lookup would have failed.
        while True:
            try:
                yield event_of(from_run.recv())
            except (EOFError, OSError):
                if not self._closing:
                    yield self._died()
                return

    def close(self) -> None:
        """No more runs. Asked, waited for, and never killed mid-run.

        ``drive._write`` stages and then commits with no cancellation point
        between, and both roll back by unwinding. A signal does not unwind,
        so a process with a run in flight is waited for -- the stop reaches
        it at its next leaf the way `esc` already does. Only a process
        sitting in its command loop is ever ended outright, and there
        nothing is in flight to roll back.
        """
        if self._process is None:
            return
        self._closing = True
        self.stop()
        with suppress(OSError, BrokenPipeError):
            if self._to_run is not None:
                self._to_run.send(Close())
        self._process.join(GRACE)
        if self._process.is_alive() and self._busy is not None and self._busy.is_set():
            # Still writing, or still inside the kernel call before one.
            # Waiting is the only safe thing, and a stop is already asked.
            self._process.join(SETTLE)
        if self._process.is_alive() and (self._busy is None or not self._busy.is_set()):
            self._process.terminate()
            self._process.join(GRACE)
        self._forget()

    def _send(self, command: Start | Resume) -> None:
        """Begin a run, on a process that may have to be made or remade."""
        if self._stopping is not None:
            self._stopping.clear()
        self._serving().send(command)

    def _died(self) -> Died:
        """Why the pipe ended, as far as this side can tell.

        The process is forgotten here rather than kept: the next run makes
        a fresh one, because a runner that could not be used again after a
        crash would make a crash the end of the session.
        """
        code = None if self._process is None else self._process.exitcode
        self._forget()
        return Died("the run's process ended without reporting", code)

    def _forget(self) -> None:
        """Let go of a process and its pipes, so the next run makes its own."""
        for end in (self._to_run, self._from_run):
            if end is not None:
                with suppress(OSError):
                    end.close()
        self._process, self._to_run, self._from_run = None, None, None

    def _serving(self) -> Connection:
        """The process, started on the first command rather than at open.

        Decision 1: opening last week's project to look at its artefacts
        must not cost kernel work, and this is where the kernel is loaded
        -- in the child, by ``child`` importing the server. Everything is
        built into locals and published only once the process is running,
        so a failed start leaves nothing half-made behind it.
        """
        if self._to_run is not None:
            return self._to_run
        if self._context is None:
            self._context = get_context("spawn")
            self._stopping = self._context.Event()
            self._busy = self._context.Event()
        commands_out, commands_in = self._context.Pipe(duplex=False)
        events_out, events_in = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=child,
            args=(commands_out, events_in, self._stopping, self._entry, self._busy),
            daemon=True,
        )
        try:
            process.start()
        except BaseException:
            for end in (commands_out, commands_in, events_out, events_in):
                with suppress(OSError):
                    end.close()
            raise
        # Each end belongs to one side. Closing the copies this process
        # kept is what makes the reader see EOF when the run's process
        # goes, rather than waiting on a pipe it is itself holding open.
        commands_out.close()
        events_in.close()
        self._closing = False
        self._process, self._to_run, self._from_run = process, commands_in, events_out
        return self._to_run
