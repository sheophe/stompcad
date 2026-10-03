"""Where a feature's ray crosses a wall, and what the crossing states.

Frames and arithmetic, with no kernel and no model: the two planes a wall has
are a datum and a thickness, and everything here is a division. The region
test that decides whether a crossing is drillable is the model's, and
``DrillWalls``' own tests drive it against a fake one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

import pytest

from stompdrill.cad import Rejection, WallModel
from stompdrill.cli import build_parser, build_pipeline
from stompdrill.errors import StompdrillError
from stompdrill.pipeline.diameters import DEFAULT_STANDARD, DRILL_STANDARDS
from stompdrill.pipeline.walls import (
    DrillWalls,
    crossing,
    required_radius_nm,
    stocked_diameter_nm,
)
from stompmodel.diagnostics import Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import (
    SURFACE_FACE,
    CaseFace,
    CaseRegistration,
    DrillData,
    DrilledSurface,
    Profile,
    ReferenceOutline,
    WallFeature,
)
from stompmodel.protocols import Pipeline
from stompmodel.units import Nanometre
from tests.conftest import FakeCase

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


#: A part whose material begins three millimetres behind its tip, so a run that
#: ends at the tip holds none of it.
_BARE_TIP = Profile(
    steps=((Nanometre(5_700_000), Nanometre(3_000_000), Nanometre(10_000_000)),)
)


def _jack(
    bore_nm: Nanometre | None = None, profile: Profile = _J1
) -> WallFeature:
    return WallFeature(
        designator="J1",
        board=1,
        origin_nm=(Nanometre(32_000_000), Nanometre(0), Nanometre(0)),
        direction=(1.0, 0.0, 0.0),
        profile=profile,
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
    """Neither endpoint reaches the wide step; only its interior boundary does."""
    across = required_radius_nm(_jack(), (Nanometre(1_000_000), Nanometre(24_000_000)))
    assert across == 7_530_000


def test_a_part_seated_short_of_the_wall_is_still_measured_to_its_tip() -> None:
    """ADR-0007's amendment. A jack's sleeve must pass the hole whether it is
    flush with the inner face or a few millimetres inside it, so the run
    measured is the one the part travels, not the wall's own thickness."""
    flush = required_radius_nm(_jack(), (Nanometre(500_000), Nanometre(2_500_000)))
    short = required_radius_nm(_jack(), (Nanometre(-3_500_000), Nanometre(-1_500_000)))
    assert flush == 5_700_000
    assert short == 5_700_000


def test_the_run_ends_at_the_tip_so_a_nut_beyond_it_does_not_widen_the_hole() -> None:
    """The guarantee the amendment must not cost: the flange behind the bushing
    is 7.530 mm, and a rule reading the whole part would ask for it."""
    short = required_radius_nm(_jack(), (Nanometre(-3_500_000), Nanometre(-1_500_000)))
    assert short < 7_530_000


def test_a_gap_no_longer_costs_the_sleeve_its_hole() -> None:
    """What the correction is worth, in the only units a builder buys in: the
    bore alone stocks at 8.300, which the 11.400 sleeve cannot pass."""
    standard = DRILL_STANDARDS[DEFAULT_STANDARD]
    short = required_radius_nm(_jack(), (Nanometre(-3_500_000), Nanometre(-1_500_000)))
    assert stocked_diameter_nm(short, standard) == 11_400_000
    assert stocked_diameter_nm(Nanometre(4_150_000), standard) == 8_300_000


def test_a_part_reaching_past_the_inner_face_measures_only_to_that_face() -> None:
    """The other direction: a part already inside the wall is not measured
    further back than the wall, or the flange behind it would widen the hole."""
    deep = required_radius_nm(_jack(), (Nanometre(2_000_000), Nanometre(23_000_000)))
    assert deep == 7_530_000


def test_a_span_holding_no_material_needs_no_hole_for_material() -> None:
    """A bare tip: no material lies in the run, which is what the bore is for."""
    bare = _jack(profile=_BARE_TIP)
    assert required_radius_nm(bare, (Nanometre(-3_000_000), Nanometre(-1_000_000))) == 0


