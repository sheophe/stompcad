"""``Clashes``: what a placement overlaps, by how much, and against what.

The pipeline's one impure stage. ``Match`` and ``Seat`` fold over values;
this one folds over solids, reaching the kernel through ``stompgeom`` and
never through OCP. Bounding boxes filter the pairs and an exact
intersection decides every survivor, so no answer here is a proximity
estimate. Seating an assembly is two stages, the first a filter -- see
"Several boards" and "Clashes" in ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations, islice, product
from typing import Any, ClassVar

from stompgeom.shapes import common, compound, interferes, placed, volume_mm3
from stompgeom.step import StepSolid, bounding_box_mm
from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame
from stompmodel.model import StageRun
from stompmodel.units import Nanometre, format_nm, nm_from_mm

from .errors import StompcolliderError
from .insert import CavitySplit
from .model import CASE_KIND, CLOSURE_KIND, Board, Clash, DockData, Placement
from .seat import rank_key, shortfall_nm
from .solids import (
    MODEL_FRAME,
    Body,
    bodies,
    boxes_overlap,
    solid_name,
)

__all__ = ["Clashes"]

#: A clash's axis names one of the face frame's own three, never a model
#: axis: the frame the enclosure was drilled in is the frame a depth means
#: something in.
_AXES = ("u", "v", "w")

#: A board solid nobody named, exactly as :func:`solid_name` spells one: the
#: board it belongs to, and the corner that tells it from its neighbours.
_UNNAMED_BOARD_SOLID = re.compile(r"board:(\d+):unnamed@")

#: Cubic nanometres to the cubic millimetre, as an exact decimal.
_NM3_PER_MM3 = Decimal(10) ** 18

#: How many assemblies stage two will try. The Cartesian product of every
#: board's *case-clean* seatings is small in practice and frequently a
#: single element, but nothing in the geometry bounds it, so this does --
#: and a run that reaches it says so rather than truncating in silence.
_COMBINATION_LIMIT = 4096


def _nm3_from_mm3(volume_mm3_: float) -> int:
    """A measured volume as whole cubic nanometres.

    Exact decimal scaling before representation rounding, the boundary rule
    ADR-0003 fixes for every canonical quantity. Floored at zero: a volume
    is not negative, and a kernel answer a hair below it is a rounding
    artefact rather than a fact about the input.
    """
    scaled = (Decimal(str(volume_mm3_)) * _NM3_PER_MM3).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    return max(int(scaled), 0)


def _clash_from(
    region: Any,
    basis: CoordinateFrame,
    with_: str,
    kind: str,
    part: str | None = None,
) -> Clash | None:
    """``region`` as a clash in ``basis``, or ``None`` when it is contact.

    The region is moved into the face frame and measured there. Boxing it in
    the model frame first and reprojecting the eight corners of *that* box
    is a different quantity -- the box of a box -- and for any frame not a
    quarter turn about a model axis it is strictly larger: a 10 mm region
    reads 14.142 mm under a 45-degree frame. Depth is the least extent and
    the axis is that axis; zero nanometres is what the canonical
    representation says about contact, and contact is not a clash.
    """
    box = bounding_box_mm(placed(region, basis.placement_onto(MODEL_FRAME)))
    lows = tuple(nm_from_mm(box[axis]) for axis in range(3))
    highs = tuple(nm_from_mm(box[axis + 3]) for axis in range(3))
    extents = tuple(highs[axis] - lows[axis] for axis in range(3))
    least = min(range(3), key=lambda axis: extents[axis])
    if extents[least] == 0:
        return None
    # Two volumes, and they answer different questions. ``bbox_volume_nm3`` is
    # the box's own, the product of three canonical lengths and so exact
    # where a float mm^3 scaled to nm^3 would not be; it bounds the
    # material and over a whole board bounds it poorly. The material itself
    # is measured on the region the boolean already built, which is one
    # query on a shape nobody has to build twice. Volume is invariant under
    # a rigid motion, so it is read before the region is moved.
    return Clash(
        with_=with_,
        kind=kind,
        bbox_nm=(lows[0], lows[1], lows[2], highs[0], highs[1], highs[2]),
        depth_nm=Nanometre(extents[least]),
        axis=_AXES[least],
        bbox_volume_nm3=extents[0] * extents[1] * extents[2],
        common_volume_nm3=_nm3_from_mm3(volume_mm3(region)),
        part=part,
    )


def _pair_clash(
    first: Body,
    second: Body,
    basis: CoordinateFrame,
    with_: str,
    kind: str,
    part: str | None = None,
) -> Clash | None:
    """Filter the pair on bounding boxes, then decide it exactly.

    The whole of rule 2, stated once: a caller adding a third kind of thing
    to check gets the same filter and the same boolean rather than a second
    copy of either.
    """
    if not boxes_overlap(first.box, second.box):
        return None
    region = common(first.shape, second.shape)
    if region is None:
        return None
    return _clash_from(region, basis, with_, kind, part)


def _clash_key(clash: Clash) -> tuple[str, str, str, int, tuple[Nanometre, ...]]:
    """The spec's clash order, extended to a total one by part and box.

    ``part`` earns its place beside ``with``: several of one board's solids
    can meet the same solid of another, so the pair alone no longer
    separates two findings.
    """
    return (clash.kind, clash.with_, clash.part or "", int(clash.depth_nm), clash.bbox_nm)


class Clashes:
    """Fills each placement's ``clashes`` and re-ranks on what it found.

    Satisfies ``stompmodel.protocols.Stage[DockData]``. Each board is
    checked against **the whole of the rest of the assembly**. Seating is
    two stages: stage one ranks each board against the case alone and keeps
    every seating the cavity itself admits -- asked with the predicate the
    insertion search uses, so a board resting at contact passes; stage two
    picks, over the combinations of those, the assembly of least inter-board
    material. Reads only ``DockData.placements`` and ``.boards``, so it
    asserts no other stage ran, and ``describe()`` is ``Pipeline.run``'s to
    record.
    """

    name: ClassVar[str] = "clashes"

    def __init__(
        self,
        case_solids: Sequence[StepSolid],
        board_solids: Mapping[int, Sequence[StepSolid]],
    ) -> None:
        self._case: tuple[StepSolid, ...] = tuple(case_solids)
        self._boards: dict[int, tuple[StepSolid, ...]] = {
            ordinal: tuple(solids) for ordinal, solids in board_solids.items()
        }
        # Two memos over one run's geometry. A board's solids are placed
        # and bounded once per candidate seating however many combinations
        # read them, and a pair of seatings is intersected once however
        # many combinations hold both -- which is what keeps stage two's
        # product affordable rather than quadratic in the same booleans.
        self._placed: dict[tuple[int, Placement], tuple[Body, ...]] = {}
        self._pairs: dict[tuple[int, Placement, int, Placement], tuple[Clash, ...]] = {}
        # The same split the insertion search walks a board into, so the two
        # stages cannot disagree about which solid is the enclosure and which
        # closes over it.
        self._split = CavitySplit(self._case)

    def describe(self) -> StageRun:
        """Report the (parameterless) configuration this stage ran with."""
        return StageRun(self.name)

    def apply(self, data: DockData) -> DockData:
        basis = data.case.frame.basis
        boards = {board.ordinal: board for board in data.boards}

        ranked: dict[int, tuple[Placement, ...]] = {}
        clean: dict[int, tuple[Placement, ...]] = {}
        for ordinal in sorted(data.placements):
            board = self._board_for(ordinal, boards)
            filled = [
                (
                    replace(
                        placement, clashes=self._against_case(board, placement, basis)
                    ),
                    self._clears_the_cavity(board, placement, basis),
                )
                for placement in data.placements[ordinal]
            ]
            order = sorted(filled, key=lambda pair: rank_key(pair[0]))
            numbered = [
                replace(placement, rank=rank)
                for rank, (placement, _clear) in enumerate(order, start=1)
            ]
            ranked[ordinal] = tuple(numbered)
            clean[ordinal] = tuple(
                placement
                for placement, (_seated, clear) in zip(numbered, order, strict=True)
                if clear
            )

        seated, notes = self._assembly(ranked, clean, boards, basis)
        return replace(
            data,
            placements=seated,
            diagnostics=data.diagnostics + _findings(seated) + notes,
        )

    def _board_for(self, ordinal: int, boards: Mapping[int, Board]) -> Board:
        """The board these placements belong to, with the solids to check.

        Refused rather than skipped: rule 1 is a claim about the whole
        assembly, so a board this stage was handed no geometry for would
        report no clashes and look exactly like one that has none.
        """
        if ordinal not in boards:
            raise StompcolliderError(
                f"placements are ranked for board {ordinal}, which the data holds no board for"
            )
        if not self._boards.get(ordinal):
            raise StompcolliderError(
                f"board {ordinal} has placements to check but no solids were supplied for it"
            )
        return boards[ordinal]

    def _bodies(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> tuple[Body, ...]:
        """This board's solids, each named and bounded, under one placement."""
        key = (board.ordinal, placement)
        cached = self._placed.get(key)
        if cached is None:
            cached = bodies(board, placement, basis, self._boards[board.ordinal])
            self._placed[key] = cached
        return cached

    def _against_case(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> tuple[Clash, ...]:
        """Every case solid this placement meets. None is privileged or exempt.

        Stated per case solid rather than per pair of solids: a wall is one
        thing to move the board away from, however many of its parts reach
        into it. Only the parts whose boxes reach that solid are compounded
        for the boolean, which is rule 2's own filter and changes no answer
        -- a solid whose box misses cannot contribute to the shared region.
        Each finding carries whether it is against the cavity or against
        what closes over it, which decides nothing about what is reported
        and everything about what may rank a seating.
        """
        inside, beyond = self._split.of(basis, board.extent_nm)
        bodies = self._bodies(board, placement, basis)
        found = []
        for solid, kind in [(one, CASE_KIND) for one in inside] + [
            (one, CLOSURE_KIND) for one in beyond
        ]:
            box = solid.box_mm
            meeting = [body.shape for body in bodies if boxes_overlap(body.box, box)]
            if not meeting:
                continue
            region = common(compound(meeting), solid.shape)
            if region is None:
                continue
            clash = _clash_from(region, basis, solid_name(solid, box, "case"), kind)
            if clash is not None:
                found.append(clash)
        return tuple(sorted(found, key=_clash_key))

    def _clears_the_cavity(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> bool:
        """Whether the enclosure this board is inserted into admits this seating.

        **The predicate the insertion search asks**, not the exact
        intersection the findings are measured with, and one coherent rule
        rather than a threshold laid over two. A board the search advanced
        to rest at first contact lies within a nanometre of what stopped it,
        and the exact boolean finds a sliver there; asking a second
        definition here left every real seating failing this filter, and the
        mutual-interference stage behind it never ran at all.

        What closes over the cavity takes no part: the board is inserted
        into an open case and the backplate goes on afterwards, so a lid
        that will not close is a finding rather than a seating refused.

        The case solids go as a sequence, for the reason ``CaseCavity``'s
        own predicate passes them that way.
        """
        inside, _beyond = self._split.of(basis, board.extent_nm)
        bodies = self._bodies(board, placement, basis)
        met = [
            solid.shape
            for solid in inside
            if any(boxes_overlap(body.box, solid.box_mm) for body in bodies)
        ]
        if not met:
            return True
        meeting = [
            body.shape
            for body in bodies
            if any(boxes_overlap(body.box, solid.box_mm) for solid in inside)
        ]
        return not interferes(compound(meeting), met)

    def _between(
        self,
        first: Board,
        first_placement: Placement,
        second: Board,
        second_placement: Placement,
        basis: CoordinateFrame,
    ) -> tuple[Clash, ...]:
        """Every pair of solids of two boards that meets, named on both sides.

        Per solid rather than per board: "board 1 clashes with board 2" is
        not something a person can act on, and the aggregate that is worth
        stating is a sum over exactly these.
        """
        key = (first.ordinal, first_placement, second.ordinal, second_placement)
        cached = self._pairs.get(key)
        if cached is None:
            found = [
                clash
                for mine in self._bodies(first, first_placement, basis)
                for theirs in self._bodies(second, second_placement, basis)
                if (clash := _pair_clash(mine, theirs, basis, theirs.name, "board", mine.name))
                is not None
            ]
            cached = tuple(sorted(found, key=_clash_key))
            self._pairs[key] = cached
        return cached

    def _assembly(
        self,
        ranked: Mapping[int, tuple[Placement, ...]],
        clean: Mapping[int, tuple[Placement, ...]],
        boards: Mapping[int, Board],
        basis: CoordinateFrame,
    ) -> tuple[dict[int, tuple[Placement, ...]], tuple[Diagnostic, ...]]:
        """Stage two: which of the cavity-clean seatings this assembly is made of.

        The case takes no part here, having already been answered in stage
        one. A board no seating clears the cavity for is fixed at its
        stage-one rank 1 and says so, because a seating that fouls the
        enclosure cannot be improved by anything a neighbour does -- and
        because a reader could not otherwise tell a chosen seating from a
        defaulted one.
        """
        notes: list[Diagnostic] = []
        candidates = self._candidates(ranked, clean, notes)
        ordinals = sorted(candidates)
        possible = math.prod(len(candidates[ordinal]) for ordinal in ordinals)
        tried = list(
            islice(
                product(*(candidates[ordinal] for ordinal in ordinals)),
                _COMBINATION_LIMIT,
            )
        )
        if possible > _COMBINATION_LIMIT:
            notes.append(
                Diagnostic.info(
                    "seating-search-bounded",
                    f"{possible} assemblies of case-clean seatings are possible and "
                    f"the first {_COMBINATION_LIMIT} were tried, so one of less "
                    f"mutual interference may lie outside them",
                    data=(("limit", _COMBINATION_LIMIT), ("combinations", possible)),
                )
            )
        chosen, pairs = self._least_interference(ordinals, tried, boards, basis)
        extra: dict[int, list[Clash]] = {ordinal: [] for ordinal in ordinals}
        for (first, second), found in sorted(pairs.items()):
            if not found:
                continue
            extra[first].extend(found)
            notes.append(_summary(first, second, found))
        seated = {
            ordinal: _with_assembly_clashes(
                _chosen_first(placements, chosen.get(ordinal)), extra.get(ordinal, [])
            )
            for ordinal, placements in ranked.items()
        }
        return seated, tuple(notes)

    def _candidates(
        self,
        ranked: Mapping[int, tuple[Placement, ...]],
        clean: Mapping[int, tuple[Placement, ...]],
        notes: list[Diagnostic],
    ) -> dict[int, tuple[Placement, ...]]:
        """Stage one's survivors: the seatings the cavity admits *and* that seat.

        Two conditions, and the second is not redundant. A board the case
        arrests well out of it clears the cavity by resting against it, and
        it fouls a neighbour less than the seating that really goes in --
        precisely because it never went in. Measured on the tar assembly,
        that is a 14 mm shortfall winning stage two outright. So a seating
        that inserts less far than another of the same board is not a
        candidate, exactly as one that fouls the enclosure is not; what
        stage two then chooses among is boards that are all equally seated,
        and mutual interference alone decides between them.
        """
        candidates: dict[int, tuple[Placement, ...]] = {}
        for ordinal in sorted(ranked):
            placements = ranked[ordinal]
            if not placements:
                continue
            admitted = _best_seated(clean.get(ordinal, ()))
            candidates[ordinal] = admitted or (placements[0],)
            if admitted:
                continue
            notes.append(
                Diagnostic.info(
                    "every-seating-clashes",
                    f"board {ordinal}: no seating of it clears the case, so it took "
                    f"no part in choosing the assembly",
                    data=(("board", ordinal),),
                )
            )
        return candidates

    def _least_interference(
        self,
        ordinals: Sequence[int],
        tried: Sequence[tuple[Placement, ...]],
        boards: Mapping[int, Board],
        basis: CoordinateFrame,
    ) -> tuple[dict[int, Placement], dict[tuple[int, int], tuple[Clash, ...]]]:
        """The assembly of least inter-board material among those tried.

        Ties fall through to the stage-one ranks, which are themselves a
        function of the geometry, so the answer never depends on the order
        the product enumerated (ADR-0006).
        """
        best: tuple[tuple[int, tuple[int, ...]], dict[Any, Any], dict[Any, Any]] | None
        best = None
        for combination in tried:
            pairs: dict[tuple[int, int], tuple[Clash, ...]] = {}
            for (first, mine), (second, theirs) in combinations(
                zip(ordinals, combination, strict=True), 2
            ):
                pairs[(first, second)] = self._between(
                    boards[first], mine, boards[second], theirs, basis
                )
            total = sum(
                clash.common_volume_nm3 for found in pairs.values() for clash in found
            )
            key = (total, tuple(one.rank for one in combination))
            if best is None or key < best[0]:
                best = (key, dict(zip(ordinals, combination, strict=True)), pairs)
        if best is None:  # pragma: no cover - product() always yields one tuple
            return {}, {}
        return best[1], best[2]


def _best_seated(placements: Sequence[Placement]) -> tuple[Placement, ...]:
    """Those of ``placements`` that insert as far as any of them does.

    Exact equality of whole nanometres, so a genuinely symmetric pair -- the
    case a second seating exists to report at all -- survives whole, and a
    board that merely leant on the enclosure does not.
    """
    if not placements:
        return ()
    least = min(shortfall_nm(placement) for placement in placements)
    return tuple(
        placement for placement in placements if shortfall_nm(placement) == least
    )


def _chosen_first(
    placements: tuple[Placement, ...], chosen: Placement | None
) -> tuple[Placement, ...]:
    """``chosen`` at rank 1, the rest behind it in the order stage one gave.

    Renumbered rather than reordered alone: the model is written at rank 1
    and the report reads the same field, so a seating stage two picked has
    to *be* rank 1 or neither artefact would show it.
    """
    if chosen is None or not placements:
        return placements
    index = next(
        position for position, one in enumerate(placements) if one is chosen
    )
    ordered = (placements[index], *placements[:index], *placements[index + 1:])
    return tuple(
        replace(one, rank=rank) for rank, one in enumerate(ordered, start=1)
    )


def _with_assembly_clashes(
    placements: tuple[Placement, ...], extra: Sequence[Clash]
) -> tuple[Placement, ...]:
    """Add the assembly's findings to the rank-1 placement alone."""
    if not extra:
        return placements
    first = placements[0]
    merged = tuple(sorted(first.clashes + tuple(extra), key=_clash_key))
    return (replace(first, clashes=merged), *placements[1:])


def _stated_mm(depth_nm: Nanometre) -> str:
    """``depth_nm`` in millimetres, never rounded away to nothing.

    Three decimals is what the rest of the workspace states a length at, but
    rule 3's whole content is that one nanometre is a fact and contact is
    not, and "0.000 mm" erases exactly that distinction in the half of the
    report a person reads. Six decimals states any whole nanometre exactly,
    so the fallback cannot round to zero either.
    """
    stated = format_nm(depth_nm, 3)
    if stated == format_nm(Nanometre(0), 3):
        return format_nm(depth_nm, 6)
    return stated


def _mm3(volume_nm3: int, decimals: int) -> str:
    quantum = Decimal(1).scaleb(-decimals)
    return str(
        (Decimal(volume_nm3) / _NM3_PER_MM3).quantize(quantum, rounding=ROUND_HALF_UP)
    )


def _stated_mm3(volume_nm3: int) -> str:
    """``volume_nm3`` in cubic millimetres, never rounded away to nothing.

    The same rule :func:`_stated_mm` applies to a depth: a region a person
    should see must not print as "0.000", and cubic nanometres shrink far
    faster than nanometres do, so the fallback carries nine decimals.
    """
    stated = _mm3(volume_nm3, 3)
    if volume_nm3 and stated == _mm3(0, 3):
        return _mm3(volume_nm3, 9)
    return stated


def _summary(first: int, second: int, found: Sequence[Clash]) -> Diagnostic:
    """One line saying *these two boards interfere*, over the pairs that do.

    A summary of the detail rather than a replacement for it: an assembly of
    many parts needs a line a reader can take without walking every pair,
    and the pairs are still there to walk.
    """
    total = sum(clash.common_volume_nm3 for clash in found)
    return Diagnostic.warning(
        "clash",
        f"board {first} clashes with board {second} by {_stated_mm3(total)} mm³ "
        f"over {len(found)} solid pair{'' if len(found) == 1 else 's'}",
        data=(
            ("board", first),
            ("with", f"board:{second}"),
            ("kind", "board"),
            ("solids", len(found)),
            ("common_volume_nm3", total),
        ),
    )


def _stated_solid(name: str) -> str:
    """``name`` as a person reads it, where nobody named the solid.

    A board solid with no name of its own is keyed on its least corner, so
    the identity is exact but reads as a coordinate rather than a thing.
    The message says what it is; the finding's own ``part`` and ``with``
    keep the key, which is the name the assembly writes that solid under
    and so the one a reader opening the model needs. A named solid is left
    alone: its designator is already the readable name, and a second name
    for it would make the message and the model disagree.
    """
    matched = _UNNAMED_BOARD_SOLID.match(name)
    return f"board {matched.group(1)}'s substrate" if matched else name


def _finding(ordinal: int, clash: Clash) -> Diagnostic:
    """One warning for one clash: what fouls what, and by how much.

    A clash is a WARNING and never an error: a matched board whose every
    candidate clashes is the right board with a misaligned design, and
    withholding the artefacts there would defeat the tool.
    """
    where = f"{_stated_mm(clash.depth_nm)} mm along {clash.axis}"
    if clash.part is None:
        message = f"board {ordinal} clashes with {_stated_solid(clash.with_)} by {where}"
    else:
        message = (
            f"{_stated_solid(clash.part)} clashes with {_stated_solid(clash.with_)} by "
            f"{_stated_mm3(clash.common_volume_nm3)} mm³, {where}"
        )
    data: tuple[tuple[str, Any], ...] = (
        ("board", ordinal),
        ("with", clash.with_),
        ("kind", clash.kind),
        ("depth_nm", int(clash.depth_nm)),
        ("axis", clash.axis),
        ("common_volume_nm3", clash.common_volume_nm3),
    )
    if clash.part is not None:
        data = (*data[:1], ("part", clash.part), *data[1:])
    return Diagnostic.warning("clash", message, data=data)


def _findings(placements: Mapping[int, tuple[Placement, ...]]) -> tuple[Diagnostic, ...]:
    """One warning per clash of each board's chosen placement."""
    return tuple(
        _finding(ordinal, clash)
        for ordinal in sorted(placements)
        if placements[ordinal]
        for clash in placements[ordinal][0].clashes
    )

