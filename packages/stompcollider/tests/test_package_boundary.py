"""This package's one structural invariant: it reaches the kernel only through
stompgeom.

An import gate rather than a text one, modelled on stompgeom's own: a name in
prose is not a dependency, and one written under ``TYPE_CHECKING`` is not one
ruff or mypy records as a package edge. ``OCP`` is absent from ``PERMITTED``
on purpose and stays absent: the kernel is reached through ``stompgeom``,
never directly, so a module importing ``OCP`` fails here first. See ADR-0008
and ADR-0009.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

__all__: list[str] = []

SOURCE = Path(__file__).resolve().parent.parent / "src" / "stompcollider"

#: The whole permitted world: the standard library, this package, the leaf
#: model package, and the kernel layer. ``stompgeom`` joined it with
#: ``boards.py``, the first module here to read geometry -- declared in this
#: package's own ``pyproject.toml`` in the same commit that first imported
#: it. ``OCP`` did not join it and does not: every kernel operation this
#: package performs is one ``stompgeom`` publishes, which is what keeps
#: ADR-0008's boundary a boundary rather than a preference. ``stompdrill``
#: is not reachable either -- nothing here reads a drill document except
#: through ``stompmodel``'s codec.
PERMITTED = frozenset(sys.stdlib_module_names) | {
    "stompcollider", "stompmodel", "stompgeom",
}


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


def test_the_scanner_finds_the_kernel_itself_foreign() -> None:
    """The GUILTY probe that survived stompgeom's admission.

    Unlike stompgeom, this package's permitted world excludes OCP: every
    kernel operation it performs is one stompgeom publishes, so a module
    reaching for OCP directly is duplicating that layer rather than using
    it. Widening ``PERMITTED`` by one name must not have widened it by two.
    """
    assert foreign_imports("import OCP.TDF\n") == {"OCP"}


def test_the_scanner_still_finds_the_kernel_beside_a_permitted_import() -> None:
    """The narrowing's own control: admitting stompgeom must not admit what
    stompgeom itself imports. A module taking both is reported for OCP alone.
    """
    both = "from stompgeom.step import read_step\nfrom OCP.TopoDS import TopoDS_Shape\n"

    assert foreign_imports(both) == {"OCP"}


def test_the_scanner_accepts_the_kernel_layer_this_package_declares() -> None:
    """The INNOCENT probe beside them: stompgeom is a declared dependency
    now, so ``boards.py``'s own import must not read as a violation."""
    assert foreign_imports("from stompgeom.levels import levels\n") == set()


def test_the_scanner_finds_a_third_party_import() -> None:
    """This package declares two dependencies, both workspace members, so any
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
    """This package names no sibling above it and no kernel binding.

    A dependency here is inherited by every package above this one in the
    workspace, which is why the set is widened one declared name at a time.
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
        "__init__.py", "boards.py", "canonicalise.py", "clash.py",
        "designators.py", "emitters/__init__.py", "emitters/report.py",
        "errors.py", "match.py", "model.py", "protrude.py",
        "raw.py", "seat.py", "sources/__init__.py", "sources/step.py",
    }
