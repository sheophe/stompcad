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

from stompcad import cli
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
