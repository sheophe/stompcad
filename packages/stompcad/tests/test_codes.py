"""Every code the tools raise has a family, and the table knows what the driver reaches."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad.workbench.families import CODES, FAMILIES, REMEDIES, Family
from tools.list_diagnostic_codes import UNREACHABLE, codes_in, reached, unreadable_in

__all__: list[str] = []

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
#: Anchored to this file, not the working directory: the documented package
#: command runs from ``packages/stompcad``, where a relative root reads nothing.
_SRC = tuple(
    REPO / "packages" / name / "src"
    for name in ("stompdrill", "stompcollider", "stompmodel", "stompcad")
)

#: A code enum, so a control can tell "refused" from "found nothing to add".
_ENUM = "from enum import Enum\nclass Rejection(Enum):\n    GONE = 'hole-gone'\n"


def _tree(root: Path, files: dict[str, str]) -> Path:
    """A throwaway source tree, for the tool's controls."""
    src = root / "src"
    for name, text in files.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return src


def _dead(src: Path, entry: str) -> set[str]:
    """The codes in this tree that nothing reachable from ``entry`` raises."""
    live = reached([src], entry)
    codes = codes_in([src], ("tool",))
    return {code for code, sites in codes.items() if not any(s.unit in live for s in sites)}


# -- the real tree ------------------------------------------------------------


def test_the_roots_exist_and_hold_sources() -> None:
    for root in _SRC:
        assert root.is_dir() and any(root.rglob("*.py")), root


def test_every_code_a_tool_can_raise_has_a_family() -> None:
    missing = sorted(set(codes_in(_SRC)) - CODES)
    assert not missing, f"no family for: {', '.join(missing)}"


def test_no_family_row_names_a_code_that_no_longer_exists() -> None:
    dead = sorted(CODES - set(codes_in(_SRC)))
    assert not dead, f"no tool raises: {', '.join(dead)}"


def test_the_driver_reaches_every_row_but_the_recorded_ones() -> None:
    """Decision 11's second half, per class or function rather than per file.

    A guard, not a proof: a new entry in ``UNREACHABLE`` is confirmed by
    reading the driver before it is accepted, never because this passed.
    """
    live = reached(_SRC, "stompcad.drive")
    unreachable = {
        code
        for code, sites in codes_in(_SRC).items()
        if not any(site.unit in live for site in sites)
    }
    assert unreachable == set(UNREACHABLE)


def test_each_unreachable_row_says_why() -> None:
    for code, reason in UNREACHABLE.items():
        assert code in CODES, code
        assert "never" in reason or "only" in reason, code


def test_every_reachable_setting_or_choice_has_a_remedy() -> None:
    """These two families promise a row; a reachable code without one breaks it."""
    promised = FAMILIES[Family.SETTING].codes | FAMILIES[Family.CANDIDATES].codes
    for code in promised - set(UNREACHABLE):
        assert code in REMEDIES, code


def test_every_call_site_is_read() -> None:
    assert unreadable_in(_SRC) == ()


# -- what the scanner reads, and what it refuses --------------------------------


def test_a_literal_code_is_read(tmp_path: Path) -> None:
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f():\n    return Diagnostic.warning('plain-code', 'x')\n",
    })
    assert set(codes_in([src], ("tool",))) == {"plain-code"}


def test_an_aliased_or_directly_built_diagnostic_is_read(tmp_path: Path) -> None:
    """Both are legitimate ways to raise one; a scan blind to them would shrink."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": (
            "from stompmodel.diagnostics import Diagnostic as D\n"
            "def f():\n    return D.error('aliased-code', 'x')\n"
            "def g():\n    return Diagnostic(Severity.ERROR, 'built-code', 'x')\n"
            "def h():\n    return Diagnostic(Severity.INFO, code='named-code', message='x')\n"
        ),
    })
    assert set(codes_in([src], ("tool",))) == {"aliased-code", "built-code", "named-code"}


def test_a_built_diagnostic_with_a_computed_code_is_reported(tmp_path: Path) -> None:
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f(code):\n    return Diagnostic(Severity.ERROR, code, 'x')\n",
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_an_enum_code_is_credited_to_where_it_is_raised(tmp_path: Path) -> None:
    """Not to where the enum is defined: reachability follows the raise site."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/base.py": _ENUM,
        "tool/check.py": (
            "from .base import Rejection\n"
            "def reject(rejection: Rejection):\n"
            "    return Diagnostic.error(rejection.value, 'x')\n"
        ),
    })
    sites = codes_in([src], ("tool",))["hole-gone"]
    assert {site.path.name for site in sites} == {"check.py"}


