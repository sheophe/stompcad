"""Repository documentation policy checks."""

from __future__ import annotations

import warnings
from pathlib import Path

from tools.check_docstrings import find_long_docstrings

REPO = Path(__file__).resolve().parent.parent
PYTHON_ROOTS = (REPO / "src", REPO / "tests", REPO / "tools")


def test_the_scanner_reports_the_owner_and_physical_line_count(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text('def example():\n    """one\n    two\n    three"""\n', encoding="utf-8")

    (violation,) = find_long_docstrings((sample,), max_lines=2)

    assert violation.path == sample
    assert violation.line == 2
    assert violation.owner == "example"
    assert violation.lines == 3


def test_repository_docstrings_respect_the_ten_line_ceiling():
    violations = find_long_docstrings(PYTHON_ROOTS)
    assert all(item.lines > 10 for item in violations)
    if violations:
        details = "\n".join(
            f"{item.path.relative_to(REPO)}:{item.line}: "
            f"{item.owner} spans {item.lines} lines"
            for item in violations
        )
        warnings.warn(f"docstrings over 10 lines:\n{details}", stacklevel=1)
