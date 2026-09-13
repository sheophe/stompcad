"""The project file: what it holds, what it refuses, and what it ignores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stompcad import manifest


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    panel = tmp_path / "tar.ai"
    (tmp_path / "tar.stompcad.json").write_text(json.dumps(payload), encoding="utf-8")
    return panel


def test_the_manifest_sits_beside_the_panel_and_is_named_from_it(tmp_path: Path) -> None:
    assert manifest.manifest_path(tmp_path / "tar.ai") == tmp_path / "tar.stompcad.json"


def test_a_missing_manifest_reads_as_empty_rather_than_failing(tmp_path: Path) -> None:
    read = manifest.read(tmp_path / "tar.ai")
    assert read.values == {}
    assert read.notes == []


def test_a_declared_value_reaches_its_place(tmp_path: Path) -> None:
    panel = _write(tmp_path, {"version": 1, "drilling": {"grid_mm": 0.5}})
    assert manifest.read(panel).values["drilling"]["grid_mm"] == 0.5


def test_a_relative_path_is_resolved_against_the_project(tmp_path: Path) -> None:
    panel = _write(tmp_path, {"version": 1, "boards": {"boards": ["tar-pcb.stp"]}})
    assert manifest.read(panel).values["boards"]["boards"] == [tmp_path / "tar-pcb.stp"]


def test_an_unknown_key_is_reported_and_ignored(tmp_path: Path) -> None:
    panel = _write(tmp_path, {"version": 1, "drilling": {"grid_mm": 0.5, "wobble": 3}})
    read = manifest.read(panel)
    assert read.values["drilling"] == {"grid_mm": 0.5}
    assert any("wobble" in note for note in read.notes)


def test_an_unknown_place_is_reported_and_ignored(tmp_path: Path) -> None:
    panel = _write(tmp_path, {"version": 1, "sparkle": {"x": 1}})
    read = manifest.read(panel)
    assert "sparkle" not in read.values
    assert any("sparkle" in note for note in read.notes)


def test_malformed_json_is_a_usage_failure_naming_the_file(tmp_path: Path) -> None:
    panel = tmp_path / "tar.ai"
    (tmp_path / "tar.stompcad.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(manifest.ManifestError) as failure:
        manifest.read(panel)
    assert "tar.stompcad.json" in str(failure.value)


def test_a_manifest_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    panel = _write(tmp_path, ["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(manifest.ManifestError):
        manifest.read(panel)


def test_a_later_version_still_opens(tmp_path: Path) -> None:
    """Forward compatibility is the whole reason an unknown key is a note."""
    panel = _write(tmp_path, {"version": manifest.VERSION + 1, "drilling": {"grid_mm": 0.5}})
    read = manifest.read(panel)
    assert read.values["drilling"]["grid_mm"] == 0.5
    assert any("version" in note for note in read.notes)


def test_a_manifest_error_exits_three() -> None:
    """It is caught beside the library faults cli.main already handles."""
    from stompmodel.errors import StompError

    assert issubclass(manifest.ManifestError, StompError)
