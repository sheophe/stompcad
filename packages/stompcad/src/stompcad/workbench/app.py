"""The workbench: eight places on one screen, and the keys that move them.

Spec decisions 1, 3, 4, 5 and 14. Every rule lives in ``Session``; this is
drawing and dispatch. Bindings are built from ``keys``, so the table proved
distinct is the table the application answers. A run is an event here rather
than the app's exit, so starting it, stopping it and quitting are three acts.

No bare letter is a priority binding: an open text field consumes a printable
key before any binding is checked. The stop is, because it must outrank a modal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Input, Static, TextArea

from stompmodel.diagnostics import EXIT_ERRORS, Diagnostic
from stompmodel.errors import StompError
from stompmodel.model import CaseFace

from .. import discover
from ..plan import RunPlan, Step
from ..present import step_line
from .keys import GLOBAL_VERBS, LOCAL_KEYS, PLACE_KEYS, RUN_KEYS, STEP_KEYS, Place
from .places import (
    Editor,
    Field,
    FocusRow,
    Kind,
    PickerScreen,
    RunView,
    ValueRow,
    choices_for,
    chosen_for,
    field_of,
    pane_for,
    position_line,
    table_bindings,
)
from .run import Launch, start
from .session import Locked, Phase, Refused, Session
from .sidebar import Sidebar

__all__ = ["Workbench", "KeysScreen", "ConfirmScreen"]


class Workbench(App[int], inherit_bindings=False):
    """The project open, full screen. ``run`` hands back the exit code it earned.

    Textual's own chords are not inherited: its priority ``ctrl+q`` would quit
    without the session's exit code, and the palette's ``ctrl+p`` would answer
    in every place. Neither is in the table decision 3 proves distinct.
    """

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #body { width: 1fr; padding: 0 1; }
    #mode { dock: bottom; height: 1; background: $panel; }
    """

    BINDINGS = table_bindings()

    message: reactive[str] = reactive("")

    def __init__(self, session: Session, launch: Launch | None = None) -> None:
        super().__init__()
        self.session = session
        self.launch = launch
        self._base: Screen[Any] | None = None
        # What the run leaves behind, in the form a pipe would have received
        # it (decision 15), plus where the run stands while it is working.
        self.plan: RunPlan | None = None
        self.settled: list[str] = []
        self.outcomes: dict[str, str] = {}
        self.position = 0.0
        self.branch = ""
        self.stopping = False
        self.failure: BaseException | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Sidebar()
            yield Vertical(id="body")
        yield Static(id="mode")

    async def on_mount(self) -> None:
        self._base = self.screen
        await self.redraw()

    # -- drawing -----------------------------------------------------------

    def mode(self) -> str:
        """Which mode the footer states. Decision 3's one hazard, closed."""
        focused = self.focused
        typing = focused is not None and focused.can_focus and _is_text(focused)
        return "typing" if typing else "moving"

    async def redraw(self, field: str | None = None) -> None:
        """Draw the sidebar, the current place and the mode line.

        Drawn on the base screen, which a picker may still be covering. The
        old pane's removal is awaited first, since both carry one id when the
        place is unchanged. Focus lands on ``field``'s row, else the first.
        A run reports through ``call_later``, so one can arrive after the app
        has begun tearing its widgets down; there is nothing left to draw on.
        """
        if not self.is_running:
            return
        base = self._base if self._base is not None else self.screen
        base.query_one(Sidebar).show(self.session.rows())
        body = base.query_one("#body", Vertical)
        await body.remove_children()
        await body.mount(pane_for(self.session, self.session.place, self._run_view()))
        rows = list(body.query(FocusRow))
        target = next((row for row in rows if row.field == field), rows[0] if rows else None)
        if target is not None:
            target.focus()
        self._show_mode()

    def _run_view(self) -> RunView:
        """What the `Run` place draws, gathered from what the run has reported."""
        return RunView(tuple(self.settled), self.position, self.branch)

    def _refresh(self) -> None:
        """Schedule a redraw from a method the worker crossed into.

        ``redraw`` remounts the pane and so must be awaited; the run reports
        from a thread and cannot await anything, so the app's own loop takes
        it from here.
        """
        self.call_later(self.redraw)

    def redraw_run(self) -> None:
        """Update the live line alone. A full redraw per leaf would move focus."""
        if not self.is_running:
            return
        base = self._base if self._base is not None else self.screen
        for line in base.query("#run-position").results(Static):
            line.update(position_line(self.position, self.branch))

    def _show_mode(self) -> None:
        if self._base is not None and self.is_running:
            self._base.query_one("#mode", Static).update(self._mode_line())

    def _mode_line(self) -> str:
        if self.mode() == "typing":
            return "  typing — letters type here; esc leaves the field" + self._tail()
        return "  moving — letters jump to a place; ? for the keys" + self._tail()

    def _tail(self) -> str:
        return f"    {self.message}" if self.message else ""

    def watch_message(self) -> None:
        self._show_mode()

    def on_descendant_focus(self, _event: events.DescendantFocus) -> None:
        """The footer follows focus, because focus is what decides the mode."""
        self._show_mode()

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self._show_mode()

    def sidebar_text(self) -> str:
        """Every sidebar row as one string. For tests, and for nothing else."""
        return "\n".join(
            str(row.content) for row in self.query_one(Sidebar).query(Static)
        )

    # -- moving ------------------------------------------------------------

    async def action_go(self, place: str) -> None:
        self._leave_modal()
        self.session.go(Place(place))
        self.message = ""
        await self.redraw()

    async def action_step_place(self, forward: bool) -> None:
        self._leave_modal()
        self.session.step_place(forward)
        self.message = ""
        await self.redraw()

    def _leave_modal(self) -> None:
        """Decision 12: a picker is transient, so leaving closes it uncommitted.

        The keys screen closes the same way: a place letter pressed over it
        means what it means anywhere else, and leaving the help open behind
        the place it moved to would be a second state to get out of.
        """
        if isinstance(self.screen, (PickerScreen, KeysScreen)):
            self.pop_screen()

    async def on_sidebar_chosen(self, event: Sidebar.Chosen) -> None:
        await self.action_go(event.place.value)

    # -- changing ----------------------------------------------------------

    async def on_value_row_edit(self, event: ValueRow.Edit) -> None:
        """`enter` on a row: a field for text, a picker for a list."""
        if not self.session.may_edit(event.place):
            self.message = "nothing is editable while a run is working"
            return
        field = field_of(event.place, event.field)
        typed = field.name == "panel_reference" and not self.session.designators
        if field.kind in (Kind.CHOICE, Kind.MANY) and not typed:
            self._open_picker(event.place, field)
            return
        base = self._base if self._base is not None else self.screen
        await base.query(Editor).remove()
        editor = Editor(event.row)
        editor.placeholder = str(event.row.content)
        pane = event.row.parent
        assert isinstance(pane, Widget)
        await pane.mount(editor, after=event.row)
        editor.focus()

    def _open_picker(self, place: Place, field: Field) -> None:
        """Offer the owning tool's answers, or say why there are none to offer."""
        try:
            choices = choices_for(self.session, place, field.name)
        except (StompError, OSError) as failure:
            self.message = str(failure)
            return
        if field.kind is Kind.CHOICE and not choices:
            self.message = f"there is nothing to choose from for {field.name.replace('_', ' ')}"
            return
        picker = PickerScreen(
            field,
            choices,
            multiple=field.kind is Kind.MANY,
            chosen=chosen_for(self.session, place, field.name),
        )
        self.push_screen(picker, lambda answer: self._picked(place, field, answer))

    def _picked(self, place: Place, field: Field, answer: object) -> None:
        """A picker's answer, or ``None`` when `escape` abandoned it."""
        if answer is None:
            return
        self._commit(place, field.name, answer)
        self.call_later(self.redraw, field.name)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        editor = event.input
        if not isinstance(editor, Editor):
            return
        self._commit(editor.row.place, editor.row.field, event.value)
        await self.redraw(editor.row.field)

    def _commit(self, place: Place, field: str, answer: object) -> None:
        """Convert, then hand the value over; a refusal is shown, never taken."""
        try:
            self.session.set(place, field, _as_value(self.session, place, field, answer))
        except (Refused, Locked, ValueError) as failure:
            self.message = str(failure)
            return
        self.message = ""

    # -- the run -----------------------------------------------------------

    def show(self, plan: RunPlan) -> None:
        """The plan the run intends to take, which may be less than the whole."""
        self.plan = plan
        self.session.begin_run(frozenset(step.key for step in plan.steps))
        self._refresh()

    def advance(self, position: float, path: tuple[str, ...]) -> None:
        self.position = position
        self.branch = " / ".join(path)
        self.redraw_run()

    def settle(self, step: Step, outcome: str) -> None:
        """Keep the finished line in the form a pipe would have received."""
        self.settled.append(step_line(step.label, outcome, self._label_width()))
        self.outcomes[step.key] = outcome
        self.session.credit(step.key)
        self._refresh()

    def record(self, lines: list[str]) -> None:
        """The provenance report, which follows the last step unchanged."""
        self.settled.extend(lines)
        self._refresh()

    def completed(
        self,
        code: int,
        diagnostics: Sequence[Diagnostic] | None,
        written: Sequence[Path],
        designators: Mapping[int, tuple[str, ...]],
    ) -> None:
        """The run ended. Its code is the app's until another run earns one."""
        self.session.finish_run(code)
        if diagnostics is not None:
            self.session.record_findings(diagnostics)
        self.session.record_written(written)
        self.session.record_designators(designators)
        self._refresh()

    def fault(self, failure: BaseException) -> None:
        """A run that broke. The app stays; the run does not."""
        self.failure = failure
        self.session.finish_run(EXIT_ERRORS)
        self.message = f"the run failed: {failure}"
        self._refresh()

    def _label_width(self) -> int:
        """The column a step's label is padded into, from the plan the run declared.

        Decision 15: these lines are byte-compared against the same run
        piped, and ``PlainWriter`` pads from the plan it was given in
        ``begin``. Deriving the width any other way is how the two diverge.
        """
        if self.plan is None:
            return 0
        return max((len(step.label) for step in self.plan.steps), default=0)

    def action_start_run(self) -> None:
        """`Ctrl+R` on the Run place, and `enter` on Project's run row."""
        if self.session.phase is Phase.RUNNING:
            self.message = "a run is already working"
            return
        if not self.session.may_run():
            self.message = self.session.statement()
            return
        if self.launch is None:
            self.message = "no project is open"
            return
        self.plan = self.launch.plan
        self.settled = []
        self.outcomes = {}
        self.position = 0.0
        self.branch = ""
        self.failure = None
        self.message = ""
        # Decision 5 binds from the keypress, not from the worker's first
        # crossing: a window in which a place still accepts an edit is a
        # window in which a value can change under work already under way.
        self.session.begin_run(frozenset(step.key for step in self.launch.plan.steps))
        start(self)
        self._refresh()

    def action_stop_run(self) -> None:
        """Ask the run to stop; the sink notices at its next reported leaf."""
        if self.session.phase in (Phase.RUNNING, Phase.PAUSED):
            self.stopping = True
            self.message = "stopping…"

    def action_escape(self) -> None:
        """The ladder, innermost first. Task 9 adds the paused rung."""
        if isinstance(self.screen, (PickerScreen, KeysScreen)):
            self.pop_screen()
            return
        if self._editors():
            self._close_editor()
            return
        if self.session.place is Place.RUN:
            self.action_stop_run()

    def _editors(self) -> list[Editor]:
        base = self._base if self._base is not None else self.screen
        return list(base.query(Editor))

    def _close_editor(self) -> None:
        for editor in self._editors():
            editor.action_close()

    # -- the verbs ---------------------------------------------------------

    def action_verb(self, verb: str) -> None:
        if verb == "window":
            self.action_window()
        elif verb == "keys":
            self.action_keys()
        else:
            self._quit()

    def _quit(self) -> None:
        """Decision 14: `q` quits, stopping any run first and confirming during one.

        Quitting and stopping are different acts once the app outlives the
        run, so throwing minutes of kernel work away takes an answer rather
        than one key.
        """
        if self.session.phase in (Phase.RUNNING, Phase.PAUSED):
            self.push_screen(ConfirmScreen(), self._quit_confirmed)
            return
        self.exit(self.session.exit_code)

    def _quit_confirmed(self, leave: bool | None) -> None:
        if leave:
            self.action_stop_run()
            self.exit(self.session.exit_code)

    def action_window(self) -> None:
        """Open the viewer on the current subject.

        Decision 13: ``available()`` false means ``w`` explains why rather
        than failing, and the default implementation is the null one -- so
        the whole workbench ships, runs and passes its suite with no window
        in existence. Plan 3 replaces this body with ``Window.open``.
        """
        self.message = "no viewer is installed, so there is nothing to open"

    def action_keys(self) -> None:
        self.push_screen(KeysScreen())

    def action_local(self, key: str) -> None:
        """Refuse a place's own key pressed somewhere else, and say where it lives."""
        owner, detail = LOCAL_KEYS[key]
        if self.session.place is not owner:
            self.message = f"{key} belongs to {owner.value.capitalize()} ({detail})"
            return
        if key == "ctrl+r":
            self.action_start_run()
            return
        self.message = f"{detail} is not wired up yet"


