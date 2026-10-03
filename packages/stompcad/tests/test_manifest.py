"""The project file: what it holds, what it refuses, and what it ignores."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad import manifest
from stompcad.settings import Origin, Provenance, Resolved, Settings
from stompdrill.emitters import available


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    panel = tmp_path / "tar.ai"
    (tmp_path / "tar.stompcad.json").write_text(json.dumps(payload), encoding="utf-8")
    return panel


def _settings_with_no_boards(panel: Path) -> Settings:
    """Defaults with the empty board list recorded as an answer, not a default."""
    settings = Settings.of_defaults(panel)
    return replace(
        settings,
        boards=replace(settings.boards, boards=Resolved((), Provenance(Origin.PROJECT))),
    )


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
    written = json.loads(payload_for(panel, settings, Half.MODEL, manifest.Manifest()) or "{}")
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
    written = json.loads(payload_for(panel, Settings.of_defaults(panel), Half.MODEL, held) or "{}")
    assert written["drilling"]["grid_mm"] == 0.5, "a declaration is never overwritten by a run"


def test_nothing_to_fill_stages_nothing(tmp_path: Path) -> None:
    """A run that adds no declaration must not rewrite the file it read."""
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    settings = Settings.of_defaults(panel)
    first = payload_for(panel, settings, Half.MODEL, manifest.Manifest())
    assert first is not None
    (tmp_path / "tar.stompcad.json").write_text(first, encoding="utf-8")
    assert payload_for(panel, settings, Half.MODEL, manifest.read(panel)) is None


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
        text = payload_for(panel, settings, Half.MODEL, manifest.Manifest())
        assert text is not None
        (tmp_path / "tar.stompcad.json").write_text(text, encoding="utf-8")
        back = manifest.read(panel).values["drilling"]["grid_mm"]
        assert nm_from_mm(back) == nm_from_mm(millimetres), millimetres


def test_the_schema_covers_every_field_a_place_carries() -> None:
    """A field added to settings without a row in PLACES is never remembered.

    ``panel`` names the manifest, and ``case_model`` is resolved from the
    command line alone, so the project file has nothing to declare for
    either.
    """
    from dataclasses import fields

    from stompcad.manifest import PLACES
    from stompcad.settings import DEFAULTS

    resolved_elsewhere = {"artwork": {"panel"}, "enclosure": {"case_model"}}

    for place, allowed in PLACES.items():
        carried = {field.name for field in fields(getattr(DEFAULTS, place))}
        assert allowed <= carried, f"{place}: schema names a field settings does not carry"
        exempt: set[str] = resolved_elsewhere.get(place, set())
        assert carried - allowed <= exempt, (
            f"{place}: settings carries a field the schema forgets"
        )


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
    written = json.loads(payload_for(panel, settings, Half.MODEL, held) or "{}")
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
    first = payload_for(panel, drill_settings, Half.MODEL, manifest.Manifest())
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


def test_an_unknown_key_survives_being_read_and_written_back(tmp_path: Path) -> None:
    """A key this build does not know is ignored on the way in, never deleted.

    An additive version bump only works if an older build can open a newer
    file, run, fill its own gaps and leave the file still readable by the
    build that wrote it. Filtering the unknown key out of the payload as
    well as out of the values would make every bump destructive.
    """
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = _write(tmp_path, {"version": 1, "drilling": {"grid_mm": 0.5, "wobble": 3}})
    held = manifest.read(panel)
    assert held.values["drilling"] == {"grid_mm": 0.5}, "the run must not resolve from an unknown key"

    written = json.loads(payload_for(panel, Settings.of_defaults(panel), Half.MODEL, held) or "{}")
    assert written["drilling"]["wobble"] == 3
    assert written["drilling"]["grid_mm"] == 0.5


def test_an_unknown_section_survives_being_read_and_written_back(tmp_path: Path) -> None:
    """A whole place a later version added is carried, for the same reason a key is."""
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = _write(tmp_path, {"version": 1, "sparkle": {"x": 1}})
    held = manifest.read(panel)
    assert "sparkle" not in held.values

    written = json.loads(payload_for(panel, Settings.of_defaults(panel), Half.MODEL, held) or "{}")
    assert written["sparkle"] == {"x": 1}


@pytest.mark.parametrize(
    ("place", "key", "declared"),
    [
        ("output", "targets", "x.out"),
        ("output", "targets", ["a", "b"]),
        ("output", "targets", {"excellon": 3}),
        ("boards", "boards", "tar-pcb.stp"),
        ("boards", "boards", [1, 2]),
        ("boards", "panel_reference", ["RV*"]),
        ("boards", "wall_reference", ["J1"]),
        ("drilling", "grid_mm", "abc"),
        ("drilling", "grid_mm", None),
        ("drilling", "title", 7),
        ("drilling", "drill_sizes", 3.2),
        ("artwork", "form_depth", "deep"),
        ("artwork", "form_depth", 1.5),
        ("artwork", "drill_layer", None),
        ("enclosure", "case", ["1590B"]),
        ("enclosure", "case_margin_mm", "1"),
    ],
)
def test_a_known_key_of_the_wrong_shape_is_refused(
    tmp_path: Path, place: str, key: str, declared: object,
) -> None:
    """A hand-authored value reaching the run as the wrong type is a usage failure.

    The sentence has to serve someone editing JSON in a text editor, so it
    names the file, the place, the key and the shape that key holds.
    """
    panel = _write(tmp_path, {"version": 1, place: {key: declared}})
    with pytest.raises(manifest.ManifestError) as failure:
        manifest.read(panel)
    sentence = str(failure.value)
    assert "tar.stompcad.json" in sentence
    assert f"{place}.{key}" in sentence


def test_a_true_is_refused_where_a_number_is_expected(tmp_path: Path) -> None:
    """``bool`` subclasses ``int``; a project that says ``true`` did not say one."""
    panel = _write(tmp_path, {"version": 1, "artwork": {"form_depth": True}})
    with pytest.raises(manifest.ManifestError) as failure:
        manifest.read(panel)
    assert "artwork.form_depth" in str(failure.value)


def test_a_nullable_key_still_accepts_null(tmp_path: Path) -> None:
    """The fields a run leaves unset are written as ``null`` and must read back."""
    panel = _write(tmp_path, {
        "version": 1,
        "enclosure": {"case": None},
        "drilling": {"grid_warn_mm": None, "drill_sizes": None, "no_drill_sizes": None},
        "boards": {"match_tolerance_mm": None},
    })
    read = manifest.read(panel)
    assert read.values["enclosure"]["case"] is None
    assert read.values["drilling"]["grid_warn_mm"] is None


def test_an_integer_is_a_number_where_a_number_is_wanted(tmp_path: Path) -> None:
    """JSON writes ``1`` for a whole millimetre; that is a number, not a mistake."""
    panel = _write(tmp_path, {"version": 1, "drilling": {"grid_mm": 1}})
    assert manifest.read(panel).values["drilling"]["grid_mm"] == 1


def test_an_unknown_key_of_any_shape_is_still_only_a_note(tmp_path: Path) -> None:
    """The control: shape checking reaches known keys, and no others.

    An unknown key has no declared shape to be wrong against, and refusing
    one would make every version bump destructive.
    """
    panel = _write(tmp_path, {"version": 1, "drilling": {"wobble": ["anything", 3, None]}})
    read = manifest.read(panel)
    assert "drilling" not in read.values
    assert read.stored["drilling"]["wobble"] == ["anything", 3, None]
    assert any("wobble" in note for note in read.notes)


def test_every_schema_key_declares_a_shape() -> None:
    """A key in one table and not the other is a key nothing checks.

    The count is the second half of the same invariant: one shape row per
    declared key holds only while no two places spell a key name the same,
    and comparing flattened sets alone cannot see the day that changes.
    """
    from stompcad.manifest import _SHAPES

    declared = {key for keys in manifest.PLACES.values() for key in keys}
    assert set(_SHAPES) == declared, "the schema and the shape table must name the same keys"
    assert sum(len(keys) for keys in manifest.PLACES.values()) == len(declared), (
        "the shape table is keyed by name alone, so two places spelling one key "
        "the same way would share a single row"
    )


@pytest.mark.parametrize("half_name", ["MODEL", "DOCK"])
def test_what_a_half_writes_is_what_the_reader_accepts(tmp_path: Path, half_name: str) -> None:
    """The shapes are the file's own: a payload this tool wrote must read back."""
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import Settings

    panel = tmp_path / "tar.ai"
    text = payload_for(panel, Settings.of_defaults(panel), Half[half_name], manifest.Manifest())
    assert text is not None
    (tmp_path / "tar.stompcad.json").write_text(text, encoding="utf-8")
    manifest.read(panel)


