"""The command line drives one composed run over both tools.

``stompcad PANEL.ai`` composes both tools in one invocation, streams its step
log, writes the artefacts either tool would write and exits on the worst
finding either half reported. The two byte-for-byte comparisons are the
acceptance criterion -- an artefact measured against what ``stompdrill``'s
own command line writes from the same inputs, once where a flag declares the
enclosure and once where nothing but the supplied model names it.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import shutil
from pathlib import Path

import pytest
from textual.pilot import Pilot

from stompcad import cli
from stompcad.cancel import EXIT_CANCELLED
from stompcad.workbench.app import Workbench
from stompcad.workbench.session import Phase
from stompdrill import cli as stompdrill_cli
from stompmodel.diagnostics import EXIT_USAGE, EXIT_WARNINGS
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, case_model

__all__: list[str] = []


def _boardless_panel(tmp_path: Path) -> Path:
    """A private copy of the tar fixture, declared to have no boards.

    Copied rather than read in place: the shared fixture must not gain a
    companion project file that every other suite reading it would also
    see. Declaring an empty ``boards`` list is this project's own way of
    confirming the pedal has none, which readiness otherwise has no way to
    tell apart from a directory nobody has looked in yet.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "boards": {"boards": []}}), encoding="utf-8"
    )
    return panel


def test_the_command_line_writes_what_stompdrill_writes_byte_for_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One composed run, and an artefact the orchestrator changed nothing about."""
    panel = _boardless_panel(tmp_path)
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    # stompdrill reads the same copy stompcad does: the excellon header
    # names the panel path it was given, so the two must agree on it for
    # a byte-for-byte comparison to mean anything.
    reference = stompdrill_cli.main([
        str(panel), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])
    mine_code = cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={mine}"])

    assert reference == EXIT_WARNINGS
    assert mine_code == reference, capsys.readouterr().err
    assert mine.read_bytes() == theirs.read_bytes()


def test_the_step_log_streams_as_each_step_completes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec decisions 2 and 11: the same step lines, streamed, with no terminal."""
    panel = _boardless_panel(tmp_path)
    cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={tmp_path / 'out.drl'}"])

    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines() if line.startswith("  ")][:4] == [
        "read", "quantise", "drill", "write",
    ]


def test_a_tie_a_pipe_cannot_answer_exits_3_and_writes_nothing(tmp_path: Path) -> None:
    """The tar footprint ties three parts, and a pipe cannot answer the tie.

    Decision 11: the tie is a question now rather than an error, so a run
    with no terminal to ask on exits with a usage failure naming what was
    missing -- and writes nothing either way.
    """
    panel = _boardless_panel(tmp_path)
    target = tmp_path / "out.drl"

    code = cli.main([str(panel), "--emit", f"excellon={target}"])

    assert code == EXIT_USAGE
    assert not target.exists()


def test_a_gap_with_no_terminal_exits_three_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 11: a pipe cannot answer, so the run says what it needed.

    The tar fixture ties three parts when no case is declared, which is a
    resolvable gap; piped, it must refuse rather than prompt.
    """
    panel = _boardless_panel(tmp_path)
    code = cli.main([str(panel), "--emit", f"excellon={tmp_path / 'out.drl'}"])

    assert code == EXIT_USAGE
    message = capsys.readouterr().err
    assert "1590B" in message, "the refusal does not name the parts it was tied between"


def test_two_targets_naming_one_file_are_a_usage_error(tmp_path: Path) -> None:
    """``check_target_set``: each artefact needs its own path, as both tools require."""
    target = tmp_path / "out.drl"

    code = cli.main([
        str(TAR_AI), "--case", "1590B",
        "--emit", f"excellon={target}", "--emit", f"json={target}",
    ])

    assert code == EXIT_USAGE
    assert not target.exists()


def test_a_board_without_a_panel_reference_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Readiness's rule: no default can guess which components mount to the panel.

    The message is asserted, not only the code: several blockers can share
    this exit, so a test reading the code alone would pass with this
    particular refusal deleted. A case model is supplied so that blocker
    alone is the one under test.
    """
    code = cli.main([
        str(TAR_AI), str(TAR_PCB), "--case", "1590B",
        "--case-model", str(tmp_path / "case.stp"),
    ])

    assert code == EXIT_USAGE
    assert "Tick the components that mount through the panel" in capsys.readouterr().err


