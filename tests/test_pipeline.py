"""Tests for pipeline composition, stage order and provenance."""

from __future__ import annotations

import dataclasses
import random

import pytest

from aidrill.model import (
    Diagnostic,
    DrillData,
    RawDrillData,
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.units import Millimetre, Nanometre
from aidrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    CheckReferenceSize,
    Deduplicate,
    DrillStandard,
    IdentifyHammondFootprint,
    ReviewGridTies,
    SnapDiametersToDrillTable,
    SnapPositions,
    SortHoles,
)
from aidrill.protocols import Pipeline, Stage
from aidrill.quantise import quantise
from tests.conftest import at, codes, diameters, holes, make_data, positions

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


#: Every class that satisfies ``Stage``. The three quantisers are not among
#: them: they answer about one measurement at a time and run in an order they do
#: not choose, so none of them is a ``DrillData → DrillData`` transform.
ALL_STAGES = [
    Deduplicate(),
    ReviewGridTies(),
    SortHoles(),
    CheckReferenceSize((113_000_000, 60_000_000)),
]


# --------------------------------------------------------------------------
# protocol conformance and purity (LSP / SRP)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_every_stage_satisfies_the_stage_protocol(stage):
    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str) and type(stage).name


@pytest.mark.parametrize(
    "quantiser",
    [SnapPositions(Nanometre(250_000)), SnapDiametersToDrillTable(), IdentifyHammondFootprint()],
    ids=lambda q: type(q).__name__,
)
def test_a_quantiser_is_not_a_stage(quantiser):
    """Quantisers do not satisfy the stage protocol."""
    assert not isinstance(quantiser, Stage)
    assert not hasattr(quantiser, "apply")


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_are_pure_functions(stage):
    """A stage may not mutate its input, and must be deterministic."""
    data = make_data(
        at(-40_000_000, 18_000_000, 7_000_000, index=4),
        at(-40_000_000, 18_000_000, 7_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=9),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    )
    before_holes, before_diags = data.holes, data.diagnostics

    first = stage.apply(data)
    second = stage.apply(data)

    assert data.holes == before_holes, "stage mutated input holes"
    assert data.diagnostics == before_diags, "stage mutated input diagnostics"
    assert isinstance(first, DrillData)
    assert first.holes == second.holes
    assert codes(first) == codes(second)


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_survive_empty_input(stage):
    """No stage may assume it has holes, or that a predecessor ran (LSP)."""
    prior = Diagnostic.info("prior", "something earlier said this")
    data = DrillData(
        holes=(),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
        diagnostics=(prior,),
        source=SourceInfo(path="test"),
    )

    out = stage.apply(data)

    assert out.holes == ()
    assert out.reference == data.reference, "an early return dropped the reference"
    assert out.source == data.source, "an early return dropped the provenance"
    assert prior in out.diagnostics, "an early return dropped earlier diagnostics"

    # And the wholly default value object must not raise either.
    assert stage.apply(DrillData()).holes == ()


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_preserve_existing_diagnostics(stage):
    prior = Diagnostic.info("prior", "something earlier said this")
    data = make_data(at(0, 0, 7_000_000, index=4)).with_diagnostics(prior)
    assert prior in stage.apply(data).diagnostics


# --------------------------------------------------------------------------
# Deduplicate
# --------------------------------------------------------------------------


