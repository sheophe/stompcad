"""The command line drives the run: the plan's goal sentence, tested.

``stompcad PANEL.ai`` composes both tools in one invocation, streams its step
log, writes the artefacts either tool would write and exits on the worst
finding either half reported. The first test is the acceptance criterion --
the artefact compared, byte for byte, against what ``stompdrill``'s own
command line writes from the same inputs.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from stompcad import cli
from stompdrill import cli as stompdrill_cli
from stompmodel.diagnostics import EXIT_USAGE, EXIT_WARNINGS
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB

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


def test_a_board_without_a_case_model_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A board is seated in the drilled case, so there must be one to seat it in.

    Without this refusal the run reaches the ``step`` emitter and fails
    there, deep inside the dock half's own read -- exit 3 either way, which
    is why the message is what this asserts.
    """
    code = cli.main([
        str(TAR_AI), str(TAR_PCB), "--case", "1590B", "--panel-reference", PANEL_REFERENCE,
    ])

    assert code == EXIT_USAGE
    assert "Choose the enclosure model the boards are seated in" in capsys.readouterr().err


def test_a_captured_stream_is_not_a_terminal() -> None:
    """Decision 11: without a terminal the plain writer runs, and nothing prompts."""
    assert cli.choose_presentation(io.StringIO()) is False


def test_a_terminal_gets_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tty, and not a dumb one, is what the inline app needs."""

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setenv("TERM", "xterm")
    assert cli.choose_presentation(_Tty()) is True


def test_a_dumb_terminal_falls_back_to_the_plain_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """TERM=dumb cannot address a cursor, so drawing would corrupt the output."""

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setenv("TERM", "dumb")
    assert cli.choose_presentation(_Tty()) is False


def test_a_lone_panel_is_discovered(tmp_path: Path) -> None:
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    (tmp_path / "tar.ai").write_bytes(b"")
    resolved = resolve(build_parser().parse_args([]), tmp_path)
    assert resolved.settings.artwork.panel.value == tmp_path / "tar.ai"
    assert resolved.settings.artwork.panel.provenance.origin is Origin.DISCOVERED


def test_several_panels_without_an_argument_is_a_usage_failure(tmp_path: Path) -> None:
    from stompcad.cli import UsageError, build_parser, resolve

    for name in ("a.ai", "b.ai"):
        (tmp_path / name).write_bytes(b"")
    with pytest.raises(UsageError) as failure:
        resolve(build_parser().parse_args([]), tmp_path)
    assert "a.ai" in str(failure.value) and "b.ai" in str(failure.value)


def test_no_panel_at_all_is_a_usage_failure(tmp_path: Path) -> None:
    from stompcad.cli import UsageError, build_parser, resolve

    with pytest.raises(UsageError):
        resolve(build_parser().parse_args([]), tmp_path)


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


def test_an_argument_beats_a_conflicting_discovery(tmp_path: Path) -> None:
    """The rank a bare flag reaches is stronger than a filename's own guess.

    ``--case-model``'s stem names a real catalogue part, so ``case`` would
    be discovered as ``1590B`` if nothing outranked it; ``--case`` still
    wins over that discovery, the pair no other test here exercises.
    """
    from stompcad.cli import build_parser, resolve
    from stompcad.settings import Origin

    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    resolved = resolve(
        build_parser().parse_args([
            str(panel), "--case", "1590BB", "--case-model", str(tmp_path / "1590B.stp"),
        ]),
        tmp_path,
    )
    case = resolved.settings.enclosure.case
    assert case.value == "1590BB"
    assert case.provenance.origin is Origin.ARGUMENT
