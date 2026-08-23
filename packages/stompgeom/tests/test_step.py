"""The reader's own contract, apart from any enclosure that uses it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stompgeom.step import (
    _EPOCH,
    bounding_box_mm,
    label_name,
    read_step,
    source_timestamp,
)
from stompmodel.errors import DocumentError

from .xcaf import BODY_SIZE_MM, build_document


def test_source_timestamp_reads_the_comment_marker(tmp_path: Path) -> None:
    """ST-Developer's comment above FILE_NAME, not the FILE_NAME field."""
    target = tmp_path / "stamped.stp"
    target.write_bytes(b"ISO-10303-21;\n/* time_stamp */ '2020-01-02T03:04:05'\n")

    assert source_timestamp(target) == "2020-01-02T03:04:05"


def test_source_timestamp_falls_back_to_the_epoch(tmp_path: Path) -> None:
    """Never a clock reading: determinism does not depend on the file
    carrying a stamp, only on every write copying the same value."""
    target = tmp_path / "bare.stp"
    target.write_bytes(b"ISO-10303-21;\n")

    assert source_timestamp(target) == _EPOCH


def test_reading_a_missing_file_is_a_document_error(tmp_path: Path) -> None:
    """A stompgeom reader cannot raise a stompdrill error; refusing a foreign
    document is a failure any member can have, so the base is shared.

    The message says "model", not "case model": an enclosure is one thing a
    caller might have been reading, and this layer knows about none of them.
    """
    with pytest.raises(DocumentError, match="no model at"):
        read_step(tmp_path / "absent.stp")


def test_reading_a_non_step_file_is_a_document_error(tmp_path: Path) -> None:
    """Not readable is distinct from not present, and both are the file's
    fault rather than the data's."""
    target = tmp_path / "rubbish.stp"
    target.write_bytes(b"this is not a STEP file at all\n")

    with pytest.raises(DocumentError, match="is not a readable STEP file"):
        read_step(target)


# ---------------------------------------------------------------------------
# The reader driven against a file this package wrote, needing no download
# ---------------------------------------------------------------------------


def _written(tmp_path: Path) -> Path:
    """A real STEP assembly, built in memory and written by this package."""
    from stompgeom.writer import render_step

    target = tmp_path / "round-trip.stp"
    payload = render_step(
        build_document(),
        title="a round trip",
        timestamp="2020-01-02T03:04:05",
        originating_system="a supplied originating system 9.9",
    )
    target.write_bytes(payload)
    return target


def test_read_step_returns_every_leaf_solid_and_no_assembly(tmp_path: Path) -> None:
    """``_collect`` recurses past an assembly label rather than recording it,
    so three components come back as three solids under their own names."""
    document = read_step(_written(tmp_path))

    assert len(document.solids) == 3
    assert {"body", "lid"} <= {solid.name for solid in document.solids}


def test_read_step_places_each_solid_in_assembly_coordinates(tmp_path: Path) -> None:
    """``_collect``'s central claim: reading the *component* label applies the
    placement its parent gave it. The lid is modelled at the origin like the
    body and lifted 5 mm by the assembly, so a reader taking the referred
    product label instead would hand it back sitting at zero."""
    document = read_step(_written(tmp_path))
    (body,) = document.named("body")
    (lid,) = document.named("lid")

    assert bounding_box_mm(body.shape)[2] == pytest.approx(0.0, abs=1e-6)
    assert bounding_box_mm(lid.shape)[2] == pytest.approx(5.0, abs=1e-6)


def test_bounding_box_mm_measures_a_solid_in_millimetres(tmp_path: Path) -> None:
    """The extent the document was built with, which is also what proves the
    reader's unit normalisation left a millimetre model alone."""
    (body,) = read_step(_written(tmp_path)).named("body")
    x0, y0, z0, x1, y1, z1 = bounding_box_mm(body.shape)

    assert (x1 - x0, y1 - y0, z1 - z0) == pytest.approx(BODY_SIZE_MM, abs=1e-6)


def test_a_file_this_package_wrote_reads_back_with_no_provenance(
    tmp_path: Path,
) -> None:
    """``source_timestamp``'s documented consequence, asserted rather than
    described: this writer emits no ``/* time_stamp */`` comment, so a file it
    produced carries a real header stamp the reader deliberately ignores."""
    target = _written(tmp_path)

    assert b"'2020-01-02T03:04:05'" in target.read_bytes()
    assert read_step(target).timestamp == _EPOCH


# ---------------------------------------------------------------------------
# label_name -- the one rule for what XCAF recorded as a label's name
# ---------------------------------------------------------------------------


