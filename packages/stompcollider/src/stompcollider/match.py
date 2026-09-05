"""``Match``: registering a board into the panel frame, then recognising it.

Registration precedes recognition. A board reaches this stage in the frame
its CAD tool exported it in, so no protrusion lies near any hole until the
rigid motion carrying that frame onto the panel is known. Every part pair
is therefore seeded against every ordered hole pair -- separation is the
one quantity comparable before a transform exists -- and each seeded
transform is what pairing is judged under. A candidate is a seed
recognising as many protrusions as any other seed does; two is the floor.
"""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import combinations, permutations
from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import Hole, StageRun
from stompmodel.units import Nanometre, format_nm, mm_from_nm, nm_from_mm

from .model import (
    Board,
    Component,
    Correspondence,
    DockData,
    Placement,
    admitting_radius,
)

__all__ = ["Match", "PANEL_FACE", "TOLERANCE_PARAMETER"]

#: The key ``Match`` records its recognition tolerance under, and the key
#: the report reads it back from. Spelled once for the reason the pitch's
#: own key is: the tolerance is now usually derived rather than typed, so
#: this record is the only place an operator can see what recognised their
#: boards -- and a reader looking under a stale name would show nothing.
TOLERANCE_PARAMETER: str = "tolerance_nm"


#: Which side of the carrier plane points at the panel. Derived, never
#: searched: a board is seatable only when its components protrude *out*
#: through the drilled face, so the rotation placing it satisfies
#: ``R . w_board = w_panel``, and both bases are right-handed about their own
#: normals. That one equation fixes the handedness of the planar map, so a
#: reflected hypothesis is not a second candidate -- it is inadmissible.
PANEL_FACE: str = "+w"

#: (part axis, hole centre) in nanometres, both already in the same plane.
_Point = tuple[Nanometre, Nanometre]
_Anchor = tuple[_Point, _Point]

#: ``(x_mm, y_mm, theta_rad)``: a rigid planar motion, panel millimetres.
_Transform = tuple[float, float, float]

#: One recognised pairing, before it is measured into a ``Correspondence``.
_Pairing = tuple[str, Hole]


def _mm(value_nm: int) -> float:
    return mm_from_nm(Nanometre(value_nm))


def _distance_mm(a: _Point, b: _Point) -> float:
    return math.hypot(_mm(a[0] - b[0]), _mm(a[1] - b[1]))


def _centre(hole: Hole) -> _Point:
    return (hole.x_nm, hole.y_nm)


def _number(hole: Hole) -> int:
    """The drill number ``DockData.holes`` already guarantees every hole."""
    assert hole.index is not None
    return hole.index


def _axes(board: Board) -> dict[str, _Point]:
    """Every admitted protrusion's axis, in the board's own frame.

    Board coordinates, never panel ones: their origin and rotation relative
    to the panel are exactly what seeding solves for, so nothing read here
    may be compared against a hole until a transform exists.
    """
    return {
        component.designator: component.protrusion.axis_xy_nm
        for component in board.components
        if component.protrusion is not None
    }


def _insertion_nm(component: Component, hole: Hole) -> Nanometre | None:
    """The profile's own insertion depth through this hole -- a fact, not a
    fit judgement: recognition never rejects a pairing over it.

    Measured against the radius the hole admits, which is its own exactly.
    A **reported** measurement rather than the seat: where a board really
    comes to rest is the insertion search's answer, and a profile measured
    at a tangency states a depth the drilled plate does not agree with.
    """
    protrusion = component.protrusion
    assert protrusion is not None
    return protrusion.profile.insertion_through(admitting_radius(hole.diameter_nm))


def _seat_nm(component: Component, insertion_nm: Nanometre | None) -> Nanometre | None:
    """Where this pairing alone brings the board to rest, along the face normal.

    The insertion depth is measured from the part's tip and the board's own
    origin plane is where a placement's ``z`` is measured to, so the travel
    is the one less the other: negative, into the cavity. ``None`` for a
    part nothing stops, which holds the board nowhere.
    """
    if insertion_nm is None:
        return None
    protrusion = component.protrusion
    assert protrusion is not None
    return Nanometre(insertion_nm - protrusion.tip_nm)


