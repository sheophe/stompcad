"""Where a feature's ray crosses a wall, and what the crossing states.

Frames and arithmetic, with no kernel and no model: the two planes a wall has
are a datum and a thickness, and everything here is a division. The region
test that decides whether a crossing is drillable is the model's, and
``DrillWalls``' own tests drive it against a fake one.
"""

from __future__ import annotations

from stompdrill.pipeline.diameters import DEFAULT_STANDARD, DRILL_STANDARDS
from stompdrill.pipeline.walls import crossing, required_radius_nm, stocked_diameter_nm
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import DrilledSurface, Profile, WallFeature
from stompmodel.units import Nanometre

__all__: list[str] = []

#: A face frame whose ``u``/``v`` are the model's X/Z and whose ``w`` is +Y --
#: the arrangement every catalogued box has, so the numbers below read as
#: model millimetres.
FACE = FaceFrame(
    basis=CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 0.0, -1.0),
        w=(0.0, 1.0, 0.0),
    )
)


def _wall(key: str = "right", thickness_mm: float = 2.0, at_mm: float = 30.0) -> DrilledSurface:
    """An undrafted wall at ``at_mm`` along +X, facing +X, 40 x 20 mm.

    Undrafted so the crossings are numbers a reader can check by hand; the
    drafted case is what the cached models exercise, in Task 15.
    """
    thickness_nm = Nanometre(int(thickness_mm * 1_000_000))
    inner = at_mm - thickness_mm
    return DrilledSurface(
        key=key,
        frame=FaceFrame(
            basis=CoordinateFrame(
                origin_nm=(Nanometre(int(inner * 1_000_000)), Nanometre(0), Nanometre(0)),
                u=(0.0, 0.0, -1.0),
                v=(0.0, 1.0, 0.0),
                w=(1.0, 0.0, 0.0),
            )
        ),
        thickness_nm=thickness_nm,
        bounds_nm=(
            Nanometre(-20_000_000), Nanometre(-10_000_000),
            Nanometre(20_000_000), Nanometre(10_000_000),
        ),
    )


def _feature(
    origin_mm: tuple[float, float, float] = (32.0, 0.0, 0.0),
    direction: tuple[float, float, float] = (1.0, 0.0, 0.0),
    bore_nm: Nanometre | None = None,
) -> WallFeature:
    """A feature tipping 2 mm outside the wall, pointing straight out along +X.

    ``origin_mm`` is stated in the **case face frame**, whose ``u``/``v``/``w``
    are X/Z/Y, so the tuple reads as ``(u, v, depth)``.
    """
    return WallFeature(
        designator="J1",
        board=1,
        origin_nm=tuple(Nanometre(int(value * 1_000_000)) for value in origin_mm),  # type: ignore[arg-type]
        direction=direction,
        profile=Profile(
            steps=((Nanometre(5_000_000), Nanometre(0), Nanometre(10_000_000)),)
        ),
        bore_nm=bore_nm,
    )


def test_a_ray_pointing_away_from_a_wall_never_crosses_it() -> None:
    """Which is the whole reason both signs of an axis are measured."""
    assert crossing(_wall(), _feature(direction=(-1.0, 0.0, 0.0)), FACE) is None


def test_a_ray_parallel_to_a_wall_never_crosses_it() -> None:
    assert crossing(_wall(), _feature(direction=(0.0, 0.0, 1.0)), FACE) is None


def test_a_protruding_feature_crosses_the_outer_plane_nearer_its_tip() -> None:
    """Depths grow back from the tip, so the outer crossing is the shallower."""
    found = crossing(_wall(), _feature(), FACE)
    assert found is not None
    assert found.key == "right"
    assert found.span_nm == (Nanometre(2_000_000), Nanometre(4_000_000))


def test_the_crossings_land_on_the_wall_s_own_datum_for_an_axial_ray() -> None:
    found = crossing(_wall(), _feature(), FACE)
    assert found is not None
    assert found.outer_nm == (Nanometre(0), Nanometre(0))
    assert found.inner_nm == (Nanometre(0), Nanometre(0))


def test_an_oblique_ray_crosses_the_two_planes_at_different_places() -> None:
    """Decision 8's consequence: a hole coaxial with its part is not wall-normal."""
    import math

    tilt = math.radians(30.0)
    oblique = _feature(direction=(math.cos(tilt), 0.0, math.sin(tilt)))
    found = crossing(_wall(), oblique, FACE)
    assert found is not None
    assert found.outer_nm != found.inner_nm


def test_a_recessed_feature_crosses_the_wall_behind_its_own_tip() -> None:
    """The case the bore exists for: the wall's span holds none of the part.

    A negative outer depth is not an error -- it says the tip stops short of
    the wall, and the plug still has to get through it.
    """
    recessed = _feature(origin_mm=(27.0, 0.0, 0.0))
    found = crossing(_wall(), recessed, FACE)
    assert found is not None
    assert found.span_nm == (Nanometre(-3_000_000), Nanometre(-1_000_000))


