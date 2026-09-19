"""Composed runs that cost nothing, reachable by name from another process.

``ProcessRunner`` is given a dotted name rather than a function because a
process started by ``spawn`` inherits nothing and imports what it is told
to. That is the one seam a test can put a composer of its own through, so
these live at module level and keep no state a caller would want to read:
what a run did is what it reported, which is the only thing that crosses.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from stompcad.cancel import Cancelled
from stompcad.drive import Driver, Project, RunOptions
from stompcad.plan import RunPlan
from stompcad.present import Choice, Presentation
from stompmodel.diagnostics import Diagnostic, Severity

__all__ = [
    "BURN_SECONDS",
    "asking",
    "burning",
    "faulting",
    "holding",
    "narrating",
    "refusing",
    "steady",
]

#: How long ``burning`` holds the interpreter it is running in. Long enough
#: that an interface sharing that interpreter could not hide it, short
#: enough to sit in a suite.
BURN_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class _Data:
    """One half's data, as much of it as a run's outcome actually reads."""

    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def worst_severity(self) -> Severity | None:
        return max((found.severity for found in self.diagnostics), default=None)


class _Holding(Driver):
    """A driver that holds one thing, and spends it when it is resumed.

    Subclassed rather than duck-typed because the run's process keeps
    whatever ``compose`` hands back and a later resume spends it: a double
    that is not a ``Driver`` would prove nothing about that. What it holds
    is a nonce made at composition, so a resume that quietly built a fresh
    driver reports a different one and the test sees it.
    """

    def __init__(self, plan: RunPlan, presentation: Presentation, options: RunOptions) -> None:
        super().__init__(plan, presentation, options)
        self.nonce = f"{os.getpid()}:{uuid4().hex[:8]}"
        self.resumes = 0

    def declare(self, settings: object) -> None:
        return None

    def resume(self, stale: frozenset[str], options: RunOptions, scope: object) -> None:
        self.resumes += 1
        step = self._plan.steps[0]
        self._presentation.begin(RunPlan((step,)))
        self._presentation.finish_step(step, f"held {self.nonce} spent {self.resumes}")


def steady(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """Every step, immediately, with the process id as each step's outcome.

    The id is the assertion: a run in the interface's own process reports
    the interface's own number, so a test of the boundary needs nothing
    but the lines the run already sends.
    """
    presentation.begin(plan)
    for step in plan.steps:
        presentation.finish_step(step, f"pid {os.getpid()}")
    return Driver(plan, presentation, options), _Data(), None


def narrating(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """A position and a report line, the two events no other composer sends.

    Nothing in the suite drove ``Advanced`` or ``Reported`` across the
    boundary before this: both are values ``wire.py`` closes over, and a
    value nothing exercises is a value nothing has actually proven crosses.
    """
    presentation.begin(plan)
    presentation.update(0.5, ("seat",))
    presentation.report(["read 8 holes"])
    for step in plan.steps:
        presentation.finish_step(step, f"pid {os.getpid()}")
    return Driver(plan, presentation, options), _Data(), None


def holding(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[_Holding, _Data, None]:
    """A run whose driver can be told apart from any other driver."""
    driver = _Holding(plan, presentation, options)
    presentation.begin(plan)
    presentation.finish_step(plan.steps[0], f"made {driver.nonce}")
    return driver, _Data(), None


def burning(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """Pure Python work, which is the thing decision 18 is about.

    Not ``sleep`` and not a kernel call: both release the interpreter, and
    releasing it is what a thread already did well enough. What made the
    interface answer late was a run holding the lock between kernel calls,
    so that is what this holds.
    """
    presentation.begin(plan)
    deadline = time.monotonic() + BURN_SECONDS
    while time.monotonic() < deadline:
        sum(index * index for index in range(20_000))
        if stop is not None and stop():
            raise Cancelled("cancelled while working")
    for step in plan.steps:
        presentation.finish_step(step, f"pid {os.getpid()}")
    return Driver(plan, presentation, options), _Data(), None


def asking(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """One gap, then a step whose outcome is the answer that closed it."""
    presentation.begin(plan)
    answer = presentation.ask(
        Choice(
            prompt="reference outline is within tolerance of more than one footprint",
            candidates=("1590B", "1590B2"),
            multiple=False,
            code="ambiguous-enclosure",
        )
    )
    presentation.finish_step(plan.steps[0], f"answered {answer}")
    return Driver(plan, presentation, options), _Data(), None


def faulting(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """A run that breaks in a way ``main`` has no branch for."""
    presentation.begin(plan)
    raise ZeroDivisionError("the run broke")


def refusing(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[Driver, _Data, None]:
    """A run that breaks in a way ``main`` does have a branch for.

    ``OSError`` rather than a made-up class: the standing test asserts the
    interface still sees one, and an exit code the command line chooses by
    type is the thing a boundary is most likely to have quietly flattened.
    """
    presentation.begin(plan)
    raise OSError("disk full")
