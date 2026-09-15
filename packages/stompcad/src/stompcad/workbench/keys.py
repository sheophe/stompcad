"""Every key the workbench answers, as data rather than as bindings.

Spec decision 3: the table proves distinctness, without running the app.
Each ``Place`` value is the name ``readiness`` and ``stale`` already use,
so nothing translates between two spellings.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Place",
    "SIDEBAR_ORDER",
    "CONFIGURATION",
    "PLACE_KEYS",
    "GLOBAL_VERBS",
    "LOCAL_KEYS",
    "STEP_KEYS",
    "neighbour",
    "conflicts",
]


class Place(Enum):
    """The eight places, named for subjects rather than for settings."""

    PROJECT = "project"
    ARTWORK = "artwork"
    ENCLOSURE = "enclosure"
    DRILLING = "drilling"
    BOARDS = "boards"
    OUTPUT = "output"
    RUN = "run"
    FINDINGS = "findings"


#: The sidebar's own order, which is also what ``[`` and ``]`` step through.
SIDEBAR_ORDER: tuple[Place, ...] = (
    Place.PROJECT,
    Place.ARTWORK,
    Place.ENCLOSURE,
    Place.DRILLING,
    Place.BOARDS,
    Place.OUTPUT,
    Place.RUN,
    Place.FINDINGS,
)

#: The five places that carry the left marker. ``Project`` is the landing and
#: the run row, ``Run`` is the activity and ``Findings`` is the outcome; none
#: of the three is a stage of configuration, which is why the sidebar groups.
CONFIGURATION: tuple[Place, ...] = (
    Place.ARTWORK,
    Place.ENCLOSURE,
    Place.DRILLING,
    Place.BOARDS,
    Place.OUTPUT,
)

#: One unique bare letter each. Decision 3: the eight initials are distinct
#: without compromise, so no place needs a second-choice key.
PLACE_KEYS: dict[str, Place] = {
    "p": Place.PROJECT,
    "a": Place.ARTWORK,
    "e": Place.ENCLOSURE,
    "d": Place.DRILLING,
    "b": Place.BOARDS,
    "o": Place.OUTPUT,
    "r": Place.RUN,
    "f": Place.FINDINGS,
}

#: The three bare letters no place claims. ``?`` is spelled as Textual names
#: it, because the binding table is built from these keys directly.
GLOBAL_VERBS: dict[str, str] = {
    "w": "window",
    "q": "quit",
    "question_mark": "keys",
}

#: ``Ctrl``+letter belongs to the place, so each row names its owner and the
#: application refuses the key anywhere else. A second place claiming one
#: would be two meanings for one chord, which ``conflicts`` reports.
LOCAL_KEYS: dict[str, tuple[Place, str]] = {
    "ctrl+l": (Place.ARTWORK, "re-read the artwork"),
    "ctrl+f": (Place.ENCLOSURE, "look again for a cached model"),
    "ctrl+r": (Place.RUN, "start or resume the run"),
}

#: Previous and next place. Not a second navigation model: both resolve to the
#: same place change a letter makes, and exist so nobody is stuck while
#: learning the letters.
STEP_KEYS: tuple[str, str] = ("[", "]")


def neighbour(place: Place, forward: bool) -> Place:
    """The next or previous place, wrapping at both ends of the sidebar."""
    index = SIDEBAR_ORDER.index(place)
    return SIDEBAR_ORDER[(index + (1 if forward else -1)) % len(SIDEBAR_ORDER)]


def conflicts() -> tuple[str, ...]:
    """Every key claimed by more than one table, in sorted order.

    The whole table is checked at once rather than each pair being asserted
    separately: a key added to one dictionary and forgotten in the others is
    exactly the failure this exists to catch, and it is invisible to a test
    that names the keys it already knows about.
    """
    seen: dict[str, int] = {}
    for table in (PLACE_KEYS, GLOBAL_VERBS, LOCAL_KEYS, dict.fromkeys(STEP_KEYS)):
        for key in table:
            seen[key] = seen.get(key, 0) + 1
    return tuple(sorted(key for key, count in seen.items() if count > 1))
