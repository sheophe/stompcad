"""The application through Textual's own pilot: keys, places, markers."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from rich.cells import cell_len
from textual.binding import Binding, BindingsMap
from textual.command import CommandPalette
from textual.pilot import Pilot
from textual.widgets import Input, Rule, SelectionList, Static

from stompcad import cli, manifest
from stompcad.cli import Resolution
from stompcad.readiness import readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.app import Workbench, _key_list
from stompcad.workbench.keys import (
    GLOBAL_VERBS,
    LOCAL_KEYS,
    PLACE_KEYS,
    RUN_KEYS,
    SIDEBAR_KEYS,
    STEP_KEYS,
    TO_SIDEBAR,
    Place,
)
from stompcad.workbench.places import FIELDS, PickerScreen, ValueRow
from stompcad.workbench.session import Session
from stompcad.workbench.sidebar import Sidebar, SidebarRow
from stompmodel.diagnostics import Diagnostic, Severity
from tests.conftest import TAR_AI

__all__: list[str] = []

_PANEL = Path("/project/tar.ai")


def _session(
    settings: Settings | None = None, project: manifest.Manifest | None = None
) -> Session:
    """A session whose edits are checked by the real consuming tool, as a run's are."""
    resolved = settings if settings is not None else _runnable()
    return Session(
        Resolution(
            settings=resolved,
            notes=(),
            blockers=readiness(resolved),
            project=project if project is not None else manifest.Manifest(),
        ),
        validator=lambda settings, place: cli.validate_place(settings, place, _PANEL),
    )


def _runnable() -> Settings:
    """A project with nothing outstanding, so the sidebar is clean."""
    base = Settings.of_defaults(_PANEL)
    return replace(
        base,
        enclosure=replace(
            base.enclosure,
            case_model=Resolved(Path("/project/1590B.stp"), Provenance(Origin.PROJECT)),
        ),
        boards=replace(
            base.boards,
            boards=Resolved((Path("/project/tar-pcb.stp"),), Provenance(Origin.PROJECT)),
            panel_reference=Resolved("RV*", Provenance(Origin.PROJECT)),
        ),
        output=replace(
            base.output,
            targets=Resolved(
                (("excellon", Path("/project/tar-case.drl")),), Provenance(Origin.PROJECT)
            ),
        ),
    )


def _targets(paths: dict[str, Path]) -> Settings:
    """A runnable project whose artefacts are these, declared by the project."""
    base = _runnable()
    return replace(
        base,
        output=replace(
            base.output,
            targets=Resolved(tuple(sorted(paths.items())), Provenance(Origin.PROJECT)),
        ),
    )


def _declared_case(part: str) -> Settings:
    """A project that names its enclosure part and holds no model for it yet."""
    base = Settings.of_defaults(_PANEL)
    return replace(
        base,
        enclosure=replace(base.enclosure, case=Resolved(part, Provenance(Origin.PROJECT))),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "place"), sorted(PLACE_KEYS.items()))
async def test_every_place_letter_reaches_its_place(key: str, place: Place) -> None:
    """Decision 3: each place owns one unique bare letter, and it works everywhere."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press(key)
        assert app.session.place is place


@pytest.mark.asyncio
async def test_the_step_keys_reach_the_same_places_the_letters_do() -> None:
    """Both routes resolve to one place change; neither is a second model."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("p", "]")
        assert _place(app) is Place.ARTWORK
        await pilot.press("[", "[")
        assert _place(app) is Place.FINDINGS


def _place(app: Workbench) -> Place:
    """The selected place, read fresh: mypy would keep a narrowed property's type."""
    return app.session.place