def test_a_bore_is_a_floor_on_the_radius_however_little_material_surrounds_it() -> None:
    """Ruling 6, and the case the committed board cannot make govern."""
    recessed = (Nanometre(-3_000_000), Nanometre(-1_000_000))
    bore = Nanometre(3_175_000)
    assert required_radius_nm(_jack(bore_nm=bore, profile=_BARE_TIP), recessed) == 3_175_000


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


# ---------------------------------------------------------------------------
# DrillWalls
# ---------------------------------------------------------------------------


@dataclass
class _FakeWalls:
    """A wall model that answers with arithmetic, so the stage is testable alone.

    ``admitting`` names the surfaces whose region accepts a point at all and
    ``rejecting`` maps a surface to the refusal it gives a sized hole, which is
    every question ``DrillWalls`` asks of a model.
    """

    walls: tuple[DrilledSurface, ...]
    admitting: frozenset[str] = frozenset()
    rejecting: Mapping[str, Rejection] = field(default_factory=dict)
    walls_unavailable: str | None = None

    def admits(self, key: str, x_nm: Nanometre, y_nm: Nanometre) -> bool:
        return key in self.admitting

    def classify_wall(
        self,
        key: str,
        outer_nm: tuple[Nanometre, Nanometre],
        inner_nm: tuple[Nanometre, Nanometre],
        radius_nm: Nanometre,
    ) -> Rejection | None:
        return self.rejecting.get(key)


def test_the_fake_really_is_a_wall_model() -> None:
    """``DrillWalls`` is typed against ``WallModel``, so the fake must satisfy it.

    Without this, every test below would drive a shape that merely happens to
    have the right method names today.
    """
    assert isinstance(_FakeWalls(walls=(_wall(),)), WallModel)


def _data() -> DrillData:
    """A document registering a case and its plate, as the clearance stage leaves one."""
    return DrillData(
        holes=(),
        reference=ReferenceOutline.from_measurement(
            Nanometre(112_400_000), Nanometre(60_500_000)
        ),
        case=CaseRegistration("1590B", CaseFace.BOX, "1590B.stp", FACE),
        surfaces=(
            DrilledSurface(
                key=SURFACE_FACE,
                frame=FACE,
                thickness_nm=Nanometre(2_000_000),
                bounds_nm=(
                    Nanometre(-55_000_000), Nanometre(-30_000_000),
                    Nanometre(55_000_000), Nanometre(30_000_000),
                ),
            ),
        ),
    )


def _seated(across_mm: float = 0.0, designator: str = "J1") -> WallFeature:
    """``_jack()`` tipping half a millimetre outside the 2 mm wall ``_wall()`` is.

    The whole of that wall then lies inside the barrel's outermost three
    millimetres, which is the span rule's own case: the hole admits the
    5.700 mm bushing and not the 7.530 mm flange standing behind it, so this
    is the feature whose hole a reader can check against the file's own
    ``required_radius_nm`` tests. ``across_mm`` slides the tip along the wall,
    so two features can differ in where their holes land.
    """
    return replace(
        _jack(),
        designator=designator,
        origin_nm=(
            Nanometre(30_500_000), Nanometre(int(across_mm * 1_000_000)), Nanometre(0)
        ),
    )


def _stage(model: _FakeWalls, *features: WallFeature) -> DrillWalls:
    return DrillWalls(model, features, DRILL_STANDARDS[DEFAULT_STANDARD])


def _drill_pipeline() -> Pipeline[DrillData]:
    """The pipeline ``cli.build_pipeline`` composes with a case model supplied.

    Built the way ``test_cli`` and ``test_invariant`` build theirs -- parsed
    defaults plus the one attribute the CLI attaches -- rather than a second
    namespace builder of this module's own.
    """
    args = build_parser().parse_args(["panel.ai"])
    args.case_model_object = FakeCase()
    return build_pipeline(args)


def test_a_stage_with_no_feature_changes_nothing_at_all() -> None:
    """Decision 18's byte identity, at the stage rather than at the artefact."""
    data = _data()
    found = _stage(_FakeWalls(walls=(_wall(),))).apply(data)
    assert found.holes == ()
    assert found.surfaces == data.surfaces
    assert found.diagnostics == ()


