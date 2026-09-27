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

from stompdrill.cad.case import _plates, select_solid
from stompdrill.cad.walls import draft_degrees, find_walls, lateral_plates
from stompgeom.levels import direction_bin, levels
from stompgeom.step import assembly_spans, read_step
from stompmodel.model import CaseFace
from stompmodel.units import mm_from_nm

__all__ = ["cache_dir", "main"]

#: Every part the Evidence covers, in catalogue order.
PARTS = ("1590A", "1590B", "1590BB", "1590BB2", "1590BBS", "1590LB", "1590Y")


def cache_dir() -> Path:
    """Where the workbench caches enclosure models: ``$XDG_CACHE_HOME`` else ``~/.cache``."""
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "stompcad" / "cases"


def main(argv: Sequence[str] | None = None) -> int:
    """Print one block per model. Names the parts it could not find rather than failing."""
    wanted = tuple(argv) if argv else PARTS
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
        plates = _plates(list(levels(solid)))
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
        print(f"{part}: drill axis {axis}, {len(plates)} plate levels")
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
