"""The workbench: eight places on one screen, and the keys that move them.

Spec decisions 1, 3 and 4. Every rule lives in ``Session``; this is drawing
and dispatch. Bindings are built from ``keys``, so the table proved distinct
is the table the application answers.

No bare letter is a priority binding: an open text field consumes a
printable key before any binding is checked, and nothing here is heard over it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Input, Static, TextArea

from stompmodel.errors import StompError
from stompmodel.model import CaseFace

from .. import discover
from .keys import GLOBAL_VERBS, LOCAL_KEYS, PLACE_KEYS, STEP_KEYS, Place
from .places import (
    Editor,
    Field,
    Kind,
    PickerScreen,
    ValueRow,
    choices_for,
    chosen_for,
    field_of,
    pane_for,
    table_bindings,
)
from .session import Locked, Refused, Session
from .sidebar import Sidebar

__all__ = ["Workbench", "KeysScreen"]


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

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._base: Screen[Any] | None = None

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
        """
        base = self._base if self._base is not None else self.screen
        base.query_one(Sidebar).show(self.session.rows())
        body = base.query_one("#body", Vertical)
        await body.remove_children()
        await body.mount(pane_for(self.session, self.session.place))
        rows = list(body.query(ValueRow))
        target = next((row for row in rows if row.field == field), rows[0] if rows else None)
        if target is not None:
            target.focus()
        self._show_mode()

    def _show_mode(self) -> None:
        if self._base is not None:
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
        self._abandon_picker()
        self.session.go(Place(place))
        self.message = ""
        await self.redraw()

    async def action_step_place(self, forward: bool) -> None:
        self._abandon_picker()
        self.session.step_place(forward)
        self.message = ""
        await self.redraw()

    def _abandon_picker(self) -> None:
        """Decision 12: a picker is transient, so leaving closes it uncommitted."""
        if isinstance(self.screen, PickerScreen):
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

    # -- the verbs ---------------------------------------------------------

    def action_verb(self, verb: str) -> None:
        if verb == "window":
            self.action_window()
        elif verb == "keys":
            self.action_keys()
        else:
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
    """What `?` shows: the same table the bindings were built from."""

    BINDINGS = [("escape", "dismiss", "close"), ("question_mark", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        yield Static(_key_list(), id="key-list")


def _key_list() -> str:
    """Every key and what it does, read from the tables rather than restated."""
    lines = ["Places"]
    lines += [f"  {key}   {place.value.capitalize()}" for key, place in PLACE_KEYS.items()]
    lines += ["", "Anywhere"]
    lines += [
        f"  {key.replace('question_mark', '?')}   {verb}" for key, verb in GLOBAL_VERBS.items()
    ]
    lines += [f"  {STEP_KEYS[0]}   previous place", f"  {STEP_KEYS[1]}   next place"]
    lines += ["", "In a place"]
    lines += [
        f"  {key}   {detail} ({owner.value.capitalize()})"
        for key, (owner, detail) in LOCAL_KEYS.items()
    ]
    return "\n".join(lines)
