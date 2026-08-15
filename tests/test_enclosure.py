"""Tests for ``IdentifyHammondFootprint`` (SPEC §5, PLAN task B).

Split out of ``test_pipeline.py``, which had grown to 2160 lines covering six
stages with three agents about to work on it in parallel: one file per stage
gives each agent disjoint ownership instead of a merge conflict waiting to
happen. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import json

import pytest

from aidrill.emitters.json_out import JsonEmitter
from aidrill.enclosures import footprints
from aidrill.model import DrillData, RawOutline, ReferenceOutline, Severity
from aidrill.pipeline import IdentifyHammondFootprint, normalize_part_name
from aidrill.pipeline import enclosure as enclosure_stage
from aidrill.protocols import Pipeline
from tests.conftest import at, codes, make_data


def an_outline(width: float, height: float) -> DrillData:
    """A panel whose reference outline is the measurement, and nothing else."""
    return make_data(reference=ReferenceOutline.from_measurement(width, height))


class TestIdentifyHammondFootprint:
    def test_the_fixture_outline_snaps_to_the_1590B_footprint(self):
        """tar.ai measures 113.0 × 60.0; the catalogue says 112 × 61. Snap, silently."""
        out = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0))

        assert (out.reference.width, out.reference.height) == (112.0, 61.0)
        assert (out.reference.raw.width, out.reference.raw.height) == (113.0, 60.0)
        assert out.enclosure.candidates == ("1590B", "1590B2", "1590BS")
        assert out.enclosure.family == "Hammond 1590"
        assert (out.enclosure.length_mm, out.enclosure.width_mm) == (112, 61)
        assert out.diagnostics == ()  # silence is the decision

    def test_the_catalogue_dimensions_are_whole_millimetres_not_floats(self):
        """The datasheet's metric column is integral; the outline's is not.

        Recorded as ``int`` so a consumer printing the enclosure gets "112 × 61"
        rather than "112.0 × 61.0" and cannot mistake a catalogue constant for a
        measurement that happened to land on a whole number.
        """
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure

        assert isinstance(match.length_mm, int) and isinstance(match.width_mm, int)
        assert isinstance(match.rotated, bool)

    def test_no_reference_outline_is_left_alone(self):
        """LSP: the source may simply not have had a reference layer."""
        data = make_data(at(0.0, 0.0, index=0))

        out = IdentifyHammondFootprint().apply(data)

        assert out == data
        assert out.enclosure is None
        assert out.diagnostics == ()

    def test_an_outline_matching_nothing_is_reported_without_being_refused(self):
        """A warning, not an error, and never a guess.

        This is the one finding in this stage that is about *our catalogue*
        rather than about the operator's panel: we hold 22 Hammond footprints
        and the world holds rather more. It still may not be silent — an
        unmatched outline is not snapped, so every downstream number keeps the
        artwork's fractional millimetres — but refusing the run would be this
        tool claiming an authority it does not have.
        """
        out = IdentifyHammondFootprint().apply(an_outline(500.0, 500.0))

        assert codes(out) == ["unknown-enclosure"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == (500.0, 500.0)

    def test_drawing_an_unrecognised_outline_is_not_punished_harder_than_omitting_one(self):
        """The asymmetry that decided the severity, asserted as one comparison.

        A panel with no reference layer returns untouched and clean, because no
        stage may assume a predecessor ran. If an unrecognised outline were an
        ERROR, then *drawing* your panel outline would fail the run while
        leaving it out would pass — and the two would be judged by two different
        standards for the same missing knowledge. Whatever severity these two
        carry, the drawn one may not be the worse of them.
        """
        omitted = IdentifyHammondFootprint().apply(make_data(at(0.0, 0.0, index=0)))
        drawn = IdentifyHammondFootprint().apply(an_outline(500.0, 500.0))

        assert omitted.worst_severity is None
        assert drawn.worst_severity is not Severity.ERROR

    def test_the_unknown_diagnostic_carries_what_was_measured_and_what_was_searched(self):
        """``Diagnostic.data`` is a consumer contract, not a debug aid: it is
        there so a report can say what failed without re-deriving the predicate.
        Unasserted, it is an unpinned contract."""
        # 113.6 rather than 500: the size must come from the outline as it
        # stands, and a payload sourced from ``raw`` instead would be
        # indistinguishable on an outline nothing has snapped.
        diagnostic = IdentifyHammondFootprint(tolerance_mm=0.4).apply(
            make_data(reference=ReferenceOutline(113.6, 60.0, raw=RawOutline(1.0, 2.0)))
        ).diagnostics[0]

        assert diagnostic.get("width_mm") == 113.6
        assert diagnostic.get("height_mm") == 60.0
        assert diagnostic.get("tolerance_mm") == 0.4
        assert diagnostic.get("catalogue") == "Hammond 1590"

    def test_a_near_miss_is_unknown_rather_than_the_footprint_it_nearly_is(self):
        """113.6 × 60.0 is 1.6 mm off 1590B on one axis. Outside is outside.

        The far-away 500 × 500 fixture cannot tell a tolerance check from a
        catalogue lookup that only ever succeeds on an exact hit, and it would
        stay green under a tolerance widened to 2 mm. This one dies to both.
        """
        out = IdentifyHammondFootprint().apply(an_outline(113.6, 60.0))

        assert codes(out) == ["unknown-enclosure"]
        assert out.enclosure is None
        assert out.reference.width == 113.6, "an unmatched outline was snapped anyway"

    def test_the_tolerance_boundary_is_inclusive(self):
        """1.5 mm exactly is a match; the machinist typed the number they meant."""
        assert IdentifyHammondFootprint().apply(an_outline(113.5, 61.0)).enclosure is not None
        assert IdentifyHammondFootprint().apply(an_outline(113.51, 61.0)).enclosure is None

    def test_a_tighter_tolerance_rejects_what_the_default_accepts(self):
        """The fixture's own 1.0 mm error, against a tolerance that will not have it."""
        tight = IdentifyHammondFootprint(tolerance_mm=0.5)
        assert tight.apply(an_outline(113.0, 60.0)).enclosure is None
        assert IdentifyHammondFootprint(tolerance_mm=1.5).apply(an_outline(113.0, 60.0)).enclosure

    def test_both_axes_must_be_within_the_tolerance(self):
        """One axis on the nose does not carry the other one home.

        The assertion is on the *code*, not on ``enclosure is None``, and that
        distinction is the whole test. ``enclosure is None`` is reachable by two
        paths — nothing matched, and too much matched — so it asserts the union
        rather than the case the name claims. Drop the height clause from
        ``_fits`` and 112.0 × 65.0 matches three footprints on width alone,
        (111, 82), (112, 61) and (192, 112) turned 90°, giving
        ``ambiguous-enclosure`` with ``enclosure`` still ``None``: the half of
        this test that names the height axis would have stayed green.
        """
        # Width exact, height 4 mm out.
        assert codes(IdentifyHammondFootprint().apply(an_outline(112.0, 65.0))) == [
            "unknown-enclosure"
        ]
        # Height exact, width 4 mm out.
        assert codes(IdentifyHammondFootprint().apply(an_outline(108.0, 61.0))) == [
            "unknown-enclosure"
        ]


