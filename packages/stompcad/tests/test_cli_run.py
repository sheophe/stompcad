"""The command line drives the run: the plan's goal sentence, tested.

``stompcad PANEL.ai`` composes both tools in one invocation, streams its step
log, writes the artefacts either tool would write and exits on the worst
finding either half reported. The first test is the acceptance criterion --
the artefact compared, byte for byte, against what ``stompdrill``'s own
command line writes from the same inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad import cli
from stompdrill import cli as stompdrill_cli
from stompmodel.diagnostics import EXIT_ERRORS, EXIT_USAGE, EXIT_WARNINGS
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB

__all__: list[str] = []


def test_the_command_line_writes_what_stompdrill_writes_byte_for_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One composed run, and an artefact the orchestrator changed nothing about."""
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    reference = stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])
    mine_code = cli.main([str(TAR_AI), "--case", "1590B", "--emit", f"excellon={mine}"])

    assert reference == EXIT_WARNINGS
    assert mine_code == reference, capsys.readouterr().err
    assert mine.read_bytes() == theirs.read_bytes()


def test_the_step_log_streams_as_each_step_completes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec decisions 2 and 11: the same step lines, streamed, with no terminal."""
    cli.main([str(TAR_AI), "--case", "1590B", "--emit", f"excellon={tmp_path / 'out.drl'}"])

    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines() if line.startswith("  ")][:4] == [
        "read", "quantise", "drill", "write",
    ]


def test_an_errored_run_exits_2_and_writes_nothing(tmp_path: Path) -> None:
    """The tar footprint matches three parts, so no declared case is an error."""
    target = tmp_path / "out.drl"

    code = cli.main([str(TAR_AI), "--emit", f"excellon={target}"])

    assert code == EXIT_ERRORS
    assert not target.exists()


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
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stompcollider's rule: the flag has no default, because a default would be a guess.

    The message is asserted, not only the code: three separate failures on
    this invocation exit 3, so a test reading the code alone would pass with
    this refusal deleted.
    """
    code = cli.main([str(TAR_AI), str(TAR_PCB), "--case", "1590B"])

    assert code == EXIT_USAGE
    assert "--panel-reference is required to dock a board" in capsys.readouterr().err


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
    assert "--case-model is required to dock a board" in capsys.readouterr().err
