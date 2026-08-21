"""Layer 2: what each emitter owns, against the model it was given.

Python values, so comparison needs no parser -- and cross-artefact agreement
(T4) is established here, between representations this project wrote, not by
parsing two artefacts back and trusting both readers at once.
"""

from __future__ import annotations

from typing import Any

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing.scene import Circle, Group, Scene
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter
from stompdrill.emitters.drawing_svg import DrawingSvgEmitter
from stompmodel.codec import to_document
from stompmodel.model import DrillData, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data

__all__: list[str] = []

#: A hundredth of a sheet millimetre. Far finer than any plotter resolves and
#: far coarser than the layout's own float noise, which is ~1e-12.
SHEET_TOLERANCE_MM = 1e-5


def panel() -> DrillData:
    """The same four holes every layer checks, numbered out of tuple order."""
    return make_data(
        at(-20_000_000, 18_000_000, 7_000_000, index=3),
        at(20_000_000, 18_000_000, 7_000_000, index=4),
        at(-19_000_000, -18_750_000, 5_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    )


def circles(scene: Scene, token: str) -> list[Circle]:
    """Every circle carrying ``token`` in its class, wherever a group nests it."""
    found: list[Circle] = []

    def walk(item) -> None:
        if isinstance(item, Group):
            for child in item.items:
                walk(child)
        elif isinstance(item, Circle) and token in item.cls.split():
            found.append(item)

    for item in scene.items:
        walk(item)
    return found


def datum(scene: Scene) -> tuple[float, float]:
    """The sheet point the canonical origin sits at.

    ``build`` draws exactly one ``origin``-class circle and draws it there,
    so the scene states its own datum and the comparison need not assume a
    placement.
    """
    marks = circles(scene, "origin")
    assert len(marks) == 1, f"expected one origin mark, found {len(marks)}"
    return marks[0].cx, marks[0].cy


def scenes(data: DrillData) -> dict[str, tuple[Scene, float]]:
    """Each drawing backend's owned representation, with its own scale.

    The two solve for different unknowns -- SVG fixes the sheet and fits the
    scale, PDF fixes the scale at 1:1 and walks the ISO 5457 candidates -- so
    they own two scenes, not one, and T4 has something to say.
    """
    built = {}
    for name, emitter in (("svg", DrawingSvgEmitter()), ("pdf", DrawingPdfEmitter())):
        layout = emitter.layout(data)
        built[name] = (build_scene(layout, data, SheetText(title="LAYER 2")), layout.scale)
    return built


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_draws_one_hole_mark_for_every_hole_in_the_model(backend):
    data = panel()

    scene, _ = scenes(data)[backend]

    assert len(circles(scene, "hole")) == len(data.holes)


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_places_every_hole_where_the_model_puts_it(backend):
    """One affine map, shared by every hole: the canonical Y-up frame scaled
    and flipped onto the sheet's Y-down one. A per-hole error, a transposed
    axis or a one-sided scale all break this; a uniform offset does not, and
    is a placement decision the datum absorbs."""
    data = panel()
    scene, scale = scenes(data)[backend]
    ox, oy = datum(scene)

    placed = sorted((c.cx, c.cy) for c in circles(scene, "hole"))
    expected = sorted(
        (ox + hole.x_nm / 1_000_000 * scale, oy - hole.y_nm / 1_000_000 * scale)
        for hole in data.holes
    )

    assert placed == pytest.approx(expected, abs=SHEET_TOLERANCE_MM)


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_draws_every_hole_at_the_models_diameter(backend):
    """Separate from position: a radius scaled by the wrong factor lands every
    mark correctly and still drills the wrong bit."""
    data = panel()
    scene, scale = scenes(data)[backend]

    drawn = sorted(2 * c.r for c in circles(scene, "hole"))
    expected = sorted(hole.diameter_nm / 1_000_000 * scale for hole in data.holes)

    assert drawn == pytest.approx(expected, abs=SHEET_TOLERANCE_MM)


def test_the_pdf_scene_is_drawn_at_one_to_one():
    """The PDF solves for the sheet, so its scale is fixed. If this ever fails
    the two backends have stopped differing in the way the design says."""
    assert scenes(panel())["pdf"][1] == 1.0


def test_the_document_states_every_hole_the_model_holds_in_canonical_units():
    """The JSON emitter's owned representation is this mapping; ``json.dumps``
    below it is stdlib and trusted."""
    data = panel()

    document = to_document(data)

    assert [(h["x_nm"], h["y_nm"], h["diameter_nm"]) for h in document["holes"]] == [
        (hole.x_nm, hole.y_nm, hole.diameter_nm) for hole in data.holes
    ]


def test_the_document_states_the_tool_the_model_assigned_each_diameter():
    data = panel()

    document = to_document(data)

    assert {t["diameter_nm"]: t["number"] for t in document["tools"]} == dict(data.tools())


def projected(scene: Scene, scale: float) -> list[tuple[int, int, int]]:
    """A scene's holes in canonical nanometres, through its own frame alone."""
    ox, oy = datum(scene)
    return sorted(
        (
            round((c.cx - ox) / scale * 1_000_000),
            round(-(c.cy - oy) / scale * 1_000_000),
            round(2 * c.r / scale * 1_000_000),
        )
        for c in circles(scene, "hole")
    )


def test_every_owned_representation_agrees_about_the_same_holes():
    """T4. Three representations, three different frames, one geometry.

    Established between values this project owns rather than by parsing two
    artefacts back: a comparison of two parsers' output is only as good as
    the weaker parser, and this one has no parser in it at all.
    """
    data = panel()
    built = scenes(data)

    from_model = sorted((h.x_nm, h.y_nm, h.diameter_nm) for h in data.holes)
    from_document = sorted(
        (h["x_nm"], h["y_nm"], h["diameter_nm"]) for h in to_document(data)["holes"]
    )

    assert from_document == from_model
    assert projected(*built["svg"]) == from_model
    assert projected(*built["pdf"]) == from_model


def _cut_component_shape(document: Any, keyword: str) -> Any:
    """The placed shape ``cut_shape`` wrote back, found by the walk it uses.

    No public accessor hands back the drilled solid alone: ``cut_shape``
    only returns the whole document, an ``undo`` and the touched entries.
    This retraces ``step_module._cut_component``'s own recursion to read the
    shape rather than mutate it -- the private helper it reuses is the name
    lookup only, matched to the emitter's own ``keyword`` rule.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    from stompdrill.emitters import step as step_module

    def walk(label: Any) -> Any | None:
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            children = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, children)
            for index in range(1, children.Length() + 1):
                found = walk(children.Value(index))
                if found is not None:
                    return found
            return None
        if keyword not in step_module._label_name(label).upper():
            return None
        return XCAFDoc_ShapeTool.GetShape_s(label)

    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    for index in range(1, free.Length() + 1):
        found = walk(free.Value(index))
        if found is not None:
            return found
    raise AssertionError(f"no component named {keyword!r} was found")


@pytest.mark.hammond
def test_the_cut_shapes_new_cylinders_sit_at_the_models_hole_positions():
    """STEP's owned representation is ``cut_shape``'s own result, not a
    written-and-reread solid: this checks the cylinder axes it left behind,
    projected through the model's own frame, against the holes it was given.
    """
    pytest.importorskip("OCP", reason="needs stompdrill[step]")

    from OCP.Precision import Precision

    from stompdrill.cad import load_case_model
    from stompdrill.emitters.step import cut_shape
    from stompmodel.units import mm_from_nm, nm_from_mm
    from tests.hammond import cylinders, require_model

    model_path = require_model("1590BB")
    model = load_case_model(model_path, face="box", margin_nm=Nanometre(1_000_000))
    data = make_data(
        at(0, 0, 6_000_000, index=1),
        at(20_000_000, -15_000_000, 8_000_000, index=2),
    )

    before = cylinders(model.target_shape)
    document, undo, _touched = cut_shape(model, data)
    try:
        shape = _cut_component_shape(document, "BOX")
        added = cylinders(shape) - before
    finally:
        undo()

    tolerance_mm = Precision.Confusion_s()
    frame = model.frame
    origin_mm = tuple(float(mm_from_nm(value)) for value in frame.origin_nm)

    def canonical_xy(ax: int, ay: int, az: int) -> tuple[Nanometre, Nanometre]:
        point_mm = (ax * tolerance_mm, ay * tolerance_mm, az * tolerance_mm)
        relative = tuple(p - o for p, o in zip(point_mm, origin_mm))
        x_mm = sum(r * c for r, c in zip(relative, frame.u))
        y_mm = sum(r * c for r, c in zip(relative, frame.v))
        return nm_from_mm(x_mm), nm_from_mm(y_mm)

    found = {canonical_xy(ax, ay, az) for ax, ay, az, _radius in added}
    expected = {(hole.x_nm, hole.y_nm) for hole in data.holes}

    assert len(added) == len(data.holes)
    assert found == expected
