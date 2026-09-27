"""Which files an emitter owes for a document, and what they are called.

The naming lives in one module because both command lines write these, and
``stompcad``'s artefacts must match ``stompdrill``'s byte for byte.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
from stompdrill.emitters.excellon import ExcellonEmitter, ExcellonOptions
from stompdrill.emitters.json_out import JsonEmitter
from stompdrill.emitters.surfaces import artefacts, sibling
from stompmodel.errors import EmitterError
from stompmodel.model import Origin, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data, wall_surface

__all__: list[str] = []


def test_a_sibling_carries_the_surface_key_before_the_extension():
    assert sibling(Path("out/tar-case.drl"), "left") == Path("out/tar-case-left.drl")
    assert sibling(Path("tar-case.svg"), "top") == Path("tar-case-top.svg")


def test_the_drilled_plate_keeps_the_path_it_was_given():
    data = make_data(at(0, 0, 7_000_000, index=1))

    (written,) = artefacts(
        ExcellonEmitter(ExcellonOptions(origin=Origin.CENTRE)),
        Path("out/tar-case.drl"),
        data,
    )

    assert written[0] == Path("out/tar-case.drl")


def test_a_per_setup_format_writes_one_file_for_every_surface_with_a_hole():
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 5_000_000, index=2, surface="left"),
        at(1_000_000, 0, 5_000_000, index=3, surface="top"),
    ).with_surfaces([wall_surface("left"), wall_surface("top")])

    written = artefacts(
        ExcellonEmitter(ExcellonOptions(origin=Origin.CENTRE)),
        Path("out/tar-case.drl"),
        data,
    )

    assert [path for path, _payload in written] == [
        Path("out/tar-case.drl"),
        Path("out/tar-case-left.drl"),
        Path("out/tar-case-top.drl"),
    ]


def test_each_per_setup_file_holds_only_its_own_surface_s_holes():
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 5_000_000, index=2, surface="left"),
    ).with_surfaces([wall_surface("left")])

    written = dict(
        artefacts(
            ExcellonEmitter(ExcellonOptions(origin=Origin.CENTRE)),
            Path("out/tar-case.drl"),
            data,
        )
    )

    assert written[Path("out/tar-case.drl")].count("X") == 1
    assert written[Path("out/tar-case-left.drl")].count("X") == 1
    assert "C5" in written[Path("out/tar-case-left.drl")]
    assert "C5" not in written[Path("out/tar-case.drl")]


def test_a_whole_job_format_writes_the_one_file_it_was_given():
    """The document and the model describe the whole job, not one setup: one
    object drilled in two passes is still one object."""
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 5_000_000, index=2, surface="left"),
    ).with_surfaces([wall_surface("left")])

    written = artefacts(JsonEmitter(), Path("out/tar-case.json"), data)

    assert [path for path, _payload in written] == [Path("out/tar-case.json")]


def test_a_plate_with_no_holes_still_gets_its_file():
    data = make_data(
        at(0, 0, 5_000_000, index=1, surface="left")
    ).with_surfaces([wall_surface("left")])

    written = artefacts(
        ExcellonEmitter(ExcellonOptions(origin=Origin.CENTRE)),
        Path("out/tar-case.drl"),
        data,
    )

    assert [path for path, _payload in written] == [
        Path("out/tar-case.drl"),
        Path("out/tar-case-left.drl"),
    ]


def test_a_drill_file_over_two_surfaces_at_once_is_refused():
    """Two frames in one file would put a wall hole at a panel coordinate;
    the projection is not optional, so the emitter refuses to be bypassed."""
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 5_000_000, index=2, surface="left"),
    ).with_surfaces([wall_surface("left")])

    with pytest.raises(EmitterError, match="one surface"):
        ExcellonEmitter(ExcellonOptions(origin=Origin.CENTRE)).emit(data)


def test_a_sheet_over_two_surfaces_at_once_is_refused():
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 5_000_000, index=2, surface="left"),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    ).with_surfaces([wall_surface("left")])
    emitter = DrawingSvgEmitter(DrawingOptions())

    with pytest.raises(EmitterError, match="one surface"):
        build_scene(emitter.layout(data), data, SheetText())


def test_a_wall_s_drill_file_counts_from_that_wall_s_own_lower_left():
    """The CLI's own default origin, on a wall, not the centre these tests
    otherwise pass.

    ``ExcellonOptions()`` is ``LOWER_LEFT``, so the wall's file counts from
    the corner of the wall's own region: a hole 1 mm inside the low edge of a
    30 by 20 mm wall is at X1.000, whatever the panel's outline measures.
    """
    data = make_data(
        at(-14_000_000, 9_000_000, 5_000_000, index=1, surface="left"),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    ).with_surfaces([wall_surface("left", 30_000_000, 20_000_000)])

    written = dict(artefacts(ExcellonEmitter(), Path("out/tar-case.drl"), data))

    wall = written[Path("out/tar-case-left.drl")]
    assert "X1.000Y19.000" in wall
