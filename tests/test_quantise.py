"""Tests for ``aidrill.quantise`` — the phase, not the three quantisers in it.

What each quantiser answers is pinned in ``test_enclosure.py``,
``test_diameters.py`` and ``test_snap.py``. What is pinned here is everything
that only exists because they are composed: the order they run in, that an
enclosure ERROR stops the run before a hole is touched, that a hole's identity
survives the assembly, that the two once-per-run findings are not lost, and that
the provenance records what actually happened rather than what was configured.

One test at the end opens a file. Every other test in the tree builds its
measurements by hand, which is right for a phase of pure functions and wrong for
exactly one claim: that ``grid-ambiguous`` fires on *artwork*. A hand-built
``RawHole(0.125, ...)`` states a midpoint, where a drawn circle only
approximates one.

Diagnostics are matched on ``code``, never on ``message``.
"""

from __future__ import annotations

import pytest

from aidrill.model import (
    Diagnostic,
    RawDrillData,
    RawHole,
    RawOutline,
    Severity,
    SourceInfo,
)
from aidrill.pipeline import (
    DRILL_STANDARDS,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from aidrill.pipeline.enclosure import DEFAULT_TOLERANCE_NM
from aidrill.quantise import quantise
from aidrill.sources import AiPdfSource
from tests.conftest import build_pdf, circle_ops

#: The fixture panel's own measurement: 113.000 × 60.000, which the catalogue
#: calls a 112 × 61 mm 1590B. Every test that wants a panel the enclosure
#: quantiser recognises uses this one.
MEASURED = RawOutline(113.0, 60.0)


def read(
    *holes: RawHole,
    reference: RawOutline | None = MEASURED,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> RawDrillData:
    """One source read, in the float millimetres a source answers in."""
    return RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=reference,
        centre=(56.5, 30.0),
        holes=holes,
        diagnostics=diagnostics,
    )


def phase(raw: RawDrillData, **overrides):
    """``quantise`` with the CLI's defaults, unless a test names another."""
    quantisers = {
        "enclosure": IdentifyHammondFootprint(),
        "diameters": SnapDiametersToDrillTable(),
        "positions": SnapPositions(250_000),
    }
    quantisers.update(overrides)
    return quantise(raw, **quantisers)


def codes(data) -> list[str]:
    return [d.code for d in data.diagnostics]


# ---------------------------------------------------------------------------
# the order, which is the whole reason this is one function
# ---------------------------------------------------------------------------


class Watched:
    """Quantisers that write their own name into a shared log when reached.

    Subclasses rather than stand-ins, so what is observed is the real
    composition: a stub that answered plausibly would let the phase reorder the
    two whose answers actually depend on each other and still pass.
    """

    def __init__(self) -> None:
        self.log: list[str] = []

    def enclosure(
        self,
        expected_part: str | None = None,
        tolerance_nm: int = DEFAULT_TOLERANCE_NM,
    ) -> IdentifyHammondFootprint:
        log = self.log

        class WatchedEnclosure(IdentifyHammondFootprint):
            def quantise(self, outline, centre):
                log.append("enclosure")
                return super().quantise(outline, centre)

        return WatchedEnclosure(expected_part, tolerance_nm)

    def diameters(self) -> SnapDiametersToDrillTable:
        log = self.log

        class WatchedDiameters(SnapDiametersToDrillTable):
            def quantise(self, hole):
                log.append(f"diameters {hole.index}")
                return super().quantise(hole)

        return WatchedDiameters()

    def positions(self, grid_nm: int = 250_000) -> SnapPositions:
        log = self.log

        class WatchedPositions(SnapPositions):
            def quantise(self, hole):
                log.append(f"grid {hole.index}")
                return super().quantise(hole)

        return WatchedPositions(grid_nm)


def test_the_phase_runs_enclosure_then_diameters_then_grid():
    """The one deliberately literal statement of the order.

    Order is the single thing none of the three could declare for itself, and
    unlike the pipeline's it is not the caller's to choose either — so this is
    where it is said. One hole, so the sequence is the whole answer: any swap of
    the three reads differently here.
    """
    watched = Watched()

    phase(
        read(RawHole(-20.0, 18.0, 7.0, 4)),
        enclosure=watched.enclosure(),
        diameters=watched.diameters(),
        positions=watched.positions(),
    )

    assert watched.log == ["enclosure", "diameters 4", "grid 4"]


def test_a_hole_the_drill_table_refuses_never_reaches_the_grid():
    """Why diameters runs before the grid, made observable.

    ``unknown-diameter`` is an ERROR that *drops* the hole, so a run that
    snapped it to the grid first would have positioned a hole that appears in no
    artifact. Hole 9 is a 30 mm cut-out no bit makes; holes 4 and 1 are real.
    """
    watched = Watched()

    out = phase(
        read(
            RawHole(-20.0, 18.0, 7.0, 4),
            RawHole(0.0, 18.0, 30.0, 9),
            RawHole(20.0, 18.0, 5.0, 1),
        ),
        diameters=watched.diameters(),
        positions=watched.positions(),
    )

    assert watched.log == [
        "diameters 4",
        "grid 4",
        "diameters 9",  # refused, and no "grid 9" after it
        "diameters 1",
        "grid 1",
    ]
    assert [hole.index for hole in out.holes] == [4, 1]
    assert codes(out) == ["unknown-diameter"]


# ---------------------------------------------------------------------------
# aborting, which a stage could not have done at all
# ---------------------------------------------------------------------------


def test_a_run_that_stopped_records_only_what_ran():
    """A ``StageRun`` says what a quantiser *did*. A phase that recorded all
    three regardless would tell a consumer the drill table and the grid had been
    applied to a document holding no holes at all."""
    out = phase(
        read(RawHole(-20.0, 18.0, 7.0, 4)),
        enclosure=IdentifyHammondFootprint("1590BB"),
    )

    assert [run.name for run in out.processing] == ["identify-enclosure"]


@pytest.mark.parametrize(
    "declared, tolerance_nm, reference, code",
    [
        ("1590BB", DEFAULT_TOLERANCE_NM, MEASURED, "wrong-enclosure"),
        ("1590B", DEFAULT_TOLERANCE_NM, None, "unverifiable-enclosure"),
        ("1590B", DEFAULT_TOLERANCE_NM, RawOutline(200.0, 100.0), "unmatched-enclosure"),
        (None, 2_000_000, RawOutline(118.0, 78.5), "ambiguous-enclosure"),
    ],
)
def test_every_enclosure_error_stops_the_run(declared, tolerance_nm, reference, code):
    """All four of them, because they arrive by four different paths.

    The first three are the ways a *declaration* can fail, and the fourth is not
    a fourth spelling of them: ``ambiguous-enclosure`` is the undeclared path —
    118 × 78.5 mm sits within 2 mm of both 1590B3 and 1590T, and with no
    ``--case`` there is nothing to break the tie — so it is the one that reaches
    the abort with ``expected_part`` unset. A phase that returned early on a set
    of *codes* rather than on the severity would let exactly this one through,
    and a matrix of the three declaration errors would not notice.

    Asserted on the *work*, not merely on the result: a phase that quantised
    every hole and then threw them away would produce identical data and would
    still be wrong about a panel with two thousand circles on it. Hence two
    holes, both of which the drill table and the grid would have had something
    to say about.
    """
    watched = Watched()

    out = phase(
        read(
            RawHole(-20.0, 18.0, 7.0, 4),
            RawHole(20.0, 18.0, 5.0, 1),
            reference=reference,
        ),
        enclosure=watched.enclosure(declared, tolerance_nm),
        diameters=watched.diameters(),
        positions=watched.positions(),
    )

    assert watched.log == ["enclosure"]
    assert codes(out) == [code]
    assert out.holes == ()
    assert out.worst_severity is Severity.ERROR


def test_an_outline_a_hair_outside_the_tolerance_stops_the_run_too():
    """The pre-rounding counterexample, carried to the consequence that matters.

    113.5000004 mm is 113 500 000.4 nm, four tenths of a nanometre outside a
    1 500 000 nm tolerance around 1590B's 112 mm. ``test_enclosure.py`` pins the
    quantiser's answer; what a returned tuple cannot carry is what that answer
    costs — the run's worst severity is ERROR, which is the single thing the CLI
    reads to withhold every artifact, and no hole was quantised for it.
    """
    out = phase(
        read(RawHole(-20.0, 18.0, 7.0, 4), reference=RawOutline(113.5000004, 61.0)),
        enclosure=IdentifyHammondFootprint("1590B"),
    )

    assert codes(out) == ["unmatched-enclosure"]
    assert out.worst_severity is Severity.ERROR
    assert out.holes == ()
    assert [run.name for run in out.processing] == ["identify-enclosure"]


def test_an_enclosure_warning_does_not_stop_the_run():
    """``unknown-enclosure`` is a WARNING about *our* catalogue, not about the
    panel: the outline keeps the size it was drawn at and the artifacts are
    still written, so the holes must still be quantised."""
    out = phase(
        read(RawHole(-20.0, 18.0, 7.0, 4), reference=RawOutline(200.0, 100.0))
    )

    assert codes(out) == ["unknown-enclosure"]
    assert [hole.index for hole in out.holes] == [4]
    assert (out.reference.width_nm, out.reference.height_nm) == (200_000_000, 100_000_000)


def test_a_dropped_hole_does_not_stop_the_run():
    """``unknown-diameter`` withholds the artifacts, not the work. Every other
    hole is still quantised, because the report has to name all of them."""
    out = phase(
        read(
            RawHole(-20.0, 18.0, 30.0, 4),
            RawHole(0.0, 18.0, 29.0, 1),
            RawHole(20.0, 18.0, 5.0, 9),
        )
    )

    assert codes(out) == ["unknown-diameter", "unknown-diameter"]
    assert [hole.index for hole in out.holes] == [9]


def test_a_diameter_a_hair_outside_the_tolerance_costs_the_run_its_artifacts():
    """The drill table's half of the same counterexample, at the phase.

    25.2500004 mm is 250 000.4 nm from the largest metric bit, four tenths of a
    nanometre outside the matching bound; ``test_diameters.py`` pins the refusal
    itself. Here is what it means for the panel: hole 4 is gone from a document
    that still carries hole 1, and the run's worst severity is ERROR — so the
    drill file the machinist would otherwise receive, one hole short and
    perfectly well-formed, is never written.
    """
    out = phase(
        read(RawHole(-20.0, 18.0, 25.2500004, 4), RawHole(20.0, 18.0, 7.0, 1))
    )

    assert codes(out) == ["unknown-diameter"]
    assert out.worst_severity is Severity.ERROR
    assert [hole.index for hole in out.holes] == [1]


# ---------------------------------------------------------------------------
# identity, which the assembly is the one place that can break
# ---------------------------------------------------------------------------


def test_every_finished_hole_keeps_the_number_its_measurement_had():
    """4, 1, 9 — deliberately neither ordered nor equal to a list position.

    ``Hole.__post_init__`` refuses a hole whose two identities differ, so this
    cannot be broken quietly; it is asserted anyway because that guard is the
    only thing standing between an assembly that renumbers and a diagnostic
    naming a different hole than the drawing's balloon does. Numbered 0, 1, 2 the
    assertion would pass just as happily for an implementation that enumerated.
    """
    out = phase(
        read(
            RawHole(-20.0, 18.0, 7.0, 4),
            RawHole(0.0, 18.0, 7.0, 1),
            RawHole(20.0, 18.0, 5.0, 9),
        )
    )

    assert [hole.index for hole in out.holes] == [4, 1, 9]
    assert [hole.raw.index for hole in out.holes] == [4, 1, 9]


def test_the_measurement_travels_with_the_hole_it_was_taken_from():
    """``raw`` is the artwork's own number, kept so a residual can be recomputed
    rather than remembered. Each hole must carry *its* measurement, which a
    fixture of identical circles could not show."""
    out = phase(
        read(RawHole(-19.9906, 18.0021, 6.9998, 4), RawHole(20.0031, -18.7, 5.0002, 1))
    )

    assert [hole.raw.x for hole in out.holes] == [-19.9906, 20.0031]
    assert [(hole.x_nm, hole.y_nm) for hole in out.holes] == [
        (-20_000_000, 18_000_000),
        (20_000_000, -18_750_000),
    ]
    assert [hole.diameter_nm for hole in out.holes] == [7_000_000, 5_000_000]


# ---------------------------------------------------------------------------
# findings: the source's, the once-per-run one, and the per-hole ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hole_count", [0, 1, 3])
def test_a_clamped_grid_is_reported_exactly_once(hole_count):
    """The finding the phase is the only thing positioned to raise.

    ``SnapPositions`` sets it in its constructor, because a pitch below the
    floor is a fact about the configuration and not about any hole. Returned per
    hole it would repeat for every circle on the panel and vanish entirely on a
    panel with none — which is the run where the operator most needs telling
    that the grid they typed is not the one their holes were snapped to. Hence
    the zero case, which is the one that actually falsifies the alternative.
    """
    holes = tuple(RawHole(float(i), 0.0, 7.0, index=i + 4) for i in range(hole_count))

    out = phase(read(*holes), positions=SnapPositions(0))

    assert codes(out).count("grid-too-fine") == 1
    assert len(out.holes) == hole_count


def test_an_unclamped_grid_says_nothing():
    """The clamp finding is news, and a run that reports it on every panel is a
    run that has trained the operator to skim past it."""
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4)), positions=SnapPositions(250_000))
    assert codes(out) == []