class TestDeduplicate:
    def test_collapses_coincident_holes_of_equal_diameter(self):
        data = make_data(
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(-40_000_000, 18_000_000, 7_000_000, index=1),
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 1

    def test_keeps_the_first_hole_in_input_order(self):
        first = at(-40_000_000, 18_000_000, 7_000_000, index=4)
        second = at(-40_000_000, 18_000_000, 7_000_000, index=1)
        out = Deduplicate().apply(make_data(first, second))
        assert out.holes == (first,)

    def test_emits_one_warning_per_collapsed_group(self):
        data = make_data(
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(-40_000_000, 18_000_000, 7_000_000, index=1),
            at(-40_000_000, 18_000_000, 7_000_000, index=9),
            at(0, 0, 7_000_000, index=6),
        )
        out = Deduplicate().apply(data)

        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.diagnostics[0].location_nm == (-40_000_000, 18_000_000)

    def test_two_groups_two_warnings(self):
        data = make_data(
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(-40_000_000, 18_000_000, 7_000_000, index=1),
            at(20_000_000, 18_000_000, 7_000_000, index=9),
            at(20_000_000, 18_000_000, 7_000_000, index=6),
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole", "duplicate-hole"]

    def test_does_not_collapse_different_diameters_at_the_same_place(self):
        data = make_data(
            at(0, 0, 7_000_000, index=4), at(0, 0, 5_000_000, index=1)
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    @pytest.mark.parametrize("dx_nm, dy_nm", [(1_000, 0), (0, 1_000), (40_000, 40_000)])
    def test_a_hole_a_hair_away_is_a_different_hole(self, dx_nm, dy_nm):
        """Coincidence is exact, on each axis separately."""
        data = make_data(
            at(0, 0, 7_000_000, index=4), at(dx_nm, dy_nm, 7_000_000, index=1)
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    def test_even_a_hole_one_nanometre_away_is_a_different_hole(self):
        """No deduplication slack: one nanometre is a distinct model position."""
        data = make_data(at(0, 0, 7_000_000, index=4), at(1, 0, 7_000_000, index=1))
        assert len(Deduplicate().apply(data).holes) == 2

    def test_the_fixtures_own_duplicate_is_byte_identical_before_any_quantising(self):
        """Why exactness is enough: a copy-paste duplicates the coordinates."""
        both = (-39.990641944444405, 17.999956944444445, 6.999816666666661)
        raw = RawDrillData(
            source=SourceInfo(path="tar.ai"),
            reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
            centre=(56.5, 30.0),
            holes=(RawHole(*both, 2), RawHole(*both, 5)),
        )
        data = quantise(
            raw,
            # ``tar.ai``'s 113 × 60 fits both 1590BS and 1590B/1590B2, so the
            # case is declared: an undeclared run stops on
            # ``ambiguous-enclosure`` and never reaches the dedupe this names.
            enclosure=IdentifyHammondFootprint("1590B"),
            diameters=SnapDiametersToDrillTable(),
            positions=SnapPositions(Nanometre(250_000)),
        )

        out = Deduplicate().apply(data)

        assert [hole.index for hole in out.holes] == [2]
        assert codes(out) == ["duplicate-hole"]

    def test_unquantised_diameters_are_not_treated_as_equal(self):
        """Dedupe does not do the drill table's job (SRP)."""
        data = make_data(
            at(0, 0, 6_999_800, index=4), at(0, 0, 7_000_000, index=1)
        )
        assert len(Deduplicate().apply(data).holes) == 2

    def test_diagnostic_carries_a_machine_readable_payload(self):
        """A consumer must be able to identify the survivor without re-deriving it."""
        # Identities deliberately do not match positions: an implementation that
        # reported where the survivor sits rather than who it is would answer 0.
        survivor = at(-40_000_000, 18_000_000, 7_000_000, index=4)
        data = make_data(
            survivor,
            at(-40_000_000, 18_000_000, 7_000_000, index=7),
            at(-40_000_000, 18_000_000, 7_000_000, index=5),
            at(0, 0, 5_000_000, index=9),  # a lonely hole raises nothing
        )

        out = Deduplicate().apply(data)

        assert codes(out) == ["duplicate-hole"]
        diag = out.diagnostics[0]
        assert diag.get("hole_index") == survivor.index
        assert diag.location_nm == (survivor.x_nm, survivor.y_nm)
        assert diag.location_nm == (out.holes[0].x_nm, out.holes[0].y_nm)
        assert diag.get("diameter_nm") == survivor.diameter_nm
        assert diag.get("dropped") == 2
        assert diag.get("kept") == 1

    def test_the_payloads_diameter_is_whole_nanometres_under_a_key_that_says_so(self):
        """A payload key ending ``_nm`` is held to a whole ``int`` by the model,
        which is the only thing telling a consumer what the number means: a
        millimetre float under this key would print as a plausible 7.0 in the CLI
        report, the drawing's NOTES and the JSON alike, all three quoting each
        other."""
        data = make_data(
            at(0, 0, 3_200_000, index=4), at(0, 0, 3_200_000, index=1)
        )

        diag = Deduplicate().apply(data).diagnostics[0]

        assert diag.get("diameter_nm") == 3_200_000
        assert type(diag.get("diameter_nm")) is int

    def test_the_diagnostic_names_the_holes_that_went_not_only_how_many(self):
        """A count cannot be turned back into identities."""
        data = make_data(
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(-40_000_000, 18_000_000, 7_000_000, index=7),
            at(-40_000_000, 18_000_000, 7_000_000, index=5),
            at(0, 0, 5_000_000, index=9),
        )

        diag = Deduplicate().apply(data).diagnostics[0]

        assert diag.get("dropped_indices") == (7, 5)
        assert diag.get("hole_index") == 4

    def test_a_lone_dropped_hole_is_still_named(self):
        data = make_data(at(0, 0, 7_000_000, index=8), at(0, 0, 7_000_000, index=3))
        diag = Deduplicate().apply(data).diagnostics[0]
        assert diag.get("dropped_indices") == (3,)

    def test_property_dedupe_is_idempotent(self):
        rng = random.Random(90210)
        for _ in range(300):
            built = []
            for _ in range(8):
                x_nm = rng.randrange(-50_000_000, 50_000_000, 250_000)
                y_nm = rng.randrange(-25_000_000, 25_000_000, 250_000)
                dia_nm = rng.choice([5_000_000, 7_000_000])
                built.append(at(x_nm, y_nm, dia_nm, index=len(built)))
                if rng.random() < 0.4:  # sprinkle exact duplicates
                    built.append(at(x_nm, y_nm, dia_nm, index=len(built)))
            stage = Deduplicate()
            once = stage.apply(make_data(*built))
            twice = stage.apply(once)
            assert twice.holes == once.holes
            assert codes(twice) == codes(once), "second pass found new duplicates"


def test_duplicate_diagnostic_identifies_the_survivor_by_index_not_position():
    """The referent must survive the population changing under it."""
    data = make_data(
        at(0, 25_000_000, 7_000_000, index=3),
        at(10_000_000, 5_000_000, 7_000_000, index=7),
        at(10_000_000, 5_000_000, 7_000_000, index=1),
    )

    after = Pipeline([Deduplicate(), SortHoles()]).run(data)

    duplicates = [d for d in after.diagnostics if d.code == "duplicate-hole"]
    assert len(duplicates) == 1
    survivor_index = duplicates[0].get("hole_index")
    assert survivor_index == 7
    assert [h.index for h in after.holes] == [3, 7]
    # The rejected design — "the survivor is at index 1 of the surviving tuple" —
    # would name hole 7 as 1, which is a real and different hole in this fixture.
    assert [h.index for h in after.holes].index(survivor_index) == 1


# --------------------------------------------------------------------------
# ReviewGridTies, which is only interesting beside the stages around it
# --------------------------------------------------------------------------


#: The two quantisers the phase needs that have nothing to do with grids, and the
#: case the fixture outline needs declaring: 113 × 60 is within tolerance of two
#: real footprints, so an undeclared run aborts on ``ambiguous-enclosure`` before
#: a hole is snapped. What each of those answers is pinned in its own file.
def _phase(*measurements: RawHole, grid_nm: int = 250_000) -> DrillData:
    return quantise(
        RawDrillData(
            source=SourceInfo(path="panel.ai"),
            reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
            centre=(56.5, 30.0),
            holes=measurements,
        ),
        enclosure=IdentifyHammondFootprint("1590B"),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(grid_nm),
    )


class TestReviewGridTiesSeesWhatTheEmittersSee:
    """The reason the review is a stage placed after dedupe, and not a step of the
    quantisation phase.
    """

    #: 0.000 mm and 0.125 mm both snap onto 0 at a 250 000 nm pitch: one exactly
    #: on the grid point, the other exactly halfway between two of them. Same
    #: diameter, same Y, so they are one hole by the time dedupe sees them —
    #: which is precisely what a fixture of two byte-identical measurements can
    #: never show, because identical copies share their residual as well.
    ON_GRID = RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(7.0), 4)
    TIED = RawHole(Millimetre(0.125), Millimetre(18.0), Millimetre(7.0), 9)

    @pytest.mark.parametrize(
        "drawn, kept, findings",
        [
            ((ON_GRID, TIED), 4, ["off-grid", "duplicate-hole"]),
            ((TIED, ON_GRID), 9, ["off-grid", "duplicate-hole", "grid-ambiguous"]),
        ],
        ids=["on-grid drawn first", "tied drawn first"],
    )
    def test_the_verdict_describes_the_hole_that_survived(self, drawn, kept, findings):
        """One panel, two traversal orders, and the answer follows the survivor."""
        out = Pipeline([Deduplicate(), ReviewGridTies(), SortHoles()]).run(_phase(*drawn))

        assert [hole.index for hole in out.holes] == [kept]
        assert codes(out) == findings

    def test_every_named_tie_is_a_hole_the_artifacts_will_list(self):
        """Every tied identity names a hole that survives into emitted artefacts."""
        for drawn in ((self.ON_GRID, self.TIED), (self.TIED, self.ON_GRID)):
            out = Pipeline([Deduplicate(), ReviewGridTies(), SortHoles()]).run(_phase(*drawn))
            emitted = {hole.index for hole in out.holes}

            for diagnostic in out.diagnostics:
                named = diagnostic.get("tied_indices", ())
                assert set(named) <= emitted, f"{diagnostic.code} named a dropped hole"

    def test_a_hole_the_drill_table_dropped_is_not_reviewed(self):
        """The only tied circle on this panel is one no bit can make."""
        out = Pipeline([Deduplicate(), ReviewGridTies(), SortHoles()]).run(
            _phase(
                RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4),
                RawHole(Millimetre(0.125), Millimetre(18.0), Millimetre(30.0), 9),
                RawHole(Millimetre(0.25), Millimetre(18.0), Millimetre(7.0), 1),
            )
        )

        assert [hole.index for hole in out.holes] == [4, 1]
        assert codes(out) == ["unknown-diameter"]


# --------------------------------------------------------------------------
# CheckReferenceSize
# --------------------------------------------------------------------------


class TestCheckReferenceSize:
    #: The declared panel, in whole nanometres. This stage's caller is a library
    #: consumer whose authority is outside the catalogue, and they convert at
    #: their own boundary rather than leaving this stage to do it a second time.
    DECLARED = (113_000_000, 60_000_000)

    def test_matching_outline_is_silent(self):
        data = make_data(at(0, 0, 7_000_000, index=4), reference=ReferenceOutline(*self.DECLARED))
        assert codes(CheckReferenceSize(self.DECLARED).apply(data)) == []

    def test_mismatch_warns(self):
        data = make_data(
            at(0, 0, 7_000_000, index=4), reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_000_000))
        )
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert codes(out) == ["reference-size-mismatch"]
        assert out.diagnostics[0].severity is Severity.WARNING

    def test_is_a_pure_validator_and_returns_holes_untouched(self):
        given = (
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(20_000_000, -18_750_000, 5_000_000, index=1),
        )
        data = make_data(*given, reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(60_000_000)))
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert out.holes == given
        assert out.reference == data.reference

    def test_the_tolerance_boundary_is_inclusive_to_the_nanometre(self):
        """A caller who declares a 50 000 nm slack on a panel that is 50 000 nm out typed
        the number they meant.
        """
        on_it = make_data(reference=ReferenceOutline(Nanometre(113_050_000), Nanometre(60_000_000)))
        assert codes(CheckReferenceSize(self.DECLARED, Nanometre(50_000)).apply(on_it)) == []

        one_nm_over = make_data(reference=ReferenceOutline(Nanometre(113_050_001), Nanometre(60_000_000)))
        assert codes(CheckReferenceSize(self.DECLARED, Nanometre(50_000)).apply(one_nm_over)) == [
            "reference-size-mismatch"
        ]

    def test_a_width_mismatch_alone_is_enough(self):
        """A width mismatch alone fails even when height matches."""
        data = make_data(reference=ReferenceOutline(Nanometre(112_000_000), Nanometre(60_000_000)))
        assert codes(CheckReferenceSize(self.DECLARED).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_a_height_mismatch_alone_is_enough(self):
        data = make_data(reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(59_000_000)))
        assert codes(CheckReferenceSize(self.DECLARED).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_missing_outline_is_an_info_not_a_raise(self):
        data = make_data(at(0, 0, 7_000_000, index=4))
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert codes(out) == ["no-reference-outline"]
        assert out.diagnostics[0].severity is Severity.INFO
        assert out.holes == data.holes

    def test_the_mismatch_carries_the_difference_it_already_worked_out(self):
        """The payload carries signed per-axis deltas.

        Asymmetric deltas distinguish swapped axes and dropped signs.
        """
        data = make_data(reference=ReferenceOutline(Nanometre(112_500_000), Nanometre(60_250_000)))

        diagnostic = CheckReferenceSize(self.DECLARED).apply(data).diagnostics[0]

        assert (diagnostic.get("width_nm"), diagnostic.get("height_nm")) == (
            112_500_000,
            60_250_000,
        )
        assert (
            diagnostic.get("expected_width_nm"),
            diagnostic.get("expected_height_nm"),
        ) == self.DECLARED
        assert (diagnostic.get("delta_width_nm"), diagnostic.get("delta_height_nm")) == (
            -500_000,
            250_000,
        )
        assert diagnostic.get("tolerance_nm") == 50_000

    def test_the_missing_outline_notice_says_what_it_was_going_to_check(self):
        """A consumer rendering this finding needs the declared size it could
        not check, and it is the one fact the stage still holds."""
        diagnostic = (
            CheckReferenceSize(self.DECLARED).apply(make_data(at(0, 0, 7_000_000, index=4)))
        ).diagnostics[0]

        assert (
            diagnostic.get("expected_width_nm"),
            diagnostic.get("expected_height_nm"),
        ) == self.DECLARED
        assert diagnostic.get("tolerance_nm") == 50_000

    def test_a_declared_size_that_is_not_whole_nanometres_is_refused(self):
        """Declared dimensions and tolerance must be whole nanometres."""
        with pytest.raises(TypeError):
            CheckReferenceSize((113.0, 60_000_000))
        with pytest.raises(TypeError):
            CheckReferenceSize((113_000_000, 60.0))
        with pytest.raises(TypeError):
            CheckReferenceSize(self.DECLARED, 0.05)


# --------------------------------------------------------------------------
# SortHoles
# --------------------------------------------------------------------------


class TestSortHoles:
    def test_default_is_descending_y_then_ascending_x(self):
        data = make_data(
            at(20_000_000, -18_750_000, 5_000_000, index=4),
            at(-20_000_000, 18_000_000, index=1),
            at(-40_000_000, 18_000_000, index=9),
            at(-20_000_000, -18_750_000, 5_000_000, index=6),
        )
        out = SortHoles().apply(data)
        assert positions(out) == [
            (-40_000_000, 18_000_000),
            (-20_000_000, 18_000_000),
            (-20_000_000, -18_750_000),
            (20_000_000, -18_750_000),
        ]

    def test_accepts_a_custom_key(self):
        data = make_data(
            at(0, 0, 7_000_000, index=4),
            at(10_000_000, 0, 3_200_000, index=1),
            at(-10_000_000, 0, 5_000_000, index=9),
        )
        out = SortHoles(key=lambda h: h.diameter_nm).apply(data)
        assert diameters(out) == [3_200_000, 5_000_000, 7_000_000]

    def test_is_deterministic_under_input_permutation(self):
        given = [
            at(-40_000_000, 18_000_000, index=4),
            at(0, 18_000_000, index=1),
            at(-19_000_000, -18_750_000, 5_000_000, index=9),
            at(20_000_000, 18_000_000, index=6),
        ]
        rng = random.Random(7)
        expected = SortHoles().apply(make_data(*given)).holes
        for _ in range(20):
            shuffled = given[:]
            rng.shuffle(shuffled)
            assert SortHoles().apply(make_data(*shuffled)).holes == expected

    def test_emits_no_diagnostics(self):
        data = make_data(at(0, 0, index=4), at(1_000_000, 1_000_000, index=1))
        assert codes(SortHoles().apply(data)) == []

    def test_tools_are_stable_under_hole_reordering(self):
        """``tools()`` does not depend on hole order."""
        given = [
            at(0, 0, 7_000_000, index=4),
            at(1_000_000, 0, 5_000_000, index=1),
            at(2_000_000, 0, 3_200_000, index=9),
        ]
        rng = random.Random(11)
        expected = dict(make_data(*given).tools())
        for _ in range(20):
            shuffled = given[:]
            rng.shuffle(shuffled)
            assert dict(make_data(*shuffled).tools()) == expected
            assert dict(SortHoles().apply(make_data(*shuffled)).tools()) == expected


# --------------------------------------------------------------------------
# Composition: Pipeline is a left fold and stage order is observable
# --------------------------------------------------------------------------


class TestPipelineComposition:
    def test_empty_pipeline_is_the_identity(self):
        data = make_data(at(0, 0, index=4))
        assert Pipeline([]).run(data) is data

    def test_run_is_a_left_fold(self):
        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def __init__(self, tag: str) -> None:
                self.tag = tag

            def apply(self, data: DrillData) -> DrillData:
                calls.append(self.tag)
                return data.with_diagnostics(Diagnostic.info(self.tag, self.tag))

            def describe(self) -> StageRun:
                return StageRun(self.name, (("tag", self.tag),))

        out = Pipeline([Recorder("a"), Recorder("b"), Recorder("c")]).run(make_data())
        assert calls == ["a", "b", "c"]
        assert codes(out) == ["a", "b", "c"]

    def test_stage_order_is_observable(self):
        """Sorting before deduplicating keeps a different hole."""
        data = make_data(
            at(10_000_000, 5_000_000, 7_000_000, index=7),
            at(10_000_000, 5_000_000, 7_000_000, index=1),
        )
        dedupe, sort = Deduplicate(), SortHoles(key=lambda h: h.index)

        dedupe_first = Pipeline([dedupe, sort]).run(data)
        sort_first = Pipeline([sort, dedupe]).run(data)

        assert [h.index for h in dedupe_first.holes] == [7]
        assert [h.index for h in sort_first.holes] == [1]

    def test_the_phase_and_the_pipeline_compose_into_one_tool_for_a_noisy_row(self):
        """The library flow, end to end, on the shape of panel it meets."""
        raw = RawDrillData(
            source=SourceInfo(path="panel.ai"),
            reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
            centre=(56.5, 30.0),
            holes=(
                RawHole(Millimetre(-40.003), Millimetre(18.001), Millimetre(6.9998), 4),
                RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(7.0000), 1),  # a duplicate of the above, once quantised
                RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0001), 9),
                RawHole(Millimetre(-19.0), Millimetre(-18.75), Millimetre(5.0002), 6),
                RawHole(Millimetre(19.0), Millimetre(-18.75), Millimetre(4.9998), 2),
            ),
        )

        out = Pipeline([Deduplicate(), SortHoles()]).run(
            quantise(
                raw,
                # Declared, for the reason above: 113 × 60 is a tie.
                enclosure=IdentifyHammondFootprint("1590B"),
                diameters=SnapDiametersToDrillTable(),
                positions=SnapPositions(Nanometre(250_000)),
            )
        )

        assert len(out.holes) == 4
        assert list(out.tools()) == [5_000_000, 7_000_000]
        assert codes(out) == ["duplicate-hole"]
        assert positions(out) == [
            (-40_000_000, 18_000_000),
            (-20_000_000, 18_000_000),
            (-19_000_000, -18_750_000),
            (19_000_000, -18_750_000),
        ]
        assert [hole.index for hole in out.holes] == [4, 9, 6, 2]


