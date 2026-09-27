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

from stompcollider.boards import carrier_frame, group, substrates
from stompcollider.canonicalise import _canonicalise_component
from stompcollider.model import Profile
from stompcollider.protrude import (
    admissible,
    bore_of,
    clad_length,
    in_plane,
    protrusion_of,
    wall_axis,
    wall_features_of,
)
from stompcollider.raw import RawComponent
from stompgeom.cylinders import Cylinder, cylindrical_faces
from stompgeom.step import StepDocument, StepSolid, read_step
from stompmodel.frames import dot
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

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


# --------------------------------------------------------------------------
# A probe landing exactly on a tangent face must not find more than a
# narrower one. Reproduced only on the fixture's own geometry: a synthetic
# cylinder of a known radius cuts cleanly at its own tangent point, so this
# defect needs the footswitch's real bush.
# --------------------------------------------------------------------------


@pytest.mark.boards
def test_a_probe_exactly_on_a_tangent_face_finds_no_more_than_a_narrower_one(
    document: StepDocument,
) -> None:
    """``SW1``'s bush is tangent to the ⌀12 hole its own probe is drawn from.

    A probe strictly narrower than that hole's radius must never be told
    less material than the tangent probe itself: widening a probe can only
    exclude material, never uncover more of it. Two bands from one cut, read
    by the radius each was probed at rather than by stack position.
    """
    switch = _part(document, "SW1")
    narrower, tangent = Nanometre(5_999_000), Nanometre(6_000_000)
    stack = _measured_component(switch, _OUTWARD, (narrower, tangent)).stack
    bands = {band.radius_mm: band for band in stack}
    narrower_band = bands[mm_from_nm(Nanometre(narrower + 1))]
    tangent_band = bands[mm_from_nm(Nanometre(tangent + 1))]

    assert tangent_band.depth_from_tip_min_mm >= narrower_band.depth_from_tip_min_mm


# --------------------------------------------------------------------------
# A wall feature's axis is the one its material clads the most of
# --------------------------------------------------------------------------


def _a_face(
    radius: float,
    direction: tuple[float, float, float],
    extent: tuple[float, float],
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    concave: bool = False,
) -> Cylinder:
    """One cylindrical face stated directly, for a measure that reads only fields."""
    return Cylinder(
        axis_location_mm=at,
        axis_direction=direction,
        radius_mm=radius,
        extent_mm=extent,
        concave=concave,
    )


def test_a_part_with_no_in_plane_cylinder_has_no_wall_axis() -> None:
    """A part that only protrudes through the panel reaches no wall."""
    solid = StepSolid(name="RV1", shape=_pin(3.0, 8.0))
    assert wall_axis(solid, (0.0, 0.0, 1.0)) is None


