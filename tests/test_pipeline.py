"""Tests for ``Deduplicate``, ``CheckReferenceSize``, ``SortHoles``, ``Pipeline``
composition and provenance, and the package-root re-exports (SPEC §5, PLAN
task B).

``SnapPositions``, ``SnapDiametersToDrillTable`` and ``IdentifyHammondFootprint``
moved out to ``test_snap.py``, ``test_diameters.py`` and ``test_enclosure.py``
respectively, splitting a 2160-line file so three agents can work on it in
parallel without owning the same lines. This file kept the stage-protocol
conformance tests -- which name all six stages by ``ALL_STAGES`` and so belong
to none of them alone -- plus everything else that did not belong to a single
stage. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import dataclasses
import math
import random

import pytest

from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
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
from tests.conftest import at, codes, diameters, holes, make_data, positions

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


ALL_STAGES = [
    SnapPositions(grid=0.25),
    SnapDiametersToDrillTable(),
    Deduplicate(),
    CheckReferenceSize((113.0, 60.0)),
    SortHoles(),
    IdentifyHammondFootprint(),
]


# --------------------------------------------------------------------------
# protocol conformance and purity (LSP / SRP)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_every_stage_satisfies_the_stage_protocol(stage):
    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str) and type(stage).name


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_are_pure_functions(stage):
    """A stage may not mutate its input, and must be deterministic."""
    data = make_data(
        at(-40.003, 18.002, 6.9998, index=0),
        at(-40.0, 18.0, 7.0000, index=1),
        at(19.0, -18.75, 5.0, index=2),
        reference=ReferenceOutline(113.0, 60.0),
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
    source provenance and every diagnostic raised before it, and the pipeline
    would carry on as though the panel had never had an outline at all.
    """
    prior = Diagnostic.info("prior", "something earlier said this")
    # 112 × 61 rather than the fixture's measured 113 × 60: it is a catalogue
    # footprint exactly, so IdentifyHammondFootprint's snap is the identity and
    # ``out.reference == data.reference`` still means "the outline was not
    # dropped" for every stage. Asserting only that it is not None would have
    # weakened the check for the five stages that must not touch it at all.
    data = DrillData(
        holes=(),
        reference=ReferenceOutline(112.0, 61.0),
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
    data = make_data(at(0.0, 0.0, 7.0, index=0)).with_diagnostics(prior)
    assert prior in stage.apply(data).diagnostics


# --------------------------------------------------------------------------
# Deduplicate
# --------------------------------------------------------------------------


class TestDeduplicate:
    def test_collapses_coincident_holes_of_equal_diameter(self):
        data = make_data(at(-40.0, 18.0, 7.0, index=0), at(-40.0, 18.0, 7.0, index=1))
        out = Deduplicate().apply(data)
        assert len(out.holes) == 1

    def test_keeps_the_first_hole_in_input_order(self):
        first, second = at(-40.0, 18.0, 7.0, index=0), at(-40.0, 18.0, 7.0, index=1)
        out = Deduplicate().apply(make_data(first, second))
        assert out.holes == (first,)

    def test_emits_one_warning_per_collapsed_group(self):
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            at(-40.0, 18.0, 7.0, index=1),
            at(-40.0, 18.0, 7.0, index=2),
            at(0.0, 0.0, 7.0, index=3),
        )
        out = Deduplicate().apply(data)

        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.diagnostics[0].location == (-40.0, 18.0)

    def test_two_groups_two_warnings(self):
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            at(-40.0, 18.0, 7.0, index=1),
            at(20.0, 18.0, 7.0, index=2),
            at(20.0, 18.0, 7.0, index=3),
        )
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole", "duplicate-hole"]

    def test_does_not_collapse_different_diameters_at_the_same_place(self):
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.0, 0.0, 5.0, index=1))
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    @pytest.mark.parametrize("dx, dy", [(0.01, 0.0), (0.0, 0.01), (0.04, 0.04)])
    def test_a_hole_a_hair_away_is_a_different_hole(self, dx, dy):
        """Coincidence is exact, on each axis separately.

        The two offsets used to fall inside a 0.05 mm tolerance and collapse.
        They no longer do, and that is the behaviour, not a regression: deciding
        that two nearby coordinates are one place is ``SnapPositions``' job, and
        a near miss the grid did not close is a hole the artwork puts somewhere
        else. Dropping it drills one hole where the panel asks for two.

        Both axes are exercised on their own, because a rule written ``x == y``
        on one of them would still pass a fixture that moved the other.
        """
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(dx, dy, 7.0, index=1))
        out = Deduplicate().apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    def test_even_a_hole_one_ulp_away_is_a_different_hole(self):
        """No slack at all, not merely less than there was."""
        data = make_data(
            at(0.0, 0.0, 7.0, index=0), at(math.ulp(0.0), 0.0, 7.0, index=1)
        )
        assert len(Deduplicate().apply(data).holes) == 2

    def test_the_fixtures_own_duplicate_is_byte_identical_before_any_snapping(self):
        """Why exactness is enough: a copy-paste duplicates the coordinates.

        These are the two ⌀7 holes the shipped ``tar.ai`` carries, as
        ``AiPdfSource`` parses them — equal to the last bit, with nothing having
        snapped them. That is what a duplicate is in this domain, and it is what
        the tolerance was really catching.
        """
        both = (-39.990641944444405, 17.999956944444445, 6.999816666666661)
        data = make_data(at(*both, index=2), at(*both, index=5))

        out = Deduplicate().apply(data)

        assert [hole.index for hole in out.holes] == [2]
        assert codes(out) == ["duplicate-hole"]

    def test_unnormalised_diameters_are_not_treated_as_equal(self):
        """Dedupe does not do the diameter stage's job (SRP)."""
        data = make_data(at(0.0, 0.0, 6.9998, index=0), at(0.0, 0.0, 7.0000, index=1))
        assert len(Deduplicate().apply(data).holes) == 2

    def test_diagnostic_carries_a_machine_readable_payload(self):
        """A consumer must be able to identify the survivor without re-deriving it.

        The drawing emitter has to mark the duplicate it was told about. Given
        only a rounded message it re-implemented this stage's rule — with its own
        tolerance and no diameter check — and flagged holes the pipeline had not.
        ``hole_index`` is therefore the key a consumer matches on: it names the
        survivor and stays true however far a later stage moves it. ``location``
        is the survivor's coordinate at the time of the report — human context
        for the CLI and the drawing's NOTES, and no longer a referent.
        """
        # Identities deliberately do not match positions: an implementation that
        # reported where the survivor sits rather than who it is would answer 0.
        survivor = at(-40.0031, 18.0007, 7.0, index=4)
        data = make_data(
            survivor,
            at(-40.0031, 18.0007, 7.0, index=7),
            at(-40.0031, 18.0007, 7.0, index=5),
            at(0.0, 0.0, 5.0, index=9),  # a lonely hole raises nothing
        )

        out = Deduplicate().apply(data)

        assert codes(out) == ["duplicate-hole"]
        diag = out.diagnostics[0]
        assert diag.get("hole_index") == survivor.index
        assert diag.location == (survivor.x, survivor.y)
        assert diag.location == (out.holes[0].x, out.holes[0].y)
        assert diag.get("diameter") == survivor.diameter
        assert diag.get("dropped") == 2
        assert diag.get("kept") == 1

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
            at(-40.0031, 18.0007, 7.0, index=4),
            at(-40.0031, 18.0007, 7.0, index=7),
            at(-40.0031, 18.0007, 7.0, index=5),
            at(0.0, 0.0, 5.0, index=9),
        )

        diag = Deduplicate().apply(data).diagnostics[0]

        assert diag.get("dropped_indices") == "7,5"
        assert diag.get("hole_index") == 4

    def test_a_lone_dropped_hole_is_still_named(self):
        data = make_data(at(0.0, 0.0, 7.0, index=8), at(0.0, 0.0, 7.0, index=3))
        diag = Deduplicate().apply(data).diagnostics[0]
        assert diag.get("dropped_indices") == "3"

    def test_property_dedupe_is_idempotent(self):
        rng = random.Random(90210)
        for _ in range(300):
            holes = []
            for _ in range(8):
                x, y = rng.uniform(-50, 50), rng.uniform(-25, 25)
                dia = rng.choice([5.0, 7.0])
                holes.append(at(x, y, dia, index=len(holes)))
                if rng.random() < 0.4:  # sprinkle exact duplicates
                    holes.append(at(x, y, dia, index=len(holes)))
            stage = Deduplicate()
            once = stage.apply(make_data(*holes))
            twice = stage.apply(once)
            assert twice.holes == once.holes
            assert codes(twice) == codes(once), "second pass found new duplicates"