# --------------------------------------------------------------------------
# Provenance: what the data records about the stages that shaped it
# --------------------------------------------------------------------------


class TestStageRunAndProcessing:
    """The record itself, before any stage fills one in."""

    def test_get_reads_a_parameter_and_falls_back_to_the_default(self):
        run = StageRun("snap", (("grid_nm", 500_000), ("key", "default")))
        assert run.get("grid_nm") == 500_000
        assert run.get("key") == "default"
        assert run.get("warn_over_nm") is None
        assert run.get("warn_over_nm", 0) == 0

    def test_is_an_immutable_value(self):
        run = StageRun("snap", (("grid_nm", 500_000),))
        assert run == StageRun("snap", (("grid_nm", 500_000),))
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.name = "sort"  # type: ignore[misc]
        # slots, not just frozen: no per-instance dict to grow a stray attribute.
        assert not hasattr(run, "__dict__")

    def test_a_mutable_payload_is_coerced_on_the_way_in(self):
        """The JSON emitter deserialises into this, and JSON hands back lists."""
        run = StageRun("snap-diameters", [["sizes_nm", [3_200_000, 7_000_000]]])

        assert run == StageRun("snap-diameters", (("sizes_nm", (3_200_000, 7_000_000)),))
        assert run.get("sizes_nm") == (3_200_000, 7_000_000)
        assert hash(run) == hash(
            StageRun("snap-diameters", (("sizes_nm", (3_200_000, 7_000_000)),))
        )

    def test_data_starts_with_no_processing_history(self):
        assert make_data(at(0, 0, index=4)).processing == ()

    def test_with_processing_appends_without_mutating(self):
        data = make_data(at(0, 0, index=4))
        first = data.with_processing(StageRun("snap", ()))
        second = first.with_processing(StageRun("sort", ()))

        assert data.processing == (), "with_processing mutated its receiver"
        assert [r.name for r in first.processing] == ["snap"]
        assert [r.name for r in second.processing] == ["snap", "sort"]

    def test_the_other_transforms_carry_the_history_forward(self):
        """Every transform returns a new value; none of them may drop provenance.

        A stage that rebuilt its holes and lost the record of what came before it
        would leave the drawing with a history that starts halfway through.
        """
        run = StageRun("snap", (("grid_nm", 500_000),))
        data = make_data(at(0, 0, index=4)).with_processing(run)

        assert data.with_holes(data.holes).processing == (run,)
        assert data.with_diagnostics(Diagnostic.info("x", "x")).processing == (run,)

    def test_with_processing_of_nothing_is_the_identity(self):
        data = make_data(at(0, 0, index=4))
        assert data.with_processing() is data

    def test_last_run_answers_the_most_recent_of_a_repeated_stage(self):
        """A stage may legitimately run twice; the title block wants the last one."""
        data = make_data().with_processing(
            StageRun("snap", (("grid_nm", 1_000_000),)),
            StageRun("sort", ()),
            StageRun("snap", (("grid_nm", 250_000),)),
        )
        assert data.last_run("snap").get("grid_nm") == 250_000
        assert data.last_run("deduplicate") is None


