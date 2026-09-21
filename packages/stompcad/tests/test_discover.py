"""Rank three: what the tool finds out rather than asking about."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad import discover
from stompdrill.pipeline.enclosure import fitting_parts as parts_fitting
from stompdrill.sources import AiPdfSource
from tests.conftest import TAR_AI


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
    assert discover.output_path("report", panel) == tmp_path / "tar-assembly.json"


def test_the_catalogue_parts_are_the_tool_s_own_once_each_in_order() -> None:
    """A picker offers what ``stompdrill`` recognises, never a list kept here."""
    from stompdrill.enclosures import footprints

    parts = discover.catalogue_parts()
    assert set(parts) == {part for names in footprints().values() for part in names}
    assert list(parts) == sorted(set(parts))


def test_the_fitting_parts_are_read_from_the_artworks_own_outline() -> None:
    """tar.ai is drawn to a 1590B backplate, which several parts share."""
    parts = discover.fitting_parts(TAR_AI, "Drill", "Background", 1)
    assert "1590B" in parts


def test_the_fit_is_the_tools_own_answer_rather_than_a_second_opinion() -> None:
    """The control that keeps one matching rule: same file, same parts."""
    raw = AiPdfSource(TAR_AI, drill_layer="Drill", reference_layer="Background").read()
    assert raw.reference is not None
    assert discover.fitting_parts(TAR_AI, "Drill", "Background", 1) == parts_fitting(raw.reference)


def test_an_artwork_that_cannot_be_read_narrows_nothing(tmp_path: Path) -> None:
    """A read that fails is not an answer about enclosures, so it offers none."""
    nothing = tmp_path / "not-artwork.ai"
    nothing.write_bytes(b"this is not a PDF")
    assert discover.fitting_parts(nothing, "Drill", "Background", 1) == ()


def test_a_layer_the_artwork_has_not_got_narrows_nothing() -> None:
    assert discover.fitting_parts(TAR_AI, "Drill", "NoSuchLayer", 1) == ()


def test_a_match_that_will_not_complete_narrows_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole answer is guarded, not the read alone: a caller waiting on a
    worker thread cannot tell a match that broke from a file that would not
    read, and one that raised would leave it waiting for ever."""

    def broken(_outline: object) -> tuple[str, ...]:
        raise RuntimeError("the matching rule broke")

    monkeypatch.setattr(discover, "parts_fitting", broken)
    assert discover.fitting_parts(TAR_AI, "Drill", "Background", 1) == ()
