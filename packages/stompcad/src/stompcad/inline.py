"""The run drawn above the prompt: a bar, the steps, and what they settled into.

Decision 1: inline rather than full screen, so scrollback survives and the
record stays behind. The app owns the terminal and the main thread; the run
happens on a worker (Task 4), which reaches these methods only through
``call_from_thread``. Nothing here knows what a hole or a board is -- it
renders positions and strings a driver hands it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from .plan import RunPlan, Step
from .present import Question, step_line

__all__ = ["InlineApp", "TerminalPresentation"]


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
        self._run: Callable[[], int] | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="bar")
        yield Static(id="branch")

    def drive(self, run: Callable[[], int]) -> None:
        """Hold the run until there is a loop to start it on.

        Decision 1's second reason for a framework: a kernel query holds its
        thread for minutes, and the display must still answer a key while it
        does. ``run_worker`` needs a running app, and the caller has one only
        after ``run()``, so the start waits for ``on_mount``.
        """
        self._run = run

    def on_mount(self) -> None:
        run = self._run
        if run is not None:
            self.run_worker(lambda: self._finish(run()), thread=True)

    def _finish(self, code: int) -> None:
        self.call_from_thread(self.exit, code)

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


class TerminalPresentation:
    """The boundary plan A pinned, forwarded to an app on another thread.

    Every method crosses back through ``call_from_thread``: Textual forbids
    touching the UI from a worker, and the run that drives this lives on
    one. ``update`` also serves as the progress ``Sink``, the same double
    duty ``PlainWriter`` does, because the two signatures are one.
    """

    __slots__ = ("_app",)

    def __init__(self, app: InlineApp) -> None:
        self._app = app

    def begin(self, plan: RunPlan) -> None:
        self._app.call_from_thread(self._app.show, plan)

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self._app.call_from_thread(self._app.advance, position, path)

    def finish_step(self, step: Step, outcome: str) -> None:
        self._app.call_from_thread(self._app.settle, step, outcome)

    def ask(self, question: Question) -> str:
        raise NotImplementedError("Task 7 implements the picker")

    def report(self, lines: Sequence[str]) -> None:
        self._app.call_from_thread(self._app.record, list(lines))
