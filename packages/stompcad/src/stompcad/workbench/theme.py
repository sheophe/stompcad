"""The two shades that say which pane the arrows are answering.

Spec decision 4 gives the sidebar a selection and decision 3 gives a place
one; both mark where the user is, so marking them two ways would read as
two kinds of mark rather than one mark in two panes. Stated once and handed
to the stylesheet by the application, so no widget names a colour of its own.
"""

from __future__ import annotations

__all__ = ["FOCUSED", "IDLE", "shades"]

#: How much of the accent each state takes. The pane answering the arrows is
#: the loud one; the other is still marked -- leaving a place must not lose
#: where the user was -- but plainly not the one listening.
FOCUSED = 60
IDLE = 20


def shades(accent: str) -> dict[str, str]:
    """The two selection colours, as proportions of the theme's own accent.

    Taken from the theme rather than written as hex, so both follow a change
    of theme. Resolved here rather than left as ``$accent 60%`` for the
    stylesheet: a variable is substituted once, so one holding another
    variable reaches the parser with the inner name still in it.
    """
    return {
        "selection-focused": f"{accent} {FOCUSED}%",
        "selection-idle": f"{accent} {IDLE}%",
    }
