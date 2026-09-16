"""The orchestrator's own surface: no kernel import, and a clean ``--help``.

``stompcad`` composes ``stompdrill`` and ``stompcollider`` as libraries; it
computes no geometry of its own, so it has no business importing OCP or
``stompgeom`` directly. The fixture-resolution test guards the paths every
later task's conftest fixtures depend on, so a moved fixture fails here
rather than inside a three-minute dock test.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
from pathlib import Path

import pytest

from stompcad import cli
from stompcad.cancel import EXIT_CANCELLED
from stompmodel.diagnostics import EXIT_USAGE
from tests.conftest import TAR_AI, TAR_PCB

__all__: list[str] = []


class _AlwaysATerminal:
    """Stands in for ``out`` so ``has_terminal`` sees a tty without one."""

    def isatty(self) -> bool:
        return True


def _imported_roots(source: Path) -> set[str]:
    """Every top-level package name imported anywhere under ``source``.

    Parsed rather than grepped: a raw text scan cannot tell an import from
    a docstring naming the kernel, so it silently forbids the prose that
    explains why a module does not import one.
    """
    roots: set[str] = set()
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_package_imports_no_kernel() -> None:
    """Spec constraint: stompcad computes no geometry and never imports OCP."""
    import stompcad

    roots = _imported_roots(Path(stompcad.__file__).parent)
    assert {"OCP", "stompgeom"} & roots == set()


def test_help_exits_clean() -> None:
    assert cli.main(["--help"]) == 0


def test_the_fixtures_are_where_the_tests_expect() -> None:
    assert TAR_AI.is_file()
    assert TAR_PCB.is_file()


def test_an_unknown_emit_format_is_a_usage_error() -> None:
    """CLAUDE.md: an unrecognised target is invalid input, not a silent no-op."""
    code = cli.main([str(TAR_AI), "--emit", "bogus=out.bin"])
    assert code == EXIT_USAGE


def test_validate_targets_reports_every_bad_name_together(capsys: pytest.CaptureFixture[str]) -> None:
    """CLAUDE.md: 'Validate all requested targets together', not one round trip each."""
    code = cli.main([
        str(TAR_AI), "--emit", "bogus=a.bin", "--emit", "alsobogus=b.bin",
    ])
    assert code == EXIT_USAGE
    error = capsys.readouterr().err
    assert "bogus" in error
    assert "alsobogus" in error


def test_a_bad_target_leaves_a_good_target_unwritten(tmp_path: Path) -> None:
    """Validation happens before rendering, so a bad name spoils the good one too.

    The control is the point: the same invocation without the bad name does
    write that artefact, so the assertion below is about validation rather
    than about a command line that writes nothing whatever it is asked. A
    declared empty ``boards`` confirms the pedal has none, on a private copy
    of the fixture so the declaration cannot leak into another suite reading
    the shared one.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "boards": {"boards": []}}), encoding="utf-8"
    )
    good, control = tmp_path / "good.drl", tmp_path / "control.drl"
    assert cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={control}"]) != EXIT_USAGE
    assert control.is_file(), "the control wrote nothing; the assertion below proves nothing"

    code = cli.main([
        str(panel), "--case", "1590B", "--emit", f"excellon={good}", "--emit", "bogus=bad.bin",
    ])

    assert code == EXIT_USAGE
    assert not good.exists()


def test_parse_emit_accepts_a_bare_format() -> None:
    """The optional path form: a known format takes its name from the panel."""
    assert cli.parse_emit("excellon", TAR_AI) == (
        "excellon", TAR_AI.with_name(f"{TAR_AI.stem}-case.drl"),
    )


def test_parse_emit_rejects_a_spec_with_no_format_name() -> None:
    with pytest.raises(cli.UsageError):
        cli.parse_emit("=out.bin", TAR_AI)


def test_parse_emit_rejects_a_spec_with_an_empty_path() -> None:
    with pytest.raises(cli.UsageError):
        cli.parse_emit("excellon=", TAR_AI)


