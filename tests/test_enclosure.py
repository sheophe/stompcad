"""Tests for enclosure identification and declared-case validation."""

from __future__ import annotations

import pytest

from aidrill.enclosures import footprints
from aidrill.units import Millimetre, Nanometre
from aidrill.model import Diagnostic, RawOutline, Severity
from aidrill.pipeline import IdentifyHammondFootprint, normalize_part_name
from aidrill.pipeline import enclosure as enclosure_stage

#: Nanometres in a millimetre, spelled out rather than imported from ``units``:
#: a test that took the factor from the module under test could not tell a
#: correct conversion from a consistently wrong one.
MM = 1_000_000

#: A page centre for the outlines whose source-space position is not the point.
ORIGIN = (0.0, 0.0)

#: The project's own fixture panel, as ``AiPdfSource`` measures ``tar.ai``. It is
#: a 1590B — and it fits **two** catalogue footprints, 1590BS's 112.00 × 60.50 and
#: 1590B/1590B2's 112.40 × 60.50, so an undeclared run cannot identify it. Every
#: test below that uses it therefore declares a case, and
#: `TestTheFixturePanelNeedsADeclaredCase` pins that requirement on its own.
FIXTURE = RawOutline(Millimetre(113.0), Millimetre(60.0))

#: 1590B's footprint, which `FIXTURE` snaps to once a case is declared.
B_FOOTPRINT = (112_400_000, 60_500_000)

#: A panel drawn for a 1590A, whose 92.60 × 38.50 has no catalogue neighbour
#: within tolerance in either orientation. Every test that needs a *silent,
#: undeclared* match uses this one, because the fixture above can no longer
#: supply it — and the axes differ, so a transposed answer cannot pass.
UNAMBIGUOUS = RawOutline(Millimetre(93.0), Millimetre(38.0))

#: 1590A's footprint, which `UNAMBIGUOUS` snaps to.
A_FOOTPRINT = (92_600_000, 38_500_000)


def codes(diagnostics: tuple[Diagnostic, ...]) -> list[str]:
    """The stable machine key of every finding, in order.

    Every diagnostic assertion below goes through this, so none of them can
    quietly start matching on wording.
    """
    return [d.code for d in diagnostics]


def catalogue_footprints_nm() -> set[tuple[int, int]]:
    """Every catalogue footprint, in nanometres, in the catalogue's orientation."""
    return set(footprints())


