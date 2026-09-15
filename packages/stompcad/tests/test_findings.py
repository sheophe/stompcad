"""The count the sidebar carries, and the seam plan 3 fills."""

from __future__ import annotations

from stompcad.workbench import findings
from stompmodel.diagnostics import Diagnostic, Severity

__all__: list[str] = []

_ERROR = Diagnostic(Severity.ERROR, "cannot-enter", "board 1 never enters the case")
_WARNING = Diagnostic(Severity.WARNING, "off-grid", "a hole moved 0.06 mm")
_INFO = Diagnostic(Severity.INFO, "inferred-enclosure", "the part came from tar-case.stp")


def test_the_count_covers_errors_and_warnings_only() -> None:
    """Decision 4: a run that inferred an enclosure succeeded; it owes nothing."""
    assert findings.counted(findings.classify([_ERROR, _WARNING, _INFO])) == 2


def test_information_is_listed_even_though_it_is_never_counted() -> None:
    """Listed in the place, never counted and never marking anything."""
    assert len(findings.classify([_INFO])) == 1


def test_every_diagnostic_becomes_exactly_one_finding() -> None:
    """A finding belongs to exactly one family, so classification never fans out."""
    assert len(findings.classify([_ERROR, _WARNING, _INFO])) == 3
