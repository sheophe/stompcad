"""The outline containment stage, driven by hand-built drill data."""

from __future__ import annotations

from stompdrill.pipeline import CheckOutlineContainment
from stompmodel.diagnostics import Severity
from stompmodel.model import ReferenceOutline, StageRun
from stompmodel.protocols import Stage
from stompmodel.units import Nanometre
from tests.conftest import at, codes, make_data

__all__: list[str] = []

MM = 1_000_000

#: 100 x 60 mm. Half-extents of 50 and 30 mm, so every boundary case below is a
#: whole number of millimetres and no assertion rests on an odd nanometre.
PANEL = ReferenceOutline(Nanometre(100 * MM), Nanometre(60 * MM))

#: The widest hole that fits centred on the +x edge: 50 - 7/2 = 46.5 mm.
ON_THE_EDGE = 46_500_000


def run(*holes, reference=PANEL):
    """Apply the stage to hand-built holes in the canonical, outline-centred frame."""
    return CheckOutlineContainment().apply(make_data(*holes, reference=reference))


def only(data):
    """The single diagnostic the stage raised, or fail saying how many there were."""
    assert len(data.diagnostics) == 1, codes(data)
    return data.diagnostics[0]


def test_it_satisfies_the_stage_protocol():
    assert isinstance(CheckOutlineContainment(), Stage)


def test_describe_names_the_stage_and_takes_no_parameters():
    assert CheckOutlineContainment().describe() == StageRun("check-outline-containment", ())


def test_a_hole_well_inside_the_outline_raises_nothing():
    assert codes(run(at(0, 0, 7 * MM, index=1))) == []


def test_a_hole_whose_edge_lands_exactly_on_the_boundary_is_contained():
    """Touching is inside. The inclusive boundary is the decision, not an accident."""
    assert codes(run(at(ON_THE_EDGE, 0, 7 * MM, index=1))) == []


def test_a_hole_one_nanometre_past_the_boundary_is_reported():
    """One nanometre, so the pair with the test above pins the comparison exactly."""
    assert codes(run(at(ON_THE_EDGE + 1, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_whose_centre_is_inside_but_whose_edge_is_not_is_reported():
    """The extent is the test, not the centre: 48 mm is inside, 48 + 3.5 is not."""
    assert codes(run(at(48 * MM, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_past_the_negative_edge_is_reported_too():
    """Absolute value, not a one-sided comparison."""
    assert codes(run(at(-48 * MM, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_the_short_axis_is_checked_as_well_as_the_long_one():
    """Inside on x, outside on y. A stage that checked only x would pass everything."""
    assert codes(run(at(0, 28 * MM, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_past_the_negative_short_edge_is_reported_too():
    assert codes(run(at(0, -28 * MM, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_it_is_a_warning_so_the_artefacts_are_still_written():
    assert only(run(at(48 * MM, 0, 7 * MM, index=1))).severity is Severity.WARNING


def test_each_axis_reports_its_own_overshoot():
    """Unequal on purpose: equal figures would not catch the two swapped."""
    finding = only(run(at(48 * MM, 29 * MM, 7 * MM, index=1)))

    assert finding.get("overshoot_x_nm") == 1_500_000
    assert finding.get("overshoot_y_nm") == 2_500_000


def test_an_axis_that_is_inside_reports_no_overshoot():
    """Nought, not the negative slack: a contained axis lost no metal."""
    finding = only(run(at(0, 29 * MM, 7 * MM, index=1)))

    assert finding.get("overshoot_x_nm") == 0
    assert finding.get("overshoot_y_nm") == 2_500_000


def test_the_reported_overshoot_rounds_up():
    """One odd nanometre over. Flooring would report nought and read as contained."""
    finding = only(run(at(ON_THE_EDGE, 0, 7_000_001, index=1)))

    assert finding.get("overshoot_x_nm") == 1


def test_the_finding_carries_the_hole_and_the_outline_it_left():
    finding = only(run(at(48 * MM, 0, 7 * MM, index=1)))

    assert finding.location_nm == (48 * MM, 0)
    assert finding.get("diameter_nm") == 7 * MM
    assert finding.get("width_nm") == 100 * MM
    assert finding.get("height_nm") == 60 * MM


def test_the_message_states_the_hole_the_breakout_and_the_outline():
    message = only(run(at(48 * MM, 0, 7 * MM, index=1))).message

    assert "7" in message and "48" in message
    assert "1.5" in message
    assert "100" in message and "60" in message


def test_a_panel_with_no_outline_is_not_checked():
    """No outline, no boundary. Page-relative coordinates have nothing to leave."""
    assert codes(run(at(10_000 * MM, 0, 7 * MM, index=1), reference=None)) == []


def test_every_hole_outside_is_reported_not_only_the_first():
    result = run(at(48 * MM, 0, 7 * MM, index=1), at(-48 * MM, 0, 7 * MM, index=2))

    assert codes(result) == ["hole-outside-outline", "hole-outside-outline"]
    assert [d.location_nm for d in result.diagnostics] == [(48 * MM, 0), (-48 * MM, 0)]


def test_it_reports_an_unrouted_hole_as_readily_as_a_routed_one():
    """No stage may require another to have run first; this one must not read an index."""
    assert codes(run(at(48 * MM, 0, 7 * MM))) == ["hole-outside-outline"]


def test_the_stage_changes_no_hole():
    given = (at(48 * MM, 0, 7 * MM, index=1), at(0, 0, 7 * MM, index=2))

    assert run(*given).holes == given
