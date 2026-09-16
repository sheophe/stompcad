"""One pane per place: its rows, what `enter` opens on each, and the picker.

Spec decision 2 names the places for subjects, and decision 7 has every row
state its value and origin; both come straight from ``Settings.<place>.rows()``,
so a pane composes strings rather than deciding anything. Decision 3 makes
every list a picker rather than a field, which confines text entry to
numbers, paths and the designator expression.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, OptionList, SelectionList, Static

from stompdrill.emitters import available
from stompdrill.pipeline import DRILL_STANDARDS
from stompmodel.model import CaseFace

from .. import discover
from ..drive import DOCK_TARGET_NAMES
from ..settings import as_flag_string
from .keys import CONFIGURATION, GLOBAL_VERBS, LOCAL_KEYS, PLACE_KEYS, STEP_KEYS, Place
from .session import Session

__all__ = [
    "Kind",
    "Field",
    "FIELDS",
    "field_of",
    "choices_for",
    "chosen_for",
    "table_bindings",
    "pane_for",
    "Rows",
    "ValueRow",
    "Editor",
    "Ticks",
    "PickerScreen",
]


class Kind(Enum):
    """What ``enter`` opens on this row. Decision 3: lists wherever possible."""

    TEXT = "text"
    NUMBER = "number"
    PATH = "path"
    CHOICE = "choice"
    MANY = "many"


@dataclass(frozen=True, slots=True)
class Field:
    """One editable row: the attribute it carries and what opens on it."""

    name: str
    kind: Kind


#: Every place's rows. Joined to ``Settings.<place>.rows()`` by name, and a
#: test holds the two to the same set: a field added to one and not the other
#: is either a row nobody can edit or an editor for nothing.
FIELDS: dict[Place, tuple[Field, ...]] = {
    Place.ARTWORK: (
        Field("panel", Kind.PATH),
        Field("drill_layer", Kind.CHOICE),
        Field("reference_layer", Kind.CHOICE),
        Field("form_depth", Kind.NUMBER),
    ),
    Place.ENCLOSURE: (
        Field("case", Kind.CHOICE),
        Field("case_model", Kind.PATH),
        Field("case_face", Kind.CHOICE),
        Field("case_margin_mm", Kind.NUMBER),
    ),
    Place.DRILLING: (
        Field("grid_mm", Kind.NUMBER),
        Field("grid_warn_mm", Kind.NUMBER),
        Field("drill_standard", Kind.CHOICE),
        Field("drill_sizes", Kind.TEXT),
        Field("no_drill_sizes", Kind.TEXT),
        Field("title", Kind.TEXT),
    ),
    Place.BOARDS: (
        Field("boards", Kind.MANY),
        Field("panel_reference", Kind.MANY),
        Field("match_tolerance_mm", Kind.NUMBER),
        Field("seat_pitch_max_mm", Kind.NUMBER),
        Field("seat_pitch_min_mm", Kind.NUMBER),
    ),
    Place.OUTPUT: (Field("targets", Kind.MANY),),
}


def field_of(place: Place, name: str) -> Field:
    """This place's row for one field, from the one table stating them."""
    return next(field for field in FIELDS[place] if field.name == name)


def choices_for(session: Session, place: Place, field: str) -> tuple[str, ...]:
    """The answers this row's picker offers, from whoever owns the question."""
    panel = session.settings.artwork.panel.value
    if field in ("drill_layer", "reference_layer"):
        return () if panel is None else discover.layers(panel)
    if field == "case":
        return discover.catalogue_parts()
    if field == "case_face":
        return tuple(face.value for face in CaseFace)
    if field == "drill_standard":
        return tuple(sorted(DRILL_STANDARDS))
    if field == "boards":
        return () if panel is None else tuple(
            str(path) for path in discover.board_candidates(
                panel.parent, panel, session.settings.enclosure.case_model.value
            )
        )
    if field == "panel_reference":
        return session.designators
    if field == "targets":
        return tuple(sorted(frozenset(available()) | DOCK_TARGET_NAMES))
    return ()


def chosen_for(session: Session, place: Place, field: str) -> tuple[str, ...]:
    """The current value as the picker's own answers, so opening one loses nothing."""
    value = getattr(getattr(session.settings, place.value), field).value
    if field == "targets":
        return tuple(name for name, _path in value)
    if field == "boards":
        return tuple(str(path) for path in value)
    if field == "panel_reference":
        return tuple(term.strip() for term in str(value).split(",") if term.strip())
    return () if value is None else (str(as_flag_string(value)),)


