"""The application through Textual's own pilot: keys, places, markers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Static

from stompcad import manifest
from stompcad.cli import Resolution
from stompcad.readiness import readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.app import Workbench
from stompcad.workbench.keys import GLOBAL_VERBS, PLACE_KEYS, Place
from stompcad.workbench.session import Session

__all__: list[str] = []

_PANEL = Path("/project/tar.ai")


def _session(settings: Settings | None = None) -> Session:
    resolved = settings if settings is not None else _runnable()
    return Session(Resolution(
        settings=resolved, notes=(), blockers=readiness(resolved), project=manifest.Manifest(),
    ))


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
        shown = str(app.screen.query_one("#key-list", Static).content)
        for key in (*PLACE_KEYS, *GLOBAL_VERBS):
            assert key.replace("question_mark", "?") in shown


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
