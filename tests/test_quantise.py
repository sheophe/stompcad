"""Tests for raw-measurement quantisation and diagnostic propagation."""

from __future__ import annotations

from typing import Any

import pytest

from aidrill.model import (
    Diagnostic,
    DrillData,
    RawDrillData,
    RawHole,
    RawOutline,
    Severity,
    SourceInfo,
)
from aidrill.pipeline import (
    DRILL_STANDARDS,
    IdentifyHammondFootprint,
    ReviewGridTies,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from aidrill.pipeline.enclosure import DEFAULT_TOLERANCE_NM
from aidrill.quantise import quantise
from aidrill.sources import AiPdfSource
from aidrill.units import Millimetre, Nanometre
from tests.conftest import build_pdf, circle_ops

#: The fixture panel's own measurement: 113.000 × 60.000, which is within
#: tolerance of both 1590BS (112.00 × 60.50) and 1590B/1590B2 (112.40 × 60.50).
#: Every test that wants a panel the enclosure quantiser recognises uses this
#: one — together with `DECLARED` below, because on its own it is a tie.
MEASURED = RawOutline(Millimetre(113.0), Millimetre(60.0))

#: The case `MEASURED` needs declaring. Two real enclosures fit that outline and
#: nothing in the artwork chooses between them, so the phase's default quantiser
#: declares one: an undeclared run raises ``ambiguous-enclosure``, which is an
#: ERROR, and every test here would be testing the abort path instead of the one
#: it names. That behaviour is not incidental to these tests, so it is pinned
#: directly in ``test_enclosure.py`` rather than left to be inferred from this.
DECLARED = "1590B"


def read(
    *holes: RawHole,
    reference: RawOutline | None = MEASURED,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> RawDrillData:
    """One source read, in the float millimetres a source answers in."""
    return RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=reference,
        centre=(Millimetre(56.5), Millimetre(30.0)),
        holes=holes,
        diagnostics=diagnostics,
    )


def phase(raw: RawDrillData, **overrides: Any) -> DrillData:
    """``quantise`` with the CLI's defaults, unless a test names another."""
    quantisers: dict[str, Any] = {
        "enclosure": IdentifyHammondFootprint(DECLARED),
        "diameters": SnapDiametersToDrillTable(),
        "positions": SnapPositions(Nanometre(250_000)),
    }
    quantisers.update(overrides)
    return quantise(raw, **quantisers)


def codes(data) -> list[str]:
    return [d.code for d in data.diagnostics]


# ---------------------------------------------------------------------------
# the order, which is the whole reason this is one function
# ---------------------------------------------------------------------------


class Watched:
    """Quantisers that write their own name into a shared log when reached."""

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

        return WatchedEnclosure(expected_part, Nanometre(tolerance_nm))

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

        return WatchedPositions(Nanometre(grid_nm))


def test_the_phase_runs_enclosure_then_diameters_then_grid():
    """The phase runs enclosure, diameters and grid in order.

    One hole makes every permutation observable in the shared log.
    """
    watched = Watched()

    phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)),
        enclosure=watched.enclosure(DECLARED),
        diameters=watched.diameters(),
        positions=watched.positions(),
    )

    assert watched.log == ["enclosure", "diameters 4", "grid 4"]


def test_a_hole_the_drill_table_refuses_never_reaches_the_grid():
    """A hole rejected by diameter quantisation never reaches grid quantisation."""
    watched = Watched()

    out = phase(
        read(
            RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4),
            RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(30.0), 9),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0), 1),
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
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)),
        enclosure=IdentifyHammondFootprint("1590BB"),
    )

    assert [run.name for run in out.processing] == ["identify-enclosure"]


@pytest.mark.parametrize(
    "declared, tolerance_nm, reference, code",
    [
        # 1590Y's own 92 × 92, not the fixture's outline: ``wrong-enclosure``
        # needs the panel to be *identified* and the declaration to disagree, so
        # it is reachable only from a footprint nothing else is near.
        ("1590BB", DEFAULT_TOLERANCE_NM, RawOutline(Millimetre(92.4), Millimetre(91.8)), "wrong-enclosure"),
        ("1590B", DEFAULT_TOLERANCE_NM, None, "unverifiable-enclosure"),
        ("1590B", DEFAULT_TOLERANCE_NM, RawOutline(Millimetre(200.0), Millimetre(100.0)), "unmatched-enclosure"),
        (None, 2_000_000, RawOutline(Millimetre(118.0), Millimetre(78.5)), "ambiguous-enclosure"),
    ],
)
def test_every_enclosure_error_stops_the_run(declared, tolerance_nm, reference, code):
    """All four of them, because they arrive by four different paths."""
    watched = Watched()

    out = phase(
        read(
            RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0), 1),
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
    """The pre-rounding counterexample, carried to the consequence that matters."""
    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), reference=RawOutline(Millimetre(113.9000004), Millimetre(60.5))),
        enclosure=IdentifyHammondFootprint("1590B"),
    )

    assert codes(out) == ["unmatched-enclosure"]
    assert out.worst_severity is Severity.ERROR
    assert out.holes == ()
    assert [run.name for run in out.processing] == ["identify-enclosure"]


