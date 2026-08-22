"""The leaf's one structural invariant: it imports no sibling.

An import gate rather than a text one. A name in prose is not a dependency,
and a dependency written under ``TYPE_CHECKING`` is not one ruff or mypy
records as a package edge. See ADR-0009.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

__all__: list[str] = []

SOURCE = Path(__file__).resolve().parent.parent / "src" / "stompmodel"

#: The whole permitted world. ADR-0009 makes this package the workspace's
#: pure-Python leaf and its distribution declares no dependencies, so a
#: third-party root is as much a violation here as a sibling member is.
PERMITTED = frozenset(sys.stdlib_module_names) | {"stompmodel"}


def foreign_imports(source: str) -> set[str]:
    """Every imported root in ``source`` that is neither stdlib nor this package.

    A relative import cannot leave the package, so it needs no check. An
    absolute one is reduced to its root: ``stompdrill.units`` is a dependency
    on ``stompdrill``, whatever it takes from it.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found - PERMITTED


def modules() -> list[Path]:
    """Every module the package ships, sorted so a failure names a stable one."""
    return sorted(
        path
        for path in SOURCE.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_the_scanner_finds_a_sibling_import() -> None:
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert foreign_imports("from stompdrill.units import Micron") == {"stompdrill"}


def test_the_scanner_finds_a_plain_sibling_import_too() -> None:
    """``import x`` and ``from x import y`` are the same edge, differently spelt."""
    assert foreign_imports("import stompdrill.quantise") == {"stompdrill"}


def test_the_scanner_finds_a_sibling_hidden_behind_type_checking() -> None:
    """A gate reading only runtime imports would miss the annotation-only one.

    Under ``from __future__ import annotations`` such an import is erased at
    runtime, so nothing but the source says it is there.
    """
    guarded = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from stompgeom.step import read_step\n"
    )

    assert foreign_imports(guarded) == {"stompgeom"}


def test_the_scanner_finds_a_third_party_import() -> None:
    """The leaf declares no dependencies, so a runtime one is a violation too."""
    assert foreign_imports("import pikepdf") == {"pikepdf"}


def test_the_scanner_accepts_the_package_and_the_standard_library() -> None:
    """Both halves of the permitted world, so neither passes by accident."""
    accepted = (
        "from __future__ import annotations\n"
        "import ast\n"
        "from decimal import Decimal\n"
        "from . import units\n"
        "from .model import DrillData\n"
        "import stompmodel.codec\n"
    )

    assert foreign_imports(accepted) == set()


def test_every_module_imports_only_the_standard_library_and_itself() -> None:
    """``stompmodel`` names no sibling. This is the whole reason it exists.

    A dependency here is inherited by every package in the workspace, which
    is why the leaf's distribution declares none at all.
    """
    offenders = {
        str(module.relative_to(SOURCE)): foreign_imports(module.read_text(encoding="utf-8"))
        for module in modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_scan_reaches_every_module_the_package_ships() -> None:
    """An empty or narrowed walk would pass the test above by finding nothing."""
    scanned = {str(module.relative_to(SOURCE)) for module in modules()}

    assert scanned >= {
        "__init__.py",
        "codec.py",
        "diagnostics.py",
        "errors.py",
        "frames.py",
        "model.py",
        "protocols.py",
        "units.py",
    }
