"""The pure half of resolution: what a gap offers, without asking anybody."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad.drive import RunOptions
from stompcad.resolve import RESOLVABLE, question_for, revision_for
from stompmodel.diagnostics import Diagnostic

__all__: list[str] = []


def _options(tmp_path: Path) -> RunOptions:
    """A run's options with the two fields a picker revises set to knowns."""
    return RunOptions(
        panel=tmp_path / "panel.ai",
        boards=(),
        case=None,
        case_model=None,
        panel_reference="RV*",
        targets=(),
    )


def test_a_warning_is_never_a_question() -> None:
    """Decision 6: only an ERROR reaches a picker."""
    warning = Diagnostic.warning(
        "ambiguous-enclosure", "tied", data=(("candidates", "1590B, 1590B2"),)
    )
    assert question_for(warning) is None


def test_a_refusal_carries_no_resolvable_code() -> None:
    """Decision 6: ``unknown-diameter`` and its kin can reach no picker."""
    refusal = Diagnostic.error("unknown-diameter", "no such drill")
    assert question_for(refusal) is None
    assert "unknown-diameter" not in RESOLVABLE


def test_a_tie_between_parts_offers_the_tied_parts() -> None:
    """The candidates are the tool's own, split from the list it formatted."""
    tie = Diagnostic.error(
        "ambiguous-enclosure",
        "reference outline is within tolerance of more than one footprint",
        data=(("candidates", "1590B, 1590B2, 1590BS"),),
    )
    question = question_for(tie)
    assert question is not None
    assert question.candidates == ("1590B", "1590B2", "1590BS")
    assert question.prompt == tie.message


def test_a_board_admitting_nothing_offers_its_own_designators() -> None:
    """Decision 6: ``empty-group``'s candidates are the board's designators.

    The diagnostic carries the board, not the list, so the names are
    handed in by whoever holds the boards.
    """
    empty = Diagnostic.error(
        "empty-group", "board 2 admits none of its designators", data=(("board", 2),)
    )
    question = question_for(empty, {2: ("RV1", "SW1"), 3: ("D1",)})
    assert question is not None
    assert question.candidates == ("RV1", "SW1")


def test_a_board_whose_designators_are_unknown_asks_nothing() -> None:
    """An empty candidate set is no question: a picker with no answers helps nobody."""
    empty = Diagnostic.error("empty-group", "board 9", data=(("board", 9),))
    assert question_for(empty, {2: ("RV1",)}) is None


def test_every_resolvable_code_names_a_step_that_reads_its_revision() -> None:
    """A code whose step cannot honour the answer would ask and then ignore it."""
    from stompcad.drive import _STEP_INPUTS

    for code, key in RESOLVABLE.items():
        assert key in _STEP_INPUTS, f"{code} names {key}, which is no step"


def test_a_declared_case_answers_a_tie(tmp_path: Path) -> None:
    """The tie is resolved by declaring the part, which ``quantise`` reads."""
    options = _options(tmp_path)
    tie = Diagnostic.error("ambiguous-enclosure", "tied", data=(("candidates", "1590B, 1590B2"),))

    revised = revision_for(tie, options, "1590B2")

    assert revised.case == "1590B2"
    assert revised.panel_reference == options.panel_reference


def test_an_admitted_designator_widens_the_expression(tmp_path: Path) -> None:
    """Widened, not replaced: the expression still admits every other board."""
    options = _options(tmp_path)
    empty = Diagnostic.error("empty-group", "board 2", data=(("board", 2),))

    revised = revision_for(empty, options, "SW1")

    assert revised.panel_reference == "RV*,SW1"
    assert revised.case == options.case


def test_the_widened_expression_still_parses(tmp_path: Path) -> None:
    """An answer that produced an unparseable filter would fail at the retry."""
    from stompcollider.designators import parse_filter

    options = _options(tmp_path)
    empty = Diagnostic.error("empty-group", "board 2", data=(("board", 2),))

    revised = revision_for(empty, options, "SW1")

    assert parse_filter(revised.panel_reference).admit(["SW1"]) == {"SW1"}


def test_an_unresolvable_code_has_no_revision(tmp_path: Path) -> None:
    """Nothing outside the table may quietly acquire a revision."""
    with pytest.raises(KeyError):
        revision_for(
            Diagnostic.error("unknown-diameter", "no such drill"), _options(tmp_path), "x"
        )
