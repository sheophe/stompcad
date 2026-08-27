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
from collections.abc import Collection
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

__all__: list[str] = []

#: The one definition allowed to state the tuple: it is what ``Hole.tie_break``
#: returns, the sole owner ADR-0006 names. A definition, not a module -- a
#: second statement added elsewhere in ``model.py`` is a breach like any other.
TIE_BREAK_HOME = REPO / "packages" / "stompmodel" / "src" / "stompmodel" / "model.py"
_SANCTIONED = frozenset({"tie_break"})

_RAW_FIELDS = ("x", "y", "diameter")


def _outside(tree: ast.Module, sanctioned: Collection[str] = ()) -> list[ast.AST]:
    """Every node in ``tree`` outside the definitions ``sanctioned`` names.

    The exempt unit is the definition, never the file: a second statement
    added beside the owner, in the owner's own module, is exactly the
    regression a whole-file exclusion hides.
    """
    found: list[ast.AST] = []

    def descend(parent: ast.AST) -> None:
        for child in ast.iter_child_nodes(parent):
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name in sanctioned
            ):
                continue
            found.append(child)
            descend(child)

    descend(tree)
    return found


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


def _offending_lines(source: str, sanctioned: Collection[str] = ()) -> list[int]:
    """Every line outside ``sanctioned`` where ``source`` restates the tuple."""
    return sorted(
        {
            node.lineno
            for node in _outside(ast.parse(source), sanctioned)
            if isinstance(node, ast.expr) and tuple_restates_the_tie_break(node)
        }
    )


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


def test_a_second_statement_in_the_rules_own_home_is_caught():
    """The guilty home probe: the exemption is a definition, not a file.

    The home file's real text with a second tuple spliced in beside the
    owner -- in memory, never on disk, and in a *different* field order, so
    the gate's order-independence is exercised here too -- offends even
    under the sanction list, which a whole-file exclusion would have hidden.
    """
    spliced = TIE_BREAK_HOME.read_text(encoding="utf-8") + (
        "\n\ndef _second_tie_break(hole):\n"
        "    return (hole.raw.diameter, hole.raw.y, hole.raw.x)\n"
    )
    assert _offending_lines(spliced, _SANCTIONED)


def test_the_exemption_covers_the_owning_definition_and_nothing_more():
    """The anchor probe, matched to the guilty one above.

    Unexempted, the home really does state the tuple -- so the exemption is
    load-bearing and a renamed ``tie_break`` fails loudly rather than
    silently widening. Exempted, nothing else in the home states it, so the
    exemption is no wider than the definition it names.
    """
    home = TIE_BREAK_HOME.read_text(encoding="utf-8")

    assert _offending_lines(home), "the home no longer states the tuple it owns"
    assert _offending_lines(home, _SANCTIONED) == []


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
        for lines in [
            _offending_lines(
                path.read_text(encoding="utf-8"),
                _SANCTIONED if path == TIE_BREAK_HOME else (),
            )
        ]
        if lines
    }
    assert offenders == {}, (
        "a definition outside Hole.tie_break restates the raw-measurement "
        "tie-break as its own tuple literal -- call Hole.tie_break instead"
    )