class TestRotation:
    def test_a_portrait_panel_matches_its_landscape_catalogue_entry(self):
        out = IdentifyHammondFootprint().apply(an_outline(60.0, 113.0))

        assert out.enclosure.rotated is True
        assert (out.reference.width, out.reference.height) == (61.0, 112.0)

    def test_a_rotated_match_records_the_catalogue_orientation_not_the_artworks(self):
        """The datasheet says 1590B is 112 × 61. Transposing it here would make
        the identified part unfindable in the document it was identified from."""
        match = IdentifyHammondFootprint().apply(an_outline(60.0, 113.0)).enclosure

        assert (match.length_mm, match.width_mm) == (112, 61)
        assert match.candidates == ("1590B", "1590B2", "1590BS")

    def test_a_landscape_panel_is_recorded_as_not_rotated(self):
        """Paired with the portrait case so neither hardcoded flag survives."""
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure
        assert match.rotated is False

    def test_a_square_footprint_is_not_a_rotation(self):
        """1590Y is 92 × 92, so both readings fit. A turn of no consequence is
        not a turn, and reporting one would put "rotated" on a drawing for a
        panel nobody rotated."""
        match = IdentifyHammondFootprint().apply(an_outline(92.4, 91.8)).enclosure

        assert match.candidates == ("1590Y",)
        assert match.rotated is False

    def test_a_rotated_match_is_silent_too(self):
        assert IdentifyHammondFootprint().apply(an_outline(60.0, 113.0)).diagnostics == ()


