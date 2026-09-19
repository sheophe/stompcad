"""What crosses between the interface and the run, and nothing else.

Spec decision 18 puts the composed run in a process of its own, so the
boundary ADR-0013 pinned is now a boundary between processes. A pipe
carries values rather than objects, so the set of them is closed and
written here: two unions, no methods, no proxy, no ``Driver``. Something
that needs to cross and is not here is a design question rather than an
import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stompmodel.diagnostics import Diagnostic

from ..plan import RunPlan, Step
from ..present import Choice
from ..settings import Settings

__all__ = [
    "Advanced",
    "Answer",
    "Asked",
    "Began",
    "Close",
    "Command",
    "Completed",
    "Composed",
    "Died",
    "Event",
    "Faulted",
    "Reported",
    "Resume",
    "Settled",
    "Start",
    "command_of",
    "event_of",
]


# -- what the interface asks of a run -------------------------------------


@dataclass(frozen=True, slots=True)
class Start:
    """Compose this project's whole plan.

    The settings cross and the manifest does not: the run's process reads
    the project file beside the panel itself, which keeps the interface
    from being the one that decides what was on disk at the moment a run
    began.
    """

    panel: Path
    plan: RunPlan
    settings: Settings


@dataclass(frozen=True, slots=True)
class Resume:
    """Run the stale set against the intermediates the run's process holds."""

    stale: frozenset[str]
    settings: Settings


@dataclass(frozen=True, slots=True)
class Answer:
    """What somebody chose for the gap the run is paused on.

    ``asked`` names which question this answers. A run pauses more than
    once, and a boundary reorders nothing but delays everything, so an
    answer that arrives for a question already closed must be recognised
    as stale rather than taken for the answer to the question now open.
    """

    asked: int
    text: str


@dataclass(frozen=True, slots=True)
class Close:
    """No more runs. The process returns from ``serve`` and ends."""


Command = Start | Resume | Answer | Close


# -- what a run reports back ----------------------------------------------


@dataclass(frozen=True, slots=True)
class Began:
    """The plan this run intends to take, which may be less than the whole."""

    plan: RunPlan


@dataclass(frozen=True, slots=True)
class Advanced:
    """One position within the run's own span, and the branch reporting it."""

    position: float
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Settled:
    """A finished step, in the two parts the shared line format is built from."""

    step: Step
    outcome: str


@dataclass(frozen=True, slots=True)
class Reported:
    """What a write step said, in the lines a pipe would have received."""

    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Asked:
    """A gap the run cannot close for itself, narrowed to a value.

    ``Question`` is a protocol and an object satisfying it may be anything
    at all, including something no pipe can carry. ``resolve`` builds a
    ``Choice`` for every code a picker answers, so narrowing costs nothing
    real and makes the crossing a thing that can be typed.
    """

    asked: int
    question: Choice


@dataclass(frozen=True, slots=True)
class Composed:
    """A driver now exists over there; `Ctrl+R` has something to spend."""


@dataclass(frozen=True, slots=True)
class Completed:
    """The run ended. Everything the places need to draw what it left.

    ``diagnostics`` is ``None`` where there are none to record rather than
    none found: a stopped run says nothing about findings, which is not the
    same claim as a clean one.
    """

    code: int
    diagnostics: tuple[Diagnostic, ...] | None
    written: tuple[Path, ...]
    designators: dict[int, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Faulted:
    """A run that broke, with enough of its kind left to be treated as one.

    ``main`` chooses an exit code from the exception's type, so a fault
    that arrives as a sentence alone collapses branches the command line
    still has. ``refusal`` is that branch, decided where the exception
    itself is, because the side that reads a pipe must not import what the
    pipe names. ``kind`` names the class for a reader; ``detail`` is the
    traceback as the run's own process formatted it, because a traceback
    pointing at the line that re-raised names the messenger.
    """

    kind: str
    text: str
    detail: str
    refusal: bool


@dataclass(frozen=True, slots=True)
class Died:
    """The run's process ended without saying why: the last word either way.

    A run that stops being reported is still a run the workbench thinks is
    working, and a place is read-only while one is. So the end of the pipe
    is an event rather than the absence of them -- a crash, a failed
    import, an interpreter killed from outside.
    """

    reason: str
    code: int | None


Event = (
    Began | Advanced | Settled | Reported | Asked | Composed | Completed | Faulted | Died
)


def command_of(value: object) -> Command:
    """The value as a command, or a refusal. The closed set, enforced.

    A pipe carries whatever was put in it, so "only these cross" is a
    property of the code that reads rather than of the code that writes.
    Checked on arrival so a stray value is a fault naming itself, instead
    of a command silently ignored and a run that never starts.
    """
    if isinstance(value, (Start, Resume, Answer, Close)):
        return value
    raise TypeError(f"{type(value).__name__} is not something the run accepts")


def event_of(value: object) -> Event:
    """The value as an event, or a refusal. The same closure, facing back."""
    if isinstance(
        value,
        (Began, Advanced, Settled, Reported, Asked, Composed, Completed, Faulted, Died),
    ):
        return value
    raise TypeError(f"{type(value).__name__} is not something the run reports")
