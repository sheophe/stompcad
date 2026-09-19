"""The footer: which mode is in force, and what the keys do in it.

Spec decision 3. The model's one hazard is not knowing whether a letter
jumps or types, so the mode is named first and in a cell of its own, and
the keys that matter in it follow. Held as data rather than as a sentence,
because two modes written as two sentences drift into two layouts, and a
key that changes should change in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Static

__all__ = ["Hint", "Mode", "MOVING", "TYPING", "ModeLine"]

#: What divides two cells. A drawn bar for the reason the sidebar's group
#: separator is a drawn line: it divides without reading as something typed.
DIVIDER = " │ "

#: What joins keys to what they do, in the one spelling every cell uses.
BINDS = " — "


@dataclass(frozen=True, slots=True)
class Hint:
    """One cell: the keys, and what they do while this mode is in force."""

    keys: str
    detail: str

    def describe(self) -> str:
        """``q — quit``: the keys, then what pressing them does."""
        return f"{self.keys}{BINDS}{self.detail}"


@dataclass(frozen=True, slots=True)
class Mode:
    """A mode's name and its keys, in the order the footer states them."""

    name: str
    hints: tuple[Hint, ...]

    def describe(self, message: str = "") -> str:
        """The whole line: the mode, its keys, and anything the app is saying.

        The message takes a cell like any other rather than a corner of its
        own, so one divider divides everything and a long message pushes
        nothing off the end that a builder still needs.
        """
        cells = [self.name.upper(), *(hint.describe() for hint in self.hints)]
        if message:
            cells.append(message)
        return f" {DIVIDER.join(cells)} "


#: Letters jump. The arrows lead because they are what a newcomer tries
#: first, and the two keys that leave -- to help, or to the shell -- close
#: the line, because an application that states no way out is a trap.
MOVING = Mode(
    "moving",
    (
        Hint("← ↑ → ↓ and letters", "navigation"),
        Hint("?", "help"),
        Hint("q", "quit"),
    ),
)

#: Letters type. ``q`` is absent because here it types a ``q``: a footer
#: offering the exit where that key does something else would be a hint
#: that lies exactly where somebody is most likely to try it.
TYPING = Mode(
    "typing",
    (
        Hint("letters", "type here"),
        Hint("esc", "leave the field"),
    ),
)


class ModeLine(Static):
    """The one footer, docked at the bottom and redrawn as either half changes."""

    DEFAULT_CSS = """
    ModeLine { dock: bottom; height: 1; background: $panel; }
    """

    def show(self, mode: Mode, message: str = "") -> None:
        """State the mode in force, and whatever the application is saying."""
        self.update(mode.describe(message))