#: Rows whose empty answer means "not given" rather than an empty string.
_OPTIONAL = frozenset({
    "case", "case_model", "grid_warn_mm", "drill_sizes", "no_drill_sizes", "match_tolerance_mm",
})


def _as_value(session: Session, place: Place, field: str, answer: object) -> object:
    """What an editor or picker handed back, as the value ``Settings`` carries.

    Every conversion is here, keyed by the row's kind, so kinds and
    conversions are one statement. Targets are paired and sorted by format
    name -- the manifest's own order -- so an edit never disagrees with its
    own spelling. Whether a value is *acceptable* is the tool's question.
    """
    if field == "targets":
        panel = session.settings.artwork.panel.value
        if panel is None:
            raise ValueError("output.targets: no artwork is selected, so no artefact has a place")
        names = sorted(str(name) for name in _many(answer))
        return tuple((name, discover.output_path(name, panel)) for name in names)
    if field == "boards":
        return tuple(Path(str(path)) for path in _many(answer))
    if field == "panel_reference":
        return answer.strip() if isinstance(answer, str) else ",".join(_many(answer))
    if field == "case_face":
        return CaseFace(str(answer))
    text = str(answer).strip()
    if not text and field in _OPTIONAL:
        return None
    kind = field_of(place, field).kind
    if kind is Kind.NUMBER:
        try:
            return int(text) if field == "form_depth" else float(text)
        except ValueError:
            whole = "a whole number" if field == "form_depth" else "a number"
            raise ValueError(f"{place.value}.{field}: {text!r} is not {whole}") from None
    if kind is Kind.PATH:
        return Path(text) if text else None
    return text


