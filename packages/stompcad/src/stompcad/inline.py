"""The run drawn above the prompt: a bar, the steps, and what they settled into.

Decision 1: inline rather than full screen, so scrollback survives and the
record stays behind. The app owns the terminal and the main thread; the run
happens on a worker (Task 4), which reaches these methods only through
``call_from_thread``. Nothing here knows what a hole or a board is -- it
renders positions and strings a driver hands it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Event

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from stompmodel.diagnostics import EXIT_USAGE

from .cancel import Cancelled
from .plan import RunPlan, Step
from .present import Question, step_line

__all__ = ["InlineApp", "ChoiceScreen", "TerminalPresentation"]


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

    BINDINGS = [("v", "cycle_level", "detail"), ("q", "stop", "stop")]

    LEVELS = ("bar", "steps", "tree")

    CHILDREN_PER_NODE = 8
    TREE_LINES = 60

    position: reactive[float] = reactive(0.0)
    branch: reactive[str] = reactive("")
    level: reactive[str] = reactive("bar")

    def __init__(self, level: str = "bar") -> None:
        super().__init__()
        self.plan: RunPlan | None = None
        self.settled: list[str] = []
        self._run: Callable[[], int] | None = None
        self.outcomes: dict[str, str] = {}
        self.seen: list[tuple[str, ...]] = []
        self._paths: set[tuple[str, ...]] = set()
        self.level = level
        self.stopping = False
        self.failure: BaseException | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="bar")
        yield Static(id="branch")

    def action_cycle_level(self) -> None:
        """Cycle the detail while work continues; decision 3's one key."""
        self.level = self.LEVELS[(self.LEVELS.index(self.level) + 1) % len(self.LEVELS)]

    def action_stop(self) -> None:
        """Ask the run to stop. The sink notices at its next reported leaf.

        Decision 9: a thread worker cannot be cancelled from outside, so
        this sets a flag ``CancellingSink`` polls rather than trying to
        interrupt the work directly.
        """
        self.stopping = True

    def enquire(self, question: Question, chosen: Callable[[str | None], None]) -> None:
        """Put the question on screen, and hand the answer back when it comes.

        Called across ``call_from_thread`` and returns at once: the worker
        waiting for ``chosen`` must not be waiting while this runs, or the
        app thread would be blocked on the thread that is blocked on it.
        ``None`` means nobody chose, which ``ask`` treats as a stop.
        """
        self.push_screen(ChoiceScreen(question), chosen)

    def watch_level(self) -> None:
        self._redraw()

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
            self.run_worker(lambda: self._finish(self._attempt(run)), thread=True)

    def _attempt(self, run: Callable[[], int]) -> int:
        """Run the work, keeping any fault for the main thread to raise.

        An exception here would otherwise die on the worker, leaving the
        run reporting success. ``main`` already maps every fault to an exit
        code, so the fault is carried out rather than mapped a second time.
        """
        try:
            return run()
        except BaseException as error:  # noqa: BLE001 - re-raised in ``_run``
            self.failure = error
            return EXIT_USAGE

    def _finish(self, code: int) -> None:
        self.call_from_thread(self.exit, code)

    def show(self, plan: RunPlan) -> None:
        """Record the plan, so a label can be padded to the widest it holds."""
        self.plan = plan

    def advance(self, position: float, path: tuple[str, ...]) -> None:
        self.position = position
        self.branch = " / ".join(path)
        if path and path not in self._paths:
            self._paths.add(path)
            self.seen.append(path)

    def settle(self, step: Step, outcome: str) -> None:
        """Keep the finished line in the form a pipe would have received."""
        self.settled.append(step_line(step.label, outcome, self._width()))
        self.outcomes[step.label] = outcome
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
        self.query_one("#bar", Static).update(self.rendered())
        self.query_one("#branch", Static).update("")

    def rendered(self) -> str:
        """What this level draws from the state the app already holds."""
        filled = int(self.position * 30)
        bar = f"  [{'#' * filled}{'.' * (30 - filled)}] {self.position:.0%}"
        if self.level == "bar":
            return "\n".join([bar, f"  {self.branch}"])
        if self.level == "steps":
            return "\n".join([*self._step_lines(), bar])
        return "\n".join([*self._tree_lines(), bar])

    def _step_lines(self) -> list[str]:
        """The nine steps, each gaining its outcome as it completes."""
        if self.plan is None:
            return list(self.settled)
        width = self._width()
        return [
            step_line(step.label, self.outcomes.get(step.label, ""), width).rstrip()
            for step in self.plan.steps
        ]

    def _divisions(self) -> dict[tuple[str, ...], list[str]]:
        """Every observed path split into the children each prefix reported."""
        children: dict[tuple[str, ...], list[str]] = {}
        for path in self.seen:
            for depth in range(1, len(path) + 1):
                bucket = children.setdefault(path[: depth - 1], [])
                if path[depth - 1] not in bucket:
                    bucket.append(path[depth - 1])
        return children

    def _branches(
        self, prefix: tuple[str, ...], indent: int, children: dict[tuple[str, ...], list[str]]
    ) -> list[str]:
        """One node's divisions, or a count where they are per-item leaves.

        Decision 3 wants the divisions a step reports, not its every hole,
        so a fan-out wider than ``CHILDREN_PER_NODE`` is counted rather
        than listed: ``drill``'s six stages show, their holes do not.
        """
        bucket = children.get(prefix, [])
        if len(bucket) > self.CHILDREN_PER_NODE:
            return ["  " + "  " * indent + f"{len(bucket)} items"]
        lines: list[str] = []
        for name in bucket:
            lines.append("  " + "  " * indent + name)
            lines.extend(self._branches((*prefix, name), indent + 1, children))
        return lines

    def _tree_lines(self) -> list[str]:
        """Each step, and beneath it the divisions its scope reported."""
        if self.plan is None:
            return list(self.settled)
        children = self._divisions()
        lines: list[str] = []
        for line, step in zip(self._step_lines(), self.plan.steps, strict=True):
            lines.append(line)
            lines.extend(self._branches((step.label,), 1, children))
        if len(lines) > self.TREE_LINES:
            return [*lines[: self.TREE_LINES], f"  ... {len(lines) - self.TREE_LINES} more"]
        return lines


