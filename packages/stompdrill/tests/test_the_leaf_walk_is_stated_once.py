"""``stompgeom.step.leaf_labels`` is the only XCAF leaf descent in the workspace.

Deduplicating the three sites this fold found closes three recipes; a fourth
site reopens the class, which has already happened once (a private
cross-package import, then a fifth walk in the writer's own tests). This
gate is the one that catches the next one, whichever package adds it. See
ADR-0008 and ``test_nanometre_guard_is_singular.py``, the sibling gate this
one is modelled on.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
#: Every workspace member's own source and tests -- the reach the theme
#: names ("no module under any package's source or tests"), so a second
#: consumer package is caught the day it is added, with no edit here.
SOURCE_ROOTS = tuple(
    REPO / "packages" / package / area
    for package in ("stompmodel", "stompgeom", "stompdrill")
    for area in ("src", "tests")
)

#: The one module allowed to name these: it is what publishes the walk.
WALK_HOME = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "step.py"

#: The writer's colour census in the tests keeps its own walk deliberately
#: (see its docstring): folding it in would verify the writer's count with
#: the code that produces it, which this repository's testing rules forbid.
#: Exactly one entry, named and commented, per the ticket that added this gate.
ALLOWED_INDEPENDENT_ORACLE = REPO / "packages" / "stompdrill" / "tests" / "test_step_cut.py"

#: The XCAF calls that only ``leaf_labels`` may make: the assembly test, the
#: component accessor, and the free-shape accessor -- the whole descent.
_WALK_NAMES = frozenset({"IsAssembly_s", "GetComponents_s", "GetFreeShapes"})


def _names_the_walk(source: str) -> bool:
    """Whether ``source`` refers to any of ``_WALK_NAMES``, as a call or not."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in _WALK_NAMES:
            return True
        if isinstance(node, ast.Name) and node.id in _WALK_NAMES:
            return True
    return False


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def test_the_scanner_finds_the_walk_it_exists_to_catch() -> None:
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert _names_the_walk(
        "def leaves(label, out):\n"
        "    if XCAFDoc_ShapeTool.IsAssembly_s(label):\n"
        "        pass\n"
    )
    assert _names_the_walk("shape_tool.GetFreeShapes(free)")
    assert _names_the_walk("XCAFDoc_ShapeTool.GetComponents_s(label, children)")


def test_a_plain_name_is_read_too() -> None:
    """Not every offender would qualify the call with a module or tool."""
    assert _names_the_walk("from OCP.XCAFDoc import IsAssembly_s\nIsAssembly_s(label)")


def test_the_walk_is_named_in_exactly_two_places() -> None:
    """One producer (the walk's own home) and one declared, independent oracle.

    A third file naming any of these identifiers is a fourth walk: exactly
    the class of regression the theme's root cause records having already
    happened once.
    """
    offenders = [
        path
        for path in _source_files()
        if path not in (WALK_HOME, ALLOWED_INDEPENDENT_ORACLE)
        and _names_the_walk(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
