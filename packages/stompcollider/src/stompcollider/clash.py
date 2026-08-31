"""``Clashes``: what a placement overlaps, by how much, and against what.

The pipeline's one impure stage. ``Match`` and ``Seat`` fold over values;
this one folds over solids, reaching the kernel through ``stompgeom`` and
never through OCP. Bounding boxes filter the pairs and an exact
intersection decides every survivor, so no answer here is a proximity
estimate. See "Clashes" in ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import combinations
from typing import Any, ClassVar

from stompgeom.shapes import common, compound, placed
from stompgeom.step import StepSolid, bounding_box_mm
from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, RigidTransform
from stompmodel.model import StageRun
from stompmodel.units import Nanometre, format_nm, nm_from_mm

from .errors import StompcolliderError
from .model import Board, Clash, DockData, Placement
from .seat import rank_key

__all__ = ["Clashes", "placement_transform", "solid_name"]

#: A clash's axis names one of the face frame's own three, never a model
#: axis: the frame the enclosure was drilled in is the frame a depth means
#: something in.
_AXES = ("u", "v", "w")

#: A shape's bounding box, ``(x0, y0, z0, x1, y1, z1)`` in millimetres.
_Box = tuple[float, float, float, float, float, float]

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


def _boxes_overlap(first: _Box, second: _Box) -> bool:
    """Whether two axis-aligned boxes share any point, contact included.

    Non-strict on purpose: the filter may never discard a pair the exact
    intersection would have kept, so two boxes merely touching go through
    to the boolean, which answers contact for itself.
    """
    return all(first[axis] <= second[axis + 3] and second[axis] <= first[axis + 3]
               for axis in range(3))


def _clash_from(region: Any, basis: CoordinateFrame, with_: str, kind: str) -> Clash | None:
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
    # ``volume_nm3`` is the box's own volume, not the boolean's measured
    # one: a clash *is* this box, and the product of three canonical
    # lengths is exact where a float mm^3 scaled to nm^3 would not be.
    return Clash(
        with_=with_,
        kind=kind,
        bbox_nm=(lows[0], lows[1], lows[2], highs[0], highs[1], highs[2]),
        depth_nm=Nanometre(extents[least]),
        axis=_AXES[least],
        volume_nm3=extents[0] * extents[1] * extents[2],
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


def _pair_clash(
    first: Any,
    first_box: _Box,
    second: Any,
    second_box: _Box,
    basis: CoordinateFrame,
    with_: str,
    kind: str,
) -> Clash | None:
    """Filter the pair on bounding boxes, then decide it exactly.

    The whole of rule 2, stated once: a caller adding a third kind of thing
    to check gets the same filter and the same boolean rather than a second
    copy of either.
    """
    if not _boxes_overlap(first_box, second_box):
        return None
    region = common(first, second)
    if region is None:
        return None
    return _clash_from(region, basis, with_, kind)


def _clash_key(clash: Clash) -> tuple[str, str, int, tuple[Nanometre, ...]]:
    """The spec's clash order, extended to a total one by the box itself."""
    return (clash.kind, clash.with_, int(clash.depth_nm), clash.bbox_nm)


class Clashes:
    """Fills each placement's ``clashes`` and re-ranks on what it found.

    Satisfies ``stompmodel.protocols.Stage[DockData]``. Each board is
    checked against **the whole of the rest of the assembly** -- every case
    solid and every other board -- and ranked against the case alone; the
    assembly is then formed once from each board's rank-1 placement. Reads
    only ``DockData.placements`` and ``.boards``, so it neither depends on
    nor asserts that another stage ran first, and recording its own
    ``describe()`` is ``Pipeline.run``'s job rather than ``apply``'s.
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

    def describe(self) -> StageRun:
        """Report the (parameterless) configuration this stage ran with."""
        return StageRun(self.name)

    def apply(self, data: DockData) -> DockData:
        basis = data.case.frame.basis
        boards = {board.ordinal: board for board in data.boards}
        case = tuple((solid, bounding_box_mm(solid.shape)) for solid in self._case)

        ranked: dict[int, tuple[Placement, ...]] = {}
        for ordinal in sorted(data.placements):
            board = self._board_for(ordinal, boards)
            filled = [
                replace(
                    placement,
                    clashes=self._against_case(board, placement, basis, case),
                )
                for placement in data.placements[ordinal]
            ]
            ranked[ordinal] = tuple(
                replace(placement, rank=rank)
                for rank, placement in enumerate(sorted(filled, key=rank_key), start=1)
            )

        seated = self._assembly(ranked, boards, basis)
        return replace(
            data,
            placements=seated,
            diagnostics=data.diagnostics + _findings(seated),
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

    def _moved(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> tuple[Any, _Box]:
        """This board's solids, all of them, under one placement."""
        motion = placement_transform(board, placement, basis)
        shape = compound(
            placed(solid.shape, motion) for solid in self._boards[board.ordinal]
        )
        return shape, bounding_box_mm(shape)

    def _against_case(
        self,
        board: Board,
        placement: Placement,
        basis: CoordinateFrame,
        case: tuple[tuple[StepSolid, _Box], ...],
    ) -> tuple[Clash, ...]:
        """Every case solid this placement meets. None is privileged or exempt."""
        shape, box = self._moved(board, placement, basis)
        found = [
            clash
            for solid, other in case
            if (clash := _pair_clash(
                shape, box, solid.shape, other, basis, solid_name(solid, other, "case"), "case"
            ))
            is not None
        ]
        return tuple(sorted(found, key=_clash_key))

    def _assembly(
        self,
        ranked: Mapping[int, tuple[Placement, ...]],
        boards: Mapping[int, Board],
        basis: CoordinateFrame,
    ) -> dict[int, tuple[Placement, ...]]:
        """Inter-board clashes, computed once on each board's rank-1 placement.

        Never a re-rank: ranking is against the case alone, so the Cartesian
        product of every board's candidates never appears and no board's
        order depends on another's.
        """
        chosen = {
            ordinal: self._moved(boards[ordinal], placements[0], basis)
            for ordinal, placements in ranked.items()
            if placements
        }
        found: dict[int, list[Clash]] = {ordinal: [] for ordinal in chosen}
        for first, second in combinations(sorted(chosen), 2):
            clash = _pair_clash(
                chosen[first][0], chosen[first][1],
                chosen[second][0], chosen[second][1],
                basis, f"board:{second}", "board",
            )
            if clash is None:
                continue
            found[first].append(clash)
            found[second].append(replace(clash, with_=f"board:{first}"))
        return {
            ordinal: _with_assembly_clashes(placements, found.get(ordinal, []))
            for ordinal, placements in ranked.items()
        }


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


def _findings(placements: Mapping[int, tuple[Placement, ...]]) -> tuple[Diagnostic, ...]:
    """One warning per clash of each board's chosen placement.

    A clash is a WARNING and never an error: a matched board whose every
    candidate clashes is the right board with a misaligned design, and
    withholding the artefacts there would defeat the tool.
    """
    return tuple(
        Diagnostic.warning(
            "clash",
            f"board {ordinal} clashes with {clash.with_} by "
            f"{_stated_mm(clash.depth_nm)} mm along {clash.axis}",
            data=(
                ("board", ordinal),
                ("with", clash.with_),
                ("kind", clash.kind),
                ("depth_nm", int(clash.depth_nm)),
                ("axis", clash.axis),
            ),
        )
        for ordinal in sorted(placements)
        if placements[ordinal]
        for clash in placements[ordinal][0].clashes
    )
