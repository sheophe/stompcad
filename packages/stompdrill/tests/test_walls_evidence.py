"""The wall-drilling spec's Evidence, as assertions over the cached models.

A figure a design argues from is a figure a suite has to hold: these are the
measurements decision 5 reasons about, and a drift in any of them makes that
reasoning stale rather than merely inaccurate. ``tools/measure_walls.py``
prints the same numbers for a human. See ``_model_path`` for why this reads
the cache directly rather than through ``hammond.require_model``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompdrill.cad.case import _plates, select_solid
from stompdrill.cad.walls import draft_degrees, lateral_plates
from stompgeom.levels import direction_bin, levels
from stompgeom.step import StepSolid, assembly_spans, read_step
from stompmodel.model import CaseFace

from . import hammond

__all__: list[str] = []

#: Every catalogued box's own wall draft, in degrees, and how many direction
#: bins its lateral plate levels fall into. Measured, not published: Hammond
#: states no draft. The bin count is a property of the casting's internal
#: features as much as its walls, which is why it varies and why nothing
#: reasons from it -- it is recorded so a change in the models is visible.
EVIDENCE: dict[str, tuple[tuple[float, ...], int, int]] = {
    "1590A": ((1.500,), 29, 8),
    "1590B": ((1.250,), 29, 8),
    "1590BB": ((2.500,), 29, 8),
    "1590BB2": ((1.150,), 30, 8),
    "1590BBS": ((1.250,), 31, 8),
    "1590LB": ((1.300, 1.400), 28, 12),
    "1590Y": ((1.500,), 33, 8),
}


def _model_path(part: str) -> Path:
    """The cached model for ``part``, skipping rather than fetching or failing.

    ``hammond.require_model`` gates on ``hammond.MODELS``, a four-part
    catalogue ``test_hammond_harness.py`` locks; three of the seven parts
    here (1590BB2, 1590BBS, 1590LB) sit outside it, so that gate would raise
    rather than skip. This mirrors its cache-hit path without the gate.
    """
    path = hammond.cache_dir() / f"{part}.stp"
    if not path.is_file():
        pytest.skip(f"{part} is not cached")
    return path


def _box(part: str) -> tuple[StepSolid, int]:
    document = read_step(_model_path(part))
    spans = assembly_spans(document)
    axis = min(range(3), key=lambda index: spans[index])
    return select_solid(document, CaseFace.BOX), axis


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_every_wall_level_sits_at_this_model_s_own_draft(part: str) -> None:
    drafts, _bins, _drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    found = {
        round(draft_degrees(level.direction, (unit[0], unit[1], unit[2])), 3)
        for level in _plates(list(levels(solid)))
    }
    assert found == {0.0, 90.0} | set(drafts)


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_nothing_sits_between_the_draft_and_a_right_angle(part: str) -> None:
    """The measured gap the 45-degree boundary is never asked to decide inside.

    The margin is 1e-3 degrees, not the brief's original 1e-6: every cached
    model's own drafted levels measure 3e-5 to 3e-6 degrees off their nominal
    figure (the STEP file's own normal is not exact), which false-failed the
    1e-6 margin though no third population exists. 1e-3 clears that noise by
    two to three orders while staying under 1 degree of the nearest real
    draft or the 87.5-88.85 degree gap to 90 -- so it still catches a real
    intermediate population if the kernel or a model ever produced one.
    """
    drafts, _bins, _drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    degrees = [
        draft_degrees(level.direction, (unit[0], unit[1], unit[2]))
        for level in _plates(list(levels(solid)))
    ]
    between = [value for value in degrees if max(drafts) + 1e-3 < value < 90.0 - 1e-3]
    assert between == []


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_the_lateral_plate_levels_fall_into_the_bins_recorded(part: str) -> None:
    _drafts, bins, drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    lateral = lateral_plates(solid, axis)
    assert len({direction_bin(level.direction) for level in lateral}) == bins
    assert len(
        {
            direction_bin(level.direction)
            for level in lateral
            if draft_degrees(level.direction, (unit[0], unit[1], unit[2])) > 0.0
        }
    ) == drafted


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_the_drill_axis_is_the_shallowest_and_the_walls_are_not_on_it(part: str) -> None:
    solid, axis = _box(part)
    assert axis == 1
    for level in lateral_plates(solid, axis):
        assert abs(level.direction[axis]) < 0.05