def test_the_crossing_names_the_surface_it_was_asked_about() -> None:
    assert crossing(_wall(key="top"), _feature(), FACE).key == "top"  # type: ignore[union-attr]


#: J1's measured stack, in whole nanometres -- see the plan's Evidence. The
#: 7.530 mm radius is the material a hole must *not* be sized for when the
#: wall is crossed inside the outermost three millimetres.
_J1 = Profile(
    steps=(
        (Nanometre(4_150_000), Nanometre(0), Nanometre(3_000_000)),
        (Nanometre(5_700_000), Nanometre(0), Nanometre(3_000_000)),
        (Nanometre(3_250_000), Nanometre(3_000_000), Nanometre(24_483_612)),
        (Nanometre(7_530_000), Nanometre(3_000_000), Nanometre(23_610_000)),
    )
)


def _jack(bore_nm: Nanometre | None = None) -> WallFeature:
    return WallFeature(
        designator="J1",
        board=1,
        origin_nm=(Nanometre(32_000_000), Nanometre(0), Nanometre(0)),
        direction=(1.0, 0.0, 0.0),
        profile=_J1,
        bore_nm=bore_nm,
    )


def test_a_modelled_nut_outside_the_wall_does_not_inflate_the_hole() -> None:
    """Decision 9's own counter-example, as arithmetic over the measured stack."""
    inside = required_radius_nm(_jack(), (Nanometre(500_000), Nanometre(2_500_000)))
    assert inside == 5_700_000


def test_the_whole_part_would_ask_for_a_hole_half_again_as_wide() -> None:
    """What the span rule is worth, stated so the rule cannot be quietly dropped."""
    everything = required_radius_nm(_jack(), (Nanometre(0), Nanometre(24_483_612)))
    assert everything == 7_530_000


def test_the_span_rule_is_the_difference_between_two_stocked_sizes() -> None:
    standard = DRILL_STANDARDS[DEFAULT_STANDARD]
    inside = required_radius_nm(_jack(), (Nanometre(500_000), Nanometre(2_500_000)))
    everything = required_radius_nm(_jack(), (Nanometre(0), Nanometre(24_483_612)))
    assert stocked_diameter_nm(inside, standard) == 11_400_000
    assert stocked_diameter_nm(everything, standard) == 15_500_000


def test_a_step_boundary_inside_the_span_is_evaluated_and_not_skipped() -> None:
    """The profile is piecewise constant, so the widest step inside the span governs."""
    across = required_radius_nm(_jack(), (Nanometre(2_000_000), Nanometre(4_000_000)))
    assert across == 7_530_000


def test_a_span_holding_no_material_needs_no_hole_for_material() -> None:
    """A recessed part: the envelope is nothing there, which is what the bore is for."""
    assert required_radius_nm(_jack(), (Nanometre(-3_000_000), Nanometre(-1_000_000))) == 0


def test_a_bore_is_a_floor_on_the_radius_however_little_material_surrounds_it() -> None:
    """Ruling 6, and the case the committed board cannot make govern."""
    recessed = (Nanometre(-3_000_000), Nanometre(-1_000_000))
    assert required_radius_nm(_jack(bore_nm=Nanometre(3_175_000)), recessed) == 3_175_000


def test_material_wider_than_the_bore_governs_over_it() -> None:
    inside = (Nanometre(500_000), Nanometre(2_500_000))
    assert required_radius_nm(_jack(bore_nm=Nanometre(3_175_000)), inside) == 5_700_000


def test_the_smallest_stocked_size_that_admits_the_part_is_chosen() -> None:
    """A bound and not a nearest: rounding down would leave the part not fitting."""
    standard = DRILL_STANDARDS[DEFAULT_STANDARD]
    assert stocked_diameter_nm(Nanometre(5_649_000), standard) == 11_300_000
    assert stocked_diameter_nm(Nanometre(5_700_000), standard) == 11_400_000
    assert stocked_diameter_nm(Nanometre(5_700_001), standard) == 11_500_000


def test_a_requirement_past_the_standard_s_stock_is_answered_with_none() -> None:
    standard = DRILL_STANDARDS[DEFAULT_STANDARD]
    assert stocked_diameter_nm(Nanometre(20_000_000), standard) is None


def test_a_narrowed_standard_can_refuse_what_the_full_one_stocks() -> None:
    """The operator's own selection is the answer set, per ADR-0002."""
    narrowed = DRILL_STANDARDS[DEFAULT_STANDARD].select(
        include=(Nanometre(6_000_000), Nanometre(8_000_000))
    )
    assert stocked_diameter_nm(Nanometre(3_500_000), narrowed) == 8_000_000
    assert stocked_diameter_nm(Nanometre(4_500_000), narrowed) is None