@pytest.mark.asyncio
async def test_a_clean_project_shows_a_clean_sidebar() -> None:
    """Decision 4: the marker marks the exception, and silence is the reassurance."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "!" not in app.sidebar_text()


@pytest.mark.asyncio
async def test_a_place_that_needs_the_user_is_marked_and_the_others_are_not() -> None:
    base = _runnable()
    app = Workbench(_session(replace(base, boards=DEFAULTS.boards)))
    async with app.run_test() as pilot:
        await pilot.pause()
        lines = {line.split()[0] if line.split() else "": line for line in app.sidebar_text().splitlines()}
        assert "!" in "".join(line for name, line in lines.items() if "Boards" in line)
        assert "!" not in "".join(line for name, line in lines.items() if "Drilling" in line)


@pytest.mark.asyncio
async def test_a_group_separator_is_one_drawn_line() -> None:
    """Decision 4: the groups are divided by a rule, not by dashes and air.

    Measured as the distance between the places it divides, because that is
    what a reader sees: the widget's own margin is a blank line either side,
    and it is outside the size the rule reports for itself.
    """
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(Sidebar)
        rows = {row.place: row.region.y for row in bar.query(SidebarRow)}
        assert [rule.line_style for rule in bar.query(Rule)] == ["solid", "solid"]
        assert rows[Place.ARTWORK] - rows[Place.PROJECT] == 2
        assert rows[Place.RUN] - rows[Place.OUTPUT] == 2


def test_the_sidebar_binds_exactly_its_own_table() -> None:
    """Its arrows are proved distinct only if the table is what it binds."""
    own = {binding.key for binding in Sidebar.BINDINGS if isinstance(binding, Binding)}
    assert own == set(SIDEBAR_KEYS)


@pytest.mark.asyncio
async def test_the_workbench_opens_inside_a_place_not_the_list() -> None:
    """The list is focusable now, but the app still starts where the work is."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not isinstance(app.focused, Sidebar)
        assert app.focused is not None


@pytest.mark.asyncio
async def test_left_moves_focus_from_a_place_to_the_sidebar() -> None:
    """Decision 3: `←` leaves the place for the list, and the place stays put."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "left")
        assert isinstance(app.focused, Sidebar)
        assert app.session.place is Place.DRILLING


@pytest.mark.asyncio
async def test_left_reaches_the_sidebar_from_a_place_with_nothing_to_select() -> None:
    """Findings holds no row to focus, so `←` must not depend on one being focused."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("f", "left")
        assert isinstance(app.focused, Sidebar)


@pytest.mark.asyncio
async def test_up_and_down_in_the_sidebar_step_places_and_keep_focus_there() -> None:
    """Stepping in the list is the change a letter makes; focus stays in the list."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "left", "down")
        assert _place(app) is Place.BOARDS
        assert isinstance(app.focused, Sidebar)
        assert app.query("#pane-boards")
        await pilot.press("up", "up")
        assert _place(app) is Place.ENCLOSURE
        assert isinstance(app.focused, Sidebar)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["right", "enter"])
async def test_right_or_enter_goes_into_the_place(key: str) -> None:
    """The way back in: focus lands on the place's first row, as a letter leaves it."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "left", "down", key)
        assert isinstance(app.focused, ValueRow)
        assert app.focused.place is Place.BOARDS


@pytest.mark.asyncio
async def test_right_on_a_place_with_nothing_to_select_stays_in_the_sidebar() -> None:
    """Going in where there is nothing to hold focus must not strand it nowhere."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("f", "left", "right")
        assert isinstance(app.focused, Sidebar)


@pytest.mark.asyncio
async def test_a_letter_still_jumps_from_the_sidebar() -> None:
    """The fast route works from either pane."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "left", "o")
        assert _place(app) is Place.OUTPUT


@pytest.mark.asyncio
async def test_left_in_an_open_field_moves_the_cursor_not_the_focus() -> None:
    """The control: typing keeps its own arrows, as it keeps its letters."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter", "T", "a", "r", "left")
        editor = app.query_one("#editor", Input)
        assert app.focused is editor
        assert editor.cursor_position == 2


@pytest.mark.asyncio
async def test_a_sidebar_row_is_clickable() -> None:
    """Nobody is stuck while learning the letters."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.click(f"#row-{Place.DRILLING.value}")
        assert app.session.place is Place.DRILLING


