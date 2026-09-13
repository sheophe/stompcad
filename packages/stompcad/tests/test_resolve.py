"""The pure half of resolution: what a gap offers, without asking anybody."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad.drive import RunOptions
from stompcad.resolve import RESOLVABLE, promoted, question_for, revision_for
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.model import CaseFace

__all__: list[str] = []


def _options(tmp_path: Path) -> RunOptions:
    """A run's options with the two fields a picker revises set to knowns."""
    return RunOptions(
        panel=tmp_path / "panel.ai",
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case=None,
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(),
        panel_reference="RV*",
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
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


def test_every_resolvable_code_survives_its_own_retry(tmp_path: Path) -> None:
    """A retry consults ``_RETRY_INPUTS``, not ``_STEP_INPUTS``: a code whose
    step cannot honour its own revision on a second run would ask a
    question, then refuse the very answer it asked for.
    """
    from dataclasses import fields

    from stompcad.drive import _RETRY_INPUTS

    options = _options(tmp_path)
    for code, key in RESOLVABLE.items():
        assert key in _RETRY_INPUTS, f"{code} names {key}, which no retry can run again"
        revised = revision_for(Diagnostic.error(code, "message"), options, "X")
        changed = {
            field.name
            for field in fields(options)
            if getattr(revised, field.name) != getattr(options, field.name)
        }
        assert changed <= _RETRY_INPUTS[key], f"{code} revises {changed}, which {key!r} refuses"


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


def test_promotion_raises_every_warning_not_only_resolvable_ones() -> None:
    """Decision 6: promotion happens before the resolvable check, not after."""
    diagnostics = (
        Diagnostic.warning("ambiguous-placement", "board 1: 2 placements fit"),
        Diagnostic.info("grid-tie", "two holes share a grid point"),
        Diagnostic.error("unknown-diameter", "no such drill"),
    )

    raised = promoted(diagnostics)

    assert [d.severity for d in raised] == [Severity.ERROR, Severity.INFO, Severity.ERROR]
    assert [d.code for d in raised] == [d.code for d in diagnostics]


def test_a_promoted_warning_becomes_a_question_when_its_code_is_resolvable() -> None:
    """One resolution path: a promoted warning is asked about exactly as an error is."""
    warning = Diagnostic.warning(
        "ambiguous-enclosure", "tied", data=(("candidates", "1590B, 1590B2"),)
    )
    assert question_for(warning) is None

    (raised,) = promoted((warning,))
    question = question_for(raised)

    assert question is not None
    assert question.candidates == ("1590B", "1590B2")


def test_a_promoted_placement_is_still_not_a_question() -> None:
    """No stage applies a chosen placement, so no picker may offer one.

    ``ambiguous-placement`` carries a count rather than candidates, and
    ``--place`` is refused as unsupported; a picker here would ask what
    nothing could honour.
    """
    (raised,) = promoted(
        (Diagnostic.warning("ambiguous-placement", "board 1", data=(("placements", 2),)),)
    )
    assert raised.severity is Severity.ERROR
    assert question_for(raised) is None
    assert "ambiguous-placement" not in RESOLVABLE