def test_duplicate_diagnostic_identifies_the_survivor_by_index_not_position():
    """The referent must survive a later coordinate change.

    protocols.py forbids a stage assuming its predecessor, so Deduplicate may
    legitimately run before SnapPositions. When it does, the survivor moves
    after the diagnostic is written and a position-keyed referent goes stale.

    The two identities are out of order and neither equals a position, so the
    rejected design — reporting the survivor's index in the surviving tuple —
    would answer 0 here rather than 7, and SortHoles would invalidate it later.
    """
    data = make_data(
        Hole.from_measurement(10.03, 5.02, 7.0, index=7),
        Hole.from_measurement(10.03, 5.02, 7.0, index=3),
    )
    after = Pipeline([Deduplicate(), SnapPositions(grid=0.25)]).run(data)

    duplicates = [d for d in after.diagnostics if d.code == "duplicate-hole"]
    assert len(duplicates) == 1
    survivor_index = duplicates[0].get("hole_index")
    assert survivor_index == 7
    assert [h.index for h in after.holes] == [survivor_index]

    # The move the docstring turns on, made observable: by the end of the run
    # the reported coordinate names nowhere a hole is, and only the id resolves.
    survivor = after.holes[0]
    assert (survivor.x, survivor.y) == (10.0, 5.0)
    assert duplicates[0].location == (10.03, 5.02)
    assert duplicates[0].location != (survivor.x, survivor.y)


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
        holes = (
            at(-40_000_000, 18_000_000, 7_000_000, index=4),
            at(20_000_000, -18_750_000, 5_000_000, index=1),
        )
        data = make_data(*holes, reference=ReferenceOutline(100_000_000, 60_000_000))
        out = CheckReferenceSize(self.DECLARED).apply(data)
        assert out.holes == holes
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

    def test_describe_reports_the_declared_panel_and_the_slack(self):
        """Provenance in the same unit the comparison was made in. A consumer
        reading a slack of 0.05 off a stage that compared 50 000 would be
        reading a number the data was never checked against."""
        run = CheckReferenceSize(self.DECLARED, 50_000).describe()

        assert run.name == "check-reference-size"
        assert (run.get("expected_width_nm"), run.get("expected_height_nm")) == self.DECLARED
        assert run.get("tolerance_nm") == 50_000

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
            at(20.0, -18.75, 5.0, index=0),
            at(-20.0, 18.0, index=1),
            at(-40.0, 18.0, index=2),
            at(-20.0, -18.75, 5.0, index=3),
        )
        out = SortHoles().apply(data)
        assert positions(out) == [
            (-40.0, 18.0),
            (-20.0, 18.0),
            (-20.0, -18.75),
            (20.0, -18.75),
        ]

    def test_accepts_a_custom_key(self):
        data = make_data(
            at(0.0, 0.0, 7.0, index=0),
            at(10.0, 0.0, 3.2, index=1),
            at(-10.0, 0.0, 5.0, index=2),
        )
        out = SortHoles(key=lambda h: h.diameter).apply(data)
        assert diameters(out) == [3.2, 5.0, 7.0]

    def test_is_deterministic_under_input_permutation(self):
        holes = [
            at(-40.0, 18.0, index=0),
            at(0.0, 18.0, index=1),
            at(-19.0, -18.75, 5.0, index=2),
            at(20.0, 18.0, index=3),
        ]
        rng = random.Random(7)
        expected = SortHoles().apply(make_data(*holes)).holes
        for _ in range(20):
            shuffled = holes[:]
            rng.shuffle(shuffled)
            assert SortHoles().apply(make_data(*shuffled)).holes == expected

    def test_emits_no_diagnostics(self):
        data = make_data(at(0.0, 0.0, index=0), at(1.0, 1.0, index=1))
        assert codes(SortHoles().apply(data)) == []

    def test_tools_are_stable_under_hole_reordering(self):
        """SPEC §9 property: tools() does not depend on hole order."""
        holes = [
            at(0.0, 0.0, 7.0, index=0),
            at(1.0, 0.0, 5.0, index=1),
            at(2.0, 0.0, 3.2, index=2),
        ]
        rng = random.Random(11)
        expected = dict(make_data(*holes).tools())
        for _ in range(20):
            shuffled = holes[:]
            rng.shuffle(shuffled)
            assert dict(make_data(*shuffled).tools()) == expected
            assert dict(SortHoles().apply(make_data(*shuffled)).tools()) == expected