@pytest.mark.asyncio
async def test_the_footer_always_states_the_mode() -> None:
    """The key model's one hazard, closed: you can always see whether letters jump."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.mode() == "moving"
        assert "moving" in str(app.query_one("#mode", Static).content).lower()


@pytest.mark.asyncio
async def test_the_way_out_is_on_screen_before_anybody_asks_for_it() -> None:
    """The footer names the key that leaves, so nobody has to know it already.

    A full-screen application that states no way out is one a builder has to
    look up how to leave, and looking that up is not part of making a pedal.
    """
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "q to quit" in str(app.query_one("#mode", Static).content)


@pytest.mark.asyncio
async def test_the_field_names_its_own_way_out_rather_than_the_application_s() -> None:
    """`q` types a letter here, so the footer must not offer it as the exit."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter")
        stated = str(app.query_one("#mode", Static).content)
        assert "esc leaves the field" in stated
        assert "quit" not in stated


@pytest.mark.asyncio
async def test_the_keys_screen_lists_every_key_the_table_holds() -> None:
    """`?` teaches the letters, from the same table the bindings are built from."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        lines = [
            line.strip() for line in str(app.screen.query_one("#key-list", Static).content).splitlines()
        ]
        glyphs = {"left": "←", "right": "→", "up": "↑", "down": "↓", "question_mark": "?"}
        for key in (
            *PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS, *TO_SIDEBAR, *SIDEBAR_KEYS
        ):
            shown = glyphs.get(key, key)
            assert any(line.startswith(f"{shown} ") for line in lines), shown


@pytest.mark.asyncio
async def test_the_keys_screen_is_a_window_sized_to_its_text() -> None:
    """`?` opens a centred box that fits the whole key list, with a margin.

    Measured against the text itself, not the terminal: a box collapsed to
    nothing is also smaller than the screen, so that alone proves nothing.
    """
    lines = _key_list().splitlines()
    width, height = max(cell_len(line) for line in lines), len(lines)
    app = Workbench(_session())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        text = app.screen.query_one("#key-list").region
        box = app.screen.query_one("#keys").region
        assert (text.width, text.height) == (width, height)
        # A border plus at least one blank row and two blank columns each side.
        assert text.x - box.x >= 3 and box.right - text.right >= 3
        assert text.y - box.y >= 2 and box.bottom - text.bottom >= 2
        assert box.width < app.size.width and box.height < app.size.height
        left, right = box.x, app.size.width - box.right
        top, bottom = box.y, app.size.height - box.bottom
        assert abs(left - right) <= 1 and abs(top - bottom) <= 1


#: Keys the running application answers that no table holds, each with its reason.
#: All three are Textual's ``Screen`` defaults: ``super+c`` is the other half of
#: its one ``ctrl+c,super+c`` copy binding, whose ``ctrl+c`` the run's own stop
#: now outranks, and ``tab`` belongs to the place under decision 3, as does its
#: reverse.
_EXEMPT = {
    "super+c": "the other half of the screen's one `ctrl+c,super+c` copy binding",
    "tab": "decision 3: tab belongs to the place",
    "shift+tab": "tab's reverse",
}


def _spelled(*keys: str) -> set[str]:
    """Each key as Textual spells it once bound: ``[`` is ``left_square_bracket``."""
    return set(BindingsMap(Binding(key, "noop") for key in keys).key_to_bindings)


@pytest.mark.asyncio
async def test_the_app_answers_only_the_keys_its_table_holds() -> None:
    """Decision 3: the table proved distinct is every key a press reaches.

    The app's and the default screen's maps answer whatever is focused; a
    focused widget's own keys, such as a scroll pane's arrows, are local.
    """
    tabled = _spelled(*PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS, *TO_SIDEBAR)
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.pause()
        bound = set(app._bindings.key_to_bindings) | set(app.screen._bindings.key_to_bindings)
        assert tabled <= bound
        assert bound - tabled - set(_EXEMPT) == set()


@pytest.mark.asyncio
async def test_the_keys_screen_answers_only_the_keys_its_table_holds() -> None:
    """A modal hides the app's bindings, so `?` must carry the table too."""
    tabled = _spelled(*PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS)
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        assert app.screen.query("#key-list")
        bound = set(app.screen._bindings.key_to_bindings)
        assert tabled <= bound
        assert bound - tabled - set(_EXEMPT) == set()


@pytest.mark.asyncio
async def test_a_place_letter_leaves_the_keys_screen_for_that_place() -> None:
    """The control: a table that never reached the help would strand the letters."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("question_mark", "b")
        assert not app.screen.query("#key-list")
        assert app.session.place is Place.BOARDS


@pytest.mark.asyncio
async def test_ctrl_p_opens_no_command_palette() -> None:
    """Textual's palette chord is in no table, so no place answers it."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "ctrl+p")
        assert app.session.place is Place.DRILLING
        assert not isinstance(app.screen, CommandPalette)


@pytest.mark.asyncio
async def test_a_local_key_pressed_in_another_place_is_refused_and_says_so() -> None:
    """Decision 3: `Ctrl`+letter belongs to the place, not to the application."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "ctrl+l")
        assert "Artwork" in app.message


@pytest.mark.asyncio
async def test_the_window_verb_reports_that_no_viewer_is_installed() -> None:
    """Decision 13: `available()` false means `w` explains, never fails. Plan 3 fills it."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert "viewer" in app.message.lower()


async def _focus_row(pilot: Pilot[int], app: Workbench, field: str) -> None:
    """Focus one row by name: the subject is editing, not how many arrows reach it."""
    row = next(row for row in app.query(ValueRow) if row.field == field)
    row.focus()
    await pilot.pause()


@pytest.mark.asyncio
async def test_an_open_text_field_suppresses_every_bare_letter() -> None:
    """Decision 3's one hazard, closed. The guard this whole model rests on."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter")
        await pilot.press("b", "o", "a", "r", "d")
        assert app.session.place is Place.DRILLING
        assert app.query_one("#editor", Input).value == "board"
        assert app.mode() == "typing"
        assert "typing" in str(app.query_one("#mode", Static).content).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["alt+backspace", "ctrl+backspace", "ctrl+w"])
async def test_a_word_key_takes_the_word_behind_the_cursor(key: str) -> None:
    """Every spelling a terminal sends for `Option+Backspace` removes a word.

    Which one arrives depends on the terminal: the plain escape form reaches
    Textual as ``ctrl+w``, and one speaking the extended protocol sends
    ``alt+backspace``, which Textual binds to the word *ahead* of the cursor.
    """
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter")
        editor = app.query_one("#editor", Input)
        editor.value = "one two three"
        editor.cursor_position = len(editor.value)
        await pilot.press(key)
        assert editor.value == "one two "


@pytest.mark.asyncio
async def test_backspace_alone_still_takes_one_character() -> None:
    """The control: a field that deleted a word per keystroke could not be typed in."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter")
        editor = app.query_one("#editor", Input)
        editor.value = "one two three"
        editor.cursor_position = len(editor.value)
        await pilot.press("backspace")
        assert editor.value == "one two thre"