def _exact(
    board: Board,
    components: dict[str, Component],
    candidates: tuple[tuple[_Pairing, ...], ...],
) -> tuple[Diagnostic, ...]:
    """``zero-clearance`` for a part exactly as wide as the hole it passes.

    An INFO finding, not a fault: comparison is strict, so a bush measuring
    12.000 mm into a 12.000 mm hole passes -- and a part fitting with
    nothing to spare is worth seeing. Quantified over the whole surviving
    set and stated once per part and hole, for the reason every other
    part-level finding here is: no candidate is singled out.
    """
    found: dict[tuple[str, int], None] = {}
    for pairings in candidates:
        for designator, hole in pairings:
            protrusion = components[designator].protrusion
            if protrusion is None:  # pragma: no cover - pairings carry an axis
                continue
            if protrusion.profile.meets(admitting_radius(hole.diameter_nm)):
                found.setdefault((designator, _number(hole)), None)
    return tuple(
        Diagnostic.info(
            "zero-clearance",
            f"board {board.ordinal}: {designator} is exactly as wide as hole "
            f"{number} and passes with nothing to spare",
            data=(("designator", designator), ("hole", number)),
        )
        for designator, number in sorted(found)
    )


def _transform(first: _Anchor, second: _Anchor) -> _Transform | None:
    """``(x_mm, y_mm, theta_rad)`` taking both parts onto both holes.

    ``None`` when the two parts coincide, which fixes no angle. Closed form:
    the angle between the two separation vectors, then the translation that
    lands the first part. A proper rotation is solved for, never a general
    affine fit, so no reflected hypothesis can be seeded at all.
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


def _apply(transform: _Transform, point_mm: tuple[float, float]) -> tuple[float, float]:
    x_mm, y_mm, theta = transform
    cos, sin = math.cos(theta), math.sin(theta)
    px, py = point_mm
    return (x_mm + cos * px - sin * py, y_mm + sin * px + cos * py)


def _offset_mm(transform: _Transform, axis: _Point, hole: Hole) -> float:
    """How far the registered axis lands from that hole's centre."""
    x_mm, y_mm = _apply(transform, (_mm(axis[0]), _mm(axis[1])))
    return math.hypot(x_mm - _mm(hole.x_nm), y_mm - _mm(hole.y_nm))


def _recognise(
    axes: dict[str, _Point],
    holes: tuple[Hole, ...],
    transform: _Transform,
    tolerance_mm: float,
) -> tuple[_Pairing, ...]:
    """Each registered axis against the hole nearest it, within tolerance.

    Injectivity is deliberately not forced: two parts landing on one hole is
    ``ambiguous-pairing``, a finding this stage must be able to make, and a
    nearest-wins fallback here would silently resolve it away.
    """
    pairings: list[_Pairing] = []
    for designator in sorted(axes):
        axis = axes[designator]
        nearest = min(holes, key=lambda hole: _offset_mm(transform, axis, hole))
        if _offset_mm(transform, axis, nearest) <= tolerance_mm:
            pairings.append((designator, nearest))
    return tuple(pairings)


def _widest_pair(designators: tuple[str, ...], axes: dict[str, _Point]) -> tuple[str, str]:
    """The two most widely separated corresponded protrusions, ties broken by
    designator order -- the best-conditioned pair a candidate can report from.

    Enumerated over designator-sorted pairs, so the first pair to reach the
    maximum distance is the one designator order prefers; only a strictly
    greater distance replaces it.
    """
    ordered = sorted(designators)
    best = (ordered[0], ordered[1])
    best_distance = -1.0
    for a, b in combinations(ordered, 2):
        distance = _distance_mm(axes[a], axes[b])
        if distance > best_distance:
            best_distance = distance
            best = (a, b)
    return best


