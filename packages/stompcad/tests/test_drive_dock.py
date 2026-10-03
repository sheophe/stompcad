"""The dock half of the driver: composed in memory, matching stompcollider's own CLI.

Spec decision 7: stompcad calls each phase separately. The first test is
the byte-identity acceptance criterion for the dock half, mirroring
test_drive_drill.py; the other two pin the withhold rule CLAUDE.md
requires and both wrapped tools already honour -- an error withholds
every requested target, on both halves of one run alike.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.present import PlainWriter
from stompcollider import cli as stompcollider_cli
from stompcollider.designators import NOTHING, parse_filter
from stompcollider.errors import UsageError
from stompcollider.model import DockData
from stompcollider.sources import BoardGeometry, BoardScan
from stompdrill import cli as stompdrill_cli
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import (
    SURFACE_FACE,
    CaseFace,
    CaseRegistration,
    DrillData,
    admitting_radius,
)
from stompmodel.progress import track
from stompmodel.units import Nanometre, nm_from_mm
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, NullSink, case_model

__all__: list[str] = []

#: The unnarrowed conftest expression admits both of board 2's designators.
#: The tar panel currently drills no hole wide enough for either
#: (CLAUDE.md's tar footswitch note), so both correspond to nothing --
#: ``no-correspondence``, an ERROR that withholds every target. Admitting
#: only one of the two leaves board 2 merely under-constrained (a
#: warning), which is what lets a byte-identity run reach an artefact at
#: all without touching the shared fixture or relaxing the assertion.
_PAIRING_PANEL_REFERENCE = f"{PANEL_REFERENCE},!SW2"


class _RecordingPresentation:
    """Records every ``finish_step`` and ``report`` call the driver makes."""

    def __init__(self) -> None:
        self.began: RunPlan | None = None
        self.finished: list[tuple[Step, str]] = []
        self.reported: list[list[str]] = []

    def begin(self, plan: RunPlan) -> None:
        self.began = plan

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        self.finished.append((step, outcome))

    def ask(self, question: object) -> str:
        raise AssertionError("a write step must not ask a question of its own")

    def report(self, lines: Sequence[str]) -> None:
        self.reported.append(list(lines))


def _drilled(tmp_path: Path, model: Path) -> tuple[Path, Path]:
    """A drill document and a drilled case, made once by stompdrill itself."""
    document, case = tmp_path / "tar.json", tmp_path / "tar-case.stp"
    code = stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--case-model", str(model),
        "--emit", f"json={document}", "--emit", f"step={case}",
    ])
    assert code in (0, 1), f"the fixture run failed with exit {code}"
    return document, case


@pytest.mark.boards
@pytest.mark.hammond
def test_the_dock_half_matches_stompcollider_byte_for_byte(tmp_path: Path) -> None:
    """Composed in memory, the report is the one the tool writes from a file."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    document, case = _drilled(tmp_path, model)

    theirs = tmp_path / "theirs.json"
    stompcollider_cli.main([
        str(document), str(TAR_PCB), "--case-model", str(case),
        "--panel-reference", _PAIRING_PANEL_REFERENCE, "--report", str(theirs),
    ])

    mine = tmp_path / "mine.json"
    options = RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case="1590B",
        case_model=model,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(TAR_PCB,),
        panel_reference=_PAIRING_PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=(("report", mine),),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run(scope)

    assert theirs.is_file(), "the reference run wrote nothing; narrow the fixture further"
    assert mine.is_file(), "the driver wrote nothing; narrow the fixture further"
    assert mine.read_bytes() == theirs.read_bytes()


def _dummy_case_registration() -> CaseRegistration:
    """A minimal, valid ``CaseRegistration`` for data no write step should read past."""
    frame = FaceFrame(
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    return CaseRegistration(part="1590B", face=CaseFace.BOX, model="case.stp", frame=frame)


def _options(name: str, target: Path) -> RunOptions:
    return RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case="1590B",
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(TAR_PCB,),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=((name, target),),
    )


