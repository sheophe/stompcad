"""The work tree this tool reports, seen through a recording sink.

Written per package because each package's tests run in their own
process; ``stompcollider`` has its own copy for the same reason.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from stompdrill import cli
from stompdrill.quantise import RawDrillData, quantise
from stompmodel.progress import track
from tests.conftest import FakeCase

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"


class Recorder:
    """Every update in order, for a test to read back."""

    def __init__(self) -> None:
        self.updates: list[tuple[float, tuple[str, ...]]] = []

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self.updates.append((position, path))

    @property
    def paths(self) -> list[tuple[str, ...]]:
        return [path for _position, path in self.updates]

    @property
    def positions(self) -> list[float]:
        return [position for position, _path in self.updates]


def test_quantise_reports_one_step_per_raw_hole(tar_raw) -> None:
    """The count is the measurements, known before the walk begins."""
    recorder = Recorder()
    with track(recorder) as scope:
        quantise(tar_raw.raw, **tar_raw.quantisers, scope=scope)

    # Not a set: tar.ai carries one genuine duplicate hole (test_cli.py's
    # "duplicate-hole" fixture fact), so two labels are identical by content.
    # The count under test is steps taken, not distinct label text.
    holes = [path for path in recorder.paths if path and path[0].startswith("hole ")]
    assert len(holes) == len(tar_raw.raw.holes)
    assert recorder.positions == sorted(recorder.positions)


def test_the_case_model_slot_spans_the_real_read(monkeypatch) -> None:
    """The case-model leaf opens before the STEP read and closes only after.

    ``build_case_model`` is replaced with a stand-in that inspects the sink's
    own last update the moment it is called: a version that labels this leaf
    only after the read has already happened -- the defect this replaces --
    would leave the sink with no update at all to find at that point.
    """
    recorder = Recorder()
    seen_on_entry: list[tuple[float, tuple[str, ...]]] = []

    def fake_build_case_model(args: object) -> FakeCase:
        seen_on_entry.append(recorder.updates[-1])
        return FakeCase()

    monkeypatch.setattr(cli, "build_case_model", fake_build_case_model)

    args = cli.build_parser().parse_args(
        [str(FIXTURE), "--case", "1590B", "--case-model", "unused.stp"]
    )
    with track(recorder) as scope:
        cli._run(args, io.StringIO(), scope)

    assert seen_on_entry, "the stand-in read never ran"
    _position, path_on_entry = seen_on_entry[0]
    assert path_on_entry == ("read", "case model")

    case_index = recorder.paths.index(("read", "case model"))
    artwork_index = recorder.paths.index(("read", "artwork"))
    assert artwork_index > case_index


def test_the_root_position_stays_below_one_until_the_artwork_is_read(monkeypatch) -> None:
    """A slot's position must still be open when its own work starts.

    Drawing every slot from one division in a single statement -- rather
    than one ``next()`` per slot, immediately before that slot's work -- pulls
    them all back to back with no work between them, so the position races to
    1.0 before anything has actually run. ``read_source`` is watched here
    because it is the first read this run performs.
    """
    recorder = Recorder()
    seen_on_entry: list[tuple[float, tuple[str, ...]]] = []
    real_read_source = cli.read_source

    def watching_read_source(args: argparse.Namespace) -> RawDrillData:
        seen_on_entry.append(recorder.updates[-1])
        return real_read_source(args)

    monkeypatch.setattr(cli, "read_source", watching_read_source)

    args = cli.build_parser().parse_args([str(FIXTURE), "--case", "1590B"])
    with track(recorder) as scope:
        cli._run(args, io.StringIO(), scope)

    assert seen_on_entry, "the artwork read never ran"
    position_on_entry, _path = seen_on_entry[0]
    assert position_on_entry < 1.0

    assert recorder.positions[-1] == 1.0
