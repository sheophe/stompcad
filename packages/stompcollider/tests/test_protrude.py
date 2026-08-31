"""A component's protrusion: which cylinders count, and the profile they make.

Every synthetic solid is built so the three rules disagree with the easy
answers: admitted cylinders of unequal extent with the furthest not first in
the walk, a non-parallel cylinder reaching further than any admitted one, a
stepped stack rather than one diameter, and geometry not symmetric about its
own axis midpoint. The solids use OCP directly because that is what a
fixture is; the source reaches the kernel only through ``stompgeom``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stompcollider.canonicalise import _canonicalise_component
from stompcollider.model import Profile
from stompcollider.protrude import admissible, protrusion_of
from stompcollider.raw import RawComponent
from stompgeom.cylinders import Cylinder, cylindrical_faces
from stompgeom.step import StepDocument, StepSolid, read_step
from stompmodel.units import Nanometre

_FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"

#: Which way "outward" points on the fixture. Its two substrates occupy
#: z 0.00 to 1.51 and every component's body reaches towards negative z --
#: SW1 as far as -38.4 -- so the direction pointing away from the board, at
#: the panel, is -z. Measured from the fixture, not assumed: with +z the
#: tipmost admitted cylinder on a footswitch is a solder pin, and
#: ``test_the_outward_directions_negation_reads_the_wrong_end`` is what shows
#: that the sign is doing work here.
_OUTWARD = (0.0, 0.0, -1.0)

#: A carrier normal for the synthetic solids, which are built the other way
#: up so that a copied constant cannot make either set pass by accident.
_UP = (0.0, 0.0, 1.0)


# --------------------------------------------------------------------------
# Synthetic solids
# --------------------------------------------------------------------------


def _pin(
    radius: float,
    height: float,
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    along: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*at), gp_Dir(*along)), radius, height
    ).Shape()


def _cuboid() -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 4.0, 5.0, 6.0).Shape()


def _solid(name: str, *shapes: Any) -> StepSolid:
    from stompgeom.shapes import compound

    return StepSolid(name=name, shape=compound(shapes))


#: A short pin at the origin and a taller, wider one offset from it. The
#: short one is built first, so "the furthest" and "the first walked" are
#: different cylinders, and neither axis sits at (0, 0) in the carrier
#: plane, so a dropped projection cannot read as a correct answer.
def _two_pins_of_unequal_reach() -> StepSolid:
    return _solid(
        "U1",
        _pin(1.0, 5.0, at=(0.0, 0.0, 0.0)),
        _pin(2.0, 9.0, at=(3.0, 7.0, 0.0)),
    )


def _the_same_two_pins_walked_the_other_way() -> StepSolid:
    return _solid(
        "U1",
        _pin(2.0, 9.0, at=(3.0, 7.0, 0.0)),
        _pin(1.0, 5.0, at=(0.0, 0.0, 0.0)),
    )


#: The two pins again, plus a cylinder leaning 45 degrees that reaches
#: further along +z than either of them.
def _the_two_pins_and_a_leaning_cylinder() -> StepSolid:
    return _solid(
        "U1",
        _pin(1.0, 5.0, at=(0.0, 0.0, 0.0)),
        _pin(2.0, 9.0, at=(3.0, 7.0, 0.0)),
        _pin(1.5, 30.0, at=(30.0, 0.0, 0.0), along=(1.0, 0.0, 1.0)),
    )


#: A narrow pin and a short wide collar sharing one axis. Stepped, so a
#: profile of one radius cannot pass; and not symmetric about the axis
#: midpoint, so reading the axis the other way round gives a different
#: answer rather than the same one.
def _a_stepped_stack() -> StepSolid:
    return _solid(
        "U2",
        _pin(1.0, 10.0, at=(0.0, 0.0, 0.0)),
        _pin(3.0, 4.0, at=(0.0, 0.0, 0.0)),
    )


#: The tall pin, and a much wider parallel pin beside it that reaches less
#: far. Only coaxiality keeps the wide one out of the stack.
def _a_tall_pin_beside_a_wider_one() -> StepSolid:
    return _solid(
        "U3",
        _pin(2.0, 9.0, at=(0.0, 0.0, 0.0)),
        _pin(5.0, 8.0, at=(30.0, 0.0, 0.0)),
    )


def _profile(
    solid: StepSolid,
    normal: tuple[float, float, float],
    probes_nm: tuple[Nanometre, ...] = (),
) -> Profile:
    """The profile the two stages make together.

    ``protrusion_of`` measures and ``canonicalise`` scales, dedupes and
    orders; a profile is what they produce jointly, so the assertions below
    are stated in whole nanometres at the seam rather than on either half.
    """
    protrusion = _canonicalise_component(
        _measured_component(solid, normal, probes_nm)
    ).protrusion
    assert protrusion is not None
    return protrusion.profile


def _axis_nm(
    solid: StepSolid, normal: tuple[float, float, float]
) -> tuple[Nanometre, Nanometre]:
    protrusion = _canonicalise_component(_measured_component(solid, normal)).protrusion
    assert protrusion is not None
    return protrusion.axis_xy_nm


def _measured_component(
    solid: StepSolid,
    normal: tuple[float, float, float],
    probes_nm: tuple[Nanometre, ...] = (),
) -> RawComponent:
    found = protrusion_of(solid, normal, probes_nm)
    assert found is not None
    return found


def _radii(solid: StepSolid, normal: tuple[float, float, float]) -> set[Nanometre]:
    return {step[0] for step in _profile(solid, normal).steps}


def _reach_along(cylinder: Cylinder, axis: tuple[float, float, float]) -> float:
    """How far along ``axis`` the cylinder's furthest end circle sits."""
    base = sum(a * b for a, b in zip(cylinder.axis_location_mm, axis))
    step = sum(a * b for a, b in zip(cylinder.axis_direction, axis))
    return max(base + cylinder.extent_mm[0] * step, base + cylinder.extent_mm[1] * step)