def test_a_reachable_feature_becomes_a_hole_on_the_wall_it_reaches() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    found = _stage(model, _seated()).apply(_data())
    assert len(found.holes) == 1
    hole = found.holes[0]
    assert hole.surface == "right"
    assert hole.index is None
    assert hole.diameter_nm == 11_400_000


def test_the_hole_sits_where_the_axis_crosses_the_outer_plane() -> None:
    """The surface a builder marks, which is why the datum is stated there."""
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    found = _stage(model, _seated()).apply(_data())
    assert (found.holes[0].x_nm, found.holes[0].y_nm) == (Nanometre(0), Nanometre(0))


def test_a_wall_that_took_a_hole_is_registered_beside_the_plate() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    found = _stage(model, _seated()).apply(_data())
    assert [surface.key for surface in found.surfaces or ()] == [SURFACE_FACE, "right"]


def test_a_wall_nothing_was_drilled_in_is_not_registered() -> None:
    """A wall with no hole is not a setup, so it is owed no record and no file."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall(key="left")), admitting=frozenset({"right"})
    )
    found = _stage(model, _seated()).apply(_data())
    assert [surface.key for surface in found.surfaces or ()] == [SURFACE_FACE, "right"]


def test_a_run_that_drilled_no_wall_registers_exactly_what_it_was_handed() -> None:
    """``None`` and an empty tuple are different claims in the document (codec)."""
    data = replace(_data(), surfaces=None)
    found = _stage(_FakeWalls(walls=(_wall(key="right"),)), _seated()).apply(data)
    assert found.surfaces is None


def test_a_feature_reaching_no_wall_is_an_error_naming_the_component() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),))
    found = _stage(model, _seated()).apply(_data())
    refused = [d for d in found.diagnostics if d.code == "wall-feature-unreachable"]
    assert len(refused) == 1
    assert refused[0].severity is Severity.ERROR
    assert "J1" in refused[0].message
    assert found.holes == ()


def test_a_model_that_found_no_walls_blames_the_enclosure_and_names_why() -> None:
    reason = "no flat face backs the drilled face"
    model = _FakeWalls(walls=(), walls_unavailable=reason)
    found = _stage(model, _seated()).apply(_data())
    (refused,) = [d for d in found.diagnostics if d.code == "wall-feature-unreachable"]
    assert "walls of this enclosure could not be determined" in refused.message
    assert reason in refused.message
    assert "its axis reaches" not in refused.message
    assert "J1" in refused.message
    assert found.holes == ()


def test_a_feature_missing_the_walls_a_model_has_still_blames_its_axis() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),))
    found = _stage(model, _seated()).apply(_data())
    (refused,) = [d for d in found.diagnostics if d.code == "wall-feature-unreachable"]
    assert "its axis reaches no drillable part of any wall" in refused.message
    assert "could not be determined" not in refused.message


def test_a_model_with_walls_is_never_blamed_whatever_it_says_it_lacks() -> None:
    """The reason is read only where there are no walls to reach."""
    model = _FakeWalls(walls=(_wall(key="right"),), walls_unavailable="stale")
    found = _stage(model, _seated()).apply(_data())
    (refused,) = [d for d in found.diagnostics if d.code == "wall-feature-unreachable"]
    assert "stale" not in refused.message


def test_both_signs_of_one_axis_earn_one_finding_and_not_two() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),))
    outward = _seated()
    inward = replace(outward, direction=(-1.0, 0.0, 0.0))
    found = _stage(model, outward, inward).apply(_data())
    assert len([d for d in found.diagnostics if d.code == "wall-feature-unreachable"]) == 1


@pytest.mark.parametrize("along", [1e-9, 1e-30])
def test_a_ray_grazing_a_wall_is_refused_rather_than_raising(along: float) -> None:
    """A whisker off parallel meets the plane, unboundedly far along the wall.

    ``crossing`` answers *where* a ray meets a plane and owns no bound, so the
    bound is this stage's. Two magnitudes, because two things go wrong without
    it: at 1e-9 the crossing is thirty kilometres from the datum and a hole
    would be cut there, and below about 1e-22 the travel is a magnitude
    ``nm_from_mm`` refuses outright, so the stage would raise where a refusal
    is owed. The fake's region admits every point, which is what makes both
    cases discriminate here rather than only the second.
    """
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    graze = replace(
        _seated(), direction=(along, math.sqrt(1.0 - along * along), 0.0)
    )
    found = _stage(model, graze).apply(_data())
    assert [d.code for d in found.diagnostics] == ["wall-feature-unreachable"]
    assert found.holes == ()


def test_a_hole_whose_circle_leaves_the_wall_is_refused_as_off_face() -> None:
    model = _FakeWalls(
        walls=(_wall(key="right"),),
        admitting=frozenset({"right"}),
        rejecting={"right": Rejection.OFF_FACE},
    )
    found = _stage(model, _seated()).apply(_data())
    assert [d.code for d in found.diagnostics] == ["hole-off-face"]
    assert found.holes == ()


def test_a_hole_fouling_what_stands_behind_the_wall_is_refused_as_through_boss() -> None:
    model = _FakeWalls(
        walls=(_wall(key="right"),),
        admitting=frozenset({"right"}),
        rejecting={"right": Rejection.THROUGH_BOSS},
    )
    found = _stage(model, _seated()).apply(_data())
    assert [d.code for d in found.diagnostics] == ["hole-through-boss"]


def test_a_requirement_past_the_standard_s_stock_is_the_unstocked_refusal() -> None:
    """An existing code on a new surface, rather than a fifth one invented for it."""
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    huge = replace(
        _seated(),
        profile=Profile(steps=((Nanometre(20_000_000), Nanometre(0), Nanometre(10_000_000)),)),
    )
    found = _stage(model, huge).apply(_data())
    assert [d.code for d in found.diagnostics] == ["unknown-diameter"]
    assert found.holes == ()


def _wall_facing_back(key: str = "left", at_mm: float = -30.0) -> DrilledSurface:
    """A 2 mm wall at ``at_mm`` along -X, facing -X, the mirror of ``_wall()``.

    Needed because the backward sign of an axis reaches the *opposite* wall, and
    ``_wall()`` only ever faces +X, so one of the two signs could never resolve.
    """
    return DrilledSurface(
        key=key,
        frame=FaceFrame(
            basis=CoordinateFrame(
                origin_nm=(Nanometre(int((at_mm + 2.0) * 1_000_000)), Nanometre(0), Nanometre(0)),
                u=(0.0, 0.0, -1.0),
                v=(0.0, -1.0, 0.0),
                w=(-1.0, 0.0, 0.0),
            )
        ),
        thickness_nm=Nanometre(2_000_000),
        bounds_nm=(
            Nanometre(-20_000_000), Nanometre(-10_000_000),
            Nanometre(20_000_000), Nanometre(10_000_000),
        ),
    )


def test_the_sign_whose_wall_is_nearer_its_own_tip_carries_the_hole() -> None:
    """ADR-0007's amendment: a part is mounted at the wall it passes through.

    ``_seated()``'s tip sits half a millimetre outside ``_wall()``, so the
    forward ray's wall is 2.5 mm behind that tip and the wall facing back at
    -30 is 58.5 mm ahead of it. Nothing about the part changes between this
    test and its mirror below; only which wall it is standing at does.
    """
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "left"}),
    )
    forward = _seated()
    backward = replace(forward, direction=(-1.0, 0.0, 0.0))

    cut = _stage(model, forward, backward).apply(_data())

    assert [hole.surface for hole in cut.holes] == ["right"]
    assert not [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]


def test_the_mirrored_part_is_drilled_through_the_mirrored_wall() -> None:
    """The control a nearest-wins rule must pass and a farthest-wins rule cannot.

    The same two walls and the same jack, its tip moved to the other side of
    the enclosure. A rule reading the sign rather than the distance would
    answer ``right`` both times.
    """
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "left"}),
    )
    forward = replace(
        _seated(), origin_nm=(Nanometre(-30_500_000), Nanometre(0), Nanometre(0))
    )
    backward = replace(forward, direction=(-1.0, 0.0, 0.0))

    cut = _stage(model, forward, backward).apply(_data())

    assert [hole.surface for hole in cut.holes] == ["left"]


def test_two_walls_equally_near_are_refused_rather_than_broken() -> None:
    """Nothing geometric separates them, so a tie-break would be invented here."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "left"}),
    )
    # Midway: 28 mm from each wall's inner plane, which is the only way two
    # walls are equally near when the part is not touching either.
    forward = replace(_seated(), origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)))
    backward = replace(forward, direction=(-1.0, 0.0, 0.0))

    cut = _stage(model, forward, backward).apply(_data())

    assert not cut.holes
    refusals = [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]
    assert len(refusals) == 1
    assert "equally near" in refusals[0].message
    assert "left, right" in refusals[0].message


