"""There is exactly one implementation of the whole-nanometre type guard.

``stompmodel.units.check_nanometres`` is the rule's one home; a definition
that states the rule again -- in the owner's words or in its own mechanism,
and inside the owner's own module as readily as another's -- is the defect
ticket 01 exists to remove. This gate lives in the owner's own suite (ticket
25): running this package's own documented command is what must fail when
the duplication reappears, in this package's source or any other's. See
ADR-0004, ADR-0008 and ADR-0009.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

from tools.workspace_membership import REPO, member_area_roots, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
#: Every workspace member's own source, discovered rather than named, plus
#: the catalogue generator -- a private copy could as easily hide there as
#: in a package. One statement (``member_package_dirs``) decides which
#: packages that is; a member added under the workspace is scanned with no
#: edit here.
SOURCE_ROOTS = tuple(pkg / "src" for pkg in member_package_dirs()) + (REPO / "tools",)
GUARD_HOME = REPO / "packages" / "stompmodel" / "src" / "stompmodel" / "units.py"
_PHRASE = "whole number of nanometres"

#: The one definition allowed to state the rule. ``check_millimetres`` sits
#: in the same module, raises ``TypeError`` too, and is deliberately absent:
#: it tests ``float``, so the shape below cannot reach it, and a control
#: below proves that on the home file's real text.
_SANCTIONED = frozenset({"check_nanometres"})


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


def _string_value(node: ast.expr) -> str | None:
    """Read a plain string or f-string literal's constant text, or ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            piece.value
            for piece in node.values
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
        )
    return None


def _raises_a_type_error(node: ast.AST) -> bool:
    """Is this statement exactly ``raise TypeError(...)``?"""
    return (
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "TypeError"
    )


def _tests_int_exactness(test: ast.expr) -> bool:
    """Does this expression ask whether a value is *exactly* an ``int``?

    ``type(x) is int``, its negation, and ``isinstance(x, int)`` on a bare
    ``int`` -- never a tuple. ``isinstance(c, (int, float))`` asks a looser
    question than this rule does, and admitting it fires on guards that are
    not this one. A boolean operand is descended into, so the real
    ``type(x) is not int or x < 1`` in ``sources/ai_pdf.py`` counts as asking.
    """
    if isinstance(test, ast.BoolOp):
        return any(_tests_int_exactness(value) for value in test.values)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _tests_int_exactness(test.operand)
    if isinstance(test, ast.Compare):
        return (
            isinstance(test.left, ast.Call)
            and isinstance(test.left.func, ast.Name)
            and test.left.func.id == "type"
            and all(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops)
            and any(
                isinstance(other, ast.Name) and other.id == "int"
                for other in test.comparators
            )
        )
    return (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and isinstance(test.args[1], ast.Name)
        and test.args[1].id == "int"
    )


def refuses_a_non_int_with_a_type_error(node: ast.AST) -> bool:
    """Is this an ``if`` refusing a non-``int`` by raising ``TypeError``?"""
    return (
        isinstance(node, ast.If)
        and _tests_int_exactness(node.test)
        and any(_raises_a_type_error(statement) for statement in node.body)
    )


def states_the_guards_phrase(node: ast.AST) -> bool:
    """Does this ``raise TypeError`` carry the guard's own wording?"""
    if not isinstance(node, ast.Raise) or not _raises_a_type_error(node):
        return False
    call = node.exc
    if not isinstance(call, ast.Call):
        return False
    return any(_PHRASE in (_string_value(arg) or "") for arg in call.args)


def restates_the_guard(node: ast.AST) -> bool:
    """The union of the two arms, and the union is the point.

    A paraphrase evades a text match; a copy that borrows the owner's
    wording while delegating its type test to a helper evades a shape
    match. A gate decided by either arm alone is decided by wording or by
    spelling rather than by the rule itself.
    """
    return refuses_a_non_int_with_a_type_error(node) or states_the_guards_phrase(node)


def _offending_lines(source: str, sanctioned: Collection[str] = ()) -> list[int]:
    """Every line outside ``sanctioned`` where ``source`` restates the guard."""
    return sorted(
        {
            node.lineno
            for node in _outside(ast.parse(source), sanctioned)
            if isinstance(node, ast.stmt) and restates_the_guard(node)
        }
    )


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


# ---------------------------------------------------------------------------
# proof the scanner fires, and does not over-fire
# ---------------------------------------------------------------------------


def test_the_scanner_finds_the_duplication_it_exists_to_catch():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert _offending_lines(
        "def f(value):\n"
        "    if type(value) is not int:\n"
        '        raise TypeError(f"x must be a whole number of nanometres, not {value!r}")\n'
    )


def test_a_plain_string_argument_is_read_too():
    """Not every duplicate would bother with an f-string."""
    assert _offending_lines(
        'raise TypeError("y must be a whole number of nanometres")'
    )


