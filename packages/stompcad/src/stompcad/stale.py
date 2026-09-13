"""What a change invalidated, and the place the roadmap falls back to.

Spec decision 10. Two derived answers, one change set: the steps to run
again, and the earliest place the sidebar marks. Deriving both from the
same input is what stops the roadmap from disagreeing with the engine --
there is no second thing to keep in step.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

__all__ = ["PLACE_ORDER", "PLACE_OF_FIELD", "stale_steps", "earliest_place"]

#: The five configuration places, in the order the sidebar lists them.
PLACE_ORDER: tuple[str, ...] = ("artwork", "enclosure", "drilling", "boards", "output")

#: Which place owns each option field. The sidebar's marker is derived from
#: this rather than from which step went stale, because a change originates in
#: a place: the grid is read by ``quantise`` but belongs to ``Drilling``, and a
#: marker pointing at ``Enclosure`` for a grid edit would be pointing at the
#: wrong row.
PLACE_OF_FIELD: dict[str, str] = {
    "panel": "artwork",
    "drill_layer": "artwork",
    "reference_layer": "artwork",
    "form_depth": "artwork",
    "case": "enclosure",
    "case_model": "enclosure",
    "case_face": "enclosure",
    "case_margin_mm": "enclosure",
    "grid_mm": "drilling",
    "grid_warn_mm": "drilling",
    "drill_standard": "drilling",
    "drill_sizes": "drilling",
    "no_drill_sizes": "drilling",
    "title": "drilling",
    "boards": "boards",
    "panel_reference": "boards",
    "match_tolerance_mm": "boards",
    "seat_pitch_max_mm": "boards",
    "seat_pitch_min_mm": "boards",
    "targets": "output",
}


def stale_steps(
    order: Sequence[str],
    changed: frozenset[str],
    inputs: Mapping[str, frozenset[str]],
    holds: Mapping[str, tuple[str, ...]],
    consumes: Mapping[str, tuple[str, ...]],
) -> frozenset[str]:
    """Every step a change invalidated: those reading it, and those reading them.

    Propagation follows data. A step is stale when it reads a changed field,
    or when an *earlier* step producing something it consumes is stale --
    earlier because the dock stages each overwrite one attribute, so "the
    producer" is a position rather than a name.
    """
    stale: set[str] = set()
    for index, key in enumerate(order):
        if inputs.get(key, frozenset()) & changed:
            stale.add(key)
            continue
        wanted = set(consumes.get(key, ()))
        if any(
            earlier in stale and wanted.intersection(holds.get(earlier, ()))
            for earlier in order[:index]
        ):
            stale.add(key)
    return frozenset(stale)


def earliest_place(changed: frozenset[str]) -> str | None:
    """The place the roadmap falls back to, or ``None`` when nothing changed."""
    touched = {PLACE_OF_FIELD[field] for field in changed if field in PLACE_OF_FIELD}
    if not touched:
        return None
    return min(touched, key=PLACE_ORDER.index)
