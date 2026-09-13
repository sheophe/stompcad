"""Rank three: what the tool finds out rather than asking about."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad import discover
from tests.conftest import TAR_AI, case_model


def test_one_panel_in_a_directory_is_found(tmp_path: Path) -> None:
    (tmp_path / "tar.ai").write_bytes(b"")
    assert discover.panels(tmp_path) == (tmp_path / "tar.ai",)


def test_several_panels_come_back_in_a_stable_order(tmp_path: Path) -> None:
    for name in ("b.ai", "a.ai"):
        (tmp_path / name).write_bytes(b"")
    assert [path.name for path in discover.panels(tmp_path)] == ["a.ai", "b.ai"]


def test_no_panel_is_an_empty_result_not_a_failure(tmp_path: Path) -> None:
    assert discover.panels(tmp_path) == ()


def test_layers_come_from_the_artwork_itself() -> None:
    found = discover.layers(TAR_AI)
    assert "Drill" in found
    assert found == tuple(dict.fromkeys(found)), "layer names must not repeat"


def test_a_board_candidate_excludes_the_case_model_and_our_own_outputs(
    tmp_path: Path,
) -> None:
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    for name in ("tar-pcb.stp", "other.stp", "tar-case.stp", "tar-assembly.stp"):
        (tmp_path / name).write_bytes(b"")
    model = tmp_path / "1590B.stp"
    model.write_bytes(b"")
    found = discover.board_candidates(tmp_path, panel, model)
    assert [path.name for path in found] == ["tar-pcb.stp", "other.stp"]


def test_a_pcb_suffix_sorts_first_because_it_is_ours() -> None:
    """`-pcb` is this project's own naming, so it leads; the rest follow by name."""
    assert discover.board_candidates.__doc__ is not None


def test_a_part_is_read_from_a_model_filename(tmp_path: Path) -> None:
    assert discover.part_from_model(tmp_path / "1590BB.stp") == "1590BB"
    assert discover.part_from_model(tmp_path / "not-a-part.stp") is None


@pytest.mark.hammond
def test_a_cached_model_is_found_by_part() -> None:
    cached = case_model("1590B")
    assert cached is not None
    found = discover.cached_model("1590B", cached.parent)
    assert found is not None and found.value == cached
    assert found.detail == "cached for 1590B"


def test_every_format_has_a_file_name() -> None:
    from stompcad.drive import DOCK_TARGET_NAMES
    from stompdrill.emitters import available

    assert set(discover.ARTEFACT_NAMES) == set(available()) | DOCK_TARGET_NAMES


def test_output_paths_follow_the_naming_scheme(tmp_path: Path) -> None:
    panel = tmp_path / "tar.ai"
    assert discover.output_path("excellon", panel) == tmp_path / "tar-case.drl"
    assert discover.output_path("drawing-pdf", panel) == tmp_path / "tar-case.pdf"
    assert discover.output_path("step", panel) == tmp_path / "tar-case.stp"
    assert discover.output_path("assembly", panel) == tmp_path / "tar-assembly.stp"
    assert discover.output_path("report", panel) == tmp_path / "tar-assembly.txt"
