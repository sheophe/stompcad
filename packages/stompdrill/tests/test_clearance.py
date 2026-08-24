"""The clearance stage, driven by a fake case model."""

from __future__ import annotations

import pytest

from stompdrill.enclosures import HAMMOND_1590
from stompdrill.pipeline import CheckCaseClearance
from stompdrill.pipeline.enclosure import DEFAULT_TOLERANCE_NM, IdentifyHammondFootprint
from stompmodel.diagnostics import Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, EnclosureMatch, RawOutline, ReferenceOutline
from stompmodel.units import Nanometre, mm_from_nm
from tests.conftest import FakeCase, at, codes, make_data

MM = 1_000_000


def outline(width_nm: int, height_nm: int) -> ReferenceOutline:
    """A reference outline whose nominal size is also its measurement."""
    return ReferenceOutline.from_measurement(Nanometre(width_nm), Nanometre(height_nm))

#: Sentinel distinguishing "use the model's own footprint" from "no enclosure".
_DEFAULT_MATCH = object()


def run(model, *holes, reference=None, enclosure=_DEFAULT_MATCH, margin_nm=1 * MM):
    model.margin_nm = Nanometre(margin_nm)
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
    return CheckCaseClearance(model).apply(data)


def test_apply_attaches_the_registration_stating_the_model_it_checked_against():
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1))

    assert result.case == CaseRegistration(
        part=FakeCase.part, face=FakeCase.face, model=FakeCase.model_name, frame=FakeCase.frame
    )


def test_apply_attaches_the_registration_even_when_the_check_errors():
    """A document must state what it was checked against even when the check
    against it failed -- the registration and the error are not exclusive."""
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_400_000),
        width_nm=Nanometre(60_500_000),
        candidates=("1590B",),
        selected_part="1590B",
    )

    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=match)

    assert "wrong-case-model" in codes(result)
    assert result.case is not None
    assert result.case.part == FakeCase.part


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


def test_an_odd_diameter_rounds_the_bit_up_not_down():
    """An odd nanometre diameter must round the bit radius up, never down.

    The play area's edge sits at x = 50 mm. A ⌀7,000,001 nm hole's floor
    radius (3,500,000 nm) exactly reaches it -- passing, if the check
    truncates. Its ceiling radius (3,500,001 nm) overhangs by one nanometre,
    which is the direction a safety check must round in: when in doubt
    whether a hole fits, refuse it.
    """
    model = FakeCase()
    x1 = model.play_area_nm[2]

    result = run(model, at(x1 - 3_500_000, 0, 7_000_001, index=1))

    assert codes(result) == ["hole-off-face"]


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


def test_a_1590lb_model_is_not_wrong_case_model_though_its_footprint_is_transposed():
    """The catalogue publishes 1590LB with length (50.55 mm) smaller than
    width (50.60 mm) -- the one row where "length" is not the larger figure.
    ``load_case_model`` always sorts a model's in-plane spans descending, so a
    genuine 1590LB model's ``footprint_nm`` is (larger, smaller) while the
    catalogue match's (length_nm, width_nm) is (smaller, larger). The
    cross-check must recognise these as the same pair, not two different
    footprints.
    """
    model = FakeCase()
    model.part = "1590LB"
    model.footprint_nm = (Nanometre(50_600_000), Nanometre(50_550_000))
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(50_550_000),
        width_nm=Nanometre(50_600_000),
        candidates=("1590LB",),
        selected_part="1590LB",
    )

    result = run(model, at(0, 0, 7 * MM, index=1), enclosure=match)

    assert "wrong-case-model" not in codes(result)


def test_a_1590lb_model_against_a_genuinely_different_footprint_still_fails():
    """Order independence must not blur a footprint that is actually
    different -- only a transposed-but-equal pair passes. Same fixture model
    as the transposed case above; only the identified match differs, so the
    distinction is the test's, not the fixture's.
    """
    model = FakeCase()
    model.part = "1590LB"
    model.footprint_nm = (Nanometre(50_600_000), Nanometre(50_550_000))
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(50_500_000),
        width_nm=Nanometre(50_500_000),
        candidates=("1590LLB",),
        selected_part="1590LLB",
    )

    result = run(model, at(0, 0, 7 * MM, index=1), enclosure=match)

    assert "wrong-case-model" in codes(result)


def test_an_unidentified_panel_skips_the_cross_check_with_an_info():
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=None)

    assert codes(result) == ["case-model-unverified", "case-orientation-unverifiable"]