# --------------------------------------------------------------------------
# Rule 1: only cylinders parallel to the carrier normal are admitted
# --------------------------------------------------------------------------


def test_a_cylinder_at_an_angle_is_not_admitted() -> None:
    """Rule 1's guilty probe on synthetic geometry, so it runs without --boards."""
    leaning = _solid("U1", _pin(1.5, 30.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 1.0)))

    assert admissible(leaning, _UP) == ()


def test_an_axial_cylinder_is_admitted() -> None:
    """The innocent probe beside it."""
    upright = _solid("U1", _pin(1.5, 30.0, at=(0.0, 0.0, 0.0)))

    assert len(admissible(upright, _UP)) == 1


def test_a_cylinder_facing_the_other_way_along_the_normal_is_still_admitted() -> None:
    """Admission is parallelism, which is sign-agnostic: which way a
    cylindrical surface's axis points is the exporter's convention."""
    upright = _solid("U1", _pin(1.5, 30.0, at=(0.0, 0.0, 0.0)))

    assert len(admissible(upright, (0.0, 0.0, -1.0))) == 1


def test_rejecting_a_leaning_cylinder_changes_the_answer_not_only_the_count() -> None:
    """The leaning cylinder reaches further along the normal than either pin,
    so a rule that admitted it would take its axis and its radius. The
    control is the first assertion: without rule 1 it *would* be tipmost."""
    with_lean = _the_two_pins_and_a_leaning_cylinder()
    without = _two_pins_of_unequal_reach()
    leaning = max(cylindrical_faces(with_lean.shape), key=lambda c: _reach_along(c, _UP))

    assert leaning.radius_mm == 1.5
    assert _reach_along(leaning, _UP) > max(
        _reach_along(c, _UP) for c in admissible(with_lean, _UP)
    )
    assert len(admissible(with_lean, _UP)) == len(admissible(without, _UP)) == 2
    assert protrusion_of(with_lean, _UP) == protrusion_of(without, _UP)


def test_a_component_with_no_admissible_cylinder_has_no_axis() -> None:
    """Reported as unmatched-part, the same finding as an axis that pairs with
    no hole -- not as a crash and not as a zero-radius profile."""
    assert protrusion_of(_solid("U1", _cuboid()), _UP) is None


def test_a_component_whose_every_cylinder_leans_has_no_axis_either() -> None:
    """Not the same case as the cuboid: here there is cylindrical geometry and
    rule 1 refuses all of it."""
    leaning = _solid("U1", _pin(1.5, 30.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 1.0)))

    assert cylindrical_faces(leaning.shape) != ()
    assert protrusion_of(leaning, _UP) is None


# --------------------------------------------------------------------------
# Rule 3: the furthest admitted cylinder fixes the axis
# --------------------------------------------------------------------------