def test_write_case_withholds_every_target_on_an_error_severity(tmp_path: Path) -> None:
    """The drill half's own write step refuses errored data before it renders.

    Constructed rather than driven through the artwork: the rule is about
    severity alone, and a synthetic ``DrillData`` proves that without the
    cost of a real read.
    """
    presentation = _RecordingPresentation()
    target = tmp_path / "mine.drl"
    driver = Driver(DRILL_AND_DOCK, presentation, _options("excellon", target))
    data = DrillData().with_diagnostics(
        Diagnostic.error("synthetic-error", "forced for the withhold guard")
    )

    with track(NullSink()) as scope:
        written = driver._write_case(data, scope)

    assert written == []
    assert not target.exists()
    assert any("wrote nothing" in line for lines in presentation.reported for line in lines)


def test_write_dock_withholds_every_target_on_an_error_severity(tmp_path: Path) -> None:
    """The dock half's own write step refuses the same data either tool would.

    ``scan`` and ``geometry`` are never read on this path -- the severity
    check returns before either is touched -- so a cast stands in for the
    real, kernel-touching values the write step would otherwise need.
    """
    presentation = _RecordingPresentation()
    target = tmp_path / "mine.json"
    driver = Driver(DRILL_AND_DOCK, presentation, _options("report", target))
    data = DockData(case=_dummy_case_registration()).with_diagnostics(
        Diagnostic.error("synthetic-error", "forced for the withhold guard")
    )
    geometry: dict[int, BoardGeometry] = {}

    with track(NullSink()) as scope:
        written = driver._write_dock(data, cast(BoardScan, None), geometry, scope)

    assert written == []
    assert not target.exists()
    assert any("wrote nothing" in line for lines in presentation.reported for line in lines)


def test_an_errored_drill_half_stops_before_a_board_is_read(tmp_path: Path) -> None:
    """CLAUDE.md's "any error prevents every requested output" binds the run too.

    A genuine ERROR rather than a constructed one: the tar footprint is no
    1590BB, so declaring one raises ``unmatched-enclosure`` out of
    quantisation. Decision 6 gives that code no picker, so it stays an
    error the run stops on rather than a gap it could ask about. Docking
    such a run would read every board and seat it for output it may not
    write.
    """
    presentation = _RecordingPresentation()
    target = tmp_path / "report.json"
    options = RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case="1590BB",
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(TAR_PCB,),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=(("report", target),),
    )
    driver = Driver(DRILL_AND_DOCK, presentation, options)

    with track(NullSink()) as scope:
        drilled, dock = driver.run(scope)

    assert drilled.worst_severity is Severity.ERROR
    assert [finding.code for finding in drilled.diagnostics] == ["unmatched-enclosure"]
    assert dock is None
    assert [step.key for step, _outcome in presentation.finished] == [
        "read-panel", "quantise", "drill", "write-case",
    ]
    assert not target.exists()
    assert any("read no board" in line for lines in presentation.reported for line in lines)


@pytest.mark.hammond
@pytest.mark.boards
def test_a_named_part_is_resolved_against_the_wall_it_is_mounted_at(
    tmp_path: Path,
) -> None:
    """The whole plan, end to end: a builder names J1, the sleeve is measured
    at this run's own radii, and the hole it needs is resolved in the right
    wall's frame at a stocked size.

    Refused there, and that is this fixture's geometry: a 1590B will not
    close over the tar board, so the seating sits 14.089 mm deeper than the
    panel's holes fix, putting J1's axis where ⌀11.400 leaves the drillable
    region. Every link before it still holds, and the refusal abandons
    neither the panel's own holes nor the commit that preceded docking.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    out = tmp_path / "p.json"
    options = replace(
        _options("json", out),
        case_model=model,
        panel_reference=_PAIRING_PANEL_REFERENCE,
        wall_reference="J1",
        targets=(("excellon", tmp_path / "p.drl"), ("json", out)),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        drill, _dock = driver.run(scope)

    refused = [finding for finding in drill.diagnostics if finding.code == "hole-off-face"]
    assert len(refused) == 1
    stated = dict(refused[0].data)
    assert stated["designator"] == "J1"
    assert stated["surface"] == "right"
    # J1's sleeve is 5.700 mm in radius and the metric standard stocks 11.400
    # exactly, so this is the size with no rounding in it at all.
    assert stated["diameter_nm"] == 11_400_000
    assert all(hole.surface == SURFACE_FACE for hole in drill.holes)
    # ADR-0013's deliberate limit: the panel's own commit happened before
    # docking began and stands, while the commit describing the whole job is
    # withheld, because the document it would write records a refused hole.
    assert (tmp_path / "p.drl").is_file()
    assert not out.exists()


@pytest.mark.hammond
@pytest.mark.boards
def test_naming_no_part_cuts_nothing_and_changes_no_byte(tmp_path: Path) -> None:
    """Decision 18's lock, through the composed run: the default is empty, so
    the artefacts of a run that names nothing are the ones it wrote before."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for target, expression in ((first, ""), (second, "")):
        options = replace(
            _options("json", target),
            case_model=model,
            panel_reference=_PAIRING_PANEL_REFERENCE,
            wall_reference=expression,
        )
        driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
        with track(NullSink()) as scope:
            driver.run(scope)

    assert first.read_bytes() == second.read_bytes()
    assert b'"surface": "right"' not in first.read_bytes()