def _key(pairings: tuple[_Pairing, ...]) -> tuple[tuple[str, int], ...]:
    """A candidate's identity: its exact, ordered correspondence set.

    Discrete and exact -- no rounding of x, y or theta, and therefore no
    angular resolution to choose. Two seeds reaching this same set are one
    candidate; nothing here prefers one candidate over another.
    """
    return tuple(sorted((designator, _number(hole)) for designator, hole in pairings))


def _seeds(
    axes: dict[str, _Point], holes: tuple[Hole, ...], tolerance_mm: float
) -> list[_Transform]:
    """Every rigid motion a part pair against an ordered hole pair implies.

    Separation is the only quantity comparable before a transform exists,
    and the one invariant under it. Both orderings of the hole pair are
    enumerated because which protrusion goes to which hole is itself part of
    the unknown. The two gaps must agree within *twice* the tolerance: two
    independent recognition errors, not one.
    """
    transforms: list[_Transform] = []
    for part_a, part_b in combinations(sorted(axes), 2):
        part_gap = _distance_mm(axes[part_a], axes[part_b])
        for hole_a, hole_b in permutations(holes, 2):
            hole_gap = _distance_mm(_centre(hole_a), _centre(hole_b))
            if abs(part_gap - hole_gap) > 2 * tolerance_mm:
                continue
            transform = _transform(
                (axes[part_a], _centre(hole_a)), (axes[part_b], _centre(hole_b))
            )
            if transform is not None:
                transforms.append(transform)
    return transforms


def _candidates(
    axes: dict[str, _Point], holes: tuple[Hole, ...], tolerance_nm: Nanometre
) -> tuple[tuple[_Pairing, ...], ...]:
    """Every registration recognising as many protrusions as any other does.

    A candidate recognising fewer than another is strictly dominated: a rigid
    motion demonstrably exists putting more of this board's parts through
    holes, so the poorer hypothesis is not a serious claim about where the
    board sits. A tie *at* the maximum is different in kind -- two genuinely
    symmetric seatings -- and every one of those is returned, because handing
    back one silently is how a pedal gets assembled mirror-imaged.
    """
    tolerance_mm = _mm(tolerance_nm)
    ordered = tuple(sorted(holes, key=_number))
    seen: dict[tuple[tuple[str, int], ...], tuple[_Pairing, ...]] = {}
    for transform in _seeds(axes, ordered, tolerance_mm):
        pairings = _recognise(axes, ordered, transform, tolerance_mm)
        # A surviving seed carries its own two protrusions onto their holes
        # exactly, so this states the rank of a rigid planar transform rather
        # than filtering anything a real seed produces.
        if len(pairings) >= 2:
            seen.setdefault(_key(pairings), pairings)
    if not seen:
        return ()
    most = max(len(pairings) for pairings in seen.values())
    # Sorted so this tuple is a function of the geometry alone and not of the
    # order seeds were enumerated in (ADR-0006). It states no preference:
    # ranking placements is ``Seat``'s, and it re-orders them anyway.
    return tuple(sorted(
        (pairings for pairings in seen.values() if len(pairings) == most), key=_key
    ))


def _placement(
    pairings: tuple[_Pairing, ...],
    axes: dict[str, _Point],
    components: dict[str, Component],
) -> tuple[Placement, _Transform]:
    """One registration's placement, measured under its own recomputed motion.

    The transform comes from the two most widely separated corresponded
    protrusions rather than from whichever seed happened to find the set --
    the best-conditioned pair available, and the only choice that makes the
    reported motion independent of enumeration order.
    """
    holes = dict(pairings)
    wide_a, wide_b = _widest_pair(tuple(holes), axes)
    final = _transform(
        (axes[wide_a], _centre(holes[wide_a])), (axes[wide_b], _centre(holes[wide_b]))
    )
    # The widest pair is at least as far apart as the seed pair that found
    # this set, and that one was non-degenerate.
    assert final is not None
    x_mm, y_mm, theta_rad = final
    correspondence = tuple(
        _correspondence(designator, hole, final, axes, components)
        for designator, hole in sorted(pairings, key=lambda pairing: pairing[0])
    )
    placement = Placement(
        rank=1,
        x_nm=nm_from_mm(x_mm),
        y_nm=nm_from_mm(y_mm),
        z_nm=Nanometre(0),
        theta_deg=math.degrees(theta_rad),
        correspondence=correspondence,
        clashes=(),
    )
    return placement, final


