"""Every stage in this package declares a weight and takes a scope.

A stage added later that misses the protocol would silently take no share
of the bar and report nothing. The pinned set is what makes adding one a
deliberate act: the count changes, this fails, and the author chooses a
weight rather than inheriting a default.

Written once per package rather than once for the workspace:
``test_package_boundary.py`` forbids importing ``stompdrill``, so no one
process may enumerate both packages' stages.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__: list[str] = []

SOURCE = Path(__file__).resolve().parent.parent / "src" / "stompcollider"

#: The three stages this package defines. Update deliberately, with a weight.
EXPECTED = {"Clashes", "Match", "Seat"}


def stage_classes() -> dict[str, ast.ClassDef]:
    """Every class in this package defining both ``apply`` and a ``name``."""
    found: dict[str, ast.ClassDef] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
            annotated = {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
            if "apply" in methods and "name" in annotated:
                found[node.name] = node
    return found


def test_the_stage_set_is_the_pinned_one() -> None:
    assert set(stage_classes()) == EXPECTED


def test_every_stage_declares_a_weight() -> None:
    missing = [
        name
        for name, node in stage_classes().items()
        if "weight"
        not in {
            item.target.id
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        }
    ]
    assert missing == []


def test_every_stage_takes_a_scope() -> None:
    missing = []
    for name, node in stage_classes().items():
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "apply":
                if "scope" not in {arg.arg for arg in item.args.args}:
                    missing.append(name)
    assert missing == []
