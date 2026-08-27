"""``stompgeom.step.leaf_labels`` is the only XCAF leaf descent in the workspace.

Deduplicating the three sites this fold found closes three recipes; a
fourth site reopens the class, which has already happened once. This gate
lives in the owner's own suite (ticket 25): running this package's own
command must fail when a second descent reappears anywhere in the
workspace -- previously a duplicate added to this package's own
``writer.py`` went uncaught by this package's own suite, run alone.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

#: Every workspace member's own source and tests -- the reach the theme
#: names ("no module under any package's source or tests"), so a second
#: consumer package is caught the day it is added, with no edit here.
#: ``member_package_dirs`` is the one statement of which members that is.
SOURCE_ROOTS = tuple(
    pkg / area for pkg in member_package_dirs() for area in ("src", "tests")
)

#: The one module allowed to name these: it is what publishes the walk.
WALK_HOME = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "step.py"

#: The file holding the one independent oracle: a test verifying the
#: writer's colour count needs a walk that does not share code with the
#: thing it verifies, which this repository's testing rules forbid. Naming
#: the file is not the exemption -- ``_SANCTIONED`` below names the one
#: function inside it.
ORACLE_HOME = REPO / "packages" / "stompdrill" / "tests" / "test_step_cut.py"

#: The writer's own census keeps a third, deliberately independent walk (see
#: ``_count_colour_assignments``'s own docstring): a sub-shape colour can sit
#: on an *intermediate* assembly label a leaf-only descent never visits, so
#: reusing ``leaf_labels`` here would under-count exactly the case Task 8
#: exists to fix, not merely duplicate it.
WRITER_HOME = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "writer.py"

#: The XCAF calls that only a sanctioned walk may make: the assembly test,
#: the component accessor, and the free-shape accessor.
_WALK_NAMES = frozenset({"IsAssembly_s", "GetComponents_s", "GetFreeShapes"})

#: The definitions allowed to name the walk, keyed by the file that holds
#: them. A *definition*, not a file: the oracle's home is a 29 KB test
#: module, and a fifth walk added anywhere else in it must still be caught.
#: Both ``step.py`` names are needed -- ``leaf_labels`` holds the
#: ``GetFreeShapes`` prologue and ``_walk_leaves`` holds the descent.
_SANCTIONED: dict[Path, frozenset[str]] = {
    WALK_HOME: frozenset({"leaf_labels", "_walk_leaves"}),
    ORACLE_HOME: frozenset({"_colours_by_product"}),
    WRITER_HOME: frozenset({"_count_colour_assignments"}),
}


def _outside(tree: ast.Module, sanctioned: Collection[str] = ()) -> list[ast.AST]:
    """Every node in ``tree`` outside the definitions ``sanctioned`` names.

    The exempt unit is the definition, never the file: a second walk added
    beside the owner, in the owner's own module, is exactly the regression
    a whole-file exclusion hides.
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


def _names_the_walk(node: ast.AST) -> bool:
    """Whether this node refers to any of ``_WALK_NAMES``, as a call or not."""
    if isinstance(node, ast.Attribute) and node.attr in _WALK_NAMES:
        return True
    return isinstance(node, ast.Name) and node.id in _WALK_NAMES


def _offending_lines(source: str, sanctioned: Collection[str] = ()) -> list[int]:
    """Every line outside ``sanctioned`` where ``source`` names the walk."""
    return sorted(
        {
            node.lineno
            for node in _outside(ast.parse(source), sanctioned)
            if isinstance(node, ast.expr) and _names_the_walk(node)
        }
    )


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def test_the_scanner_finds_the_walk_it_exists_to_catch() -> None:
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert _offending_lines(
        "def leaves(label, out):\n"
        "    if XCAFDoc_ShapeTool.IsAssembly_s(label):\n"
        "        pass\n"
    )
    assert _offending_lines("shape_tool.GetFreeShapes(free)")
    assert _offending_lines("XCAFDoc_ShapeTool.GetComponents_s(label, children)")


def test_a_plain_name_is_read_too() -> None:
    """Not every offender would qualify the call with a module or tool."""
    assert _offending_lines("from OCP.XCAFDoc import IsAssembly_s\nIsAssembly_s(label)")


def test_a_second_walk_in_a_rules_own_home_is_caught() -> None:
    """The guilty home probe, run once per home the exemption names.

    Each home's real text with a second descent spliced in beside its owner
    -- in memory, never on disk -- offends even under that home's sanction
    list. Iterating ``_SANCTIONED`` covers every declared home, including
    the oracle's 29 KB test module in another package.
    """
    breach = (
        "\n\ndef _second_leaf_walk(document):\n"
        "    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())\n"
        "    free = TDF_LabelSequence()\n"
        "    tool.GetFreeShapes(free)\n"
        "    for i in range(1, free.Length() + 1):\n"
        "        label = free.Value(i)\n"
        "        if XCAFDoc_ShapeTool.IsAssembly_s(label):\n"
        "            kids = TDF_LabelSequence()\n"
        "            XCAFDoc_ShapeTool.GetComponents_s(label, kids)\n"
    )
    for home, sanctioned in _SANCTIONED.items():
        spliced = home.read_text(encoding="utf-8") + breach
        assert _offending_lines(spliced, sanctioned), f"{home} hid a second walk"


def test_the_exemption_covers_the_owning_definitions_and_nothing_more() -> None:
    """The anchor probe, matched to the guilty one above.

    Unexempted, each home really does name the walk -- so its exemption is
    load-bearing and a renamed owner fails loudly rather than silently
    widening. Exempted, nothing else in that home names it, so the
    exemption is no wider than the definitions it names.
    """
    for home, sanctioned in _SANCTIONED.items():
        text = home.read_text(encoding="utf-8")
        assert _offending_lines(text), f"{home} no longer names the walk it owns"
        assert _offending_lines(text, sanctioned) == [], f"{home} names it elsewhere too"


def test_the_scan_reaches_every_workspace_member() -> None:
    """The reach control is a property of the scan, not a pinned answer.

    Checked two ways: every member the scan discovered really ships the
    ``src`` it claims to (well-formedness), and the scan's own roots cover
    every ``src``/``tests`` directory an independent walk of ``packages/``
    finds — one that never calls ``member_package_dirs`` — so narrowing the
    shared discovery itself, not only this gate's use of it, is caught.
    """
    for pkg in member_package_dirs():
        assert (pkg / "src").is_dir(), f"{pkg} was discovered but ships no src"
    discovered = set(SOURCE_ROOTS)
    ground_truth = member_area_roots("src") | member_area_roots("tests")
    assert ground_truth, "no member ships a src or tests -- nothing for this control to check"
    missing = ground_truth - discovered
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"


def test_the_walk_is_named_only_inside_the_definitions_that_own_it() -> None:
    """Two producers in the walk's own home, one declared oracle, and one
    declared, deliberately independent census.

    A fourth *definition* naming any of these identifiers is a fifth walk:
    exactly the class of regression the theme's root cause records having
    already happened once. Anywhere else in any home counts, which is the
    reach a whole-file exclusion used to give away.
    """
    offenders = {
        str(path): lines
        for path in _source_files()
        for lines in [
            _offending_lines(
                path.read_text(encoding="utf-8"),
                _SANCTIONED.get(path, frozenset()),
            )
        ]
        if lines
    }
    assert offenders == {}