@pytest.mark.hammond
@pytest.mark.boards
def test_an_expression_naming_nothing_says_so_rather_than_cutting_in_silence(
    tmp_path: Path,
) -> None:
    """Review focus. A typo admits no component, so nothing is measured and no
    refusal is raised: without this the run reports success and cuts nothing."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    options = replace(
        _options("json", tmp_path / "p.json"),
        case_model=model,
        panel_reference=_PAIRING_PANEL_REFERENCE,
        wall_reference="NOPE*",
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run(scope)

    named = [d for d in driver.findings if d.code == "wall-feature-unreachable"]
    assert len(named) == 1
    assert "NOPE*" in named[0].message
    assert named[0].severity is Severity.WARNING
    # A warning and not an error: nothing was cut, so the document and the
    # model are still a true description of what was drilled, and withholding
    # them over a stale expression would cost a builder the whole run.
    assert (tmp_path / "p.json").is_file()


@pytest.mark.hammond
@pytest.mark.boards
def test_a_designator_both_expressions_claim_is_a_finding(tmp_path: Path) -> None:
    """Decision 11's error, through the composed run: it is the second of the
    two codes this plan makes reachable, and a run is the only thing that can
    reach it, because which designators exist is known only once a board is
    read."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    options = replace(
        _options("json", tmp_path / "p.json"),
        case_model=model,
        panel_reference=_PAIRING_PANEL_REFERENCE,
        # RV1 is a panel reference in that expression, so claiming it here too
        # leaves nothing to say which hole the part is for.
        wall_reference="RV1",
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run(scope)

    claimed = [d for d in driver.findings if d.code == "component-claimed-twice"]
    assert len(claimed) == 1
    assert "RV1" in claimed[0].message
    assert claimed[0].severity is Severity.ERROR


def _driver(tmp_path: Path, **overrides: object) -> Driver:
    """A driver over the tar options, for a question no run has to be made to ask."""
    options = replace(_options("json", tmp_path / "p.json"), **overrides)  # type: ignore[arg-type]
    return Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)


def test_an_empty_wall_expression_becomes_the_filter_that_admits_nothing(
    tmp_path: Path,
) -> None:
    """``parse_filter("")`` refuses rather than admitting nothing, and empty is
    this field's default, so the driver is what tells the two apart. Without
    that, every run naming no wall part would fail as a usage error."""
    with pytest.raises(UsageError, match="empty designator filter expression"):
        parse_filter("")

    driver = _driver(tmp_path)
    assert driver._options.wall_reference == ""
    assert driver._wall_filter() is NOTHING
    assert driver._wall_filter().admit(("J1", "J4")) == frozenset()
    assert _driver(tmp_path, wall_reference="J1")._wall_filter().admit(
        ("J1", "J4")
    ) == frozenset({"J1"})


def test_a_wall_feature_is_measured_at_the_radii_this_run_could_drill(
    tmp_path: Path,
) -> None:
    """Decision 7: a wall carries no holes to take an answer set from, so the
    selected standard is the whole set a wall hole can come from. Narrowing
    the standard must narrow what a sleeve is probed at, or a part is measured
    against a diameter nobody here can cut."""
    driver = _driver(tmp_path)
    whole = driver._standard()
    assert driver._wall_probes_nm() == tuple(
        sorted({admitting_radius(size) for size in whole.sizes_nm})
    )

    narrowed = _driver(tmp_path, drill_sizes="3,11.4")
    assert narrowed._standard().sizes_nm == (nm_from_mm(3.0), nm_from_mm(11.4))
    assert narrowed._wall_probes_nm() == (Nanometre(1_500_000), Nanometre(5_700_000))
    assert len(driver._wall_probes_nm()) > len(narrowed._wall_probes_nm())
