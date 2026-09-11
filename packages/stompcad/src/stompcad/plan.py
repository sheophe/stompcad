"""The run's nine steps, and the share of the bar each one carries.

Spec decision 2 names the nine steps; decision 5 states how a weight is
derived, not guessed. ``weights.py`` holds the counting command and the
counts it produced; this module only declares the plan those counts fill
in. Renders in Plan B, driven in a later task -- nothing here runs a step.
"""

from __future__ import annotations

from dataclasses import dataclass

from .weights import KERNEL_LEAF_WEIGHT

__all__ = ["Step", "RunPlan", "DRILL_AND_DOCK", "KERNEL_LEAF_WEIGHT"]


@dataclass(frozen=True, slots=True)
class Step:
    """One unit of a run: what it is called, and what share of the bar it holds."""

    key: str
    label: str
    weight: float


@dataclass(frozen=True, slots=True)
class RunPlan:
    """The ordered steps of one invocation, and the division they ask for."""

    steps: tuple[Step, ...]

    def weights(self) -> tuple[float, ...]:
        """The weights, in step order, ready for ``Scope.parts``."""
        return tuple(step.weight for step in self.steps)


# Leaf counts measured on packages/stompdrill/tests/fixtures/tar.ai with
# packages/stompcollider/tests/fixtures/tar-pcb.stp against the cached
# 1590B model, --panel-reference "RV*,SW*,D(3..4),!RV5". Regenerate with:
#
#   .venv/bin/python -c "
#   from pathlib import Path
#   from stompcad.weights import count_leaves
#   cases = Path.home() / '.cache' / 'stompcad' / 'cases'
#   t = count_leaves(
#       Path('packages/stompdrill/tests/fixtures/tar.ai'),
#       Path('packages/stompcollider/tests/fixtures/tar-pcb.stp'),
#       cases / '1590B.stp', 'RV*,SW*,D(3..4),!RV5')
#   for k, v in t.items(): print(k, v.plain, v.kernel, v.weight)"
#
# step            plain  kernel  weight (= plain + kernel * KERNEL_LEAF_WEIGHT)
# read-panel          1       1      11
# quantise            8       0       8
# drill              24       7      94
# write-case          4       1      14
# read-boards         1       2      21
# match               2       0       2
# seat               88      98    1068
# clash               0       2      20
# write-assembly      0       1      10
DRILL_AND_DOCK = RunPlan(
    (
        Step("read-panel", "read panel", 1 + 1 * KERNEL_LEAF_WEIGHT),
        Step("quantise", "quantise", 8),
        Step("drill", "drill", 24 + 7 * KERNEL_LEAF_WEIGHT),
        Step("write-case", "write case", 4 + 1 * KERNEL_LEAF_WEIGHT),
        Step("read-boards", "read boards", 1 + 2 * KERNEL_LEAF_WEIGHT),
        Step("match", "match", 2),
        Step("seat", "seat", 88 + 98 * KERNEL_LEAF_WEIGHT),
        Step("clash", "clash", 0 + 2 * KERNEL_LEAF_WEIGHT),
        Step("write-assembly", "write assembly", 0 + 1 * KERNEL_LEAF_WEIGHT),
    )
)
