"""The run's own side of the boundary, driven over a pipe without a process."""

from __future__ import annotations

import multiprocessing
import threading
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

import pytest

from stompcad.cancel import EXIT_CANCELLED
from stompcad.plan import DRILL_AND_DOCK
from stompcad.workbench import serve, wire

from . import composers
from .projects import PANEL, runnable

__all__: list[str] = []
#: Long enough that a slow machine does not fail a test about correctness,
#: short enough that a genuine hang is a failure rather than a coffee break.
_PATIENCE = 20.0


class _Served:
    """``serve`` on a thread, with both ends of both pipes in hand."""

    def __init__(self, compose: Any) -> None:
        commands_out, self.commands = multiprocessing.Pipe(duplex=False)
        self.events, events_in = multiprocessing.Pipe(duplex=False)
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=serve.serve,
            args=(commands_out, events_in, self.stopping, compose),
            daemon=True,
        )

    def send(self, command: wire.Command) -> None:
        self.commands.send(command)

    def until(self, kind: type) -> Any:
        """The next event of this kind, failing on anything that ends the run.

        A ``Faulted`` or a ``Died`` while waiting is the end of this run,
        so waiting past one waits for ever. Reported with its own text,
        because "no Completed arrived" names the symptom and the fault
        names the cause.
        """
        while self.events.poll(_PATIENCE):
            event = self.events.recv()
            if isinstance(event, kind):
                return event
            if isinstance(event, (wire.Faulted, wire.Died)):
                raise AssertionError(f"the run ended instead: {event}")
        raise AssertionError(f"no {kind.__name__} arrived")


@pytest.fixture
def served(request: pytest.FixtureRequest) -> Iterator[Any]:
    """A server for the composer named by the test's ``compose`` mark."""

    def build(compose: Any) -> _Served:
        served = _Served(compose)
        served.thread.start()
        request.addfinalizer(lambda: _shut(served))
        return served

    yield build


def _shut(served: _Served) -> None:
    """Every test ends the same way, and a server that will not end fails it."""
    served.stopping.set()
    with suppress(OSError):  # a server that already returned has closed its end
        served.send(wire.Close())
    served.thread.join(_PATIENCE)
    assert not served.thread.is_alive(), "serve did not return on Close"


def test_a_start_reports_the_plan_then_each_step(served: Any) -> None:
    """The events a run sends are the ones a presentation was always given."""
    server = served(composers.steady)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    assert server.until(wire.Began).plan == DRILL_AND_DOCK
    assert server.until(wire.Settled).step == DRILL_AND_DOCK.steps[0]
    assert server.until(wire.Completed).code == 0


def test_a_driver_is_announced_before_the_run_is_finished(served: Any) -> None:
    """`Ctrl+R` needs to know a driver exists, which is not the same as done."""
    server = served(composers.steady)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    seen: list[type] = []
    while server.events.poll(_PATIENCE):
        seen.append(type(server.events.recv()))
        if seen[-1] is wire.Completed:
            break
    assert wire.Completed in seen, "the run never finished"
    assert seen.index(wire.Composed) < seen.index(wire.Completed)


def test_the_driver_outlives_one_run(served: Any) -> None:
    """Decision 10: a resume spends what the first run left, so it is still there.

    The nonce is what makes this an assertion rather than an observation:
    a server that quietly composed a fresh driver for the resume would
    still reach ``Completed``, and would report a different one.
    """
    server = served(composers.holding)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    made = server.until(wire.Settled).outcome.removeprefix("made ")
    server.until(wire.Completed)
    server.send(wire.Resume(frozenset({"read panel"}), runnable()))
    assert server.until(wire.Settled).outcome == f"held {made} spent 1"


def test_a_resume_with_nothing_held_is_a_fault_rather_than_a_crash(served: Any) -> None:
    """The control for the test above, and the path a lost process takes.

    ``may_resume`` is what stops this happening, but a guard on the far
    side of a boundary is a guard that can be raced, and a process that
    dies takes its driver with it.
    """
    server = served(composers.holding)
    server.send(wire.Resume(frozenset({"read panel"}), runnable()))
    assert server.until(wire.Faulted) is not None
    assert server.thread.is_alive()