def test_a_run_with_no_boards_records_the_empty_list_that_decided_it(tmp_path: Path) -> None:
    """Decision 17: the confirmed empty list is declared intent and must be remembered.

    A drill-only run has no dock half, so the drill half's commit is the
    only commit it has. Recording nothing would ask the question again
    every time the project opened.
    """
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "tar.ai"
    settings = _settings_with_no_boards(panel)
    written = json.loads(payload_for(panel, settings, Half.DRILL_ONLY, manifest.Manifest()) or "{}")
    assert written["boards"]["boards"] == []
    assert "artwork" in written and "enclosure" in written


def test_the_model_commit_of_a_docking_run_still_declares_no_board(tmp_path: Path) -> None:
    """The control: the dock half owns `boards` whenever there is a dock half."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "tar.ai"
    written = json.loads(
        payload_for(panel, Settings.of_defaults(panel), Half.MODEL, manifest.Manifest()) or "{}"
    )
    assert "boards" not in written


def test_every_half_names_places_that_exist() -> None:
    """The structural guard: a half added without a row declares nothing."""
    from stompcad.manifest import _HALF_PLACES, PLACES, Half

    assert set(_HALF_PLACES) == {half.value for half in Half}
    for places in _HALF_PLACES.values():
        assert set(places) <= set(PLACES)


def _settings_with_targets(panel: Path, *names: str) -> Settings:
    """Defaults, with one made-up path per requested format, as a user typed them."""
    settings = Settings.of_defaults(panel)
    return replace(
        settings,
        output=replace(
            settings.output,
            targets=Resolved(
                tuple((name, panel.parent / f"tar.{name}") for name in names),
                Provenance(Origin.USER),
            ),
        ),
    )


def test_the_model_commit_declares_only_its_own_target_formats(tmp_path: Path) -> None:
    """Decision 8: ``write case`` must not name a file only ``write assembly`` commits."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "tar.ai"
    settings = _settings_with_targets(panel, "json", "report", "assembly")
    written = json.loads(payload_for(panel, settings, Half.MODEL, manifest.Manifest()) or "{}")
    assert set(written["output"]["targets"]) == {"json"}


