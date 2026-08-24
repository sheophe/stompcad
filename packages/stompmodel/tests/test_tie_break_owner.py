"""Structural gate: the raw-measurement tie-break has one owner (ADR-0006).

Scans every workspace member's own source -- discovered from
``member_package_dirs``, read as plain text and never imported (this
package must not import a sibling above it) -- for a tuple built from a
hole's raw ``x``, ``y`` and ``diameter`` in any order: the tie-break
restated by hand. This gate lives in the owner's own suite (ticket 25):
running this package's own command must fail when the restatement
reappears anywhere in the workspace.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.workspace_membership import member_area_roots, member_package_dirs

__all__: list[str] = []

#: The one module allowed to state the tuple literally: it is what
#: ``Hole.tie_break`` returns, the sole owner ADR-0006 names.
_OWNER_PACKAGE = "stompmodel"
_OWNER_MODULE = "model.py"

_RAW_FIELDS = ("x", "y", "diameter")


def _source_files() -> list[Path]:
    """Every ``.py`` file under a scanned member's own ``src``, sorted for a
    stable failure. ``member_package_dirs`` is the one statement of which
    members that is; adding a package here requires no edit to this file."""
    return sorted(
        path
        for pkg in member_package_dirs()
        for path in (pkg / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _is_bare_raw_field(node: ast.expr, field: str) -> bool:
    """Is ``node`` exactly ``<expr>.raw.<field>`` -- no call, no arithmetic?

    A restatement of the tie-break reads the field bare, the way
    ``Hole.tie_break`` itself does. A derived fact built *from* the field
    (``nm_from_mm(hole.raw.x)``, a JSON encoder's ``hole.raw.x`` value) is a
    different computation and is not what this gate polices.
    """
    return (
        isinstance(node, ast.Attribute)
        and node.attr == field
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "raw"
    )


def tuple_restates_the_tie_break(node: ast.AST) -> bool:
    """Does this AST node build a tuple from all three raw fields, any order?

    Two of three is not the rule: ``snap.py`` legitimately reads raw ``x``
    and ``y`` together for the grid-tie check, with no ``diameter`` in
    sight. Only a tuple carrying all three, each read bare off ``.raw``, is
    the shape this gate exists to catch.
    """
    if not isinstance(node, ast.Tuple):
        return False
    present = {
        field
        for field in _RAW_FIELDS
        if any(_is_bare_raw_field(elt, field) for elt in node.elts)
    }
    return present == set(_RAW_FIELDS)


def _offending_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple) and tuple_restates_the_tie_break(node)
    ]


def _is_owner(path: Path) -> bool:
    return path.name == _OWNER_MODULE and path.parent.name == _OWNER_PACKAGE


# ---------------------------------------------------------------------------
# proof the gate fires
# ---------------------------------------------------------------------------


def test_the_gate_fires_on_a_restated_tuple():
    """Every field, any order -- the gate is only worth its line if it does."""
    assert tuple_restates_the_tie_break(
        ast.parse("(hole.raw.x, hole.raw.y, hole.raw.diameter)", mode="eval").body
    )
    assert tuple_restates_the_tie_break(
        ast.parse("(h.raw.diameter, h.raw.y, h.raw.x)", mode="eval").body
    )


def test_the_gate_does_not_fire_on_two_of_three_fields():
    """``snap.py``'s grid-tie check reads raw x and y together, no diameter --
    proof the gate does not over-fire on every pair of raw attributes.
    """
    assert not tuple_restates_the_tie_break(
        ast.parse("(hole.raw.x, hole.raw.y)", mode="eval").body
    )


def test_the_gate_does_not_fire_on_a_derived_computation():
    """``residual_nm`` reads all three raw fields, but each wrapped in
    arithmetic and a unit conversion -- a different fact, not a restatement.
    """
    source = (
        "(Nanometre(x_nm - nm_from_mm(hole.raw.x)), "
        "Nanometre(y_nm - nm_from_mm(hole.raw.y)), "
        "Nanometre(d_nm - nm_from_mm(hole.raw.diameter)))"
    )
    assert not tuple_restates_the_tie_break(ast.parse(source, mode="eval").body)


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
    discovered = {pkg / "src" for pkg in member_package_dirs()}
    ground_truth = member_area_roots("src")
    assert ground_truth, "no member ships a src -- nothing for this control to check"
    missing = ground_truth - discovered
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"
    names = {path.name for path in _source_files()}
    assert {"model.py", "dedupe.py", "route.py"} <= names
    assert len(_source_files()) > 20  # the workspace's three packages are not tiny


# ---------------------------------------------------------------------------
# the gate itself
# ---------------------------------------------------------------------------


def test_no_module_outside_the_owner_restates_the_raw_measurement_tuple():
    """Criterion 3: the rule has one owner and cannot be restated.

    Binds every member ``member_package_dirs`` names, named neither by stage
    nor by package -- so a fourth field on ``RawHole`` reaches every consumer
    by editing ``Hole.tie_break`` alone, and a second package gaining a
    restated copy fails here the moment its ``src`` directory exists.
    """
    offenders = {
        str(path): lines
        for path in _source_files()
        if not _is_owner(path)
        for lines in [_offending_lines(path)]
        if lines
    }
    assert offenders == {}, (
        "a module outside stompmodel.model restates the raw-measurement "
        "tie-break as its own tuple literal -- call Hole.tie_break instead"
    )