def test_the_axis_with_the_most_material_along_it_wins() -> None:
    """Two in-plane axes, one clad 20 mm and one clad 1 mm: the long one is the feature.

    Built rather than measured so the margin is stated, not inherited: the
    committed board's own separation is asserted separately below.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    barrel = _pin(4.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0))
    pin = _pin(0.5, 1.0, at=(5.0, 0.0, 0.0), along=(0.0, 1.0, 0.0))
    fused = BRepAlgoAPI_Fuse(barrel, pin)
    assert fused.IsDone()
    solid = StepSolid(name="J1", shape=fused.Shape())

    found = wall_axis(solid, (0.0, 0.0, 1.0))
    assert found is not None
    assert abs(dot(found, (1.0, 0.0, 0.0))) == pytest.approx(1.0)


def test_two_short_features_far_apart_on_one_line_do_not_outrank_a_long_one() -> None:
    """The measure the plan corrects the spec on, stated as a fixture.

    Two 0.5 mm rings 16 mm apart span 17 mm and clad 1 mm. A span measure
    prefers them to a 10 mm barrel; a clad measure does not, and it is the
    clad length a hole has to admit.
    """
    ring_low = _pin(0.5, 0.5, at=(0.0, 0.0, 0.0), along=(0.0, 1.0, 0.0))
    ring_high = _pin(0.5, 0.5, at=(0.0, 16.0, 0.0), along=(0.0, 1.0, 0.0))
    faces = cylindrical_faces(ring_low) + cylindrical_faces(ring_high)
    assert clad_length(faces, (0.0, 1.0, 0.0)) == pytest.approx(1.0)


def test_a_seam_s_two_halves_clad_the_same_length_as_one_whole_face() -> None:
    """Invariance to tessellation, which is the reason for this measure.

    One surface reported as two patches covering the same extent must not
    count double -- ``cylindrical_faces`` reports per face and says a
    consumer owes that its own answer.
    """
    whole = _a_face(radius=2.0, direction=(1.0, 0.0, 0.0), extent=(0.0, 10.0))
    halves = (
        _a_face(radius=2.0, direction=(1.0, 0.0, 0.0), extent=(0.0, 6.0)),
        _a_face(radius=2.0, direction=(1.0, 0.0, 0.0), extent=(4.0, 10.0)),
    )
    assert clad_length((whole,), (1.0, 0.0, 0.0)) == pytest.approx(10.0)
    assert clad_length(halves, (1.0, 0.0, 0.0)) == pytest.approx(10.0)


@pytest.mark.boards
def test_the_committed_board_s_jacks_measure_what_the_plan_recorded(
    document: StepDocument,
) -> None:
    """Decision 7's Evidence, as assertions. A drift here fails a suite.

    Both jacks, not one: they are mirrored on the board and a rule reading
    the kernel's walk order would answer differently for the pair.
    """
    for substrate, parts in group(document, substrates(document)):
        normal = carrier_frame(substrate).w  # type: ignore[union-attr]
        for part in parts:
            if part.name not in {"J1", "J4"}:
                continue
            faces = in_plane(part, normal)
            assert len(faces) == 12
            assert admissible(part, normal) == ()
            axis = wall_axis(part, normal)
            assert axis is not None
            assert clad_length(
                [f for f in faces if f.is_parallel_to(axis)], axis
            ) == pytest.approx(24.484, abs=1e-3)
            pins = [f for f in faces if not f.is_parallel_to(axis)]
            assert len(pins) == 4
            assert {round(f.radius_mm, 3) for f in pins} == {0.550}
            assert clad_length(pins, pins[0].axis_direction) == pytest.approx(1.0)


@pytest.mark.boards
def test_the_committed_board_s_bore_is_never_wider_than_its_own_material(
    document: StepDocument,
) -> None:
    """Why Task 5 has to build a fixture: this one cannot exercise the bore branch."""
    for substrate, parts in group(document, substrates(document)):
        normal = carrier_frame(substrate).w  # type: ignore[union-attr]
        for part in parts:
            if part.name != "J1":
                continue
            faces = in_plane(part, normal)
            axis = wall_axis(part, normal)
            assert axis is not None
            assert bore_of(faces, axis) == pytest.approx(4.150)
            widest = max(f.radius_mm for f in faces if f.is_parallel_to(axis))
            assert widest == pytest.approx(7.530)


# --------------------------------------------------------------------------
# bore_of reads the deepest-clad coaxial class, not every parallel face
# --------------------------------------------------------------------------


def _a_bore_fixture() -> tuple[Cylinder, ...]:
    """A winning coaxial class and a shorter, wider, off-axis concave face.

    The winning class clads 10 mm on one line and carries a 2 mm bore; a
    second, parallel line 8 mm away clads only 1 mm but carries a wider,
    5 mm bore. A rule reading every parallel face would report the wider
    bore; a rule reading only the winning line's own material would not.
    """
    return (
        _a_face(radius=6.0, direction=(0.0, 0.0, 1.0), extent=(0.0, 10.0)),
        _a_face(
            radius=2.0,
            direction=(0.0, 0.0, 1.0),
            extent=(0.0, 10.0),
            concave=True,
        ),
        _a_face(
            radius=5.0,
            direction=(0.0, 0.0, 1.0),
            extent=(0.0, 1.0),
            at=(8.0, 0.0, 0.0),
            concave=True,
        ),
    )


def test_bore_of_reads_the_winning_lines_own_bore_not_a_wider_offset_one() -> None:
    """Decision: coaxial, not merely parallel -- a hole is cut on one ray."""
    faces = _a_bore_fixture()

    assert bore_of(faces, (0.0, 0.0, 1.0)) == pytest.approx(2.0)


def test_reordering_the_faces_does_not_change_which_bore_wins() -> None:
    """ADR-0006's own control: two spellings of one face list agree."""
    faces = _a_bore_fixture()

    assert bore_of(faces, (0.0, 0.0, 1.0)) == bore_of(
        tuple(reversed(faces)), (0.0, 0.0, 1.0)
    )