def table_bindings(namespace: str = "") -> list[BindingType]:
    """Every key the tables hold, bound to the application's own actions.

    One builder serves the application and the picker, so a list open over
    a place answers exactly the letters the place does, and no key is added
    to one alone. None of them is a priority binding: an open text field
    consumes a printable key, and nothing here asks to be heard over it.
    """
    return [
        *(
            Binding(key, f"{namespace}go('{place.value}')", place.value.capitalize(), show=False)
            for key, place in PLACE_KEYS.items()
        ),
        *(
            Binding(key, f"{namespace}verb('{verb}')", verb, show=False)
            for key, verb in GLOBAL_VERBS.items()
        ),
        Binding(STEP_KEYS[0], f"{namespace}step_place(False)", "previous", show=False),
        Binding(STEP_KEYS[1], f"{namespace}step_place(True)", "next", show=False),
        *(
            Binding(key, f"{namespace}local('{key}')", detail, show=False)
            for key, (_owner, detail) in LOCAL_KEYS.items()
        ),
    ]


def pane_for(session: Session, place: Place) -> Widget:
    """The widget this place draws into the body."""
    pane = Rows(id=f"pane-{place.value}")
    pane.border_title = place.value.capitalize()
    if place is Place.PROJECT:
        pane.compose_add_child(Static(session.statement()))
    elif place in CONFIGURATION:
        record = getattr(session.settings, place.value)
        for field, label, stated in record.rows():
            pane.compose_add_child(ValueRow(place, field, f"{label:<18}{stated}"))
    else:
        pane.compose_add_child(Static(""))
    return pane


class Rows(VerticalScroll):
    """A place's rows. Arrows move between neighbours, as they do everywhere.

    Not itself focusable: one row holds focus, so there is no pane to tab
    into before reaching a value.
    """

    can_focus = False

    BINDINGS = [
        Binding("up", "app.focus_previous", "previous row", show=False),
        Binding("down", "app.focus_next", "next row", show=False),
    ]


class ValueRow(Static):
    """One value: its name, what it states, and `enter` to change it."""

    can_focus = True

    DEFAULT_CSS = """
    ValueRow:focus { background: $accent 30%; }
    """

    BINDINGS = [Binding("enter", "edit", "change", show=False)]

    class Edit(Message):
        """`enter` on a row. The application decides what opens on it."""

        def __init__(self, row: ValueRow) -> None:
            self.row = row
            self.place = row.place
            self.field = row.field
            super().__init__()

    def __init__(self, place: Place, field: str, text: str) -> None:
        super().__init__(text, id=f"value-{field}", markup=False)
        self.place = place
        self.field = field

    def action_edit(self) -> None:
        self.post_message(ValueRow.Edit(self))


class Editor(Input):
    """The one open text field: while it has focus, letters type rather than jump."""

    BINDINGS = [Binding("escape", "close", "close", show=False)]

    def __init__(self, row: ValueRow) -> None:
        super().__init__(id="editor")
        self.row = row

    def action_close(self) -> None:
        """Abandon the text, and hand focus back to the row that opened it."""
        self.row.focus()
        self.remove()


class Ticks(SelectionList[str]):
    """A multiple picker. `space` ticks; `enter` is the commit, as in a single one."""

    BINDINGS = [Binding("enter", "screen.commit", "use these", show=False)]


class PickerScreen(ModalScreen[object]):
    """A list over the place, dismissed with a string for one or a tuple for many.

    A modal screen hides the application's bindings, so this one carries
    the same table plus `escape`: decision 3 needs every bare letter to work
    while a list is open. Moving place closes it without committing,
    because a picker is a transient widget rather than a place's state.
    """

    DEFAULT_CSS = """
    PickerScreen { align: center middle; }
    PickerScreen > Vertical {
        width: 60; height: auto; max-height: 80%;
        border: round $accent; background: $surface; padding: 0 1;
    }
    PickerScreen #picker { height: auto; max-height: 20; }
    """

    BINDINGS = [Binding("escape", "dismiss", "close", show=False), *table_bindings("app.")]

    def __init__(
        self,
        field: Field | None,
        choices: tuple[str, ...],
        multiple: bool = False,
        label: str = "",
        chosen: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.field = field
        self.choices = choices
        self.multiple = multiple
        self.label = label or ("" if field is None else field.name.replace("_", " "))
        self.chosen = chosen

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.label, id="picker-label", markup=False)
            if self.multiple:
                yield Ticks(
                    *((choice, choice, choice in self.chosen) for choice in self.choices),
                    id="picker",
                )
            else:
                yield OptionList(*self.choices, id="picker")

    def on_mount(self) -> None:
        if not self.multiple and self.chosen and self.chosen[0] in self.choices:
            self.query_one("#picker", OptionList).highlighted = self.choices.index(self.chosen[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.multiple:
            self.dismiss(self.choices[event.option_index])

    def action_commit(self) -> None:
        """Every tick, nothing ticked included: that is decision 17's *none*."""
        self.dismiss(tuple(self.query_one("#picker", Ticks).selected))
