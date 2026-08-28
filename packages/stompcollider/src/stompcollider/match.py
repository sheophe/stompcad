"""``Match``: which face of a board points at the panel, and what fits.

A board's carrier normal comes from ``stompgeom.levels()``'s own partition
key, unsearched and unswept -- its sign is not a fact about which side faces
the panel. ``Match`` therefore tries both, purely in the plane: each
protrusion's axis as measured, and the same axis with one in-plane
coordinate negated (the two-dimensional trace of physically turning the
board over). Whichever hypothesis produces strictly more within-tolerance
pairings is the one that faces the panel -- a predicate over counts, never a
score. See "Match" in ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import combinations
from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import Hole, StageRun
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

from .model import Board, Component, Correspondence, DockData, Placement

__all__ = ["Match"]

#: The two hypotheses a board's carrier normal might actually point along.
_AS_EXPORTED = "+w"
_FLIPPED = "-w"

#: (part axis, hole centre) in nanometres, both already in the same plane.
_Point = tuple[Nanometre, Nanometre]
_Anchor = tuple[_Point, _Point]


def _mm(value_nm: int) -> float:
    return mm_from_nm(Nanometre(value_nm))


def _flip(axis_xy_nm: _Point) -> _Point:
    """The other physical face: negate one in-plane coordinate.

    A board turned over is a proper rotation in three dimensions, but its
    trace in the carrier plane alone is indistinguishable from a single-axis
    reflection -- which coordinate is negated does not matter, because the
    candidate step below searches every rotation freely.
    """
    x, y = axis_xy_nm
    return (x, Nanometre(-y))


def _axes_for_face(board: Board, face: str) -> dict[str, _Point]:
    """Every admitted protrusion's axis, under one face hypothesis."""
    axes: dict[str, _Point] = {}
    for component in board.components:
        if component.protrusion is None:
            continue
        axis = component.protrusion.axis_xy_nm
        axes[component.designator] = axis if face == _AS_EXPORTED else _flip(axis)
    return axes


def _distance_mm(a: _Point, b: _Point) -> float:
    return math.hypot(_mm(a[0] - b[0]), _mm(a[1] - b[1]))