def test_a_board_without_a_case_part_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A board is seated in the drilled case, and the part is what names its model.

    Without this refusal the run would open the artwork and stop in the
    enclosure step at ``ambiguous-enclosure``, since this fixture's outline
    ties -- exit 3 either way, because a captured stream cannot answer the
    question that raises, which is why the message is what this asserts.
    """
    code = cli.main([
        str(TAR_AI), str(TAR_PCB), "--panel-reference", PANEL_REFERENCE,
    ])

    assert code == EXIT_USAGE
    assert "Choose the enclosure part" in capsys.readouterr().err


def test_a_captured_stream_is_not_a_terminal() -> None:
    """Decision 15: without a terminal the plain writer runs, and nothing prompts."""
    assert cli.has_terminal(io.StringIO()) is False


def test_a_terminal_gets_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tty, and not a dumb one, is what the workbench needs."""

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    assert cli.has_terminal(_Tty()) is True


def test_a_dumb_terminal_falls_back_to_the_plain_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """TERM=dumb cannot address a cursor, so drawing would corrupt the output."""

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert cli.has_terminal(_Tty()) is False


def test_a_lone_panel_is_discovered(tmp_path: Path) -> None:
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    (tmp_path / "tar.ai").write_bytes(b"")
    resolved = resolve(build_parser().parse_args([]), tmp_path)
    assert resolved.settings.artwork.panel.value == tmp_path / "tar.ai"
    assert resolved.settings.artwork.panel.provenance.origin is Origin.DISCOVERED


