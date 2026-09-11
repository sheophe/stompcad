"""The plain writer: the same step lines a terminal would settle into."""

from __future__ import annotations

import io

import pytest

from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import Choice, NoTerminal, PlainWriter

__all__: list[str] = []


def test_a_step_prints_when_it_finishes_not_when_it_starts() -> None:
    """Spec decision 4: a step is reported on completion."""
    out = io.StringIO()
    writer = PlainWriter(out)
    writer.begin(DRILL_AND_DOCK)
    writer.update(0.0, ("read panel",))
    assert out.getvalue() == ""

    writer.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai, 1590B.stp")
    assert out.getvalue() == "  read panel      tar.ai, 1590B.stp\n"


def test_asking_without_a_terminal_is_a_usage_failure() -> None:
    """Spec decision 11: a gap with no terminal names what was missing."""
    writer = PlainWriter(io.StringIO())
    question = Choice(prompt="which enclosure?", candidates=("1590B",))

    with pytest.raises(NoTerminal) as raised:
        writer.ask(question)

    assert "which enclosure?" in str(raised.value)