def test_a_keyboard_interrupt_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec decision 9: an interrupt stops the run exactly as ``q`` does.

    Docs/CLI.md documents 130 as reachable by a signal; nothing under
    ``main`` used to catch ``KeyboardInterrupt``, so a headless Ctrl-C
    escaped as a traceback instead.
    """

    def raises_interrupt(args: object, out: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", raises_interrupt)
    assert cli.main([str(TAR_AI)]) == EXIT_CANCELLED


def test_a_project_target_set_is_checked_like_a_flag_one(tmp_path: Path) -> None:
    """Two artefacts naming one file are refused wherever the pair came from.

    ``--emit`` is not the only rank that supplies targets, and the rollback
    both tools stage their writes through assumes each artefact owns its
    own path. A run that is otherwise able to finish is the control: what
    is under test is the refusal, not an invocation that fails anyway.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    target = tmp_path / "x.out"
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({
            "version": 1,
            "boards": {"boards": []},
            "enclosure": {"case": "1590B"},
            "output": {"targets": {"excellon": "x.out", "json": "x.out"}},
        }),
        encoding="utf-8",
    )

    code = cli.main([str(panel)])

    assert code == EXIT_USAGE
    assert not target.exists(), "one file on disk under two claims of having written it"


def test_a_project_target_this_build_cannot_render_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown format is named, not dropped, whichever rank asked for it.

    Each write step filters to the formats its own half owns, so a name
    outside their union is written by neither -- silently, unless it is
    rejected before the run starts.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({
            "version": 1,
            "boards": {"boards": []},
            "enclosure": {"case": "1590B"},
            "output": {"targets": {"bogus": "a.out", "excellon": "b.drl"}},
        }),
        encoding="utf-8",
    )

    code = cli.main([str(panel)])

    assert code == EXIT_USAGE
    error = capsys.readouterr().err
    assert "bogus" in error
    assert "output.targets" in error, "the refusal names a flag the builder did not type"
    assert not (tmp_path / "b.drl").exists(), "a bad name must spoil the good one too"


def test_a_malformed_project_value_is_refused_before_the_artwork_is_opened(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """CLAUDE.md: options are validated before the artwork is opened.

    A grid the project spells as text is only a number when something tries
    to scale it, which is several steps into a run that has already read the
    panel. The control is the same invocation with a number, which writes
    the artefact this one must not reach.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    project = tmp_path / "tar.stompcad.json"
    good, refused = tmp_path / "good.drl", tmp_path / "refused.drl"

    project.write_text(
        json.dumps({"version": 1, "boards": {"boards": []}, "drilling": {"grid_mm": 0.25}}),
        encoding="utf-8",
    )
    assert cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={good}"]) != EXIT_USAGE
    assert good.is_file(), "the control wrote nothing; the assertion below proves nothing"
    capsys.readouterr()

    project.write_text(
        json.dumps({"version": 1, "boards": {"boards": []}, "drilling": {"grid_mm": "abc"}}),
        encoding="utf-8",
    )
    code = cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={refused}"])

    printed = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "drilling.grid_mm" in printed.err
    assert "read panel" not in printed.out, "the artwork was opened before the value was checked"
    assert not refused.exists()


def test_every_configuration_place_is_checked_after_an_edit() -> None:
    """A place with no branch would accept anything an edit put into it."""
    from stompcad.stale import PLACE_ORDER

    source = inspect.getsource(cli.validate_place)
    for place in PLACE_ORDER:
        assert f'"{place}"' in source


def test_an_edited_place_is_refused_by_the_tool_that_reads_it() -> None:
    """The refusal is ``stompdrill``'s own, naming the key the value was typed into."""
    from dataclasses import replace

    from stompcad.settings import Origin, Provenance, Resolved, Settings

    settings = Settings.of_defaults(TAR_AI)
    zero = replace(
        settings,
        drilling=replace(settings.drilling, grid_mm=Resolved(0.0015, Provenance(Origin.USER))),
    )
    with pytest.raises(cli.UsageError, match="drilling.grid_mm"):
        cli.validate_place(zero, "drilling", TAR_AI)


@pytest.mark.parametrize("place", ["artwork", "enclosure", "drilling", "boards", "output"])
def test_every_place_accepts_its_defaults(place: str) -> None:
    """The control: a check that refused everything would pass the test above."""
    from stompcad.settings import Settings

    cli.validate_place(Settings.of_defaults(TAR_AI), place, TAR_AI)


def test_ci_counts_as_no_terminal_even_with_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 15: a runner that allocates a pty must not get a full-screen app."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TERM", "xterm")
    assert not cli.has_terminal(_AlwaysATerminal())  # type: ignore[arg-type]