def test_several_panels_without_an_argument_is_an_obstacle_and_still_exits_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 6: a state the workbench can show, and the usage code without one."""
    from stompcad.cli import blocked, build_parser, main

    for name in ("a.ai", "b.ai"):
        (tmp_path / name).write_bytes(b"")
    obstacle = blocked(build_parser().parse_args([]), tmp_path).obstacle
    assert obstacle is not None and "a.ai" in obstacle and "b.ai" in obstacle

    monkeypatch.setenv("CI", "true")
    monkeypatch.chdir(tmp_path)
    assert main([]) == EXIT_USAGE
    named = capsys.readouterr().err
    assert "a.ai" in named and "b.ai" in named


def test_no_panel_at_all_is_an_obstacle_and_still_exits_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from stompcad.cli import blocked, build_parser, main

    resolved = blocked(build_parser().parse_args([]), tmp_path)
    assert resolved.obstacle is not None
    assert not resolved.blockers.ready

    monkeypatch.setenv("CI", "true")
    monkeypatch.chdir(tmp_path)
    assert main([]) == EXIT_USAGE
    assert "artwork" in capsys.readouterr().err.lower()


def test_an_argument_beats_the_project_and_says_so(tmp_path: Path) -> None:
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "enclosure": {"case": "1590B"}}), encoding="utf-8"
    )
    resolved = resolve(build_parser().parse_args([str(panel), "--case", "1590BB"]), tmp_path)
    case = resolved.settings.enclosure.case
    assert case.value == "1590BB"
    assert case.provenance.origin is Origin.ARGUMENT
    assert case.describe() == "1590BB, from the command line — the project says 1590B"


def test_a_project_value_contradicted_by_discovery_is_a_finding(tmp_path: Path) -> None:
    """The declaration stands; the disagreement is reported, not resolved."""
    import shutil

    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "artwork": {"drill_layer": "Sparkle"}}), encoding="utf-8"
    )
    resolved = resolve(build_parser().parse_args([str(panel)]), tmp_path)
    layer = resolved.settings.artwork.drill_layer
    assert layer.value == "Sparkle", "a declaration is never silently re-picked"
    assert layer.provenance.origin is Origin.PROJECT
    assert any("Sparkle" in note and "tar.ai" in note for note in resolved.notes)


def test_a_run_that_is_not_ready_is_refused_headlessly(tmp_path: Path) -> None:
    from stompcad.cli import UsageError, build_parser, resolve

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar-pcb.stp").write_bytes(b"")
    resolved = resolve(build_parser().parse_args([str(panel), "--emit", "assembly"]), tmp_path)
    with pytest.raises(UsageError) as failure:
        resolved.require_ready()
    assert "boards" in str(failure.value)


def test_a_bare_emit_takes_its_path_from_the_naming_scheme(tmp_path: Path) -> None:
    from stompcad.cli import build_parser, resolve

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    resolved = resolve(build_parser().parse_args([str(panel), "--emit", "excellon"]), tmp_path)
    assert resolved.settings.output.targets.value == (("excellon", tmp_path / "tar-case.drl"),)


def test_an_argument_names_the_board_among_models_nobody_asked_for(tmp_path: Path) -> None:
    """One named board, and the other model beside it stays where it is.

    The control for the test below: the directory is the same, so an empty
    list there is the absence of a rank rather than an empty directory.
    """
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    for name in ("tar-pcb.stp", "other.stp"):
        (tmp_path / name).write_bytes(b"")
    resolved = resolve(
        build_parser().parse_args([str(panel), str(tmp_path / "other.stp")]), tmp_path
    )
    boards = resolved.settings.boards.boards
    assert boards.value == (tmp_path / "other.stp",)
    assert boards.provenance.origin is Origin.ARGUMENT


def test_models_beside_the_artwork_are_never_docked_unasked(tmp_path: Path) -> None:
    """A STEP file beside the artwork is a candidate to offer, not a board.

    Nothing in a filename says whether a model is a board, an enclosure or
    an assembly somebody exported under a name of their own, so adopting
    the directory would dock whatever happened to be in it. Unresolved is
    the honest state, and it is the one that asks.
    """
    from stompcad.cli import build_parser, resolve
    from stompcad.readiness import Blocker
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    for name in ("tar-pcb.stp", "TarAssembled.stp"):
        (tmp_path / name).write_bytes(b"")
    resolved = resolve(build_parser().parse_args([str(panel)]), tmp_path)
    boards = resolved.settings.boards.boards
    assert boards.value == ()
    assert boards.provenance.origin is Origin.DEFAULT
    assert Blocker.BOARDS_UNRESOLVED in {
        blocker for blocker, _place, _advice in resolved.blockers.blockers
    }


def test_a_case_model_filename_never_becomes_a_declared_case(tmp_path: Path) -> None:
    """A supplied model is a file to read, not a statement about the enclosure.

    ``stompdrill`` treats a model's stem as a guess to try against the
    measurement, and only where a tie is otherwise undeclared. Promoting
    that stem to ``case`` here would hand the same guess in as a
    declaration, which is an error where it disagrees rather than an
    ambiguity a picker can still settle.
    """
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    resolved = resolve(
        build_parser().parse_args([str(panel), "--case-model", str(tmp_path / "1590B.stp")]),
        tmp_path,
    )
    case = resolved.settings.enclosure.case
    assert case.value is None, "a filename was promoted to a declaration"
    assert case.provenance.origin is Origin.DEFAULT


@pytest.mark.hammond
def test_a_model_alone_writes_what_stompdrill_writes_byte_for_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Byte identity on the path where the model, not a flag, names the part.

    The drill document carries both the run's parameters and its
    diagnostics, so it is the artefact that shows a part this half inferred
    being handed to the next run as though it had been declared.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    panel = _boardless_panel(tmp_path)
    here = tmp_path / "1590B.stp"
    shutil.copy(model, here)
    mine, theirs = tmp_path / "mine.json", tmp_path / "theirs.json"

    reference = stompdrill_cli.main([
        str(panel), "--case-model", str(here), "--emit", f"json={theirs}",
    ])
    mine_code = cli.main([str(panel), "--case-model", str(here), "--emit", f"json={mine}"])

    assert mine_code == reference, capsys.readouterr().err
    assert mine.read_bytes() == theirs.read_bytes()


def test_a_malformed_size_list_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md: options are validated before the artwork opens.

    ``discover.layers`` is made to fail loudly if it is ever called; a
    validation ordered after layer discovery would surface that failure
    instead of the usage error under test.
    """
    from stompcad import discover
    from stompcad.cli import UsageError, build_parser, resolve

    def _must_not_be_called(panel: Path) -> tuple[str, ...]:
        raise AssertionError("the artwork must not be opened before options are validated")

    monkeypatch.setattr(discover, "layers", _must_not_be_called)

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "drilling": {"drill_sizes": "nope"}}), encoding="utf-8"
    )
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "drilling.drill_sizes" in str(failure.value)


def test_an_unstocked_drill_standard_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A standard nobody publishes is a usage error, not a ``KeyError`` mid-run."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"drilling": {"drill_standard": "nonsense"}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "drilling.drill_standard" in str(failure.value)


def test_a_size_outside_the_standard_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A size that parses but the table does not hold is refused at the same boundary."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"drilling": {"drill_sizes": "3.77"}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "3.77" in str(failure.value)


