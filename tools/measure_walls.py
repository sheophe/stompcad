"""Print the measured wall populations the wall-drilling design reasons from.

A tool and not a test, because a human comparing seven castings wants the
numbers laid out; ``packages/stompdrill/tests/test_walls_evidence.py`` is
what fails when one of them drifts. Reads the cached models the workbench
already fetches and downloads nothing.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from stompdrill.cad.case import facing, plates, select_solid
from stompdrill.cad.walls import (
    draft_degrees,
    find_walls,
    lateral_plates,
    nearest_axis,
)
from stompgeom.levels import Direction, Level, direction_bin, levels
from stompgeom.step import StepSolid, assembly_spans, read_step
from stompmodel.frames import dot
from stompmodel.model import CaseFace
from stompmodel.units import mm_from_nm

__all__ = ["cache_dir", "cached_parts", "level_draft", "main"]

#: Every part the Evidence covers, in catalogue order.
PARTS = (
    "1590A", "1590B", "1590B2", "1590BB", "1590BB2", "1590BBS", "1590BS", "1590LB",
    "1590Y",
)


def cache_dir() -> Path:
    """Where the workbench caches enclosure models: ``$XDG_CACHE_HOME`` else ``~/.cache``."""
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "stompcad" / "cases"



def cached_parts() -> tuple[str, ...]:
    """Every casting the cache holds, in catalogue order.

    ``PARTS`` names the nine the Evidence quotes, which is the right
    population for a draft or an area. A rule about what a wall *is* has to
    answer for every casting a workbench may fetch, so the inner-face
    measurement sweeps whatever has been cached instead.
    """
    return tuple(sorted(path.stem for path in cache_dir().glob("*.stp")))


def _wall_outers(solid: StepSolid, axis: int) -> list[tuple[Direction, Level]]:
    """Each wall's outer level, under the signed kernel axis it leans on.

    The same grouping ``find_walls`` does, repeated here rather than exposed
    from it: this tool prints the candidates a pairing rule chooses *between*,
    which means it must reach the state before the choice.
    """
    groups: dict[Direction, list[Level]] = {}
    for level in lateral_plates(solid, axis):
        groups.setdefault(nearest_axis(level.direction), []).append(level)
    return [
        (
            lean,
            max(groups[lean], key=lambda level: level.offset_nm * dot(level.direction, lean)),
        )
        for lean in sorted(groups)
    ]


def level_draft(direction: Direction) -> float:
    """A level's own draft: how far its plane tilts off the axis it leans on, in degrees.

    The angle a casting is published with, reached without being told which
    axis is the drill's -- a level is all a pairing rule holds. Named rather
    than inlined because the arithmetic hides the quantity: ``draft_degrees``
    measures tilt *out of* the plane perpendicular to the axis it is handed,
    so against a level's own leaning axis it answers the complement, and a
    right angle less that complement is the draft.
    """
    return 90.0 - draft_degrees(direction, nearest_axis(direction))


def _inner_face_block(solid: StepSolid, axis: int, group: str = "wall") -> None:
    """Print, per lateral group, what the pairing rule chooses and what between.

    The ``elsewhere`` row is the measurement's point: it is the nearest level
    behind the group leaning on some other axis, and where its gap is zero no
    depth and no area can tell a wall's own inner face from a sibling wall's.
    A ``draft refused`` row names a level the inequality turns away, marked
    ``nearest`` where that level is the one depth alone would have taken, so a
    clause that moved an answer is visible. A group the rule cannot answer
    prints ``none`` rather than a plate of zero.
    """
    slabs = plates(list(levels(solid)))
    recorded = {
        nearest_axis(wall.outward): wall.plate_nm for wall in find_walls(solid, axis)
    }
    for lean, outer in _wall_outers(solid, axis):
        back = (-lean[0], -lean[1], -lean[2])
        # Only an opposing level's offset sum is the material between two
        # planes, so only those are rivals this comparison can even state.
        behind = sorted(
            (
                level
                for level in slabs
                if facing(level, outer) < 0 and level.offset_nm + outer.offset_nm > 0
            ),
            key=lambda level: level.offset_nm + outer.offset_nm,
        )
        on_axis = [level for level in behind if nearest_axis(level.direction) == back]
        other = [level for level in behind if nearest_axis(level.direction) != back]
        # Applied, because the rule applies it: a candidate drafting further
        # than the outer face is no inner face, so the nearest on this axis is
        # not always the answer.
        limit = level_draft(outer.direction)
        admitted = [level for level in on_axis if level_draft(level.direction) <= limit]
        chosen = admitted[0] if admitted else None
        answer = f"{chosen.offset_nm + outer.offset_nm:9d} nm" if chosen else "     none"
        # Both drafts, because their difference is what the inequality
        # compares and a reader checking the rule should not have to infer
        # either side of it.
        inner_draft = f"{level_draft(chosen.direction):6.3f}\u00b0" if chosen else "    --"
        print(
            f"    {group} {lean}  recorded {recorded[lean]:9d} nm  "
            f"under the rule {answer}  "
            f"drafts outer {level_draft(outer.direction):6.3f}\u00b0 inner {inner_draft}"
        )
        for level in on_axis:
            if level_draft(level.direction) <= limit:
                continue
            mark = "nearest" if level is on_axis[0] else "       "
            print(
                f"      draft refused {mark}  {level.offset_nm + outer.offset_nm:9d} nm  "
                f"{level.area_mm2:10.3f} mm\u00b2  "
                f"draft {level_draft(level.direction):6.3f}\u00b0"
            )
        # The next level the rule would accept, not the next on the axis: a
        # refused one already has its own row, and printing it twice -- once as
        # the chosen level, where the clause moved the answer -- reads as two
        # findings.
        for label, found in (("next on this axis", admitted[1:2]), ("nearest elsewhere", other[:1])):
            for level in found:
                plate = level.offset_nm + outer.offset_nm
                gap = plate - (chosen.offset_nm + outer.offset_nm if chosen else 0)
                print(
                    f"      {label}  {plate:9d} nm  {gap:+10d} nm  "
                    f"{level.area_mm2:10.3f} mm²  leaning {nearest_axis(level.direction)}  "
                    f"draft {level_draft(level.direction):6.3f}°"
                )


def _inner_face_main(wanted: Sequence[str]) -> int:
    """Print, for every named casting, the population the inner-face rule decides on.

    A mode of its own rather than more of the default block: the default
    prints a casting's drafts and areas, and this prints the one comparison
    the pairing turns on. The box is where the program discovers walls. The
    lid is swept too, and labelled ``rim``, because its lateral groups are a
    closure flange rather than anything drillable, and seeing what the rule
    would make of one is the evidence that a lid is given no walls at all
    (ADR-0007). Names the parts it could not find rather than failing.
    """
    missing = [part for part in wanted if not (cache_dir() / f"{part}.stp").is_file()]
    for part in wanted:
        path = cache_dir() / f"{part}.stp"
        if not path.is_file():
            continue
        document = read_step(path)
        spans = assembly_spans(document)
        axis = min(range(3), key=lambda index: spans[index])
        for face, group in ((CaseFace.BOX, "wall"), (CaseFace.LID, "rim")):
            aside = " (no wall is discovered here)" if group == "rim" else ""
            print(f"{part} {face.value}: drill axis {axis}{aside}")
            _inner_face_block(select_solid(document, face), axis, group)
    if missing:
        print(f"not cached: {', '.join(missing)}", file=sys.stderr)
    return 0


#: Every flag this tool takes. A mistyped one is refused rather than ignored:
#: dropping it would run the default block and look like a successful
#: measurement of something nobody asked for.
_FLAGS = frozenset({"--inner-face"})


def main(argv: Sequence[str] | None = None) -> int:
    """Print one block per model. Names the parts it could not find rather than failing."""
    arguments = list(argv) if argv else []
    unknown = [value for value in arguments if value.startswith("-") and value not in _FLAGS]
    if unknown:
        print(
            f"unrecognised: {', '.join(unknown)}; this tool takes "
            f"{', '.join(sorted(_FLAGS))} and part names",
            file=sys.stderr,
        )
        return 2
    named = tuple(value for value in arguments if not value.startswith("-"))
    if "--inner-face" in arguments:
        return _inner_face_main(named or cached_parts())
    wanted = named or PARTS
    missing = [part for part in wanted if not (cache_dir() / f"{part}.stp").is_file()]
    for part in wanted:
        path = cache_dir() / f"{part}.stp"
        if not path.is_file():
            continue
        document = read_step(path)
        spans = assembly_spans(document)
        axis = min(range(3), key=lambda index: spans[index])
        unit = [0.0, 0.0, 0.0]
        unit[axis] = 1.0
        along = (unit[0], unit[1], unit[2])
        solid = select_solid(document, CaseFace.BOX)
        slabs = plates(list(levels(solid)))
        lateral = lateral_plates(solid, axis)
        drafts = sorted(
            {
                round(draft_degrees(level.direction, along), 3)
                for level in lateral
                if draft_degrees(level.direction, along) > 0.0
            }
        )
        drafted = {
            direction_bin(level.direction)
            for level in lateral
            if draft_degrees(level.direction, along) > 0.0
        }
        print(f"{part}: drill axis {axis}, {len(slabs)} plate levels")
        print(f"  draft {', '.join(f'{value:.3f}°' for value in drafts) or 'none'}")
        print(
            f"  {len(lateral)} lateral plate levels in "
            f"{len({direction_bin(level.direction) for level in lateral})} direction bins, "
            f"{len(drafted)} drafted"
        )
        for level in sorted(lateral, key=lambda level: -level.area_mm2)[:12]:
            print(
                f"    {draft_degrees(level.direction, along):7.3f}°  "
                f"{level.area_mm2:9.2f} mm²  offset {mm_from_nm(level.offset_nm):9.3f} mm  "
                f"{tuple(round(component, 6) for component in level.direction)}"
            )
        for wall in find_walls(solid, axis):
            print(
                f"    wall {tuple(round(c, 6) for c in wall.outward)}  "
                f"outer {wall.outer.area_mm2:9.2f} mm²  "
                f"plate {mm_from_nm(wall.plate_nm):.4f} mm"
            )
    if missing:
        print(f"not cached: {', '.join(missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
