"""There is exactly one statement of how an artefact's bytes reach a path.

``stompmodel.protocols`` (``stage_payload``/``StagedWrite.commit``) is the
rule's one home: the atomic ``os.replace`` and the ``.{name}.{hex}.tmp``
temporary naming it depends on. A module that restates either itself is the
defect ticket 26 exists to remove. This gate lives in the owner's own suite
(ticket 25's convention). It must not fire on ``stompgeom.writer``'s kernel
scratch file (``tempfile.mkstemp``), already carved out by ADR-0005's
"caller-visible" qualifier. See ADR-0001, ADR-0005 and ADR-0008.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
#: Same reach as ``test_nanometre_guard_is_singular.py``: every workspace
#: member's own source, discovered rather than named, plus the catalogue
#: generator -- a private copy could as easily hide there as in a package.
SOURCE_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs()) + (REPO / "tools",)
OWNER_MODULE = REPO / "packages" / "stompmodel" / "src" / "stompmodel" / "protocols.py"

#: The definitions allowed to state the mechanism: ``stage_payload`` builds
#: the temporary name and ``StagedWrite.commit`` performs the atomic
#: replace. ``discard`` is deliberately absent -- it states neither shape,
#: and sanctioning a definition pre-emptively is the too-wide exemption
#: this replaces. A definition, not a file: a second statement added
#: elsewhere in ``protocols.py`` is a breach like any other.
_SANCTIONED = frozenset({"stage_payload", "commit"})


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


def _offending_nodes(source: str, sanctioned: Collection[str] = ()) -> list[ast.AST]:
    return [
        node
        for node in _outside(ast.parse(source), sanctioned)
        if performs_the_atomic_replace(node) or builds_the_temporary_name_shape(node)
    ]


def _offending_lines(source: str, sanctioned: Collection[str] = ()) -> list[int]:
    """The lines of ``_offending_nodes``, sorted, for a readable failure."""
    return sorted(
        {
            node.lineno
            for node in _offending_nodes(source, sanctioned)
            if isinstance(node, (ast.stmt, ast.expr))
        }
    )


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


def test_a_second_statement_in_the_rules_own_home_is_caught() -> None:
    """The guilty home probe: the exemption is a definition, not a file.

    The home file's real text with a second write mechanism spliced in
    beside the owner -- in memory, never on disk -- offends even under the
    sanction list, which a whole-file exclusion would have hidden.
    """
    spliced = OWNER_MODULE.read_text(encoding="utf-8") + (
        "\n\ndef _second_write_mechanism(tmp, path, target):\n"
        "    os.replace(tmp, path)\n"
        '    return f".{target.name}.{id(target)}.tmp"\n'
    )
    assert _offending_lines(spliced, _SANCTIONED)


def test_the_exemption_covers_the_owning_definitions_and_nothing_more() -> None:
    """The anchor probe, matched to the guilty one above.

    Unexempted, the home really does state the mechanism -- so the
    exemption is load-bearing and a renamed owner fails loudly rather than
    silently widening. Exempted, nothing else in the home states it, so the
    exemption is no wider than the definitions it names.
    """
    home = OWNER_MODULE.read_text(encoding="utf-8")

    assert _offending_lines(home), "the home no longer states the mechanism it owns"
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
    discovered = {root for root in SOURCE_ROOTS if root.name == "src"}
    ground_truth = member_area_roots("src")
    assert ground_truth, "no member ships a src -- nothing for this control to check"
    missing = ground_truth - discovered
    assert not missing, f"the scan's own roots do not cover: {sorted(missing)}"


# ---------------------------------------------------------------------------
# the gate itself
# ---------------------------------------------------------------------------


def test_no_module_outside_stompmodel_protocols_writes_an_artefacts_bytes():
    """Criterion 1 and 6: the mechanism has one statement, in one module.

    No definition outside ``stage_payload`` and ``StagedWrite.commit`` may
    call ``os.replace`` or build the ``.{...}.{...}.tmp`` temporary name --
    both are the owner's alone, published as ``stage_payload`` and the two
    verbs on the ``StagedWrite`` it returns. A definition, not a module:
    a second statement in ``protocols.py`` itself is caught here too.
    """
    offenders = {
        str(path): lines
        for path in _source_files()
        for lines in [
            _offending_lines(
                path.read_text(encoding="utf-8"),
                _SANCTIONED if path == OWNER_MODULE else (),
            )
        ]
        if lines
    }
    assert offenders == {}, (
        "a definition outside stage_payload and StagedWrite.commit performs "
        "the atomic replace or builds the temporary-name shape itself -- call "
        "stage_payload and commit/discard the value it returns instead"
    )