def test_bore_of_is_none_when_nothing_is_concave() -> None:
    """The documented ``None`` branch, exercised directly rather than by
    absence: a face set that is parallel and coaxial but wholly convex."""
    faces = (
        _a_face(radius=3.0, direction=(1.0, 0.0, 0.0), extent=(0.0, 5.0)),
        _a_face(radius=1.0, direction=(1.0, 0.0, 0.0), extent=(0.0, 5.0)),
    )

    assert bore_of(faces, (1.0, 0.0, 0.0)) is None


# --------------------------------------------------------------------------
# wall_features_of: both signs of the in-plane axis, in the board's own frame
# --------------------------------------------------------------------------


def test_a_part_with_no_in_plane_cylinder_yields_no_wall_feature() -> None:
    solid = StepSolid(name="RV1", shape=_pin(3.0, 8.0))
    assert wall_features_of(solid, (0.0, 0.0, 1.0)) == ()


def test_a_wall_feature_is_measured_both_ways_along_its_axis() -> None:
    """Neither sign is known to point at a wall, so neither is chosen here."""
    solid = StepSolid(
        name="J1",
        shape=_pin(4.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0)),
    )
    found = wall_features_of(solid, (0.0, 0.0, 1.0))
    assert len(found) == 2
    first, second = found
    assert first.direction == tuple(-c for c in second.direction)
    assert first.tip_mm != second.tip_mm


def test_the_pair_comes_back_in_an_order_the_geometry_fixes() -> None:
    """Ordered on the direction itself: a loop's order must reach no artefact."""
    solid = StepSolid(
        name="J1",
        shape=_pin(4.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0)),
    )
    found = wall_features_of(solid, (0.0, 0.0, 1.0))
    assert [f.direction for f in found] == sorted(f.direction for f in found)


def test_the_tip_is_the_far_end_of_the_part_along_its_own_direction() -> None:
    """A 20 mm rod from the origin: one sign tips at 20, the other at 0."""
    solid = StepSolid(
        name="J1",
        shape=_pin(4.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0)),
    )
    tips = {
        round(f.direction[0]): pytest.approx(f.tip_mm[0], abs=1e-9)
        for f in wall_features_of(solid, (0.0, 0.0, 1.0))
    }
    assert tips[1] == 20.0
    assert tips[-1] == 0.0