def test_a_dumb_terminal_counts_as_no_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert not cli.has_terminal(_AlwaysATerminal())  # type: ignore[arg-type]


def test_a_real_terminal_gets_the_workbench(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: a rule that said no to everything would never open the app."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert cli.has_terminal(_AlwaysATerminal())  # type: ignore[arg-type]


def test_the_parser_carries_only_what_identifies_the_work() -> None:
    """Decision 6: no flag is added for any value the workbench exposes."""
    parser = cli.build_parser()
    flags = {action.dest for action in parser._actions} - {"help"}
    assert flags == {"panel", "boards", "case", "case_model", "panel_reference", "emit"}


def test_the_retired_flags_are_gone() -> None:
    """Decision 16: `--progress` had no remaining job, and `--promote-warnings` none at all."""
    parser = cli.build_parser()
    for flag in ("--progress", "--promote-warnings"):
        with pytest.raises(SystemExit):
            parser.parse_args(["tar.ai", flag])


def test_no_panel_blocks_rather_than_refusing(tmp_path: Path) -> None:
    """Decision 6: the workbench opens on the Artwork place, stating that none is selected."""
    resolved = cli.blocked(cli.build_parser().parse_args([]), tmp_path)
    assert resolved.settings.artwork.panel.value is None
    assert not resolved.blockers.ready
    assert resolved.obstacle is not None
    assert "artwork" in resolved.obstacle.lower()


def test_several_panels_offer_a_pick(tmp_path: Path) -> None:
    for name in ("tar.ai", "fuzz.ai"):
        (tmp_path / name).write_bytes(b"%PDF-1.4\n")
    resolved = cli.blocked(cli.build_parser().parse_args([]), tmp_path)
    assert {path.name for path in resolved.panel_candidates} == {"tar.ai", "fuzz.ai"}


def test_a_malformed_project_blocks_the_run_and_names_the_file(tmp_path: Path) -> None:
    """Decision 9: never silent defaults, and never a run under values that look like the user's."""
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"%PDF-1.4\n")
    (tmp_path / "tar.stompcad.json").write_text("{not json", encoding="utf-8")
    resolved = cli.blocked(cli.build_parser().parse_args([str(panel)]), tmp_path)
    assert not resolved.blockers.ready
    assert resolved.obstacle is not None
    assert "tar.stompcad.json" in resolved.obstacle
    assert resolved.settings.drilling.grid_mm.value == 0.25, "every place must stay readable"


def test_each_blocked_state_still_exits_three_without_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Decision 6: without a terminal the same three cases keep the usage code.

    All three, because each reaches the code by its own route: two of them
    through the panel nobody named, and the third through a project file
    that cannot be read. ``CI`` is what makes this the headless path with a
    terminal attached or without one.
    """
    monkeypatch.setenv("CI", "true")
    monkeypatch.chdir(tmp_path)

    assert cli.main([]) == EXIT_USAGE
    assert "artwork" in capsys.readouterr().err.lower()

    for name in ("tar.ai", "fuzz.ai"):
        (tmp_path / name).write_bytes(b"%PDF-1.4\n")
    assert cli.main([]) == EXIT_USAGE
    several = capsys.readouterr().err
    assert "tar.ai" in several and "fuzz.ai" in several

    (tmp_path / "tar.stompcad.json").write_text("{not json", encoding="utf-8")
    assert cli.main(["tar.ai"]) == EXIT_USAGE
    assert "tar.stompcad.json" in capsys.readouterr().err


def test_an_argument_beyond_the_panel_starts_the_run() -> None:
    """Decision 1: an argument is an act of intent in this invocation."""
    parser = cli.build_parser()
    assert cli.started_by_argument(parser.parse_args(["tar.ai", "--case", "1590B"]))
    assert cli.started_by_argument(parser.parse_args(["tar.ai", "tar-pcb.stp"]))


def test_a_bare_panel_against_a_complete_project_starts_nothing() -> None:
    """A manifest value is a standing declaration, not an act of intent."""
    assert not cli.started_by_argument(cli.build_parser().parse_args(["tar.ai"]))
