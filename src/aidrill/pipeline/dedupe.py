"""Duplicate hole collapsing.

Artwork routinely carries a hole twice — a copied row, a stray paste, a circle
that survived on two layers. Drilling the same coordinate twice is at best a
wasted move and at worst a broken bit, so coincident holes are collapsed here,
once, and the operator is told it happened.
"""

from __future__ import annotations

import math
from typing import ClassVar

from ..model import Diagnostic, DrillData, Hole, StageRun
from ..tolerance import within

__all__ = ["Deduplicate"]


class Deduplicate:
    """Collapse holes that coincide within ``tolerance`` **and** share a diameter.

    Equality of diameter is exact: deciding that 6.9998 and 7.0000 are the same
    size is ``SnapDiametersToDrillTable``'s job, not this stage's, and doing it
    in two places is how the two of them come to disagree. Run that stage first
    if that is what you want — but this stage never assumes you did.

    The first hole of a group in input order survives, so ordering upstream (or
    the lack of it) fully determines the result.
    """

    name: ClassVar[str] = "deduplicate"

    def __init__(self, tolerance: float = 0.05) -> None:
        self.tolerance = float(tolerance)

    def describe(self) -> StageRun:
        """The radius within which two same-size holes were treated as one."""
        return StageRun(self.name, (("tolerance_mm", self.tolerance),))

    def apply(self, data: DrillData) -> DrillData:
        kept: list[Hole] = []
        counts: list[int] = []

        for hole in data.holes:
            for index, survivor in enumerate(kept):
                if self._same_hole(hole, survivor):
                    counts[index] += 1
                    break
            else:
                kept.append(hole)
                counts.append(1)

        diagnostics = [
            self._report(hole, count) for hole, count in zip(kept, counts) if count > 1
        ]

        return data.with_holes(kept).with_diagnostics(*diagnostics)

    def _report(self, survivor: Hole, count: int) -> Diagnostic:
        """Describe one collapsed group, for humans *and* for machines.

        ``hole_index`` is the foreign key: the survivor's stable identity, which
        stays true however far a later stage moves it. ``location`` is the
        survivor's coordinate *at the time of the report* and stays for human
        context — the CLI report and the drawing's NOTES both read better with a
        position in them — but it is no longer what a consumer matches on. It
        was: with only a position to go by the drawing emitter re-derived which
        holes were duplicates, a second, divergent implementation of this
        stage's rule with its own tolerance and no diameter check, and it
        flagged holes this stage had not.
        """
        return Diagnostic.warning(
            "duplicate-hole",
            f"{count} coincident ⌀{survivor.diameter:g} mm holes at "
            f"({survivor.x:.3f}, {survivor.y:.3f}) within {self.tolerance:g} mm; "
            f"kept 1, dropped {count - 1}",
            location=(survivor.x, survivor.y),
            data=(
                ("hole_index", survivor.index),
                ("diameter", survivor.diameter),
                ("dropped", count - 1),
                ("kept", 1),
            ),
        )

    def _same_hole(self, a: Hole, b: Hole) -> bool:
        return a.diameter == b.diameter and within(
            math.hypot(a.x - b.x, a.y - b.y), 0.0, self.tolerance
        )