def test_the_furthest_admitted_cylinder_fixes_the_axis_not_the_first_walked() -> None:
    """The short pin is built first and sits at the origin; the answer must be
    the taller one, whose axis is at (3, 7) and whose radius is 2."""
    solid = _two_pins_of_unequal_reach()

    # basis_about((0, 0, 1)) gives u = (0, -1, 0) and v = (1, 0, 0).
    assert _axis_nm(solid, _UP) == (Nanometre(-7_000_000), Nanometre(3_000_000))
    assert _profile(solid, _UP).steps == (
        (Nanometre(2_000_000), Nanometre(0), Nanometre(9_000_000)),
    )


def test_the_walk_order_does_not_choose_the_axis() -> None:
    """Two spellings of one geometry, differing only in the order the faces
    are walked, must give one answer (ADR-0006)."""
    assert protrusion_of(_two_pins_of_unequal_reach(), _UP) == protrusion_of(
        _the_same_two_pins_walked_the_other_way(), _UP
    )


def test_two_cylinders_reaching_exactly_as_far_are_separated_on_geometry() -> None:
    """The tie-break's own control. Reach alone leaves these two undecided, so
    without a geometric second key the answer would be whichever the walk met
    first -- which the two spellings below would then disagree about."""
    wider_first = _solid("U1", _pin(2.0, 9.0, at=(3.0, 7.0, 0.0)), _pin(1.0, 9.0))
    narrower_first = _solid("U1", _pin(1.0, 9.0), _pin(2.0, 9.0, at=(3.0, 7.0, 0.0)))
    reaches = {_reach_along(c, _UP) for c in admissible(wider_first, _UP)}

    assert reaches == {9.0}
    assert protrusion_of(wider_first, _UP) == protrusion_of(narrower_first, _UP)
    assert _axis_nm(narrower_first, _UP) == (Nanometre(-7_000_000), Nanometre(3_000_000))


def test_only_a_coaxial_cylinder_joins_the_stack() -> None:
    """A wider parallel pin beside the axis must contribute no step, or a
    profile would report a radius nothing on the axis has."""
    assert _radii(_a_tall_pin_beside_a_wider_one(), _UP) == {Nanometre(2_000_000)}


def test_two_coincident_faces_contribute_one_step() -> None:
    """A cylinder split at its seam gives two faces of one axis, one radius
    and one extent. The feature is stated once: leaving both in changes the
    value's equality and its serialised form, and on the fixture's footswitch
    it is the difference between forty-five steps and fifty-four."""
    twinned = _solid("U4", _pin(1.0, 10.0), _pin(1.0, 10.0))

    assert len(cylindrical_faces(twinned.shape)) == 2
    assert len(_measured_component(twinned, _UP).stack) == 2
    assert _profile(twinned, _UP).steps == (
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
    )


def test_the_designator_is_the_solids_own_name() -> None:
    assert _measured_component(_two_pins_of_unequal_reach(), _UP).designator == "U1"


# --------------------------------------------------------------------------
# Rule 3: the profile is radius versus depth
# --------------------------------------------------------------------------


def test_a_stepped_stack_reports_a_radius_that_changes_with_depth() -> None:
    """A narrow pin 10 long with a 4-long collar of radius 3 at its far end:
    the tip is the pin's free end, so the collar covers depth 6 to 10."""
    profile = _profile(_a_stepped_stack(), _UP)

    assert profile.steps == (
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
        (Nanometre(3_000_000), Nanometre(6_000_000), Nanometre(10_000_000)),
    )
    assert profile.radius_at(Nanometre(1_000_000)) == Nanometre(1_000_000)
    assert profile.radius_at(Nanometre(8_000_000)) == Nanometre(3_000_000)


def test_a_stepped_stack_admits_a_hole_to_the_collar_and_no_further() -> None:
    profile = _profile(_a_stepped_stack(), _UP)

    assert profile.insertion_through(Nanometre(2_000_000)) == Nanometre(6_000_000)
    assert profile.insertion_through(Nanometre(3_000_000)) is None


def test_the_outward_direction_is_not_its_own_negation() -> None:
    """The same solid read the other way up: the collar is now at the tip, so
    a 2 mm hole is stopped at once instead of six millimetres in. A rule
    ignoring the normal's sign would report one answer for both."""
    up = _profile(_a_stepped_stack(), _UP)
    down = _profile(_a_stepped_stack(), (0.0, 0.0, -1.0))

    assert down.steps == (
        (Nanometre(3_000_000), Nanometre(0), Nanometre(4_000_000)),
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
    )
    assert down.radius_at(Nanometre(1_000_000)) == Nanometre(3_000_000)
    assert down.insertion_through(Nanometre(2_000_000)) == Nanometre(0)
    assert up.steps != down.steps


