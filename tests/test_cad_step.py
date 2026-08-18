"""Reading a STEP assembly: names, placement and per-representation units."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("OCP", reason="needs aidrill[step]")

from aidrill.cad.step import read_step  # noqa: E402

pytestmark = pytest.mark.hammond


@pytest.fixture(scope="module")
def document(hammond_bb):
    return read_step(hammond_bb)


def test_every_product_in_the_assembly_is_read(document):
    """1590BB is a box, a lid and four screw instances."""
    assert len(document.solids) >= 6
    assert len(document.named("box")) == 1
    assert len(document.named("lid")) == 1


def test_a_repeated_component_is_expanded_once_per_instance(document):
    """The screw is one product occurring four times; all four must appear."""
    assert len(document.named("screw")) == 4


def test_solids_carry_their_product_names(document):
    names = {solid.name.upper() for solid in document.solids}

    assert any("BOX" in name for name in names)
    assert any("LID" in name for name in names)


def test_named_selects_by_keyword_case_insensitively(document):
    assert len(document.named("box")) == 1
    assert len(document.named("BOX")) == 1


def test_named_returns_empty_rather_than_raising_for_an_absent_keyword(document):
    assert document.named("flange") == ()


def test_solids_are_returned_in_a_stable_order(document, hammond_bb):
    again = read_step(hammond_bb)

    assert [s.name for s in document.solids] == [s.name for s in again.solids]


def test_the_inch_sub_part_is_reported_in_millimetres(document):
    """The screw is modelled in inches; its shape must arrive scaled."""
    from aidrill.cad.step import bounding_box_mm

    screw = document.named("screw")[0]
    x0, y0, z0, x1, y1, z1 = bounding_box_mm(screw.shape)
    widest = max(x1 - x0, y1 - y0, z1 - z0)

    # A #6-32 x 1/2" screw is 12.7 mm long and 3.5 mm across. Left in inches it
    # would span about 0.5 -- so the span, not the position, is what tells us.
    assert 8.0 < widest < 20.0, "an unscaled inch screw would span about 0.5"


def test_the_box_is_placed_in_assembly_coordinates_not_local_ones(document):
    """The fixture rotates local Z onto assembly Y; the read must reflect it."""
    from aidrill.cad.step import bounding_box_mm

    (box,) = document.named("box")
    x0, y0, z0, x1, y1, z1 = bounding_box_mm(box.shape)
    spans = (x1 - x0, y1 - y0, z1 - z0)

    assert sorted(round(s, 1) for s in spans) == [30.0, 94.0, 119.5]
    # The parts are modelled Z-up and the assembly places them Y-up, so reading
    # local coordinates would put the 30 mm depth on Z instead.
    assert round(spans[1], 1) == 30.0, "depth should lie along assembly Y"


def test_a_missing_file_raises_an_aidrill_error(tmp_path: Path):
    from aidrill.errors import AidrillError

    with pytest.raises(AidrillError):
        read_step(tmp_path / "absent.stp")


def test_a_file_that_is_not_step_raises_an_aidrill_error(tmp_path: Path):
    from aidrill.errors import AidrillError

    rubbish = tmp_path / "rubbish.stp"
    rubbish.write_text("not a step file", encoding="utf-8")

    with pytest.raises(AidrillError):
        read_step(rubbish)