@pytest.mark.parametrize("parameter", ["code", "code: Other"])
def test_a_value_on_a_parameter_not_typed_as_a_code_enum_is_reported(
    tmp_path: Path, parameter: str
) -> None:
    """A code enum is present, so accepting this call would add its codes: the
    difference between refused and read is visible, which is what makes this a
    control rather than a test that passes either way."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/base.py": _ENUM,
        "tool/a.py": (
            "from enum import Enum\nclass Other(Enum):\n    NEW = 'new-code'\n"
            f"def f({parameter}):\n    return Diagnostic.error(code.value, 'x')\n"
        ),
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_member_value_is_reported(tmp_path: Path) -> None:
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": (
            "from enum import Enum\nclass Other(Enum):\n    NEW = 'new-code'\n"
            "def f():\n    return Diagnostic.error(Other.NEW.value, 'x')\n"
        ),
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_typed_value_with_no_enum_to_read_is_reported(tmp_path: Path) -> None:
    """Typed as a code enum, but none is defined: nothing is known, so say so."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/check.py": (
            "def reject(rejection: Rejection):\n"
            "    return Diagnostic.error(rejection.value, 'x')\n"
        ),
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_code_enum_defined_twice_is_refused(tmp_path: Path) -> None:
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/one.py": _ENUM,
        "tool/two.py": _ENUM,
    })
    with pytest.raises(ValueError, match="more than once"):
        codes_in([src], ("tool",))


def test_an_unrelated_enum_is_not_a_code(tmp_path: Path) -> None:
    """A fixture with a real raise site: pooling ``FrameStyle`` into the code
    enums would widen the values a typed parameter resolves to, so this can
    actually fail rather than passing regardless of ``_CODE_ENUMS``."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/base.py": (
            _ENUM + "class FrameStyle(Enum):\n    THIN = 'thin'\n"
        ),
        "tool/check.py": (
            "from .base import Rejection\n"
            "def reject(rejection: Rejection):\n"
            "    return Diagnostic.error(rejection.value, 'x')\n"
        ),
    })
    assert set(codes_in([src], ("tool",))) == {"hole-gone"}


def test_a_missing_root_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        codes_in([tmp_path / "nowhere"], ("tool",))


def test_a_module_qualified_raiser_is_read(tmp_path: Path) -> None:
    """``pkg.Diagnostic.error(...)`` reads the same as an imported name."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f():\n    return diagnostics.Diagnostic.error('qualified-code', 'x')\n",
    })
    assert set(codes_in([src], ("tool",))) == {"qualified-code"}


