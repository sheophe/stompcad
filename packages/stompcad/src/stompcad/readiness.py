"""Whether a run may start, and which place answers each reason it may not.

Spec decision 17. The distinction this exists to draw is between *no
boards were found* and *this pedal has no boards to dock*: the driver
treats both as "skip docking", which is right for a library and wrong for
a person. Provenance already separates them -- an empty list at rank four
was never answered, and the same list at any higher rank is an answer --
so no second flag is introduced to carry what is already carried.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from .settings import Origin, Resolved, Settings

__all__ = ["Blocker", "Readiness", "readiness"]

_T = TypeVar("_T")


class Blocker(Enum):
    """Why a run may not start. Each names the place that can answer it."""

    NO_PANEL = "no artwork is selected"
    BOARDS_UNRESOLVED = "it is not yet settled whether this pedal has boards"
    NO_CASE_MODEL = "a board is seated in the case, so the case model is needed"
    NO_PANEL_REFERENCE = "which components mount to the panel is a pedal-specific fact"
    NO_BOARD_FOR_ASSEMBLY = "an assembly needs at least one board to seat"
    NO_TARGETS = "nothing has been chosen to make"


@dataclass(frozen=True, slots=True)
class Readiness:
    """What stands between this project and a run, in the places that answer."""

    blockers: tuple[tuple[Blocker, str, str], ...]

    @property
    def ready(self) -> bool:
        """Whether a run may start at all."""
        return not self.blockers


def _answered(resolved: Resolved[_T]) -> bool:
    """Whether any rank above the default supplied this value.

    Rank three counts as answered only when it found something: discovering
    that a directory holds no board is not a statement that the pedal has
    none.
    """
    if resolved.provenance.origin is Origin.DEFAULT:
        return False
    if resolved.provenance.origin is Origin.DISCOVERED:
        return bool(resolved.value)
    return True


def readiness(settings: Settings) -> Readiness:
    """Every reason this project cannot run yet, with the place that answers it."""
    found: list[tuple[Blocker, str, str]] = []
    if settings.artwork.panel.value is None:
        found.append((Blocker.NO_PANEL, "artwork", "Choose the Illustrator file to read."))

    boards = settings.boards.boards
    if not _answered(boards):
        found.append((
            Blocker.BOARDS_UNRESOLVED,
            "boards",
            "Tick the boards to dock, or confirm this pedal has none.",
        ))
    elif boards.value:
        if settings.enclosure.case_model.value is None:
            found.append((
                Blocker.NO_CASE_MODEL,
                "enclosure",
                "Choose the enclosure model the boards are seated in.",
            ))
        if not settings.boards.panel_reference.value:
            found.append((
                Blocker.NO_PANEL_REFERENCE,
                "boards",
                "Tick the components that mount through the panel.",
            ))

    targets = settings.output.targets
    names = {name for name, _path in targets.value}
    if names & {"assembly", "report"} and not boards.value:
        found.append((
            Blocker.NO_BOARD_FOR_ASSEMBLY,
            "output",
            "An assembly needs a board; add one, or drop the assembly.",
        ))
    if not targets.value and not _answered(targets):
        found.append((
            Blocker.NO_TARGETS,
            "output",
            "Choose what to make, or ask for a check that writes nothing.",
        ))
    return Readiness(tuple(found))
