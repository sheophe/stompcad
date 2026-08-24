"""There is exactly one statement of how an artefact's bytes reach a path.

``stompmodel.protocols`` (``stage_payload``/``commit_staged``) is the rule's
one home: the atomic ``os.replace`` and the ``.{name}.{hex}.tmp`` temporary
naming it depends on. A module that restates either itself is the defect
ticket 26 exists to remove. This gate lives in the owner's own suite (ticket
25's convention). It must not fire on ``stompgeom.writer``'s kernel scratch
file (``tempfile.mkstemp``), already carved out by ADR-0005's
"caller-visible" qualifier. See ADR-0001, ADR-0005 and ADR-0008.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.workspace_membership import REPO, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
#: Same reach as ``test_nanometre_guard_is_singular.py``: every workspace
#: member's own source, discovered rather than named, plus the catalogue
#: generator -- a private copy could as easily hide there as in a package.
SOURCE_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs()) + (REPO / "tools",)
OWNER_MODULE = REPO / "packages" / "stompmodel" / "src" / "stompmodel" / "protocols.py"


def performs_the_atomic_replace(node: ast.AST) -> bool:
    """Is this call exactly ``os.replace(...)``?"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    )


def builds_the_temporary_name_shape(node: ast.AST) -> bool:
    """Does this f-string build the ``.{...}.{...}.tmp`` naming convention?

    Matched by shape, not by the exact literal split: a leading ``.``, a
    trailing ``.tmp``, and at least two interpolated segments in between --
    the two dynamic parts (the target's own name, and a fresh disambiguator)
    that make the convention what it is, rather than the exact spelling
    ``stage_payload`` happens to use today.
    """
    if not isinstance(node, ast.JoinedStr):
        return False
    literal = "".join(
        piece.value
        for piece in node.values
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
    )
    dynamic = sum(1 for piece in node.values if isinstance(piece, ast.FormattedValue))
    return literal.startswith(".") and literal.endswith(".tmp") and dynamic >= 2


def _offending_nodes(source: str) -> list[ast.AST]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if performs_the_atomic_replace(node) or builds_the_temporary_name_shape(node)
    ]


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


# ---------------------------------------------------------------------------
# proof the gate fires, and does not over-fire
# ---------------------------------------------------------------------------


def test_the_scanner_catches_a_restated_atomic_replace():
    assert performs_the_atomic_replace(
        ast.parse("os.replace(tmp, path)", mode="eval").body
    )


def test_the_scanner_catches_a_restated_temporary_name_shape():
    assert builds_the_temporary_name_shape(
        ast.parse('f".{path.name}.{uuid.uuid4().hex}.tmp"', mode="eval").body
    )
    # Order and exact literal spelling are not the point -- the shape is.
    assert builds_the_temporary_name_shape(
        ast.parse('f".{a}.{b}.tmp"', mode="eval").body
    )


def test_the_scanner_does_not_fire_on_an_unrelated_replace_call():
    """``str.replace`` and a same-named local function are not this rule."""
    assert not performs_the_atomic_replace(
        ast.parse('text.replace("a", "b")', mode="eval").body
    )
    assert not performs_the_atomic_replace(ast.parse("replace(tmp, path)", mode="eval").body)


def test_the_scanner_does_not_fire_on_an_unrelated_f_string():
    """A single interpolation, or a name with no dot/tmp shape, is not this rule."""
    assert not builds_the_temporary_name_shape(
        ast.parse('f"{path.name}"', mode="eval").body
    )
    assert not builds_the_temporary_name_shape(
        ast.parse('f"prefix-{a}-{b}-suffix"', mode="eval").body
    )


def test_stompgeoms_kernel_scratch_file_is_not_caught():
    """ADR-0005's caller-visible qualifier, checked explicitly rather than
    left to chance: ``stompgeom.writer``'s ``tempfile.mkstemp`` call matches
    neither shape above, so it is not among the offenders below."""
    writer = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "writer.py"
    assert writer in _source_files()
    assert _offending_nodes(writer.read_text(encoding="utf-8")) == []


def test_the_scan_reaches_every_workspace_member():
    """An empty or narrowed walk would pass the rule below by finding nothing."""
    names = {root.parent.name for root in SOURCE_ROOTS if root.name == "src"}
    assert names == {"stompmodel", "stompgeom", "stompdrill"}


# ---------------------------------------------------------------------------
# the gate itself
# ---------------------------------------------------------------------------


def test_no_module_outside_stompmodel_protocols_writes_an_artefacts_bytes():
    """Criterion 1 and 6: the mechanism has one statement, in one module.

    No module outside ``stompmodel.protocols`` may call ``os.replace`` or
    build the ``.{...}.{...}.tmp`` temporary name -- both are the owner's
    alone, published as ``stage_payload``/``commit_staged``/``discard_staged``.
    """
    offenders = {
        str(path): [node.lineno for node in nodes]
        for path in _source_files()
        if path != OWNER_MODULE
        for nodes in [_offending_nodes(path.read_text(encoding="utf-8"))]
        if nodes
    }
    assert offenders == {}, (
        "a module outside stompmodel.protocols performs the atomic replace or "
        "builds the temporary-name shape itself -- call stage_payload/"
        "commit_staged/discard_staged instead"
    )