class TestIdentifyHammondFootprint:
    def test_the_fixture_outline_snaps_to_the_1590B_footprint(self):
        """tar.ai measures 113.0 × 60.0; the drawing says 1590B is 112.40 × 60.50.

        Snap, silently — with the case declared, because the same outline is
        also within tolerance of 1590BS.
        """
        outline, match, diagnostics = IdentifyHammondFootprint("1590B").quantise(
            FIXTURE, ORIGIN
        )

        assert (outline.width_nm, outline.height_nm) == B_FOOTPRINT
        assert outline.raw == FIXTURE
        assert match.candidates == ("1590B", "1590B2")
        assert match.family == "Hammond 1590"
        assert (match.length_nm, match.width_nm) == B_FOOTPRINT
        assert diagnostics == ()  # silence is the decision

    @pytest.mark.parametrize(
        "width, height",
        [
            (93.0, 38.0),  # 1590A, 92.60 × 38.50
            (38.0, 93.0),  # the same panel turned 90°
            (92.4, 91.8),  # 1590Y, square
            (99.6, 50.4),  # 1590G
            (120.7, 94.3),  # 1590BB
            (110.0, 83.0),  # 1590S, 110.50 × 82.40
        ],
    )
    def test_every_snapped_outline_is_provably_a_catalogue_footprint(self, width, height):
        """Exact *by construction*, checked rather than asserted."""
        outline, match, _ = IdentifyHammondFootprint().quantise(
            RawOutline(width, height), ORIGIN
        )
        catalogue = catalogue_footprints_nm()

        assert match is not None
        assert (match.length_nm, match.width_nm) in catalogue
        # The outline keeps the artwork's own orientation, so either reading of
        # the footprint is a legitimate answer for it — but nothing else is.
        assert (outline.width_nm, outline.height_nm) in catalogue | {
            (width_nm, length_nm) for length_nm, width_nm in catalogue
        }

    def test_the_catalogue_dimensions_are_whole_nanometres_not_floats(self):
        """The catalogue is a table of integers and the outline is a measurement."""
        _, match, _ = IdentifyHammondFootprint("1590B").quantise(FIXTURE, ORIGIN)

        assert type(match.length_nm) is int and type(match.width_nm) is int
        assert (match.length_nm, match.width_nm) == (112_400_000, 60_500_000)
        assert type(match.rotated) is bool

    def test_no_outline_is_left_alone(self):
        """LSP: the source may simply not have had a reference layer.

        It has already said so, with a WARNING of its own naming the frame the
        holes are in. A second finding here would report one absence twice.
        """
        assert IdentifyHammondFootprint().quantise(None, ORIGIN) == (None, None, ())

    def test_the_outlines_source_space_centre_is_carried_onto_the_answer(self):
        """``centre`` is where the outline sat on the page, and only the
        quantiser is in a position to put it on the outline: the measurement
        does not carry it and nothing downstream can re-derive it."""
        outline, _, _ = IdentifyHammondFootprint().quantise(UNAMBIGUOUS, (306.0, 170.0))

        assert (outline.centre_x_nm, outline.centre_y_nm) == (306 * MM, 170 * MM)

    def test_a_near_miss_is_unknown_rather_than_the_footprint_it_nearly_is(self):
        """94.2 × 38.5 is 1.6 mm off 1590A on one axis. Outside is outside."""
        outline, match, diagnostics = IdentifyHammondFootprint().quantise(
            RawOutline(Millimetre(94.2), Millimetre(38.5)), ORIGIN
        )

        assert codes(diagnostics) == ["unknown-enclosure"]
        assert match is None
        assert outline.width_nm == 94_200_000, "an unmatched outline was snapped anyway"

    def test_the_tolerance_boundary_is_inclusive_to_the_nanometre(self):
        """1.5 mm exactly is a match; the machinist typed the number they meant."""
        on_it = IdentifyHammondFootprint().quantise(RawOutline(Millimetre(94.1), Millimetre(38.5)), ORIGIN)
        one_nm_over = IdentifyHammondFootprint().quantise(
            RawOutline(Millimetre(94.100001), Millimetre(38.5)), ORIGIN
        )

        assert on_it[1] is not None
        assert one_nm_over[1] is None

    def test_the_measurement_is_compared_without_being_rounded_first(self):
        """Compare the measurement unrounded at the boundary that distinguishes it."""
        _, match, _ = IdentifyHammondFootprint().quantise(
            RawOutline(Millimetre(94.1000004), Millimetre(38.5)), ORIGIN
        )

        assert match is None

    def test_a_declared_case_is_checked_against_the_unrounded_measurement_too(self):
        """A declared case is checked against the unrounded measurement.

        Values just inside and outside the bound reject premature rounding.
        """
        on_it = IdentifyHammondFootprint("1590B").quantise(RawOutline(Millimetre(113.9), Millimetre(60.5)), ORIGIN)
        assert on_it[1] is not None, "the fixture is not a hair outside the bound"

        outline, match, diagnostics = IdentifyHammondFootprint("1590B").quantise(
            RawOutline(Millimetre(113.9000004), Millimetre(60.5)), ORIGIN
        )

        assert match is None
        assert codes(diagnostics) == ["unmatched-enclosure"]
        assert outline.width_nm == 113_900_000, "the outline was snapped to a footprint anyway"

    def test_a_tighter_tolerance_rejects_what_the_default_accepts(self):
        """A 1.4 mm drawing error against a tolerance that will not have it."""
        drawn = RawOutline(Millimetre(94.0), Millimetre(38.0))  # 1.4 and 0.5 mm off 1590A
        tight = IdentifyHammondFootprint(tolerance_nm=Nanometre(500_000))
        assert tight.quantise(drawn, ORIGIN)[1] is None
        assert (
            IdentifyHammondFootprint(tolerance_nm=Nanometre(1_500_000)).quantise(drawn, ORIGIN)[1]
            is not None
        )

    def test_both_axes_must_be_within_the_tolerance(self):
        """One axis on the nose does not carry the other one home."""
        # Width exact, height 4 mm out.
        assert codes(
            IdentifyHammondFootprint().quantise(RawOutline(Millimetre(112.0), Millimetre(65.0)), ORIGIN)[2]
        ) == ["unknown-enclosure"]
        # Height exact, width 4 mm out.
        assert codes(
            IdentifyHammondFootprint().quantise(RawOutline(Millimetre(108.0), Millimetre(61.0)), ORIGIN)[2]
        ) == ["unknown-enclosure"]

    def test_a_tolerance_that_is_not_whole_nanometres_is_refused_at_construction(self):
        """The tolerance must be plain-integer nanometres at construction."""
        with pytest.raises(TypeError):
            IdentifyHammondFootprint(tolerance_nm=1.5)
        with pytest.raises(TypeError):
            IdentifyHammondFootprint(tolerance_nm=True)

    def test_a_negative_tolerance_is_refused_rather_than_matching_nothing(self):
        """Reject negative tolerances rather than matching nothing silently."""
        with pytest.raises(ValueError, match="negative"):
            IdentifyHammondFootprint(tolerance_nm=Nanometre(-1))

    def test_a_tolerance_of_nothing_is_a_tolerance_and_is_kept(self):
        """Zero says the outline *is* a catalogue footprint, to the nanometre,
        which is a question an operator is entitled to ask."""
        exact = IdentifyHammondFootprint(tolerance_nm=Nanometre(0))

        assert exact.quantise(RawOutline(Millimetre(92.6), Millimetre(38.5)), ORIGIN)[1] is not None
        assert exact.quantise(RawOutline(Millimetre(92.600001), Millimetre(38.5)), ORIGIN)[1] is None