def test_describe_records_the_margin_the_plate_and_the_play_area():
    stage = CheckCaseClearance(FakeCase())

    run_record = stage.describe()

    assert run_record.name == "check-case-clearance"
    assert run_record.get("margin_nm") == 1 * MM
    assert run_record.get("plate_nm") == FakeCase.plate_nm
    assert run_record.get("play_area_nm") == (-50 * MM, -40 * MM, 50 * MM, 40 * MM)


def test_describe_no_longer_carries_the_part_the_face_or_the_frame():
    """Those facts moved to ``DrillData.case``; they must not exist in both
    places, because two shapes for one fact is how the two come to disagree.
    """
    run_record = CheckCaseClearance(FakeCase()).describe()

    assert run_record.get("part") is None
    assert run_record.get("face") is None
    assert run_record.get("frame_origin_nm") is None
    assert run_record.get("frame_u") is None
    assert run_record.get("frame_v") is None
    assert run_record.get("frame_w") is None
    assert [key for key, _ in run_record.parameters] == ["margin_nm", "plate_nm", "play_area_nm"]


def test_the_recorded_margin_is_the_model_s_own():
    """The stage has no margin of its own; it only reports the model's."""
    stage = CheckCaseClearance(FakeCase(margin_nm=3 * MM))

    assert stage.describe().get("margin_nm") == 3 * MM


def test_the_stage_is_independent_of_pipeline_position():
    """It reads only holes and the enclosure, so it composes anywhere."""
    from stompmodel.protocols import Pipeline

    model = FakeCase()
    data = make_data(at(0, 0, 7 * MM, index=1))
    alone = Pipeline([CheckCaseClearance(model)]).run(data)

    assert alone.processing[-1].name == "check-case-clearance"


# ---------------------------------------------------------------------------
# The panel-to-model axis reconciliation (F3-03 / T08)
# ---------------------------------------------------------------------------

#: A 1590B drawn portrait, matching the falsifier: the catalogue footprint
#: (112.40 x 60.50 mm) turned a quarter turn from the drawing convention.
_ROTATED_1590B = EnclosureMatch(
    family="Hammond 1590",
    length_nm=Nanometre(112_400_000),
    width_nm=Nanometre(60_500_000),
    candidates=("1590B",),
    selected_part="1590B",
    rotated=True,
)


def _1590b_model() -> FakeCase:
    """A play area sized to the real 1590B footprint, margin removed so a
    hole 6 mm inside the drawn (portrait) edge is unambiguously inside it.
    """
    model = FakeCase(half_x=int(56.2 * MM), half_y=int(30.25 * MM), margin_nm=0)
    model.part = "1590B"
    model.footprint_nm = (Nanometre(112_400_000), Nanometre(60_500_000))
    return model


def test_a_rotated_panel_hole_near_the_long_edge_is_not_wrongly_rejected():
    """The falsifier's own scenario: undoing the defect must not merely stop
    the rejection -- it must land the hole at the physical point the artwork
    actually puts it, asserted below as a named model point so the untested
    180-degree alternative convention could not pass the same assertion.
    """
    result = run(
        _1590b_model(),
        at(0, 50 * MM, 7 * MM, index=1),
        at(25 * MM, 0, 7 * MM, index=2),
        reference=outline(60_500_000, 112_400_000),
        enclosure=_ROTATED_1590B,
    )

    assert codes(result) == []


def test_the_rotated_hole_is_cut_at_the_named_model_point():
    """Criterion 1: not merely "no longer refused" -- the published frame
    must place the hole at a specific, named point in model space. Both
    candidate quarter turns satisfy "not refused" against this play area
    (E1's own risk note); only one satisfies this coordinate.
    """
    result = run(
        _1590b_model(),
        at(0, 50 * MM, 7 * MM, index=1),
        reference=outline(60_500_000, 112_400_000),
        enclosure=_ROTATED_1590B,
    )

    assert result.case is not None
    point = result.case.frame.basis.to_model(Nanometre(0), Nanometre(50 * MM))
    assert point == (-50.0, 0.0, -30.0)


