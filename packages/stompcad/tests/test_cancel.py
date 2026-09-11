"""Cancellation, and the exit contract that unwinds a stopped run.

Spec decision 9: a sink that raises is the whole mechanism. The first test
is the guard that a cancelled run leaves neither artefact nor temporary,
which holds because nothing is staged at any moment a sink can raise rather
than because rollback removes one; the second drives that rollback where it
can actually fire, and the rest pin the exit-code mapping ``cli.main``
applies once ``Cancelled`` or ``NoTerminal`` reaches it.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from stompcad import cli
from stompcad.cancel import EXIT_CANCELLED, Cancelled, CancellingSink
from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import NoTerminal, PlainWriter
from stompmodel.diagnostics import EXIT_USAGE
from stompmodel.progress import track
from stompmodel.protocols import Payload, stage_all
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, NullSink, case_model

__all__: list[str] = []


class _StopAfter:
    """Asks for a stop once the run has reported ``updates`` leaves."""

    def __init__(self, updates: int) -> None:
        self._left = updates

    def __call__(self) -> bool:
        self._left -= 1
        return self._left < 0


@pytest.mark.boards
@pytest.mark.hammond
def test_a_cancelled_run_leaves_neither_artefact_nor_temporary(tmp_path: Path) -> None:
    """Spec decision 9: a stopped run leaves nothing, because nothing is staged yet.

    Both write steps render every target before staging begins, so a sink
    has no moment to raise between a staged temporary and its commit. The
    rollback ADR-0001 states covers a fault *during* staging, which a
    raising sink cannot cause -- the test below drives that directly.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    target = tmp_path / "out.drl"
    options = RunOptions(
        panel=TAR_AI,
        boards=(TAR_PCB,),
        case="1590B",
        case_model=model,
        panel_reference=PANEL_REFERENCE,
        targets=(("excellon", target),),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)

    with pytest.raises(Cancelled):
        with track(CancellingSink(NullSink(), _StopAfter(updates=3))) as scope:
            driver.run(scope)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_stage_all_discards_a_staged_write_when_cancelled_partway(tmp_path: Path) -> None:
    """Direct proof of the mechanism the guard above relies on but never reaches.

    That guard's own cancellation lands during ``read panel``, well before
    ``stage_all`` runs at all -- it would pass unchanged even with
    ``stage_all``'s rollback deleted, because nothing was ever staged for it
    to roll back. This test drives ``stage_all`` itself with a target whose
    payload raises ``Cancelled`` mid-iteration, so the rollback this guards
    is the one actually exercised. See the task report for the red run this
    produced when ``protocols.py``'s handler was deliberately narrowed.
    """
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"

    def targets() -> Iterator[tuple[Path, Payload]]:
        yield first, b"staged before the cancellation"
        raise Cancelled("stop")
        yield second, b"never reached"  # pragma: no cover

    with pytest.raises(Cancelled):
        stage_all(targets())

    assert list(tmp_path.iterdir()) == []


def test_cancelling_sink_raises_once_stop_returns_true() -> None:
    sink = CancellingSink(NullSink(), _StopAfter(updates=1))
    sink.update(0.1, ())
    with pytest.raises(Cancelled):
        sink.update(0.2, ())


def test_cancelling_sink_delegates_until_stopped() -> None:
    seen: list[float] = []

    class _Recording:
        def update(self, position: float, path: tuple[str, ...]) -> None:
            seen.append(position)

    sink = CancellingSink(_Recording(), lambda: False)
    sink.update(0.5, ("a",))
    assert seen == [0.5]


def test_main_exits_130_for_a_run_the_user_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(args: object, out: object) -> None:
        raise Cancelled("cancelled at 30%")

    monkeypatch.setattr(cli, "_run", _raise)

    assert cli.main([str(TAR_AI)]) == EXIT_CANCELLED


def test_main_exits_3_for_a_gap_with_no_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(args: object, out: object) -> None:
        raise NoTerminal("which enclosure?")

    monkeypatch.setattr(cli, "_run", _raise)

    assert cli.main([str(TAR_AI)]) == EXIT_USAGE
