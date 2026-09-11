"""The run drawn above the prompt, driven through Textual's own pilot."""

from __future__ import annotations

import pytest

from stompcad.inline import InlineApp
from stompcad.plan import DRILL_AND_DOCK

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