def test_a_panel_that_ties_too_often_is_reported_once_and_after_the_holes():
    """The phase's other once-per-run finding, and the one that needs the loop.

    The clamp is known before any hole is looked at. This one cannot be: "half
    the holes" is not a fact about any hole, so it is collected after the loop
    rather than before it. Its place in the report is the reading order — the
    per-hole findings, then the conclusion drawn over all of them.

    Both holes are half a pitch out, so both are off-grid as well; a tie is
    always a move worth reporting on its own, and the two findings are about
    different things.
    """
    out = phase(read(RawHole(-20.125, 18.0, 7.0, 4), RawHole(0.125, 18.0, 7.0, 1)))

    assert codes(out) == ["off-grid", "off-grid", "grid-ambiguous"]


def test_a_panel_drawn_on_the_declared_grid_is_not_reported_as_ambiguous():
    """The finding is news, and a run that raises it on every panel has trained
    the operator to skim past it."""
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4), RawHole(0.25, 18.0, 7.0, 1)))

    assert codes(out) == []


def test_a_panel_with_no_holes_is_never_ambiguous():
    """``2 * 0 >= 0`` is true, so silence here is a guard and not an accident.

    The zero case is the one that falsifies a threshold written as a ratio, and
    a warning about a panel with no circles on it is noise in front of an
    operator with nothing to fix.
    """
    out = phase(read())

    assert codes(out) == []


