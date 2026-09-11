"""The run drawn above the prompt: a bar, the steps, and what they settled into.

Decision 1: inline rather than full screen, so scrollback survives and the
record stays behind. The app owns the terminal and the main thread; the run
happens on a worker (Task 4), which reaches these methods only through
``call_from_thread``. Nothing here knows what a hole or a board is -- it
renders positions and strings a driver hands it.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from .plan import RunPlan, Step
from .present import step_line

__all__ = ["InlineApp"]


class InlineApp(App[int]):
    """The run above the prompt; ``run`` returns the exit code it earned.

    ``App[int]`` because ``exit`` hands its argument back out of ``run``,
    and the composed run's exit code is the one thing the caller needs.
    """

    CSS = """
    Screen:inline {
        height: auto;
        border: none;
        padding: 0;
    }
    """

    position: reactive[float] = reactive(0.0)
    branch: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self.plan: RunPlan | None = None
        self.settled: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(id="bar")
        yield Static(id="branch")

    def show(self, plan: RunPlan) -> None:
        """Record the plan, so a label can be padded to the widest it holds."""
        self.plan = plan

    def advance(self, position: float, path: tuple[str, ...]) -> None:
        self.position = position
        self.branch = " / ".join(path)

    def settle(self, step: Step, outcome: str) -> None:
        """Keep the finished line in the form a pipe would have received."""
        self.settled.append(step_line(step.label, outcome, self._width()))
        self._redraw()

    def record(self, lines: list[str]) -> None:
        """The provenance report, which follows the last step unchanged."""
        self.settled.extend(lines)
        self._redraw()

    def _width(self) -> int:
        if self.plan is None:
            return 0
        return max((len(step.label) for step in self.plan.steps), default=0)

    def watch_position(self) -> None:
        self._redraw()

    def watch_branch(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        if not self.is_running:
            return
        filled = int(self.position * 30)
        self.query_one("#bar", Static).update(
            "\n".join(self.settled + [f"  [{'#' * filled}{'.' * (30 - filled)}] {self.position:.0%}"])
        )
        self.query_one("#branch", Static).update(f"  {self.branch}")
