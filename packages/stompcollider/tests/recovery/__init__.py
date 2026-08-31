"""Independent read-back of the two artefacts one docking writes.

Test support, not shipped. Each module here reads what an emitter wrote and
nothing else, and none of them may import ``stompcollider`` -- which wrote
the report -- or ``stompgeom`` -- which wrote the STEP: a recovery that
inverts its emitter's own transform proves that emitter self-consistent and
nothing more. ``test_dock_agreement.py`` holds the gate that enforces it.
The vocabulary below is shared by both readers, so a comparison between them
has one set of names to state a fact in.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stompmodel.units import Nanometre

__all__ = [
    "RecoveredSolid",
    "RecoveredAssembly",
    "RecoveredCorrespondence",
    "RecoveredClash",
    "RecoveredPlacement",
    "RecoveredBoard",
    "RecoveredDiagnostic",
    "RecoveredDock",
    "midpoint_nm",
]


def midpoint_nm(low_nm: Nanometre, high_nm: Nanometre) -> Nanometre:
    """The middle of an extent, refusing one the canonical model cannot hold.

    A half-nanometre midpoint is not a length ADR-0003's representation
    states, so it is a defect in the artefact or in the reader rather than a
    rounding question here -- the same refusal
    ``stompdrill``'s ``nm_from_decimal`` makes for the same reason.
    """
    total = int(low_nm) + int(high_nm)
    if total % 2:
        raise ValueError(f"not a whole number of nanometres: ({low_nm} + {high_nm}) / 2")
    return Nanometre(total // 2)


@dataclass(frozen=True, slots=True)
class RecoveredSolid:
    """One product the assembly model names, and the box it occupies.

    ``box_nm`` is ``(x0, y0, z0, x1, y1, z1)`` in the file's own coordinates.
    Named fields rather than positions: transposing two axes is the
    characteristic bug in a reader like this, and a bare tuple hides it.
    """

    name: str
    box_nm: tuple[
        Nanometre, Nanometre, Nanometre, Nanometre, Nanometre, Nanometre
    ]

    @property
    def centre_nm(self) -> tuple[Nanometre, Nanometre, Nanometre]:
        """The box's own middle -- where a cylinder's axis reads."""
        middle = tuple(
            midpoint_nm(self.box_nm[axis], self.box_nm[axis + 3]) for axis in range(3)
        )
        return (middle[0], middle[1], middle[2])


@dataclass(frozen=True, slots=True)
class RecoveredAssembly:
    """Every product one assembly model states, in the order the file lists them."""

    solids: tuple[RecoveredSolid, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(solid.name for solid in self.solids)

    def named(self, name: str) -> RecoveredSolid:
        """The one solid called ``name``; a repeat or a miss is an error here."""
        found = [solid for solid in self.solids if solid.name == name]
        if len(found) != 1:
            raise ValueError(f"{name!r} names {len(found)} solids, not one")
        return found[0]


@dataclass(frozen=True, slots=True)
class RecoveredCorrespondence:
    """One pairing the report states: a part, and the hole it sits over."""

    designator: str
    hole_index: int
    hole_xy_nm: tuple[Nanometre, Nanometre]
    insertion_nm: Nanometre | None
    offset_nm: Nanometre


@dataclass(frozen=True, slots=True)
class RecoveredClash:
    """One interference the report states, with the extent it claims.

    Both volumes are modelled and so is ``part``: a reader that skipped
    what it does not model would pass an emitter change by omission, and
    these three are exactly what version 2 added.
    """

    with_: str
    kind: str
    part: str | None
    bbox_nm: tuple[
        Nanometre, Nanometre, Nanometre, Nanometre, Nanometre, Nanometre
    ]
    depth_nm: Nanometre
    axis: str
    bbox_volume_nm3: int
    common_volume_nm3: int


@dataclass(frozen=True, slots=True)
class RecoveredPlacement:
    """One seating the report states, exactly as written.

    ``theta_deg`` is a ``Decimal`` and never a float: it is the document's
    one non-integer field, written at six decimals, so parsing it exactly is
    what lets a comparison demand equality rather than an epsilon.
    """

    rank: int
    x_nm: Nanometre
    y_nm: Nanometre
    z_nm: Nanometre
    theta_deg: Decimal
    correspondence: tuple[RecoveredCorrespondence, ...] = ()
    clashes: tuple[RecoveredClash, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveredBoard:
    """One board the report states, and every placement it lists for it."""

    ordinal: int
    designators: tuple[str, ...]
    extent_nm: tuple[Nanometre, Nanometre, Nanometre]
    panel_face: str | None
    placements: tuple[RecoveredPlacement, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveredDiagnostic:
    """One finding the report states, matched by ``code`` and never by message."""

    severity: str
    code: str
    location_nm: tuple[Nanometre, ...] | None


@dataclass(frozen=True, slots=True)
class RecoveredDock:
    """Everything one dock report states about one docking."""

    format: str
    version: int
    units: str
    case: tuple[str, str, str]
    boards: tuple[RecoveredBoard, ...] = ()
    unmatched_holes: tuple[int, ...] = ()
    diagnostics: tuple[RecoveredDiagnostic, ...] = ()

    def board(self, ordinal: int) -> RecoveredBoard:
        """The one board numbered ``ordinal``."""
        found = [board for board in self.boards if board.ordinal == ordinal]
        if len(found) != 1:
            raise ValueError(f"board {ordinal} appears {len(found)} times, not once")
        return found[0]