# --------------------------------------------------------------------------
# Composition: Pipeline is a left fold and stage order is observable
# --------------------------------------------------------------------------


class TestPipelineComposition:
    def test_empty_pipeline_is_the_identity(self):
        data = make_data(at(0.0, 0.0, index=0))
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
        """snap-then-dedupe collapses a near-duplicate that dedupe-then-snap does not.

        The two holes are 0.06 mm apart, so ``Deduplicate`` — which compares
        exactly — sees two holes; both snap onto the same 0.25 mm grid point, so
        after ``SnapPositions`` it sees one. The whole difference is the order,
        which is why only ``cli.build_pipeline`` gets to choose it.
        """
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.06, 0.0, 7.0, index=1))
        snap, dedupe = SnapPositions(0.25), Deduplicate()

        snap_first = Pipeline([snap, dedupe]).run(data)
        dedupe_first = Pipeline([dedupe, snap]).run(data)

        assert len(snap_first.holes) == 1
        assert "duplicate-hole" in codes(snap_first)

        assert len(dedupe_first.holes) == 2
        assert "duplicate-hole" not in codes(dedupe_first)

    def test_a_realistic_composition_yields_one_tool_for_a_noisy_seven_mm_row(self):
        """Several stages folded together, on the shape of panel they meet.

        Deliberately *not* a second statement of the CLI's stage order — that
        lives in ``cli.build_pipeline`` and is pinned once, in
        ``tests/test_cli.py``, by reading the pipeline the CLI actually builds.
        A parallel list here has already drifted once.
        """
        data = make_data(
            at(-40.003, 18.001, 6.9998, index=0),
            at(-40.0, 18.0, 7.0000, index=1),  # duplicate of the above, once snapped
            at(-20.0, 18.0, 7.0001, index=2),
            at(-19.0, -18.75, 5.0002, index=3),
            at(19.0, -18.75, 4.9998, index=4),
            reference=ReferenceOutline(113.0, 60.0),
        )

        out = Pipeline(
            [
                SnapPositions(0.25),
                SnapDiametersToDrillTable(),
                Deduplicate(),
                IdentifyHammondFootprint(),
                SortHoles(),
            ]
        ).run(data)

        assert len(out.holes) == 4
        assert len(out.tools()) == 2
        assert list(out.tools()) == [5.0, 7.0]
        assert codes(out) == ["duplicate-hole"]
        assert positions(out) == [
            (-40.0, 18.0),
            (-20.0, 18.0),
            (-19.0, -18.75),
            (19.0, -18.75),
        ]


