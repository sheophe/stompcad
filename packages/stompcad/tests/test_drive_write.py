"""The driver's writing: one transaction over the whole set, not one per path.

CLAUDE.md forbids a second write mechanism and requires ADR-0001's and
ADR-0005's rollback preserved. A bare ``commit()`` loop replaces each target
in turn and leaves the earlier ones replaced when a later one fails, so this
drives a failing commit and asserts what ``commit_all`` alone provides: the
already-replaced target back as it was, and every pending write discarded.
"""

from __future__ import annotations

import errno
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad.drive import Driver, Project, RunOptions
from stompcad.manifest import Manifest, manifest_path
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompcad.settings import Origin, Provenance, Resolved, Settings
from stompcollider.model import DockData
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, DrillData, ReferenceOutline
from stompmodel.progress import track
from stompmodel.units import Nanometre
from tests.conftest import PANEL_REFERENCE, TAR_AI, TAR_PCB, NullSink

__all__: list[str] = []

_BEFORE = b"the bytes an earlier run left here"


class _SilentPresentation:
    """A presentation that accepts every call and records nothing."""

    def begin(self, plan: RunPlan) -> None:
        return None

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        return None

    def ask(self, question: object) -> str:
        raise AssertionError("a write step must not ask a question of its own")

    def report(self, lines: Sequence[str]) -> None:
        return None


def _options(
    targets: tuple[tuple[str, Path], ...], boards: tuple[Path, ...] = ()
) -> RunOptions:
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
        boards=boards,
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=targets,
    )


def _fail_the_second_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the second commit of the set fail, and only that one.

    Patched at ``os.replace`` rather than at ``StagedWrite``: the rollback
    restores its target through the same call, so a patch on the staged
    write itself would also disable the mechanism under test. The staging
    step writes its temporaries through ``Path.write_bytes``, so only the
    commits and the rollback reach this.
    """
    real = os.replace
    seen = 0

    def replace(src: object, dst: object) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            raise OSError(errno.EIO, "forced for the transaction guard")
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", replace)


def test_a_failed_commit_restores_the_first_target_and_discards_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three targets, the second unable to commit: the set moves or none does."""
    first, second, third = (tmp_path / "a.json", tmp_path / "b.svg", tmp_path / "c.pdf")
    first.write_bytes(_BEFORE)
    targets = (("json", first), ("drawing-svg", second), ("drawing-pdf", third))
    driver = Driver(DRILL_AND_DOCK, _SilentPresentation(), _options(targets))
    _fail_the_second_replace(monkeypatch)

    with pytest.raises(OSError):
        with track(NullSink()) as scope:
            driver._write_case(DrillData(), scope)

    assert first.read_bytes() == _BEFORE, "the committed target was not put back"
    assert not second.exists()
    assert not third.exists()
    assert [path.name for path in tmp_path.iterdir()] == ["a.json"]


def _data() -> DrillData:
    """A document every drill format accepts: the Excellon needs an outline."""
    return DrillData(
        reference=ReferenceOutline(Nanometre(30_000_000), Nanometre(20_000_000))
    )


def _driver_with(
    tmp_path: Path, *, boards: tuple[Path, ...], targets: tuple[tuple[str, Path], ...]
) -> tuple[Driver, DrillData]:
    """A driver holding a project, and drill data a write step will accept.

    The data is constructed rather than driven through the artwork: these
    tests are about which commit owns which format, and reading a panel to
    find out would make them the slowest tests in the file.
    """
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    defaults = Settings.of_defaults(panel)
    settings = replace(
        defaults,
        output=replace(
            defaults.output, targets=Resolved(targets, Provenance(Origin.USER))
        ),
    )
    options = replace(_options(targets, boards=boards), panel=panel)
    project = Project(panel=panel, settings=settings, held=Manifest())
    return Driver(DRILL_AND_DOCK, _SilentPresentation(), options, project), _data()


def test_write_case_defers_the_document_and_the_model_when_there_are_boards(
    tmp_path: Path,
) -> None:
    """Decision 16. The Excellon and the drawings are complete without the
    walls; the document and the model describe the whole job and are not."""
    driver, data = _driver_with(
        tmp_path,
        boards=(TAR_PCB,),
        targets=(
            ("excellon", tmp_path / "p.drl"),
            ("json", tmp_path / "p.json"),
            ("step", tmp_path / "p.stp"),
        ),
    )
    with track(NullSink()) as scope:
        written = driver._write_case(data, scope)

    assert [Path(name).name for name in written] == ["p.drl"]
    assert not (tmp_path / "p.json").exists()
    assert not (tmp_path / "p.stp").exists()