def test_a_form_depth_the_reader_rejects_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero levels of nesting is not a depth; the reader says so, this boundary raises it."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"artwork": {"form_depth": 0}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "artwork.form_depth" in str(failure.value)


def test_a_case_the_catalogue_does_not_hold_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project's part number is checked against the catalogue, as a flag's is."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"enclosure": {"case": "nonsense"}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "enclosure.case" in str(failure.value)


def test_a_grid_no_pitch_can_be_spelled_in_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sub-micron fraction of a pitch is what ``SnapPositions`` itself refuses.

    ``stompdrill``'s command line builds that stage before it opens the
    artwork, so the same declaration must fail here rather than as a
    ``ValueError`` from inside a run that has already read the panel.
    """
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"drilling": {"grid_mm": 0.0015}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "drilling.grid_mm" in str(failure.value)


def test_a_negative_grid_warning_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distance no hole can have moved less than is not a threshold."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"drilling": {"grid_warn_mm": -0.5}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "drilling.grid_warn_mm" in str(failure.value)


def test_a_clearance_margin_of_nothing_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md: the margin is refused whether or not a model was supplied."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"enclosure": {"case_margin_mm": 0}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "enclosure.case_margin_mm" in str(failure.value)


def test_a_match_tolerance_of_nothing_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recognition tolerance of nothing pairs no component with any hole."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"boards": {"match_tolerance_mm": 0}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "boards.match_tolerance_mm" in str(failure.value)


def test_a_coarse_seat_step_of_nothing_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scan pitch of nothing describes no scan; the search clamps it to a nanometre."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"boards": {"seat_pitch_max_mm": 0}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "boards.seat_pitch_max_mm" in str(failure.value)


def test_a_negative_fine_seat_step_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finest step is a length like the coarsest, and refused on its own terms."""
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"boards": {"seat_pitch_min_mm": -1}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert "boards.seat_pitch_min_mm" in str(failure.value)