@pytest.mark.asyncio
async def test_closing_the_field_gives_the_letters_back() -> None:
    """The control: a suppression that never lifted would be a trap, not a mode."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter", "escape")
        assert "moving" in str(app.query_one("#mode", Static).content).lower()
        await pilot.press("b")
        assert app.session.place is Place.BOARDS


@pytest.mark.asyncio
async def test_committing_a_text_row_records_the_value_and_who_set_it() -> None:
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "title")
        await pilot.press("enter")
        for character in "Tar":
            await pilot.press(character)
        await pilot.press("enter")
        assert app.session.settings.drilling.title.value == "Tar"
        assert app.session.settings.drilling.title.provenance.origin is Origin.USER


@pytest.mark.asyncio
async def test_a_choice_row_opens_a_picker_rather_than_a_field() -> None:
    """Decision 3: a list keeps the letters working, which is why most rows are lists."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "drill_standard")
        await pilot.press("enter")
        assert app.screen.query("#picker")
        assert app.mode() == "moving"


@pytest.mark.asyncio
async def test_committing_a_picker_records_the_answer_it_chose() -> None:
    """The picker's `enter` is the commit: no second action to find."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "drill_standard")
        await pilot.press("enter", "home", "enter")
        assert not app.screen.query("#picker")
        standard = app.session.settings.drilling.drill_standard
        assert standard.value == "fractional"
        assert standard.provenance.origin is Origin.USER


@pytest.mark.asyncio
async def test_leaving_a_place_abandons_an_open_picker() -> None:
    """Decision 12: a picker is a transient widget, so leaving abandons it."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "drill_standard")
        await pilot.press("enter", "b")
        assert not app.screen.query("#picker")
        assert app.session.place is Place.BOARDS
        assert app.session.settings.drilling.drill_standard.provenance.origin is Origin.DEFAULT


