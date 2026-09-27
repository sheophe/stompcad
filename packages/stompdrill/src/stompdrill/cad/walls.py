"""Which of a drilled enclosure's planar levels are its walls.

Separate from ``case.py``, which owns the drilled plate's own path and whose
bytes ADR-0011 locks: a second question in that file is a second reason to
edit it. A wall is discovered and never declared -- see ADR-0007's amendment,
and ``tools/measure_walls.py`` for the measured populations it reasons from.
"""

from __future__ import annotations

import math

from stompgeom.levels import Direction, Level, levels
from stompgeom.step import StepSolid
from stompmodel.frames import dot

from ..errors import StompdrillError
from .case import _plates

__all__ = [
    "LATERAL_LIMIT",
    "draft_degrees",
    "is_lateral",
    "lateral_plates",
    "nearest_axis",
]

#: How much of a level's normal may lie along the drill axis and still be a
#: wall's. ``sin 45°``: a level is lateral or it is axial, and this is where
#: the two meanings meet -- not a tolerance fitted to a population. The
#: measured populations are 1.150°-2.500° against exactly 90.000°, so nothing
#: real is ever near it; ``tests/test_walls_evidence.py`` holds that gap.
LATERAL_LIMIT = math.sin(math.radians(45.0))

#: Components in a direction.
_COMPONENTS = 3


def draft_degrees(direction: Direction, axis: Direction) -> float:
    """How far ``direction`` tilts out of the plane perpendicular to ``axis``.

    Zero for an untilted wall, 90 for the drilled face or the floor. Reported
    in degrees because that is how a casting's draft is published and how
    ``tools/measure_walls.py`` prints it; nothing decides anything on it.
    """
    return math.degrees(math.asin(min(1.0, abs(dot(direction, axis)))))


def is_lateral(level: Level, axis: Direction) -> bool:
    """Whether this level's outward normal is a wall's rather than a face's."""
    return abs(dot(level.direction, axis)) < LATERAL_LIMIT


def lateral_plates(solid: StepSolid, axis: int) -> tuple[Level, ...]:
    """``solid``'s plate levels that are lateral to drill ``axis``.

    Unfiltered ``levels`` and then ``_plates``, in that order and not the
    reverse: ``levels``' own axis filter keeps what faces *along* an axis,
    which is the opposite population, and ``_plates`` judges a level by its
    aggregate area, so filtering faces first would split the aggregate.
    """
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    along = (unit[0], unit[1], unit[2])
    return tuple(
        level for level in _plates(list(levels(solid))) if is_lateral(level, along)
    )


def nearest_axis(direction: Direction, axis: Direction | None = None) -> Direction:
    """The signed kernel axis ``direction`` leans on most.

    Grouping a wall's outer and inner surfaces -- which lean oppositely out
    of the footprint plane, landing in different direction bins -- means
    grouping on the axis they share. An exact tie takes the lower index,
    reachable only by an in-plane 45° level no casting has. Refuses
    ``axis`` itself: a lateral level's own filter already keeps it off the
    drill axis, so landing there is a construction failure, not a wall.
    """
    lead = max(range(_COMPONENTS), key=lambda index: (abs(direction[index]), -index))
    unit = [0.0, 0.0, 0.0]
    unit[lead] = 1.0 if direction[lead] > 0.0 else -1.0
    result = (unit[0], unit[1], unit[2])
    if axis is not None and result == axis:
        raise StompdrillError(
            f"{direction!r} leans nearest the drill axis {axis!r}, which no "
            "lateral level's own axis can be"
        )
    return result
