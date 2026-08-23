"""Synthetic ``cut_shape`` tests that need OCP but no downloaded Hammond model.

Unmarked deliberately, like ``tests/test_cad_case_synthetic.py``:
``tests/test_step_cut.py`` carries a module-level ``pytest.mark.hammond``,
but nothing here needs a cached model, so it belongs in the default suite.
"""

from __future__ import annotations

from typing import Any

from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre

#: A 10 mm cube, drilled face up, at the model origin -- shape and position
#: are arbitrary, chosen only so a 4 mm hole at its centre clears every edge.
_SIZE_MM = 10.0


def _leaf(shapes: Any, shape: Any, name: str) -> Any:
    """A free top-level product label named ``name``, holding ``shape``."""
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name

    label = shapes.AddShape(shape, False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    return label


def _two_leaf_document(second_shape: Any) -> Any:
    """Two free, same-named top-level leaves; the first carries no shape.

    Both are bare top-level products, never assembly components: nulling a
    *component's* referred shape and then calling ``UpdateAssemblies`` is a
    confirmed kernel hazard (a process death with no traceback) rather than
    a Python exception, so this fixture does not go anywhere near it. A
    label cannot be added directly with a null shape either -- ``AddShape``
    refuses it -- so a real shape is added first and then erased in place.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopoDS import TopoDS_Shape
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())

    # A throwaway shape distinct from ``second_shape``'s own TShape -- XCAF
    # deduplicates an identical shape onto one label, which would collapse
    # this fixture's two leaves back into one.
    throwaway = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 1.0, 1.0, 1.0).Shape()
    victim = _leaf(shapes, throwaway, "BOX")
    shapes.SetShape(victim, TopoDS_Shape())
    _leaf(shapes, second_shape, "BOX")
    shapes.UpdateAssemblies()
    return document


def _model(document: Any, frame: FaceFrame) -> Any:
    """The minimal ``OcpCaseModel`` ``cut_shape`` needs: a document and a face
    frame. Every field ``cut_shape`` never reads (region, footprint,
    provenance, ...) is a placeholder -- ``classify`` and the loader's own
    verification are not under test here.
    """
    from stompdrill.cad.loader import OcpCaseModel

    zero = Nanometre(0)
    return OcpCaseModel(
        part="test", face=CaseFace.BOX, model_name="synthetic.stp",
        footprint_nm=(Nanometre(int(_SIZE_MM * 1_000_000)),) * 2,
        plate_nm=Nanometre(int(_SIZE_MM * 1_000_000)),
        play_area_nm=(zero, zero, zero, zero),
        frame=frame, margin_nm=zero, axis=2,
        own_region=None, own_frame=frame, box_region=None, box_frame=None,
        drilled_position_mm=_SIZE_MM, inner_position_mm=0.0,
        document=document, target_shape=None,
        document_timestamp="1970-01-01T00:00:00+00:00",
    )


def _drilled_face_frame() -> FaceFrame:
    """A frame whose plane sits atop the cube, normal pointing away from it."""
    return FaceFrame(
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(int(_SIZE_MM * 1_000_000))),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )


def _volume_mm3(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _named_solid_shapes(document: Any, keyword: str) -> list[Any]:
    """Every non-null leaf shape named like ``keyword``, via the published walk."""
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    from stompgeom.step import label_name, leaf_labels

    return [
        shape
        for label in leaf_labels(document)
        if keyword in label_name(label).upper()
        and not (shape := XCAFDoc_ShapeTool.GetShape_s(label)).IsNull()
    ]


def test_cut_shape_steps_over_a_null_shaped_leaf_and_cuts_the_next_match() -> None:
    """Criterion 1: two same-keyword leaves, the first with no shape.

    The failure mode this pins is not a crash but a silently undrilled
    enclosure emitted at the clean exit code: a rewrite that stopped at the
    first *name* match instead of the first *cuttable* one would still pass
    every other test in this suite and still return normally -- just
    leaving the drilled solid untouched. The first-match rule survives only
    if this keeps passing.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    from stompdrill.emitters.step import cut_shape
    from tests.conftest import at, make_data, registration_for

    real_box = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), _SIZE_MM, _SIZE_MM, _SIZE_MM).Shape()
    document = _two_leaf_document(real_box)
    model = _model(document, _drilled_face_frame())
    data = make_data(at(5_000_000, 5_000_000, 4_000_000, index=1)).with_case(
        registration_for(model)
    )

    cut_document, undo, touched = cut_shape(model, data)
    try:
        # Exactly one label changed, and it is not the null-shaped leaf --
        # that one is never a candidate for SetShape, since _cut_leaf steps
        # over it before ever reaching a write.
        assert len(touched) == 1
        (cut_shape_result,) = _named_solid_shapes(cut_document, "BOX")
        assert _volume_mm3(cut_shape_result) < _volume_mm3(real_box)
    finally:
        undo()

    # Undo restores the pristine volume; the null leaf was never at risk.
    (restored,) = _named_solid_shapes(cut_document, "BOX")
    assert _volume_mm3(restored) == _volume_mm3(real_box)


def test_cut_shape_refuses_when_no_leaf_matches() -> None:
    """Criterion 2: refusal is unchanged when no name-matching leaf is cut."""
    import pytest
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    from stompdrill.emitters.step import cut_shape
    from stompmodel.errors import EmitterError
    from tests.conftest import at, make_data, registration_for

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    shape = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), _SIZE_MM, _SIZE_MM, _SIZE_MM).Shape()
    label = shapes.AddShape(shape, False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString("LID"))
    shapes.UpdateAssemblies()

    model = _model(document, _drilled_face_frame())
    data = make_data(at(5_000_000, 5_000_000, 4_000_000, index=1)).with_case(
        registration_for(model)
    )

    with pytest.raises(EmitterError, match="no component named 'BOX' was found to cut"):
        cut_shape(model, data)