# --------------------------------------------------------------------------
# Provenance: what the data records about the stages that shaped it
# --------------------------------------------------------------------------


class TestStageRunAndProcessing:
    """The record itself, before any stage fills one in."""

    def test_get_reads_a_parameter_and_falls_back_to_the_default(self):
        run = StageRun("snap", (("grid_mm", 0.5), ("enabled", True)))
        assert run.get("grid_mm") == 0.5
        assert run.get("enabled") is True
        assert run.get("warn_over_mm") is None
        assert run.get("warn_over_mm", 0.0) == 0.0

    def test_is_an_immutable_value(self):
        run = StageRun("snap", (("grid_mm", 0.5),))
        assert run == StageRun("snap", (("grid_mm", 0.5),))
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.name = "sort"  # type: ignore[misc]
        # slots, not just frozen: no per-instance dict to grow a stray attribute.
        assert not hasattr(run, "__dict__")

    def test_a_mutable_payload_is_coerced_on_the_way_in(self):
        """Task 3 deserialises into this: JSON hands back lists, not tuples.

        A ``StageRun`` holding a list is unhashable and compares unequal to the
        identical record built from tuples, so a round-tripped document would
        differ from the one it was written from — while looking right in print.
        """
        run = StageRun("normalize-diameters", [["sizes_mm", [3.2, 7.0]]])

        assert run == StageRun("normalize-diameters", (("sizes_mm", (3.2, 7.0)),))
        assert run.get("sizes_mm") == (3.2, 7.0)
        assert hash(run) == hash(StageRun("normalize-diameters", (("sizes_mm", (3.2, 7.0)),)))

    def test_data_starts_with_no_processing_history(self):
        assert make_data(at(0.0, 0.0, index=0)).processing == ()

    def test_with_processing_appends_without_mutating(self):
        data = make_data(at(0.0, 0.0, index=0))
        first = data.with_processing(StageRun("snap", ()))
        second = first.with_processing(StageRun("sort", ()))

        assert data.processing == (), "with_processing mutated its receiver"
        assert [r.name for r in first.processing] == ["snap"]
        assert [r.name for r in second.processing] == ["snap", "sort"]

    def test_the_other_transforms_carry_the_history_forward(self):
        """Every transform returns a new value; none of them may drop provenance.

        A stage that rebuilt its holes and lost the record of the stages before
        it would leave the drawing with a history that starts halfway through.
        """
        run = StageRun("snap", (("grid_mm", 0.5),))
        data = make_data(at(0.0, 0.0, index=0)).with_processing(run)

        assert data.with_holes(data.holes).processing == (run,)
        assert data.with_diagnostics(Diagnostic.info("x", "x")).processing == (run,)

    def test_with_processing_of_nothing_is_the_identity(self):
        data = make_data(at(0.0, 0.0, index=0))
        assert data.with_processing() is data

    def test_last_run_answers_the_most_recent_of_a_repeated_stage(self):
        """A stage may legitimately run twice; the title block wants the last one."""
        data = make_data().with_processing(
            StageRun("snap", (("grid_mm", 1.0),)),
            StageRun("sort", ()),
            StageRun("snap", (("grid_mm", 0.25),)),
        )
        assert data.last_run("snap").get("grid_mm") == 0.25
        assert data.last_run("deduplicate") is None


