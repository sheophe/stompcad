"""Decision 17's matrix, one row at a time."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from stompcad.readiness import Blocker, readiness
from stompcad.settings import Origin, Provenance, Resolved, Settings


def test_a_project_with_no_panel_is_blocked_on_the_artwork() -> None:
    from stompcad.settings import DEFAULTS

    assert Blocker.NO_PANEL in {blocker for blocker, _, _ in readiness(DEFAULTS).blockers}


def test_a_bare_default_project_is_not_ready(tmp_path: Path) -> None:
    found = readiness(Settings.of_defaults(tmp_path / "tar.ai"))
    assert Blocker.BOARDS_UNRESOLVED in {blocker for blocker, _, _ in found.blockers}
    assert not found.ready


def test_a_confirmed_empty_board_list_means_drill_only(tmp_path: Path) -> None:
    settings = Settings.of_defaults(tmp_path / "tar.ai")
    settings = replace(
        settings,
        boards=replace(settings.boards, boards=Resolved((), Provenance(Origin.USER))),
        output=replace(
            settings.output,
            targets=Resolved((("excellon", tmp_path / "tar-case.drl"),), Provenance(Origin.USER)),
        ),
    )
    assert readiness(settings).ready


def test_a_selected_board_needs_a_case_model_and_a_reference(tmp_path: Path) -> None:
    settings = Settings.of_defaults(tmp_path / "tar.ai")
    settings = replace(
        settings,
        boards=replace(
            settings.boards,
            boards=Resolved((tmp_path / "tar-pcb.stp",), Provenance(Origin.USER)),
        ),
        output=replace(
            settings.output,
            targets=Resolved((("assembly", tmp_path / "tar-assembly.stp"),), Provenance(Origin.USER)),
        ),
    )
    blockers = {blocker for blocker, _, _ in readiness(settings).blockers}
    assert blockers == {Blocker.NO_CASE_MODEL, Blocker.NO_PANEL_REFERENCE}


def test_an_assembly_without_a_board_is_blocked(tmp_path: Path) -> None:
    settings = Settings.of_defaults(tmp_path / "tar.ai")
    settings = replace(
        settings,
        boards=replace(settings.boards, boards=Resolved((), Provenance(Origin.USER))),
        output=replace(
            settings.output,
            targets=Resolved((("assembly", tmp_path / "tar-assembly.stp"),), Provenance(Origin.USER)),
        ),
    )
    assert Blocker.NO_BOARD_FOR_ASSEMBLY in {blocker for blocker, _, _ in readiness(settings).blockers}


def test_no_artefact_at_rank_four_is_blocked_but_a_declared_none_is_not(
    tmp_path: Path,
) -> None:
    settings = Settings.of_defaults(tmp_path / "tar.ai")
    settings = replace(
        settings, boards=replace(settings.boards, boards=Resolved((), Provenance(Origin.USER)))
    )
    assert Blocker.NO_TARGETS in {blocker for blocker, _, _ in readiness(settings).blockers}

    declared_none = replace(
        settings, output=replace(settings.output, targets=Resolved((), Provenance(Origin.USER)))
    )
    assert readiness(declared_none).ready, "check-only is a legitimate thing to ask for"


def test_every_blocker_names_the_place_that_answers_it(tmp_path: Path) -> None:
    from stompcad.manifest import PLACES

    for blocker, place, sentence in readiness(Settings.of_defaults(tmp_path / "tar.ai")).blockers:
        assert place in PLACES, blocker
        assert sentence and sentence[0].isupper(), blocker
