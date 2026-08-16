"""Tests for ``Deduplicate``, ``CheckReferenceSize``, ``SortHoles``, ``Pipeline``
composition and provenance, and the package-root re-exports (SPEC §5).

``SnapPositions``, ``SnapDiametersToDrillTable`` and ``IdentifyHammondFootprint``
moved out to ``test_snap.py``, ``test_diameters.py`` and ``test_enclosure.py``
when they stopped being stages, and what composes them is pinned in
``test_quantise.py``. What is left here is the other half of the subpackage: the
three classes that really are ``DrillData → DrillData``, and everything about
folding them that belongs to no single one of them.

``ALL_STAGES`` is therefore the whole of the ``Stage`` protocol's population.
That is the point of naming it: a quantiser added to it would fail the
conformance test below, and a stage left out of it would go unfolded and
untested rather than quietly passing.

Diagnostics are matched on ``code``, never on ``message`` — ``code`` is the
stable machine API and the wording is not.
"""

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
from aidrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    CheckReferenceSize,
    Deduplicate,
    DrillStandard,
    IdentifyHammondFootprint,
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


#: Every class that satisfies ``Stage``. Three, and no longer six: the three
#: quantisers answer about one measurement at a time and run in an order they do
#: not choose, so none of them is a ``DrillData → DrillData`` transform.
ALL_STAGES = [
    Deduplicate(),
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
    [SnapPositions(250_000), SnapDiametersToDrillTable(), IdentifyHammondFootprint()],
    ids=lambda q: type(q).__name__,
)
def test_a_quantiser_is_not_a_stage(quantiser):
    """The distinction the restructure turns on, made falsifiable.

    A quantiser that grew an ``apply`` would satisfy ``Stage`` and could then be
    dropped into ``build_pipeline``, where it would run in an order the caller
    chose — which is precisely what ``aidrill.quantise`` exists to take out of a
    caller's hands, because these three depend on each other's answers.
    """
    assert not isinstance(quantiser, Stage)
    assert not hasattr(quantiser, "apply")


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_are_pure_functions(stage):
    """A stage may not mutate its input, and must be deterministic."""
    data = make_data(
        at(-40_000_000, 18_000_000, 7_000_000, index=4),
        at(-40_000_000, 18_000_000, 7_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=9),
        reference=ReferenceOutline(113_000_000, 60_000_000),
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
    """No stage may assume it has holes, or that a predecessor ran (LSP).

    Surviving means more than "returned something with no holes": a stage that
    bailed out with a bare ``DrillData()`` would drop the reference outline, the
    source provenance and every diagnostic raised before it, and the run would
    carry on as though the panel had never had an outline at all.
    """
    prior = Diagnostic.info("prior", "something earlier said this")
    data = DrillData(
        holes=(),
        reference=ReferenceOutline(113_000_000, 60_000_000),
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
        """Coincidence is exact, on each axis separately.

        Deciding that two nearby coordinates are one place is ``SnapPositions``'
        job, and a near miss the grid did not close is a hole the artwork puts
        somewhere else. Dropping it drills one hole where the panel asks for two.

        Both axes are exercised on their own, because a rule written ``x == y``
        on one of them would still pass a fixture that moved the other.
        """
        data = make_data(
            at(0, 0, 7_000_000, index=4), at(dx_nm, dy_nm, 7_000_000, index=1)
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    def test_even_a_hole_one_nanometre_away_is_a_different_hole(self):
        """No slack at all, not merely less than there was. A nanometre is the
        smallest difference the model can hold, so this is the whole of it."""
        data = make_data(at(0, 0, 7_000_000, index=4), at(1, 0, 7_000_000, index=1))
        assert len(Deduplicate().apply(data).holes) == 2

    def test_the_fixtures_own_duplicate_is_byte_identical_before_any_quantising(self):
        """Why exactness is enough: a copy-paste duplicates the coordinates.

        These are the two ⌀7 holes the shipped ``tar.ai`` carries, as
        ``AiPdfSource`` measures them — equal to the last bit, with nothing
        having quantised them. That is what a duplicate is in this domain, and it
        is what a tolerance would really have been catching. Quantised through
        the phase they stay equal, because quantising is deterministic.
        """
        both = (-39.990641944444405, 17.999956944444445, 6.999816666666661)
        raw = RawDrillData(
            source=SourceInfo(path="tar.ai"),
            reference=RawOutline(113.0, 60.0),
            centre=(56.5, 30.0),
            holes=(RawHole(*both, 2), RawHole(*both, 5)),
        )
        data = quantise(
            raw,
            enclosure=IdentifyHammondFootprint(),
            diameters=SnapDiametersToDrillTable(),
            positions=SnapPositions(250_000),
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
        """A consumer must be able to identify the survivor without re-deriving it.

        The drawing emitter has to mark the duplicate it was told about. Given
        only a rounded message it re-implemented this stage's rule — with its own
        tolerance and no diameter check — and flagged holes the pipeline had not.
        ``hole_index`` is therefore the key a consumer matches on: it names the
        survivor and stays true however far a later stage moves it.
        ``location_nm`` is the survivor's coordinate at the time of the report —
        human context for the CLI and the drawing's NOTES, and no longer a
        referent.
        """
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
        """A count cannot be turned back into identities.

        The dropped pair is 7 and 5 — out of order, not adjacent to the
        survivor's 4, and not the two array positions they occupy. Anything
        derived from position or from arithmetic on the survivor's id answers
        something else here, which is the point: ``Hole.index`` exists so an
        artwork circle can be reconciled against an emitted hole, and a hole
        that reaches no artifact is exactly the one that needs naming.
        """
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
    """The referent must survive the population changing under it.

    Dropping a hole renumbers every array position after it while no identity
    moves, and ``SortHoles`` then reorders what is left. The survivor here is
    hole 7, it is the *second* hole in the input and the *last* in the sorted
    output, so a referent derived from either list answers something else.
    """
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
            at(0, 0, 7_000_000, index=4), reference=ReferenceOutline(112_400_000, 60_000_000)
        )
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert codes(out) == ["reference-size-mismatch"]
        assert out.diagnostics[0].severity is Severity.WARNING

    def test_is_a_pure_validator_and_returns_holes_untouched(self):
        given = (
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(20_000_000, -18_750_000, 5_000_000, index=1),
        )
        data = make_data(*given, reference=ReferenceOutline(100_000_000, 60_000_000))
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert out.holes == given
        assert out.reference == data.reference

    def test_the_tolerance_boundary_is_inclusive_to_the_nanometre(self):
        """A caller who declares a 50 000 nm slack on a panel that is 50 000 nm
        out typed the number they meant.

        Exactly on the boundary and exactly one nanometre outside it: a fixture
        sitting comfortably either side would stay green under ``<``.
        """
        on_it = make_data(reference=ReferenceOutline(113_050_000, 60_000_000))
        assert codes(CheckReferenceSize(self.DECLARED, 50_000).apply(on_it)) == []

        one_nm_over = make_data(reference=ReferenceOutline(113_050_001, 60_000_000))
        assert codes(CheckReferenceSize(self.DECLARED, 50_000).apply(one_nm_over)) == [
            "reference-size-mismatch"
        ]

    def test_a_width_mismatch_alone_is_enough(self):
        """Paired with the height case below rather than folded into one
        fixture: a guard covering two axes loses half its coverage invisibly
        when one of the two tests goes, and the survivor's name still describes
        the whole behaviour."""
        data = make_data(reference=ReferenceOutline(112_000_000, 60_000_000))
        assert codes(CheckReferenceSize(self.DECLARED).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_a_height_mismatch_alone_is_enough(self):
        data = make_data(reference=ReferenceOutline(113_000_000, 59_000_000))
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
        """``Diagnostic.data`` exists so a consumer never re-derives a stage's
        own arithmetic. This one rendered the deltas into prose and dropped
        them, leaving every reader to subtract the two sizes again.

        The fixture is deliberately asymmetric — one axis under by 0.5 mm, the
        other over by 0.25 mm — so neither a swapped pair of axes nor a dropped
        sign can pass.
        """
        data = make_data(reference=ReferenceOutline(112_500_000, 60_250_000))

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
        """Checked at construction, where the offending value still has a call
        site attached to it. A caller who hands over the millimetres they were
        thinking in gets a comparison a million times too tight on every panel,
        and the only sign of it is that every panel now mismatches.

        Each of the three values separately: a guard that reads only the first
        element of the pair would pass two of these.
        """
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
        """SPEC §9 property: tools() does not depend on hole order."""
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
        """Sorting before deduplicating keeps a different hole.

        ``Deduplicate`` keeps the first member of a group *in input order*, so
        whatever decides the input order decides which hole survives — and
        survives into the artifacts under its own ``index``. The two holes are
        coincident and numbered 7 and 1, so the answer is unambiguous either way
        round: this is not a preference, it is two different panels' worth of
        provenance. Which order the CLI picks is ``cli.build_pipeline``'s to say
        and nobody else's.
        """
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
        """The library flow, end to end, on the shape of panel it meets.

        Deliberately *not* a second statement of the CLI's stage order — that
        lives in ``cli.build_pipeline`` and is pinned once, in
        ``tests/test_cli.py``, by reading the pipeline the CLI actually builds.
        A parallel list here has already drifted once.

        What it does state is the one arrangement that is not a preference:
        dedupe cannot run before the phase, because collapsing 6.9998 against
        7.0000 is the drill table's answer and collapsing −40.003 against −40.0
        is the grid's.
        """
        raw = RawDrillData(
            source=SourceInfo(path="panel.ai"),
            reference=RawOutline(113.0, 60.0),
            centre=(56.5, 30.0),
            holes=(
                RawHole(-40.003, 18.001, 6.9998, 4),
                RawHole(-40.0, 18.0, 7.0000, 1),  # a duplicate of the above, once quantised
                RawHole(-20.0, 18.0, 7.0001, 9),
                RawHole(-19.0, -18.75, 5.0002, 6),
                RawHole(19.0, -18.75, 4.9998, 2),
            ),
        )

        out = Pipeline([Deduplicate(), SortHoles()]).run(
            quantise(
                raw,
                enclosure=IdentifyHammondFootprint(),
                diameters=SnapDiametersToDrillTable(),
                positions=SnapPositions(250_000),
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
        """The JSON emitter deserialises into this, and JSON hands back lists.

        A ``StageRun`` holding a list is unhashable and compares unequal to the
        identical record built from tuples, so a round-tripped document would
        differ from the one it was written from — while looking right in print.
        """
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
    """Every stage reports what it was configured to do, in effective values.

    Only the three stages are here. What each *quantiser* records is pinned
    beside the quantiser, in ``test_snap.py``, ``test_diameters.py`` and
    ``test_enclosure.py``, where the thing being recorded is also defined.
    """

    @pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
    def test_a_stage_describes_itself_under_its_own_name(self, stage):
        assert stage.describe().name == type(stage).name

    def test_deduplicate_has_nothing_to_report_but_still_reports(self):
        """The stage has no parameters at all, and its record is not empty for it.

        A reader of ``processing`` learns that deduplication ran; there is no
        bound to publish because coincidence is exact. Publishing one anyway
        would tell a consumer a number that decides nothing.
        """
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
        """The record says what a stage *did*, so it cannot exist before it acts.

        Recording before applying would also hand every stage a record of itself
        it had not yet earned — and if ``apply`` then raised, the history would
        claim work that never happened.
        """
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
        """Read off the stages that were handed in, not from a copy of the list.

        The literal spelling drifted once already — it named the CLI's order,
        which this list has not been since the enclosure joined it — and a
        parallel list is what let that happen quietly. What is being asserted is
        that ``Pipeline`` records *in order*, which the input already states.
        """
        stages = ALL_STAGES
        after = Pipeline(stages).run(
            make_data(
                *holes((-40_000_000, 18_000_000, 7_000_000), (19_000_000, -18_750_000, 5_000_000)),
                reference=ReferenceOutline(113_000_000, 60_000_000),
            )
        )
        assert [r.name for r in after.processing] == [type(s).name for s in stages]
        assert len(after.processing) == len(stages), "a stage recorded nothing"


# --------------------------------------------------------------------------
# Reaching the stages
# --------------------------------------------------------------------------


def test_the_flow_is_reachable_from_the_package_root():
    """Nothing enumerates the stages or the quantisers, so the root names them.

    ``build_pipeline`` is the CLI's arrangement and not the only one — SPEC
    calls ``CheckReferenceSize`` a supported stage for a library caller, and the
    CLI never runs it. A root exporting ``Pipeline`` and the ``Stage`` protocol
    but no stage hands a consumer an empty pipeline and no way to fill it, and
    exporting the quantisers without ``DRILL_STANDARDS`` leaves the one that
    takes a table unconfigurable.

    ``quantise`` is the piece with no protocol standing in for it: without it a
    consumer holds a ``RawDrillData`` from ``AiPdfSource`` and has no supported
    way to turn it into the ``DrillData`` every stage and every emitter takes.
    """
    import aidrill

    for name in (
        SnapPositions,
        SnapDiametersToDrillTable,
        IdentifyHammondFootprint,
        Deduplicate,
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
    """The rule the root's docstring states, made falsifiable.

    ``METRIC_BANDS`` is what a *different* preferred series would be written as,
    not what running the flow needs, and the split is only worth having while
    something fails when it blurs.
    """
    import aidrill

    assert not hasattr(aidrill, "METRIC_BANDS")
    assert not hasattr(aidrill, "FRACTIONAL_SIXTY_FOURTHS")
