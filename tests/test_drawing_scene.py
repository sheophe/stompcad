"""Backend-neutral drawing primitives."""

from __future__ import annotations

import dataclasses

import pytest

from aidrill.emitters.drawing.scene import (
    FEINT,
    INK,
    RED,
    Circle,
    Group,
    Line,
    Polygon,
    Rect,
    Scene,
    Stroke,
    Text,
)
from aidrill.emitters.drawing.sheet import A4_PORTRAIT

THIN = Stroke(0.35, INK)


def test_every_primitive_is_frozen_and_slotted():
    """Primitives are value objects, so a backend cannot edit the scene it renders."""
    for item in (
        Line(0.0, 0.0, 1.0, 1.0, THIN),
        Circle(1.0, 2.0, 3.0, THIN),
        Rect(0.0, 0.0, 10.0, 5.0, THIN),
        Polygon(((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)), INK),
        Text(1.0, 2.0, "⌀7.000", 2.5),
        Group("sched-row"),
    ):
        assert dataclasses.is_dataclass(item)
        with pytest.raises(dataclasses.FrozenInstanceError):
            item.cls = "mutated"
        # slots=True means no instance dictionary to smuggle state through.
        assert not hasattr(item, "__dict__")


def test_a_stroke_carries_its_dashes_and_defaults_to_solid():
    """A dash pattern belongs to the stroke, not to the primitive drawn with it."""
    assert Stroke(0.35, FEINT).dashes == ()
    assert Stroke(0.35, FEINT, (12.0, 3.0, 1.0, 3.0)).dashes == (12.0, 3.0, 1.0, 3.0)


def test_a_scene_replaces_its_items_rather_than_appending_in_place():
    """Building a scene is folding, so each step yields a new scene."""
    first = Scene(A4_PORTRAIT, (Line(0.0, 0.0, 1.0, 1.0, THIN),))
    second = first.with_items((*first.items, Circle(0.0, 0.0, 2.0, THIN)))

    assert len(first.items) == 1
    assert len(second.items) == 2
    assert second.sheet is first.sheet


def test_a_circle_is_hollow_unless_it_is_told_otherwise():
    """A balloon has to hide what it lands on; every other circle must not."""
    assert Circle(0.0, 0.0, 3.0, THIN).fill == "none"
    assert Circle(0.0, 0.0, 3.0, THIN, fill="#ffffff").fill == "#ffffff"


def test_a_group_nests_the_marks_that_belong_to_one_thing():
    """One schedule row is one group, so a reader can select the whole of it."""
    row = Group("sched-row", (Text(0.0, 0.0, "7", 2.5), Text(9.0, 0.0, "T1", 2.5)))
    outer = Group("schedule", (row,))

    assert Group("empty").items == ()
    assert outer.items == (row,)
    assert [item.content for item in row.items] == ["7", "T1"]


def test_text_carries_an_anchor_the_scene_does_not_interpret():
    """Anchoring is a backend concern; the scene only records the intent."""
    assert Text(0.0, 0.0, "T1", 2.5).anchor == "start"
    assert Text(0.0, 0.0, "T1", 2.5, anchor="middle").anchor == "middle"
    assert Text(0.0, 0.0, "T1", 2.5, colour=RED).colour == RED
