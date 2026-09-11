"""The drill half of the driver: composed in memory, matching stompdrill's own CLI.

Spec decision 7: stompcad calls each phase separately rather than through one
entry point per tool. This test is the byte-identity acceptance criterion
that promise rests on -- the orchestrator must add nothing and change
nothing an artefact's bytes could show, in every format stompdrill emits.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import PlainWriter
from stompdrill import cli as stompdrill_cli
from stompdrill.emitters import available
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
        boards=(),
        case="1590B",
        case_model=None,
        panel_reference=PANEL_REFERENCE,
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
        boards=(),
        case="1590B",
        case_model=model,
        panel_reference=PANEL_REFERENCE,
        targets=tuple((name, mine_paths[name]) for name in formats),
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options)
    with track(NullSink()) as scope:
        driver.run_drill(scope)

    for name in formats:
        mine_bytes = mine_paths[name].read_bytes()
        theirs_bytes = theirs_paths[name].read_bytes()
        assert mine_bytes == theirs_bytes, f"{name}: bytes differ"
