"""Repository documentation policy checks."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from stompmodel.codec import FORMAT
from tools.check_docstrings import find_long_docstrings

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
STOMPMODEL = REPO / "packages" / "stompmodel"
STOMPGEOM = REPO / "packages" / "stompgeom"
# The scripts stayed at the repository root when the package moved beneath it,
# and a root that does not exist scans as empty rather than failing, so the two
# levels are named apart to keep the audit's reach honest. stompmodel and
# stompgeom are sibling workspace members, not subtrees of this package, so
# each one's src and tests are named apart again.
PYTHON_ROOTS = (
    PACKAGE / "src",
    PACKAGE / "tests",
    REPO / "tools",
    STOMPMODEL / "src",
    STOMPMODEL / "tests",
    STOMPGEOM / "src",
    STOMPGEOM / "tests",
)


def test_the_scanner_reports_the_owner_and_physical_line_count(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text('def example():\n    """one\n    two\n    three"""\n', encoding="utf-8")

    (violation,) = find_long_docstrings((sample,), max_lines=2)

    assert violation.path == sample
    assert violation.line == 2
    assert violation.owner == "example"
    assert violation.lines == 3


def test_the_repository_docstring_audit_reports_every_over_length_docstring():
    """The ceiling guides new prose; it does not gate the suite, so this only warns."""
    violations = find_long_docstrings(PYTHON_ROOTS)
    if not violations:
        return
    details = "\n".join(
        f"{item.path.relative_to(REPO)}:{item.line}: "
        f"{item.owner} spans {item.lines} lines"
        for item in violations
    )
    warnings.warn(f"docstrings over 10 lines:\n{details}", stacklevel=1)


def test_the_collider_spec_names_the_format_string_the_codec_actually_writes():
    """A plan-3 reader built to this spec must recognise stompdrill's document.

    Compared mechanically against ``stompmodel.codec.FORMAT`` rather than by
    eye, so the two cannot drift apart again the way they once did.
    """
    spec = REPO / "docs" / "specs" / "stompcollider-technical.md"
    text = spec.read_text(encoding="utf-8")

    found = re.search(r"Drill document \(`([^`]+)` v\d+\)", text)

    assert found, f"{spec}: the drill-document row was not found as expected"
    assert found.group(1) == FORMAT
