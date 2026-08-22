"""There is exactly one implementation of the whole-nanometre type guard.

`stompmodel.units.check_nanometres` is the rule's one home; a module that
spells the rule out again with its own ``raise TypeError`` is the defect
ticket 01 exists to remove. See ADR-0004 and ADR-0009.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
#: Every workspace member with runtime source, plus the catalogue generator --
#: the same reach as the enclosure catalogue's own currency check, because a
#: private copy could as easily hide in the generator as in a package.
SOURCE_ROOTS = (
    REPO / "packages" / "stompmodel" / "src",
    REPO / "packages" / "stompgeom" / "src",
    PACKAGE / "src",
    REPO / "tools",
)
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


def test_the_guards_phrase_appears_in_exactly_one_module():
    """No module outside ``stompmodel.units`` still enforces this rule itself."""
    offenders = [
        path
        for path in _source_files()
        if path != GUARD_HOME and raises_the_guards_phrase(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
