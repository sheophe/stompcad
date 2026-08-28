"""Assembling a document from placed, named, coloured solids."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

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
    """A placement test that moves by translation alone is passed by a
    ``build_document`` reading only ``translation_mm`` and silently dropping
    ``rotation``. A box asymmetric in x and y,
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


def test_a_placed_solid_keeps_its_colour() -> None:
    """Placement and colour together, which no test above reaches: every
    placement test here is uncoloured and every colour test unplaced, and
    the two interact -- ``AddShape`` turns a *located* shape into a
    reference to the unlocated original, and a colour set on a reference
    is not the colour ``solid_colour`` resolves."""
    document = build_document([
        PlacedSolid(_box(2, 2, 2), "A", _RED, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
    ])
    solid = read_step_document(document).solids[0]
    got = solid_colour(document, solid)
    assert got is not None
    assert all(round(g - w, 6) == 0 for g, w in zip(got, _RED))


def test_two_placed_solids_sharing_one_base_shape_keep_distinct_colours() -> None:
    """The control on the fix: a real board's solids do share base shapes --
    ``tar-pcb.stp``'s 43 solids resolve to 18 distinct unlocated bases, the
    largest of them shared by 14 solids -- so a repair that coloured the
    *referred* label instead would paint a whole group one colour and lose
    every name in it but the last."""
    base = _box(2, 3, 4)
    document = build_document([
        PlacedSolid(base, "A", _RED, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
        PlacedSolid(base, "B", _GREEN, RigidTransform(_IDENTITY, (0.0, 20.0, 0.0))),
    ])
    solids = read_step_document(document).solids
    by_name = {solid.name: solid for solid in solids}
    assert set(by_name) == {"A", "B"}
    for name, wanted in (("A", _RED), ("B", _GREEN)):
        got = solid_colour(document, by_name[name])
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, wanted))


#: Repeated enough that two fresh allocations landing in the same slot
#: order by chance is unlikely, without the cost of a subprocess per try --
#: the same instrument ``test_writer``'s reslot control uses.
_TRIALS = 20


