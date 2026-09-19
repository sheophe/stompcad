"""Every code has one family, every remedy names a real row, and the payload decides."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad.settings import Settings
from stompcad.workbench.families import (
    CODES,
    FAMILIES,
    NEAR_MISS,
    REMEDIES,
    Family,
    Register,
    family_of,
    register_of,
    remedy_of,
    secondary_of,
)
from stompmodel.diagnostics import Diagnostic, Severity

__all__: list[str] = []

_NEAR_MISS = Diagnostic.warning(
    "unmatched-part",
    "RV1 lands 0.412 mm from hole 7, its nearest",
    data=(("designator", "RV1"), ("nearest_hole", 7), ("offset_nm", 412000)),
)
_AXISLESS = Diagnostic.warning(
    "unmatched-part",
    "RV1 yields no axis and pairs with no hole",
    data=(("designator", "RV1"),),
)


def test_every_family_has_prose_and_a_way_out() -> None:
    """A family that says nothing is a heading, not a remedy."""
    for family in Family:
        assert FAMILIES[family].means, family
        assert FAMILIES[family].routes, family


def test_every_classified_code_is_in_exactly_one_family() -> None:
    """Decision 11: one membership. Checked across the table, not per row."""
    seen: dict[str, Family] = {}
    for family in Family:
        for code in FAMILIES[family].codes:
            assert code not in seen, f"{code} is in {seen.get(code)} and {family}"
            seen[code] = family
    assert set(seen) | {"unmatched-part"} == CODES


def test_a_code_with_one_payload_shape_resolves_statically() -> None:
    assert family_of(Diagnostic.warning("off-grid", "hole 3 moved")) is Family.ARTWORK


def test_unmatched_part_routes_on_its_payload() -> None:
    """One code, two remedies: a near miss is a setting, a part with no axis a board."""
    assert family_of(_NEAR_MISS) is Family.SETTING
    assert family_of(_AXISLESS) is Family.BOARD


@pytest.mark.parametrize(
    ("code", "severity", "register"),
    [
        ("cannot-enter", Severity.ERROR, Register.WITHHELD),
        ("enclosure-too-shallow", Severity.WARNING, Register.DO_NOT_BUILD),
        ("every-seating-clashes", Severity.INFO, Register.DO_NOT_BUILD),
        ("clash", Severity.WARNING, Register.INSPECT),
        ("seated-short", Severity.WARNING, Register.INSPECT),
        ("ambiguous-placement", Severity.WARNING, Register.INSPECT),
        ("zero-clearance", Severity.INFO, Register.INSPECT),
    ],
)
def test_the_register_is_decided_by_the_code_before_the_severity(
    code: str, severity: Severity, register: Register
) -> None:
    """Every fit code at the severity its raise site uses. Three rows disagree
    with a severity-only rule, which is the point."""
    assert register_of(Diagnostic(severity, code, "…")) is register


def test_no_register_outside_the_fit() -> None:
    assert register_of(Diagnostic.warning("off-grid", "…")) is None


def test_every_remedy_names_a_row_its_place_holds() -> None:
    """A jump to a field that does not exist lands on the place's first row."""
    settings = Settings.of_defaults(Path("/project/tar.ai"))
    for remedy in (*REMEDIES.values(), NEAR_MISS):
        record = getattr(settings, remedy.place.value)
        fields = {field for field, _label, _stated in record.rows()}
        assert remedy.field in fields, f"{remedy.place.value} has no {remedy.field} row"


def test_a_remedy_carries_the_field_not_just_the_place() -> None:
    """None of these is its place's first row, which is where a place alone lands."""
    assert remedy_of(Diagnostic.warning("nesting-truncated", "…")) == REMEDIES["nesting-truncated"]
    assert REMEDIES["nesting-truncated"].field == "form_depth"
    assert REMEDIES["wrong-case-model"].field == "case_model"


def test_a_near_miss_goes_to_the_tolerance_and_an_axisless_part_nowhere() -> None:
    """The control for the router: the same code, one remedy and none."""
    assert remedy_of(_NEAR_MISS) == NEAR_MISS
    assert remedy_of(_AXISLESS) is None


def test_worth_knowing_and_the_size_check_have_no_remedy() -> None:
    """Information marks no place; the size check has no row to go to."""
    assert remedy_of(Diagnostic.warning("multiple-boards", "…")) is None
    assert remedy_of(Diagnostic.info("reference-size-mismatch", "…")) is None


def test_a_second_route_is_offered_where_there_honestly_is_one() -> None:
    assert "grid" in secondary_of(Diagnostic.warning("off-grid", "…"))
    assert "artwork" in secondary_of(_NEAR_MISS)
    assert secondary_of(_AXISLESS) == ""
