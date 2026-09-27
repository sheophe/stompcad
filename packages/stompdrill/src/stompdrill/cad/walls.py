"""Which of a drilled enclosure's planar levels are its walls.

Separate from ``case.py``, which owns the drilled plate's own path and whose
bytes ADR-0011 locks: a second question in that file is a second reason to
edit it. A wall is discovered and never declared -- see ADR-0007's amendment,
and ``tools/measure_walls.py`` for the measured populations it reasons from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from stompgeom.levels import Direction, Level, direction_bin, levels
from stompgeom.shapes import compound
from stompgeom.step import StepSolid
from stompmodel.frames import dot
from stompmodel.units import Nanometre

from ..errors import StompdrillError
from .case import _inner_level, _nearest_companion_level, _plates

__all__ = [
    "LATERAL_LIMIT",
    "Wall",
    "draft_degrees",
    "find_walls",
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

#: How many walls an enclosure this drills has. Four, and a fifth or a third
#: is refused rather than guessed at -- see ``find_walls``.
_WALLS = 4


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


@dataclass(frozen=True)
class Wall:
    """One wall of a drilled solid: its two surfaces, and what stands behind it.

    ``inner`` is the inner level's own coplanar patches plus its nearest
    companion's, which is exactly the bundle ``Faces.inner`` is -- so
    ``region.build_region`` and ``region.classify_bounds`` take a wall's
    without a branch. ``outer_faces`` is the outer level's patches, which is
    what the drillable region a builder marks is built from (see the plan's
    ruling 2).
    """

    outer: Level
    outer_faces: Any
    inner: Any
    plate_nm: Nanometre
    outward: Direction


def find_walls(solid: StepSolid, axis: int) -> tuple[Wall, ...]:
    """``solid``'s four walls, each paired with the surface behind it.

    Ordered on the signed axis each leans on, so a caller may rely on the
    order and no kernel walk reaches an artefact (ADR-0006). Four or it is
    refused: a box with three lateral groups is not an enclosure this drills,
    and guessing which wall is missing would be worse than saying so.
    """
    plates = _plates(list(levels(solid)))
    groups = _grouped_by_axis(list(lateral_plates(solid, axis)), axis)
    found = []
    for along in sorted(groups):
        outer = max(
            groups[along], key=lambda level: level.offset_nm * dot(level.direction, along)
        )
        parallel = _parallel_to(plates, outer)
        inner = _inner_level(parallel, outer)
        companion = _nearest_companion_level(parallel, inner)
        found.append(
            Wall(
                outer=outer,
                outer_faces=compound(outer.faces),
                inner=compound(inner.faces + (companion.faces if companion else ())),
                plate_nm=Nanometre(inner.offset_nm + outer.offset_nm),
                outward=outer.direction,
            )
        )
    return tuple(found)


def _grouped_by_axis(found: list[Level], axis: int) -> dict[Direction, list[Level]]:
    """Every lateral level under the signed kernel axis it leans on.

    Four groups or a refusal. A level leaning on the *drill* axis is refused
    rather than grouped: it is lateral by decision 5's definition yet binning
    it on that axis would silently pair it with the drilled face. Nothing
    measured comes within 87.5° of that case (ruling 8).
    """
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    along = (unit[0], unit[1], unit[2])
    groups: dict[Direction, list[Level]] = {}
    for level in found:
        leans = nearest_axis(level.direction)
        if abs(dot(leans, along)) > 0.5:
            raise StompdrillError(
                f"a lateral level facing {level.direction} leans on the drill axis, so "
                f"it belongs to no wall; this enclosure is not one this version drills"
            )
        groups.setdefault(leans, []).append(level)
    if len(groups) != _WALLS:
        raise StompdrillError(
            f"this solid has {len(groups)} lateral direction groups, not four walls; "
            f"an enclosure whose walls cannot be told apart is not one this drills"
        )
    return groups


def _parallel_to(found: list[Level], outer: Level) -> list[Level]:
    """Every level lying in a plane parallel to ``outer``'s own.

    Tested on the direction bin and not on a dot product: ``_partition``
    re-normalises every direction from its integer-millionths key, so two
    levels are parallel exactly when their bins are equal or exact negations.
    An equality, not a second tolerance to keep in step with the first.
    """
    key = direction_bin(outer.direction)
    opposite = (-key[0], -key[1], -key[2])
    return [
        level for level in found if direction_bin(level.direction) in {key, opposite}
    ]
