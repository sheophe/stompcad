"""Decision 18's own instrument: the interface's tick, idle against working."""

from __future__ import annotations

import statistics
import time
from multiprocessing import get_context

import pytest

from stompcad.workbench.app import Workbench
from stompcad.workbench.run import Launch
from stompcad.workbench.runner import ProcessRunner, Runner

from .projects import PANEL, session, settle

__all__: list[str] = []

#: How often the interface is asked to do a trivial thing.
_INTERVAL = 0.01
#: How much later it may be while a run works than while nothing does. A
#: ratio rather than a number, because the number belongs to a machine.
#: Twenty is loose on purpose: the fault this guards against was two
#: orders of magnitude, and a test that fails on a busy machine teaches
#: people to delete it.
_RATIO = 20.0
#: The floor the ratio is taken against, so an idle machine measuring
#: near zero cannot make any working figure look like a regression.
_FLOOR_MS = 5.0


class _Tick:
    """How late the interface is to its own timer, sample by sample."""

    def __init__(self) -> None:
        self.late: list[float] = []
        self._last = time.perf_counter()

    def __call__(self) -> None:
        now = time.perf_counter()
        self.late.append((now - self._last - _INTERVAL) * 1000)
        self._last = now

    @property
    def worst(self) -> float:
        """The 95th percentile: a stall a person notices, not an average."""
        assert len(self.late) > 50, f"only {len(self.late)} samples; too few to say anything"
        return statistics.quantiles(self.late, n=20)[-1]


def _app(runner: Runner) -> Workbench:
    """A workbench with a project a run is one keypress away from."""
    return Workbench(session(), launch=Launch(panel=PANEL), runner=runner)


def _prime_multiprocessing() -> None:
    """Start the resource tracker before the app owns ``stderr``.

    A first ``spawn`` synchronisation primitive launches that tracker,
    which reads ``sys.stderr.fileno()``; Textual's own redirect answers
    that call with an invalid descriptor for as long as the app is
    running, which fails the launch. Any process that used
    multiprocessing before opening a workbench already avoids this.
    """
    get_context("spawn").Lock()


@pytest.mark.asyncio
async def test_the_interface_answers_while_a_run_works() -> None:
    """Spec decision 18. The property the process boundary exists for.

    Both figures come from one process and one application, seconds
    apart, so what is compared is the run's effect rather than two
    machines. The idle sample is taken first because taking it after
    would measure an interpreter still settling from the run.
    """
    _prime_multiprocessing()
    app = _app(ProcessRunner(entry="tests.composers:burning"))
    async with app.run_test() as pilot:
        idle = _Tick()
        timer = app.set_interval(_INTERVAL, idle)
        for _ in range(120):
            await pilot.pause()
        timer.stop()

        await pilot.press("r", "ctrl+r")
        working = _Tick()
        app.set_interval(_INTERVAL, working)
        await settle(pilot, app, patience=1500)

    assert working.worst < max(idle.worst * _RATIO, _FLOOR_MS * _RATIO)