def test_placed_coloured_solids_render_identically_from_fresh_allocations() -> None:
    """The written half of the same defect, and the sharper one: a colour
    on a *located* shape is serialised as a ``PRESENTATION_STYLE_BY_CONTEXT``
    chain, which the census does not count and ``_COLOUR_CHAIN`` does not
    match -- so the guard sees zero of zero, the reslot is skipped, and the
    kernel's pointer-hashed colour order reaches the file unnormalised.
    Nothing raises; the bytes simply stop agreeing between allocations.
    """

    def rendered() -> bytes:
        document = build_document([
            PlacedSolid(_box(2, 2, 2), "A", _RED, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
            PlacedSolid(_box(3, 3, 3), "B", _GREEN, RigidTransform(_IDENTITY, (0.0, 30.0, 0.0))),
        ])
        return render_step(
            document, title="t",
            timestamp="1970-01-01T00:00:00+00:00", originating_system="t",
        )

    payloads = {rendered() for _ in range(_TRIALS)}

    assert len(payloads) == 1
    # Grounding: agreement over a document carrying no colour chain at all
    # would prove nothing about the region this test is named for.
    assert next(iter(payloads)).count(b"STYLED_ITEM") == 2


def test_a_coloured_and_an_uncoloured_placement_share_one_base_shape() -> None:
    """The mixed document the assembly emitter actually builds: only the
    coloured solid needs its own product, so both structures appear in one
    file and must not disturb each other's colour region."""
    base = _box(2, 3, 4)
    document = build_document([
        PlacedSolid(base, "A", _RED, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
        PlacedSolid(base, "B", None, RigidTransform(_IDENTITY, (0.0, 20.0, 0.0))),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    assert payload.count(b"STYLED_ITEM") == 1

    solids = read_step_document(document).solids
    by_name = {solid.name: solid for solid in solids}
    assert set(by_name) == {"A", "B"}
    assert solid_colour(document, by_name["B"]) is None
    got = solid_colour(document, by_name["A"])
    assert got is not None
    assert all(round(g - w, 6) == 0 for g, w in zip(got, _RED))


def test_a_placed_coloured_solid_rereads_from_a_written_file(tmp_path: Path) -> None:
    """Placement and colour together through a real round trip, the way the
    assembly emitter writes them."""
    document = build_document([
        PlacedSolid(_box(2, 2, 2), "A", _RED, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
        PlacedSolid(_box(3, 3, 3), "B", _GREEN, RigidTransform(_IDENTITY, (0.0, 30.0, 0.0))),
    ])
    path = tmp_path / "placed.stp"
    path.write_bytes(render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    ))

    reread = read_step(path)
    by_name = {solid.name: solid for solid in reread.solids}
    assert round(bounding_box_mm(by_name["A"].shape)[0], 9) == 10.0
    for name, wanted in (("A", _RED), ("B", _GREEN)):
        got = solid_colour(reread.document, by_name[name])
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, wanted))


#: The one collapse ``AddShape`` performs, measured rather than assumed:
#: two solids over one base shape survive as separate labels when each is
#: *located* -- with the same placement or different ones -- and are lost
#: only when one of them is added unlocated, because that free label is
#: what the located sibling then refers to. So the repair is narrow, and
#: these two tests are what hold it to the collapsing case.


def test_an_unlocated_and_a_located_solid_over_one_base_both_survive() -> None:
    """``PlacedSolid`` invites placing one shape twice -- two identical
    footswitches on one board -- and an unplaced solid over the same base
    used to vanish, its colour reappearing on the placed one. Both input
    orders, because the collapse happened either way round."""
    for reverse in (False, True):
        base = _box(2, 3, 4)
        entries = [
            PlacedSolid(base, "A", _RED, None),
            PlacedSolid(base, "B", None, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
        ]
        document = build_document(list(reversed(entries)) if reverse else entries)

        by_name = {solid.name: solid for solid in read_step_document(document).solids}

        assert set(by_name) == {"A", "B"}, f"reversed={reverse}"
        assert solid_colour(document, by_name["B"]) is None
        got = solid_colour(document, by_name["A"])
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, _RED))


def test_two_unlocated_solids_over_one_base_both_survive() -> None:
    """The same collapse with no placement in sight: two unplaced solids
    over one base resolved to one label, so the first name was lost."""
    base = _box(2, 3, 4)
    document = build_document([
        PlacedSolid(base, "A", _RED, None),
        PlacedSolid(base, "B", _GREEN, None),
    ])

    by_name = {solid.name: solid for solid in read_step_document(document).solids}

    assert set(by_name) == {"A", "B"}
    for name, wanted in (("A", _RED), ("B", _GREEN)):
        got = solid_colour(document, by_name[name])
        assert got is not None
        assert all(round(g - w, 6) == 0 for g, w in zip(got, wanted))


def test_placing_one_base_shape_twice_writes_one_product() -> None:
    """The guard on the repair's scope, not on a bug: two *located* solids
    over one base never collapsed, so neither may be given a shape of its
    own. Wrapping them defensively would double every assembly of repeated
    parts -- measured at 2.2x on ``tar-pcb.stp`` -- for nothing.
    """
    base = _box(2, 3, 4)
    document = build_document([
        PlacedSolid(base, "A", None, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
        PlacedSolid(base, "B", None, RigidTransform(_IDENTITY, (20.0, 0.0, 0.0))),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )

    assert {solid.name for solid in read_step_document(document).solids} == {"A", "B"}
    assert payload.count(b"= MANIFOLD_SOLID_BREP") == 1


def test_a_shared_base_document_renders_identically_across_processes() -> None:
    """The structure decision is taken per batch, so it is a new place for
    process history to leak. ``IsSame`` is the kernel's own identity and a
    Python ``id()`` would not be; distinct hash seeds are what perturb the
    allocation pattern an address comes from."""
    script = (
        "from stompgeom.writer import render_step;"
        "from tests.fixtures.shared_base import shared_base_document;"
        "import hashlib,sys;"
        "sys.stdout.write(hashlib.sha256(render_step("
        "shared_base_document(), title='p',"
        "timestamp='1970-01-01T00:00:00+00:00', originating_system='t')).hexdigest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("0", "1", "2", "3", "4", "5")
    }

    assert len(digests) == 1
    assert digests != {""}


def test_a_solids_colour_reads_back() -> None:
    """The published reading half ``Order of work`` in
    ``docs/specs/stompcollider-technical.md`` requires."""
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
    """The writer's reslot is what makes a shared colour safe to write; this is the
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
    way a caller writing an assembly does."""
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
    """The shared-colour case, through the same real round trip: the writer's
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


# --------------------------------------------------------------------------
# A PlacedSolid validates at construction: OCC raises from inside
# Quantity_Color about a colour, naming no solid, so the refusal is here.
# --------------------------------------------------------------------------


def test_a_well_formed_placed_solid_is_the_control() -> None:
    """The anchor: this shape constructs, so each refusal below refuses the
    one defect it names rather than everything."""
    solid = PlacedSolid(_box(2, 2, 2), "A", _RED, RigidTransform(_IDENTITY, (1.0, 0.0, 0.0)))
    assert solid.colour == _RED


def test_a_placed_solid_with_no_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="must be a kernel shape"):
        PlacedSolid(None, "A", None, None)


def test_a_colour_with_two_components_is_refused() -> None:
    with pytest.raises(ValueError, match="three components"):
        PlacedSolid(_box(2, 2, 2), "A", (0.1, 0.2), None)  # type: ignore[arg-type]


def test_a_non_finite_colour_component_is_refused() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        PlacedSolid(_box(2, 2, 2), "A", (float("nan"), 0.2, 0.3), None)


def test_a_colour_component_above_one_is_refused() -> None:
    """``Quantity_Color`` runs 0..1; 255 is the spelling that looks right."""
    with pytest.raises(ValueError, match=r"run 0.0 to 1.0"):
        PlacedSolid(_box(2, 2, 2), "A", (255.0, 0.0, 0.0), None)


def test_a_negative_colour_component_is_refused() -> None:
    with pytest.raises(ValueError, match=r"run 0.0 to 1.0"):
        PlacedSolid(_box(2, 2, 2), "A", (-0.01, 0.0, 0.0), None)


def test_an_uncoloured_placed_solid_still_constructs() -> None:
    """``None`` is "no colour of its own", not a colour to check."""
    assert PlacedSolid(_box(2, 2, 2), "A", None, None).colour is None


def test_the_bounds_of_the_colour_range_are_admitted() -> None:
    """Both endpoints are legal colours, so the check is a range and not a
    strict interval that would refuse pure black or pure white."""
    assert PlacedSolid(_box(2, 2, 2), "A", (0.0, 0.0, 0.0), None).colour == (0.0, 0.0, 0.0)
    assert PlacedSolid(_box(2, 2, 2), "B", (1.0, 1.0, 1.0), None).colour == (1.0, 1.0, 1.0)
