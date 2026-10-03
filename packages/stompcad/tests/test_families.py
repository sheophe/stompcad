"""Every code has one family, every remedy names a real row, and the payload decides."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad.settings import Settings
from stompcad.workbench.families import (
    _WALL_ROW,
    CODES,
    FAMILIES,
    NEAR_MISS,
    REMEDIES,
    Family,
    Register,
    Remedy,
    family_of,
    register_of,
    remedy_of,
    secondary_of,
)
from stompcad.workbench.keys import Place
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
    """``form_depth`` is not its place's first row, which is where a place alone lands."""
    assert remedy_of(Diagnostic.warning("nesting-truncated", "…")) == REMEDIES["nesting-truncated"]
    assert REMEDIES["nesting-truncated"].field == "form_depth"


def test_a_model_that_disagrees_sends_the_builder_to_the_part() -> None:
    """The part chooses the model, so the part is where a wrong one is answered."""
    assert REMEDIES["wrong-case-model"].field == "case"


def test_a_near_miss_goes_to_the_tolerance_and_an_axisless_part_nowhere() -> None:
    """The control for the router: the same code, one remedy and none."""
    assert remedy_of(_NEAR_MISS) == NEAR_MISS
    assert remedy_of(_AXISLESS) is None


def test_worth_knowing_and_the_size_check_have_no_remedy() -> None:
    """Information marks no place; the size check has no row to go to."""
    assert remedy_of(Diagnostic.warning("multiple-boards", "…")) is None
    assert remedy_of(Diagnostic.info("reference-size-mismatch", "…")) is None


def test_no_worth_knowing_code_has_a_remedy() -> None:
    """Decision 11: a code marking no place cannot also name a row to jump to."""
    assert not FAMILIES[Family.KNOWING].codes & set(REMEDIES)


def test_a_second_route_is_offered_where_there_honestly_is_one() -> None:
    assert "grid" in secondary_of(Diagnostic.warning("off-grid", "…"))
    assert "artwork" in secondary_of(_NEAR_MISS)
    assert secondary_of(_AXISLESS) == ""


def _wall(code: str) -> Diagnostic:
    """A refusal as the wall stage raises it: it names the component."""
    return Diagnostic.error(code, "x", data=(("designator", "J1"), ("surface", "right")))


def _panel(code: str) -> Diagnostic:
    """The same code as the panel path raises it, with the payload it really has.

    Off-face and through-boss name the drilled face; the unstocked-diameter
    refusal names the measurement and the standard, and neither a face nor a
    component.
    """
    if code == "unknown-diameter":
        return Diagnostic.error(
            code, "x", data=(("diameter_nm", 3_000_000), ("standard", "metric")),
        )
    return Diagnostic.error(code, "x", data=(("face", "box"),))


_SHARED = ["hole-off-face", "hole-through-boss", "unknown-diameter"]


@pytest.mark.parametrize("code", _SHARED)
def test_a_wall_refusal_belongs_to_the_settings(code: str) -> None:
    """The artwork never mentions a wall hole, so "change the artwork" is false."""
    assert family_of(_wall(code)) is Family.SETTING


@pytest.mark.parametrize("code", _SHARED)
def test_a_wall_refusal_jumps_to_the_part_it_named(code: str) -> None:
    """The component it was named for is what a builder can change."""
    assert remedy_of(_wall(code)) == Remedy(Place.BOARDS, "wall_reference")


@pytest.mark.parametrize("code", _SHARED)
def test_the_same_code_on_the_panel_still_sends_them_to_the_drawing(code: str) -> None:
    """The control. One code, two surfaces, two honest remedies -- told apart by
    the payload, as ``unmatched-part`` already is."""
    assert family_of(_panel(code)) is Family.ARTWORK
    assert remedy_of(_panel(code)) is None


def test_the_wall_row_is_stated_once() -> None:
    """Every wall answer is the one object, so correcting it corrects all."""
    assert REMEDIES["wall-feature-unreachable"] is _WALL_ROW
    assert REMEDIES["component-claimed-twice"] is _WALL_ROW
    assert remedy_of(_wall("hole-off-face")) is _WALL_ROW


def test_a_designator_both_filters_claim_offers_the_other_expression_too() -> None:
    """Either expression can give it up, so the sentence says so rather than
    sending a builder to one row as though the other were not a choice."""
    claimed = Diagnostic.error("component-claimed-twice", "x", data=(("designator", "J1"),))
    assert "panel-reference" in secondary_of(claimed)
