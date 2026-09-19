"""Every value that crosses the boundary crosses it, and arrives equal."""

from __future__ import annotations

import io
import pickle
from pathlib import Path

import pytest

from stompcad import manifest
from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import Choice, PlainWriter
from stompcad.settings import DEFAULTS
from stompcad.workbench import wire
from stompmodel.diagnostics import Diagnostic, Severity

from .projects import runnable


def _options() -> RunOptions:
    """Options a driver can be built from, which ``DEFAULTS`` cannot give.

    ``DEFAULTS.artwork.panel`` is ``None`` and ``RunOptions.of`` refuses a
    project with no panel, which is the right refusal and the reason every
    test here that needs options asks ``runnable()`` for them.
    """
    return RunOptions.of(runnable())

__all__: list[str] = []


def _crossed(value: object) -> object:
    """The value as the far side receives it: through a pickle and back.

    ``Connection.send`` pickles, so this is the crossing itself rather than
    a stand-in for it -- a value that does not survive here does not reach
    the other end of the pipe either.
    """
    return pickle.loads(pickle.dumps(value))


# ``DEFAULTS`` is deliberate here and nowhere else: these tests pickle a
# command, they never build a run from one. Every test that *starts* a run
# uses ``runnable()``, because ``RunOptions.of(DEFAULTS)`` refuses a project
# with no panel -- which is the right refusal, and a whole afternoon.
@pytest.mark.parametrize(
    "command",
    [
        wire.Start(Path("/project/tar.ai"), DRILL_AND_DOCK, DEFAULTS),
        wire.Resume(frozenset({"quantise", "drill"}), DEFAULTS),
        wire.Answer(1, "1590B"),
        wire.Close(),
    ],
)
def test_every_command_crosses(command: wire.Command) -> None:
    """What the interface asks of a run survives the pipe, unchanged."""
    assert _crossed(command) == command


@pytest.mark.parametrize(
    "event",
    [
        wire.Began(DRILL_AND_DOCK),
        wire.Advanced(0.5, ("drill", "holes")),
        wire.Settled(DRILL_AND_DOCK.steps[0], "read 42 holes"),
        wire.Reported(("wrote tar-case.drl",)),
        wire.Asked(1, Choice("which part?", ("1590B", "1590B2"), False, "ambiguous-enclosure")),
        wire.Composed(),
        wire.Completed(0, (), (Path("/project/tar-case.drl"),), {1: ("RV1",)}),
        wire.Faulted("builtins:OSError", "disk full", "Traceback...\n", True),
        wire.Died("the run's process ended without reporting", 1),
    ],
)
def test_every_event_crosses(event: wire.Event) -> None:
    """What a run reports survives the pipe, unchanged."""
    assert _crossed(event) == event


def test_a_diagnostic_keeps_its_severity_across_the_boundary() -> None:
    """The findings a run produced are what the places draw, so they cross whole."""
    finding = Diagnostic(
        code="ambiguous-enclosure", severity=Severity.ERROR, message="two footprints match"
    )
    completed = wire.Completed(2, (finding,), (), {})
    crossed = _crossed(completed)
    assert isinstance(crossed, wire.Completed)
    assert crossed.diagnostics is not None
    assert crossed.diagnostics[0].severity is Severity.ERROR
    assert crossed.diagnostics[0].code == "ambiguous-enclosure"


def test_a_project_file_crosses_because_the_run_reads_its_own() -> None:
    """``Start`` carries settings; the run's process reads the manifest itself."""
    assert _crossed(manifest.Manifest()) == manifest.Manifest()


def test_a_driver_is_refused_rather_than_carried() -> None:
    """A driver is the thing most tempting to send, and the thing that must not.

    Its value is the intermediates it holds, which are the whole reason
    the run's process stays alive; a copy of one is an empty shell that
    would make a resume silently start over. Refused by the reader rather
    than trusted to be unpicklable -- some of it would pickle.
    """
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), _options())
    with pytest.raises(TypeError, match="not something the run accepts"):
        wire.command_of(driver)


def test_a_stray_value_is_refused_in_both_directions() -> None:
    """The closed set is closed by the code that reads, not by the type alias.

    ``Connection.send`` carries any picklable object and a union alias
    checks nothing at runtime, so without this a stray value is a command
    silently ignored -- a run that never starts and never says why.
    """
    with pytest.raises(TypeError, match="not something the run accepts"):
        wire.command_of("start please")
    with pytest.raises(TypeError, match="not something the run reports"):
        wire.event_of(wire.Close())


def test_the_refusal_control_admits_what_belongs() -> None:
    """The control for the two above: a reader that refused everything would pass them."""
    assert wire.command_of(wire.Answer(1, "1590B")) is not None
    assert wire.event_of(wire.Composed()) is not None