def _correspondence(
    designator: str,
    hole: Hole,
    transform: _Transform,
    axes: dict[str, _Point],
    components: dict[str, Component],
) -> Correspondence:
    """One pairing measured: how far it misses, how deep it goes, where it seats."""
    component = components[designator]
    insertion_nm = _insertion_nm(component, hole)
    return Correspondence(
        designator=designator,
        hole_index=_number(hole),
        hole_xy_nm=_centre(hole),
        insertion_nm=insertion_nm,
        offset_nm=nm_from_mm(_offset_mm(transform, axes[designator], hole)),
        seat_nm=_seat_nm(component, insertion_nm),
    )


def _claims(
    axes: dict[str, _Point],
    holes: tuple[Hole, ...],
    transform: _Transform,
    tolerance_mm: float,
) -> dict[int, tuple[str, ...]]:
    """Which registered axes lie within reach of each hole, under one motion."""
    claims: dict[int, list[str]] = {}
    for designator in sorted(axes):
        for hole in holes:
            if _offset_mm(transform, axes[designator], hole) <= tolerance_mm:
                claims.setdefault(_number(hole), []).append(designator)
    return {number: tuple(who) for number, who in claims.items()}


def _ambiguous(
    ordinal: int,
    axes: dict[str, _Point],
    holes: tuple[Hole, ...],
    transforms: tuple[_Transform, ...],
    tolerance_mm: float,
) -> tuple[Diagnostic, ...]:
    """``ambiguous-pairing`` for each hole two registered axes can reach.

    Raised when *any* returned candidate exposes it, which needs no candidate
    to be singled out: two parts within one tolerance of one hole stand
    closer together than the grid pitch itself, so the pathology is in the
    input rather than in the hypothesis that happened to reveal it.
    """
    found: dict[tuple[int, tuple[str, ...]], None] = {}
    for transform in transforms:
        for number, who in _claims(axes, holes, transform, tolerance_mm).items():
            if len(who) > 1:
                found.setdefault((number, who), None)
    return tuple(
        Diagnostic.error(
            "ambiguous-pairing",
            f"board {ordinal}: {' and '.join(who)} both claim hole {number}",
            data=(("hole", number),),
        )
        for number, who in sorted(found)
    )


def _missed(
    axes: dict[str, _Point],
    holes: tuple[Hole, ...],
    paired: frozenset[str],
    transforms: tuple[_Transform, ...],
) -> tuple[Diagnostic, ...]:
    """``unmatched-part`` for an admitted axis no candidate finds a hole for.

    Reported only for a part left loose under *every* returned candidate, so
    it needs no candidate singled out. The distance quoted is the smallest
    miss any of them achieves, because that is the useful number: a part a
    fraction of a millimetre out is a misplaced footprint worth seeing, and
    the same part read through a discarded seating is metres away.
    """
    findings: list[Diagnostic] = []
    for designator in sorted(axes):
        if designator in paired:
            continue
        axis = axes[designator]
        offset_mm, number = min(
            (_offset_mm(transform, axis, hole), _number(hole))
            for transform in transforms
            for hole in holes
        )
        offset_nm = nm_from_mm(offset_mm)
        findings.append(
            Diagnostic.warning(
                "unmatched-part",
                f"{designator} lands {format_nm(offset_nm)} mm from hole "
                f"{number}, its nearest",
                data=(
                    ("designator", designator),
                    ("nearest_hole", number),
                    ("offset_nm", int(offset_nm)),
                ),
            )
        )
    return tuple(findings)


