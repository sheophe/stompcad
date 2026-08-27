"""Assembling a document from placed, named, coloured solids."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stompgeom.build import PlacedSolid, build_document, solid_colour
from stompgeom.step import bounding_box_mm, read_step, read_step_document
from stompgeom.writer import render_step
from stompmodel.frames import RigidTransform

_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

#: Neither is one of STEP's pre-defined colours (see ``tests/xcaf.py``'s own
#: note): a pure red or green is written as ``DRAUGHTING_PRE_DEFINED_COLOUR``
#: instead of ``COLOUR_RGB``, a chain shape ``_reslot_colours`` refuses to
#: reorder outright -- confirmed against this OpenCASCADE build, where two
#: pure-primary leaves make ``render_step`` raise "foreign entities between
#: chains" rather than write anything. That refusal is real and correct; it
#: is just not what this test means to exercise, so it is avoided by choice
#: of colour, not silenced.
_RED = (0.21, 0.43, 0.65)
_GREEN = (0.75, 0.31, 0.12)


def _box(dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def test_a_built_document_renders_without_a_census_mismatch() -> None:
    """The precondition: colouring through a route the census does not walk
    fails with a message about OpenCASCADE versions, not about colour.

    ``render_step`` checks its own colour census against the written colour
    chains *before* returning any bytes (``writer._reslot_colours``'s count
    guard runs ahead of the reslot itself), so a mismatch here would raise
    rather than let the assertion below run against wrong-shaped bytes.
    """
    document = build_document([
        PlacedSolid(_box(1, 1, 1), "A", _RED, None),
        PlacedSolid(_box(2, 2, 2), "B", _GREEN, None),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    assert b"'A'" in payload and b"'B'" in payload


def test_a_placement_moves_the_solid_in_the_built_document() -> None:
    document = build_document([
        PlacedSolid(_box(2, 2, 2), "A", None, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
    ])
    solids = read_step_document(document).solids
    assert round(bounding_box_mm(solids[0].shape)[0], 9) == 10.0


def test_a_rotating_placement_turns_an_asymmetric_solid_too() -> None:
    """The brief's own placement test moves by translation alone, so a
    ``build_document`` that reads only ``translation_mm`` and silently
    drops ``rotation`` would still pass it. A box asymmetric in x and y,
    turned 90 degrees about z, swaps which axis is long -- a fact only the
    rotation, not the translation, can produce."""
    rotate_90_about_z = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    document = build_document([
        PlacedSolid(
            _box(2, 6, 1), "A", None, RigidTransform(rotate_90_about_z, (5.0, 7.0, 0.0))
        ),
    ])
    solids = read_step_document(document).solids
    box = tuple(round(v, 9) for v in bounding_box_mm(solids[0].shape))
    assert box == (-1.0, 7.0, 0.0, 5.0, 9.0, 1.0)


def test_an_absent_placement_leaves_the_solid_where_it_was() -> None:
    """The innocent probe: None must mean untouched, not identity-applied."""
    document = build_document([PlacedSolid(_box(2, 2, 2), "A", None, None)])
    solids = read_step_document(document).solids
    assert round(bounding_box_mm(solids[0].shape)[0], 9) == 0.0


def test_a_solids_colour_reads_back() -> None:
    """The published reading half stompcollider-technical.md:598-602 requires."""
    document = build_document([PlacedSolid(_box(1, 1, 1), "A", (1.0, 0.0, 0.0), None)])
    solid = read_step_document(document).solids[0]
    assert solid_colour(document, solid) == (1.0, 0.0, 0.0)


def test_an_uncoloured_solid_reads_back_as_none() -> None:
    document = build_document([PlacedSolid(_box(1, 1, 1), "A", None, None)])
    solid = read_step_document(document).solids[0]
    assert solid_colour(document, solid) is None


def test_several_distinctly_coloured_solids_all_read_back_correctly() -> None:
    """A builder that stops after the first solid, or paints every solid the
    same colour, would still pass a two-solid or uniform-colour test."""
    colours = (_RED, _GREEN, (0.10, 0.55, 0.90), (0.60, 0.60, 0.05))
    document = build_document([
        PlacedSolid(_box(1 + index, 1 + index, 1 + index), f"S{index}", colour, None)
        for index, colour in enumerate(colours)
    ])
    solids = read_step_document(document).solids
    assert len(solids) == len(colours)
    read_back = [solid_colour(document, solid) for solid in solids]
    assert all(
        got is not None and all(round(g - w, 6) == 0 for g, w in zip(got, wanted))
        for got, wanted in zip(read_back, colours)
    )


def test_a_colour_shared_by_several_solids_reads_back_on_each() -> None:
    """Task 8's reslot made a shared colour safe to write; this is the
    builder-level control that a repeated colour still resolves per-solid,
    not just once for whichever chain happened to define it."""
    document = build_document([
        PlacedSolid(_box(1, 1, 1), "P0", _RED, None),
        PlacedSolid(_box(2, 2, 2), "P1", _RED, None),
        PlacedSolid(_box(3, 3, 3), "P2", _RED, None),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    assert all(name in payload for name in (b"'P0'", b"'P1'", b"'P2'"))

    solids = read_step_document(document).solids
    assert len(solids) == 3
    for solid in solids:
        got = solid_colour(document, solid)
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, _RED))


def test_distinct_colours_survive_a_render_and_reread_round_trip(tmp_path: Path) -> None:
    """Every colour assertion above reads the same in-memory ``document``
    ``build_document`` produced -- ``solid_colour`` returns the identical
    value whether or not ``render_step`` ever ran, so those prove
    ``build_document`` and ``solid_colour`` agree with each other and
    nothing about the write path. This is the one that reaches a *written*
    colour: render, write bytes to a real file, read a fresh document back
    through ``read_step``, and check the colour there -- exercising
    ``writer``'s gamma-encoded ``COLOUR_RGB`` and its reslot together, the
    way Task 21's caller will."""
    document = build_document([
        PlacedSolid(_box(1, 1, 1), "A", _RED, None),
        PlacedSolid(_box(2, 2, 2), "B", _GREEN, None),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    path = tmp_path / "distinct.stp"
    path.write_bytes(payload)

    reread = read_step(path)
    by_name = {solid.name: solid for solid in reread.solids}
    for name, wanted in (("A", _RED), ("B", _GREEN)):
        got = solid_colour(reread.document, by_name[name])
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, wanted))


def test_a_shared_colour_survives_a_render_and_reread_round_trip(tmp_path: Path) -> None:
    """The shared-colour case, through the same real round trip: Task 8's
    canonicalisation of which chain of a repeated colour defines it is
    exactly the code path a lost or scrambled colour would hide in, and the
    in-memory tests above cannot reach it at all."""
    document = build_document([
        PlacedSolid(_box(1, 1, 1), "P0", _RED, None),
        PlacedSolid(_box(2, 2, 2), "P1", _RED, None),
        PlacedSolid(_box(3, 3, 3), "P2", _RED, None),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    path = tmp_path / "shared.stp"
    path.write_bytes(payload)

    reread = read_step(path)
    assert len(reread.solids) == 3
    for solid in reread.solids:
        got = solid_colour(reread.document, solid)
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, _RED))
