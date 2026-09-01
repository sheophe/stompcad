"""Placing and naming one run's solids: the body a later stage reasons about.

Everything that turns a ``StepSolid`` and a ``Placement`` into a named,
located, bounded body lives here, because three modules want exactly that
and none of them owns it: ``clash`` intersects bodies, ``insert`` walks a
board's bodies along the face normal, and the assembly emitter writes them.
A second copy of the placement composition would let two of those disagree
about where a board is.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from stompgeom.shapes import placed
from stompgeom.step import BoxMm, StepSolid
from stompmodel.frames import CoordinateFrame, RigidTransform
from stompmodel.units import Nanometre, nm_from_mm

from .model import Board, Placement

__all__ = [
    "Body",
    "MODEL_FRAME",
    "board_frame",
    "placement_transform",
    "transformed_box",
    "face_box",
    "boxes_overlap",
    "solid_name",
    "board_solid_name",
    "bodies",
]

#: The model frame itself. The motion carrying a face frame onto this one
#: restates a body's own coordinates as that face frame's, which is how a
#: region gets boxed *in* the face frame rather than boxed in the model's
#: and reprojected.
MODEL_FRAME = CoordinateFrame(
    origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
    u=(1.0, 0.0, 0.0),
    v=(0.0, 1.0, 0.0),
    w=(0.0, 0.0, 1.0),
)


@dataclass(frozen=True, slots=True)
class Body:
    """One solid placed for a check: what to call it, and where it now is.

    ``box`` bounds ``shape`` and is only ever read as a filter, so it may
    be wider than the shape's own box but never narrower -- see
    :func:`transformed_box`.
    """

    name: str
    shape: Any
    box: BoxMm


def board_frame(board: Board) -> CoordinateFrame:
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
    return board_frame(board).placement_onto(target)


def transformed_box(box: BoxMm, motion: RigidTransform) -> BoxMm:
    """``box``'s eight corners under ``motion``, boxed again.

    A bound on the moved shape, not that shape's own box: the box of a box
    is the larger under any rotation but a quarter turn. Sound only as a
    negative filter -- a box too large can only send a pair to the boolean
    that decides it anyway, and nothing measured is read off it. Boxing the
    moved shape instead is this package's most expensive read, once per
    solid per candidate seating.
    """
    rows = motion.rotation
    shift = motion.translation_mm
    lows = [math.inf] * 3
    highs = [-math.inf] * 3
    for corner in _corners(box):
        for axis in range(3):
            value = shift[axis] + sum(
                rows[axis][index] * corner[index] for index in range(3)
            )
            lows[axis] = min(lows[axis], value)
            highs[axis] = max(highs[axis], value)
    return (lows[0], lows[1], lows[2], highs[0], highs[1], highs[2])


def _corners(box: BoxMm) -> tuple[tuple[float, float, float], ...]:
    """A box's eight corners, in a fixed order."""
    return tuple(
        (x, y, z)
        for x in (box[0], box[3])
        for y in (box[1], box[4])
        for z in (box[2], box[5])
    )


def face_box(box: BoxMm, basis: CoordinateFrame, motion: RigidTransform | None = None) -> BoxMm:
    """``box``'s corners, optionally moved, read on ``basis``'s own axes.

    One boxing rather than two: the corners are carried through ``motion``
    and projected onto the face frame before the minimum and maximum are
    taken, where boxing in the model frame first and reprojecting *that*
    box is strictly the larger for any frame not a quarter turn about a
    model axis. Still only ever a filter, so either would be sound; this
    one is simply tighter for the same work.
    """
    projected = [
        basis.to_canonical(corner if motion is None else motion.apply_point(corner))
        for corner in _corners(box)
    ]
    lows = [min(point[axis] for point in projected) for axis in range(3)]
    highs = [max(point[axis] for point in projected) for axis in range(3)]
    return (lows[0], lows[1], lows[2], highs[0], highs[1], highs[2])


def boxes_overlap(first: BoxMm, second: BoxMm) -> bool:
    """Whether two axis-aligned boxes share any point, contact included.

    Non-strict on purpose: the filter may never discard a pair the exact
    intersection would have kept, so two boxes merely touching go through
    to the boolean, which answers contact for itself.
    """
    return all(first[axis] <= second[axis + 3] and second[axis] <= first[axis + 3]
               for axis in range(3))


def solid_name(solid: StepSolid, box: BoxMm, group: str) -> str:
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


def board_solid_name(solid: StepSolid, box: BoxMm, group: str) -> str:
    """A board solid's name, always carrying the board it belongs to.

    Every one, not only the solids nobody named: two boards may each carry
    an ``RV1``, so a designator alone is not unique across an assembly, and
    a reader opening the model needs to know whose component it is anyway.
    One rule for the assembly writer and for an inter-board finding, so the
    name the report states is the name the model was written under.
    """
    return f"{group}:{solid.name}" if solid.name else solid_name(solid, box, group)


def bodies(
    board: Board,
    placement: Placement,
    basis: CoordinateFrame,
    solids: Sequence[StepSolid],
) -> tuple[Body, ...]:
    """This board's solids, each named and bounded, under one placement."""
    motion = placement_transform(board, placement, basis)
    group = f"board:{board.ordinal}"
    return tuple(
        Body(
            board_solid_name(solid, solid.box_mm, group),
            placed(solid.shape, motion),
            transformed_box(solid.box_mm, motion),
        )
        for solid in solids
    )