def _several(ordinal: int, count: int) -> tuple[Diagnostic, ...]:
    """``ambiguous-placement`` when more than one seating survives.

    A symmetric hole pattern genuinely admits more than one, and every one
    of them is returned; this is what tells the operator to choose rather
    than to read the first row as the answer.
    """
    if count < 2:
        return ()
    return (
        Diagnostic.warning(
            "ambiguous-placement",
            f"board {ordinal}: {count} distinct placements fit equally well",
            data=(("board", ordinal), ("placements", count)),
        ),
    )


def _axisless(board: Board) -> tuple[Diagnostic, ...]:
    """``unmatched-part`` for an admitted part that yielded no cylinder.

    The code's second shape, told apart by the keys present rather than by a
    second code: a part with no axis has no distance to any hole under any
    motion, so it names neither a hole nor an offset -- and needs no
    registration to be reported at all.
    """
    return tuple(
        Diagnostic.warning(
            "unmatched-part",
            f"{component.designator} yields no axis and pairs with no hole",
            data=(("designator", component.designator),),
        )
        for component in sorted(board.components, key=lambda c: c.designator)
        if component.admitted and component.protrusion is None
    )


class Match:
    """Registers each board onto the panel and reports what it recognises.

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
        """Record the recognition tolerance this stage ran with."""
        return StageRun(self.name, ((TOLERANCE_PARAMETER, int(self._tolerance_nm)),))

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
    board: Board,
    holes: tuple[Hole, ...],
    tolerance_nm: Nanometre,
) -> tuple[Board, tuple[Placement, ...], tuple[Diagnostic, ...], tuple[int, ...]]:
    """One board's whole story: registration, then what it recognises.

    Returns the (possibly face-annotated) board, its placements, the
    diagnostics it earned, and the hole numbers it claims -- kept together
    because a board that registers nowhere claims none of either.
    """
    components = {component.designator: component for component in board.components}
    axes = _axes(board)

    if len(axes) < 2:
        return (
            board,
            (),
            (
                Diagnostic.warning(
                    "under-constrained-board",
                    f"board {board.ordinal}: {len(axes)} admitted protrusion(s), "
                    f"and two is the rank of a rigid planar transform",
                ),
            )
            + _axisless(board),
            (),
        )

    candidates = _candidates(axes, holes, tolerance_nm)
    if not candidates:
        return (
            board,
            (),
            (
                Diagnostic.error(
                    "no-correspondence",
                    f"board {board.ordinal}: no registration carries its parts "
                    f"onto this panel's holes",
                ),
            )
            + _axisless(board),
            (),
        )

    built = tuple(
        _placement(pairings, axes, components) for pairings in candidates
    )
    transforms = tuple(transform for _placement_, transform in built)
    # Every part-level finding below is judged over the whole surviving set,
    # never over one candidate singled out of it: which of several equally
    # good seatings the board is actually in is not settled here, and a
    # finding that changed with that choice would be a verdict this stage has
    # no evidence for.
    paired = frozenset(
        designator for pairings in candidates for designator, _hole in pairings
    )
    diagnostics = (
        _ambiguous(board.ordinal, axes, holes, transforms, _mm(tolerance_nm))
        + _several(board.ordinal, len(candidates))
        + _missed(axes, holes, paired, transforms)
        + _axisless(board)
        + _exact(board, components, candidates)
    )
    # A hole some surviving seating of this board covers is not a hole no
    # board covers, so the claim is the union rather than any one candidate's.
    claimed = {
        _number(hole) for pairings in candidates for _designator, hole in pairings
    }
    return (
        replace(board, panel_face=PANEL_FACE),
        tuple(placement for placement, _transform_ in built),
        diagnostics,
        tuple(sorted(claimed)),
    )
