"""What version 7 added to the document, and nothing else.

A format that gains a field gains a version, so the drill document is the
one artefact ADR-0011's byte lock cannot cover. What is covered instead is
the difference: the version, one key per hole, one key at the top. The
reference was captured from version 6 itself, over the same hand-built
document, so this compares two codecs and not two readings.
"""

from __future__ import annotations

import json
from pathlib import Path

from stompmodel.codec import VERSION, to_document
from tests.documents import sample_data

__all__: list[str] = []

GOLDEN = Path(__file__).parent / "golden" / "document-v6.json"


def test_version_7_adds_a_surface_to_every_hole_and_one_section_at_the_top():
    previous = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = to_document(sample_data())

    assert current["version"] == VERSION == 7
    assert previous["version"] == 6
    assert current["surfaces"] is None
    assert [hole["surface"] for hole in current["holes"]] == ["face", "face"]


def test_version_7_moved_nothing_that_version_6_stated():
    """Every key version 6 wrote, at the same place, with the same value.

    The whole document is compared, not a chosen subset: a subset is how a
    moved coordinate or a renumbered hole goes unseen.
    """
    previous = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = to_document(sample_data())

    reduced = dict(current)
    reduced["version"] = 6
    reduced.pop("surfaces")
    reduced["holes"] = [
        {key: value for key, value in hole.items() if key != "surface"}
        for hole in reduced["holes"]
    ]

    assert reduced == previous


def test_the_key_order_version_6_wrote_is_still_a_prefix_of_this_one():
    """Key order is part of this document, so an addition must be an addition
    and not a reshuffle that happens to hold the same values."""
    previous = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = to_document(sample_data())

    assert list(current)[: len(previous)] == list(previous)
    assert list(current)[len(previous):] == ["surfaces"]
    for was, now in zip(previous["holes"], current["holes"], strict=True):
        assert list(now)[: len(was)] == list(was)
        assert list(now)[len(was):] == ["surface"]