def test_a_hole_the_drill_table_dropped_counts_towards_neither_side():
    """``review_panel`` is handed the finished holes, and a dropped one is not
    among them.

    Hole 9 is a 30 mm cut-out no bit makes, so the grid never saw it and it has
    no residual to be tied or untied by. Counting it in the total would dilute
    the evidence with a hole nothing measured: one tie in the two holes that
    were quantised is half the panel and warns, while one in three would not.
    """
    out = phase(
        read(
            RawHole(-20.125, 18.0, 7.0, 4),
            RawHole(0.0, 18.0, 30.0, 9),
            RawHole(0.25, 18.0, 7.0, 1),
        )
    )

    assert "grid-ambiguous" in codes(out)


def test_the_sources_own_findings_survive_the_phase():
    """A source reports what it could not read — a reference layer with no
    outline in it, a layer it had to guess about — and those findings are about
    the read rather than about anything quantised. Losing them here would leave
    the run with no record that the frame is page-relative.
    """
    prior = Diagnostic.warning("no-reference-outline", "the reference layer held no path")

    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4), diagnostics=(prior,)))

    assert out.diagnostics[0] is prior


def test_the_sources_findings_come_before_the_phases_own():
    """Order is the reading order of the report, and the read happened first.

    A source finding shuffled in among the per-hole ones would have the operator
    reading about hole 4's diameter before being told the panel has no frame.
    """
    prior = Diagnostic.warning("no-reference-outline", "the reference layer held no path")

    out = phase(
        read(RawHole(-20.0, 18.0, 30.0, 4), diagnostics=(prior,), reference=None),
        positions=SnapPositions(0),
    )

    assert codes(out) == ["no-reference-outline", "grid-too-fine", "unknown-diameter"]