class TestAnUnmatchedOutlineIsQuantisedOntoItself:
    """The outline's answer set is *the catalogue, or the measurement itself*."""

    #: Larger than every footprint in the catalogue, on both axes, and not a
    #: whole number of millimetres: the fractional tenth is what proves the
    #: answer is the measurement rather than a rounding of it.
    #:
    #: The last digit is doing separate work, and it is the digit below a whole
    #: nanometre. 500.0004 mm is *exactly* 500 000 400 nm, so a `raw` synthesised
    #: from the nominal integer would rebuild that very float and the provenance
    #: assertion below could not tell a kept measurement from a round trip
    #: through the answer. 500.0004004 mm is 500 000 400.4, quantises to the same
    #: nominal, and rebuilds as 500.0004 — which is the disagreement the
    #: assertion needs to be able to see.
    UNRECOGNISED = (500.0004004, 300.0)

    def test_the_answer_is_provably_the_measurement_and_not_a_footprint(self):
        outline, match, _ = IdentifyHammondFootprint().quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )

        assert match is None
        assert (outline.width_nm, outline.height_nm) == (500_000_400, 300_000_000)
        assert (outline.width_nm, outline.height_nm) not in catalogue_footprints_nm()

    def test_the_measurement_is_kept_as_the_float_the_artwork_gave(self):
        """``raw`` is what lets a consumer tell a *measured* 500 from a snapped one, and it
        is the only place the un-quantised measurement survives.
        """
        outline, _, _ = IdentifyHammondFootprint().quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )

        assert outline.raw.width * MM != outline.width_nm, (
            "the fixture is a whole number of nanometres"
        )
        assert outline.raw == RawOutline(*self.UNRECOGNISED)

    def test_it_is_a_warning_and_the_frame_is_still_usable(self):
        outline, _, diagnostics = IdentifyHammondFootprint().quantise(
            RawOutline(*self.UNRECOGNISED), (306.0, 170.0)
        )

        assert codes(diagnostics) == ["unknown-enclosure"]
        assert diagnostics[0].severity is Severity.WARNING
        assert (outline.centre_x_nm, outline.centre_y_nm) == (306 * MM, 170 * MM)

    def test_drawing_an_unrecognised_outline_is_not_punished_harder_than_omitting_one(
        self,
    ):
        """An unrecognised outline is no more severe than an omitted outline."""
        omitted = IdentifyHammondFootprint().quantise(None, ORIGIN)[2]
        drawn = IdentifyHammondFootprint().quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )[2]

        assert omitted == ()
        assert all(d.severity is not Severity.ERROR for d in drawn)

    def test_the_finding_carries_what_was_measured_and_what_was_searched(self):
        """The payload carries the measurement, tolerance and catalogue searched."""
        # 113.6 rather than 500: the size must come from the outline this
        # quantiser produced, and a payload sourced from anything else would be
        # indistinguishable on an outline nothing has snapped.
        _, _, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(400_000)).quantise(
            RawOutline(Millimetre(113.6), Millimetre(60.0)), ORIGIN
        )

        assert diagnostics[0].get("width_nm") == 113_600_000
        assert diagnostics[0].get("height_nm") == 60 * MM
        assert diagnostics[0].get("tolerance_nm") == 400_000
        assert diagnostics[0].get("catalogue") == "Hammond 1590"