class TestDescribe:
    """Every stage reports what it was configured to do, in effective values."""

    @pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
    def test_a_stage_describes_itself_under_its_own_name(self, stage):
        assert stage.describe().name == type(stage).name

    def test_snap_reports_grid_and_the_resolved_warning_threshold(self):
        run = SnapPositions(grid=0.5).describe()
        assert run.get("grid_mm") == 0.5
        assert run.get("warn_over_mm") == 0.125
        assert run.get("enabled") is True

    def test_describe_reports_resolved_defaults_not_raw_arguments(self):
        """warn_over defaults to grid/4; provenance must record the effective value."""
        assert SnapPositions(grid=0.25).describe().get("warn_over_mm") == 0.0625

    def test_snap_reports_an_explicit_warning_threshold_as_given(self):
        assert SnapPositions(0.25, warn_over=0.2).describe().get("warn_over_mm") == 0.2

    def test_a_non_positive_grid_describes_itself_as_disabled(self):
        run = SnapPositions(grid=0.0).describe()
        assert run.get("enabled") is False
        assert run.get("grid_mm") == 0.0

    def test_deduplicate_has_nothing_to_report_but_still_reports(self):
        """The stage has no parameters at all, and its record is not empty for it.

        A reader of ``processing`` learns that deduplication ran; there is no
        bound to publish because coincidence is exact. Publishing one anyway —
        the ``tolerance_mm`` that used to be here — would tell a consumer a
        number that decides nothing.
        """
        run = Deduplicate().describe()
        assert run.name == "deduplicate"
        assert run.parameters == ()

    def test_check_reference_size_reports_the_declared_panel_and_slack(self):
        run = CheckReferenceSize((113.0, 60.0)).describe()
        assert run.get("expected_width_mm") == 113.0
        assert run.get("expected_height_mm") == 60.0
        assert run.get("tolerance_mm") == 0.05

    def test_sort_names_its_key_function(self):
        def by_diameter(hole):
            return hole.diameter

        assert SortHoles().describe().get("key") == "default"
        assert SortHoles(key=by_diameter).describe().get("key") == "by_diameter"

    def test_snap_diameters_reports_the_standard_it_quantised_against(self):
        run = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"], 0.1).describe()
        assert run.get("standard") == "fractional"
        assert run.get("tolerance_mm") == 0.1
        assert run.get("size_count") == 64

    def test_snap_diameters_records_the_sizes_that_were_actually_available(self):
        """The narrowed drawer, written out in full, because nothing else says it.

        A consumer's one likely question — "what is the nearest size this panel
        could have used?" — is answered wrongly by the standard's name once the
        operator has told us which bits they own. The set is run-specific, so it
        travels with the run; it is also small, which is why it can.
        """
        drawer = DRILL_STANDARDS["metric"].select(include=(3.2, 5.0, 7.0, 12.0))
        run = SnapDiametersToDrillTable(drawer).describe()

        assert run.get("standard") == "metric"
        assert run.get("sizes_mm") == (3.2, 5.0, 7.0, 12.0)
        assert run.get("size_count") == 4

    def test_an_unnarrowed_standard_is_recorded_by_name_and_count_alone(self):
        """183 sizes a reader can look up are not worth 90 % of the document.

        The name is an address into a registry of physical constants, and a
        consumer that cannot expand it cannot use the numbers either. The key is
        *absent* rather than empty: ``StageRun.get`` cannot tell an absent key
        from a null one, so an empty tuple here would read as "quantised against
        no bits at all".
        """
        run = SnapDiametersToDrillTable().describe()
        parameters = dict(run.parameters)

        assert run.get("standard") == "metric"
        assert run.get("size_count") == 183
        assert run.get("tolerance_mm") == 0.25
        assert "sizes_mm" not in parameters

    def test_a_table_no_registry_name_can_rebuild_records_its_sizes(self):
        """The rule is "can a reader rebuild this from the name?", not "did
        ``select`` run?" — a hand-built standard answers no just as a narrowed
        one does, and a reader looking up its name would find nothing at all."""
        label = DRILL_STANDARDS["metric"].label
        run = SnapDiametersToDrillTable(
            DrillStandard(name="the-drawer-in-the-shed", sizes_mm=(3.2, 7.0), label=label)
        ).describe()

        assert run.get("sizes_mm") == (3.2, 7.0)
        assert run.get("size_count") == 2