def test_the_quarter_turn_direction_is_a_pinned_convention():
    """E1: the direction is stated, not derived -- ``u`` takes the model's
    own ``v``, ``v`` takes its negated ``u``, ``w`` and the origin untouched.
    Named directly against ``FakeCase``'s own basis, independent of
    ``classify()``, so this pins the convention rather than an effect of it.
    """
    stage = CheckCaseClearance(FakeCase())
    data = make_data(reference=outline(60_500_000, 112_400_000)).with_enclosure(_ROTATED_1590B)

    frame = stage._reconciled_frame(data)

    assert frame.basis.u == FakeCase.frame.basis.v
    assert frame.basis.v == tuple(-component for component in FakeCase.frame.basis.u)
    assert frame.basis.w == FakeCase.frame.basis.w
    assert frame.basis.origin_nm == FakeCase.frame.basis.origin_nm


def test_an_unidentified_enclosure_reconciles_to_the_models_own_frame():
    """No enclosure short-circuits to identity before the measurement is even
    consulted -- a portrait reference is supplied here deliberately, so a
    trigger that forgot to check ``data.enclosure`` first could not pass.
    """
    stage = CheckCaseClearance(FakeCase())
    data = make_data(reference=outline(60_500_000, 112_400_000))

    assert stage._reconciled_frame(data) is FakeCase.frame


def test_an_unrotated_match_reconciles_to_the_models_own_frame():
    """AC2: a panel drawn landscape (drawn width >= drawn height) reconciles
    to the model's own frame -- the very same object, so ``apply()`` never
    detours through the reframe arithmetic for it.
    """
    stage = CheckCaseClearance(FakeCase())
    unrotated = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(119_500_000),
        width_nm=Nanometre(94_000_000),
        candidates=("1590BB",),
        selected_part="1590BB",
    )
    data = make_data(reference=outline(119_500_000, 94_000_000)).with_enclosure(unrotated)

    assert stage._reconciled_frame(data) is FakeCase.frame


def test_the_unrotated_control_publishes_the_models_own_frame_unchanged():
    """AC2: identity reconciliation, the same registration as before this
    ticket -- the existing default-enclosure tests already cover the
    verdicts and cut geometry; this pins the frame identity specifically.
    Drawn landscape (matching FakeCase's own 119.5 x 94 mm footprint), so
    this exercises the measurement-based identity branch, not the
    missing-outline fallback.
    """
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), reference=outline(119_500_000, 94_000_000))

    assert result.case is not None
    assert result.case.frame is FakeCase.frame


def test_no_identified_enclosure_warns_orientation_unverifiable():
    """AC4, clause 1."""
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=None)

    assert "case-orientation-unverifiable" in codes(result)


def test_a_square_identified_footprint_warns_orientation_unverifiable():
    """AC4, clause 2: a square footprint's own tie-break has no signal to
    confirm or contradict, so the correspondence cannot be established even
    though ``EnclosureMatch.rotated`` is ``False`` for it.
    """
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(92_000_000),
        width_nm=Nanometre(92_000_000),
        candidates=("1590Y",),
        selected_part="1590Y",
    )
    model = FakeCase()
    model.part = "1590Y"
    model.footprint_nm = (Nanometre(92_000_000), Nanometre(92_000_000))

    result = run(model, at(0, 0, 7 * MM, index=1), enclosure=match)

    assert "case-orientation-unverifiable" in codes(result)


def test_a_rotated_non_square_footprint_does_not_warn_orientation_unverifiable():
    """AC4: the third clause, tested independently -- a rotated but
    non-square footprint IS reconciled, so it must not also warn.
    """
    result = run(_1590b_model(), at(0, 50 * MM, 7 * MM, index=1), enclosure=_ROTATED_1590B)

    assert "case-orientation-unverifiable" not in codes(result)


def test_orientation_unverifiable_is_a_warning_not_an_error():
    """The check could not run, which is not the same claim as a wrong
    answer -- an error would refuse every square-enclosure user the tool
    serves today.
    """
    result = run(FakeCase(), at(0, 0, 7 * MM, index=1), enclosure=None)

    notice = next(d for d in result.diagnostics if d.code == "case-orientation-unverifiable")
    assert notice.severity is Severity.WARNING


