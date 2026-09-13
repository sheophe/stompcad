"""The drill half of the driver: composed in memory, matching stompdrill's own CLI.

Spec decision 7: stompcad calls each phase separately rather than through one
entry point per tool. This test is the byte-identity acceptance criterion
that promise rests on -- the orchestrator must add nothing and change
nothing an artefact's bytes could show, in every format stompdrill emits.
"""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import PlainWriter
from stompcad.settings import Settings
from stompdrill import cli as stompdrill_cli
from stompdrill.emitters import available
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.model import CaseFace
from stompmodel.progress import track
from tests.conftest import PANEL_REFERENCE, TAR_AI, NullSink, case_model

__all__: list[str] = []


def test_the_drill_half_matches_stompdrill_byte_for_byte(tmp_path: Path) -> None:
    """The orchestrator adds nothing and changes nothing."""
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])

    options = RunOptions(
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
        boards=(),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=(("excellon", mine),),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run_drill(scope)

    assert mine.read_bytes() == theirs.read_bytes()


def test_the_drill_half_matches_stompdrill_under_settings_defaults(tmp_path: Path) -> None:
    """``RunOptions.of`` must route every ``Settings`` default to the field
    stompdrill's own parser fills it from -- a field sent to the wrong place
    would not show in the test above, which states the defaults by hand.
    """
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])

    options = replace(
        RunOptions.of(Settings.of_defaults(TAR_AI)),
        case="1590B",
        targets=(("excellon", mine),),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run_drill(scope)

    assert mine.read_bytes() == theirs.read_bytes()


@pytest.mark.hammond
def test_the_drill_half_matches_stompdrill_for_every_emitted_format(tmp_path: Path) -> None:
    """Every registered format, not just the one the acceptance test found easy.

    ``step`` is the only format that reads ``OutputSettings.case_model``, so
    driving every format with a real case model is what exercises the
    ``--case-model`` path through ``run_drill`` -- nothing else in this suite
    reaches it. A wrong ``OutputSettings`` field would show in exactly one
    format's bytes and nowhere else, which is why every format is compared.
    """
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")

    formats = available()
    assert set(formats) == {"drawing-pdf", "drawing-svg", "excellon", "json", "step"}

    theirs_args = [str(TAR_AI), "--case", "1590B", "--case-model", str(model)]
    theirs_paths: dict[str, Path] = {}
    for name in formats:
        path = tmp_path / f"theirs-{name}"
        theirs_paths[name] = path
        theirs_args += ["--emit", f"{name}={path}"]
    code = stompdrill_cli.main(theirs_args)
    assert code in (0, 1), f"the fixture run failed with exit {code}"

    mine_paths = {name: tmp_path / f"mine-{name}" for name in formats}
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
        boards=(),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=tuple((name, mine_paths[name]) for name in formats),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run_drill(scope)

    for name in formats:
        mine_bytes = mine_paths[name].read_bytes()
        theirs_bytes = theirs_paths[name].read_bytes()
        assert mine_bytes == theirs_bytes, f"{name}: bytes differ"