class TestPipelineRecordsProvenance:
    def test_pipeline_records_what_each_stage_actually_did(self):
        data = make_data(*holes((10.03, 5.02), (-20.0, 5.0, 5.0)))
        after = Pipeline([SnapPositions(grid=0.5), Deduplicate()]).run(data)

        assert [r.name for r in after.processing] == ["snap", "deduplicate"]
        snap = after.last_run("snap")
        assert snap.get("grid_mm") == 0.5
        assert snap.get("warn_over_mm") == 0.125  # the *resolved* default, not None

    @pytest.mark.parametrize(
        "grid, expected", [(0.25, [(10.25, 5.0)]), (0.5, [(10.5, 5.0)])]
    )
    def test_the_recorded_grid_is_the_grid_the_holes_were_snapped_to(self, grid, expected):
        """Finding 08: the sheet stated a grid the data had never been snapped to.

        The record must *predict* the coordinates, which is only true if it comes
        from the stage that moved them. Divisibility alone does not say that —
        every multiple of 0.5 is also a multiple of 0.25, so a record finer than
        the reality, which is finding 08 exactly, would satisfy it. Hence the
        literal positions per grid, plus the residual bound: a snap to a pitch
        can never move a hole further than half of it, so a doubled pitch under a
        record that still says 0.25 is caught here too.
        """
        after = Pipeline([SnapPositions(grid=grid)]).run(make_data(*holes((10.3, 5.02))))

        recorded = after.last_run("snap").get("grid_mm")
        assert recorded == grid
        assert positions(after) == expected
        for hole in after.holes:
            assert abs(hole.x - hole.raw.x) <= recorded / 2 + 1e-9
            assert abs(hole.y - hole.raw.y) <= recorded / 2 + 1e-9

    def test_a_disabled_stage_still_records_that_it_ran_and_did_nothing(self):
        after = Pipeline([SnapPositions(grid=0.0)]).run(make_data(*holes((10.03, 5.02))))

        assert [r.name for r in after.processing] == ["snap"]
        assert after.last_run("snap").get("enabled") is False
        assert positions(after) == [(10.03, 5.02)], "a disabled snap moved a hole"

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

        data = make_data(at(0.0, 0.0, index=0))
        with pytest.raises(RuntimeError):
            Pipeline([SnapPositions(0.25), Explodes()]).run(data)
        assert data.processing == ()

    def test_a_pipeline_records_its_stages_in_order(self):
        """Read off the stages that were handed in, not from a copy of the list.

        The literal spelling drifted once already — it named the CLI's order,
        which this list has not been since the enclosure stage joined it — and a
        parallel list is what let that happen quietly. What is being asserted is
        that ``Pipeline`` records *in order*, which the input already states.
        """
        stages = ALL_STAGES
        after = Pipeline(stages).run(
            make_data(
                *holes((-40.003, 18.001, 6.9998), (19.0, -18.75, 5.0002)),
                reference=ReferenceOutline(113.0, 60.0),
            )
        )
        assert [r.name for r in after.processing] == [type(s).name for s in stages]
        assert len(after.processing) == len(stages), "a stage recorded nothing"


# --------------------------------------------------------------------------
# Reaching the stages
# --------------------------------------------------------------------------


def test_the_stages_and_the_standards_are_re_exported_from_the_package_root():
    """Nothing enumerates the stages, so the root is where they are named.

    ``build_pipeline`` is the CLI's arrangement and not the only one — SPEC
    calls ``CheckReferenceSize`` a supported stage for a library caller, and the
    CLI never runs it. A root exporting ``Pipeline`` and the ``Stage`` protocol
    but no stage hands a consumer an empty pipeline and no way to fill it, and
    exporting the stages without ``DRILL_STANDARDS`` leaves the one stage that
    takes an argument unconfigurable.
    """
    import aidrill

    stages = (
        SnapPositions,
        SnapDiametersToDrillTable,
        Deduplicate,
        IdentifyHammondFootprint,
        SortHoles,
        CheckReferenceSize,
    )
    for stage in stages:
        assert getattr(aidrill, stage.__name__, None) is stage
        assert stage.__name__ in aidrill.__all__

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
