"""What a change invalidates, and what it must not."""

from __future__ import annotations

from stompcad import stale
from stompcad.drive import _STEP_CONSUMES, _STEP_HOLDS, _STEP_INPUTS
from stompcad.plan import DRILL_AND_DOCK

ORDER = tuple(step.key for step in DRILL_AND_DOCK.steps)


def _stale(*changed: str) -> frozenset[str]:
    return stale.stale_steps(ORDER, frozenset(changed), _STEP_INPUTS, _STEP_HOLDS, _STEP_CONSUMES)


def test_an_output_change_touches_only_the_write_steps() -> None:
    """The finding that forced this design: a filename must not cost kernel work."""
    assert _stale("targets") == {"write-case", "write-assembly"}


def test_a_position_rule_would_have_been_wrong() -> None:
    """The control: everything-after-the-earliest-reader is strictly larger."""
    earliest = min(
        index for index, key in enumerate(ORDER) if "targets" in _STEP_INPUTS.get(key, frozenset())
    )
    positional = set(ORDER[earliest:])
    assert positional > _stale("targets")
    assert "seat" in positional and "seat" not in _stale("targets")


def test_a_grid_change_invalidates_everything_downstream_of_quantise() -> None:
    invalidated = _stale("grid_mm")
    assert "quantise" in invalidated
    assert {"drill", "write-case", "read-boards", "match", "seat", "clash"} <= invalidated
    assert "read-panel" not in invalidated


def test_a_panel_reference_change_stops_at_the_dock_half() -> None:
    invalidated = _stale("panel_reference")
    assert "read-boards" in invalidated
    assert {"seat", "clash", "write-assembly"} <= invalidated
    assert not invalidated & {"read-panel", "quantise", "drill", "write-case"}


def test_nothing_changed_invalidates_nothing() -> None:
    assert _stale() == frozenset()


PLACE_FIELDS = tuple(stale.PLACE_OF_FIELD)


def test_a_step_with_no_inputs_is_never_the_earliest_stale_one() -> None:
    """Which is why `retry` never has to start at match, seat or clash."""
    for key in ("match", "seat", "clash"):
        assert not _STEP_INPUTS[key], key
        for field in PLACE_FIELDS:
            invalidated = _stale(field)
            if key in invalidated:
                assert ORDER.index(key) > min(ORDER.index(other) for other in invalidated)


def test_every_option_field_belongs_to_exactly_one_place() -> None:
    from dataclasses import fields

    from stompcad.drive import RunOptions

    assert set(stale.PLACE_OF_FIELD) == {field.name for field in fields(RunOptions)}
    assert set(stale.PLACE_OF_FIELD.values()) <= set(stale.PLACE_ORDER)


def test_the_marker_is_the_earliest_place_a_change_touched() -> None:
    assert stale.earliest_place(frozenset({"targets"})) == "output"
    assert stale.earliest_place(frozenset({"targets", "grid_mm"})) == "drilling"
    assert stale.earliest_place(frozenset({"panel", "targets"})) == "artwork"
    assert stale.earliest_place(frozenset()) is None


def test_every_step_consumes_only_attributes_some_step_holds() -> None:
    """A consumes row naming an attribute nobody produces would never propagate."""
    held = {attribute for attributes in _STEP_HOLDS.values() for attribute in attributes}
    for key, consumed in _STEP_CONSUMES.items():
        assert set(consumed) <= held, key