def test_one_ray_in_two_regions_is_refused_without_ending_the_run() -> None:
    """Decision 13's ambiguity is argued and measured unreachable; a raise here
    would still abandon every other component's hole, because this stage runs
    after the drill half has committed."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall(key="top")),
        admitting=frozenset({"right", "top"}),
    )

    cut = _stage(model, _seated()).apply(_data())

    assert not cut.holes
    refusals = [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]
    assert len(refusals) == 1
    assert "more than one wall" in refusals[0].message


def test_another_component_is_still_drilled_when_one_is_refused() -> None:
    """The whole reason neither refusal raises."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "left"}),
    )
    tied = replace(_seated(), origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)))
    tied_back = replace(tied, direction=(-1.0, 0.0, 0.0))
    other = _seated(designator="J2")

    cut = _stage(model, tied, tied_back, other).apply(_data())

    assert [hole.surface for hole in cut.holes] == ["right"]
    assert len([d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]) == 1


def test_a_document_registering_no_case_has_no_frame_to_resolve_against() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    with pytest.raises(StompdrillError, match="registers no case model"):
        _stage(model, _seated()).apply(replace(_data(), case=None))


def test_holes_come_back_in_an_order_the_geometry_fixes() -> None:
    """Board, then designator: no mapping's iteration order reaches a hole (ADR-0006)."""
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    first, second = _seated(), _seated(across_mm=5.0, designator="J4")
    one = _stage(model, first, second).apply(_data())
    other = _stage(model, second, first).apply(_data())
    assert [h.raw for h in one.holes] == [h.raw for h in other.holes]
    assert one.holes[0].x_nm != one.holes[1].x_nm


