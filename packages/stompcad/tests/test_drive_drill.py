"""The drill half of the driver: composed in memory, matching stompdrill's own CLI.

Spec decision 7: stompcad calls each phase separately rather than through one
entry point per tool. This test is the byte-identity acceptance criterion
that promise rests on -- the orchestrator must add nothing and change
nothing an artefact's bytes could show.
"""

from __future__ import annotations

import io
from pathlib import Path

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import PlainWriter
from stompdrill import cli as stompdrill_cli
from stompmodel.progress import track
from tests.conftest import PANEL_REFERENCE, TAR_AI, NullSink

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
