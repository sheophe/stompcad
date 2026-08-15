"""Duplicate hole collapsing.

Artwork routinely carries a hole twice — a copied row, a stray paste, a circle
that survived on two layers. Drilling the same coordinate twice is at best a
wasted move and at worst a broken bit, so coincident holes are collapsed here,
once, and the operator is told it happened.

**Coincident means equal, exactly, on every axis.** Deciding that 6.9998 and
7.0000 are one size belongs to ``SnapDiametersToDrillTable``; deciding that
−39.9906 and −40.0 are one place belongs to ``SnapPositions``. A stage that
re-decides either is the second implementation that comes to disagree with the
first, so this one decides neither and carries no tolerance of its own — there
is no bound here to get wrong.
"""

from __future__ import annotations

from typing import ClassVar

from ..model import Diagnostic, DrillData, Hole, StageRun

__all__ = ["Deduplicate"]


class Deduplicate:
    """Collapse holes that share a position **and** a diameter, both exactly.

    Exactness is not purity bought at the cost of catching real duplicates. A
    duplicate in this domain is a copy-paste, and Illustrator writes the copy at
    the original's coordinates: the shipped fixture's pair parses as
    ``x=-39.990641944444405, y=17.999956944444445`` for *both* circles, identical
    to the last bit and before anything has snapped them. ``SnapPositions`` is
    deterministic on top of that, so two holes that land on one grid point land
    on the same float.

    What a tolerance would additionally have caught is a near miss the grid did
    not close — which is to say a hole the artwork puts somewhere else, and
    dropping it drills one hole where the panel asks for two.

    Nothing here assumes a predecessor ran. Exact equality asserts strictly less
    about the incoming data than a tolerance did (LSP): it is the same rule
    whether the holes were snapped first or not.

    The first hole of a group in input order survives, so ordering upstream (or
    the lack of it) fully determines the result.
    """

    name: ClassVar[str] = "deduplicate"

    def describe(self) -> StageRun:
        """No parameters, because there is no longer a number to report.

        The record itself still matters: it is how a consumer knows the stage
        ran at all, and "deduplicated, on exact coincidence" is the whole of
        what it was configured to do.
        """
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        groups: list[list[Hole]] = []

        for hole in data.holes:
            for group in groups:
                if self._same_hole(hole, group[0]):
                    group.append(hole)
                    break
            else:
                groups.append([hole])

        diagnostics = [self._report(group) for group in groups if len(group) > 1]

        return data.with_holes([group[0] for group in groups]).with_diagnostics(*diagnostics)

    def _report(self, group: list[Hole]) -> Diagnostic:
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

        ``dropped_indices`` names the holes that went, not merely how many.
        Traversal order is not group order — the fixture's pair is hole 2 and
        hole 5, three apart in a list that reaches this stage as
        ``[2, 3, 4, 6, 7, 0, 1]`` — so a consumer reconciling artwork circles
        against emitted holes cannot infer 5 from "the survivor is 2, one was
        dropped". It travels as a comma-separated string because
        ``Diagnostic.data`` holds scalars; widening that is a change to the
        model and belongs with one.
        """
        survivor, dropped = group[0], group[1:]
        indices = [hole.index for hole in dropped]
        plural = "" if len(indices) == 1 else "s"
        return Diagnostic.warning(
            "duplicate-hole",
            f"{len(group)} coincident ⌀{survivor.diameter:g} mm holes at "
            f"({survivor.x:.3f}, {survivor.y:.3f}); kept hole {survivor.index}, "
            f"dropped hole{plural} {', '.join(str(index) for index in indices)}",
            location=(survivor.x, survivor.y),
            data=(
                ("hole_index", survivor.index),
                ("diameter", survivor.diameter),
                ("dropped", len(dropped)),
                ("dropped_indices", ",".join(str(index) for index in indices)),
                ("kept", 1),
            ),
        )

    def _same_hole(self, a: Hole, b: Hole) -> bool:
        return a.diameter == b.diameter and a.x == b.x and a.y == b.y
