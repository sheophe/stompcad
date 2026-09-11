"""The orchestrator's own surface: no kernel import, and a clean ``--help``.

``stompcad`` composes ``stompdrill`` and ``stompcollider`` as libraries; it
computes no geometry of its own, so it has no business importing OCP or
``stompgeom`` directly. The fixture-resolution test guards the paths every
later task's conftest fixtures depend on, so a moved fixture fails here
rather than inside a three-minute dock test.
"""

from __future__ import annotations

from pathlib import Path

from stompcad import cli
from tests.conftest import TAR_AI, TAR_PCB

__all__: list[str] = []


def test_the_package_imports_no_kernel() -> None:
    """Spec constraint: stompcad computes no geometry and never imports OCP."""
    import stompcad

    source = Path(stompcad.__file__).parent
    offenders = [
        path.name
        for path in source.rglob("*.py")
        if "OCP" in path.read_text() or "stompgeom" in path.read_text()
    ]
    assert offenders == []


def test_help_exits_clean() -> None:
    assert cli.main(["--help"]) == 0


def test_the_fixtures_are_where_the_tests_expect() -> None:
    assert TAR_AI.is_file()
    assert TAR_PCB.is_file()