class ChoiceScreen(ModalScreen[str]):
    """One finite choice, dismissed with the candidate somebody picked.

    ``ModalScreen[str]`` so ``dismiss`` carries the answer back to whoever
    pushed it. The candidates are the tool's own; this screen neither adds
    to them nor reorders them.
    """

    BINDINGS = [("q", "abandon", "stop")]

    def __init__(self, question: Question) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        yield Static(self._question.prompt)
        yield OptionList(*self._question.candidates)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))

    def action_abandon(self) -> None:
        """Give up on the question, so ``q`` means one thing everywhere."""
        self.dismiss(None)


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
        """Block this worker until somebody chooses, then return their answer.

        ``call_from_thread`` returns what its callable returned, which here
        is only the pushing of the modal -- the answer comes later, from a
        keypress, so the worker waits on an event the modal sets. Waiting
        must happen after the crossing, never during it, or the app thread
        would be blocked on the thread waiting for it. A screen popped
        without an answer never calls back at all, so the wait is bounded.
        """
        answered = Event()
        box: list[str | None] = []

        def chosen(answer: str | None) -> None:
            box.append(answer)
            answered.set()

        self._app.call_from_thread(self._app.enquire, question, chosen)
        while not answered.wait(0.05):
            if self._app.stopping or not self._app.is_running:
                raise Cancelled
        answer = box[0]
        if answer is None:
            raise Cancelled
        return answer

    def report(self, lines: Sequence[str]) -> None:
        self._app.call_from_thread(self._app.record, list(lines))