def test_a_module_qualified_constructor_is_read(tmp_path: Path) -> None:
    """``pkg.Diagnostic(severity, code, ...)`` is the built form, qualified."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": (
            "def f():\n"
            "    return sd.Diagnostic(Severity.ERROR, 'qualified-built-code', 'x')\n"
        ),
    })
    assert set(codes_in([src], ("tool",))) == {"qualified-built-code"}


def test_a_replace_call_with_a_code_keyword_is_reported(tmp_path: Path) -> None:
    """``dataclasses.replace`` can set a code without any recognised raiser."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f(d):\n    return dataclasses.replace(d, code='x')\n",
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_bare_replace_call_with_a_code_keyword_is_reported(tmp_path: Path) -> None:
    """A bare imported ``replace`` is the same call, unqualified."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f(d):\n    return replace(d, code='x')\n",
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_raiser_passed_as_a_value_is_reported(tmp_path: Path) -> None:
    """``Diagnostic.error`` handed to ``partial`` is never a call's ``.func``."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "def f():\n    return functools.partial(Diagnostic.error, 'x')\n",
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_a_raiser_bound_to_a_name_is_reported(tmp_path: Path) -> None:
    """Aliasing a raiser and calling the alias hides the code from the scan."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/a.py": "make = Diagnostic.warning\ndef f():\n    return make('x', 'y')\n",
    })
    assert codes_in([src], ("tool",)) == {}
    assert len(unreadable_in([src], ("tool",))) == 1


def test_an_annotated_enum_member_is_read(tmp_path: Path) -> None:
    """A member's value counts whether or not it carries a type annotation."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/base.py": "from enum import Enum\nclass Rejection(Enum):\n    GONE: str = 'hole-gone'\n",
        "tool/check.py": (
            "from .base import Rejection\n"
            "def reject(rejection: Rejection):\n"
            "    return Diagnostic.error(rejection.value, 'x')\n"
        ),
    })
    assert set(codes_in([src], ("tool",))) == {"hole-gone"}


# -- what the graph reaches ---------------------------------------------------------

_STAGES = (
    "class Used:\n    def run(self):\n        return Diagnostic.warning('used-code', 'x')\n"
    "class Unused:\n    def run(self):\n        return Diagnostic.warning('unused-code', 'x')\n"
)


def test_reachability_tells_two_classes_in_one_file_apart(tmp_path: Path) -> None:
    """The control a filename test fails: same file, one reached, one not."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/stages.py": _STAGES,
        "entry.py": "from tool.stages import Used\ndef drive():\n    return Used().run()\n",
    })
    assert _dead(src, "entry") == {"unused-code"}


def test_reachability_follows_a_package_re_export(tmp_path: Path) -> None:
    src = _tree(tmp_path, {
        "tool/__init__.py": "from .stages import Used, Unused\n",
        "tool/stages.py": _STAGES,
        "entry.py": "from tool import Used\ndef drive():\n    return Used().run()\n",
    })
    assert _dead(src, "entry") == {"unused-code"}


def test_reachability_follows_an_import_inside_a_function(tmp_path: Path) -> None:
    """An ordinary local import is a real edge; missing it calls live code dead."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/stages.py": _STAGES,
        "entry.py": "def drive():\n    from tool.stages import Used\n    return Used().run()\n",
    })
    assert _dead(src, "entry") == {"unused-code"}


def test_a_type_named_only_in_an_annotation_is_not_reached(tmp_path: Path) -> None:
    """Naming a type is not calling it; following it would call dead code live."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/stages.py": _STAGES,
        "entry.py": (
            "from tool.stages import Unused, Used\n"
            "def drive(spare: Unused) -> Unused:\n    return Used().run()\n"
        ),
    })
    assert _dead(src, "entry") == {"unused-code"}


def test_a_diagnostic_built_at_import_counts_only_if_something_keeps_it(
    tmp_path: Path,
) -> None:
    """A named constant is reached when it is named; a loose statement's result
    is discarded, so no run can report it. Calling either unreachable errs
    loud, failing the real test for somebody to read; the graph also errs
    quiet elsewhere, crediting a dead method inside a reached class as live."""
    src = _tree(tmp_path, {
        "tool/__init__.py": "",
        "tool/stages.py": (
            _STAGES
            + "KEPT = Diagnostic.info('kept-code', 'x')\n"
            + "SPARE = Diagnostic.info('spare-code', 'x')\n"
        ),
        "tool/loose.py": "def helper():\n    return 1\nDiagnostic.info('loose-code', 'x')\n",
        "entry.py": (
            "from tool.loose import helper\nfrom tool.stages import KEPT, Used\n"
            "def drive():\n    helper()\n    return [KEPT, Used().run()]\n"
        ),
    })
    assert _dead(src, "entry") == {"unused-code", "spare-code", "loose-code"}