def test_the_standalone_pipeline_composes_no_wall_stage() -> None:
    """Decision 18: ``stompdrill`` drills no wall, because it has no seating.

    Asserted on the composed stages and not on the flags: a stage reachable
    from ``build_pipeline`` would be reachable from the command line, and
    ``DrillWalls`` needs a ranking nothing there can produce.
    """
    composed = _drill_pipeline()
    assert not any(isinstance(stage, DrillWalls) for stage in composed)
    assert "drill-walls" not in {stage.name for stage in composed}


def test_the_stage_records_the_standard_and_the_feature_count_it_ran_with() -> None:
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    run = _stage(model, _seated()).describe()
    assert run.name == "drill-walls"
    assert dict(run.parameters)["standard"] == "metric"
    assert dict(run.parameters)["features"] == 1


def test_a_part_whose_span_holds_nothing_of_it_is_refused_and_not_drilled() -> None:
    """A required radius of zero is no hole: every stocked size admits nothing.

    The axis reaches the wall's own region, so nothing above refuses it, and
    the smallest size in the standard satisfies a requirement of zero. The
    part's material begins behind its tip, so none of it lies in the run.
    """
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    short = replace(
        _seated(),
        origin_nm=(Nanometre(8_000_000), Nanometre(0), Nanometre(0)),
        profile=_BARE_TIP,
    )
    found = _stage(model, short).apply(_data())
    assert found.holes == ()
    assert [d.code for d in found.diagnostics] == ["wall-feature-unreachable"]
    assert found.diagnostics[0].severity is Severity.ERROR
    assert "right" in found.diagnostics[0].message


def test_a_bore_with_no_material_in_the_span_still_asks_for_its_hole() -> None:
    """A bare tip has no material in the run, and the bore still asks for a hole.

    The companion of the refusal above, so narrowing it to the both-absent
    case cannot quietly take the bore's own hole with it.
    """
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))
    recessed = replace(
        _seated(),
        origin_nm=(Nanometre(27_000_000), Nanometre(0), Nanometre(0)),
        profile=_BARE_TIP,
        bore_nm=Nanometre(3_175_000),
    )
    found = _stage(model, recessed).apply(_data())
    assert found.diagnostics == ()
    assert [hole.diameter_nm for hole in found.holes] == [6_400_000]


