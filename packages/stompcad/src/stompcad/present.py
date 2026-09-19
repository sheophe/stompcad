"""The presentation boundary: a run reports steps, asks, and writes a report.

Spec decision 2 requires one shared line format between a terminal's
settled scrollback and a pipe's streamed output, so ``PlainWriter`` keeps
that format in one place rather than duplicating it per output mode. The
presentation specification's decision 11 requires a genuine gap with no
terminal to exit ``3`` naming what was missing, which is why ``ask`` raises
rather than prompts. Plan B implements ``Presentation`` with a live
terminal; plan C is ``ask``'s only caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TextIO

from stompcad.plan import RunPlan, Step
from stompmodel.errors import StompError

__all__ = ["step_line", "Question", "Choice", "Presentation", "PlainWriter", "NoTerminal"]


def step_line(label: str, outcome: str, width: int = 0) -> str:
    """The one line a finished step leaves, wherever it is written.

    Decision 2: a terminal's settled scrollback and a pipe's stream are the
    same lines, so both writers render through this rather than each
    formatting its own. ``width`` pads the label into a column; zero means
    no plan is known yet and the label is simply unpadded.
    """
    return f"  {label:<{width}}  {outcome}"


class Question(Protocol):
    """A finite choice a run cannot make for itself."""

    @property
    def prompt(self) -> str: ...
    @property
    def candidates(self) -> tuple[str, ...]: ...
    @property
    def multiple(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class Choice:
    """One finite choice: what is asked, and the answers the tool computed.

    ``multiple`` is per code rather than per question. A panel is drawn for
    exactly one part; a board is usually held to the panel by several
    components, and offering one would satisfy the filter and then earn
    ``under-constrained-board`` from the next step -- a picker resolving one
    error into another. ``code`` is the diagnostic's own, so whoever draws
    the question finds the place that answers it without re-deriving it
    from a prompt a tool wrote for a person.
    """

    prompt: str
    candidates: tuple[str, ...]
    multiple: bool = False
    code: str = ""


class Presentation(Protocol):
    """What a run drives, whether a terminal draws it or a pipe streams it."""

    def begin(self, plan: RunPlan) -> None: ...
    def update(self, position: float, path: tuple[str, ...]) -> None: ...
    def finish_step(self, step: Step, outcome: str) -> None: ...
    def ask(self, question: Question) -> str: ...
    def report(self, lines: Sequence[str]) -> None: ...


class NoTerminal(StompError):
    """Raised when a run must ask, but has no terminal to ask on.

    The presentation specification's decision 11: a pipe or a dumb terminal
    exits with a usage error naming the missing question, rather than
    prompting where no one can answer.
    """


class PlainWriter:
    """Streams each step's line as it completes; nothing before, no bar.

    ``update`` does nothing -- there is no bar without a terminal.
    ``begin`` records the plan so ``finish_step`` can pad its label to the
    widest one the plan holds. Called before ``begin``, there is no known
    width yet, so the label is simply unpadded rather than guessed at.
    """

    def __init__(self, out: TextIO) -> None:
        self._out = out
        self._label_width = 0

    def begin(self, plan: RunPlan) -> None:
        self._label_width = max((len(step.label) for step in plan.steps), default=0)

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        self._out.write(step_line(step.label, outcome, self._label_width) + "\n")

    def ask(self, question: Question) -> str:
        raise NoTerminal(question.prompt)

    def report(self, lines: Sequence[str]) -> None:
        for line in lines:
            self._out.write(f"{line}\n")
