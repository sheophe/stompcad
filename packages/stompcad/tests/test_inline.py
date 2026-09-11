"""The run drawn above the prompt, driven through Textual's own pilot."""

from __future__ import annotations

import pytest

from stompcad.inline import InlineApp, TerminalPresentation
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import Presentation

__all__: list[str] = []


@pytest.mark.asyncio
async def test_the_bar_names_the_deepest_live_branch() -> None:
    """Decision 3: the bar level draws one bar and one line for the branch."""
    app = InlineApp()
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.advance(0.25, ("seat", "board 1", "coarse"))
        await pilot.pause()

        assert app.position == pytest.approx(0.25)
        assert "coarse" in app.branch


@pytest.mark.asyncio
async def test_a_settled_step_keeps_the_shared_line_format() -> None:
    """Decision 2: what the terminal settles into is what a pipe receives."""
    app = InlineApp()
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.settle(DRILL_AND_DOCK.steps[1], "8 holes, 2 tools")
        await pilot.pause()

        assert app.settled == ["  quantise        8 holes, 2 tools"]


def _accepts_presentation(presentation: Presentation) -> None:
    """Structural conformance, enforced by mypy rather than at runtime."""


@pytest.mark.asyncio
async def test_the_terminal_presentation_satisfies_the_boundary() -> None:
    """Plan A pinned ``Presentation``; this is the second implementation of it."""
    app = InlineApp()
    _accepts_presentation(TerminalPresentation(app))


@pytest.mark.asyncio
async def test_every_call_crosses_back_to_the_app_thread() -> None:
    """Textual forbids touching the UI from a worker; nothing here may.

    The double records what it was asked to run rather than running it, so a
    method that reached a widget directly would leave this list short.
    """
    app = InlineApp()
    crossings: list[str] = []

    def crossed(callback, *args, **kwargs):  # type: ignore[no-untyped-def]
        crossings.append(callback.__name__)
        return callback(*args, **kwargs)

    async with app.run_test() as pilot:
        app.call_from_thread = crossed  # type: ignore[method-assign]
        presentation = TerminalPresentation(app)
        presentation.begin(DRILL_AND_DOCK)
        presentation.update(0.5, ("seat",))
        presentation.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai")
        presentation.report(["read 8 holes"])
        await pilot.pause()

    assert crossings == ["show", "advance", "settle", "record"]


@pytest.mark.asyncio
async def test_the_worker_runs_the_composed_run_and_its_code_comes_back() -> None:
    """The run happens off the main thread; its exit code leaves through ``exit``."""
    app = InlineApp()
    app.drive(lambda: 7)
    async with app.run_test() as pilot:
        for _ in range(50):
            await pilot.pause()
            if app.return_value is not None:
                break
    assert app.return_value == 7


@pytest.mark.asyncio
async def test_v_cycles_the_level_without_disturbing_the_run() -> None:
    """Decision 3: the key redraws in place; it restarts nothing."""
    app = InlineApp(level="bar")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.advance(0.4, ("seat", "board 1"))
        app.settle(DRILL_AND_DOCK.steps[0], "tar.ai")
        await pilot.pause()

        await pilot.press("v")
        assert app.level == "steps"
        await pilot.press("v")
        assert app.level == "tree"
        await pilot.press("v")
        assert app.level == "bar"

        assert app.position == pytest.approx(0.4)
        assert app.settled == ["  read panel      tar.ai"]


@pytest.mark.asyncio
async def test_every_level_renders_the_same_recorded_run() -> None:
    """Each level is a projection of one state, not a separate record."""
    frames = {}
    for level in ("bar", "steps", "tree"):
        app = InlineApp(level=level)
        async with app.run_test() as pilot:
            app.show(DRILL_AND_DOCK)
            app.settle(DRILL_AND_DOCK.steps[0], "tar.ai")
            app.advance(0.4, ("quantise", "hole 3"))
            await pilot.pause()
            frames[level] = app.rendered()

    assert "  read panel      tar.ai" in frames["steps"]
    assert "  read panel      tar.ai" in frames["tree"]
    assert "quantise" in frames["bar"]
    assert "hole 3" in frames["tree"]
    assert "hole 3" not in frames["steps"]


@pytest.mark.asyncio
async def test_the_tree_expands_divisions_and_counts_per_item_leaves() -> None:
    """Decision 3: the divisions a step reports, not its every hole."""
    app = InlineApp(level="tree")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        for hole in range(25):
            app.advance(0.5, ("drill", "route", f"hole {hole}.000,0.000"))
        for phase in ("coarse", "fine", "settle"):
            app.advance(0.6, ("seat", "board 1", phase))
        await pilot.pause()
        drawn = app.rendered()

    assert "    route" in drawn
    assert "25 items" in drawn
    assert "hole 0.000,0.000" not in drawn
    assert "      coarse" in drawn
