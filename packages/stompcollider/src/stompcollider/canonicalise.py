"""``canonicalise()``: the seam where measured floats become canonical facts.

Unlike ``stompdrill.quantise``, this selects nothing -- a board's geometry
has no answer set to snap to. It only scales millimetres to nanometres by
exact decimal conversion (ADR-0003), then orders boards, components and
profile steps by geometry rather than by input order, stating each distinct
step once (ADR-0006). See "The boundary is canonicalise(), not quantise()"
in ``stompcollider-technical.md``.
"""

from __future__ import annotations

from collections.abc import Sequence

from stompmodel.frames import CoordinateFrame
from stompmodel.model import CaseRegistration
from stompmodel.units import Nanometre, nm_from_mm

from .model import Board, Component, DockData, Profile, Protrusion
from .raw import RawBoard, RawBoards, RawComponent, RawCylinder

__all__ = ["canonicalise"]

#: A board's ordinal sort key, as "Board ordinals" in the spec fixes it:
#: least corner first, then largest footprint first among ties.
_SortKey = tuple[Nanometre, Nanometre, Nanometre, int]


def _corner_extremes(
    board: RawBoard,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The board's bounding box, least and greatest per axis.

    Corner order in ``RawBoard`` carries no meaning; taking the per-axis
    min and max here is what makes that true.
    """
    a, b = board.corner_a_mm, board.corner_b_mm
    low = tuple(min(a[i], b[i]) for i in range(3))
    high = tuple(max(a[i], b[i]) for i in range(3))
    return low, high  # type: ignore[return-value]


def _sort_key(board: RawBoard, basis: CoordinateFrame) -> _SortKey:
    """Project the board's bounding box into the case's face frame.

    Every one of the box's eight corners is projected, not just the two
    measured extremes: the face frame may be rotated relative to the model
    frame, so the measured min/max corner is not necessarily the projected
    one. Nanometre conversion happens before comparison, per ADR-0003.
    """
    low, high = _corner_extremes(board)
    corners = [
        basis.to_canonical((x, y, z))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]
    xs_nm = [nm_from_mm(p[0]) for p in corners]
    ys_nm = [nm_from_mm(p[1]) for p in corners]
    min_x_nm, max_x_nm = min(xs_nm), max(xs_nm)
    min_y_nm, max_y_nm = min(ys_nm), max(ys_nm)
    min_z_nm = min(nm_from_mm(p[2]) for p in corners)
    footprint_nm2 = (max_x_nm - min_x_nm) * (max_y_nm - min_y_nm)
    return (min_x_nm, min_y_nm, min_z_nm, -footprint_nm2)


def _canonical_steps(
    stack: Sequence[RawCylinder],
) -> tuple[tuple[Nanometre, Nanometre, Nanometre], ...]:
    """One step per distinct cylinder, ordered outside in.

    Both rules apply after the scaling and never before it: exact equality
    is a fact about whole nanometres, and a set keyed on a millimetre float
    would be the composite float key ADR-0003's boundary rules out. Depth
    leads the order so the profile reads from the tip, and every part of the
    key is geometry, so ``stack``'s own order -- a kernel walk's -- reaches
    no artefact (ADR-0006).
    """
    scaled = {
        (
            nm_from_mm(cylinder.radius_mm),
            nm_from_mm(cylinder.depth_from_tip_min_mm),
            nm_from_mm(cylinder.depth_from_tip_max_mm),
        )
        for cylinder in stack
    }
    return tuple(sorted(scaled, key=lambda step: (step[1], step[2], step[0])))


def _canonicalise_component(raw: RawComponent) -> Component:
    """Scale one component's axis and stack; select nothing about either.

    "Nothing" is exact: no measurement is snapped, and nothing is dropped
    but a repeat -- two cylinders that scale to one step were one feature
    stated twice. :func:`_canonical_steps` holds that rule and the order.
    """
    if raw.axis_xy_mm is None:
        return Component(designator=raw.designator, protrusion=None)
    axis_nm = (nm_from_mm(raw.axis_xy_mm[0]), nm_from_mm(raw.axis_xy_mm[1]))
    steps = _canonical_steps(raw.stack)
    protrusion = Protrusion(
        designator=raw.designator, axis_xy_nm=axis_nm, profile=Profile(steps=steps)
    )
    return Component(designator=raw.designator, protrusion=protrusion)


def _canonicalise_board(raw: RawBoard, ordinal: int) -> Board:
    low, high = _corner_extremes(raw)
    extent_nm = tuple(nm_from_mm(high[i] - low[i]) for i in range(3))
    carrier = CoordinateFrame(
        origin_nm=tuple(nm_from_mm(v) for v in raw.carrier_origin_mm),  # type: ignore[arg-type]
        u=raw.carrier_u,
        v=raw.carrier_v,
        w=raw.carrier_w,
    )
    # ADR-0006 is not only about board order: a board's own component list
    # must not carry the raw reader's traversal order into the model either.
    components = tuple(
        sorted((_canonicalise_component(c) for c in raw.components), key=lambda c: c.designator)
    )
    designators = tuple(c.designator for c in components)
    return Board(
        ordinal=ordinal,
        designators=designators,
        extent_nm=extent_nm,  # type: ignore[arg-type]
        carrier=carrier,
        components=components,
    )


def canonicalise(raw: RawBoards, case: CaseRegistration) -> DockData:
    """Convert every measured board to canonical nanometres and order them.

    Ordering happens on an explicitly sorted sequence, keyed by geometry in
    the case's face frame -- never by ``raw.boards``' own order, per
    ADR-0006. Ordinals are then assigned 1..n over that sorted sequence.
    """
    ordered = sorted(raw.boards, key=lambda board: _sort_key(board, case.frame.basis))
    boards = tuple(
        _canonicalise_board(board, ordinal)
        for ordinal, board in enumerate(ordered, start=1)
    )
    return DockData(case=case, boards=boards)
