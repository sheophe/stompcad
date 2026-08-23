"""Structural gate: the raw-measurement tie-break has one owner (ADR-0006).

Scans the *installed* packages' source -- resolved through ``importlib``,
never a path relative to the working directory -- for a tuple literal built
from a hole's raw ``x``, ``y`` and ``diameter`` in any order: that shape is
the tie-break restated by hand, and the property is the one legitimate
occurrence. Names no stage and no package, so a second consumer is caught
the moment its package joins ``PACKAGES`` below. A separate gate polices the
document-traversal rule over its own, different type, in its own module.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

__all__: list[str] = []

#: Every package this gate is responsible for. Adding a name here is the
#: whole of what "a second consumer" requires -- no stage, no path, no
#: caller-specific allowance.
PACKAGES = ("stompmodel", "stompdrill", "stompgeom")

#: The one module allowed to state the tuple literally: it is what
#: ``Hole.tie_break`` returns, the sole owner ADR-0006 names.
_OWNER_PACKAGE = "stompmodel"
_OWNER_MODULE = "model.py"

_RAW_FIELDS = ("x", "y", "diameter")


def _package_roots() -> list[Path]:
    """Every scanned package's source directory, resolved via import.

    Not a path relative to this file or the working directory: importing
    each package and reading its own ``__path__`` is what makes the gate
    bind whatever source a caller's interpreter actually resolves to.
    """
    roots: list[Path] = []
    for name in PACKAGES:
        pkg = importlib.import_module(name)
        assert pkg.__path__, f"{name} has no source directory to scan"
        roots.extend(Path(location) for location in pkg.__path__)
    return roots


def _source_files() -> list[Path]:
    """Every ``.py`` file under a scanned package's source, sorted for a stable failure."""
    return sorted(
        path
        for root in _package_roots()
        for path in root.rglob("*.py")
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


def test_the_scan_reaches_every_source_file():
    """An empty or narrowed walk would pass every check below by finding nothing."""
    names = {path.name for path in _source_files()}
    assert {"model.py", "dedupe.py", "route.py"} <= names
    assert len(_source_files()) > 20  # the workspace's three packages are not tiny


# ---------------------------------------------------------------------------
# the gate itself
# ---------------------------------------------------------------------------


def test_no_module_outside_the_owner_restates_the_raw_measurement_tuple():
    """Criterion 3: the rule has one owner and cannot be restated.

    Binds every package in ``PACKAGES``, named neither by stage nor by
    package -- so a fourth field on ``RawHole`` reaches every consumer by
    editing ``Hole.tie_break`` alone, and a second package gaining a
    restated copy fails here the moment it is added to the scan.
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
