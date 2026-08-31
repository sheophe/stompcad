"""Colour resolved off solids as a STEP file really records them.

``build_document`` writes a colour onto the label owning the whole shape,
and every test built that way reads it straight back. Real files do not
look like that: a component instance carries a *located* shape while the
colour sits on the product it refers to, and a component modelled face by
face carries no whole-solid colour at all. Both are round-tripped here
through this package's own writer and reader rather than committed, for
the reason ``fixtures/per_face_colours.py`` states.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stompgeom.build import solid_colour
from stompgeom.step import StepDocument, read_step
from stompgeom.writer import render_step

from .fixtures.per_face_colours import (
    BROAD_COLOUR,
    NARROW_COLOUR,
    PART_NAME,
    area_weighted_document,
    per_face_coloured_document,
    solid_by_solid_document,
)
from .xcaf import BODY_COLOUR, LID_COLOUR, build_document

_EPOCH = "1970-01-01T00:00:00+00:00"


def _round_tripped(document: Any, path: Path) -> StepDocument:
    """``document`` written to ``path`` and read back as a real STEP file."""
    path.write_bytes(render_step(
        document, title="t", timestamp=_EPOCH, originating_system="t"
    ))
    return read_step(path)


def _matches(got: tuple[float, float, float] | None, wanted: tuple[float, ...]) -> bool:
    """``got`` is a colour and agrees with ``wanted`` to six places."""
    return got is not None and all(round(g - w, 6) == 0 for g, w in zip(got, wanted))


def test_an_assembly_components_colour_is_resolved_through_its_placement(
    tmp_path: Path,
) -> None:
    """The reader hands back a component's *located* shape while the colour
    sits on the product label, so a lookup on that shape alone finds nothing.

    Every named, coloured leaf of a real assembly is affected, which is why
    both are asserted rather than one: a rule reaching only the first solid
    would pass on a single-leaf file.
    """
    reread = _round_tripped(build_document(), tmp_path / "assembly.stp")
    by_name = {solid.name: solid for solid in reread.solids}

    assert _matches(solid_colour(reread.document, by_name["body"]), BODY_COLOUR)
    assert _matches(solid_colour(reread.document, by_name["lid"]), LID_COLOUR)


def test_an_assembly_component_nobody_coloured_still_reads_as_none(
    tmp_path: Path,
) -> None:
    """The control on the test above: a leaf carrying no colour anywhere must
    stay ``None``, so resolving through the placement cannot answer by
    borrowing a sibling's colour or inventing one."""
    reread = _round_tripped(build_document(), tmp_path / "assembly.stp")
    by_name = {solid.name: solid for solid in reread.solids}

    assert solid_colour(reread.document, by_name["bracket"]) is None


def test_a_solid_coloured_only_face_by_face_reads_as_its_broadest_colour(
    tmp_path: Path,
) -> None:
    """A component modelled face by face records no whole-solid colour, so a
    lookup on the solid alone finds nothing though the file is full of them.

    The answer is the colour covering the most surface. Asserting it is not
    ``NARROW_COLOUR`` is the load-bearing half: that colour is on four of
    the six faces and would win a rule that counted faces instead.
    """
    reread = _round_tripped(area_weighted_document(), tmp_path / "faces.stp")
    (solid,) = reread.solids

    got = solid_colour(reread.document, solid)
    assert not _matches(got, NARROW_COLOUR)
    assert _matches(got, BROAD_COLOUR)


def test_a_part_coloured_on_its_solids_resolves_below_the_shape_it_hands_back(
    tmp_path: Path,
) -> None:
    """A part built from solids may be coloured a level below the shape the
    reader hands back and a level above its faces, which is where a board
    substrate's colour lives.

    Neither the compound nor any face carries one here, so both earlier
    routes answer nothing. The bigger solid decides: asserting it is not
    ``NARROW_COLOUR`` is what makes the weighing load-bearing rather than
    the arrival order of two equally eligible colours.
    """
    reread = _round_tripped(solid_by_solid_document(), tmp_path / "solids.stp")
    (solid,) = reread.solids
    assert solid.name == PART_NAME

    got = solid_colour(reread.document, solid)
    assert not _matches(got, NARROW_COLOUR)
    assert _matches(got, BROAD_COLOUR)


def test_a_face_by_face_colour_is_one_of_the_colours_the_file_records(
    tmp_path: Path,
) -> None:
    """Six faces, six colours, none of them a majority: the answer is still
    one the document actually holds, never a blend of them."""
    reread = _round_tripped(per_face_coloured_document(), tmp_path / "six.stp")
    (solid,) = reread.solids

    got = solid_colour(reread.document, solid)
    assert got is not None
    shades = {round((index + 1) / 8.0, 6) for index in range(6)}
    assert round(got[0], 6) in shades
    assert round(got[1], 6) == round(1.0 - got[0], 6)
    assert round(got[2], 6) == 0.5
