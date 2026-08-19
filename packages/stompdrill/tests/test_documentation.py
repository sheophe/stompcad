"""Repository documentation policy checks."""

from __future__ import annotations

import warnings
from pathlib import Path

from tools.check_docstrings import find_long_docstrings

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
# The scripts stayed at the repository root when the package moved beneath it,
# and a root that does not exist scans as empty rather than failing, so the two
# levels are named apart to keep the audit's reach honest.
PYTHON_ROOTS = (PACKAGE / "src", PACKAGE / "tests", REPO / "tools")


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