def test_a_dock_half_declares_only_its_own_target_formats(tmp_path: Path) -> None:
    """The control: the dock half's own two formats, never a format the drill half rendered."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "tar.ai"
    settings = _settings_with_targets(panel, "json", "report", "assembly")
    written = json.loads(payload_for(panel, settings, Half.DOCK, manifest.Manifest()) or "{}")
    assert set(written["output"]["targets"]) == {"report", "assembly"}


def test_no_format_name_belongs_to_both_halves() -> None:
    """The premise the two tests above rest on: a name identifies one half.

    ``payload_for`` attributes a target by asking whether the dock half
    names it, which is only an attribution while the two sets are disjoint.
    An overlap would let the drill half declare a file ``write assembly``
    has not committed yet, which is the one thing decision 8 forbids.
    """
    from stompdrill.emitters import available

    assert not frozenset(available()) & manifest.DOCK_TARGET_NAMES


def test_the_model_formats_are_real_emitters_and_never_the_dock_halfs() -> None:
    """The premise ``write case`` and ``write model`` rest on: a name here is a
    format that exists. A renamed emitter would turn the drill half's
    ``owned -= MODEL_TARGET_NAMES`` and ``_targets_for`` into silent no-ops,
    and a boards run would again write the document before the walls are cut.
    """
    assert manifest.MODEL_TARGET_NAMES <= frozenset(available())
    assert not manifest.MODEL_TARGET_NAMES & manifest.DOCK_TARGET_NAMES


def test_a_project_declaring_a_case_model_is_told_it_is_no_longer_read(tmp_path: Path) -> None:
    """Told once, and kept in the file: refusing to resolve from a key is not
    a reason to delete it."""
    panel = _write(
        tmp_path, {"version": 1, "enclosure": {"case": "1590B", "case_model": "1590B.stp"}}
    )
    read_back = manifest.read(panel)
    assert read_back.values["enclosure"] == {"case": "1590B"}
    assert any("case_model" in note for note in read_back.notes)
    assert read_back.stored["enclosure"]["case_model"] == "1590B.stp"


@pytest.mark.parametrize("expression", ["J1", ""])
def test_a_wall_reference_survives_a_run_with_no_boards(tmp_path: Path, expression: str) -> None:
    """Every step that reads it is pruned on such a run, so only the file carries it.

    Empty is the decided value, not an absent one: it must come back as ``""``
    and resolve from the project rank rather than fall through to the default.
    """
    from stompcad.manifest import Half, payload_for
    from stompcad.settings import pick

    panel = tmp_path / "tar.ai"
    base = _settings_with_no_boards(panel)
    settings = replace(
        base,
        boards=replace(
            base.boards, wall_reference=Resolved(expression, Provenance(Origin.USER))
        ),
    )
    written = payload_for(panel, settings, Half.DOCK, manifest.Manifest())
    assert written is not None
    manifest.manifest_path(panel).write_text(written, encoding="utf-8")
    stored = manifest.read(panel).values["boards"]["wall_reference"]
    assert stored == expression
    assert pick(None, stored, None, "default").provenance.origin is Origin.PROJECT


def test_the_drill_half_s_panel_commit_declares_nothing(tmp_path: Path) -> None:
    """Decision 16: the declaration joins the *last* drill-half commit, and with
    boards that is the model's. Declaring here would name a file the model
    commit has not reached yet."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "p.ai"
    settings = _settings_with_targets(panel, "excellon")
    assert payload_for(panel, settings, Half.DRILL, manifest.Manifest()) is None


def test_the_model_commit_declares_every_drill_half_format(tmp_path: Path) -> None:
    """By the time it runs, the panel's own files are on disk too, so it is the
    only commit that can name all of them."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "p.ai"
    settings = _settings_with_targets(panel, "excellon", "json", "report")
    stored = json.loads(payload_for(panel, settings, Half.MODEL, manifest.Manifest()) or "{}")
    assert set(stored["output"]["targets"]) == {"excellon", "json"}
    assert "drilling" in stored and "boards" not in stored


def test_a_drill_only_run_still_declares_everything_in_one_commit(tmp_path: Path) -> None:
    """The regression guard: with no boards there is no model commit, so the
    panel commit is the last one and keeps the behaviour it has today."""
    from stompcad.manifest import Half, payload_for

    panel = tmp_path / "p.ai"
    settings = _settings_with_targets(panel, "excellon")
    stored = json.loads(
        payload_for(panel, settings, Half.DRILL_ONLY, manifest.Manifest()) or "{}"
    )
    assert set(stored["output"]["targets"]) == {"excellon"}
    assert {"artwork", "enclosure", "drilling", "boards"} <= set(stored)
