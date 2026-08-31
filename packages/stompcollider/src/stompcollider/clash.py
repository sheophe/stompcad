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
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations, islice, product
from typing import Any, ClassVar

from stompgeom.shapes import common, compound, placed, volume_mm3
from stompgeom.step import BoxMm, StepSolid, bounding_box_mm
from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, RigidTransform
from stompmodel.model import StageRun
from stompmodel.units import Nanometre, format_nm, nm_from_mm

from .errors import StompcolliderError
from .model import Board, Clash, DockData, Placement
from .seat import rank_key

__all__ = ["Clashes", "board_solid_name", "placement_transform", "solid_name"]

#: A clash's axis names one of the face frame's own three, never a model
#: axis: the frame the enclosure was drilled in is the frame a depth means
#: something in.
_AXES = ("u", "v", "w")

#: A shape's bounding box, ``(x0, y0, z0, x1, y1, z1)`` in millimetres.
_Box = BoxMm

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

#: The model frame itself. The motion carrying a face frame onto this one
#: restates a body's own coordinates as that face frame's, which is how a
#: region gets boxed *in* the face frame rather than boxed in the model's
#: and reprojected -- see :func:`_clash_from`.
_MODEL_FRAME = CoordinateFrame(
    origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
    u=(1.0, 0.0, 0.0),
    v=(0.0, 1.0, 0.0),
    w=(0.0, 0.0, 1.0),
)


@dataclass(frozen=True, slots=True)
class _Body:
    """One solid placed for a check: what to call it, and where it now is.

    ``box`` bounds ``shape`` and is only ever read as a filter, so it may
    be wider than the shape's own box but never narrower -- see
    :func:`_transformed_box`.
    """

    name: str
    shape: Any
    box: _Box


def _board_frame(board: Board) -> CoordinateFrame:
    """The board's own frame, as the file it was exported from states it.

    Origin at the model origin, not at the carrier plane: a protrusion's
    ``axis_xy_nm`` is the plain projection of its axis onto ``u`` and ``v``,
    so ``Match``'s ``(x, y, theta)`` is solved against exactly these
    coordinates. There is no second hypothesis to switch on -- which face
    points at the panel is derived rather than searched, so ``panel_face``
    is ``+w`` for every board that has one, and a board Match never reached
    is placed the same way.
    """
    carrier = board.carrier
    origin = (Nanometre(0), Nanometre(0), Nanometre(0))
    return CoordinateFrame(origin_nm=origin, u=carrier.u, v=carrier.v, w=carrier.w)


def placement_transform(
    board: Board, placement: Placement, basis: CoordinateFrame
) -> RigidTransform:
    """The rigid motion carrying ``board`` into ``placement`` on the face.

    The spec's composition, in its stated order: the board turned to the
    face it was matched on, rotated by theta about the face normal,
    translated by ``(x, y)`` in the face frame and by ``z`` along its
    normal. Built as one frame-to-frame placement rather than a product of
    matrices written here -- ``translated_nm`` moves along the frame's own
    unrotated axes, so it comes before the turn.
    """
    target = basis.translated_nm(
        placement.x_nm, placement.y_nm, placement.z_nm
    ).rotated_about_w(math.radians(placement.theta_deg))
    return _board_frame(board).placement_onto(target)


def _transformed_box(box: _Box, motion: RigidTransform) -> _Box:
    """``box``'s eight corners under ``motion``, boxed again.

    A bound on the moved shape, not that shape's own box: the box of a box
    is the larger under any rotation but a quarter turn. Sound *here* and
    nowhere else, because this is only ever rule 2's negative filter -- a
    box too large can only send a pair to the boolean that decides it
    anyway, and nothing measured is read off it. Boxing the moved shape
    instead is this package's most expensive read, once per solid per
    candidate seating.
    """
    rows = motion.rotation
    shift = motion.translation_mm
    lows = [math.inf] * 3
    highs = [-math.inf] * 3
    for corner in product((box[0], box[3]), (box[1], box[4]), (box[2], box[5])):
        for axis in range(3):
            value = shift[axis] + sum(
                rows[axis][index] * corner[index] for index in range(3)
            )
            lows[axis] = min(lows[axis], value)
            highs[axis] = max(highs[axis], value)
    return (lows[0], lows[1], lows[2], highs[0], highs[1], highs[2])


def _boxes_overlap(first: _Box, second: _Box) -> bool:
    """Whether two axis-aligned boxes share any point, contact included.

    Non-strict on purpose: the filter may never discard a pair the exact
    intersection would have kept, so two boxes merely touching go through
    to the boolean, which answers contact for itself.
    """
    return all(first[axis] <= second[axis + 3] and second[axis] <= first[axis + 3]
               for axis in range(3))


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
    box = bounding_box_mm(placed(region, basis.placement_onto(_MODEL_FRAME)))
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


