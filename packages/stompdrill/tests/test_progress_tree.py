"""The work tree this tool reports, seen through a recording sink.

Written per package because each package's tests run in their own
process; ``stompcollider`` has its own copy for the same reason.
"""

from __future__ import annotations

import io
from pathlib import Path

from stompdrill import cli
from stompdrill.quantise import quantise
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