def test_a_tube_s_bore_is_measured_off_the_solid_and_not_assumed() -> None:
    """The read the committed board cannot make govern -- ruling 7.

    A tube, not a jack: what is under test is that a concave coaxial face
    reaches ``bore_mm`` at all. Whether a bore *governs* a diameter is
    arithmetic over a profile, and the drill side drives that.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    outer = _pin(5.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0))
    bore = _pin(3.0, 30.0, at=(-5.0, 0.0, 0.0), along=(1.0, 0.0, 0.0))
    cut = BRepAlgoAPI_Cut(outer, bore)
    assert cut.IsDone()
    solid = StepSolid(name="J9", shape=cut.Shape())

    found = wall_features_of(solid, (0.0, 0.0, 1.0))
    assert len(found) == 2
    for feature in found:
        assert feature.bore_mm == pytest.approx(3.0)


def test_a_solid_part_states_no_bore_rather_than_a_zero_one() -> None:
    solid = StepSolid(
        name="J1",
        shape=_pin(4.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0)),
    )
    assert all(f.bore_mm is None for f in wall_features_of(solid, (0.0, 0.0, 1.0)))


@pytest.mark.boards
def test_the_committed_board_s_jack_measures_the_stack_the_plan_recorded(
    document: StepDocument,
) -> None:
    """The profile the span rule is asserted against, in whole nanometres.

    Stated in nanometres and not millimetres because these are the numbers
    ``canonicalise`` will scale to, and a float assertion here would not
    notice the day the scaling changed.
    """
    for substrate, parts in group(document, substrates(document)):
        normal = carrier_frame(substrate).w  # type: ignore[union-attr]
        for part in parts:
            if part.name != "J1":
                continue
            outward = next(
                f for f in wall_features_of(part, normal) if f.direction[0] < 0.0
            )
            steps = {
                (
                    nm_from_mm(c.radius_mm),
                    nm_from_mm(c.depth_from_tip_min_mm),
                    nm_from_mm(c.depth_from_tip_max_mm),
                )
                for c in outward.stack
            }
            assert steps == {
                (4_150_000, 0, 3_000_000),
                (5_700_000, 0, 3_000_000),
                (3_250_000, 3_000_000, 24_483_612),
                (7_530_000, 3_000_000, 23_610_000),
            }
            assert outward.bore_mm == pytest.approx(4.150)


def _collared_jack() -> StepSolid:
    """A 3 mm barrel 20 mm long with an 8 mm collar on its outermost 2 mm.

    The shape a wall span meets: the collar stands *outside* the wall, which
    the barrel passes through, so the wide material is shallower than the span
    rather than deeper. The committed board's jack is the other way round --
    its 7.530 mm flange sits behind the wall -- so nothing measured reaches
    this arrangement.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    barrel = _pin(3.0, 20.0, at=(0.0, 0.0, 0.0), along=(1.0, 0.0, 0.0))
    collar = _pin(8.0, 2.0, at=(18.0, 0.0, 0.0), along=(1.0, 0.0, 0.0))
    fused = BRepAlgoAPI_Fuse(barrel, collar)
    assert fused.IsDone()
    return StepSolid(name="J1", shape=fused.Shape())


def _outward(features: tuple[Any, ...]) -> Any:
    return next(f for f in features if f.direction[0] > 0.0)


def _widest_at(feature: Any, depth_mm: float) -> float:
    """The widest radius the stack claims at one depth from the tip."""
    return max(
        band.radius_mm
        for band in feature.stack
        if band.depth_from_tip_min_mm <= depth_mm <= band.depth_from_tip_max_mm
    )


def test_a_probed_band_claims_no_material_the_part_does_not_have_at_that_depth() -> None:
    """The wall's question is a span, not an insertion depth.

    Through a panel, everything behind the first obstruction is unreachable, so
    a band running to the part's far end is the truth about how deep it can go.
    Across a wall's span only the material *in* the span is in the hole, and a
    band open to the far end reports a collar standing clear of the wall as
    though it were inside it -- which sizes the hole to the collar.
    """
    solid = _collared_jack()
    found = wall_features_of(solid, _UP, probes_nm=(Nanometre(4_000_000),))
    assert len(found) == 2
    # 5 mm from the tip is three millimetres behind the collar, where the part
    # is the bare barrel.
    assert _widest_at(_outward(found), 5.0) == pytest.approx(3.0, abs=1e-6)


def test_a_probed_band_still_states_material_that_is_in_the_span() -> None:
    """The control: bounding a band must not stop it reporting the collar itself."""
    found = wall_features_of(_collared_jack(), _UP, probes_nm=(Nanometre(4_000_000),))
    assert _widest_at(_outward(found), 1.0) > 4.0
