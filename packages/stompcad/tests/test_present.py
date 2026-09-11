"""The plain writer: the same step lines a terminal would settle into."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import (
    Choice,
    NoTerminal,
    PlainWriter,
    Presentation,
    Question,
    step_line,
)

__all__: list[str] = []


def _accepts_presentation(presentation: Presentation) -> None:
    """Structural conformance, enforced by mypy rather than at runtime."""


def _accepts_question(question: Question) -> None:
    """As above, for the question protocol plan C constructs."""


def test_plain_writer_satisfies_presentation() -> None:
    """Plan B is written against ``Presentation``; mypy must check ``PlainWriter`` here."""
    _accepts_presentation(PlainWriter(io.StringIO()))


def test_choice_satisfies_question() -> None:
    """Plan C constructs ``Choice`` and passes it where ``Question`` is expected."""
    _accepts_question(Choice(prompt="which enclosure?", candidates=("1590B",)))


def test_a_step_prints_when_it_finishes_not_when_it_starts() -> None:
    """Spec decision 4: a step is reported on completion."""
    out = io.StringIO()
    writer = PlainWriter(out)
    writer.begin(DRILL_AND_DOCK)
    writer.update(0.0, ("read panel",))
    assert out.getvalue() == ""

    writer.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai, 1590B.stp")
    assert out.getvalue() == "  read panel      tar.ai, 1590B.stp\n"


def test_finish_step_before_begin_leaves_the_label_unpadded() -> None:
    """No plan means no known widest label, so the column simply does not exist."""
    out = io.StringIO()
    writer = PlainWriter(out)

    writer.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai, 1590B.stp")

    assert out.getvalue() == "  read panel  tar.ai, 1590B.stp\n"


def test_report_writes_each_line_terminated_and_nothing_else() -> None:
    out = io.StringIO()
    writer = PlainWriter(out)

    writer.report(["holes: 6", "tools: 2"])

    assert out.getvalue() == "holes: 6\ntools: 2\n"


def test_asking_without_a_terminal_is_a_usage_failure() -> None:
    """Spec decision 11: a gap with no terminal names what was missing."""
    writer = PlainWriter(io.StringIO())
    question = Choice(prompt="which enclosure?", candidates=("1590B",))

    with pytest.raises(NoTerminal) as raised:
        writer.ask(question)

    assert "which enclosure?" in str(raised.value)


def test_textual_is_declared_not_merely_installed() -> None:
    """It reaches this venv through mutmut's own dependencies, not ours.

    A presentation built on an undeclared import would pass every test here
    and fail for anyone who installed this package on its own.
    """
    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    block = re.search(r"^dependencies = \[(.*?)\]", manifest.read_text(), re.S | re.M)
    assert block is not None, "no dependencies block in pyproject.toml"
    assert "textual" in block.group(1)


def test_one_format_serves_both_writers() -> None:
    """Decision 2: the settled terminal lines and the piped lines are the same."""
    assert step_line("quantise", "8 holes, 2 tools", width=10) == "  quantise    8 holes, 2 tools"
    assert step_line("quantise", "8 holes, 2 tools") == "  quantise  8 holes, 2 tools"