def test_an_enclosure_warning_does_not_stop_the_run():
    """``unknown-enclosure`` is a WARNING about *our* catalogue, not about the panel: the
    outline keeps the size it was drawn at and the artefacts are still written, so the
    holes must still be quantised.
    """
    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), reference=RawOutline(Millimetre(200.0), Millimetre(100.0))),
        enclosure=IdentifyHammondFootprint(),
    )

    assert codes(out) == ["unknown-enclosure"]
    assert [hole.index for hole in out.holes] == [4]
    assert (out.reference.width_nm, out.reference.height_nm) == (200_000_000, 100_000_000)


def test_a_dropped_hole_does_not_stop_the_run():
    """``unknown-diameter`` withholds the artefacts, not the work. Every other
    hole is still quantised, because the report has to name all of them."""
    out = phase(
        read(
            RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(30.0), 4),
            RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(29.0), 1),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0), 9),
        )
    )

    assert codes(out) == ["unknown-diameter", "unknown-diameter"]
    assert [hole.index for hole in out.holes] == [9]


def test_a_diameter_a_hair_outside_the_tolerance_costs_the_run_its_artifacts():
    """The drill table's half of the same counterexample, at the phase."""
    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(25.2500004), 4), RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(7.0), 1))
    )

    assert codes(out) == ["unknown-diameter"]
    assert out.worst_severity is Severity.ERROR
    assert [hole.index for hole in out.holes] == [1]


# ---------------------------------------------------------------------------
# identity, which the assembly is the one place that can break
# ---------------------------------------------------------------------------


def test_every_finished_hole_keeps_the_number_its_measurement_had():
    """4, 1, 9 — deliberately neither ordered nor equal to a list position."""
    out = phase(
        read(
            RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4),
            RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(7.0), 1),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0), 9),
        )
    )

    assert [hole.index for hole in out.holes] == [4, 1, 9]
    assert [hole.raw.index for hole in out.holes] == [4, 1, 9]


def test_the_measurement_travels_with_the_hole_it_was_taken_from():
    """``raw`` is the artwork's own number, kept so a residual can be recomputed
    rather than remembered. Each hole must carry *its* measurement, which a
    fixture of identical circles could not show."""
    out = phase(
        read(RawHole(Millimetre(-19.9906), Millimetre(18.0021), Millimetre(6.9998), 4), RawHole(Millimetre(20.0031), Millimetre(-18.7), Millimetre(5.0002), 1))
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
    """The finding the phase is the only thing positioned to raise."""
    holes = tuple(RawHole(float(i), Millimetre(0.0), Millimetre(7.0), index=i + 4) for i in range(hole_count))

    out = phase(read(*holes), positions=SnapPositions(Nanometre(0)))

    assert codes(out).count("grid-too-fine") == 1
    assert len(out.holes) == hole_count


def test_an_unclamped_grid_says_nothing():
    """The clamp finding is news, and a run that reports it on every panel is a
    run that has trained the operator to skim past it."""
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)), positions=SnapPositions(Nanometre(250_000)))
    assert codes(out) == []


def test_the_phase_reports_a_tied_hole_as_moved_and_says_nothing_more():
    """Whether the *panel* ties is not this phase's question to answer."""
    out = phase(read(RawHole(Millimetre(-20.125), Millimetre(18.0), Millimetre(7.0), 4), RawHole(Millimetre(0.125), Millimetre(18.0), Millimetre(7.0), 1)))

    assert codes(out) == ["off-grid", "off-grid"]


def test_a_panel_drawn_on_the_declared_grid_says_nothing_at_all():
    """The findings this phase makes are news, and a run that raises one on
    every panel has trained the operator to skim past it."""
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), RawHole(Millimetre(0.25), Millimetre(18.0), Millimetre(7.0), 1)))

    assert codes(out) == []


def test_a_panel_with_no_holes_is_quantised_without_complaint():
    """A phase handed nothing to quantise has nothing to say about it, and a
    warning about a panel with no circles on it is noise in front of an operator
    with nothing to fix."""
    out = phase(read())

    assert codes(out) == []


