"""The workbench: eight places on one screen, and the keys that move them.

Spec decisions 1, 3 and 4. Every rule lives in ``Session``; this is drawing
and dispatch. Bindings are built from ``keys``, so the table proved distinct
is the table the application answers.

No bare letter is a priority binding. That is how an open text field
suppresses them: a focused ``Input`` consumes a printable key before it
reaches an application binding, and a priority binding would take it back.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Static

from .keys import GLOBAL_VERBS, LOCAL_KEYS, PLACE_KEYS, STEP_KEYS, Place
from .places import pane_for
from .session import Session
from .sidebar import Sidebar

__all__ = ["Workbench", "KeysScreen"]


class Workbench(App[int]):
    """The project open, full screen. ``run`` hands back the exit code it earned."""

    CSS = """
    #body { width: 1fr; padding: 0 1; }
    #mode { dock: bottom; height: 1; background: $panel; }
    """

    BINDINGS = [
        *(
            Binding(key, f"go('{place.value}')", place.value.capitalize(), show=False)
            for key, place in PLACE_KEYS.items()
        ),
        *(
            Binding(key, f"verb('{verb}')", verb, show=False)
            for key, verb in GLOBAL_VERBS.items()
        ),
        Binding(STEP_KEYS[0], "step_place(False)", "previous", show=False),
        Binding(STEP_KEYS[1], "step_place(True)", "next", show=False),
        *(
            Binding(key, f"local('{key}')", detail, show=False)
            for key, (_owner, detail) in LOCAL_KEYS.items()
        ),
    ]

    message: reactive[str] = reactive("")

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Sidebar()
            yield Vertical(id="body")
        yield Static(id="mode")

    async def on_mount(self) -> None:
        await self.redraw()

    # -- drawing -----------------------------------------------------------

    def mode(self) -> str:
        """Which mode the footer states. Decision 3's one hazard, closed."""
        focused = self.focused
        typing = focused is not None and focused.can_focus and _is_text(focused)
        return "typing" if typing else "moving"

    async def redraw(self) -> None:
        """Draw the sidebar, the current place and the mode line.

        The old pane's removal is awaited before the new one mounts: both
        carry the same id when the place has not changed.
        """
        self.query_one(Sidebar).show(self.session.rows())
        body = self.query_one("#body", Vertical)
        await body.remove_children()
        await body.mount(pane_for(self.session, self.session.place))
        self.query_one("#mode", Static).update(self._mode_line())

    def _mode_line(self) -> str:
        if self.mode() == "typing":
            return "  typing — letters type here; esc leaves the field" + self._tail()
        return "  moving — letters jump to a place; ? for the keys" + self._tail()

    def _tail(self) -> str:
        return f"    {self.message}" if self.message else ""

    def watch_message(self) -> None:
        if self.is_running:
            self.query_one("#mode", Static).update(self._mode_line())

    def sidebar_text(self) -> str:
        """Every sidebar row as one string. For tests, and for nothing else."""
        return "\n".join(
            str(row.content) for row in self.query_one(Sidebar).query(Static)
        )

    # -- moving ------------------------------------------------------------

    async def action_go(self, place: str) -> None:
        self.session.go(Place(place))
        self.message = ""
        await self.redraw()

    async def action_step_place(self, forward: bool) -> None:
        self.session.step_place(forward)
        self.message = ""
        await self.redraw()

    async def on_sidebar_chosen(self, event: Sidebar.Chosen) -> None:
        await self.action_go(event.place.value)

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


def _is_text(widget: object) -> bool:
    """Whether this widget is an open text field, which is what suppresses letters."""
    return type(widget).__name__ in ("Input", "TextArea")


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
    lines += [f"  {STEP_KEYS[0]} {STEP_KEYS[1]}  previous and next place"]
    lines += ["", "In a place"]
    lines += [
        f"  {key}   {detail} ({owner.value.capitalize()})"
        for key, (owner, detail) in LOCAL_KEYS.items()
    ]
    return "\n".join(lines)