def test_a_paraphrased_duplicate_is_caught_by_its_own_mechanism():
    """The guilty probe for the text arm's blind spot.

    A genuine second implementation of the rule, semantically identical to
    ``check_nanometres`` but worded differently, shares not one word of the
    owner's message. A gate decided by prose reports nothing here.
    """
    assert _offending_lines(
        "def f(name, value):\n"
        "    if type(value) is not int:\n"
        '        raise TypeError(f"{name} must be an integral count of nanometres, not {value!r}")\n'
    )
    # The old text matcher's verdict on the same source, so the arm this
    # test adds is provably what catches it rather than the retained one.
    assert not any(
        states_the_guards_phrase(node)
        for node in ast.walk(
            ast.parse(
                "def f(name, value):\n"
                "    if type(value) is not int:\n"
                '        raise TypeError(f"{name} must be an integral count of '
                'nanometres, not {value!r}")\n'
            )
        )
    )


def test_an_int_check_that_raises_something_else_is_not_this_rule():
    """``sources/ai_pdf.py``'s real form-depth guard: exact-int, ``ValueError``.

    The int clause really is asked -- asserted, so this probe cannot pass by
    failing to reach the arm it constrains -- and only the raised type differs.
    """
    source = (
        "if type(form_depth) is not int or form_depth < 1:\n"
        '    raise ValueError(f"form depth must be a whole number of levels from 1, '
        'not {form_depth!r}")\n'
    )
    guard = ast.parse(source).body[0]
    assert isinstance(guard, ast.If) and _tests_int_exactness(guard.test)
    assert _offending_lines(source) == []


def test_an_int_check_that_merely_returns_is_not_this_rule():
    """``emitters/drawing/content.py``'s real grid label: exact-int, no raise."""
    source = (
        "if type(grid_nm) is not int or grid_nm <= 0:\n"
        '    return "NOT RECORDED"\n'
    )
    guard = ast.parse(source).body[0]
    assert isinstance(guard, ast.If) and _tests_int_exactness(guard.test)
    assert _offending_lines(source) == []


def test_a_type_error_guarded_by_no_int_test_is_not_this_rule():
    """``check_millimetres``'s real shape, which shares the home file.

    It raises ``TypeError`` on a failed exact-type check like the owner
    does, but the type it checks is ``float`` -- so the shape arm cannot
    reach it, and the home file's exemption need not name it.
    """
    source = (
        "if type(value) is not float or not math.isfinite(value):\n"
        '    raise TypeError(f"{owner}.{name} must be a finite number of millimetres, '
        'not {value!r}")\n'
    )
    guard = ast.parse(source).body[0]
    assert isinstance(guard, ast.If) and not _tests_int_exactness(guard.test)
    assert _offending_lines(source) == []


def test_a_tuple_narrowed_isinstance_is_not_this_rule():
    """``isinstance(x, (int, float))`` asks a looser question than the rule.

    The narrowing to a bare ``int`` is deliberate: it is what keeps the
    family's innocent probe green over code that merely admits integers.
    """
    source = (
        "if not isinstance(value, (int, float)):\n"
        '    raise TypeError("value must be a number")\n'
    )
    assert _offending_lines(source) == []


def test_a_second_statement_in_the_rules_own_home_is_caught():
    """The guilty home probe: the exemption is a definition, not a file.

    The home file's real text with a second guard spliced in beside the
    owner -- in memory, never on disk -- offends even under the sanction
    list, which a whole-file exclusion would have hidden.
    """
    spliced = GUARD_HOME.read_text(encoding="utf-8") + (
        "\n\ndef _second_nanometre_guard(name, value):\n"
        "    if type(value) is not int:\n"
        '        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")\n'
    )
    assert _offending_lines(spliced, _SANCTIONED)


def test_the_exemption_covers_the_owning_definition_and_nothing_more():
    """The anchor probe, matched to the guilty one above.

    Unexempted, the home really does state the rule -- so the exemption is
    load-bearing and a renamed owner fails loudly rather than silently
    widening. Exempted, nothing else in the home states it, so the
    exemption is no wider than the definition it names.
    """
    home = GUARD_HOME.read_text(encoding="utf-8")

    assert _offending_lines(home), "the home no longer states the rule the gate exempts"
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


def test_the_guard_is_stated_in_exactly_one_definition():
    """No definition outside ``check_nanometres`` enforces this rule itself."""
    offenders = {
        str(path): lines
        for path in _source_files()
        for lines in [
            _offending_lines(
                path.read_text(encoding="utf-8"),
                _SANCTIONED if path == GUARD_HOME else (),
            )
        ]
        if lines
    }
    assert offenders == {}, (
        "a definition outside stompmodel.units.check_nanometres states the "
        "whole-nanometre guard again -- call check_nanometres instead"
    )