def test_a_close_during_a_pause_ends_the_server(served: Any) -> None:
    """A ``Close`` reaching a paused run must leave, not become its outcome.

    The command loop and a paused ``ask`` read the same pipe. A ``Close``
    consumed as this run's cancellation is a ``Close`` the loop then waits
    for and never receives, and the only way out of that is a signal --
    which is the one thing a quit must never need.
    """
    server = served(composers.asking)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    server.until(wire.Asked)
    server.send(wire.Close())
    server.thread.join(_PATIENCE)
    assert not server.thread.is_alive(), "the server was left waiting for a second Close"


def test_a_stale_answer_does_not_close_the_question_now_open(served: Any) -> None:
    """An answer names the question it answers, because a pipe delays everything."""
    server = served(composers.asking)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    asked = server.until(wire.Asked)
    server.send(wire.Answer(asked.asked + 7, "1590B"))
    assert not server.events.poll(0.2), "a stale answer was taken for this one"
    server.send(wire.Answer(asked.asked, "1590B"))
    assert server.until(wire.Settled).outcome == "answered 1590B"


def test_an_answer_the_question_did_not_offer_is_refused(served: Any) -> None:
    """Decision 11: a picker chooses between answers a tool computed.

    The boundary must not become the hole in that rule. An answer arriving
    over a pipe is checked against the question that is open, rather than
    trusted for having arrived.
    """
    server = served(composers.asking)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    asked = server.until(wire.Asked)
    server.send(wire.Answer(asked.asked, "1590XX"))
    faulted = server.until(wire.Faulted)
    assert "not among the answers offered" in faulted.text


def test_a_gap_waits_on_this_side_of_the_boundary(served: Any) -> None:
    """The interface is not waiting; it is drawing. The run is the one blocked."""
    server = served(composers.asking)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    asked = server.until(wire.Asked)
    assert asked.question.code == "ambiguous-enclosure"
    assert not server.events.poll(0.2), "the run went on without an answer"
    server.send(wire.Answer(asked.asked, "1590B"))
    assert server.until(wire.Settled).outcome == "answered 1590B"


def test_a_stop_ends_an_unanswered_gap(served: Any) -> None:
    """A picker abandoned leaves the run paused; only a stop ends the wait."""
    server = served(composers.asking)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    server.until(wire.Asked)
    server.stopping.set()
    assert server.until(wire.Completed).code == EXIT_CANCELLED


def test_a_stop_while_working_is_heard_at_the_next_leaf(served: Any) -> None:
    """The same granularity progress already reports at -- no finer."""
    server = served(composers.burning)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    server.until(wire.Began)
    server.stopping.set()
    completed = server.until(wire.Completed)
    assert completed.code == EXIT_CANCELLED
    assert completed.diagnostics is None


def test_a_fault_is_sent_rather_than_raised(served: Any) -> None:
    """A run ending is not the process ending: the next resume needs it alive."""
    server = served(composers.faulting)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    faulted = server.until(wire.Faulted)
    assert faulted.text == "the run broke"
    assert faulted.kind == "builtins:ZeroDivisionError"


def test_a_fault_carries_the_traceback_of_where_it_happened(served: Any) -> None:
    """The interface's own traceback would name the line that re-raised."""
    server = served(composers.faulting)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    assert "composers.py" in server.until(wire.Faulted).detail


def test_a_fault_the_command_line_branches_on_keeps_its_kind(served: Any) -> None:
    """``main`` chooses an exit code by type, so the type has to survive."""
    server = served(composers.refusing)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    assert server.until(wire.Faulted).kind == "builtins:OSError"


def test_an_entry_that_cannot_be_imported_is_reported(served: Any) -> None:
    """A child that fails before its loop must still say so.

    Without this the interface sees a closed pipe and nothing else, and a
    closed pipe is indistinguishable from a run that simply stopped being
    reported -- which leaves every place read-only with no way back.
    """
    server = served("tests.composers:no_such_composer")
    assert server.until(wire.Faulted) is not None


def test_the_process_survives_a_fault(served: Any) -> None:
    """The control for the test above: a dead server would pass it too."""
    server = served(composers.faulting)
    server.send(wire.Start(PANEL, DRILL_AND_DOCK, runnable()))
    server.until(wire.Faulted)
    assert server.thread.is_alive()
