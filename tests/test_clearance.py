"""The clearance stage, driven by a fake case model."""

from __future__ import annotations

from aidrill.model import EnclosureMatch, Severity
from aidrill.pipeline import CheckCaseClearance
from aidrill.units import Nanometre
from tests.conftest import FakeCase, at, codes, make_data

MM = 1_000_000

#: Sentinel distinguishing "use the model's own footprint" from "no enclosure".
_DEFAULT_MATCH = object()


def run(model, *holes, reference=None, enclosure=_DEFAULT_MATCH, margin_nm=1 * MM):
    data = make_data(*holes, reference=reference)
    if enclosure is _DEFAULT_MATCH:
        length_nm, width_nm = model.footprint_nm
        enclosure = EnclosureMatch(
            family="Hammond 1590",
            length_nm=length_nm,
            width_nm=width_nm,
            candidates=(model.part,),
            selected_part=model.part,
        )
    if enclosure is not None:
        data = data.with_enclosure(enclosure)
    return CheckCaseClearance(model, Nanometre(margin_nm)).apply(data)


def test_a_hole_well_inside_the_play_area_raises_nothing():
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1))

    assert codes(result) == []


def test_a_hole_overhanging_the_play_area_is_off_face():
    result = run(FakeCase(), at(48 * MM, 0, 7 * MM, index=1))

    assert codes(result) == ["hole-off-face"]


def test_a_hole_meeting_a_boss_is_reported_as_through_boss():
    model = FakeCase(bosses=((30 * MM, 30 * MM, 5 * MM),))

    result = run(model, at(30 * MM, 30 * MM, 7 * MM, index=1))

    assert codes(result) == ["hole-through-boss"]


def test_a_hole_with_structure_behind_it_is_reported_as_obstructed():
    model = FakeCase(behind=((10 * MM, 10 * MM, 5 * MM),))

    result = run(model, at(10 * MM, 10 * MM, 7 * MM, index=1))

    assert codes(result) == ["hole-obstructed"]


def test_every_clearance_rejection_is_an_error():
    result = run(FakeCase(), at(48 * MM, 0, 7 * MM, index=1))

    assert result.worst_severity is Severity.ERROR


def test_the_bit_radius_and_not_the_centre_decides_the_edge_case():
    """A centre inside the region whose rim is outside must still be rejected."""
    inside = run(FakeCase(), at(46 * MM, 0, 7 * MM, index=1))
    outside = run(FakeCase(), at(47 * MM, 0, 7 * MM, index=1))

    assert codes(inside) == []
    assert codes(outside) == ["hole-off-face"]


def test_no_hole_is_dropped_by_the_stage():
    """Clearance diagnoses; it never edits geometry, so artefacts still agree."""
    model = FakeCase(bosses=((30 * MM, 30 * MM, 5 * MM),))

    result = run(model, at(0, 0, 7 * MM, index=1), at(30 * MM, 30 * MM, 7 * MM, index=2))

    assert len(result.holes) == 2


def test_the_diagnostic_locates_the_offending_hole():
    result = run(FakeCase(), at(48 * MM, 0, 7 * MM, index=1))

    assert result.diagnostics[0].location_nm == (48 * MM, 0)


def test_each_rejected_hole_gets_its_own_diagnostic():
    result = run(
        FakeCase(),
        at(48 * MM, 0, 7 * MM, index=1),
        at(-48 * MM, 0, 7 * MM, index=2),
        at(0, 0, 7 * MM, index=3),
    )

    assert codes(result) == ["hole-off-face", "hole-off-face"]


def test_a_model_whose_footprint_contradicts_the_panel_is_an_error():
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_400_000),
        width_nm=Nanometre(60_500_000),
        candidates=("1590B",),
        selected_part="1590B",
    )

    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=match)

    assert "wrong-case-model" in codes(result)


def test_a_model_agreeing_with_the_panel_raises_nothing():
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(119_500_000),
        width_nm=Nanometre(94_000_000),
        candidates=("1590BB",),
        selected_part="1590BB",
    )

    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=match)

    assert codes(result) == []


def test_an_unidentified_panel_skips_the_cross_check_with_an_info():
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=None)

    assert codes(result) == ["case-model-unverified"]


def test_describe_records_the_model_face_margin_and_frame():
    stage = CheckCaseClearance(FakeCase(), Nanometre(1 * MM))

    run_record = stage.describe()

    assert run_record.name == "check-case-clearance"
    assert run_record.get("part") == "1590BB"
    assert run_record.get("face") == "box"
    assert run_record.get("margin_nm") == 1 * MM
    assert run_record.get("frame_w") == (0.0, 0.0, -1.0)
    assert run_record.get("play_area_nm") == (-50 * MM, -40 * MM, 50 * MM, 40 * MM)


def test_the_stage_is_independent_of_pipeline_position():
    """It reads only holes and the enclosure, so it composes anywhere."""
    from aidrill.protocols import Pipeline

    model = FakeCase()
    data = make_data(at(0, 0, 7 * MM, index=1))
    alone = Pipeline([CheckCaseClearance(model, Nanometre(1 * MM))]).run(data)

    assert alone.processing[-1].name == "check-case-clearance"