@pytest.mark.asyncio
async def test_a_step_key_and_a_verb_still_reach_the_app_through_a_picker() -> None:
    """Decision 3: every bare letter works everywhere, an open list included."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "drill_standard")
        await pilot.press("enter", "w")
        assert "viewer" in app.message.lower()
        await pilot.press("]")
        assert not app.screen.query("#picker")
        assert app.session.place is Place.BOARDS


@pytest.mark.asyncio
async def test_an_open_picker_answers_only_the_keys_its_table_holds() -> None:
    """The picker's own map is the app's whole table, and nothing besides it."""
    tabled = _spelled(*PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS)
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "drill_standard")
        await pilot.press("enter")
        assert app.screen.query("#picker")
        bound = set(app.screen._bindings.key_to_bindings)
        assert tabled <= bound
        assert bound - tabled - set(_EXEMPT) == set()


@pytest.mark.asyncio
async def test_a_refused_value_is_shown_rather_than_taken() -> None:
    """The consuming tool's own sentence reaches the row that carried the value."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _focus_row(pilot, app, "grid_mm")
        await pilot.press("enter")
        for character in "0.0015":  # 1500 nm: no whole-micron grid; 0 would be clamped
            await pilot.press(character)
        await pilot.press("enter")
        assert app.session.settings.drilling.grid_mm.value == 0.25
        assert "grid" in app.message.lower()


@pytest.mark.asyncio
async def test_arrows_move_between_neighbouring_rows() -> None:
    """Decision 3: navigation is identical everywhere."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("d", "down", "down")
        assert app.focused is not None
        assert getattr(app.focused, "field", None) == "drill_standard"


@pytest.mark.asyncio
async def test_a_clicked_place_is_entered_at_its_first_row() -> None:
    """Every route into a place lands in the same spot, the mouse included."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.click(f"#row-{Place.ENCLOSURE.value}")
        assert getattr(app.focused, "field", None) == "case"


@pytest.mark.asyncio
async def test_targets_commit_in_the_manifest_s_own_order() -> None:
    """A ticked set is saved as the project spells it, so it never disagrees with itself."""
    declared = (
        ("drawing-pdf", Path("/project/tar-case.pdf")),
        ("excellon", Path("/project/tar-case.drl")),
    )
    project = manifest.Manifest(values={"output": {"targets": declared}})
    app = Workbench(_session(project=project))
    async with app.run_test() as pilot:
        await pilot.press("o")
        await _focus_row(pilot, app, "targets")
        await pilot.press("enter")
        app.screen.query_one("#picker", SelectionList).select("drawing-pdf")
        await pilot.press("enter")
        targets = app.session.settings.output.targets
        assert targets.value == declared
        assert targets.project is None


