"""One pane per place: its rows, what `enter` opens on each, and the picker.

Spec decision 2 names the places for subjects, and decision 7 has every row
state its value and origin; both come straight from ``Settings.<place>.rows()``,
so a pane composes strings rather than deciding anything. Decision 3 makes
every list a picker rather than a field, so a row is typed only where the
tool that owns it offers nothing to choose from: the numbers, the paths, the
drawing title and the two size lists -- and the designators, which are a tick
list once a run has read a board and an expression until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from textual import events
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
from ..settings import Origin, as_flag_string
from .keys import (
    CONFIGURATION,
    GLOBAL_VERBS,
    LOCAL_KEYS,
    PLACE_KEYS,
    PRIORITY_KEYS,
    RUN_KEYS,
    STEP_KEYS,
    Place,
)
from .session import PendingGap, Session

__all__ = [
    "Kind",
    "Field",
    "FIELDS",
    "field_of",
    "choices_for",
    "chosen_for",
    "table_bindings",
    "RunView",
    "NO_RUN",
    "position_line",
    "finding_lines",
    "output_lines",
    "pane_for",
    "Rows",
    "FocusRow",
    "ValueRow",
    "RunRow",
    "GapRow",
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
    if field == "panel":
        # Decision 6: several artwork files offer a pick rather than a
        # refusal, and the row that states which one is open is the row that
        # offers them. With none found there is nothing to offer and the
        # path is typed instead.
        return tuple(str(path) for path in session.panel_candidates)
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

    One builder serves the application, the picker and the keys screen, so a
    list open over a place answers exactly the letters the place does, and no
    key is added to one alone. Only ``PRIORITY_KEYS`` is heard over what is
    focused: a bare letter must lose to an open text field, and a stop must
    not lose to a modal.
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
        *(
            Binding(
                key,
                f"{namespace}{action}",
                detail,
                show=False,
                priority=key in PRIORITY_KEYS,
            )
            for key, (action, detail) in RUN_KEYS.items()
        ),
    ]


@dataclass(frozen=True, slots=True)
class RunView:
    """What the `Run` place draws: the whole step list, the reports, the position.

    ``steps`` is every step of the plan, finished or not, so the place holds
    the list live rather than only what is done (decision 2). ``reports`` is
    what a write step said, kept apart because the step lines are built from
    the plan and would otherwise be drawn twice.
    """

    steps: tuple[str, ...] = ()
    reports: tuple[str, ...] = ()
    position: float = 0.0
    branch: str = ""


#: No run has reported anything yet. One instance, because it holds nothing.
NO_RUN = RunView()


def position_line(position: float, branch: str) -> str:
    """The one live line: how far the run has got, and what it is inside."""
    return f"  {position:.0%}  {branch}"


def finding_lines(session: Session) -> tuple[str, ...]:
    """What the `Findings` place lists, in the order the run raised them.

    Plan 3 replaces this body with the six families, their shared prose and
    the jump to the row that addresses each finding. It is a function rather
    than a widget so that replacement changes what is said and not where it
    is said.
    """
    if not session.findings:
        return ("Nothing to report.",)
    return tuple(
        f"{finding.diagnostic.severity.value:<8}{finding.diagnostic.code:<28}"
        f"{finding.diagnostic.message}"
        for finding in session.findings
    )


def output_lines(session: Session) -> tuple[str, ...]:
    """Each artefact, where it goes, and what is honestly known about it.

    Decision 2: a file found on disk is labelled as found, never as current.
    The manifest holds no hashes, so this is the strongest true statement
    available -- and it is the session's, never persisted.
    """
    targets = session.settings.output.targets
    if not targets.value:
        # Decision 17: an empty set somebody answered is a run permitted to
        # write nothing, which is a legitimate thing to want and so must be
        # said -- a run that quietly writes nothing is indistinguishable
        # from one that failed to. At rank four it is an unanswered
        # question instead, which the editable row above already states.
        answered = targets.provenance.origin is not Origin.DEFAULT
        return ("check only — writes nothing",) if answered else ()
    return tuple(
        f"{name:<14}{path}  — {session.label_for(path, exists=path.is_file())}"
        for name, path in targets.value
    )


def pane_for(session: Session, place: Place, run: RunView = NO_RUN) -> Widget:
    """The widget this place draws into the body."""
    pane = Rows(id=f"pane-{place.value}")
    pane.border_title = place.value.capitalize()
    if place is Place.PROJECT:
        pane.compose_add_child(Static(session.statement(), markup=False))
        if session.notes:
            # Decisions 6 and 9: a declaration discovery contradicts is news,
            # and so is a key this build does not know. Neither re-picks
            # anything, so saying them where the project is read is the whole
            # of what "reported" can mean inside an application.
            pane.compose_add_child(
                Static("\n".join(session.notes), id="project-notes", markup=False)
            )
        pane.compose_add_child(RunRow())
    elif place is Place.RUN:
        pane.compose_add_child(
            Static(position_line(run.position, run.branch), id="run-position", markup=False)
        )
        pane.compose_add_child(
            Static("\n".join((*run.steps, *run.reports)), id="run-lines", markup=False)
        )
    elif place in CONFIGURATION:
        record = getattr(session.settings, place.value)
        for field, label, stated in record.rows():
            pane.compose_add_child(ValueRow(place, field, f"{label:<18}{stated}"))
        if place is Place.OUTPUT:
            # Beside the row that chooses them, never in place of it: what an
            # artefact is called is editable, what is known about it is not.
            pane.compose_add_child(Static("\n".join(output_lines(session)), markup=False))
        gap = session.gap
        if gap is not None and gap.place is place:
            pane.compose_add_child(GapRow(gap))
    else:
        pane.compose_add_child(Static("\n".join(finding_lines(session)), markup=False))
    return pane


class Rows(VerticalScroll):
    """A place's rows. `↑`/`↓` move between neighbours; `←` leaves for the list.

    Not itself focusable: one row holds focus, so there is no pane to tab
    into before reaching a value.
    """

    can_focus = False

    BINDINGS = [
        Binding("up", "app.focus_previous", "previous row", show=False),
        Binding("down", "app.focus_next", "next row", show=False),
    ]


class FocusRow(Static):
    """One line a place can put focus on, whether it carries a value or a verb.

    Arrows move between these and nothing else, so a pane's focusable lines
    are one set rather than one set per kind of row.
    """

    can_focus = True

    #: Which value this row carries, or empty where it carries none.
    field: str = ""

    DEFAULT_CSS = """
    FocusRow:focus { background: $accent 30%; }
    """


class ValueRow(FocusRow):
    """One value: its name, what it states, and `enter` to change it."""

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


class RunRow(FocusRow):
    """`Project`'s own way into a run: decision 3's second route, and no letter.

    Two keys start a run, and this is the other pair. `enter` here means
    what `enter` means on every other row -- commit what this line is for.
    """

    BINDINGS = [Binding("enter", "app.start_run", "run", show=False)]

    def __init__(self) -> None:
        super().__init__("Run this project", id="run-row", markup=False)


class GapRow(FocusRow):
    """What the paused run waits for, and `enter` to answer it. Decision 12.

    A picker is transient, so abandoning one must be recoverable rather than
    the end of the run; and a gap answered by a free edit has no picker at
    all. One row serves both: the way back into the list, and the named
    continuation that edit would otherwise lack.
    """

    BINDINGS = [Binding("enter", "app.answer_gap", "answer", show=False)]

    def __init__(self, gap: PendingGap) -> None:
        choice = gap.choice
        label = "Continue run" if choice is None else f"Answer and continue: {choice.prompt}"
        super().__init__(label, id="continue-run" if choice is None else "gap-row", markup=False)


class Editor(Input):
    """The one open text field: while it has focus, letters type rather than jump."""

    BINDINGS = [Binding("escape", "close", "close", show=False)]

    def __init__(self, row: ValueRow) -> None:
        super().__init__(id="editor")
        self.row = row

    async def on_key(self, event: events.Key) -> None:
        """Decision 3: an open field suppresses a place's chords, not just its letters.

        Textual consumes a printable key here already, so a bare letter
        never reaches a binding; a ``Ctrl``+letter would, and ``Ctrl+R``
        mid-edit commits minutes of kernel work nobody asked for.
        """
        if _claimed(event.key):
            event.stop()
            event.prevent_default()

    def action_close(self) -> None:
        """Abandon the text, and hand focus back to the row that opened it."""
        self.row.focus()
        self.remove()


def _claimed(key: str) -> bool:
    """Whether a place owns this chord, which is what a field must not leak.

    By the table rather than by spelling: suppressing every ``Ctrl``+letter
    took Textual's own editing chords from the one field this application
    has. ``ctrl+c`` is absent because it is a priority binding, answered
    before the focused widget ever sees it.
    """
    return key in LOCAL_KEYS


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
        """Highlight the current answer, or the first, so `enter` always commits one."""
        if self.multiple:
            return
        picker = self.query_one("#picker", OptionList)
        if self.chosen and self.chosen[0] in self.choices:
            picker.highlighted = self.choices.index(self.chosen[0])
        elif self.choices:
            picker.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.multiple:
            self.dismiss(self.choices[event.option_index])

    def action_commit(self) -> None:
        """Every tick, nothing ticked included: that is decision 17's *none*."""
        self.dismiss(tuple(self.query_one("#picker", Ticks).selected))
