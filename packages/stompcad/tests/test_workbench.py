"""The application through Textual's own pilot: keys, places, markers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.binding import Binding, BindingsMap
from textual.command import CommandPalette
from textual.pilot import Pilot
from textual.widgets import Input, SelectionList, Static

from stompcad import cli, manifest
from stompcad.cli import Resolution
from stompcad.readiness import readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.app import Workbench
from stompcad.workbench.keys import (
    GLOBAL_VERBS,
    LOCAL_KEYS,
    PLACE_KEYS,
    RUN_KEYS,
    STEP_KEYS,
    Place,
)
from stompcad.workbench.places import FIELDS, ValueRow
from stompcad.workbench.session import Session

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
async def test_the_sidebar_is_never_focused() -> None:
    """Decision 3: the sidebar is a map, not a control to tab into."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("tab", "tab", "tab")
        assert app.focused is None or "Sidebar" not in type(app.focused).__name__


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
async def test_the_keys_screen_lists_every_key_the_table_holds() -> None:
    """`?` teaches the letters, from the same table the bindings are built from."""
    app = Workbench(_session())
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        lines = [
            line.strip() for line in str(app.screen.query_one("#key-list", Static).content).splitlines()
        ]
        for key in (*PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS):
            shown = key.replace("question_mark", "?")
            assert any(line.startswith(f"{shown} ") for line in lines), shown


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
    tabled = _spelled(*PLACE_KEYS, *GLOBAL_VERBS, *STEP_KEYS, *LOCAL_KEYS, *RUN_KEYS)
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