def test_a_findings_hole_index_names_the_measurement_it_was_taken_from():
    """The refusal is written by the quantiser that held the measurement, and
    the drill file numbers what survived — so the two agree only if the phase
    hands the measurement's own number over rather than a position."""
    out = phase(
        read(RawHole(-20.0, 18.0, 7.0, 4), RawHole(0.0, 18.0, 30.0, 9))
    )

    assert out.diagnostics[0].get("hole_index") == 9


# ---------------------------------------------------------------------------
# the frame and the conclusion
# ---------------------------------------------------------------------------


def test_the_outline_is_snapped_to_the_catalogue_and_the_measurement_is_kept():
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4)))

    assert (out.reference.width_nm, out.reference.height_nm) == (112_000_000, 61_000_000)
    assert (out.reference.raw.width, out.reference.raw.height) == (113.0, 60.0)
    assert (out.reference.centre_x_nm, out.reference.centre_y_nm) == (56_500_000, 30_000_000)


def test_the_identified_footprint_reaches_the_document():
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4)))

    assert out.enclosure.candidates == ("1590B", "1590B2", "1590BS")
    assert (out.enclosure.length_nm, out.enclosure.width_nm) == (112_000_000, 61_000_000)
    assert out.enclosure.selected_part is None


def test_a_panel_with_no_reference_layer_is_quantised_all_the_same():
    """The source has already reported the absence; the phase adds nothing and
    refuses nothing. Positions are page-relative and the holes still need bits.
    """
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4), reference=None))

    assert out.reference is None
    assert out.enclosure is None
    assert codes(out) == []
    assert [hole.diameter_nm for hole in out.holes] == [7_000_000]


