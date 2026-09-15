"""One pane per place: what it holds, and where each value came from.

Spec decision 2 names the places for subjects rather than for settings, and
decision 7 requires every row to state its value and its origin in a
vocabulary a builder can act on. Both come straight from
``Settings.places()``, which already renders exactly that sentence -- so a
pane composes strings rather than deciding anything.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from .keys import Place
from .session import Session

__all__ = ["pane_for"]


def pane_for(session: Session, place: Place) -> Widget:
    """The widget this place draws into the body."""
    pane = VerticalScroll(id=f"pane-{place.value}")
    pane.border_title = place.value.capitalize()
    for line in _lines(session, place):
        pane.compose_add_child(Static(line))
    return pane


def _lines(session: Session, place: Place) -> tuple[str, ...]:
    """Every line this place states, in the order the place lists them."""
    if place is Place.PROJECT:
        return (session.statement(),)
    if place in (Place.RUN, Place.FINDINGS):
        return ("",)
    record = getattr(session.settings, place.value)
    return tuple(f"{name:<18}{stated}" for name, stated in record.rows())
