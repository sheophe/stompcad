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

from stompdrill.cad import Rejection
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
    """Neither endpoint reaches the wide step; only its interior boundary does."""
    across = required_radius_nm(_jack(), (Nanometre(1_000_000), Nanometre(24_000_000)))
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


def _drill_pipeline() -> object:
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
    bound is this stage's. The two magnitudes are the two things that go wrong:
    at 1e-9 the crossing is thirty kilometres from the datum, which no region
    holds; below about 1e-22 the travelled distance is one ``nm_from_mm``
    refuses outright, because it scales through ``Decimal`` and that context
    cannot state 1e22 mm as whole nanometres.
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


def test_a_ray_landing_in_two_regions_is_refused_rather_than_tie_broken() -> None:
    """Decision 13's ambiguity, which Task 11 measures to be unreachable.

    Refused and not tie-broken: nothing argued for a preference, and an
    enclosure whose walls overlap in projection is outside this version.
    """
    model = _FakeWalls(
        walls=(_wall(key="right"), _wall(key="top")),
        admitting=frozenset({"right", "top"}),
    )
    with pytest.raises(StompdrillError, match="more than one wall"):
        _stage(model, _seated()).apply(_data())


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