def test_the_play_area_describe_reports_is_restated_in_the_checked_frame():
    """Class criterion (E2): a rotated panel's document must not carry the
    registration in one frame and the play area in another -- the fix would
    otherwise manufacture a fresh instance of the theme it exists to close.
    """
    stage = CheckCaseClearance(FakeCase())
    data = make_data(
        at(0, 0, 7 * MM, index=1), reference=outline(60_500_000, 112_400_000)
    ).with_enclosure(_ROTATED_1590B)

    stage.apply(data)
    run_record = stage.describe()

    # FakeCase's own play area is (-50, -40, 50, 40) mm; restated through the
    # same quarter turn ``apply()`` used, ``(x, y) -> (y, -x)`` per corner.
    assert run_record.get("play_area_nm") == (-40 * MM, -50 * MM, 40 * MM, 50 * MM)


def test_describe_before_any_apply_still_reports_the_models_own_play_area():
    """A ``describe()`` with no preceding ``apply()`` -- as every pre-existing
    test in this file does -- must report exactly what it always has."""
    stage = CheckCaseClearance(FakeCase())

    assert stage.describe().get("play_area_nm") == (-50 * MM, -40 * MM, 50 * MM, 40 * MM)


@pytest.mark.hammond
def test_a_real_rotated_1590b_is_reconciled_to_the_named_model_point(hammond_b):
    """AC3: verified once against a real supplied model, not reasoned from
    the algebra alone. ``FakeCase``'s frame is deliberately axis-aligned and
    idealised; the real 1590B's own frame is measured by ``build_frame`` from
    the kernel's own face normals (see ``stompmodel.frames._BASIS_TOLERANCE``)
    and its play area from real B-rep topology -- including the box's own
    cast lettering, which the loose falsifier fixture has no equivalent of.
    """
    from stompdrill.cad import load_case_model

    model = load_case_model(hammond_b, face=CaseFace.BOX, margin_nm=Nanometre(0))
    data = make_data(
        at(0, 40 * MM, 7 * MM, index=1), reference=outline(60_500_000, 112_400_000)
    ).with_enclosure(_ROTATED_1590B)

    result = CheckCaseClearance(model).apply(data)

    assert codes(result) == []
    point = result.case.frame.basis.to_model(Nanometre(0), Nanometre(40 * MM))
    assert point == pytest.approx((-40.0, -25.0, 0.0))


# ---------------------------------------------------------------------------
# The registration is read from the measurement, not from ``rotated`` (T15)
# ---------------------------------------------------------------------------


class FakeCase1590LB(FakeCase):
    """Shaped like ``cad.loader``/``cad.case.build_frame`` would build for a
    real 1590LB model: footprint descending, ``u`` on the larger span."""

    part = "1590LB"
    model_name = "1590LB.stp"
    footprint_nm = (Nanometre(50_600_000), Nanometre(50_550_000))
    frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-15 * MM)),
            u=(1.0, 0.0, 0.0), v=(0.0, -1.0, 0.0), w=(0.0, 0.0, -1.0),
        )
    )

    def __init__(self):
        super().__init__(half_x=25_300_000, half_y=25_275_000, margin_nm=0)


def _1590lb_match(*, rotated: bool) -> EnclosureMatch:
    return EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(50_550_000),
        width_nm=Nanometre(50_600_000),
        candidates=("1590LB",),
        selected_part="1590LB",
        rotated=rotated,
    )


def test_1590lb_drawn_as_printed_is_reconciled_to_the_named_model_point():
    """Criterion 3, first orientation, migrated from the falsifier's red
    test: drawn 50.55 mm wide x 50.60 mm tall matches the catalogue's own
    printed row exactly, so ``EnclosureMatch.rotated`` is ``False`` -- and
    identity is the wrong answer, because canonical x is the *smaller*
    drawn extent here. Named against a real model point so the untested
    identity alternative could not pass the same assertion.
    """
    model = FakeCase1590LB()
    data = make_data(
        at(0, 10 * MM, 7 * MM, index=1),
        reference=outline(50_550_000, 50_600_000),
    ).with_enclosure(_1590lb_match(rotated=False))

    result = CheckCaseClearance(model).apply(data)

    assert codes(result) == []
    assert result.case is not None
    assert result.case.frame is not model.frame
    point = result.case.frame.basis.to_model(Nanometre(0), Nanometre(10 * MM))
    assert point == (-10.0, 0.0, -15.0)