class TestTheBackplateConvention:
    """Face measurements are refused in favour of the backplate convention."""

    #: A 1590B measured across its drilled face: 1.9 mm under its 112.40 × 60.50
    #: backplate on both axes, which is ``2 · d · tan 2°`` at its 31 mm depth.
    FACE_DRAWN_1590B = (110.5, 58.6)
    #: 1590B3 (116.00 × 77.00) and 1590T (120.00 × 80.00) are the closest pair in
    #: the catalogue that is *not* one of the four inherently ambiguous ones,
    #: 4 mm apart. An outline halfway between them ties at 2 mm.
    TIED = (118.0, 78.5)

    def test_a_face_drawn_panel_is_refused_and_the_message_names_the_convention(self):
        """A failure that teaches the fix costs a re-run; a silent one costs a case."""
        _, match, diagnostics = IdentifyHammondFootprint().quantise(
            RawOutline(*self.FACE_DRAWN_1590B), ORIGIN
        )

        assert codes(diagnostics) == ["unknown-enclosure"]
        assert match is None
        assert "backplate" in diagnostics[0].message

    def test_no_tolerance_at_all_identifies_a_face_drawn_panel(self):
        """A face-drawn 1590B matches none at 1 899 999 nm and two at 1 900 000 nm.

        No tolerance can therefore identify it uniquely.
        """
        under = IdentifyHammondFootprint(tolerance_nm=Nanometre(1_899_999))
        at_it = IdentifyHammondFootprint(tolerance_nm=Nanometre(1_900_000))
        face = RawOutline(*self.FACE_DRAWN_1590B)

        _, no_match, refused = under.quantise(face, ORIGIN)
        assert no_match is None
        assert codes(refused) == ["unknown-enclosure"]

        _, still_none, tied = at_it.quantise(face, ORIGIN)
        assert still_none is None
        assert codes(tied) == ["ambiguous-enclosure"]
        assert tied[0].get("candidates") == "1590BS, 1590B, 1590B2"

    def test_the_default_tolerance_stays_under_the_wall_draft(self):
        """The bound the default is chosen against, stated as a number."""
        assert IdentifyHammondFootprint().tolerance_nm < 1_900_000

    def test_the_declared_case_message_names_the_convention_too(self):
        """The operator most likely to be reading ``unmatched-enclosure`` is the
        careful one who declared the *right* part and measured its face."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590B").quantise(
            RawOutline(*self.FACE_DRAWN_1590B), ORIGIN
        )

        assert codes(diagnostics) == ["unmatched-enclosure"]
        assert "backplate" in diagnostics[0].message


class TestAmbiguity:
    # 1590B3 (116.00 × 77.00) and 1590T (120.00 × 80.00) are 4 mm apart on the
    # wider axis. An outline halfway between them is within 2 mm of both, which
    # is the shape of fixture that reaches a tie the tolerance created rather
    # than one the catalogue already had.
    TIED = (118.0, 78.5)

    def test_an_ambiguous_tie_is_an_error_not_a_choice(self):
        outline, match, diagnostics = IdentifyHammondFootprint(
            tolerance_nm=Nanometre(2_000_000)
        ).quantise(RawOutline(*self.TIED), ORIGIN)

        assert codes(diagnostics) == ["ambiguous-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR
        assert match is None
        assert (outline.width_nm, outline.height_nm) == (118 * MM, 78_500_000)

    def test_the_tie_diagnostic_names_every_footprint_it_could_not_choose_between(self):
        """Naming one of them would be the guess this rule exists to refuse."""
        _, _, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(2_000_000)).quantise(
            RawOutline(*self.TIED), ORIGIN
        )

        assert diagnostics[0].get("footprints") == "116.000 × 77.000, 120.000 × 80.000"
        assert diagnostics[0].get("candidates") == "1590B3, 1590T"
        # The tolerance is the actionable half of this finding: it is the one
        # thing the operator can change to break the tie.
        assert diagnostics[0].get("tolerance_nm") == 2_000_000

    def test_the_same_outline_is_unambiguous_at_the_default_tolerance(self):
        """The tie is a property of the tolerance, not of the outline."""
        assert codes(
            IdentifyHammondFootprint().quantise(RawOutline(*self.TIED), ORIGIN)[2]
        ) == ["unknown-enclosure"]

    def test_the_footprints_no_artwork_can_tell_apart_are_exactly_these_four(self):
        """Exactly four footprint pairs tie at the default tolerance."""
        outlines = sorted(footprints())
        tolerance_nm = IdentifyHammondFootprint().tolerance_nm
        tied = {
            (footprints()[a], footprints()[b])
            for i, a in enumerate(outlines)
            for b in outlines[i + 1 :]
            if min(
                max(abs(a[0] - b[0]), abs(a[1] - b[1])),
                max(abs(a[0] - b[1]), abs(a[1] - b[0])),
            )
            <= 2 * tolerance_nm
        }

        assert len(outlines) == 26
        assert tied == {
            (("1590LLB",), ("1590LB",)),
            (("1590BS",), ("1590B", "1590B2")),
            (("1590KK",), ("1590K",)),
            (("1590D",), ("1590DD", "1590E")),
        }

    def test_no_other_pair_ties_at_the_default_tolerance(self):
        """Every other pair lies outside twice the default tolerance."""
        assert 2 * IdentifyHammondFootprint().tolerance_nm < 4 * MM

        assert codes(
            IdentifyHammondFootprint(tolerance_nm=Nanometre(2_000_000)).quantise(
                RawOutline(*self.TIED), ORIGIN
            )[2]
        ) == ["ambiguous-enclosure"]

        _, match, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(1_990_000)).quantise(
            RawOutline(*self.TIED), ORIGIN
        )
        assert match is None
        assert codes(diagnostics) == ["unknown-enclosure"]

    def test_the_tie_is_reported_in_size_order_whatever_order_the_catalogue_is_in(
        self, monkeypatch
    ):
        """The message must not reshuffle when an unrelated part is added."""
        monkeypatch.setattr(
            enclosure_stage,
            "footprints",
            lambda: {
                (120_000_000, 80_000_000): ("FAKE-T",),
                (116_000_000, 77_000_000): ("FAKE-B3",),
            },
        )
        _, _, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(2_000_000)).quantise(
            RawOutline(*self.TIED), ORIGIN
        )

        assert codes(diagnostics) == ["ambiguous-enclosure"]
        assert diagnostics[0].get("footprints") == "116.000 × 77.000, 120.000 × 80.000"
        assert diagnostics[0].get("candidates") == "FAKE-B3, FAKE-T"


class TestRotation:
    #: `UNAMBIGUOUS` turned 90°: a portrait 1590A.
    PORTRAIT = RawOutline(Millimetre(38.0), Millimetre(93.0))

    def test_a_portrait_panel_matches_its_landscape_catalogue_entry(self):
        outline, match, _ = IdentifyHammondFootprint().quantise(self.PORTRAIT, ORIGIN)

        assert match.rotated is True
        assert (outline.width_nm, outline.height_nm) == (38_500_000, 92_600_000)

    def test_a_rotated_match_records_the_catalogue_orientation_not_the_artworks(self):
        """The drawing says 1590A is 92.60 × 38.50. Transposing it here would make
        the identified part unfindable in the document it was identified from."""
        _, match, _ = IdentifyHammondFootprint().quantise(self.PORTRAIT, ORIGIN)

        assert (match.length_nm, match.width_nm) == A_FOOTPRINT
        assert match.candidates == ("1590A",)

    def test_a_landscape_panel_is_recorded_as_not_rotated(self):
        """Paired with the portrait case so neither hardcoded flag survives."""
        _, match, _ = IdentifyHammondFootprint().quantise(UNAMBIGUOUS, ORIGIN)
        assert match.rotated is False

    def test_a_square_footprint_is_not_a_rotation(self):
        """1590Y is 92 × 92, so both readings fit. A turn of no consequence is
        not a turn, and reporting one would put "rotated" on a drawing for a
        panel nobody rotated."""
        _, match, _ = IdentifyHammondFootprint().quantise(RawOutline(Millimetre(92.4), Millimetre(91.8)), ORIGIN)

        assert match.candidates == ("1590Y",)
        assert match.rotated is False

    def test_a_rotated_match_is_silent_too(self):
        assert IdentifyHammondFootprint().quantise(self.PORTRAIT, ORIGIN)[2] == ()


class TestDeclaredCase:
    """The 1590A panel, not the fixture, wherever a *single* match is needed."""

    def test_declaring_the_wrong_case_is_an_error(self):
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590BB").quantise(
            UNAMBIGUOUS, ORIGIN
        )

        assert codes(diagnostics) == ["wrong-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR

    def test_the_wrong_case_diagnostic_names_both_parts(self):
        """The operator needs to know what they asked for *and* what they drew;
        either alone leaves them re-deriving the other from the artwork."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590BB").quantise(
            UNAMBIGUOUS, ORIGIN
        )

        assert diagnostics[0].get("requested_part") == "1590BB"
        assert diagnostics[0].get("identified_parts") == "1590A"
        # And the footprint that identified them, so a consumer can show the
        # measurement that produced the disagreement rather than re-taking it.
        assert (
            diagnostics[0].get("length_nm"),
            diagnostics[0].get("width_nm"),
        ) == A_FOOTPRINT

    def test_the_wrong_case_message_prints_the_catalogues_own_precision(self):
        """``92.600 × 38.500``, not ``93 × 39``."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590BB").quantise(
            UNAMBIGUOUS, ORIGIN
        )

        assert "92.600 × 38.500 mm" in diagnostics[0].message

    def test_a_wrongly_declared_panel_is_still_identified_and_still_snapped(self):
        """The outline matched; only the declaration disagrees. Dropping the
        match would leave the report with nothing to name."""
        outline, match, _ = IdentifyHammondFootprint(expected_part="1590BB").quantise(
            UNAMBIGUOUS, ORIGIN
        )

        assert match.candidates == ("1590A",)
        assert match.selected_part == "1590BB"
        assert (outline.width_nm, outline.height_nm) == A_FOOTPRINT

    def test_a_correctly_declared_case_becomes_the_selected_part(self):
        """A footprint names candidates; only the operator can pick among them."""
        _, match, diagnostics = IdentifyHammondFootprint(expected_part="1590B2").quantise(
            FIXTURE, ORIGIN
        )

        assert match.selected_part == "1590B2"
        assert diagnostics == ()

    def test_nothing_is_selected_when_nothing_was_declared(self):
        """The artwork does not contain the height, so it cannot be inferred."""
        _, match, _ = IdentifyHammondFootprint().quantise(UNAMBIGUOUS, ORIGIN)
        assert match.selected_part is None

    def test_a_declared_case_is_matched_however_it_was_typed(self):
        _, match, diagnostics = IdentifyHammondFootprint(expected_part=" 1590b2 ").quantise(
            FIXTURE, ORIGIN
        )

        assert diagnostics == ()
        assert match.selected_part == "1590B2"

    def test_a_blank_declaration_is_no_declaration(self):
        """An empty ``--case`` must not become a part number nothing can match."""
        _, match, diagnostics = IdentifyHammondFootprint(expected_part="   ").quantise(
            UNAMBIGUOUS, ORIGIN
        )

        assert diagnostics == ()
        assert match.selected_part is None


class TestADeclarationIsCheckedOnEveryOutcome:
    """The declaration has to bite where the geometry *failed*, not only where it
    succeeded.
    """

    TIED = (118.0, 78.5)
    #: Larger than every footprint in the catalogue, on both axes.
    UNRECOGNISED = (300.0, 300.0)

    def test_a_declaration_with_no_outline_to_check_it_against_is_refused(self):
        """Silence here would be indistinguishable from a confirmed declaration."""
        outline, match, diagnostics = IdentifyHammondFootprint(
            expected_part="1590B"
        ).quantise(None, ORIGIN)

        assert codes(diagnostics) == ["unverifiable-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR
        assert outline is None
        assert match is None

    def test_no_outline_and_no_declaration_is_still_left_alone(self):
        """The undeclared twin: nothing was claimed, so nothing is checked."""
        assert IdentifyHammondFootprint().quantise(None, ORIGIN) == (None, None, ())

    def test_the_unverifiable_diagnostic_names_the_part_and_the_size_it_would_be(self):
        """A consumer must be able to say what the panel *should* measure
        without going back to the catalogue the quantiser has already read."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part=" 1590b ").quantise(
            None, ORIGIN
        )

        assert diagnostics[0].get("requested_part") == "1590B"
        assert (
            diagnostics[0].get("expected_length_nm"),
            diagnostics[0].get("expected_width_nm"),
        ) == B_FOOTPRINT
        assert diagnostics[0].get("catalogue") == "Hammond 1590"

    def test_a_declaration_the_artwork_matches_nothing_for_is_refused(self):
        """A declared part is refused when the artwork matches no footprint."""
        outline, match, diagnostics = IdentifyHammondFootprint(
            expected_part="1590BB"
        ).quantise(RawOutline(*self.UNRECOGNISED), ORIGIN)

        assert codes(diagnostics) == ["unmatched-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR
        assert match is None
        assert (outline.width_nm, outline.height_nm) == (300 * MM, 300 * MM)

    def test_an_unrecognised_outline_nobody_declared_stays_a_warning(self):
        """The undeclared twin, and the reason the new code is not
        ``unknown-enclosure`` at a second severity."""
        _, _, diagnostics = IdentifyHammondFootprint().quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )

        assert codes(diagnostics) == ["unknown-enclosure"]
        assert diagnostics[0].severity is Severity.WARNING

    def test_the_unmatched_diagnostic_carries_the_declaration_and_the_measurement(self):
        """Both halves of the disagreement, so the consumer re-measures nothing."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590BB").quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )
        diagnostic = diagnostics[0]

        assert diagnostic.get("requested_part") == "1590BB"
        assert (
            diagnostic.get("expected_length_nm"),
            diagnostic.get("expected_width_nm"),
        ) == (119_500_000, 94_000_000)
        assert (diagnostic.get("width_nm"), diagnostic.get("height_nm")) == (
            300 * MM,
            300 * MM,
        )
        assert diagnostic.get("tolerance_nm") == 1_500_000
        assert diagnostic.get("catalogue") == "Hammond 1590"
        assert diagnostic.get("footprints") == ""
        assert diagnostic.get("candidates") == ""

    def test_a_declaration_breaks_a_tie_the_catalogue_cannot(self):
        """Two footprints fit; the operator already said which one it is."""
        outline, match, diagnostics = IdentifyHammondFootprint(
            expected_part="1590T", tolerance_nm=Nanometre(2_000_000)
        ).quantise(RawOutline(*self.TIED), ORIGIN)

        assert diagnostics == ()
        assert (match.length_nm, match.width_nm) == (120 * MM, 80 * MM)
        assert match.selected_part == "1590T"
        assert (outline.width_nm, outline.height_nm) == (120 * MM, 80 * MM)
        assert outline.raw == RawOutline(*self.TIED)

    def test_a_tie_the_declaration_does_not_resolve_is_refused(self):
        """Declared 1590B; the outline is within tolerance of two footprints and
        neither of them is 1590B. Naming either would be the guess."""
        outline, match, diagnostics = IdentifyHammondFootprint(
            expected_part="1590B", tolerance_nm=Nanometre(2_000_000)
        ).quantise(RawOutline(*self.TIED), ORIGIN)

        assert codes(diagnostics) == ["unmatched-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR
        assert diagnostics[0].get("requested_part") == "1590B"
        assert diagnostics[0].get("footprints") == "116.000 × 77.000, 120.000 × 80.000"
        assert diagnostics[0].get("candidates") == "1590B3, 1590T"
        assert match is None
        assert (outline.width_nm, outline.height_nm) == (118 * MM, 78_500_000)

    def test_the_tie_message_names_the_parts_the_case_could_be_declared_as(self):
        """The advice is "declare the case", and a case is a part number."""
        _, _, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(2_000_000)).quantise(
            RawOutline(*self.TIED), ORIGIN
        )

        assert "1590B3, 1590T" in diagnostics[0].message
        assert "declare the case" in diagnostics[0].message

    def test_an_undeclared_tie_is_still_ambiguous_and_still_asks_for_a_case(self):
        """The undeclared twin. ``ambiguous-enclosure`` keeps its one meaning —
        more than one footprint fits and nothing was said to choose between
        them — which is why the advice in its message is still sound."""
        _, _, diagnostics = IdentifyHammondFootprint(tolerance_nm=Nanometre(2_000_000)).quantise(
            RawOutline(*self.TIED), ORIGIN
        )

        assert codes(diagnostics) == ["ambiguous-enclosure"]
        assert "declare the case" in diagnostics[0].message

    def test_a_declared_part_no_catalogue_holds_invents_no_footprint_for_it(self):
        """The CLI refuses this as a usage error before the file is opened, but
        a library caller can hand the quantiser anything, and a payload key
        filled in with a plausible number would be worse than an absent one."""
        _, _, diagnostics = IdentifyHammondFootprint(expected_part="1590ZZ").quantise(
            RawOutline(*self.UNRECOGNISED), ORIGIN
        )

        assert diagnostics[0].code == "unmatched-enclosure"
        assert diagnostics[0].get("requested_part") == "1590ZZ"
        assert diagnostics[0].get("expected_length_nm") is None
        assert diagnostics[0].get("expected_width_nm") is None


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
        """A finish or flange suffix is left alone."""
        assert normalize_part_name("1590BBBK") == "1590BBBK"
        assert normalize_part_name("1590WF") == "1590WF"


class TestIdentifyHammondFootprintDescribe:
    def test_it_reports_the_tolerance_and_the_catalogue_it_searched(self):
        run = IdentifyHammondFootprint(tolerance_nm=Nanometre(750_000)).describe()

        assert run.name == "identify-enclosure"
        assert run.get("tolerance_nm") == 750_000
        assert run.get("catalogue") == "Hammond 1590"

    def test_it_reports_the_declared_part_as_the_quantiser_resolved_it(self):
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
    def test_the_outline_still_quotes_what_the_artwork_said(self):
        """The outline still quotes what the artwork said."""
        outline, _, _ = IdentifyHammondFootprint("1590B").quantise(
            FIXTURE, (306.0, 170.0)
        )

        assert (outline.width_nm, outline.height_nm) == B_FOOTPRINT
        assert outline.raw == FIXTURE

    def test_the_measurement_is_the_artworks_float_not_a_round_trip_of_the_answer(self):
        """``raw`` is what the source measured, and the distinction has a floor below a
        nanometre.
        """
        outline, _, _ = IdentifyHammondFootprint().quantise(
            RawOutline(Millimetre(113.0000004), Millimetre(60.0)), ORIGIN
        )

        assert outline.raw == RawOutline(Millimetre(113.0000004), Millimetre(60.0))

    def test_the_snap_keeps_the_outlines_source_space_centre(self):
        """``centre_x_nm``/``centre_y_nm`` say where the outline sat on the page.
        A fresh construction would drop them back to the origin."""
        outline, _, _ = IdentifyHammondFootprint("1590B").quantise(
            FIXTURE, (306.0, 170.0)
        )

        assert outline.width_nm == 112_400_000, "the outline was never snapped at all"
        assert (outline.centre_x_nm, outline.centre_y_nm) == (306 * MM, 170 * MM)

    def test_an_outline_that_already_measures_a_footprint_is_not_promoted(self):
        """92.60 × 38.50 is already a footprint, so nothing moves — and the
        measurement must still be recorded as a measurement rather than
        acquiring the catalogue's authority by coincidence."""
        outline, match, diagnostics = IdentifyHammondFootprint().quantise(
            RawOutline(Millimetre(92.6), Millimetre(38.5)), ORIGIN
        )

        assert (outline.width_nm, outline.height_nm) == A_FOOTPRINT
        assert outline.raw == RawOutline(Millimetre(92.6), Millimetre(38.5))
        assert match.candidates == ("1590A",)
        assert diagnostics == ()


