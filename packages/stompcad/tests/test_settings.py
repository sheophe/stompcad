"""The four ranks, and what each resolved value says about itself."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_a_list_states_its_own_items_rather_than_Python_s_spelling_of_them() -> None:
    """Decision 7: a row is read by a builder, and ``PosixPath`` is not a path."""
    boards = (Path("/project/tar-pcb.stp"), Path("/project/jack.stp"))
    resolved = pick(boards, None, None, ())
    assert resolved.describe() == (
        "/project/tar-pcb.stp, /project/jack.stp, from the command line"
    )


def test_an_artefact_states_both_the_format_and_where_it_goes() -> None:
    """The pair is one row's whole answer, so neither half may be dropped."""
    targets = (("excellon", Path("/project/tar-case.drl")),)
    assert pick(targets, None, None, ()).describe() == (
        "excellon: /project/tar-case.drl, from the command line"
    )


@pytest.mark.parametrize("empty", [(), None, ""])
def test_nothing_reads_as_an_answer_rather_than_as_its_own_spelling(empty: object) -> None:
    """``()``, ``None`` and a blank are one state on screen, so they read alike.

    A row states an answer a builder can act on. Three spellings of the
    absent answer -- one of them invisible -- are three things to learn.
    """
    assert pick(None, None, None, empty).describe() == "none, default"


def test_the_project_agreeing_with_itself_carries_no_disagreement() -> None:
    resolved = pick(0.25, 0.25, None, 0.25)
    assert resolved.project is None
    assert resolved.describe() == "0.25, from the command line"


def test_every_default_matches_the_tool_that_owns_it() -> None:
    """Rank four is both tools' own CLI defaults, read from their parsers.

    A control rather than a restatement: numbers copied into this test
    would agree with themselves forever while the tools moved underneath.
    """
    from stompcad.settings import DEFAULTS
    from stompcollider.cli import build_parser as dock_parser
    from stompdrill.cli import build_parser as drill_parser

    drill = {action.dest: action.default for action in drill_parser()._actions}
    dock = {action.dest: action.default for action in dock_parser()._actions}

    # Every field here is `Resolved[T]`, not `T`: `Resolved` carries no
    # equality against a raw value, so each comparison unwraps `.value`
    # first. `case_face` unwraps twice -- once for `Resolved`, once for
    # `CaseFace` -- to reach the string stompdrill's flag itself uses.
    assert DEFAULTS.artwork.drill_layer.value == drill["drill_layer"]
    assert DEFAULTS.artwork.reference_layer.value == drill["reference_layer"]
    assert DEFAULTS.artwork.form_depth.value == drill["form_depth"]
    assert DEFAULTS.enclosure.case.value is drill["case"]
    assert DEFAULTS.enclosure.case_model.value is drill["case_model"]
    assert DEFAULTS.enclosure.case_face.value.value == drill["case_face"]
    assert DEFAULTS.enclosure.case_margin_mm.value == drill["case_margin"]
    assert DEFAULTS.drilling.grid_mm.value == drill["grid"]
    assert DEFAULTS.drilling.grid_warn_mm.value is drill["grid_warn"]
    assert DEFAULTS.drilling.drill_standard.value == drill["drill_standard"]
    assert DEFAULTS.drilling.drill_sizes.value is drill["drill_sizes"]
    assert DEFAULTS.drilling.no_drill_sizes.value is drill["no_drill_sizes"]
    assert DEFAULTS.drilling.title.value == drill["title"]
    assert DEFAULTS.boards.match_tolerance_mm.value is dock["match_tolerance"]
    # stompcollider's two pitch defaults are strings, parsed later by its own
    # length parser. Comparing floats to them directly would pass never and
    # comparing strings would hide a real change of value, so both sides are
    # floated here and the test says why.
    assert DEFAULTS.boards.seat_pitch_max_mm.value == float(dock["seat_pitch_max"])
    assert DEFAULTS.boards.seat_pitch_min_mm.value == float(dock["seat_pitch_min"])


def test_a_place_reports_each_row_with_its_provenance() -> None:
    from stompcad.settings import Settings

    settings = Settings.of_defaults(Path("tar.ai"))
    rows = {label: stated for _field, label, stated in settings.drilling.rows()}
    assert rows["grid"] == "0.25, default"
    assert rows["drill standard"] == "metric, default"


def test_an_enum_valued_row_describes_the_flag_string_not_the_member_name() -> None:
    """``CaseFace.BOX`` must read as stompdrill's own ``box``, not ``CaseFace.BOX``.

    ``Resolved.describe()`` interpolates ``self.value`` directly; an ``Enum``
    with no custom ``__str__`` would otherwise leak its member name into a row
    that every sibling row states as the flag's own string.
    """
    from stompcad.settings import Settings

    settings = Settings.of_defaults(Path("tar.ai"))
    rows = {label: stated for _field, label, stated in settings.enclosure.rows()}
    assert rows["drilled face"] == "box, default"


def test_settings_name_every_place() -> None:
    from stompcad.settings import Settings

    settings = Settings.of_defaults(Path("tar.ai"))
    assert [place for place, _ in settings.places()] == [
        "artwork",
        "enclosure",
        "drilling",
        "boards",
        "output",
    ]


def test_every_row_names_the_field_it_states() -> None:
    """The workbench joins its own field table to these rows by name, not by position."""
    from stompcad.settings import Settings

    settings = Settings.of_defaults(Path("tar.ai"))
    names = {field for field, _label, _stated in settings.drilling.rows()}
    assert names == {
        "grid_mm", "grid_warn_mm", "drill_standard",
        "drill_sizes", "no_drill_sizes", "title",
    }


def test_the_wall_reference_defaults_to_naming_nothing() -> None:
    """Decision 11: a hole in a wall is irreversible and the panel says nothing
    about it, so the default is the empty expression rather than a glob."""
    from stompcad.settings import DEFAULTS

    assert DEFAULTS.boards.wall_reference.value == ""
    assert DEFAULTS.boards.wall_reference.provenance.origin is Origin.DEFAULT


def test_the_boards_place_states_the_wall_reference_row() -> None:
    from stompcad.settings import DEFAULTS

    rows = {name: shown for name, shown, _stated in DEFAULTS.boards.rows()}
    assert rows["wall_reference"] == "wall references"
