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
from pathlib import Path
from typing import cast

import pytest

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.present import PlainWriter
from stompcollider import cli as stompcollider_cli
from stompcollider.model import DockData
from stompcollider.sources import BoardGeometry, BoardScan
from stompdrill import cli as stompdrill_cli
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, DrillData
from stompmodel.progress import track
from stompmodel.units import Nanometre
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
        boards=(TAR_PCB,),
        case="1590B",
        case_model=model,
        panel_reference=_PAIRING_PANEL_REFERENCE,
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
        boards=(TAR_PCB,),
        case="1590B",
        case_model=None,
        panel_reference=PANEL_REFERENCE,
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

    A genuine ERROR rather than a constructed one: the tar fixture's
    footprint matches three catalogue parts, so a run declaring no case
    raises ``ambiguous-enclosure`` out of quantisation. Docking such a run
    would read every board and seat it for output it may not write.
    """
    presentation = _RecordingPresentation()
    target = tmp_path / "report.json"
    options = RunOptions(
        panel=TAR_AI,
        boards=(TAR_PCB,),
        case=None,
        case_model=None,
        panel_reference=PANEL_REFERENCE,
        targets=(("report", target),),
    )
    driver = Driver(DRILL_AND_DOCK, presentation, options)

    with track(NullSink()) as scope:
        drilled, dock = driver.run(scope)

    assert drilled.worst_severity is Severity.ERROR
    assert [finding.code for finding in drilled.diagnostics] == ["ambiguous-enclosure"]
    assert dock is None
    assert [step.key for step, _outcome in presentation.finished] == [
        "read-panel", "quantise", "drill", "write-case",
    ]
    assert not target.exists()
    assert any("docked nothing" in line for lines in presentation.reported for line in lines)
