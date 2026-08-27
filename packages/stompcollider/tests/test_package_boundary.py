"""This package's one structural invariant: the pure core takes only the leaf.

An import gate rather than a text one, modelled on stompgeom's own: a name in
prose is not a dependency, and one written under ``TYPE_CHECKING`` is not one
ruff or mypy records as a package edge. OCP and stompgeom are absent from
``PERMITTED`` on purpose -- this phase's core must not touch the kernel at
all, so a module reaching for either fails here before it fails anywhere
else. See ADR-0009.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

__all__: list[str] = []

SOURCE = Path(__file__).resolve().parent.parent / "src" / "stompcollider"

#: The whole permitted world for this phase: the standard library, this
#: package, and the leaf model package it consumes. Neither stompdrill nor
#: the kernel (stompgeom, OCP) is reachable from here yet -- see
#: "Everything above sources/ and emitters/ is pure" in the spec.
PERMITTED = frozenset(sys.stdlib_module_names) | {"stompcollider", "stompmodel"}


def foreign_imports(source: str) -> set[str]:
    """Every imported root in ``source`` that is neither stdlib nor permitted.

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
        path for path in SOURCE.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_the_scanner_finds_a_sibling_import() -> None:
    """The gate is only worth its line if it fires; this is the guilty probe."""
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
        "    from stompdrill.cli import main\n"
    )

    assert foreign_imports(guarded) == {"stompdrill"}


def test_the_scanner_finds_the_kernel_as_foreign_for_this_phase() -> None:
    """The pure core must not reach the kernel at all -- not even by name.

    Unlike stompgeom, this package's permitted world excludes OCP: nothing
    in Phase 1 needs it, and admitting it here would let a later task's
    kernel-touching source slip in unnoticed beside the pure stages.
    """
    assert foreign_imports("import OCP.TDF\n") == {"OCP"}


def test_the_scanner_finds_stompgeom_as_foreign_for_this_phase() -> None:
    """Likewise stompgeom: ``sources/`` and ``emitters/`` earn it later."""
    assert foreign_imports("from stompgeom.step import read_step\n") == {"stompgeom"}


def test_the_scanner_finds_a_third_party_import() -> None:
    """This package declares exactly one dependency, the leaf, so any other
    third-party import is a violation too."""
    assert foreign_imports("import pikepdf") == {"pikepdf"}


def test_the_scanner_accepts_the_package_and_the_standard_library() -> None:
    accepted = (
        "from __future__ import annotations\n"
        "import ast\n"
        "from decimal import Decimal\n"
        "from . import model\n"
        "from .errors import StompcolliderError\n"
        "import stompmodel.units\n"
    )

    assert foreign_imports(accepted) == set()


def test_every_module_imports_only_the_standard_library_and_itself() -> None:
    """This package names no sibling above it and no kernel, yet.

    A dependency here is inherited by every package above this one in the
    workspace, which is why this phase's core takes only the leaf.
    """
    offenders = {
        str(module.relative_to(SOURCE)): foreign_imports(module.read_text(encoding="utf-8"))
        for module in modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_scan_reaches_every_module_the_package_ships() -> None:
    """An empty or narrowed walk would pass the test above by finding nothing."""
    scanned = {str(module.relative_to(SOURCE)) for module in modules()}

    assert scanned == {
        "__init__.py", "canonicalise.py", "designators.py", "errors.py", "model.py", "raw.py",
    }
