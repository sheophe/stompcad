"""The run's nine steps, and the share of the bar each one carries.

Spec decision 2 names the nine steps; decision 5 states how a weight is
derived, not guessed. ``tools/count_leaves.py`` holds the counting command
and the counts it produced; this module only declares the plan those counts
fill in. A pure data structure -- Plan B renders it, a later task drives
it -- so it imports nothing beyond ``dataclasses``: neither tool it
orchestrates, and so no CAD kernel.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["KERNEL_LEAF_WEIGHT", "Step", "RunPlan", "DRILL_AND_DOCK"]

#: Spec decision 5's one stated judgement: a kernel leaf's multiplier.
KERNEL_LEAF_WEIGHT: int = 10


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
#   .venv/bin/python tools/count_leaves.py \
#       packages/stompdrill/tests/fixtures/tar.ai \
#       packages/stompcollider/tests/fixtures/tar-pcb.stp \
#       ~/.cache/stompcad/cases/1590B.stp \
#       'RV*,SW*,D(3..4),!RV5'
#
# quantise, drill, read-boards, match, seat and clash are measured: each
# phase took a real counting Scope and reported its own division; see
# tools/count_leaves.py. read-panel, write-case and write-assembly are
# declared, because Source.read and Emitter.emit take no scope at all
# (packages/stompdrill/src/stompdrill/protocols.py:25 and
# packages/stompmodel/src/stompmodel/protocols.py:295) -- there is nothing
# for a Scope to be passed into.
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