def solid_name(solid: StepSolid, box: _Box, group: str) -> str:
    """What to call ``solid`` within ``group``, including one nobody named.

    An empty ``StepSolid.name`` means nobody named the solid, legitimate
    input for a supplied enclosure (ADR-0007) that ``Clash`` still refuses
    and the assembly must still write. Keyed on the solid's own least
    corner in whole nanometres -- a property of the geometry, so two files
    listing the same solids in a different order name them the same way,
    where an index into the supplied sequence would not (ADR-0006).
    """
    if solid.name:
        return solid.name
    corner = ",".join(str(nm_from_mm(box[axis])) for axis in range(3))
    return f"{group}:unnamed@{corner}"


def board_solid_name(solid: StepSolid, box: _Box, group: str) -> str:
    """A board solid's name, always carrying the board it belongs to.

    Every one, not only the solids nobody named: two boards may each carry
    an ``RV1``, so a designator alone is not unique across an assembly, and
    a reader opening the model needs to know whose component it is anyway.
    One rule for the assembly writer and for an inter-board finding, so the
    name the report states is the name the model was written under.
    """
    return f"{group}:{solid.name}" if solid.name else solid_name(solid, box, group)


def _pair_clash(
    first: _Body,
    second: _Body,
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
    if not _boxes_overlap(first.box, second.box):
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
    every seating whose case clash is empty; stage two picks, over the
    combinations of those, the assembly of least inter-board material.
    Reads only ``DockData.placements`` and ``.boards``, so it asserts no
    other stage ran, and ``describe()`` is ``Pipeline.run``'s to record.
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
        self._placed: dict[tuple[int, Placement], tuple[_Body, ...]] = {}
        self._pairs: dict[tuple[int, Placement, int, Placement], tuple[Clash, ...]] = {}

    def describe(self) -> StageRun:
        """Report the (parameterless) configuration this stage ran with."""
        return StageRun(self.name)

    def apply(self, data: DockData) -> DockData:
        basis = data.case.frame.basis
        boards = {board.ordinal: board for board in data.boards}

        ranked: dict[int, tuple[Placement, ...]] = {}
        for ordinal in sorted(data.placements):
            board = self._board_for(ordinal, boards)
            filled = [
                replace(placement, clashes=self._against_case(board, placement, basis))
                for placement in data.placements[ordinal]
            ]
            ranked[ordinal] = tuple(
                replace(placement, rank=rank)
                for rank, placement in enumerate(sorted(filled, key=rank_key), start=1)
            )

        seated, notes = self._assembly(ranked, boards, basis)
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
    ) -> tuple[_Body, ...]:
        """This board's solids, each named and bounded, under one placement."""
        key = (board.ordinal, placement)
        cached = self._placed.get(key)
        if cached is None:
            motion = placement_transform(board, placement, basis)
            group = f"board:{board.ordinal}"
            cached = tuple(
                _Body(
                    board_solid_name(solid, solid.box_mm, group),
                    placed(solid.shape, motion),
                    _transformed_box(solid.box_mm, motion),
                )
                for solid in self._boards[board.ordinal]
            )
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
        """
        bodies = self._bodies(board, placement, basis)
        found = []
        for solid in self._case:
            box = solid.box_mm
            meeting = [body.shape for body in bodies if _boxes_overlap(body.box, box)]
            if not meeting:
                continue
            region = common(compound(meeting), solid.shape)
            if region is None:
                continue
            clash = _clash_from(region, basis, solid_name(solid, box, "case"), "case")
            if clash is not None:
                found.append(clash)
        return tuple(sorted(found, key=_clash_key))

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
        boards: Mapping[int, Board],
        basis: CoordinateFrame,
    ) -> tuple[dict[int, tuple[Placement, ...]], tuple[Diagnostic, ...]]:
        """Stage two: which of the case-clean seatings this assembly is made of.

        The case takes no part here, having already been answered in stage
        one. A board no seating clears the case for is fixed at its
        stage-one rank 1 and says so, because a seating that fouls the
        enclosure cannot be improved by anything a neighbour does -- and
        because a reader could not otherwise tell a chosen seating from a
        defaulted one.
        """
        notes: list[Diagnostic] = []
        candidates = self._candidates(ranked, notes)
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
        notes: list[Diagnostic],
    ) -> dict[int, tuple[Placement, ...]]:
        """Stage one's survivors: every seating whose clash with the case is empty."""
        candidates: dict[int, tuple[Placement, ...]] = {}
        for ordinal in sorted(ranked):
            placements = ranked[ordinal]
            if not placements:
                continue
            clean = tuple(one for one in placements if not one.clashes)
            candidates[ordinal] = clean or (placements[0],)
            if clean:
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

