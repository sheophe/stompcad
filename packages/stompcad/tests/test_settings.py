"""The four ranks, and what each resolved value says about itself."""

from __future__ import annotations

from pathlib import Path

from stompcad.settings import Discovery, Origin, pick


def test_an_argument_beats_every_other_rank() -> None:
    resolved = pick(0.5, 0.25, Discovery(0.1, "the artwork"), 0.25)
    assert resolved.value == 0.5
    assert resolved.provenance.origin is Origin.ARGUMENT


def test_the_project_beats_discovery_and_the_default() -> None:
    resolved = pick(None, 0.25, Discovery(0.1, "the artwork"), 0.05)
    assert resolved.value == 0.25
    assert resolved.provenance.origin is Origin.PROJECT


def test_discovery_beats_the_default_and_keeps_how() -> None:
    resolved = pick(None, None, Discovery(Path("a.stp"), "found beside it"), None)
    assert resolved.value == Path("a.stp")
    assert resolved.provenance.origin is Origin.DISCOVERED
    assert resolved.provenance.detail == "found beside it"


def test_the_default_is_the_last_rank() -> None:
    resolved = pick(None, None, None, 0.25)
    assert resolved.value == 0.25
    assert resolved.provenance.origin is Origin.DEFAULT


def test_a_disagreement_is_carried_not_discarded() -> None:
    resolved = pick(0.5, 0.25, None, 0.25)
    assert resolved.project == 0.25
    assert resolved.describe() == "0.5, from the command line — the project says 0.25"


def test_agreement_says_only_where_the_value_came_from() -> None:
    assert pick(None, None, None, 0.25).describe() == "0.25, default"


def test_the_project_agreeing_with_itself_carries_no_disagreement() -> None:
    resolved = pick(0.25, 0.25, None, 0.25)
    assert resolved.project is None
    assert resolved.describe() == "0.25, from the command line"