def test_1590lb_drawn_landscape_stays_identity_and_names_the_model_point():
    """Criterion 3, second orientation: drawn 50.60 mm wide x 50.55 mm tall
    is turned from the catalogue's own printed row (``rotated=True``), and
    here identity is *already* correct -- canonical x already runs along
    the model's larger 50.60 mm ``u`` axis, so no reframing is needed.
    Named against a real model point so the untested swap could not pass
    the same assertion.
    """
    model = FakeCase1590LB()
    data = make_data(
        at(25 * MM, 0, 10_000, index=1),
        reference=outline(50_600_000, 50_550_000),
    ).with_enclosure(_1590lb_match(rotated=True))

    result = CheckCaseClearance(model).apply(data)

    assert codes(result) == []
    assert result.case is not None
    assert result.case.frame is model.frame
    point = result.case.frame.basis.to_model(Nanometre(25 * MM), Nanometre(0))
    assert point == (25.0, 0.0, -15.0)


def test_the_frame_follows_the_measurement_when_rotated_says_no_turn():
    """Criterion 2, clause-level mutant killer, direction one: ``rotated``
    says no turn is needed but the measurement says the panel was drawn
    portrait. The frame must follow the measurement -- a trigger that
    reads ``rotated`` at all, alongside or instead of the measurement,
    cannot pass this the way one reading only the measurement can.
    """
    stage = CheckCaseClearance(FakeCase())
    contradicting = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_400_000),
        width_nm=Nanometre(60_500_000),
        candidates=("1590B",),
        selected_part="1590B",
        rotated=False,
    )
    data = make_data(reference=outline(60_500_000, 112_400_000)).with_enclosure(contradicting)

    frame = stage._reconciled_frame(data)

    assert frame is not FakeCase.frame
    assert frame.basis.u == FakeCase.frame.basis.v


def test_the_frame_follows_the_measurement_when_rotated_says_turn():
    """Criterion 2, clause-level mutant killer, direction two: ``rotated``
    says a turn is needed but the measurement says the panel was drawn
    landscape. The frame must stay identity.
    """
    stage = CheckCaseClearance(FakeCase())
    contradicting = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_400_000),
        width_nm=Nanometre(60_500_000),
        candidates=("1590B",),
        selected_part="1590B",
        rotated=True,
    )
    data = make_data(reference=outline(112_400_000, 60_500_000)).with_enclosure(contradicting)

    frame = stage._reconciled_frame(data)

    assert frame is FakeCase.frame


@pytest.mark.parametrize("swap", [False, True], ids=["as-printed", "turned"])
@pytest.mark.parametrize("enclosure", HAMMOND_1590, ids=lambda e: e.part)
def test_the_trigger_matches_the_drawn_width_across_the_whole_catalogue(enclosure, swap):
    """Criterion 1: a computed sweep, not a hard-coded list. For every
    catalogued row and both drawn orientations, the reconciled frame is
    the model's own exactly when the drawn width is the larger drawn
    extent. Fails today on exactly the two ``1590LB`` rows -- the one part
    whose catalogue dimensions differ by less than the matcher's own
    per-axis slack -- and fails again on any revert to ``rotated`` or to
    the snapped nominal extents, which are a *constant* for that one part.
    """
    length_mm = mm_from_nm(enclosure.length_nm)
    width_mm = mm_from_nm(enclosure.width_nm)
    drawn_width, drawn_height = (width_mm, length_mm) if swap else (length_mm, width_mm)
    identify = IdentifyHammondFootprint(enclosure.part)

    snapped, match, diagnostics = identify.quantise(RawOutline(drawn_width, drawn_height), (0.0, 0.0))

    assert match is not None, f"{enclosure.part} did not match its own catalogue footprint"
    assert snapped is not None
    data = make_data(reference=snapped).with_enclosure(match)
    stage = CheckCaseClearance(FakeCase())

    frame = stage._reconciled_frame(data)

    expect_identity = drawn_width >= drawn_height
    assert (frame is FakeCase.frame) == expect_identity, (
        f"{enclosure.part} drawn {drawn_width} x {drawn_height} mm: "
        f"expected identity={expect_identity}"
    )


def test_the_near_square_band_is_computed_and_is_exactly_1590lb():
    """Criterion 4: computed from the catalogue, not asserted. If a future
    catalogue row's two dimensions differ by less than the matcher's own
    per-axis slack, this fails and the ADR sentence naming ``1590LB`` alone
    is revisited rather than quietly falsified.
    """
    near_square = [
        enclosure.part
        for enclosure in HAMMOND_1590
        if enclosure.length_nm != enclosure.width_nm
        and abs(enclosure.length_nm - enclosure.width_nm) < DEFAULT_TOLERANCE_NM
    ]

    assert near_square == ["1590LB"]