def _insertion_nm(component: Component, hole: Hole) -> Nanometre | None:
    """The profile's own insertion depth through this hole -- a fact, not a
    fit judgement: recognition never rejects a pairing over it (rule 2)."""
    protrusion = component.protrusion
    assert protrusion is not None
    radius_nm = Nanometre(hole.diameter_nm // 2)
    return protrusion.profile.insertion_through(radius_nm)


def _pair_face(
    components: dict[str, Component],
    axes: dict[str, _Point],
    holes: tuple[Hole, ...],
    tolerance_nm: Nanometre,
) -> tuple[Correspondence, ...] | None:
    """Pair every axis with the one hole within tolerance.

    ``None`` marks an ambiguous pairing: two protrusions within tolerance of
    the same hole (rule 3), which a majority or a nearest-wins fallback would
    paper over rather than report.
    """
    tolerance_mm = _mm(tolerance_nm)
    claims: dict[int, list[str]] = {}
    matched: dict[str, Hole] = {}
    for designator, axis in axes.items():
        within = [
            hole for hole in holes if _distance_mm(axis, (hole.x_nm, hole.y_nm)) <= tolerance_mm
        ]
        for hole in within:
            assert hole.index is not None  # DockData.holes guarantees a drill number
            claims.setdefault(hole.index, []).append(designator)
        if len(within) == 1:
            matched[designator] = within[0]
    if any(len(designators) > 1 for designators in claims.values()):
        return None
    correspondences = []
    for designator, hole in matched.items():
        assert hole.index is not None
        axis = axes[designator]
        offset = _distance_mm(axis, (hole.x_nm, hole.y_nm))
        correspondences.append(
            Correspondence(
                designator=designator,
                hole_index=hole.index,
                hole_xy_nm=(hole.x_nm, hole.y_nm),
                insertion_nm=_insertion_nm(components[designator], hole),
                offset_nm=nm_from_mm(offset),
            )
        )
    return tuple(sorted(correspondences, key=lambda c: c.designator))


def _cross_mm2(origin: _Point, a: _Point, b: _Point) -> float:
    """The signed area of the triangle ``origin, a, b``, in square millimetres."""
    ox, oy = _mm(origin[0]), _mm(origin[1])
    ax, ay = _mm(a[0]), _mm(a[1])
    bx, by = _mm(b[0]), _mm(b[1])
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def _chirality_conflict(
    correspondences: tuple[Correspondence, ...],
    axes: dict[str, _Point],
    seed_a: Correspondence,
    seed_b: Correspondence,
    tolerance_nm: Nanometre,
) -> bool:
    """Whether a third corresponded point proves this seed needs a reflection.

    Two points alone carry no orientation, so a seed pair's own rotation
    always "fits" itself; a third point is what a mirrored layout cannot
    survive. Every correspondence carries up to one tolerance of ordinary
    recognition noise, so the check is banded rather than exact -- see the
    comment beside the band below for what it actually bounds.
    """
    part_a, part_b = axes[seed_a.designator], axes[seed_b.designator]
    hole_a, hole_b = seed_a.hole_xy_nm, seed_b.hole_xy_nm
    tolerance_mm = _mm(tolerance_nm)
    # cross(seed_a, seed_b, other) equals |seed_a - seed_b| times other's
    # perpendicular distance from the seed_a-seed_b line, so a signed area
    # at or under tolerance * |seed_a - seed_b| means that distance is at
    # most one tolerance -- consistent with ordinary recognition noise on
    # `other` alone, not evidence of a reflection. This is the explicit
    # determinant check the brief calls for when a mirrored layout would
    # otherwise validate through a seed pair alone, banded so it does not
    # also convict a board recognition noise alone can explain. Each seed
    # carries its own band from its own edge length; it bounds only a
    # perturbation of `other`, not of `seed_a` or `seed_b` themselves.
    part_uncertainty = tolerance_mm * _distance_mm(part_a, part_b)
    hole_uncertainty = tolerance_mm * _distance_mm(hole_a, hole_b)
    for other in correspondences:
        if other.designator in (seed_a.designator, seed_b.designator):
            continue
        part_cross = _cross_mm2(part_a, part_b, axes[other.designator])
        hole_cross = _cross_mm2(hole_a, hole_b, other.hole_xy_nm)
        if abs(part_cross) <= part_uncertainty or abs(hole_cross) <= hole_uncertainty:
            continue
        if (part_cross > 0) != (hole_cross > 0):
            return True
    return False


def _transform(first: _Anchor, second: _Anchor) -> tuple[float, float, float] | None:
    """``(x_mm, y_mm, theta_rad)`` taking both parts onto both holes.

    ``None`` when the two parts coincide, which fixes no angle. Closed form:
    the angle between the two separation vectors, then the translation that
    lands the first part. A rotation is solved for, never a general affine
    fit, so a layout that only fits under reflection finds no transform here
    that also survives validation against a third point (rule 4's proof is
    in ``test_a_transform_fitting_only_under_reflection_is_rejected``).
    """
    (part_a, hole_a), (part_b, hole_b) = first, second
    px, py = _mm(part_b[0] - part_a[0]), _mm(part_b[1] - part_a[1])
    hx, hy = _mm(hole_b[0] - hole_a[0]), _mm(hole_b[1] - hole_a[1])
    if math.hypot(px, py) == 0.0:
        return None
    theta = math.atan2(hy, hx) - math.atan2(py, px)
    cos, sin = math.cos(theta), math.sin(theta)
    ax, ay = _mm(part_a[0]), _mm(part_a[1])
    x = _mm(hole_a[0]) - (cos * ax - sin * ay)
    y = _mm(hole_a[1]) - (sin * ax + cos * ay)
    return (x, y, theta)


def _apply(transform: tuple[float, float, float], point_mm: tuple[float, float]) -> tuple[float, float]:
    x_mm, y_mm, theta = transform
    cos, sin = math.cos(theta), math.sin(theta)
    px, py = point_mm
    return (x_mm + cos * px - sin * py, y_mm + sin * px + cos * py)


def _validate(
    correspondences: tuple[Correspondence, ...],
    axes: dict[str, _Point],
    transform: tuple[float, float, float],
    tolerance_nm: Nanometre,
    seed_a: Correspondence,
    seed_b: Correspondence,
) -> tuple[Correspondence, ...]:
    """The seed pair, plus every *other* correspondence within tolerance.

    "Every other correspondence is then tested against that transform" --
    the spec's own wording excludes the seed: it defines the transform (its
    own gap agreement is the separate, twice-tolerance check already made),
    so re-testing it here at the single tolerance would reject exactly the
    disagreement that check was written to admit.
    """
    tolerance_mm = _mm(tolerance_nm)
    kept = [seed_a, seed_b]
    for correspondence in correspondences:
        if correspondence.designator in (seed_a.designator, seed_b.designator):
            continue
        part_mm = (_mm(axes[correspondence.designator][0]), _mm(axes[correspondence.designator][1]))
        moved = _apply(transform, part_mm)
        hole_mm = (_mm(correspondence.hole_xy_nm[0]), _mm(correspondence.hole_xy_nm[1]))
        if math.hypot(moved[0] - hole_mm[0], moved[1] - hole_mm[1]) <= tolerance_mm:
            kept.append(correspondence)
    return tuple(sorted(kept, key=lambda c: c.designator))


def _widest_pair(
    correspondences: tuple[Correspondence, ...], axes: dict[str, _Point]
) -> tuple[Correspondence, Correspondence]:
    """The two most widely separated corresponded protrusions, ties broken by
    designator order -- the best-conditioned pair a candidate can report from.

    Enumerated over correspondences already sorted by designator, so the
    first pair to reach the maximum distance is the one designator order
    prefers; only a strictly greater distance replaces it.
    """
    ordered = sorted(correspondences, key=lambda c: c.designator)
    best = (ordered[0], ordered[1])
    best_distance = -1.0
    for a, b in combinations(ordered, 2):
        distance = _distance_mm(axes[a.designator], axes[b.designator])
        if distance > best_distance:
            best_distance = distance
            best = (a, b)
    return best


def _candidates(
    correspondences: tuple[Correspondence, ...],
    axes: dict[str, _Point],
    tolerance_nm: Nanometre,
) -> tuple[Placement, ...]:
    """Every distinct rigid placement the correspondences imply.

    A candidate is identified by the exact, discrete set of correspondences
    it validates (rule 3) -- two seed pairs reaching the same set collapse
    to one entry in ``seen`` before a ``Placement`` is ever built.
    """
    tolerance_mm = _mm(tolerance_nm)
    seen: dict[frozenset[tuple[str, int]], tuple[Correspondence, ...]] = {}
    ordered = sorted(correspondences, key=lambda c: c.designator)
    for first, second in combinations(ordered, 2):
        anchor_a: _Anchor = (axes[first.designator], first.hole_xy_nm)
        anchor_b: _Anchor = (axes[second.designator], second.hole_xy_nm)
        part_gap = _distance_mm(axes[first.designator], axes[second.designator])
        hole_gap = _distance_mm(first.hole_xy_nm, second.hole_xy_nm)
        if abs(part_gap - hole_gap) > 2 * tolerance_mm:
            continue
        if _chirality_conflict(correspondences, axes, first, second, tolerance_nm):
            continue
        transform = _transform(anchor_a, anchor_b)
        if transform is None:
            continue
        validated = _validate(correspondences, axes, transform, tolerance_nm, first, second)
        key = frozenset((c.designator, c.hole_index) for c in validated)
        seen.setdefault(key, validated)
    placements = []
    for validated in seen.values():
        wide_a, wide_b = _widest_pair(validated, axes)
        final = _transform(
            (axes[wide_a.designator], wide_a.hole_xy_nm),
            (axes[wide_b.designator], wide_b.hole_xy_nm),
        )
        assert final is not None
        x_mm, y_mm, theta_rad = final
        placements.append(
            Placement(
                rank=1,
                x_nm=nm_from_mm(x_mm),
                y_nm=nm_from_mm(y_mm),
                z_nm=Nanometre(0),
                theta_deg=math.degrees(theta_rad),
                correspondence=validated,
                clashes=(),
            )
        )
    return tuple(placements)


class Match:
    """Pairs each board's protrusions with holes and enumerates placements.

    Satisfies ``stompmodel.protocols.Stage[DockData]``. Reads only what
    ``DockData`` already states -- ``boards`` and ``holes`` -- so it neither
    depends on nor asserts that any other stage ran first. Recording this
    stage's own ``describe()`` into a document's processing history is
    ``Pipeline.run``'s job, not ``apply``'s -- a stage records nothing about
    itself.
    """

    name: ClassVar[str] = "match"

    def __init__(self, tolerance_nm: Nanometre) -> None:
        self._tolerance_nm = tolerance_nm

    def describe(self) -> StageRun:
        """Record the recognition tolerance this stage was configured with."""
        return StageRun(self.name, (("tolerance_nm", int(self._tolerance_nm)),))

    def apply(self, data: DockData) -> DockData:
        boards: list[Board] = []
        placements: dict[int, tuple[Placement, ...]] = {}
        diagnostics: list[Diagnostic] = []
        claimed_hole_indices: set[int] = set()

        for board in data.boards:
            new_board, board_placements, board_diagnostics, claimed = _match_board(
                board, data.holes, self._tolerance_nm
            )
            boards.append(new_board)
            diagnostics.extend(board_diagnostics)
            claimed_hole_indices.update(claimed)
            if board_placements:
                placements[board.ordinal] = board_placements

        unmatched = tuple(
            sorted(
                hole.index
                for hole in data.holes
                if hole.index is not None and hole.index not in claimed_hole_indices
            )
        )
        return replace(
            data,
            boards=tuple(boards),
            placements=placements,
            unmatched_holes=unmatched,
        ).with_diagnostics(*diagnostics)


def _match_board(
    board: Board, holes: tuple[Hole, ...], tolerance_nm: Nanometre
) -> tuple[Board, tuple[Placement, ...], tuple[Diagnostic, ...], tuple[int, ...]]:
    """One board's whole story: face selection, then candidates.

    Returns the (possibly face-annotated) board, its placements, the
    diagnostics it earned, and the hole indices it claims -- kept together
    because a board that fails face selection claims none of either.
    """
    components = {c.designator: c for c in board.components}
    axes_plus = _axes_for_face(board, _AS_EXPORTED)
    axes_minus = _axes_for_face(board, _FLIPPED)
    corr_plus = _pair_face(components, axes_plus, holes, tolerance_nm)
    corr_minus = _pair_face(components, axes_minus, holes, tolerance_nm)

    if corr_plus is None or corr_minus is None:
        return (
            board,
            (),
            (Diagnostic.error("ambiguous-pairing", f"board {board.ordinal}: two protrusions claim one hole"),),
            (),
        )

    count_plus, count_minus = len(corr_plus), len(corr_minus)
    if count_plus == 0 and count_minus == 0:
        return (
            board,
            (),
            (Diagnostic.error("no-correspondence", f"board {board.ordinal}: no protrusion pairs with a hole"),),
            (),
        )
    if count_plus == count_minus:
        return (
            board,
            (),
            (Diagnostic.error(
                "both-faced-group",
                f"board {board.ordinal}: {count_plus} pairings on each face",
            ),),
            (),
        )

    if count_plus > count_minus:
        face, axes, correspondences = _AS_EXPORTED, axes_plus, corr_plus
    else:
        face, axes, correspondences = _FLIPPED, axes_minus, corr_minus

    new_board = replace(board, panel_face=face)
    claimed = tuple(c.hole_index for c in correspondences)

    if len(correspondences) < 2:
        return (
            new_board,
            (),
            (Diagnostic.warning(
                "under-constrained-board",
                f"board {board.ordinal}: only {len(correspondences)} correspondence(s)",
            ),),
            claimed,
        )

    candidates = _candidates(correspondences, axes, tolerance_nm)
    if not candidates:
        return (
            new_board,
            (),
            (Diagnostic.error(
                "no-valid-placement",
                f"board {board.ordinal}: no candidate transform fits within tolerance",
            ),),
            claimed,
        )
    return new_board, candidates, (), claimed