# --------------------------------------------------------------------------
# The fixture. Rule 1's measured consequence and the spec's own table.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def document() -> StepDocument:
    return read_step(_FIXTURE)


def _part(document: StepDocument, name: str) -> StepSolid:
    return next(solid for solid in document.solids if solid.name == name)


@pytest.mark.boards
def test_an_ordinary_diode_reduces_to_two_admitted_faces(document: StepDocument) -> None:
    """Rule 1's measured consequence; the numbers are the spec's own."""
    diode = _part(document, "D2")

    assert len(cylindrical_faces(diode.shape)) == 7
    assert len(admissible(diode, _OUTWARD)) == 2


@pytest.mark.boards
def test_a_footswitch_reduces_from_534_faces_to_124(document: StepDocument) -> None:
    switch = _part(document, "SW1")

    assert len(cylindrical_faces(switch.shape)) == 534
    assert len(admissible(switch, _OUTWARD)) == 124


@pytest.mark.boards
def test_a_potentiometer_reduces_from_72_faces_to_43(document: StepDocument) -> None:
    pot = _part(document, "RV1")

    assert len(cylindrical_faces(pot.shape)) == 72
    assert len(admissible(pot, _OUTWARD)) == 43


@pytest.mark.boards
def test_the_admitted_set_does_not_depend_on_the_normals_sign(
    document: StepDocument,
) -> None:
    """Rule 1 is parallelism, and the fixture carries admitted faces pointing
    both ways along z, so this would fail for an equality test."""
    switch = _part(document, "SW1")

    assert admissible(switch, _OUTWARD) == admissible(switch, (0.0, 0.0, 1.0))
    assert {
        round(c.axis_direction[2]) for c in admissible(switch, _OUTWARD)
    } == {1, -1}


@pytest.mark.boards
def test_the_footswitch_profile_admits_a_twelve_millimetre_hole_fully(
    document: StepDocument,
) -> None:
    """The spec's validation table, as a test: 10 tip, 8 shaft, 12 bush;
    a 12 mm hole passes it to full depth and an 11.9 mm one does not."""
    profile = _profile(_part(document, "SW1"), _OUTWARD)

    assert profile.steps[0] == (Nanometre(5_000_000), Nanometre(0), Nanometre(4_300_000))
    assert {step[0] for step in profile.steps} == {
        Nanometre(4_000_000), Nanometre(4_050_000), Nanometre(4_900_000),
        Nanometre(5_000_000), Nanometre(5_250_000), Nanometre(6_000_000),
    }
    assert profile.insertion_through(Nanometre(6_000_000)) is None
    assert profile.insertion_through(Nanometre(5_950_000)) == Nanometre(10_250_000)


@pytest.mark.boards
def test_the_footswitch_states_each_of_its_features_once(
    document: StepDocument,
) -> None:
    """Its stack is fifty-four coaxial faces and its profile forty-five
    steps: nine of those faces are a seam-split cylinder's other half,
    stating a feature the profile already carries."""
    switch = _part(document, "SW1")

    assert len(_measured_component(switch, _OUTWARD).stack) == 54
    assert len(_profile(switch, _OUTWARD).steps) == 45


@pytest.mark.boards
def test_a_potentiometer_profile_is_a_shaft_then_a_narrower_bushing(
    document: StepDocument,
) -> None:
    """The spec's table again: 6.35 shaft, then a 6.188 bushing. A stack whose
    second step is *narrower* than its first, which no monotonic rule gives."""
    profile = _profile(_part(document, "RV1"), _OUTWARD)

    assert profile.steps[0] == (Nanometre(3_175_000), Nanometre(0), Nanometre(13_700_000))
    assert {step[0] for step in profile.steps} == {
        Nanometre(3_175_000), Nanometre(3_094_051)
    }


@pytest.mark.boards
def test_a_five_millimetre_led_seats_on_its_flange(document: StepDocument) -> None:
    """The case a largest-radius rule gets wrong: the flange is precisely the
    feature that must not pass through, and it is 5.15 mm down the shaft."""
    profile = _profile(_part(document, "D3"), _OUTWARD)

    assert profile.steps == (
        (Nanometre(2_450_000), Nanometre(0), Nanometre(5_150_000)),
        (Nanometre(2_900_000), Nanometre(5_150_000), Nanometre(6_150_000)),
    )
    assert profile.insertion_through(Nanometre(2_500_000)) == Nanometre(5_150_000)
    assert profile.insertion_through(Nanometre(3_000_000)) is None