def test_the_read_that_produced_the_document_is_carried_over():
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4)))
    assert out.source == SourceInfo(path="panel.ai", drill_layer="Drill")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def test_the_phase_records_all_three_quantisers_in_the_order_they_ran():
    out = phase(read(RawHole(-20.0, 18.0, 7.0, 4)))

    assert [run.name for run in out.processing] == [
        "identify-enclosure",
        "snap-diameters",
        "snap",
    ]


def test_the_record_is_the_effective_configuration_not_the_arguments():
    """The drawing's title block reads the pitch from here, so a clamped grid
    must be recorded as the pitch the holes were really snapped to. Recording
    the requested one would stamp a sheet with a grid no hole ever met."""
    out = phase(
        read(RawHole(-20.0, 18.0, 7.0, 4)),
        diameters=SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]),
        positions=SnapPositions(0),
    )

    assert out.last_run("snap").get("grid_nm") == 1_000
    assert out.last_run("snap").get("warn_over_nm") == 250
    assert out.last_run("snap-diameters").get("standard") == "fractional"
    assert out.last_run("identify-enclosure").get("catalogue") == "Hammond 1590"


def test_a_hole_less_panel_still_records_every_quantiser():
    """Nothing was quantised and all three still ran: a consumer must be able to
    tell a panel with no circles from a run that never reached the drill table.
    """
    out = phase(read())

    assert out.holes == ()
    assert [run.name for run in out.processing] == [
        "identify-enclosure",
        "snap-diameters",
        "snap",
    ]


# ---------------------------------------------------------------------------
# the same finding, on artwork rather than on a fixture
# ---------------------------------------------------------------------------


def pt_from_mm(mm: float) -> float:
    """Millimetres to PDF user-space points, the way a drawing tool would.

    The fixture below is specified in the millimetres a designer would type and
    converted here, rather than written as points chosen to come back as round
    millimetres. That is the whole point of it: what a designer means and what
    survives the page are different numbers.
    """
    return mm * 72 / 25.4


def test_artwork_drawn_on_half_the_declared_pitch_is_reported_as_ambiguous(tmp_path):
    """The one test here that opens a file, and the only kind that can prove it.

    A circle drawn 10.25 mm off centre leaves ``AiPdfSource`` as
    10.249999999999993, because the PDF operands, the CTM, the Bézier centroid
    and the frame subtraction are all binary float before anything decimal
    happens. An exact test on the *measurement* therefore never fires, and this
    diagnostic would be dead code on every real panel while passing every
    hand-built fixture in the file above.

    Reading the *residual* sidesteps it: the residual is measured against
    ``nm_from_mm`` of the measurement, so the nanometre boundary supplies a
    ±0.5 nm window implicitly — inherited from a boundary the codebase already
    has rather than a constant anybody chose. 10.249999999999993 mm is
    10 250 000 nm, and the tie is exact again.

    The panel is a 1590B drawn on 0.25 mm and the run declares 0.5 mm, which is
    the mistake the finding exists for: every hole lands on a midpoint, and
    every one of them is snapped anyway.
    """
    width, height = pt_from_mm(112.0), pt_from_mm(61.0)
    centre_x, centre_y = 10 + width / 2, 10 + height / 2
    offsets_mm = ((-10.25, 0.0), (0.25, 5.25), (10.25, -5.25))
    pdf = build_pdf(
        tmp_path / "half-pitch.pdf",
        {
            "Background": f"10 10 {width} {height} re f",
            "Drill": " ".join(
                circle_ops(
                    centre_x + pt_from_mm(x),
                    centre_y + pt_from_mm(y),
                    pt_from_mm(3.5),
                )
                for x, y in offsets_mm
            ),
        },
    )

    out = quantise(
        AiPdfSource(pdf).read(),
        enclosure=IdentifyHammondFootprint(),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(500_000),
    )

    assert codes(out) == ["off-grid", "off-grid", "off-grid", "grid-ambiguous"]
    ambiguous = out.diagnostics[-1]
    assert ambiguous.get("tied_indices") == (0, 1, 2)

    # The claim the fixture exists for: the artwork did not survive as the
    # midpoint it was drawn at, and the residual is one anyway.
    assert out.holes[2].raw.x != 10.25
    assert [hole.residual_nm[0] for hole in out.holes] == [250_000, -250_000, -250_000]
