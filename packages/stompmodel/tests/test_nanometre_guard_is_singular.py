"""There is exactly one implementation of the whole-nanometre type guard.

``stompmodel.units.check_nanometres`` is the rule's one home; a module that
spells the rule out again with its own ``raise TypeError`` is the defect
ticket 01 exists to remove. This gate lives in the owner's own suite (ticket
25): running this package's own documented command is what must fail when
the duplication reappears, in this package's source or any other's. See
ADR-0004, ADR-0008 and ADR-0009.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
#: Every workspace member's own source, discovered rather than named, plus
#: the catalogue generator -- a private copy could as easily hide there as
#: in a package. One statement (``member_package_dirs``) decides which
#: packages that is; a member added under the workspace is scanned with no
#: edit here.
SOURCE_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs()) + (REPO / "tools",)
GUARD_HOME = REPO / "packages" / "stompmodel" / "src" / "stompmodel" / "units.py"
_PHRASE = "whole number of nanometres"


def _string_value(node: ast.expr) -> str | None:
    """Read a plain string or f-string literal's constant text, or ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            piece.value
            for piece in node.values
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
        )
    return None


def raises_the_guards_phrase(source: str) -> bool:
    """Whether ``source`` raises a ``TypeError`` stating the guard's own phrase."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Raise):
            continue
        call = node.exc
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "TypeError"
        ):
            continue
        if any(_PHRASE in (_string_value(arg) or "") for arg in call.args):
            return True
    return False


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def test_the_scanner_finds_the_duplication_it_exists_to_catch():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert raises_the_guards_phrase(
        "def f(value):\n"
        "    if type(value) is not int:\n"
        '        raise TypeError(f"x must be a whole number of nanometres, not {value!r}")\n'
    )


def test_a_plain_string_argument_is_read_too():
    """Not every duplicate would bother with an f-string."""
    assert raises_the_guards_phrase(
        'raise TypeError("y must be a whole number of nanometres")'
    )


def test_the_scan_reaches_every_workspace_member():
    """The reach control is a property of the scan, not a pinned answer.

    Checked two ways: every member the scan discovered really ships the
    ``src`` it claims to (well-formedness), and the scan's own roots cover
    every ``src`` directory an independent walk of ``packages/`` finds —
    one that never calls ``member_package_dirs`` — so narrowing the shared
    discovery itself, not only this gate's use of it, is caught.
    """
    for pkg in member_package_dirs():
        assert (pkg / "src").is_dir(), f"{pkg} was discovered but ships no src"
    discovered = {root for root in SOURCE_ROOTS if root.name == "src"}
    ground_truth = member_area_roots("src")
    assert ground_truth, "no member ships a src -- nothing for this control to check"
    missing = ground_truth - discovered
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"


def test_the_guards_phrase_appears_in_exactly_one_module():
    """No module outside ``stompmodel.units`` still enforces this rule itself."""
    offenders = [
        path
        for path in _source_files()
        if path != GUARD_HOME and raises_the_guards_phrase(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
