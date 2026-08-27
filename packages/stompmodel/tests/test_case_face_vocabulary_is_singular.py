"""There is exactly one stated vocabulary of legal case faces.

``stompmodel.model.CaseFace`` is the vocabulary's one home. A module that
spells out the set of legal faces again -- a container holding both
``"box"`` and ``"lid"``, or a comparison against either as a bare string --
is the defect ticket 13 exists to remove. This gate lives in the owner's own
suite (ticket 25): running this package's own command must fail when the
duplication reappears anywhere in the workspace. See ADR-0008 and ADR-0009.
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
_VOCABULARY = {"box", "lid"}


def _string_constant(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _restates_the_vocabulary(source: str) -> bool:
    """Whether ``source`` spells out the face vocabulary itself.

    Two shapes catch every duplication the theme named: a container literal
    holding both legal values (``cli._FACES``, ``cad._FACE_KEYWORDS``), and a
    comparison against either as a bare string (the STEP emitter's ternary,
    and ``cad.loader``'s old ``face == "lid"``). A single legal value used on
    its own -- an argparse default, for instance -- is neither shape and is
    not what this rule is about.
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
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def test_the_scanner_finds_a_tuple_that_lists_both_faces():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert _restates_the_vocabulary('_FACES = ("box", "lid")')


def test_the_scanner_finds_a_dict_keyed_on_both_faces():
    assert _restates_the_vocabulary('_KEYWORDS = {"box": "BOX", "lid": "LID"}')


def test_the_scanner_finds_a_bare_comparison_against_either_face():
    assert _restates_the_vocabulary('keyword = "BOX" if model.face == "box" else "LID"')


def test_a_single_legal_value_used_alone_is_not_a_restatement():
    """An argparse default naming one legal value is not the vocabulary."""
    assert not _restates_the_vocabulary('default = "box"')


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


def test_no_module_states_the_face_vocabulary_a_second_time():
    """Only ``CaseFace``'s own values (an ``Assign``, not a compare or a
    collection) exist anywhere in the workspace; every consumer reaches the
    vocabulary through the published type instead."""
    offenders = [path for path in _source_files() if _restates_the_vocabulary(path.read_text(encoding="utf-8"))]
    assert offenders == []
