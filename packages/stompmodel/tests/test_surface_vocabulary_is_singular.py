"""There is exactly one stated vocabulary of legal surfaces.

``stompmodel.model.SURFACES`` is the vocabulary's one home. A module that
spells out the set of legal surfaces again -- a container holding all six
names, or a bare comparison against one of them -- re-spells a name plan 2
will be writing wall code against, in three packages, with no gate to catch
it. This gate lives in the owner's own suite, mirroring
``test_case_face_vocabulary_is_singular.py``. See ADR-0008 and ADR-0009.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
#: Same reach as ``test_nanometre_guard_is_singular.py``: every workspace
#: member's own source, discovered rather than named, plus the catalogue
#: generator.
SOURCE_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs()) + (REPO / "tools",)
_VOCABULARY = {"face", "back", "left", "right", "top", "bottom"}

#: ``SURFACES``'s own definition is the vocabulary, not a restatement of it.
OWNER = PACKAGE / "src" / "stompmodel" / "model.py"


def _string_constant(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _restates_the_vocabulary(source: str) -> bool:
    """Whether ``source`` spells out the surface vocabulary itself.

    Two shapes catch every duplication the theme named: a container literal
    holding all six legal values, and a comparison against one of them as a
    bare string. A single legal value used on its own -- an argparse default,
    for instance -- is neither shape and is not what this rule is about.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            values = [_string_constant(node.left), *(_string_constant(c) for c in node.comparators)]
            if any(value in _VOCABULARY for value in values if value is not None):
                return True
        elif isinstance(node, ast.Dict):
            keys = {_string_constant(key) for key in node.keys if key is not None}
            if _VOCABULARY <= keys:
                return True
        elif isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            elements = {_string_constant(elt) for elt in node.elts}
            if _VOCABULARY <= elements:
                return True
    return False


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(
            p for p in root.rglob("*.py")
            if "__pycache__" not in p.parts and p != OWNER
        )
    return sorted(files)


def test_the_scanner_finds_a_tuple_that_lists_every_surface():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert _restates_the_vocabulary(
        '_KEYS = ("face", "back", "left", "right", "top", "bottom")'
    )


def test_the_scanner_finds_a_bare_comparison_against_a_surface():
    assert _restates_the_vocabulary('if hole.surface == "left": pass')


def test_a_container_of_some_surfaces_is_not_the_vocabulary():
    assert not _restates_the_vocabulary('_WALLS = ("left", "right", "top", "bottom")')


def test_a_single_legal_value_used_alone_is_not_a_restatement():
    assert not _restates_the_vocabulary('default = "face"')


def test_the_scan_reaches_every_workspace_member():
    """The reach control is a property of the scan, not a pinned answer.

    Checked two ways: every member the scan discovered really ships the
    ``src`` it claims to (well-formedness), and the scan's own roots cover
    every ``src`` directory an independent walk of ``packages/`` finds --
    one that never calls ``member_package_dirs`` -- so narrowing the shared
    discovery itself, not only this gate's use of it, is caught.
    """
    for pkg in member_package_dirs():
        assert (pkg / "src").is_dir(), f"{pkg} was discovered but ships no src"
    discovered = {root for root in SOURCE_ROOTS if root.name == "src"}
    ground_truth = member_area_roots("src")
    assert ground_truth, "no member ships a src -- nothing for this control to check"
    missing = ground_truth - discovered
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"


def test_no_module_states_the_surface_vocabulary_a_second_time():
    """Only ``SURFACES``'s own definition (an ``Assign``, not a compare or a
    collection) exists anywhere in the workspace; every consumer reaches the
    vocabulary through the published tuple instead."""
    offenders = [path for path in _source_files() if _restates_the_vocabulary(path.read_text(encoding="utf-8"))]
    assert offenders == []
