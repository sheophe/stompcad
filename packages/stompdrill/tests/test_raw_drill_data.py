"""Tests for the unquantised container a source hands the quantiser."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from stompdrill.formatting import format_mm
from stompdrill.quantise import RawDrillData
from stompmodel.diagnostics import Diagnostic
from stompmodel.model import RawHole, RawOutline, SourceInfo
from stompmodel.units import Millimetre, mm_from_nm, nm_from_mm

#: A whole number of nanometres, which is exactly the value that reaches a
#: millimetre field by never having been converted at all.
_A_NANOMETRE_INT = 7_000_000


def raw_panel(**overrides: Any) -> RawDrillData:
    """Return a measured panel whose holes are distinguishable by position."""
    fields: dict[str, Any] = dict(
        source=SourceInfo(path="tar.ai"),
        reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        centre=(Millimetre(297.6), Millimetre(421.0)),
        holes=(
            RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(7.0)),
            RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(7.0)),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(12.7)),
        ),
    )
    fields.update(overrides)
    return RawDrillData(**fields)


def test_the_raw_field_order_is_source_reference_centre_holes() -> None:
    """Positional construction orders source, reference, centre and holes."""
    positional = RawDrillData(
        SourceInfo(path="tar.ai"),
        RawOutline(Millimetre(113.0), Millimetre(60.0)),
        (Millimetre(297.6), Millimetre(421.0)),
        (RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(7.0)),),
    )
    assert positional.source == SourceInfo(path="tar.ai")
    assert positional.reference == RawOutline(Millimetre(113.0), Millimetre(60.0))
    assert positional.centre == (297.6, 421.0)
    assert positional.holes == (RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(7.0)),)


def test_a_raw_document_keeps_its_holes_in_the_order_it_was_given() -> None:
    """Traversal order is the source's answer."""
    assert [hole.x for hole in raw_panel().holes] == [-40.0, 0.0, 20.0]


def test_a_raw_document_reports_no_findings_unless_it_was_given_some() -> None:
    """The default is an empty tuple, not ``None``: every reader of this field
    iterates it, and a ``None`` would make each of them decide separately what
    an absent list of findings means."""
    assert raw_panel().diagnostics == ()


def test_a_raw_document_carries_the_findings_the_source_made() -> None:
    finding = Diagnostic.warning("no-reference-layer", "no outline found")
    assert raw_panel(diagnostics=(finding,)).diagnostics == (finding,)


def test_a_raw_document_may_have_no_reference_outline_at_all() -> None:
    """``None`` is a real answer here, unlike on ``ReferenceOutline.raw``."""
    unreferenced = raw_panel(reference=None, centre=(0.0, 0.0))
    assert unreferenced.reference is None
    assert unreferenced.centre == (0.0, 0.0)
    assert [hole.x for hole in unreferenced.holes] == [-40.0, 0.0, 20.0]


#: The centre's two coordinates, one builder each. Listed separately for the
#: reason every other guard in this file is: they are two keyword arguments to
#: one strict helper, and a call that names only ``centre_x`` leaves the Y axis
#: exactly as unchecked as it was.
_GUARDED_CENTRE = [
    pytest.param(lambda v: raw_panel(centre=(v, 421.0)), id="centre_x"),
    pytest.param(lambda v: raw_panel(centre=(297.6, v)), id="centre_y"),
]


def test_a_nanometre_centre_would_displace_the_whole_panel_not_one_field() -> None:
    """Why ``centre`` is guarded, stated as the frame it keeps."""
    centre_x_nm = nm_from_mm(297.6)
    assert format_mm(centre_x_nm) == "297600000.000"
    assert format_mm(mm_from_nm(centre_x_nm)) == "297.600"

    with pytest.raises(TypeError, match="millimetres"):
        raw_panel(centre=(centre_x_nm, 421.0))


@pytest.mark.parametrize(
    "value",
    [_A_NANOMETRE_INT, True, float("nan"), float("inf")],
    ids=["int", "bool", "nan", "inf"],
)
@pytest.mark.parametrize("build", _GUARDED_CENTRE)
def test_a_centre_coordinate_that_is_not_a_measurement_is_refused(build, value) -> None:
    """A centre coordinate that is not a measurement is refused."""
    with pytest.raises(TypeError, match="millimetres"):
        build(value)


def test_raw_drill_data_is_frozen_and_slotted() -> None:
    panel = raw_panel()
    with pytest.raises(dataclasses.FrozenInstanceError):
        panel.reference = None  # type: ignore[misc]
    assert not hasattr(panel, "__dict__")


def test_raw_documents_differing_only_in_where_the_outline_sat_are_not_equal() -> None:
    """``centre`` is data, not decoration: it is where on the page the outline
    was found, and two panels drawn at different places on one artboard are two
    different reads."""
    assert raw_panel() != raw_panel(centre=(300.0, 421.0))
    assert raw_panel() == raw_panel()


def test_the_guard_names_the_container_that_holds_the_frame() -> None:
    """The centre guard is ``RawDrillData``'s own, and says so.

    It is the one guard that did not travel with the values into
    ``stompmodel``, because the container did not: only the source and the
    quantiser ever hold one.
    """
    with pytest.raises(TypeError, match="RawDrillData"):
        RawDrillData(
            source=SourceInfo(path="panel.ai", drill_layer="Drill"),
            reference=None,
            centre=(Millimetre(float("inf")), Millimetre(0.0)),
            holes=(),
        )