class TestDescribe:
    """Every stage reports what it was configured to do, in effective values."""

    @pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
    def test_a_stage_describes_itself_under_its_own_name(self, stage):
        assert stage.describe().name == type(stage).name

    def test_deduplicate_has_nothing_to_report_but_still_reports(self):
        """The stage has no parameters at all, and its record is not empty for it."""
        run = Deduplicate().describe()
        assert run.name == "deduplicate"
        assert run.parameters == ()

    def test_sort_names_its_key_function(self):
        def by_diameter(hole):
            return hole.diameter_nm

        assert SortHoles().describe().get("key") == "default"
        assert SortHoles(key=by_diameter).describe().get("key") == "by_diameter"


class TestPipelineRecordsProvenance:
    def test_pipeline_records_what_each_stage_actually_did(self):
        data = make_data(*holes((10_000_000, 5_000_000), (-20_000_000, 5_000_000, 5_000_000)))
        after = Pipeline([Deduplicate(), SortHoles()]).run(data)

        assert [r.name for r in after.processing] == ["deduplicate", "sort"]
        assert after.last_run("sort").get("key") == "default"

    def test_a_stage_that_changed_nothing_still_records_that_it_ran(self):
        """An empty diagnostics list cannot tell a consumer whether a panel had
        no duplicates or whether nobody looked."""
        after = Pipeline([Deduplicate()]).run(make_data(at(0, 0, index=4)))

        assert [r.name for r in after.processing] == ["deduplicate"]
        assert codes(after) == []

    def test_a_stage_never_sees_its_own_provenance_in_its_input(self):
        """The record says what a stage *did*, so it cannot exist before it acts."""
        class Nosy:
            name = "nosy"

            def apply(self, data: DrillData) -> DrillData:
                return data.with_diagnostics(
                    Diagnostic.info(
                        "seen", "counted the history", data=(("runs", len(data.processing)),)
                    )
                )

            def describe(self) -> StageRun:
                return StageRun(self.name, ())

        out = Pipeline([Nosy(), Nosy(), Nosy()]).run(make_data())

        assert [d.get("runs") for d in out.diagnostics] == [0, 1, 2]
        assert len(out.processing) == 3

    def test_a_stage_that_raises_records_nothing(self):
        class Explodes:
            name = "explodes"

            def apply(self, data: DrillData) -> DrillData:
                raise RuntimeError("boom")

            def describe(self) -> StageRun:
                return StageRun(self.name, ())

        data = make_data(at(0, 0, index=4))
        with pytest.raises(RuntimeError):
            Pipeline([Deduplicate(), Explodes()]).run(data)
        assert data.processing == ()

    def test_a_pipeline_records_its_stages_in_order(self):
        """Read off the stages that were handed in, not from a copy of the list."""
        stages = ALL_STAGES
        after = Pipeline(stages).run(
            make_data(
                *holes((-40_000_000, 18_000_000, 7_000_000), (19_000_000, -18_750_000, 5_000_000)),
                reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
            )
        )
        assert [r.name for r in after.processing] == [type(s).name for s in stages]
        assert len(after.processing) == len(stages), "a stage recorded nothing"


