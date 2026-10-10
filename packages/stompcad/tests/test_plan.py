"""The run's eleven steps, in spec order, weighted so the dock dominates."""

from __future__ import annotations

import subprocess
import sys

from stompcad.plan import DRILL_AND_DOCK

__all__: list[str] = []


def test_importing_the_plan_loads_no_kernel() -> None:
    """``plan.py`` is a pure data structure; nothing it imports may reach the kernel.

    Checked against both ``OCP`` and ``stompgeom`` -- the kernel binding
    imports OCP lazily throughout this codebase (functions, not module top),
    so an eager ``import stompgeom`` is the fact that would actually catch a
    regression here; ``OCP`` is kept alongside it in case that changes.
    """
    probe = (
        "import stompcad.plan, sys; "
        "loaded = sorted("
        "m for m in sys.modules "
        "if m == 'OCP' or m.startswith('OCP.') "
        "or m == 'stompgeom' or m.startswith('stompgeom.')); "
        "assert not loaded, loaded"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_plan_is_the_eleven_steps_in_order() -> None:
    assert [step.key for step in DRILL_AND_DOCK.steps] == [
        "read-panel", "quantise", "drill", "write-case",
        "read-boards", "match", "seat", "clash",
        "drill-walls", "write-model", "write-assembly",
    ]


def test_the_walls_are_cut_after_the_clash_and_before_the_model_is_written() -> None:
    """``clash`` precedes ``drill-walls``, which precedes ``write-model``.

    Walls are cut from the ranking that survived re-ranking, the only one
    that will not change under drilling, and the model is written after so
    that it describes the cut walls (ADR-0013).
    """
    keys = [step.key for step in DRILL_AND_DOCK.steps]
    assert keys.index("clash") < keys.index("drill-walls") < keys.index("write-model")


def test_both_new_steps_fall_inside_the_region_a_boardless_run_prunes() -> None:
    """A run naming no board takes only the four drill-half steps.

    ``drill-walls`` and ``write-model`` both lie in the region ``plan_for``
    prunes, so a drill-only run is untouched by them (ADR-0013).
    """
    from stompcad.drive import plan_for

    assert [step.key for step in plan_for(()).steps] == [
        "read-panel", "quantise", "drill", "write-case",
    ]


def test_seat_and_clash_carry_most_of_the_bar() -> None:
    """``seat`` carries over 0.4 of the bar, ``seat`` and ``clash`` together over 0.6,
    and ``quantise`` under 0.05.

    A weight counts a kernel leaf ten times a plain one (ADR-0013), and
    nearly every kernel leaf the run has falls in ``seat`` and ``clash``.
    """
    by_key = {step.key: step.weight for step in DRILL_AND_DOCK.steps}
    total = sum(by_key.values())
    assert by_key["seat"] / total > 0.4
    assert (by_key["seat"] + by_key["clash"]) / total > 0.6
    assert by_key["quantise"] / total < 0.05


def test_every_weight_is_positive() -> None:
    assert all(step.weight > 0 for step in DRILL_AND_DOCK.steps)