def _many(answer: object) -> tuple[str, ...]:
    """A multiple picker's ticks, as strings in the order they arrived."""
    return tuple(str(item) for item in answer) if isinstance(answer, (tuple, list)) else ()


def _is_text(widget: object) -> bool:
    """Whether this widget is an open text field, which is what suppresses letters."""
    return isinstance(widget, (Input, TextArea))


class KeysScreen(ModalScreen[None]):
    """What `?` shows: the same table the bindings were built from.

    A modal screen hides the application's bindings, so this one carries
    the same table as well as its own two closes: decision 3 needs every
    bare letter to work while the help is open, exactly as it does over a
    picker. Its own `escape` and `?` are listed first, so both close it.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "close", show=False),
        Binding("question_mark", "dismiss", "close", show=False),
        *table_bindings("app."),
    ]

    def compose(self) -> ComposeResult:
        yield Static(_key_list(), id="key-list")


class ConfirmScreen(ModalScreen[bool]):
    """A yes or no over the app: `enter` leaves, `esc` stays.

    No bare letter is claimed, because every one of them belongs to a place
    and a question is not a place. `Ctrl+C` is bound with priority and so
    still stops the run from here.
    """

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 52; height: auto; border: round $accent;
        background: $surface; padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "leave", "quit", show=False),
        Binding("escape", "stay", "stay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static("A run is working. Quit anyway?", markup=False)
            yield Static("enter — stop it and quit     esc — stay", markup=False)

    def action_leave(self) -> None:
        self.dismiss(True)

    def action_stay(self) -> None:
        self.dismiss(False)


def _key_list() -> str:
    """Every key and what it does, read from the tables rather than restated."""
    lines = ["Places"]
    lines += [f"  {key}   {place.value.capitalize()}" for key, place in PLACE_KEYS.items()]
    lines += ["", "Anywhere"]
    lines += [
        f"  {key.replace('question_mark', '?')}   {verb}" for key, verb in GLOBAL_VERBS.items()
    ]
    lines += [f"  {key}   {detail}" for key, (_action, detail) in RUN_KEYS.items()]
    lines += [f"  {STEP_KEYS[0]}   previous place", f"  {STEP_KEYS[1]}   next place"]
    lines += ["", "In a place"]
    lines += [
        f"  {key}   {detail} ({owner.value.capitalize()})"
        for key, (owner, detail) in LOCAL_KEYS.items()
    ]
    return "\n".join(lines)