def _new_shape_tool() -> tuple[object, Any]:
    """A fresh, empty XCAF document and its shape tool.

    Returns the document alongside the tool; the caller must keep the
    document referenced for as long as it uses any label drawn from it --
    the document owns the label's underlying data.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)
    return document, XCAFDoc_DocumentTool.ShapeTool_s(document.Main())


def _a_box() -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape()


def _unnamed_occurrence_document() -> tuple[object, object]:
    """One component whose *occurrence* label carries no name of its own
    while its *referred product* label does -- exactly what a raw board body
    copied into an assembly looks like. ``AddComponent`` always synthesises
    *some* name attribute, here its own indirection placeholder.

    Returns ``(document, component)``; the caller must keep both alive.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location

    document, shapes = _new_shape_tool()

    product = shapes.AddShape(_a_box(), False)
    TDataStd_Name.Set_s(product, TCollection_ExtendedString("Sluch_PCB_1"))

    assembly = shapes.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("enclosure"))
    component = shapes.AddComponent(assembly, product, TopLoc_Location())
    # Deliberately no TDataStd_Name.Set_s(component, ...): this is the
    # occurrence a real KiCad export leaves unnamed for a raw board body.
    shapes.UpdateAssemblies()
    return document, component


def _named_occurrence_document(name: str) -> tuple[object, object]:
    """A component whose *occurrence* label carries a genuine name, distinct
    from its referred product's own name.

    Returns ``(document, component)``; the caller must keep both alive.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location

    document, shapes = _new_shape_tool()

    product = shapes.AddShape(_a_box(), False)
    TDataStd_Name.Set_s(product, TCollection_ExtendedString("Sluch_PCB_1"))

    assembly = shapes.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("enclosure"))
    component = shapes.AddComponent(assembly, product, TopLoc_Location())
    TDataStd_Name.Set_s(component, TCollection_ExtendedString(name))
    shapes.UpdateAssemblies()
    return document, component


def _labelled(name: str) -> tuple[object, object]:
    """A free-standing product label carrying ``name``.

    Returns ``(document, label)``; the caller must keep both alive.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name

    document, shapes = _new_shape_tool()
    label = shapes.AddShape(_a_box(), False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    return document, label


def _unattributed_label() -> tuple[object, object]:
    """A label carrying no ``TDataStd_Name`` attribute at all.

    ``AddShape`` sets one of its own accord ("SOLID"); ``ForgetAttribute``
    removes it, leaving the label exactly as a label that was never named.
    Returns ``(document, label)``; the caller must keep both alive.
    """
    from OCP.TDataStd import TDataStd_Name

    document, shapes = _new_shape_tool()
    label = shapes.AddShape(_a_box(), False)
    label.ForgetAttribute(TDataStd_Name.GetID_s())
    return document, label


def test_label_name_reports_the_occ_indirection_placeholder_as_unnamed() -> None:
    """An occurrence with no name of its own must read as unnamed, not as
    OCC's synthesised ``=>[0:1:1:N]`` indirection string."""
    _document, component = _unnamed_occurrence_document()

    assert label_name(component) == ""


def test_label_name_reports_a_genuine_occurrence_name_exactly() -> None:
    """The other direction of the same rule: a component whose occurrence
    label *was* named reports that name, not the placeholder and not the
    referred product's own name."""
    _document, component = _named_occurrence_document("body")

    assert label_name(component) == "body"


def test_label_name_reports_a_label_with_no_name_attribute_as_unnamed() -> None:
    """A label that was never named at all -- no placeholder, no attribute --
    reads the same as one carrying the synthesised indirection: both are
    "nobody named this", and the caller must not be able to tell them apart."""
    _document, label = _unattributed_label()

    assert label_name(label) == ""


def test_label_name_leaves_a_genuine_bracketed_colonned_name_untouched() -> None:
    """The placeholder pattern is matched with ``fullmatch``, so a genuine
    name that merely contains its punctuation -- embedded, as a prefix, or
    as a suffix -- must survive unchanged in every case."""
    embedded = "weird =>[0:1:1:34] name"
    prefixed = "prefix=>[0:1:1:34]"
    suffixed = "=>[0:1:1:34]suffix"

    for name in (embedded, prefixed, suffixed):
        _document, label = _labelled(name)
        assert label_name(label) == name


def test_the_reader_keeps_no_private_twin_of_the_name_rule() -> None:
    """``label_name`` is the one implementation; a private ``_name_of`` would
    let the reader and the writer disagree about what a name is."""
    import stompgeom.step as step_module

    assert not hasattr(step_module, "_name_of")
