"""``ProcessRunner``'s twin, with a thread where the process goes.

Everything but the process is real: the same commands, the same ``serve``
loop, the same events through the same pipes. The tests that must see a
real process are ``test_runner.py``'s; these are about what the
application does with what comes back, and a thread makes each of them
cost milliseconds instead of a spawn. It takes its composer as a function
rather than a name because nothing here has to cross an interpreter --
which is also why it may keep one a test can read afterwards.
"""

from __future__ import annotations

import multiprocessing
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from stompcad.plan import RunPlan
from stompcad.settings import Settings
from stompcad.workbench.runner import GRACE
from stompcad.workbench.serve import serve
from stompcad.workbench.wire import Answer, Close, Died, Event, Resume, Start, event_of

__all__ = ["ThreadRunner"]


class ThreadRunner:
    """The runner protocol, served by a thread in this interpreter."""

    def __init__(self, compose: Callable[..., Any]) -> None:
        self._compose = compose
        self._stopping = threading.Event()
        self._busy = threading.Event()
        self._thread: threading.Thread | None = None
        self._to_run: Any = None
        self._from_run: Any = None
        self._closing = False

    def start(self, panel: Path, plan: RunPlan, settings: Settings) -> None:
        self._stopping.clear()
        self._serving().send(Start(panel, plan, settings))

    def resume(self, stale: frozenset[str], settings: Settings) -> None:
        self._stopping.clear()
        self._serving().send(Resume(stale, settings))

    def answer(self, asked: int, text: str) -> None:
        self._serving().send(Answer(asked, text))

    def stop(self) -> None:
        self._stopping.set()

    def events(self) -> Iterator[Event]:
        self._serving()
        while True:
            try:
                yield event_of(self._from_run.recv())
            except (EOFError, OSError):
                if not self._closing:
                    yield Died("the server thread ended without reporting", None)
                return

    def close(self) -> None:
        """Fail loudly on a thread that will not go, and let go of everything.

        A test runner that quietly abandoned a stuck thread would leak one
        per failing teardown, hold its pipes open, and let a re-seated
        suite go green over exactly the hangs this plan exists to avoid.
        """
        if self._thread is None:
            return
        self._closing = True
        self._stopping.set()
        with suppress(OSError):
            self._to_run.send(Close())
        self._thread.join(GRACE)
        alive = self._thread.is_alive()
        for end in (self._to_run, self._from_run):
            with suppress(OSError):
                end.close()
        self._thread, self._to_run, self._from_run = None, None, None
        assert not alive, "the served thread did not return on Close"

    def _serving(self) -> Any:
        if self._to_run is not None:
            return self._to_run
        commands_out, self._to_run = multiprocessing.Pipe(duplex=False)
        self._from_run, events_in = multiprocessing.Pipe(duplex=False)
        self._thread = threading.Thread(
            target=serve,
            args=(commands_out, events_in, self._stopping, self._compose, self._busy),
            daemon=True,
        )
        self._closing = False
        self._thread.start()
        return self._to_run
