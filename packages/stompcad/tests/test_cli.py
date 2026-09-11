"""The orchestrator's own surface: no kernel import, and a clean ``--help``.

``stompcad`` composes ``stompdrill`` and ``stompcollider`` as libraries; it
computes no geometry of its own, so it has no business importing OCP or
``stompgeom`` directly. The fixture-resolution test guards the paths every
later task's conftest fixtures depend on, so a moved fixture fails here
rather than inside a three-minute dock test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from stompcad import cli
from stompmodel.diagnostics import EXIT_USAGE
from tests.conftest import TAR_AI, TAR_PCB

__all__: list[str] = []


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
    than about a command line that writes nothing whatever it is asked.
    """
    good, control = tmp_path / "good.drl", tmp_path / "control.drl"
    assert cli.main([str(TAR_AI), "--case", "1590B", "--emit", f"excellon={control}"]) != EXIT_USAGE
    assert control.is_file(), "the control wrote nothing; the assertion below proves nothing"

    code = cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={good}", "--emit", "bogus=bad.bin",
    ])

    assert code == EXIT_USAGE
    assert not good.exists()


def test_parse_emit_rejects_a_spec_with_no_separator() -> None:
    with pytest.raises(cli.UsageError):
        cli.parse_emit("no-equals-sign")
