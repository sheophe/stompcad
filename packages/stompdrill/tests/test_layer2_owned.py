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
from stompmodel.model import CaseFace, DrillData, ReferenceOutline
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
    # Assumes no hole here is clamped by build.py's HOLE_MIN_RADIUS (0.4 mm)
    # floor; the fixture's scale is 1.0 so nothing is clamped today.
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
    """The cut leaf's shape, found with ``stompgeom.step``'s own published walk.

    ``cut_shape`` hands back the XCAF document rather than the shape it
    touched, so the leaf has to be found again. ``leaf_labels`` is the one
    walk this workspace performs and ``named`` the keyword rule, so neither
    is re-typed here -- a second copy of the recursion would keep working
    while diverging from the one the emitter actually uses.
    """
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    from stompgeom.step import StepDocument, StepSolid, leaf_labels

    solids: list[StepSolid] = []
    for entry in leaf_labels(document):
        shape = XCAFDoc_ShapeTool.GetShape_s(entry.label)
        if shape.IsNull():
            continue
        solids.append(StepSolid(name=entry.name, shape=shape))

    found = StepDocument(tuple(solids), document).named(keyword)
    assert found, f"the cut document holds no solid named like {keyword!r}"
    return found[0].shape


@pytest.mark.hammond
def test_the_cut_shapes_new_cylinders_sit_at_the_models_hole_positions():
    """STEP's owned representation is ``cut_shape``'s own result, not a
    written-and-reread solid: this checks the cylinder axes it left behind,
    projected through the model's own frame, against the holes it was given.
    """
    from OCP.Precision import Precision

    from stompdrill.cad import load_case_model
    from stompdrill.emitters.step import cut_shape
    from stompmodel.units import nm_from_mm
    from tests.conftest import registration_for
    from tests.hammond import cylinders, require_model

    model_path = require_model("1590BB")
    model = load_case_model(model_path, face=CaseFace.BOX, margin_nm=Nanometre(1_000_000))
    data = make_data(
        at(0, 0, 6_000_000, index=1),
        at(20_000_000, -15_000_000, 8_000_000, index=2),
    ).with_case(registration_for(model))

    before = cylinders(model.target_shape)
    document, undo, _touched = cut_shape(model, data)
    try:
        shape = _cut_component_shape(document, "BOX")
        added = cylinders(shape) - before
    finally:
        undo()

    tolerance_mm = Precision.Confusion_s()
    frame = model.frame

    def canonical_hole(ax: int, ay: int, az: int, radius: int) -> tuple[Nanometre, Nanometre, int]:
        point_mm = (ax * tolerance_mm, ay * tolerance_mm, az * tolerance_mm)
        # The depth is dropped on purpose: this checks where each
        # cylinder sits on the face, not how far along its own axis the
        # sampled point lies.
        x_mm, y_mm, _depth_mm = frame.basis.to_canonical(point_mm)
        return nm_from_mm(x_mm), nm_from_mm(y_mm), radius

    # Joining position and radius in one tuple, rather than checking the
    # position set and the radius set separately, is what catches two holes
    # with swapped diameters: each would pass a position-only and a
    # radius-only check alike.
    found = {canonical_hole(ax, ay, az, radius) for ax, ay, az, radius in added}
    expected = {
        (hole.x_nm, hole.y_nm, round((hole.diameter_nm / 2) / 1_000_000 / tolerance_mm))
        for hole in data.holes
    }

    assert len(added) == len(data.holes)
    assert found == expected
