"""The sidebar: three independent states per row, and one message out.

Spec decision 4. Where the user is, how far the project has got and whether
this place needs the user are three channels: a background, a marker on the
left, a marker on the right. The characters are this implementation's
choice -- the specification leaves them open -- but the separation is not.

The sidebar is one of two panes. `←` from a place focuses it, `↑`/`↓` step
between places, and `→` or `enter` goes back in. A step, a click and a
bare letter all resolve to one place change, so no route disagrees.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Rule, Static

from .keys import CONFIGURATION, SIDEBAR_KEYS, SIDEBAR_ORDER, Place
from .session import Row

__all__ = ["Sidebar", "SidebarRow"]

#: The left marker: this place's work is done and still stands.
REACHED = "✓"
#: The right marker: this place holds something the run cannot proceed past.
ATTENTION = "!"


class SidebarRow(Static):
    """One place. Clicking it is the same change its letter makes."""

    def __init__(self, place: Place) -> None:
        super().__init__(id=f"row-{place.value}")
        self.place = place
        self.can_focus = False

    def on_click(self) -> None:
        self.post_message(Sidebar.Chosen(self.place))

    def show(self, row: Row) -> None:
        """Draw this row's three states, each in its own channel."""
        left = REACHED if row.reached else " "
        right = str(row.count) if row.count else (ATTENTION if row.attention else " ")
        self.update(f" {left} {row.label:<10}{right}")
        self.set_class(row.selected, "-selected")


class Sidebar(Vertical):
    """The eight rows, grouped: the landing, configuration, then the outcome."""

    DEFAULT_CSS = """
    Sidebar { width: 18; border-right: solid $panel; }
    Sidebar SidebarRow.-selected { background: $accent 20%; }
    Sidebar:focus SidebarRow.-selected { background: $accent 60%; }
    """

    can_focus = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(key, f"app.{action}", detail, show=False)
        for key, (action, detail) in SIDEBAR_KEYS.items()
    ]

    class Chosen(Message):
        """A row was clicked. The app decides what that means."""

        def __init__(self, place: Place) -> None:
            self.place = place
            super().__init__()

    def compose(self) -> ComposeResult:
        for place in SIDEBAR_ORDER:
            if place is CONFIGURATION[0] or (place is Place.RUN):
                yield Rule(line_style="ascii")
            yield SidebarRow(place)

    def show(self, rows: tuple[Row, ...]) -> None:
        for row in rows:
            self.query_one(f"#row-{row.place.value}", SidebarRow).show(row)