@pytest.mark.asyncio
async def test_an_empty_ticked_board_list_is_the_declaration_of_none() -> None:
    """Decision 17: nothing ticked is an answer, recorded at your rank."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("b")
        await _focus_row(pilot, app, "boards")
        await pilot.press("enter")
        picker = app.screen.query_one("#picker", SelectionList)
        picker.deselect_all()
        await pilot.press("enter")
        boards = app.session.settings.boards.boards
        assert boards.value == ()
        assert boards.provenance.origin is Origin.USER


@pytest.mark.asyncio
async def test_panel_references_are_typed_until_a_run_has_read_designators() -> None:
    """Decision 6: the designators arrive with the boards, so the list comes later."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("b")
        await _focus_row(pilot, app, "panel_reference")
        await pilot.press("enter")
        assert app.query("#editor")
        assert not app.screen.query("#picker")
        await pilot.press("escape")

        app.session.record_designators({1: ("SW1", "RV1")})
        await _focus_row(pilot, app, "panel_reference")
        await pilot.press("enter")
        picker = app.screen.query_one("#picker", SelectionList)
        picker.select_all()
        await pilot.press("enter")
        assert app.session.settings.boards.panel_reference.value == "RV1,SW1"


@pytest.mark.asyncio
async def test_a_picker_whose_answers_cannot_be_read_says_so() -> None:
    """A missing artwork is reported on the footer, never raised out of the app."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("a")
        await _focus_row(pilot, app, "drill_layer")
        await pilot.press("enter")
        assert not app.screen.query("#picker")
        assert "cannot read" in app.message


@pytest.mark.asyncio
async def test_a_path_typed_into_artwork_starts_the_project(tmp_path: Path) -> None:
    """Decision 6: a blocked start is usable, and a typed path is what starts it.

    Exiting at a builder who ran the tool in the wrong directory is the
    command line's reflex, so the row that states there is no artwork is
    also the row that answers it -- and the run that follows is over what
    was typed there.
    """
    panel = tmp_path / "artwork" / "tar.ai"
    panel.parent.mkdir()
    panel.write_bytes(b"")
    elsewhere = tmp_path / "empty"
    elsewhere.mkdir()
    app = cli._workbench_for(cli.build_parser().parse_args([]), elsewhere)
    assert app.launch is None, "nothing was named, so there is no project to run yet"

    async with app.run_test() as pilot:
        await pilot.press("a")
        await _focus_row(pilot, app, "panel")
        await pilot.press("enter")
        app.query_one("#editor", Input).value = str(panel)
        await pilot.press("enter")
        await pilot.pause()

        assert app.session.settings.artwork.panel.value == panel
        assert app.session.obstacle is None
        assert app.launch is not None and app.launch.panel == panel


@pytest.mark.asyncio
async def test_several_artworks_offer_the_artwork_row_a_pick(tmp_path: Path) -> None:
    """Decision 6: several `.ai` files offer a pick, on the row that holds the answer."""
    for name in ("fuzz.ai", "tar.ai"):
        (tmp_path / name).write_bytes(b"")
    app = cli._workbench_for(cli.build_parser().parse_args([]), tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("a")
        await _focus_row(pilot, app, "panel")
        await pilot.press("enter")
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        assert {Path(choice).name for choice in picker.choices} == {"fuzz.ai", "tar.ai"}

        await pilot.press("enter")
        await pilot.pause()
        assert app.session.settings.artwork.panel.value == tmp_path / "fuzz.ai"
        assert app.launch is not None and app.launch.panel == tmp_path / "fuzz.ai"


@pytest.mark.asyncio
async def test_a_refused_flag_marks_the_place_that_can_answer_it(tmp_path: Path) -> None:
    """Decision 4: the marker marks the place holding a gap, so it must be that place.

    The sidebar is what a blocked start is read through, and a mark on
    `Project` would send a builder to the one place with nothing to change.
    """
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    app = cli._workbench_for(
        cli.build_parser().parse_args([str(panel), "--case", "bogus"]), tmp_path
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        marked = [line for line in app.sidebar_text().splitlines() if "!" in line]
        assert len(marked) == 1, app.sidebar_text()
        assert "Enclosure" in marked[0]


@pytest.mark.asyncio
async def test_a_declaration_the_artwork_contradicts_is_drawn(tmp_path: Path) -> None:
    """Decision 6: a contradicted declaration is news, so somebody has to read it.

    The declaration stands, which is the dangerous half and is already
    right; what this asks is that the run says so where a builder is
    looking.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "artwork": {"drill_layer": "Sparkle"}}), encoding="utf-8"
    )
    app = cli._workbench_for(cli.build_parser().parse_args([str(panel)]), tmp_path)
    assert app.session.notes, "nothing was resolved into a note, so nothing below is about one"

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        assert "Sparkle" in app.pane_text()


