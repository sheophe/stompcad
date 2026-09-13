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


def test_a_gap_is_filled_by_the_half_that_owns_it(tmp_path: Path) -> None:
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    settings = Settings.of_defaults(panel)
    written = json.loads(payload_for(panel, settings, Half.DRILL, manifest.Manifest()) or "{}")
    assert set(written) == {"version", "artwork", "enclosure", "drilling", "output"}
    assert "boards" not in written, "the dock half's place is not the drill half's to write"


def test_the_dock_half_writes_only_its_own_places(tmp_path: Path) -> None:
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    written = json.loads(
        payload_for(panel, Settings.of_defaults(panel), Half.DOCK, manifest.Manifest()) or "{}"
    )
    assert set(written) == {"version", "boards", "output"}


def test_a_value_the_project_already_holds_is_left_alone(tmp_path: Path) -> None:
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    held = manifest.Manifest(
        values={"drilling": {"grid_mm": 0.5}}, stored={"drilling": {"grid_mm": 0.5}}
    )
    written = json.loads(payload_for(panel, Settings.of_defaults(panel), Half.DRILL, held) or "{}")
    assert written["drilling"]["grid_mm"] == 0.5, "a declaration is never overwritten by a run"


def test_nothing_to_fill_stages_nothing(tmp_path: Path) -> None:
    """A run that adds no declaration must not rewrite the file it read."""
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    settings = Settings.of_defaults(panel)
    first = payload_for(panel, settings, Half.DRILL, manifest.Manifest())
    assert first is not None
    (tmp_path / "tar.stompcad.json").write_text(first, encoding="utf-8")
    assert payload_for(panel, settings, Half.DRILL, manifest.read(panel)) is None


def test_a_path_is_stored_relative_to_the_project(tmp_path: Path) -> None:
    from dataclasses import replace

    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Origin, Provenance, Resolved, Settings

    panel = tmp_path / "tar.ai"
    settings = Settings.of_defaults(panel)
    settings = replace(
        settings,
        boards=replace(
            settings.boards,
            boards=Resolved((tmp_path / "tar-pcb.stp",), Provenance(Origin.USER)),
        ),
    )
    written = json.loads(payload_for(panel, settings, Half.DOCK, manifest.Manifest()) or "{}")
    assert written["boards"]["boards"] == ["tar-pcb.stp"], "an absolute path breaks on a move"


def test_every_length_survives_the_round_trip(tmp_path: Path) -> None:
    """Decimal scaling is exact here; a manifest that loses a digit moves metal."""
    from dataclasses import replace

    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Origin, Provenance, Resolved, Settings
    from stompmodel.units import nm_from_mm

    panel = tmp_path / "tar.ai"
    for millimetres in (0.05, 0.1, 0.25, 0.3, 1.0, 2.0, 12.7, 0.7999):
        settings = Settings.of_defaults(panel)
        settings = replace(
            settings,
            drilling=replace(
                settings.drilling,
                grid_mm=Resolved(millimetres, Provenance(Origin.USER)),
            ),
        )
        text = payload_for(panel, settings, Half.DRILL, manifest.Manifest())
        assert text is not None
        (tmp_path / "tar.stompcad.json").write_text(text, encoding="utf-8")
        back = manifest.read(panel).values["drilling"]["grid_mm"]
        assert nm_from_mm(back) == nm_from_mm(millimetres), millimetres


def test_the_schema_covers_every_field_a_place_carries() -> None:
    """A field added to settings without a row in PLACES is never remembered."""
    from dataclasses import fields

    from stompcad.manifest import PLACES
    from stompcad.settings import DEFAULTS

    for place, allowed in PLACES.items():
        carried = {field.name for field in fields(getattr(DEFAULTS, place))}
        assert allowed <= carried, f"{place}: schema names a field settings does not carry"
        assert carried - allowed <= {"panel"}, f"{place}: settings carries a field the schema forgets"


def test_a_carried_over_path_reaches_the_next_half_as_the_string_it_was(tmp_path: Path) -> None:
    """A held path is already in-memory as a ``Path``; the payload must not choke on it.

    ``read()`` turns a declared path into a ``Path`` for the rest of the tool to
    resolve against. That resolved form must never be fed back to ``json.dumps``
    directly -- the file's own stored form has to be carried over unchanged.
    """
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "boards": {"boards": ["tar-pcb.stp"]}}), encoding="utf-8"
    )
    held = manifest.read(panel)
    settings = Settings.of_defaults(panel)
    written = json.loads(payload_for(panel, settings, Half.DRILL, held) or "{}")
    assert written["boards"]["boards"] == ["tar-pcb.stp"], "a carried-over path must not be re-derived"


def test_targets_merge_by_format_across_halves(tmp_path: Path) -> None:
    """``output.targets`` is the one key both halves declare into; each keeps its own format."""
    from dataclasses import replace

    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Origin, Provenance, Resolved, Settings

    panel = tmp_path / "tar.ai"
    manifest_file = tmp_path / "tar.stompcad.json"

    drill_settings = Settings.of_defaults(panel)
    drill_settings = replace(
        drill_settings,
        output=replace(
            drill_settings.output,
            targets=Resolved((("gerber", tmp_path / "tar.drl"),), Provenance(Origin.USER)),
        ),
    )
    first = payload_for(panel, drill_settings, Half.DRILL, manifest.Manifest())
    assert first is not None
    manifest_file.write_text(first, encoding="utf-8")

    dock_settings = Settings.of_defaults(panel)
    dock_settings = replace(
        dock_settings,
        output=replace(
            dock_settings.output,
            targets=Resolved((("assembly", tmp_path / "tar.json"),), Provenance(Origin.USER)),
        ),
    )
    second = payload_for(panel, dock_settings, Half.DOCK, manifest.read(panel))
    assert second is not None
    manifest_file.write_text(second, encoding="utf-8")

    final = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert final["output"]["targets"] == {"gerber": "tar.drl", "assembly": "tar.json"}, (
        "both halves' target formats must survive"
    )


def test_merging_a_target_does_not_mutate_the_held_manifest(tmp_path: Path) -> None:
    """``payload_for`` does not write -- and a held object is not the caller's to edit either."""
    from dataclasses import replace

    from stompcad.manifest import Half, Manifest, payload_for
    from stompcad.settings import Origin, Provenance, Resolved, Settings

    panel = tmp_path / "tar.ai"
    held = Manifest(stored={"output": {"targets": {"gerber": "tar.drl"}}})
    before = dict(held.stored["output"]["targets"])

    settings = Settings.of_defaults(panel)
    settings = replace(
        settings,
        output=replace(
            settings.output,
            targets=Resolved((("assembly", tmp_path / "tar.json"),), Provenance(Origin.USER)),
        ),
    )
    payload_for(panel, settings, Half.DOCK, held)
    assert held.stored["output"]["targets"] == before, "the caller's held manifest must be untouched"
