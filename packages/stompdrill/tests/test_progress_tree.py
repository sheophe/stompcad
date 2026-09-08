"""The work tree this tool reports, seen through a recording sink.

Written per package because each package's tests run in their own
process; ``stompcollider`` has its own copy for the same reason.
"""

from __future__ import annotations

from stompdrill.quantise import quantise
from stompmodel.progress import track

__all__: list[str] = []


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