def test_write_case_still_writes_everything_when_there_are_no_boards(
    tmp_path: Path,
) -> None:
    """The control. A drill-only run has no model commit to defer to."""
    driver, data = _driver_with(
        tmp_path,
        boards=(),
        targets=(
            ("excellon", tmp_path / "p.drl"),
            ("json", tmp_path / "p.json"),
        ),
    )
    with track(NullSink()) as scope:
        written = driver._write_case(data, scope)

    assert sorted(Path(name).name for name in written) == ["p.drl", "p.json"]


def test_the_model_commit_writes_only_the_two_formats_that_describe_the_job(
    tmp_path: Path,
) -> None:
    driver, data = _driver_with(
        tmp_path,
        boards=(TAR_PCB,),
        targets=(
            ("excellon", tmp_path / "p.drl"),
            ("json", tmp_path / "p.json"),
        ),
    )
    with track(NullSink()) as scope:
        written = driver._write_model(data, scope)

    assert [Path(name).name for name in written] == ["p.json"]


def test_the_model_commit_lands_even_when_it_writes_no_artefact(tmp_path: Path) -> None:
    """A boards run asking for neither json nor step. The declaration is still
    the last drill-half commit, or a project file sits beside artefacts it
    does not describe."""
    driver, data = _driver_with(
        tmp_path, boards=(TAR_PCB,), targets=(("excellon", tmp_path / "p.drl"),)
    )
    with track(NullSink()) as scope:
        driver._write_case(data, scope)
        assert not manifest_path(driver._options.panel).exists()
        driver._write_model(data, scope)

    stored = json.loads(manifest_path(driver._options.panel).read_text())
    assert set(stored["output"]["targets"]) == {"excellon"}


def _errored_dock() -> DockData:
    """A dock result carrying an error, for the model commit's own withhold gate."""
    frame = FaceFrame(
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    return DockData(
        case=CaseRegistration("1590B", CaseFace.BOX, "case.stp", frame)
    ).with_diagnostics(Diagnostic.error("stand-in-error", "forced for the withhold gate"))


def test_the_model_commit_withholds_its_artefacts_on_a_dock_half_error(
    tmp_path: Path,
) -> None:
    """ADR-0013's per-half limit does not reach this commit.

    It runs after docking and its wall holes are resolved from the features
    the dock half settled, so bytes written over a dock error would describe
    holes that run called undecidable.
    """
    driver, data = _driver_with(
        tmp_path,
        boards=(TAR_PCB,),
        targets=(("excellon", tmp_path / "p.drl"), ("json", tmp_path / "p.json")),
    )
    driver._dock_data = _errored_dock()

    with track(NullSink()) as scope:
        written = driver._write_model(data, scope)

    assert written == []
    assert not (tmp_path / "p.json").exists()


def test_a_dock_half_error_still_records_the_drill_half_s_declaration(
    tmp_path: Path,
) -> None:
    """The control, and decision 8's own rule.

    A declaration records the values that produced a half's artefacts, not the
    artefacts; the Excellon those values produced is on disk and no dock
    finding puts it in doubt. This commit carries the drill half's declaration
    in a run with boards, so withholding it too would leave that file beside no
    project file at all.
    """
    driver, data = _driver_with(
        tmp_path,
        boards=(TAR_PCB,),
        targets=(("excellon", tmp_path / "p.drl"), ("json", tmp_path / "p.json")),
    )
    with track(NullSink()) as scope:
        driver._write_case(data, scope)
    assert not manifest_path(driver._options.panel).exists(), (
        "the control: write case defers the declaration on a boards run"
    )
    driver._dock_data = _errored_dock()

    with track(NullSink()) as scope:
        driver._write_model(data, scope)

    stored = json.loads(manifest_path(driver._options.panel).read_text(encoding="utf-8"))
    assert "drilling" in stored, "the values that produced the Excellon are declared"
    # And only the format that produced a file: ``output.targets`` is a
    # per-format map, so naming ``json`` here would point at a file this very
    # commit withheld -- the rule ``payload_for`` already applies to a format
    # it does not own.
    assert set(stored["output"]["targets"]) == {"excellon"}