# --------------------------------------------------------------------------
# Reaching the stages
# --------------------------------------------------------------------------


def test_the_flow_is_reachable_from_the_package_root():
    """Nothing enumerates the stages or the quantisers, so the root names them."""
    import aidrill

    for name in (
        SnapPositions,
        SnapDiametersToDrillTable,
        IdentifyHammondFootprint,
        Deduplicate,
        ReviewGridTies,
        SortHoles,
        CheckReferenceSize,
    ):
        assert getattr(aidrill, name.__name__, None) is name
        assert name.__name__ in aidrill.__all__

    assert aidrill.quantise is quantise
    assert "quantise" in aidrill.__all__

    assert aidrill.DRILL_STANDARDS is DRILL_STANDARDS
    assert aidrill.DEFAULT_STANDARD == DEFAULT_STANDARD
    assert aidrill.DrillStandard is DrillStandard
    for name in ("DRILL_STANDARDS", "DEFAULT_STANDARD", "DrillStandard"):
        assert name in aidrill.__all__


def test_the_generative_bands_stay_in_the_subpackage():
    """The rule the root's docstring states, made falsifiable."""
    import aidrill

    assert not hasattr(aidrill, "METRIC_BANDS")
    assert not hasattr(aidrill, "FRACTIONAL_SIXTY_FOURTHS")
