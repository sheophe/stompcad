"""Where the enclosure stops a board, found by searching its insertion path.

Hole geometry says how deep a board *would* sit; the case is what really
stops it, and the answer is where contact happens **first** along the path
from the entry pose. Seat-then-retreat finds a clear depth rather than a
reachable one -- a board can pass an obstruction and be clear beyond it --
so this searches instead, over a path bounded by geometry rather than by
that prediction. See "The case is what stops a board, and finding where is
a search" in ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from stompgeom.shapes import centre_of_mass_mm, common, compound, interferes, placed
from stompgeom.step import BoxMm, StepSolid, bounding_box_mm
from stompmodel.frames import CoordinateFrame, RigidTransform
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

from .errors import StompcolliderError
from .model import Board, Placement
from .solids import (
    MODEL_FRAME,
    board_solid_name,
    boxes_overlap,
    face_box,
    placement_transform,
    solid_name,
)

__all__ = [
    "PITCH_MAX_PARAMETER",
    "PITCH_MIN_PARAMETER",
    "Insertion",
    "Cavity",
    "CaseCavity",
    "CavitySplit",
    "beyond_cavity",
    "contact_depth",
]

#: The two pitches a run's insertion search was configured with, recorded in
#: ``Seat``'s own ``describe()``. Named here beside the search they bound, so
#: the command line and the report read one spelling of each.
PITCH_MAX_PARAMETER: str = "seat_pitch_max_nm"
PITCH_MIN_PARAMETER: str = "seat_pitch_min_nm"


@dataclass(frozen=True, slots=True)
class Insertion:
    """How far the enclosure lets one placement travel, and what stopped it.

    Three states, distinguished without a flag: ``obstruction`` is ``None``
    where nothing on the path touches the board, so the holes fix its
    depth; a ``depth_nm`` beside an obstruction is where the enclosure
    arrested it, which may be **deeper** than the holes alone predicted;
    and a ``depth_nm`` of ``None`` is a board that cannot enter at all,
    which is never reported as a travel of zero. ``lid_nm`` is how far the
    resting board reaches into whatever closes over the cavity, and takes
    no part in the travel.
    """

    depth_nm: Nanometre | None
    part: str | None = None
    obstruction: str | None = None
    lid_nm: Nanometre | None = None
    lid_solid: str | None = None

    def __post_init__(self) -> None:
        if self.depth_nm is None and self.obstruction is None:
            raise ValueError(
                "a board that reached no depth was stopped by something: state it"
            )
        if (self.lid_nm is None) != (self.lid_solid is None):
            raise ValueError("a board meeting the lid names the solid it met")

    @property
    def arrested(self) -> bool:
        """Whether the enclosure, rather than the hole geometry, fixed this depth.

        Not "stopped short": the enclosure is what decides the depth, and it
        frequently lets a board further in than its own profile predicted.
        Whether the answer falls short of that prediction is a comparison
        ``Seat`` makes against the placement it asked about.
        """
        return self.depth_nm is not None and self.obstruction is not None


@runtime_checkable
class Cavity(Protocol):
    """What ``Seat`` asks the enclosure: where one placement's travel ends.

    A protocol rather than the class below directly, so the seating rules
    are testable with arithmetic and no kernel -- the arrangement
    ``stompdrill``'s ``CaseModel`` already uses for clearance. ``Seat``
    needs no other verb: the pitches come back through ``parameters`` for
    its own provenance record.
    """

    def insertion(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> Insertion: ...

    def parameters(self) -> tuple[tuple[str, int], ...]: ...


def contact_depth(
    blocked: Callable[[Nanometre], bool],
    entry_nm: Nanometre,
    limit_nm: Nanometre,
    pitch_max_nm: Nanometre,
    pitch_min_nm: Nanometre,
) -> Nanometre | None:
    """The deepest reachable travel, or ``None`` when the entry pose is blocked.

    Coarse to fine, bounded from above: a blocked sample bounds the answer,
    so nothing beyond the first one is sampled again. The bracket it leaves
    is swept once at the finest pitch -- which subsumes every intermediate
    halving -- and then bisected over whole nanometres. Exact rather than
    convergent: canonical lengths are a finite ordered set, so the last
    step lands on an integer and not at a tolerance. ``limit_nm`` is the
    last travel at which contact is possible at all, and it is returned
    unchanged where the whole path is clear -- which is the caller's signal
    that this enclosure says nothing about where the board rests.
    """
    if entry_nm >= limit_nm:
        return limit_nm
    if blocked(entry_nm):
        return None
    clear, found = entry_nm, None
    for depth in _samples(entry_nm, limit_nm, pitch_max_nm, inclusive=True):
        if blocked(depth):
            found = depth
            break
        clear = depth
    if found is None:
        return limit_nm
    for depth in _samples(clear, found, pitch_min_nm, inclusive=False):
        if blocked(depth):
            found = depth
            break
        clear = depth
    while found - clear > 1:
        middle = Nanometre((clear + found) // 2)
        if blocked(middle):
            found = middle
        else:
            clear = middle
    return clear


def _samples(
    low: Nanometre, high: Nanometre, pitch_nm: Nanometre, *, inclusive: bool
) -> Iterator[Nanometre]:
    """The depths between ``low`` and ``high``, ``low`` excluded.

    ``high`` is yielded last when ``inclusive``, which is what makes the
    far end of the path always tested however the pitch divides it -- a
    band ending exactly there is the common case and a scan that stopped
    one pitch short would step over it. A pitch under one nanometre is one
    nanometre: the canonical representation states no finer depth.
    """
    step = max(int(pitch_nm), 1)
    depth = low + step
    while depth < high:
        yield Nanometre(depth)
        depth += step
    if inclusive:
        yield high


def beyond_cavity(
    case_solids: Sequence[StepSolid],
    basis: CoordinateFrame,
    extent_nm: tuple[Nanometre, Nanometre, Nanometre],
) -> tuple[tuple[StepSolid, ...], tuple[StepSolid, ...]]:
    """Split the case into what a board is inserted into and what closes over it.

    Geometry decides, never a product name. The **drilled** solid straddles
    the face frame's own plane and the mouth is how deep it reaches; what
    closes over the cavity lies beyond that mouth by its centre of mass
    *and* spans at least as much as the board both ways across the face.
    Both halves are needed -- a screw fastening the backplate on occupies
    the very depths it does -- and neither is a threshold. A case carrying
    no drilled face states no mouth, and nothing is beyond it.
    """
    boxes = [(solid, face_box(solid.box_mm, basis)) for solid in case_solids]
    drilled = [box for _solid, box in boxes if box[2] <= 0.0 <= box[5]]
    if not drilled:
        return (tuple(case_solids), ())
    mouth = min(box[2] for box in drilled)
    across_nm = sorted(extent_nm, reverse=True)[:2]
    # Kept by position rather than by value: two solids of one enclosure can
    # compare equal on kernel identity, and a split that dropped either would
    # quietly stop checking it.
    closing = {
        index
        for index, (solid, box) in enumerate(boxes)
        if basis.to_canonical(centre_of_mass_mm(solid.shape))[2] < mouth
        and _covers(box, across_nm)
    }
    inside = tuple(s for i, (s, _b) in enumerate(boxes) if i not in closing)
    beyond = tuple(s for i, (s, _b) in enumerate(boxes) if i in closing)
    return inside, beyond


def _covers(box: BoxMm, across_nm: Sequence[Nanometre]) -> bool:
    """Whether ``box`` spans at least as much across the face as a board does.

    Spans rather than positions, so the answer is one fact about the case
    and this board rather than one per candidate seating: a solid counted as
    the backplate under one placement and as an obstruction under another
    would report the same geometry two ways. A backplate narrower than the
    board it covers is read as an obstruction instead, which states the
    interference as a shortfall rather than as a case that will not close --
    a different finding about the same measured overlap, never silence.
    """
    lateral = sorted(
        (nm_from_mm(box[3] - box[0]), nm_from_mm(box[4] - box[1])), reverse=True
    )
    return all(theirs >= mine for theirs, mine in zip(lateral, across_nm, strict=True))


class CavitySplit:
    """:func:`beyond_cavity` over one run's case solids, measured once each.

    Shared because two stages need the same split and must not disagree
    about it: the search walks a board into the cavity, and the clash stage
    filters its seatings on that same cavity while still reporting what the
    closure meets. The split costs a centre of mass per solid, so it is
    memoised on the only two things it varies with.
    """

    def __init__(self, case_solids: Sequence[StepSolid]) -> None:
        self._case: tuple[StepSolid, ...] = tuple(case_solids)
        self._split: dict[
            tuple[CoordinateFrame, tuple[Nanometre, Nanometre, Nanometre]],
            tuple[tuple[StepSolid, ...], tuple[StepSolid, ...]],
        ] = {}

    def of(
        self,
        basis: CoordinateFrame,
        extent_nm: tuple[Nanometre, Nanometre, Nanometre],
    ) -> tuple[tuple[StepSolid, ...], tuple[StepSolid, ...]]:
        """What a board of ``extent_nm`` is inserted into, and what closes over it."""
        key = (basis, extent_nm)
        cached = self._split.get(key)
        if cached is None:
            cached = beyond_cavity(self._case, basis, extent_nm)
            self._split[key] = cached
        return cached


@dataclass(frozen=True, slots=True)
class _Part:
    """One board solid as the search reads it: named, placed, boxed on the face.

    ``box`` is this solid's own extent in the face frame with the board's
    origin plane on that face, so the extent at travel ``t`` is this box
    shifted by ``t`` along ``w`` -- which is what lets the whole path be
    filtered from boxes measured once.
    """

    name: str
    solid: StepSolid
    box: BoxMm


class CaseCavity:
    """The enclosure a board is inserted into, and how deep it lets one in.

    Satisfies :class:`Cavity`. Impure like ``Clashes`` and for the same
    reason: the question is about solids. The predicate is a positive shared
    volume through ``stompgeom.interferes``, which carries the two kernel
    settings this use needs; contact is not interference, so a board may
    advance to a pose where it merely touches.
    """

    def __init__(
        self,
        case_solids: Sequence[StepSolid],
        board_solids: Mapping[int, Sequence[StepSolid]],
        pitch_max_nm: Nanometre,
        pitch_min_nm: Nanometre,
    ) -> None:
        self._case: tuple[StepSolid, ...] = tuple(case_solids)
        self._boards: dict[int, tuple[StepSolid, ...]] = {
            ordinal: tuple(solids) for ordinal, solids in board_solids.items()
        }
        self._pitch_max_nm = pitch_max_nm
        self._pitch_min_nm = pitch_min_nm
        self._split = CavitySplit(self._case)

    def parameters(self) -> tuple[tuple[str, int], ...]:
        """The two pitches this search ran at, for ``Seat``'s provenance."""
        return (
            (PITCH_MAX_PARAMETER, int(self._pitch_max_nm)),
            (PITCH_MIN_PARAMETER, int(self._pitch_min_nm)),
        )

    def insertion(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> Insertion:
        """How far ``board`` travels toward the seat ``placement`` states.

        The travel is ``+w``, from outside the open end toward the drilled
        face: a board is inserted through the cavity mouth and its controls
        emerge through the holes, never the other way about.
        """
        seat_nm = placement.z_nm
        inside, beyond = self._split.of(basis, board.extent_nm)
        parts = self._parts(board, placement, basis)
        if not parts:
            return Insertion(seat_nm)
        case = [(solid, face_box(solid.box_mm, basis)) for solid in inside]
        bracket = _bracket(parts, [box for _solid, box in case])
        if bracket is None:
            return self._closing(board, placement, basis, parts, beyond, seat_nm)
        entry_nm, limit_nm = bracket

        depth_nm = contact_depth(
            lambda depth: self._meets(board, placement, basis, parts, case, depth),
            entry_nm,
            limit_nm,
            self._pitch_max_nm,
            self._pitch_min_nm,
        )
        if depth_nm == limit_nm:
            # The whole path is clear, so this enclosure states nothing about
            # where the board rests and the hole geometry is the only thing
            # that does -- the same answer a run with no case model gets.
            return self._closing(board, placement, basis, parts, beyond, seat_nm)

        # The shallowest blocked depth, which the search leaves one nanometre
        # above the answer -- or the entry pose itself, which is what a board
        # that cannot go in at all was stopped at.
        blocking = Nanometre(entry_nm if depth_nm is None else depth_nm + 1)
        obstruction = self._obstruction(
            board, placement, basis, parts, case, blocking
        )
        if obstruction is None:  # pragma: no cover - the depth was blocked there
            raise StompcolliderError(
                "the insertion search found a contact it cannot name a solid for"
            )
        part = self._culprit(
            board, placement, basis, parts, case, obstruction, blocking
        )
        if depth_nm is None:  # pragma: no cover - see the note on _entry
            return Insertion(None, part, obstruction)
        return replace(
            self._closing(board, placement, basis, parts, beyond, depth_nm),
            part=part,
            obstruction=obstruction,
        )

    def _parts(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> tuple[_Part, ...]:
        """This board's solids, boxed on the face with its origin plane on it."""
        solids = self._boards.get(board.ordinal, ())
        motion = placement_transform(
            board, replace(placement, z_nm=Nanometre(0)), basis
        )
        group = f"board:{board.ordinal}"
        return tuple(
            _Part(
                board_solid_name(solid, solid.box_mm, group),
                solid,
                face_box(solid.box_mm, basis, motion),
            )
            for solid in solids
        )

    def _meets(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        parts: Sequence[_Part],
        case: Sequence[tuple[StepSolid, BoxMm]],
        depth_nm: Nanometre,
    ) -> bool:
        """Whether this board interferes with the enclosure at ``depth_nm``.

        One boolean for the whole pose rather than one per case solid: a
        shared region between two sets is a shared region between some pair
        in them, so one query answers the only question the search asks, and
        *which* pair it was is wanted once at the end rather than at every
        sample. Only the parts and solids whose boxes reach each other at
        this depth are passed, which is rule 2's own filter and changes no
        answer. The case solids go as a **sequence** and the board's as one
        compound: two solids of an enclosure routinely intersect each other
        -- a screw in its boss -- and a bundle that does is answered as
        nothing at all, while a board's own solids do not and the cheaper
        spelling is worth having.
        """
        motion = self._at(board, placement, basis, depth_nm)
        boxes = [(part, _shifted(part.box, depth_nm)) for part in parts]
        met = [
            solid.shape
            for solid, box in case
            if any(boxes_overlap(shifted, box) for _part, shifted in boxes)
        ]
        if not met:
            return False
        meeting = [
            placed(part.solid.shape, motion)
            for part, shifted in boxes
            if any(boxes_overlap(shifted, box) for _solid, box in case)
        ]
        return bool(meeting) and interferes(compound(meeting), met)

    def _obstruction(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        parts: Sequence[_Part],
        case: Sequence[tuple[StepSolid, BoxMm]],
        depth_nm: Nanometre,
    ) -> str | None:
        """Which case solid this board meets at ``depth_nm``, asked once.

        The search itself never needs the name, so it is resolved here at
        the one depth a finding reports rather than at every sample.
        """
        motion = self._at(board, placement, basis, depth_nm)
        for solid, box in case:
            meeting = [
                placed(part.solid.shape, motion)
                for part in parts
                if boxes_overlap(_shifted(part.box, depth_nm), box)
            ]
            if meeting and interferes(compound(meeting), solid.shape):
                return solid_name(solid, solid.box_mm, "case")
        return None  # pragma: no cover - the compound said this depth is blocked

    def _culprit(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        parts: Sequence[_Part],
        case: Sequence[tuple[StepSolid, BoxMm]],
        obstruction: str,
        depth_nm: Nanometre,
    ) -> str | None:
        """Which of this board's own solids meets ``obstruction`` at ``depth_nm``.

        Asked once, at the shallowest blocked depth, rather than at every
        sample: a compound answers *whether* the board is stopped for a
        fraction of the cost, and *what* stops it is only wanted once the
        search has finished, and only over the parts whose boxes reach the
        solid at that depth. ``None`` where no single solid reproduces the
        compound's answer, which a near-tangent pose can leave; the case
        solid is named either way.
        """
        motion = self._at(board, placement, basis, depth_nm)
        for solid, box in case:
            if solid_name(solid, solid.box_mm, "case") != obstruction:
                continue
            for part in parts:
                if not boxes_overlap(_shifted(part.box, depth_nm), box):
                    continue
                if interferes(placed(part.solid.shape, motion), solid.shape):
                    return part.name
        return None  # pragma: no cover - a near-tangent pose no one solid repeats

    def _closing(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        parts: Sequence[_Part],
        beyond: Sequence[StepSolid],
        depth_nm: Nanometre,
    ) -> Insertion:
        """The resting board measured against whatever closes over the cavity.

        A finding rather than a constraint: a lid that will not close is
        what an operator runs this tool to discover, so it never removes a
        seating from consideration. Measured with the same exact
        intersection the clash stage reads, along the face normal, because
        the depth of the enclosure is the dimension that is short.
        """
        motion = self._at(board, placement, basis, depth_nm)
        for solid in beyond:
            box = face_box(solid.box_mm, basis)
            meeting = [
                placed(part.solid.shape, motion)
                for part in parts
                if boxes_overlap(_shifted(part.box, depth_nm), box)
            ]
            if not meeting:
                continue
            region = common(compound(meeting), solid.shape)
            if region is None:
                continue
            reach = bounding_box_mm(placed(region, basis.placement_onto(MODEL_FRAME)))
            short_nm = nm_from_mm(reach[5]) - nm_from_mm(reach[2])
            if short_nm > 0:
                return Insertion(
                    depth_nm,
                    lid_nm=Nanometre(short_nm),
                    lid_solid=solid_name(solid, solid.box_mm, "case"),
                )
        return Insertion(depth_nm)

    def _at(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        depth_nm: Nanometre,
    ) -> RigidTransform:
        """The motion putting ``board`` at ``depth_nm`` along the face normal."""
        return placement_transform(board, replace(placement, z_nm=depth_nm), basis)


def _shifted(box: BoxMm, depth_nm: Nanometre) -> BoxMm:
    """``box``, measured on the face with the board at zero, moved to ``depth_nm``.

    The board translates along ``w`` alone, so a box measured once at the
    origin plane bounds the same solid at every depth by adding the travel
    to its third axis. Measuring it again per sample would be the same
    answer at the price of the most expensive read this package has.
    """
    travel = mm_from_nm(depth_nm)
    return (box[0], box[1], box[2] + travel, box[3], box[4], box[5] + travel)


def _bracket(
    parts: Sequence[_Part], case: Sequence[BoxMm]
) -> tuple[Nanometre, Nanometre] | None:
    """The travels between which contact is possible, or ``None`` for none at all.

    The prefilter, and a sound one at both ends: a pair whose ``(u, v)``
    boxes miss each other no travel brings together; a pair that does
    overlap laterally meets no sooner than the difference of their ``w``
    extents, and no later than the travel that carries the part clear of the
    solid entirely. The union over-approximates at both ends, so it discards
    no contact.

    Every box bounds its own solid, so the first value is the first depth
    contact is possible at and an entry pose derived here cannot interfere:
    ``cannot-enter`` cannot arise from a supplied model. The second is what
    the search may travel to -- **not** the seat the holes fix, which is a
    prediction the exact geometry is entitled to overrule in either
    direction, and does: measured on the tar footswitch board, a bush
    tangent to its own bore leaves the profile stating a seating 11 mm
    shallower than the drilled plate does.
    """
    earliest: float | None = None
    latest: float | None = None
    for box in case:
        for part in parts:
            if not (
                part.box[0] <= box[3]
                and box[0] <= part.box[3]
                and part.box[1] <= box[4]
                and box[1] <= part.box[4]
            ):
                continue
            begins = box[2] - part.box[5]
            ends = box[5] - part.box[2]
            earliest = begins if earliest is None else min(earliest, begins)
            latest = ends if latest is None else max(latest, ends)
    if earliest is None or latest is None:
        return None
    return nm_from_mm(earliest), nm_from_mm(latest)
