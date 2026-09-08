"""The weighted fold: partition, monotonicity, and early completion.

A sink records what a renderer would draw, so these tests read the protocol
the way ``stompcad`` will rather than through the fold's internals.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stompmodel.progress import NO_PROGRESS, track

__all__: list[str] = []


class Recorder:
    """Every update in order, for a test to read back."""

    def __init__(self) -> None:
        self.updates: list[tuple[float, tuple[str, ...]]] = []

    def update(self, position: float, path: tuple[str, ...]) -> None:
        self.updates.append((position, path))

    @property
    def positions(self) -> list[float]:
        return [position for position, _path in self.updates]

    @property
    def paths(self) -> list[tuple[str, ...]]:
        return [path for _position, path in self.updates]


def test_a_run_that_divides_nothing_still_ends_complete() -> None:
    recorder = Recorder()
    with track(recorder):
        pass
    assert recorder.positions[-1] == 1.0


def test_equal_steps_partition_the_run() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        for _slot in root.steps(4):
            pass
    assert recorder.positions[-1] == 1.0
    assert 0.25 in recorder.positions
    assert 0.5 in recorder.positions
    assert 0.75 in recorder.positions


def test_weights_divide_in_proportion() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        slots = root.parts(1.0, 3.0)
        next(slots)
        next(slots)
        # The first slot completed when the second was drawn.
        assert recorder.positions[-1] == 0.25
        for _rest in slots:
            pass
    assert recorder.positions[-1] == 1.0


def test_a_child_divides_only_its_own_slot() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        for index, slot in enumerate(root.steps(2)):
            for _inner in slot.steps(2):
                pass
            if index == 0:
                assert max(recorder.positions) == 0.5


def test_labels_accumulate_into_a_path() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        for slot in root.steps(1):
            slot.label("seat")
            for inner in slot.steps(1):
                inner.label("board 1")
    assert ("seat", "board 1") in recorder.paths


def test_abandoning_a_division_does_not_hold_the_run_back() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        for slot in root.steps(2):
            for _inner in slot.steps(1000):
                break  # a search that found its answer early
    assert recorder.positions[-1] == 1.0


def test_the_null_scope_reports_nothing_and_still_divides() -> None:
    for slot in NO_PROGRESS.steps(3):
        slot.label("ignored")
        for _inner in slot.parts(1.0, 2.0):
            pass


def test_a_zero_total_still_yields_one_child_per_weight_under_a_live_sink() -> None:
    """Finding 1(a): a weight of 0.0 must not vanish under a real sink.

    ``_Node._divide`` used to return early on a non-positive total, so a
    single zero weight produced no child at all, diverging from
    ``NullScope`` and breaking a pipeline whose stage weights summed to
    ``0.0``.
    """
    recorder = Recorder()
    with track(recorder) as root:
        children = list(root.parts(0.0))
    assert len(children) == 1


def test_a_zero_weight_child_claims_no_share_of_the_bar() -> None:
    recorder = Recorder()
    with track(recorder) as root:
        (only,) = root.parts(0.0)
        for _inner in only.steps(3):
            pass
    assert recorder.positions[-1] == 1.0
    assert set(recorder.positions) <= {0.0, 1.0}


@given(st.lists(st.floats(min_value=0.0, max_value=100.0), min_size=0, max_size=8))
def test_a_real_scope_and_the_null_scope_agree_on_child_count(
    weights: list[float],
) -> None:
    """Finding 1: the docstring promise that ``NullScope`` divides like a
    real scope, over weight vectors including all-zero ones."""
    recorder = Recorder()
    with track(recorder) as root:
        real_children = list(root.parts(*weights))
    null_children = list(NO_PROGRESS.parts(*weights))
    assert len(real_children) == len(null_children) == len(weights)


def test_a_negative_weight_raises_from_the_null_scope() -> None:
    """Finding 1(b): ``NullScope.parts`` accepted anything before this fix."""
    with pytest.raises(ValueError, match="cannot be negative"):
        list(NO_PROGRESS.parts(-1.0))


def test_a_single_negative_weight_raises_even_though_the_total_is_negative() -> None:
    """Finding 1(c): the old guard checked ``total <= 0.0`` before the
    validating loop, so ``parts(-1.0)`` returned silently instead of
    raising -- the negative-weight check fired only when some other
    weight kept the total positive.
    """
    recorder = Recorder()
    with track(recorder) as root:
        with pytest.raises(ValueError, match="cannot be negative"):
            list(root.parts(-1.0))


@given(st.lists(st.integers(min_value=0, max_value=6), min_size=0, max_size=4))
def test_the_position_never_decreases(shape: list[int]) -> None:
    recorder = Recorder()
    with track(recorder) as root:
        def walk(scope, remaining):
            if not remaining:
                return
            for slot in scope.steps(remaining[0]):
                walk(slot, remaining[1:])

        walk(root, shape)
    positions = recorder.positions
    assert positions == sorted(positions)
    assert positions[-1] == 1.0


@given(st.lists(st.floats(min_value=0.1, max_value=100.0), min_size=1, max_size=8))
def test_weighted_children_partition_their_parent(weights: list[float]) -> None:
    recorder = Recorder()
    with track(recorder) as root:
        for _slot in root.parts(*weights):
            pass
    # Independent of the fold's own accumulation: each child closes with an
    # advance to its cumulative share of the parent's span, computed here
    # from ``sum()`` rather than replayed from ``_divide``'s running total.
    total = sum(weights)
    expected_boundaries = [sum(weights[: i + 1]) / total for i in range(len(weights))]
    assert recorder.positions[: len(weights)] == pytest.approx(expected_boundaries, rel=1e-9)
    assert recorder.positions[-1] == 1.0