class TestTheFixturePanelNeedsADeclaredCase:
    """The fixture's tied footprint requires a declared case."""

    def test_undeclared_it_is_an_error_naming_both_enclosures(self):
        outline, match, diagnostics = IdentifyHammondFootprint().quantise(FIXTURE, ORIGIN)

        assert codes(diagnostics) == ["ambiguous-enclosure"]
        assert diagnostics[0].severity is Severity.ERROR
        assert match is None
        assert diagnostics[0].get("footprints") == "112.000 × 60.500, 112.400 × 60.500"
        assert diagnostics[0].get("candidates") == "1590BS, 1590B, 1590B2"
        # The frame survives the refusal, as the measurement, because the CLI
        # reports on a document rather than on an exception.
        assert (outline.width_nm, outline.height_nm) == (113_000_000, 60_000_000)

    def test_declaring_the_case_resolves_it_and_says_nothing(self):
        outline, match, diagnostics = IdentifyHammondFootprint("1590B").quantise(
            FIXTURE, ORIGIN
        )

        assert diagnostics == ()
        assert match.selected_part == "1590B"
        assert (match.length_nm, match.width_nm) == B_FOOTPRINT
        assert (outline.width_nm, outline.height_nm) == B_FOOTPRINT

    def test_declaring_the_other_side_of_the_tie_resolves_it_differently(self):
        """The declaration is knowledge, not a rubber stamp: 1590BS is the other real
        enclosure this outline fits, and it snaps to a different frame.
        """
        outline, match, diagnostics = IdentifyHammondFootprint("1590BS").quantise(
            FIXTURE, ORIGIN
        )

        assert diagnostics == ()
        assert match.candidates == ("1590BS",)
        assert (outline.width_nm, outline.height_nm) == (112_000_000, 60_500_000)