@pytest.mark.boards
def test_the_outward_directions_negation_reads_the_wrong_end(
    document: StepDocument,
) -> None:
    """The control for ``_OUTWARD``. Read along +z the LED's flange lands at
    the tip and a 5 mm hole is stopped at depth zero rather than 5.15 mm in,
    and the footswitch's tipmost cylinder is a 2 mm solder pin instead of its
    10 mm tip. Both directions satisfy "not None", which is why the tests
    above assert the depths and not merely that there is one."""
    inverted = _profile(_part(document, "D3"), (0.0, 0.0, 1.0))

    assert inverted.insertion_through(Nanometre(2_500_000)) == Nanometre(0)
    assert _radii(_part(document, "SW1"), (0.0, 0.0, 1.0)) == {Nanometre(1_000_000)}


@pytest.mark.boards
def test_every_admitted_cylinder_is_within_a_thousandth_of_the_normal(
    document: StepDocument,
) -> None:
    """Rule 1 is correctness: an axis at some other angle means nothing, so
    no admitted face may lean at all."""
    for name in ("SW1", "RV1", "D2", "D3"):
        for cylinder in admissible(_part(document, name), _OUTWARD):
            assert math.isclose(abs(cylinder.axis_direction[2]), 1.0, abs_tol=1e-9)


# --------------------------------------------------------------------------
# The profile is the whole solid's radial extent, not its cylinders'
# --------------------------------------------------------------------------


def _a_pin_on_a_can() -> StepSolid:
    """A 10 mm pin of radius 1 standing on a 6 mm cube, the pin at its centre.

    The cube is what a real potentiometer's can, a footswitch's body or a
    jack's shell is: the feature that arrests the part, with no cylindrical
    face anywhere on it. Measured from the pin's tip the cube's top face is
    10 mm down, and its half-width of 3 mm is the radius that stops there.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return _solid(
        "U9",
        BRepPrimAPI_MakeBox(gp_Pnt(-3.0, -3.0, -6.0), 6.0, 6.0, 6.0).Shape(),
        _pin(1.0, 10.0, at=(0.0, 0.0, 0.0)),
    )


def test_a_can_no_cylinder_describes_still_arrests_the_part() -> None:
    """The defect this module was rewritten for, in one solid.

    Every cylindrical face of this part measures radius 1, so a profile
    built from the cylinders alone says a 4 mm hole admits the whole thing.
    Probed at that hole's radius, the cube states itself: material wider
    than 2 mm begins exactly where the pin meets it.
    """
    probes = (Nanometre(2_000_000),)

    assert _profile(_a_pin_on_a_can(), _UP).insertion_through(Nanometre(2_000_000)) is None
    assert _profile(_a_pin_on_a_can(), _UP, probes).insertion_through(
        Nanometre(2_000_000)
    ) == Nanometre(10_000_000)


def test_a_probe_the_whole_part_passes_states_no_band_at_all() -> None:
    """The control beside it: a hole wide enough for the cube reports nothing
    to stop the part, so the band above is evidence about the cube rather
    than about being probed at all."""
    probes = (Nanometre(5_000_000),)

    assert _profile(_a_pin_on_a_can(), _UP, probes).insertion_through(
        Nanometre(5_000_000)
    ) is None


def test_a_band_states_only_that_the_material_is_wider_than_the_probe() -> None:
    """Whole nanometres, so *wider* is at least one nanometre wider -- which
    is what makes the band answer the radius it was probed at under a strict
    comparison, and what keeps it from claiming a width nobody measured."""
    probes = (Nanometre(2_000_000),)
    steps = _profile(_a_pin_on_a_can(), _UP, probes).steps

    assert (Nanometre(2_000_001), Nanometre(10_000_000), Nanometre(16_000_000)) in steps


def test_the_tip_is_measured_and_carried_beside_the_axis() -> None:
    """Where the part's tip stands along the carrier normal, in the board's
    own frame: the pin's free end at 10, not the depth 0 it is measured as
    and not the cube's own -6."""
    measured = _measured_component(_a_pin_on_a_can(), _UP)

    assert measured.tip_mm == pytest.approx(10.0, abs=1e-9)
    assert _canonicalise_component(measured).protrusion.tip_nm == Nanometre(10_000_000)  # type: ignore[union-attr]