def test_a_hole_obstructed_by_what_stands_behind_the_wall_is_refused() -> None:
    """The third refusal the ``WallModel`` contract can give, which today's loader cannot.

    Reachable through the protocol regardless, so the clause it renders is
    exercised rather than left to a reader's word.
    """
    model = _FakeWalls(
        walls=(_wall(key="right"),),
        admitting=frozenset({"right"}),
        rejecting={"right": Rejection.OBSTRUCTED},
    )
    found = _stage(model, _seated()).apply(_data())
    assert [d.code for d in found.diagnostics] == ["hole-obstructed"]
    assert found.holes == ()


@pytest.mark.parametrize(
    ("rejection", "clause"),
    [
        (Rejection.OFF_FACE, "lies outside the drillable part of the left wall"),
        (Rejection.THROUGH_BOSS, "meets a boss or rib in the left wall"),
        (Rejection.OBSTRUCTED, "is obstructed by what stands behind the left wall"),
    ],
)
def test_a_wall_refusal_names_a_surface_and_never_the_drilled_plate(
    rejection: Rejection, clause: str
) -> None:
    """The glossary keeps "face" and "surface" apart, so these clauses must too.

    A wall hole told it left the drilled face sends a builder to the wrong
    surface, and the plate's own clause reads as nonsense with a wall appended
    to it. Each of the three is asserted whole, because the thing being checked
    is the sentence.
    """
    model = _FakeWalls(
        walls=(_wall(key="left"),),
        admitting=frozenset({"left"}),
        rejecting={"left": rejection},
    )
    found = _stage(model, _seated()).apply(_data())
    assert found.diagnostics[0].message == (
        f"⌀11.400 mm hole for board 1's J1 at (0.000, 0.000) {clause}"
    )
    assert "drilled face" not in found.diagnostics[0].message


def test_a_second_part_wanting_the_hole_a_wall_already_has_is_refused() -> None:
    """Decision 14's overlap review runs inside ``drill``, five steps earlier,
    so this stage is the only thing that can see two wall holes at once. Cut
    twice, the second pass runs a bit down a hole that is already there."""
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))

    cut = _stage(model, _seated(), _seated(designator="J2")).apply(_data())

    assert len(cut.holes) == 1
    refusals = [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]
    assert len(refusals) == 1
    assert "already" in refusals[0].message


def test_two_parts_at_different_places_on_one_wall_both_get_holes() -> None:
    """The control. ``across_mm`` slides the tip along the wall, which is what
    that parameter is for, so this is two holes and not one repeated."""
    model = _FakeWalls(walls=(_wall(key="right"),), admitting=frozenset({"right"}))

    cut = _stage(
        model, _seated(), _seated(across_mm=8.0, designator="J2")
    ).apply(_data())

    assert len(cut.holes) == 2
    assert not [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]


def test_parts_at_the_same_place_in_two_walls_frames_both_get_holes() -> None:
    """Each wall states its crossings in its own frame, so two walls can share
    ``(0, 0)``: a place is a coordinate *and* the surface it is measured in."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "left"}),
    )
    left_part = replace(
        _seated(designator="J2"),
        origin_nm=(Nanometre(-30_500_000), Nanometre(0), Nanometre(0)),
        direction=(-1.0, 0.0, 0.0),
    )

    cut = _stage(model, _seated(), left_part).apply(_data())

    assert sorted(hole.surface for hole in cut.holes) == ["left", "right"]
    assert not [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]


def test_one_sign_in_two_regions_is_refused_even_when_the_other_sign_reaches_one() -> None:
    """The refusal means what its clause says: one ray, two regions, whatever
    the other sign does. Three hits are not a ranking between two."""
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall(key="top"), _wall_facing_back(key="left")),
        admitting=frozenset({"right", "top", "left"}),
    )
    forward = _seated()

    cut = _stage(model, forward, replace(forward, direction=(-1.0, 0.0, 0.0))).apply(_data())

    assert not cut.holes
    refusals = [d for d in cut.diagnostics if d.code == "wall-feature-unreachable"]
    assert len(refusals) == 1
    assert "more than one wall" in refusals[0].message
