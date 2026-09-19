"""A real process at the far end: another interpreter, and a driver kept in it."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest

from stompcad.cancel import EXIT_CANCELLED
from stompcad.plan import DRILL_AND_DOCK
from stompcad.workbench import wire
from stompcad.workbench.runner import GRACE, ProcessRunner

from .projects import PANEL, runnable

__all__: list[str] = []

_PATIENCE = 60.0


@pytest.fixture
def runner() -> Iterator[Any]:
    """A runner whose composed run is cheap, closed however the test ends."""

    made: list[ProcessRunner] = []

    def build(entry: str = "tests.composers:steady") -> ProcessRunner:
        runner = ProcessRunner(entry=entry)
        made.append(runner)
        return runner

    yield build
    for runner in made:
        runner.close()


def _bounded_events(
    process: ProcessRunner, events: Iterator[wire.Event], deadline: float, waiting_for: str
) -> Iterator[wire.Event]:
    """``events``, with each wait for the next one bounded rather than open-ended.

    ``ProcessRunner.events()`` blocks on ``recv()`` for as long as the
    interface would hold it open -- correct for the pump that runs the
    app's whole life, wrong for a test. Polling ``_from_run`` first keeps
    the generator the only actual reader of the pipe; this only bounds
    how long a test waits for it to have something to read.
    """
    while True:
        remaining = deadline - time.monotonic()
        from_run = process._from_run  # noqa: SLF001 - bounding a wait recv() has no timeout for
        if from_run is not None and not from_run.poll(max(remaining, 0)):
            raise AssertionError(f"no {waiting_for} arrived within {_PATIENCE}s")
        try:
            yield next(events)
        except StopIteration:
            return


def _until(runner: ProcessRunner, kind: type) -> Any:
    """The next event of this kind, bounded by ``_PATIENCE``, failing on anything that ends the run."""
    deadline = time.monotonic() + _PATIENCE
    for event in _bounded_events(runner, runner.events(), deadline, f"a {kind.__name__}"):
        if isinstance(event, kind):
            return event
        if isinstance(event, (wire.Faulted, wire.Died)):
            raise AssertionError(f"the run ended instead: {event}")
    raise AssertionError(f"no {kind.__name__} arrived before the pipe closed")


def test_the_run_happens_in_another_interpreter(runner: Any) -> None:
    """Decision 18's structural requirement, asserted rather than measured.

    ``steady`` reports the process it ran in as each step's outcome, so
    this needs no clock: a run sharing the interface's interpreter would
    report the interface's own number.
    """
    process = runner()
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    settled = _until(process, wire.Settled)
    assert settled.outcome != f"pid {os.getpid()}"
    assert settled.outcome.startswith("pid ")


#: Run in a fresh interpreter, not this one: once anything in this test
#: process has spawned for real, the tracker is up for the process's whole
#: life and stays up, so a "before/after" check made here would pass
#: regardless of what the constructor does once collection has moved past
#: the first test that spawns.
_TRACKER_SCRIPT = (
    "from multiprocessing import resource_tracker\n"
    "from stompcad.workbench.runner import ProcessRunner\n"
    "assert resource_tracker._resource_tracker._pid is None\n"
    "runner = ProcessRunner()\n"
    "assert not runner.running\n"
    "assert resource_tracker._resource_tracker._pid is None\n"
)


def test_making_a_runner_starts_no_process_of_any_kind() -> None:
    """Decision 1: opening last week's project to look at it costs nothing.

    Every workbench makes a runner, including the many that never run
    anything. Checked against multiprocessing's own tracker rather than a
    private field, so a runner that built a ``spawn`` ``Event`` eagerly --
    which starts the tracker -- cannot pass by reporting a flag it never
    touched; checked in a fresh interpreter, because once this test
    process has spawned once, the tracker stays up for good.
    """
    result = subprocess.run(
        [sys.executable, "-c", _TRACKER_SCRIPT], capture_output=True, text=True, timeout=_PATIENCE
    )
    assert result.returncode == 0, result.stderr


def test_the_process_is_kept_between_runs(runner: Any) -> None:
    """One process, and the same driver in it, which is what a resume spends."""
    process = runner("tests.composers:holding")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    made = _until(process, wire.Settled).outcome.removeprefix("made ")
    _until(process, wire.Completed)
    process.resume(frozenset({"read panel"}), runnable())
    assert _until(process, wire.Settled).outcome == f"held {made} spent 1"


def test_a_process_that_dies_says_so(runner: Any) -> None:
    """A run that stops being reported is a workbench locked read-only.

    So the end of the pipe is an event. Killed from outside here, which is
    the case no protocol can prevent and every long-lived process meets.
    """
    process = runner("tests.composers:burning")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Began)
    process._process.kill()  # noqa: SLF001 - the point is that nobody asked
    assert isinstance(_until(process, wire.Died), wire.Died)


def test_a_run_can_follow_a_death(runner: Any) -> None:
    """A crash ends a run, not a session: the next one makes a fresh process."""
    process = runner("tests.composers:burning")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Began)
    process._process.kill()  # noqa: SLF001
    _until(process, wire.Died)
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    assert _until(process, wire.Began) is not None


def test_an_ordinary_close_is_not_reported_as_a_death(runner: Any) -> None:
    """The control for the two above: a runner crying death on every quit."""
    process = runner()
    stream = process.events()
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    for event in _bounded_events(process, stream, time.monotonic() + _PATIENCE, "a Completed"):
        if isinstance(event, wire.Completed):
            break
    process.close()
    seen = list(_bounded_events(process, stream, time.monotonic() + _PATIENCE, "the pipe to close"))
    assert not any(isinstance(event, wire.Died) for event in seen)


def test_a_quit_during_a_pause_ends_without_a_signal(runner: Any) -> None:
    """The one path that used to wedge: a ``Close`` reaching a paused run."""
    process = runner("tests.composers:asking")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Asked)
    started = time.monotonic()
    process.close()
    assert time.monotonic() - started < GRACE, "the close needed its whole grace"
    assert not process.running


def test_a_stale_answer_is_not_taken_for_the_open_one(runner: Any) -> None:
    """An answer names its question, because a boundary delays everything."""
    process = runner("tests.composers:asking")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    asked = _until(process, wire.Asked)
    process.answer(asked.asked + 7, "1590B")
    process.answer(asked.asked, "1590B")
    assert _until(process, wire.Settled).outcome == "answered 1590B"


def test_a_stop_crosses_while_the_run_is_working(runner: Any) -> None:
    """The stop is an event both sides see, not a message queued behind work."""
    process = runner("tests.composers:burning")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Began)
    process.stop()
    assert _until(process, wire.Completed).code == EXIT_CANCELLED


def test_a_second_run_is_not_stopped_by_the_first_ones_stop(runner: Any) -> None:
    """The control: a stop that latched would make every later run cancel."""
    process = runner("tests.composers:burning")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Began)
    process.stop()
    _until(process, wire.Completed)
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    assert _until(process, wire.Completed).code == 0


def test_an_answer_crosses_to_a_waiting_run(runner: Any) -> None:
    """The pause that navigates, all the way to the far side and back."""
    process = runner("tests.composers:asking")
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    asked = _until(process, wire.Asked)
    assert asked.question.code == "ambiguous-enclosure"
    process.answer(asked.asked, "1590B")
    assert _until(process, wire.Settled).outcome == "answered 1590B"


def test_closing_ends_the_process(runner: Any) -> None:
    """Quitting leaves nothing behind: the process is a daemon and is joined."""
    process = runner()
    process.start(PANEL, DRILL_AND_DOCK, runnable())
    _until(process, wire.Completed)
    process.close()
    assert not process.running


def test_closing_a_runner_that_never_ran_is_quiet(runner: Any) -> None:
    """Most sessions end without a run; ending one must not need a process."""
    runner().close()
