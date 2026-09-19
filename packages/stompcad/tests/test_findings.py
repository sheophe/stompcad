"""The count the sidebar carries, and where each finding's remedy sends it."""

from __future__ import annotations

import pytest

from stompcad.workbench import findings
from stompcad.workbench.families import NEAR_MISS, Family, Register
from stompcad.workbench.keys import Place
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


def test_classify_gives_every_finding_a_family() -> None:
    found = findings.classify([
        Diagnostic.warning("off-grid", "hole 3 moved onto the grid"),
        Diagnostic.error("wrong-enclosure", "1590B does not match the outline"),
        Diagnostic.info("zero-clearance", "RV1 touches the wall"),
    ])
    assert [finding.family for finding in found] == [Family.ARTWORK, Family.SETTING, Family.FIT]


def test_classify_keeps_the_order_the_run_raised_them_in() -> None:
    """Grouping is done where lines are drawn; the record stays chronological."""
    codes = ("zero-clearance", "off-grid", "wrong-enclosure")
    found = findings.classify([Diagnostic.warning(code, "…") for code in codes])
    assert tuple(finding.diagnostic.code for finding in found) == codes


def test_a_setting_finding_carries_its_row_and_marks_its_place() -> None:
    (finding,) = findings.classify([Diagnostic.warning("grid-too-fine", "…")])
    assert finding.remedy is not None and finding.remedy.field == "grid_mm"
    assert finding.place is Place.DRILLING


def test_a_near_miss_carries_the_tolerance() -> None:
    (finding,) = findings.classify([
        Diagnostic.warning(
            "unmatched-part", "RV1 lands 0.412 mm from hole 7, its nearest",
            data=(("designator", "RV1"), ("nearest_hole", 7), ("offset_nm", 412000)),
        )
    ])
    assert finding.remedy == NEAR_MISS


def test_information_carries_no_row() -> None:
    (finding,) = findings.classify([Diagnostic.warning("multiple-boards", "…")])
    assert finding.remedy is None and finding.place is None


def test_a_fit_finding_carries_its_register() -> None:
    (shallow, clash) = findings.classify([
        Diagnostic.warning("enclosure-too-shallow", "…"),
        Diagnostic.warning("clash", "…"),
    ])
    assert shallow.register is Register.DO_NOT_BUILD
    assert clash.register is Register.INSPECT


@pytest.mark.parametrize(
    "code", ["multiple-boards", "unknown-enclosure", "case-orientation-unverifiable"]
)
def test_a_warning_worth_knowing_is_not_counted(code: str) -> None:
    """Decision 4. Each of these is a WARNING at its raise site, and each is
    information: a deliberate three-board pedal raises the first every time."""
    assert findings.counted(findings.classify([Diagnostic.warning(code, "…")])) == 0


def test_a_warning_outside_worth_knowing_is_counted() -> None:
    """The control for the test above: the exclusion is the family's, not the severity's."""
    assert findings.counted(findings.classify([Diagnostic.warning("off-grid", "…")])) == 1


def test_classification_changes_no_severity() -> None:
    """The count is the badge's business; what a run earned is untouched."""
    raised = Diagnostic.warning("multiple-boards", "three boards in one file")
    (finding,) = findings.classify([raised])
    assert finding.diagnostic is raised
