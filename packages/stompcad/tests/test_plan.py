"""The run's nine steps, in spec order, weighted so the dock dominates."""

from __future__ import annotations

from stompcad.plan import DRILL_AND_DOCK

__all__: list[str] = []


def test_the_plan_is_the_nine_steps_in_order() -> None:
    assert [step.key for step in DRILL_AND_DOCK.steps] == [
        "read-panel", "quantise", "drill", "write-case",
        "read-boards", "match", "seat", "clash", "write-assembly",
    ]


def test_seat_and_clash_carry_most_of_the_bar() -> None:
    """Spec decision 5: kernel leaves dominate, so the dock dominates."""
    by_key = {step.key: step.weight for step in DRILL_AND_DOCK.steps}
    total = sum(by_key.values())
    assert by_key["seat"] / total > 0.4
    assert (by_key["seat"] + by_key["clash"]) / total > 0.6
    assert by_key["quantise"] / total < 0.05


def test_every_weight_is_positive() -> None:
    assert all(step.weight > 0 for step in DRILL_AND_DOCK.steps)
