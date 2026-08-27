"""No name ``stompgeom``'s kernel-facing modules export returns a bare label.

One reaches a caller only inside ``StepLabel``, which holds the document it
was drawn from (ADR-0008, ticket 34: "the label carries its document"). This
gate lives beside the existing leaf-walk gate
(``test_the_leaf_walk_is_stated_once.py``) and is discovered the same way --
by carrying ``_REACH_TEST``, ticket 32's convention -- rather than added to a
literal list of gates, so a workspace member or a gate gained later needs no
edit here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

#: The two free functions this ticket deletes from every published surface.
#: Either used to hand a caller a bare label with no lifetime guarantee.
_DELETED_NAMES = frozenset({"label_name", "label_entry"})

#: ``stompgeom``'s own modules that talk to the kernel directly -- the only
#: place a bare-label return could originate. Not every ``stompgeom``
#: module: ``kernel.py`` never touches a ``TDF_Label``.
_KERNEL_FACING = (
    REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "step.py",
    REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "writer.py",
)

_ALL_SRC_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs())


def _exported_names(tree: ast.Module) -> frozenset[str]:
    """The strings literally listed in a module's own ``__all__``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return frozenset(
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                )
    return frozenset()


def _bare_label_exports(source: str) -> list[str]:
    """Exported function names whose own return annotation names
    ``TDF_Label`` outright. ``StepLabel``, wrapping it, does not match this
    substring, nor does a ``tuple[StepLabel, ...]`` that carries one."""
    tree = ast.parse(source)
    exported = _exported_names(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in exported
            and node.returns is not None
            and "TDF_Label" in ast.unparse(node.returns)
        ):
            offenders.append(node.name)
    return offenders


def test_the_scanner_finds_a_bare_label_export_it_exists_to_catch() -> None:
    """The guilty control: an exported function returning a bare label must
    be flagged, or this gate could pass by scanning nothing."""
    guilty = (
        "from OCP.TDF import TDF_Label\n"
        "__all__ = ['leaked']\n"
        "def leaked(label: TDF_Label) -> TDF_Label:\n"
        "    return label\n"
    )
    assert _bare_label_exports(guilty) == ["leaked"]


def test_an_export_wrapping_the_label_is_not_flagged() -> None:
    """The innocent control: ``StepLabel`` itself, and a function returning
    it or a tuple of it, must not trip the same check."""
    innocent = (
        "from .step import StepLabel\n"
        "__all__ = ['one', 'many']\n"
        "def one(label) -> StepLabel:\n"
        "    ...\n"
        "def many(document) -> tuple[StepLabel, ...]:\n"
        "    ...\n"
    )
    assert _bare_label_exports(innocent) == []


def test_the_scan_reaches_every_workspace_member() -> None:
    """The reach control is a property of the scan, not a pinned answer:
    every member's own ``src`` is where a deleted name could resurface in
    ``__all__``, checked against an independent walk of ``packages/`` that
    never calls ``member_package_dirs`` itself.
    """
    ground_truth = member_area_roots("src")
    assert ground_truth, "no member ships a src -- nothing for this control to check"
    missing = ground_truth - frozenset(_ALL_SRC_ROOTS)
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"


def test_stompgeoms_kernel_facing_surface_publishes_no_bare_label() -> None:
    """The rule-checking assertion. ``stompgeom``'s own kernel-facing
    modules export no function returning a bare ``TDF_Label`` today, and
    the two functions this ticket deletes -- which used to hand a caller
    exactly that -- appear in no member's own ``__all__`` anywhere in the
    workspace.
    """
    offenders: list[str] = []
    for path in _KERNEL_FACING:
        for name in _bare_label_exports(path.read_text(encoding="utf-8")):
            offenders.append(f"{path}: {name!r} returns a bare TDF_Label")

    for src in _ALL_SRC_ROOTS:
        for path in sorted(Path(src).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            exported = _exported_names(ast.parse(path.read_text(encoding="utf-8")))
            leaked = exported & _DELETED_NAMES
            if leaked:
                offenders.append(f"{path}: still exports {sorted(leaked)}")

    assert offenders == [], "\n".join(offenders)