def test_the_sources_own_findings_survive_the_phase():
    """A source reports what it could not read — a reference layer with no
    outline in it, a layer it had to guess about — and those findings are about
    the read rather than about anything quantised. Losing them here would leave
    the run with no record that the frame is page-relative.
    """
    prior = Diagnostic.warning("no-reference-outline", "the reference layer held no path")

    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), diagnostics=(prior,)))

    assert out.diagnostics[0] is prior


def test_the_sources_findings_come_before_the_phases_own():
    """Order is the reading order of the report, and the read happened first.

    A source finding shuffled in among the per-hole ones would have the operator
    reading about hole 4's diameter before being told the panel has no frame.
    """
    prior = Diagnostic.warning("no-reference-outline", "the reference layer held no path")

    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(30.0), 4), diagnostics=(prior,), reference=None),
        # Undeclared: a declared case with no outline to check it against is
        # ``unverifiable-enclosure``, an ERROR, and the run would stop before
        # there were any per-hole findings to order.
        enclosure=IdentifyHammondFootprint(),
        positions=SnapPositions(Nanometre(0)),
    )

    assert codes(out) == ["no-reference-outline", "grid-too-fine", "unknown-diameter"]


def test_a_findings_location_names_the_measurement_it_was_taken_from():
    """The refusal is written by the quantiser that held the measurement, and
    it is checkable against the drawing only if the phase hands over the
    measurement's own place rather than a number assigned by a later stage."""
    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(30.0), 9))
    )

    assert out.diagnostics[0].get("hole_index") is None
    assert out.diagnostics[0].location_nm == (0, 18_000_000)


# ---------------------------------------------------------------------------
# the frame and the conclusion
# ---------------------------------------------------------------------------


def test_the_outline_is_snapped_to_the_catalogue_and_the_measurement_is_kept():
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)))

    assert (out.reference.width_nm, out.reference.height_nm) == (112_400_000, 60_500_000)
    assert (out.reference.raw.width, out.reference.raw.height) == (113.0, 60.0)
    assert (out.reference.centre_x_nm, out.reference.centre_y_nm) == (56_500_000, 30_000_000)


def test_the_identified_footprint_reaches_the_document():
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)))

    assert out.enclosure.candidates == ("1590B", "1590B2")
    assert (out.enclosure.length_nm, out.enclosure.width_nm) == (112_400_000, 60_500_000)
    assert out.enclosure.selected_part == DECLARED


def test_a_panel_with_no_reference_layer_is_quantised_all_the_same():
    """The source has already reported the absence; the phase adds nothing and refuses
    nothing. Positions are page-relative and the holes still need bits.
    """
    out = phase(
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4), reference=None),
        enclosure=IdentifyHammondFootprint(),
    )

    assert out.reference is None
    assert out.enclosure is None
    assert codes(out) == []
    assert [hole.diameter_nm for hole in out.holes] == [7_000_000]


def test_the_read_that_produced_the_document_is_carried_over():
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)))
    assert out.source == SourceInfo(path="panel.ai", drill_layer="Drill")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def test_the_phase_records_all_three_quantisers_in_the_order_they_ran():
    out = phase(read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)))

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
        read(RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0), 4)),
        diameters=SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]),
        positions=SnapPositions(Nanometre(0)),
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
    """Millimetres to PDF user-space points, the way a drawing tool would."""
    return mm * 72 / 25.4


def test_artwork_drawn_on_half_the_declared_pitch_is_reported_as_ambiguous(tmp_path):
    """PDF parsing perturbs 10.25 mm, but its residual is half a 0.5 mm pitch.

    Residual-based review detects the tie that raw-float equality misses.
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
        enclosure=IdentifyHammondFootprint(DECLARED),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(Nanometre(500_000)),
    )
    reviewed = ReviewGridTies().apply(out)

    assert codes(out) == ["off-grid", "off-grid", "off-grid"]
    assert codes(reviewed) == ["off-grid", "off-grid", "off-grid", "grid-ambiguous"]
    assert reviewed.diagnostics[-1].get("tied_indices") is None
    assert reviewed.diagnostics[-1].get("tied_locations") == tuple(
        (hole.x_nm, hole.y_nm) for hole in out.holes
    )

    # The claim the fixture exists for: the artwork did not survive as the
    # midpoint it was drawn at, and the residual is one anyway.
    assert out.holes[2].raw.x != 10.25
    assert [hole.residual_nm[0] for hole in out.holes] == [250_000, -250_000, -250_000]