def test_a_coarse_seat_step_finer_than_the_fine_one_is_reported_before_the_artwork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pair is ordered, and each is valid alone: the control is the swap.

    Declared the other way round the same two numbers are the defaults, and
    resolve without complaint, so what this refuses is the ordering rather
    than either value. The control runs before the artwork is barred,
    because a resolution that gets as far as discovery must be allowed to.
    """
    from stompcad.cli import UsageError, build_parser, resolve

    control = tmp_path / "control"
    control.mkdir()
    ordered = _declaring(
        control, {"boards": {"seat_pitch_max_mm": 2.0, "seat_pitch_min_mm": 0.05}}
    )
    resolve(build_parser().parse_args([str(ordered)]), control)

    _never_opens(monkeypatch)
    panel = _declaring(
        tmp_path, {"boards": {"seat_pitch_max_mm": 0.05, "seat_pitch_min_mm": 2.0}}
    )
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    sentence = str(failure.value)
    assert "boards.seat_pitch_max_mm" in sentence
    assert "boards.seat_pitch_min_mm" in sentence
    assert "--seat-pitch" not in sentence, "the refusal names a flag the builder did not type"


def test_a_malformed_panel_reference_is_reported_before_the_artwork_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A designator filter is a typed value, so it is refused where typed values are.

    ``parse_filter`` otherwise first runs over boards already read, which is
    the far side of the drill half's own commit: a stray comma would cost
    the whole run and leave its drill artefacts behind.
    """
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {"boards": {"panel_reference": "RV*,,SW*"}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    sentence = str(failure.value)
    assert "boards.panel_reference" in sentence
    assert "--panel-reference" not in sentence, "the refusal names a flag the builder did not type"


def test_a_malformed_panel_reference_flag_is_refused_as_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This value has a flag as well as a key, so the refusal names the rank that asked.

    The control is the same expression declared in the project above, which
    names the key instead; a fixed prefix would misattribute one of the two.
    """
    from stompcad.cli import UsageError, build_parser, resolve

    _never_opens(monkeypatch)
    panel = _declaring(tmp_path, {})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel), "--panel-reference", "RV*,,SW*"]), tmp_path)
    sentence = str(failure.value)
    assert "--panel-reference" in sentence
    assert "boards.panel_reference" not in sentence, "the refusal names a key nobody edited"


def test_an_unanswered_panel_reference_is_still_a_blocker(tmp_path: Path) -> None:
    """The empty default is "not yet chosen", which readiness reports rather than refuses.

    ``parse_filter("")`` raises, so a check asked about every value would
    turn the workbench's unanswered state into a usage failure and leave the
    readiness matrix nothing to show. The control is the malformed
    expression above, which does refuse.
    """
    from stompcad.cli import build_parser, resolve
    from stompcad.readiness import Blocker

    (tmp_path / "board.stp").write_bytes(b"")
    panel = _declaring(
        tmp_path,
        {"boards": {"boards": ["board.stp"]}, "enclosure": {"case": "1590B"}},
    )
    resolved = resolve(build_parser().parse_args([str(panel)]), tmp_path)

    assert Blocker.NO_PANEL_REFERENCE in {
        blocker for blocker, _place, _sentence in resolved.blockers.blockers
    }


def test_a_declared_face_is_normalised_as_stompdrill_normalises_it(tmp_path: Path) -> None:
    """``stompdrill`` strips and lowers what its own flag is handed; so does this key.

    A second reading of the same word would accept a spelling here that
    ``--case-face`` refuses, or refuse one it accepts.
    """
    from stompcad.cli import build_parser, resolve
    from stompmodel.model import CaseFace

    panel = _declaring(tmp_path, {"enclosure": {"case_face": " Box"}})
    resolved = resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert resolved.settings.enclosure.case_face.value is CaseFace.BOX


def test_a_face_outside_the_two_names_the_project_key(tmp_path: Path) -> None:
    """``parse_face`` names its own flag; this rank restates the key instead."""
    from stompcad.cli import UsageError, build_parser, resolve

    panel = _declaring(tmp_path, {"enclosure": {"case_face": "side"}})
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([str(panel)]), tmp_path)
    sentence = str(failure.value)
    assert "enclosure.case_face" in sentence
    assert "--case-face" not in sentence, "the refusal names a flag this command line has not got"


def test_a_declared_case_reaches_the_run_as_the_catalogue_spells_it(tmp_path: Path) -> None:
    """``stompdrill`` normalises what it is handed; a second spelling is a second answer."""
    from stompcad.cli import build_parser, resolve

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    resolved = resolve(build_parser().parse_args([str(panel), "--case", "1590b"]), tmp_path)
    assert resolved.settings.enclosure.case.value == "1590B"


def _declaring(tmp_path: Path, declared: dict[str, object]) -> Path:
    """A panel whose project file declares exactly what a test is about."""
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, **declared}), encoding="utf-8"
    )
    return panel


def _never_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make layer discovery fail loudly, so a late validation cannot pass as an early one."""
    from stompcad import discover

    def _must_not_be_called(panel: Path) -> tuple[str, ...]:
        raise AssertionError("the artwork must not be opened before options are validated")

    monkeypatch.setattr(discover, "layers", _must_not_be_called)


def _tar_project(tmp_path: Path, model: Path) -> Path:
    """A private copy of the whole fixture: the panel, its board, the case model.

    Copied rather than read in place, because both runs below fill the gaps
    in a project file beside the artwork, and the shared fixture must not
    gain one that every other suite reading it would also see.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    shutil.copy(TAR_PCB, tmp_path / "tar-pcb.stp")
    shutil.copy(model, tmp_path / "1590B.stp")
    return panel


def _args(panel: Path) -> argparse.Namespace:
    """One invocation naming everything a drilled and docked run needs."""
    return cli.build_parser().parse_args([
        str(panel),
        str(panel.with_name("tar-pcb.stp")),
        "--case", "1590B",
        "--case-model", str(panel.with_name("1590B.stp")),
        "--panel-reference", PANEL_REFERENCE,
        "--emit", f"excellon={panel.with_name('out.drl')}",
        "--emit", f"report={panel.with_name('report.json')}",
    ])


def _workbench_over(panel: Path) -> Workbench:
    """The application that same invocation opens, over that same project."""
    return cli._workbench_for(_args(panel), panel.parent)


async def _settled(pilot: Pilot[int], app: Workbench) -> None:
    """Wait for the run to end, however long the kernel holds its worker.

    Bounded by the caller's own alarm rather than by a count chosen here: a
    real drill and dock is minutes of work, and a number measured against
    one machine's clock is a guess about every other machine's.
    """
    while app.session.phase is Phase.RUNNING:
        await pilot.pause()
        await asyncio.sleep(0.05)


@pytest.mark.boards
@pytest.mark.hammond
@pytest.mark.asyncio
async def test_the_workbench_s_exit_lines_are_the_pipe_s_bytes(tmp_path: Path) -> None:
    """Decision 15: a run leaves its record behind either way.

    The same invocation, run twice over one project: once through the plain
    writer, once through the workbench, whose settled lines are written out
    as it exits. The comparison is the bytes, because "the same lines" is
    only a claim until the padding and the order are compared too.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    piped = io.StringIO()
    project = _tar_project(tmp_path, model)
    code = cli._run(_args(project), piped)
    # The tar boards interfere, and a clash is stompcollider's deliverable
    # rather than a broken run: what this needs is a run that happened, so
    # the code is held to the two that mean it did not.
    assert code not in (EXIT_USAGE, EXIT_CANCELLED), piped.getvalue()
    assert (tmp_path / "out.drl").is_file()

    app = _workbench_over(project)
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settled(pilot, app)

    assert app.failure is None
    assert app.session.phase is Phase.DONE
    assert "\n".join(app.settled) + "\n" == piped.getvalue()
    assert app.session.exit_code == code, "one run, two presentations, two statuses"


def test_an_unreadable_wall_reference_in_the_project_is_a_usage_error(
    tmp_path: Path,
) -> None:
    """The grammar is stompcollider's and is first asked over boards already
    read -- on the far side of the drill half's commit -- so it is checked
    here, naming the row that holds it."""
    from stompcad.cli import UsageError, build_parser, resolve

    panel = _declaring(tmp_path, {"boards": {"wall_reference": "J((("}})
    with pytest.raises(UsageError, match=r"boards\.wall_reference"):
        resolve(build_parser().parse_args([str(panel)]), tmp_path)


def test_a_wall_reference_naming_nothing_is_not_a_usage_error(tmp_path: Path) -> None:
    """The control: a valid expression that matches no part is a finding at
    run time, never a refusal before anything is opened."""
    from stompcad.cli import build_parser, resolve

    panel = _declaring(tmp_path, {"boards": {"wall_reference": "NOPE*"}})
    resolved = resolve(build_parser().parse_args([str(panel)]), tmp_path)
    assert resolved.settings.boards.wall_reference.value == "NOPE*"


#: The tar panel drills no hole wide enough for SW2, so admitting both switches
#: leaves a board with no correspondence, an error that withholds the model
#: artefacts. Leaving SW2 out reduces that to a warning, so a run reaches them.
_WARNING_ONLY_PANEL_REFERENCE = f"{PANEL_REFERENCE},!SW2"


@pytest.mark.hammond
@pytest.mark.boards
def test_a_run_that_names_no_wall_part_writes_what_it_always_wrote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default wall expression is empty, so a run that asks for no wall
    describes only the face and leaves no sibling file for a surface nothing
    was cut in."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    panel = _tar_project(tmp_path, model)
    code = cli.main([
        str(panel), str(panel.with_name("tar-pcb.stp")), "--case", "1590B",
        "--case-model", str(panel.with_name("1590B.stp")),
        "--panel-reference", _WARNING_ONLY_PANEL_REFERENCE,
        "--emit", f"json={tmp_path / 'p.json'}",
        "--emit", f"step={tmp_path / 'p.stp'}",
        "--emit", f"excellon={tmp_path / 'p.drl'}",
    ])

    assert code in (0, 1), capsys.readouterr().out
    document = json.loads((tmp_path / "p.json").read_text())
    assert [surface["key"] for surface in document["surfaces"]] == ["face"]
    # Named exactly, so a new artefact has to be accounted for.
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == [
        "1590B.stp", "p.drl", "p.json", "p.stp", "tar-pcb.stp", "tar.ai",
        "tar.stompcad.json",
    ]


@pytest.mark.hammond
@pytest.mark.boards
def test_the_panel_s_own_artefacts_land_before_the_walls_are_cut(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dock-half failure still leaves a builder the files to drill the panel
    with, checked by the order the two commits report."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    panel = _tar_project(tmp_path, model)
    cli.main([
        str(panel), str(panel.with_name("tar-pcb.stp")), "--case", "1590B",
        "--case-model", str(panel.with_name("1590B.stp")),
        "--panel-reference", _WARNING_ONLY_PANEL_REFERENCE,
        "--emit", f"excellon={tmp_path / 'p.drl'}",
        "--emit", f"json={tmp_path / 'p.json'}",
    ])
    printed = capsys.readouterr().out
    assert printed.index("p.drl") < printed.index("p.json")
    assert printed.index("write case") < printed.index("drill walls") < printed.index("write model")
