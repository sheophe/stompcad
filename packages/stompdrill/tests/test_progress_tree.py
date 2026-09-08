"""The work tree this tool reports, seen through a recording sink.

Written per package because each package's tests run in their own
process; ``stompcollider`` has its own copy for the same reason.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from stompdrill import cli
from stompdrill.emitters.excellon import ExcellonEmitter
from stompdrill.emitters.json_out import JsonEmitter
from stompdrill.quantise import RawDrillData, quantise
from stompmodel.model import DrillData
from stompmodel.progress import track
from stompmodel.protocols import Emitter
from tests.conftest import FakeCase, build_pipeline_for_test

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


def test_no_labelled_phase_reopens_after_the_run_reports_done() -> None:
    """Every ``next()``-drawn division must be exhausted, not only the root's.

    A division left un-exhausted stays suspended at its last ``yield``; its
    own ``finally`` fires only when the generator is garbage-collected --
    here, when ``_run`` returns -- advancing under its *parent's* name after
    the run has already told the sink it is done. ``_Run.advance`` keeps a
    maximum, so this never shows up as a position regression: it only shows
    up as a labelled path appearing again after the root's own closing
    updates, which is what this reads for directly.
    """
    recorder = Recorder()
    args = cli.build_parser().parse_args([str(FIXTURE), "--case", "1590B"])

    with track(recorder) as scope:
        cli._run(args, io.StringIO(), scope)
        # Snapshot before the ``with`` block's own exit adds track()'s
        # trailing close, so this reads only what ``_run`` itself reported.
        settled = list(recorder.updates)

    empty_path_indices = [i for i, (_position, path) in enumerate(settled) if path == ()]
    assert empty_path_indices, "the run never closed its root division"
    last_root_close = empty_path_indices[-1]
    assert all(path == () for _position, path in settled[last_root_close:])


def test_each_stage_reports_the_unit_it_walks(tar_quantised) -> None:
    """Holes for the per-hole stages, tools for the router.

    ``RouteHoles`` counts distinct diameters because ``_two_opt`` inside a
    block has no bounded pass count, so a block is one leaf.
    """
    recorder = Recorder()
    pipeline = build_pipeline_for_test()
    with track(recorder) as scope:
        pipeline.run(tar_quantised, scope)

    named = {path[0] for path in recorder.paths if path}
    assert {"deduplicate", "review-grid-ties", "route", "check-outline-containment"} <= named

    under_route = [p for p in recorder.paths if len(p) > 1 and p[0] == "route"]
    tools = {hole.diameter_nm for hole in tar_quantised.holes}
    assert len({p[1] for p in under_route}) == len(tools)

    # Not a set of labels: tar.ai carries one bit-identical raw-coordinate
    # duplicate (test_quantise_reports_one_step_per_raw_hole's fixture fact),
    # so two position labels collide by content. The count under test is
    # slots opened, one per hole, not distinct label text.
    under_dedupe = [p for p in recorder.paths if len(p) > 1 and p[0] == "deduplicate"]
    assert len(under_dedupe) == len(tar_quantised.holes)


def test_the_emit_span_divides_by_requested_target(tar_routed, tmp_path) -> None:
    """One leaf per target, whatever each emitter does inside.

    ``_write`` is exercised directly, standing in for the ``emit`` slot
    ``_run`` opens and passes to it; the scope this test tracks plays that
    slot's part.
    """
    recorder = Recorder()
    emitters: list[tuple[Emitter[DrillData], Path]] = [
        (ExcellonEmitter(), tmp_path / "a.drl"),
        (JsonEmitter(), tmp_path / "b.json"),
    ]
    with track(recorder) as scope:
        cli._write(emitters, tar_routed, scope)
        # Snapshot before track()'s own trailing close forces the root to
        # 1.0 regardless -- this reads only what the division itself left
        # behind once the loop finished.
        settled = list(recorder.updates)

    # Not a set: two labels could collide on the emitter name if a future
    # emitter reused another's, and a set would hide that. Count recorded
    # events instead.
    labelled = [path[0] for path in recorder.paths if path]
    assert labelled.count("excellon") == 1
    assert labelled.count("json") == 1

    # A third target must add a third leaf, not reuse one of the first two.
    recorder_three = Recorder()
    three = emitters + [(ExcellonEmitter(), tmp_path / "c.drl")]
    with track(recorder_three) as scope_three:
        cli._write(three, tar_routed, scope_three)
    labelled_three = [path[0] for path in recorder_three.paths if path]
    assert labelled_three.count("excellon") == 2
    assert labelled_three.count("json") == 1

    # The zip(..., strict=True) loop must exhaust the division as its last
    # target is drawn, not leave it suspended for a later ``next()`` -- so
    # the position it left behind is already at the scope's own end before
    # track()'s own exit forces one.
    assert settled[-1][0] == 1.0
