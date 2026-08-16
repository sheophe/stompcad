"""Find Python docstrings that exceed a physical-line limit."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DocstringViolation", "find_long_docstrings"]

_OWNER_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True, slots=True)
class DocstringViolation:
    """Location and size of one over-length docstring."""

    path: Path
    line: int
    owner: str
    lines: int


def _python_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
        else:
            yield from sorted(root.rglob("*.py"))


def find_long_docstrings(
    roots: Iterable[Path], *, max_lines: int = 10
) -> tuple[DocstringViolation, ...]:
    """Return module and item docstrings longer than ``max_lines``."""
    violations: list[DocstringViolation] = []
    for path in _python_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, _OWNER_NODES) or not node.body:
                continue
            expression = node.body[0]
            if not isinstance(expression, ast.Expr):
                continue
            value = expression.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            lines = value.end_lineno - value.lineno + 1
            if lines <= max_lines:
                continue
            owner = "<module>" if isinstance(node, ast.Module) else node.name
            violations.append(
                DocstringViolation(path, value.lineno, owner, lines)
            )
    return tuple(violations)