@pytest.mark.asyncio
async def test_an_unknown_manifest_key_is_drawn_where_it_is_read(tmp_path: Path) -> None:
    """Decision 9: reported and ignored -- and a report nobody draws is neither."""
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "drilling": {"grid_mm": 0.5, "wobble": 3}}), encoding="utf-8"
    )
    app = cli._workbench_for(cli.build_parser().parse_args([str(panel)]), tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        assert "wobble" in app.pane_text()


@pytest.mark.asyncio
async def test_a_project_with_nothing_to_report_draws_no_note(tmp_path: Path) -> None:
    """The control: a pane that always drew a line would prove nothing above."""
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "drilling": {"grid_mm": 0.5}}), encoding="utf-8"
    )
    app = cli._workbench_for(cli.build_parser().parse_args([str(panel)]), tmp_path)
    assert not app.session.notes

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
        assert app.pane_text().strip() == "\n".join(
            (app.session.statement(), "Run this project")
        )


def test_every_row_a_place_states_is_a_row_a_user_can_edit() -> None:
    """The two tables are one statement; a field in either alone is a defect."""
    settings = Settings.of_defaults(_PANEL)
    for place, fields in FIELDS.items():
        stated = {field for field, _label, _value in getattr(settings, place.value).rows()}
        assert {field.name for field in fields} == stated


def test_every_value_the_workbench_exposes_is_reachable_through_the_manifest() -> None:
    """Decision 6: the command line identifies the work, the project how it is done.

    A row the project cannot declare would be re-entered on every open.
    ``panel`` is the one exception, and names itself: the manifest is named
    after the panel, so recording it would answer a settled question twice.
    """
    from stompcad.manifest import PLACES

    for place, fields in FIELDS.items():
        declarable = PLACES[place.value] | ({"panel"} if place is Place.ARTWORK else set())
        assert {field.name for field in fields} <= declarable, place


@pytest.mark.asyncio
async def test_the_findings_place_lists_what_the_run_found() -> None:
    app = Workbench(_session())
    async with app.run_test() as pilot:
        app.session.record_findings([
            Diagnostic(Severity.WARNING, "off-grid", "a hole moved 0.06 mm"),
            Diagnostic(Severity.INFO, "inferred-enclosure", "the part came from tar-case.stp"),
        ])
        await pilot.press("f")
        shown = app.pane_text()
        assert "off-grid" in shown
        assert "inferred-enclosure" in shown


