"""The viewer: a written artefact, a path and a mode, and nothing coming back.

Spec decision 13, as the user decided it. A viewer is opened only when
somebody chooses an artefact in `Output`, on the file a run wrote, and is
handed a path and a mode and nothing else -- no geometry, no document. It
returns nothing and nothing waits on it, which is what stops the window
becoming something a run or a place depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

__all__ = [
    "UNVIEWABLE",
    "VIEWS",
    "NullWindow",
    "ViewMode",
    "ViewRequest",
    "Window",
    "view_mode_for",
]


class ViewMode(Enum):
    """What the viewer is being asked to show."""

    DRAWING = "drawing"
    MODEL = "model"


@dataclass(frozen=True, slots=True)
class ViewRequest:
    """Everything that crosses: a file, how to read it, and what to point at.

    ``highlight`` carries opaque identifiers -- a hole's number, a board's
    ordinal, a designator -- that the viewer interprets. A field for a
    shape or a document does not belong here; adding one is how the
    no-geometry rule would be lost.
    """

    path: Path
    mode: ViewMode
    title: str
    highlight: tuple[str, ...] = field(default_factory=tuple)


class Window(Protocol):
    """Somewhere a viewer might be, and the three things it is asked.

    ``open`` and ``close_all`` return promptly and never raise; a viewer
    that fails is the viewer's own failure to report, not the workbench's.
    """

    def available(self) -> bool: ...
    def open(self, request: ViewRequest) -> None: ...
    def close_all(self) -> None: ...


class NullWindow:
    """No viewer. The default, so the workbench ships without one.

    ``available`` is false rather than ``open`` raising, because an absent
    viewer is explained to the builder rather than failed on -- and because
    a workbench whose suite needed a display is one nobody could test.
    """

    def available(self) -> bool:
        return False

    def open(self, request: ViewRequest) -> None:
        return None

    def close_all(self) -> None:
        return None


#: How each kind of artefact is viewed.
VIEWS: dict[str, ViewMode] = {
    "drawing-pdf": ViewMode.DRAWING,
    "drawing-svg": ViewMode.DRAWING,
    "excellon": ViewMode.DRAWING,
    "json": ViewMode.DRAWING,
    "step": ViewMode.MODEL,
    "assembly": ViewMode.MODEL,
}

#: Kinds listed in `Output` on purpose but given no entry in `VIEWS`; that
#: absence, not this set, is what stops `enter` landing on them. The run's
#: report is a record of placements rather than a picture, and is not a row.
UNVIEWABLE = frozenset({"report"})


def view_mode_for(kind: str) -> ViewMode | None:
    """How to view this kind of artefact, or ``None`` for one only listed."""
    return VIEWS.get(kind)