class TestAmbiguity:
    # 1590B3 (116 × 77) and 1590T (120 × 80) are the closest pair in the whole
    # catalogue, 4 mm apart on the wider axis. An outline halfway between them
    # is within 2 mm of both — the only shape of fixture that can reach rule 5.
    TIED = (118.0, 78.5)

    def test_an_ambiguous_tie_is_an_error_not_a_choice(self):
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.TIED

    def test_the_tie_diagnostic_names_every_footprint_it_could_not_choose_between(self):
        """Naming one of them would be the guess this rule exists to refuse."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("footprints") == "116 × 77, 120 × 80"
        assert diagnostic.get("candidates") == "1590B3, 1590T"
        # The tolerance is the actionable half of this finding: it is the one
        # thing the operator can change to break the tie.
        assert diagnostic.get("tolerance_mm") == 2.0

    def test_the_same_outline_is_unambiguous_at_the_default_tolerance(self):
        """The tie is a property of the tolerance, not of the outline."""
        assert codes(IdentifyHammondFootprint().apply(an_outline(*self.TIED))) == [
            "unknown-enclosure"
        ]

    def test_the_default_tolerance_admits_no_tie_anywhere_in_the_catalogue(self):
        """Nothing had checked this, so check it against the real catalogue.

        Two footprints can both match one outline exactly when their per-axis
        separation — minimised over the rotated reading as well, since a stage
        that compares both is comparing against both orientations of every
        entry — is at most twice the tolerance. So the largest safe tolerance is
        half the closest approach in the catalogue, exclusive. That approach is
        4 mm (1590B3 116 × 77 against 1590T 120 × 80), which puts the ceiling
        just under 2 mm and leaves the default 1.5 mm clear.
        """
        outlines = sorted(footprints())
        separations = [
            min(
                max(abs(a[0] - b[0]), abs(a[1] - b[1])),
                max(abs(a[0] - b[1]), abs(a[1] - b[0])),
            )
            for i, a in enumerate(outlines)
            for b in outlines[i + 1 :]
        ]

        assert len(outlines) == 22
        assert min(separations) == 4
        assert 2 * IdentifyHammondFootprint().tolerance_mm < min(separations)

    def test_two_millimetres_is_where_ambiguity_becomes_reachable(self):
        """The bound above is tight, not merely sufficient: at exactly half the
        closest approach the tie is real, which is why the default is not 2."""
        assert codes(IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))) == [
            "ambiguous-enclosure"
        ]
        just_under = IdentifyHammondFootprint(tolerance_mm=1.99).apply(an_outline(*self.TIED))
        assert just_under.enclosure is None
        assert codes(just_under) == ["unknown-enclosure"]

    def test_the_tie_is_reported_in_size_order_whatever_order_the_catalogue_is_in(
        self, monkeypatch
    ):
        """The message must not reshuffle when an unrelated part is added.

        Needs a stand-in catalogue: the real one is *generated* ordered by
        footprint, so its insertion order already equals its sorted order and
        nothing built on it can tell the two apart. Two entries, deliberately
        the wrong way round.
        """
        monkeypatch.setattr(
            enclosure_stage,
            "footprints",
            lambda: {(120, 80): ("FAKE-T",), (116, 77): ("FAKE-B3",)},
        )
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert out.diagnostics[0].get("footprints") == "116 × 77, 120 × 80"
        assert out.diagnostics[0].get("candidates") == "FAKE-B3, FAKE-T"


class TestDeclaredCase:
    def test_declaring_the_wrong_case_is_an_error(self):
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))

        assert codes(out) == ["wrong-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR

    def test_the_wrong_case_diagnostic_names_both_parts(self):
        """The operator needs to know what they asked for *and* what they drew;
        either alone leaves them re-deriving the other from the artwork."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590BB"
        assert diagnostic.get("identified_parts") == "1590B, 1590B2, 1590BS"
        # And the footprint that identified them, so a consumer can show the
        # measurement that produced the disagreement rather than re-taking it.
        assert (diagnostic.get("length_mm"), diagnostic.get("width_mm")) == (112, 61)

    def test_a_wrongly_declared_panel_is_still_identified_and_still_snapped(self):
        """The outline matched; only the declaration disagrees. Dropping the
        match would leave the report with nothing to name."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))

        assert out.enclosure.candidates == ("1590B", "1590B2", "1590BS")
        assert out.enclosure.selected_part == "1590BB"
        assert (out.reference.width, out.reference.height) == (112.0, 61.0)

    def test_a_correctly_declared_case_becomes_the_selected_part(self):
        """A footprint names candidates; only the operator can pick among them."""
        out = IdentifyHammondFootprint(expected_part="1590B2").apply(an_outline(113.0, 60.0))

        assert out.enclosure.selected_part == "1590B2"
        assert out.diagnostics == ()

    def test_nothing_is_selected_when_nothing_was_declared(self):
        """The artwork does not contain the height, so it cannot be inferred."""
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure
        assert match.selected_part is None

    def test_a_declared_case_is_matched_however_it_was_typed(self):
        out = IdentifyHammondFootprint(expected_part=" 1590b2 ").apply(an_outline(113.0, 60.0))

        assert out.diagnostics == ()
        assert out.enclosure.selected_part == "1590B2"

    def test_a_blank_declaration_is_no_declaration(self):
        """An empty ``--case`` must not become a part number nothing can match."""
        out = IdentifyHammondFootprint(expected_part="   ").apply(an_outline(113.0, 60.0))

        assert out.diagnostics == ()
        assert out.enclosure.selected_part is None


class TestADeclarationIsCheckedOnEveryOutcome:
    """The declaration has to bite where the geometry *failed*, not only where
    it succeeded.

    Regression for the review's central finding: ``expected_part`` used to be
    compared only after a unique catalogue match, so the three early returns —
    no reference outline, no footprint, a tie — each walked past it. The panel
    that reached the operator was the worst case of all: a declared case, an
    outline nothing recognised, ``unknown-enclosure`` at WARNING, and a drill
    file on disk. ``--true-size`` was deleted on the understanding that
    ``--case`` carried this assertion; these tests are that understanding.

    Every case below is paired with its undeclared twin, because the asymmetry
    *is* the policy: declare nothing and an unidentifiable panel still runs;
    declare something and it must be checked.
    """

    # 1590B3 (116 × 77) and 1590T (120 × 80) are the catalogue's closest pair,
    # and this outline sits within 2 mm of both — the only shape of fixture that
    # can reach a tie at all.
    TIED = (118.0, 78.5)
    #: Larger than every footprint in the catalogue, on both axes.
    UNRECOGNISED = (300.0, 300.0)

    def test_a_declaration_with_no_outline_to_check_it_against_is_refused(self):
        """Silence here would be indistinguishable from a confirmed declaration."""
        data = make_data(at(3.0, -4.0, index=7))

        out = IdentifyHammondFootprint(expected_part="1590B").apply(data)

        assert codes(out) == ["unverifiable-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.holes == data.holes
        assert out.enclosure is None

    def test_no_outline_and_no_declaration_is_still_left_alone(self):
        """The undeclared twin: nothing was claimed, so nothing is checked."""
        data = make_data(at(3.0, -4.0, index=7))

        assert IdentifyHammondFootprint().apply(data) == data

    def test_the_unverifiable_diagnostic_names_the_part_and_the_size_it_would_be(self):
        """A consumer must be able to say what the panel *should* measure
        without going back to the catalogue the stage has already read."""
        out = IdentifyHammondFootprint(expected_part=" 1590b ").apply(
            make_data(at(3.0, -4.0, index=7))
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590B"
        assert (diagnostic.get("expected_length_mm"), diagnostic.get("expected_width_mm")) == (
            112,
            61,
        )
        assert diagnostic.get("catalogue") == "Hammond 1590"

    def test_a_declaration_the_artwork_matches_nothing_for_is_refused(self):
        """The reproduction from the review, exactly: a declared 1590B against
        an outline no footprint fits used to exit 1 and write the drill file."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(
            an_outline(*self.UNRECOGNISED)
        )

        assert codes(out) == ["unmatched-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.UNRECOGNISED

    def test_an_unrecognised_outline_nobody_declared_stays_a_warning(self):
        """The undeclared twin, and the reason the new code is not
        ``unknown-enclosure`` at a second severity."""
        out = IdentifyHammondFootprint().apply(an_outline(*self.UNRECOGNISED))

        assert codes(out) == ["unknown-enclosure"]
        assert out.diagnostics[0].severity is Severity.WARNING

    def test_the_unmatched_diagnostic_carries_the_declaration_and_the_measurement(self):
        """Both halves of the disagreement, so the consumer re-measures nothing.

        ``footprints``/``candidates`` are empty because nothing fitted; the keys
        are still there, so one payload shape serves both ways of failing to
        confirm a declaration.
        """
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(
            an_outline(*self.UNRECOGNISED)
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590BB"
        assert (diagnostic.get("expected_length_mm"), diagnostic.get("expected_width_mm")) == (
            120,
            94,
        )
        assert (diagnostic.get("width_mm"), diagnostic.get("height_mm")) == self.UNRECOGNISED
        assert diagnostic.get("tolerance_mm") == 1.5
        assert diagnostic.get("catalogue") == "Hammond 1590"
        assert diagnostic.get("footprints") == ""
        assert diagnostic.get("candidates") == ""

    def test_a_declaration_breaks_a_tie_the_catalogue_cannot(self):
        """Two footprints fit; the operator already said which one it is.

        1590T's 120 × 80 rather than the nearer 1590B3, so the resolved match
        cannot be confused with "the first candidate" or "the closest one" —
        116 × 77 is both.
        """
        out = IdentifyHammondFootprint(tolerance_mm=2.0, expected_part="1590T").apply(
            an_outline(*self.TIED)
        )

        assert out.diagnostics == ()
        assert (out.enclosure.length_mm, out.enclosure.width_mm) == (120, 80)
        assert out.enclosure.selected_part == "1590T"
        assert (out.reference.width, out.reference.height) == (120.0, 80.0)
        assert (out.reference.raw.width, out.reference.raw.height) == self.TIED

    def test_a_tie_the_declaration_does_not_resolve_is_refused(self):
        """Declared 1590B; the outline is within tolerance of two footprints and
        neither of them is 1590B. Naming either would be the guess."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0, expected_part="1590B").apply(
            an_outline(*self.TIED)
        )
        diagnostic = out.diagnostics[0]

        assert codes(out) == ["unmatched-enclosure"]
        assert diagnostic.severity is Severity.ERROR
        assert diagnostic.get("requested_part") == "1590B"
        assert diagnostic.get("footprints") == "116 × 77, 120 × 80"
        assert diagnostic.get("candidates") == "1590B3, 1590T"
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.TIED

    def test_an_undeclared_tie_is_still_ambiguous_and_still_asks_for_a_case(self):
        """The undeclared twin. ``ambiguous-enclosure`` keeps its one meaning —
        more than one footprint fits and nothing was said to choose between
        them — which is why the advice in its message is still sound."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert "declare the case" in out.diagnostics[0].message

    def test_a_declared_part_no_catalogue_holds_invents_no_footprint_for_it(self):
        """The CLI refuses this as a usage error before the file is opened, but
        a library caller can hand the stage anything, and a payload key filled
        in with a plausible number would be worse than an absent one."""
        out = IdentifyHammondFootprint(expected_part="1590ZZ").apply(
            an_outline(*self.UNRECOGNISED)
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.code == "unmatched-enclosure"
        assert diagnostic.get("requested_part") == "1590ZZ"
        assert diagnostic.get("expected_length_mm") is None
        assert diagnostic.get("expected_width_mm") is None


class TestNormalizePartName:
    """The public resolver. Its contract is owned here, not inherited from the
    extraction script's private ``_base_designator``."""

    @pytest.mark.parametrize(
        "typed, expected",
        [
            ("1590b", "1590B"),
            (" 1590BB\n", "1590BB"),
            ("1590BB", "1590BB"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_case_and_surrounding_space_are_the_only_things_normalised(self, typed, expected):
        assert normalize_part_name(typed) == expected

    def test_a_finish_or_flange_suffix_is_left_alone(self):
        """Deliberate. Collapsing 1590BBBK to 1590BB would need the datasheet's
        suffix grammar, whose 1590W and flange cases are subtle enough to have
        been wrong once already. An order code typed in full gets a
        ``wrong-enclosure`` naming both parts, which is a legible mistake; a
        silent collapse to the wrong base part is not.
        """
        assert normalize_part_name("1590BBBK") == "1590BBBK"
        assert normalize_part_name("1590WF") == "1590WF"


class TestIdentifyHammondFootprintDescribe:
    def test_it_reports_the_tolerance_and_the_catalogue_it_searched(self):
        run = IdentifyHammondFootprint(tolerance_mm=0.75).describe()

        assert run.name == "identify-enclosure"
        assert run.get("tolerance_mm") == 0.75
        assert run.get("catalogue") == "Hammond 1590"

    def test_it_reports_the_declared_part_as_the_stage_resolved_it(self):
        """Effective values, not raw arguments: the comparison is made against
        the normalised form, so that is what provenance must show."""
        run = IdentifyHammondFootprint(expected_part=" 1590bb ").describe()
        assert run.get("expected_part") == "1590BB"

    def test_an_undeclared_part_is_absent_rather_than_present_and_empty(self):
        """``get`` cannot tell an absent key from a null one, and ``None`` is not
        a legal ``ParameterValue``."""
        parameters = dict(IdentifyHammondFootprint().describe().parameters)
        blank = dict(IdentifyHammondFootprint(expected_part="   ").describe().parameters)

        assert "expected_part" not in parameters
        assert "expected_part" not in blank


class TestTheMeasurementSurvivesTheSnap:
    def test_the_emitted_document_still_quotes_what_the_artwork_said(self):
        """End-to-end, and it has to be: ``ReferenceOutline(112.0, 61.0)`` is
        legitimate code whose ``raw`` defaults to its own dimensions, so a snap
        that builds a fresh outline instead of calling ``resized`` silently
        rewrites the measurement to the snapped size. Nothing at the unit level
        can see the difference — both spellings produce a 112 × 61 outline — so
        the claim is made where the loss becomes visible: in the serialised
        document a library consumer actually reads.
        """
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            reference=ReferenceOutline.from_measurement(
                113.0, 60.0, centre_x=306.0, centre_y=170.0
            ),
        )

        after = Pipeline([IdentifyHammondFootprint()]).run(data)
        document = json.loads(JsonEmitter().emit(after))

        assert document["reference"]["width"] == 112.0
        assert document["reference"]["height"] == 61.0
        assert document["reference"]["raw"] == {"width": 113.0, "height": 60.0}

    def test_the_snap_keeps_the_outlines_source_space_centre(self):
        """``centre_x``/``centre_y`` say where the outline sat on the page. A
        fresh construction would drop them back to the origin."""
        data = make_data(
            reference=ReferenceOutline.from_measurement(113.0, 60.0, 306.0, 170.0)
        )
        out = IdentifyHammondFootprint().apply(data)

        assert out.reference.width == 112.0, "the outline was never snapped at all"
        assert (out.reference.centre_x, out.reference.centre_y) == (306.0, 170.0)

    def test_a_second_snap_does_not_rewrite_the_measurement(self):
        """Idempotence, and provenance under it: 112 × 61 is already a footprint,
        so running twice must change nothing and must not promote the snapped
        size to a measurement."""
        once = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0))
        twice = IdentifyHammondFootprint().apply(once)

        assert once.reference.width == 112.0, "the first pass never snapped anything"
        assert twice.reference == once.reference
        assert (twice.reference.raw.width, twice.reference.raw.height) == (113.0, 60.0)
        assert twice.diagnostics == ()
