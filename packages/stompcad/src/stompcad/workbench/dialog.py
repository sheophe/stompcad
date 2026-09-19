"""The frame every modal takes: one border, with its name written in it.

Decision 3's modals are windows over the workbench rather than screens to
learn, so each says what it is where a window says it. Taking the title at
construction is what keeps that true -- no modal can be composed without
naming itself -- and it buys back the line each one spent on a label
restating the name of the row it opened on.
"""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical

__all__ = ["Dialog"]


class Dialog(Vertical):
    """A bordered box titled in its border. Every modal is framed by one."""

    DEFAULT_CSS = """
    Dialog { border: round $accent; background: $surface; }
    """

    def __init__(self, title: str, **arguments: Any) -> None:
        super().__init__(**arguments)
        self.border_title = title