@pytest.mark.asyncio
async def test_information_is_listed_but_not_counted() -> None:
    """Decision 4: a run that inferred an enclosure succeeded, and owes nothing."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        app.session.record_findings([
            Diagnostic(Severity.INFO, "seating-search-bounded", "bounded at 20 mm"),
        ])
        await app.redraw()
        await pilot.pause()
        row = next(row for row in app.session.rows() if row.place is Place.FINDINGS)
        assert row.count == 0
        assert not row.attention


@pytest.mark.asyncio
async def test_an_artefact_already_on_disk_is_never_called_current(tmp_path: Path) -> None:
    """Decision 2: the workbench cannot know it matches, and must not imply it."""
    artefact = tmp_path / "tar-case.drl"
    artefact.write_text("M30\n", encoding="utf-8")
    app = Workbench(_session(_targets({"excellon": artefact})))
    async with app.run_test() as pilot:
        await pilot.press("o")
        shown = app.pane_text()
        assert "already on disk" in shown
        assert "made by this run" not in shown


@pytest.mark.asyncio
async def test_an_artefact_this_session_wrote_says_so(tmp_path: Path) -> None:
    artefact = tmp_path / "tar-case.drl"
    artefact.write_text("M30\n", encoding="utf-8")
    app = Workbench(_session(_targets({"excellon": artefact})))
    async with app.run_test() as pilot:
        app.session.record_written([artefact])
        await pilot.press("o")
        assert "made by this run" in app.pane_text()


@pytest.mark.asyncio
async def test_ctrl_l_re_reads_the_artwork_s_own_layer_list() -> None:
    """A re-export from Illustrator is the reason this key exists."""
    app = Workbench(_session(), launch=None)
    async with app.run_test() as pilot:
        await pilot.press("a", "ctrl+l")
        assert "read-panel" in app.session.stale()


@pytest.mark.asyncio
async def test_ctrl_f_adopts_a_model_the_cache_already_holds(tmp_path: Path) -> None:
    """CLAUDE.md: acquiring a model is separate work, so this only looks."""
    cache = tmp_path / "cases"
    cache.mkdir()
    (cache / "1590B.stp").write_text("ISO-10303-21;\n", encoding="utf-8")
    app = Workbench(_session(_declared_case("1590B")), cache=cache)
    async with app.run_test() as pilot:
        await pilot.press("e", "ctrl+f")
        assert app.session.settings.enclosure.case_model.value == cache / "1590B.stp"
        assert app.session.settings.enclosure.case_model.provenance.origin is Origin.DISCOVERED


@pytest.mark.asyncio
async def test_ctrl_f_downloads_nothing_and_says_where_to_get_one(tmp_path: Path) -> None:
    """The control: a key that fetched would make the workbench acquire models."""
    app = Workbench(_session(_declared_case("1590B")), cache=tmp_path / "empty")
    async with app.run_test() as pilot:
        await pilot.press("e", "ctrl+f")
        assert "fetch_case_model" in app.message
        assert app.session.settings.enclosure.case_model.value is None


@pytest.mark.asyncio
async def test_ctrl_f_refuses_while_a_run_holds_the_place(tmp_path: Path) -> None:
    """Decision 5: a key that adopts a value is a mutation, and a run holds the place.

    The control is the test above: with no run the same press over the same
    cache adopts the model, so this refusal is the run's and not the cache's.
    """
    cache = tmp_path / "cases"
    cache.mkdir()
    (cache / "1590B.stp").write_text("ISO-10303-21;\n", encoding="utf-8")
    app = Workbench(_session(_declared_case("1590B")), cache=cache)
    async with app.run_test() as pilot:
        app.session.begin_run(frozenset({"read-panel", "quantise"}))
        await pilot.press("e", "ctrl+f")
        assert app.session.settings.enclosure.case_model.value is None
        assert "enclosure" in app.message and "run" in app.message
        await pilot.press("d")
        assert app.session.place is Place.DRILLING, "the refusal never left the action"


@pytest.mark.asyncio
async def test_ctrl_l_refuses_while_a_run_holds_the_place() -> None:
    """Decision 5: invalidating is the statement an edit makes, so a run refuses it.

    The control is ``test_ctrl_l_re_reads_the_artwork_s_own_layer_list``:
    with no run the same press does make ``read-panel`` stale.
    """
    app = Workbench(_session())
    async with app.run_test() as pilot:
        app.session.begin_run(frozenset({"read-panel", "quantise"}))
        before = app.session.stale()
        await pilot.press("a", "ctrl+l")
        assert app.session.stale() == before
        assert "artwork" in app.message and "run" in app.message
        await pilot.press("d")
        assert app.session.place is Place.DRILLING, "the refusal never left the action"


@pytest.mark.asyncio
async def test_ctrl_f_without_the_acquiring_tool_says_no_location_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback: `tools` is a repository script, so an app cannot count on it."""
    monkeypatch.setitem(sys.modules, "tools.fetch_case_model", None)
    app = Workbench(_session(_declared_case("1590B")))
    async with app.run_test() as pilot:
        await pilot.press("e", "ctrl+f")
        assert "no cache location is known" in app.message
        assert "tools/fetch_case_model.py" in app.message
