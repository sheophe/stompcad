"""Layer 3: what each codec wrote, against what it was handed.

Excellon has no owned intermediate -- the emitter is the codec -- so its
check runs to the model and carries full weight. The rest check a codec
alone, because layer 2 has already checked the representation it was given.
"""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import groupby

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing.scene import Circle, Group, Item, Scene
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
from stompdrill.emitters.excellon import ExcellonEmitter, ExcellonOptions
from stompdrill.emitters.json_out import JsonEmitter
from stompmodel.codec import from_document
from stompmodel.model import DrillData, Origin, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data
from tests.recovery.excellon import read_excellon
from tests.recovery.pdf import read_pdf
from tests.recovery.svg import read_svg

__all__: list[str] = []

#: Excellon states three decimals of a millimetre by default.
EXCELLON_QUANTUM_NM = 1_000

#: ``drawing_pdf._num`` states four.
PDF_QUANTUM_NM = 100


def quantised(value: int, quantum: int) -> int:
    """Round a canonical nanometre the way one format rounds it.

    Comparison is then exact. No epsilon: an epsilon would let a real
    off-by-one hide inside a tolerance nobody chose on purpose.
    """
    return round(value / quantum) * quantum


def panel() -> DrillData:
    """Two tools, four holes, numbered out of tuple order.

    The scrambled numbering is load-bearing: an emitter that recomputed a
    drill number from a list position would agree with a fixture numbered
    ascending and disagree with this one.
    """
    return make_data(
        at(-20_000_000, 18_000_000, 7_000_000, index=3),
        at(20_000_000, 18_000_000, 7_000_000, index=4),
        at(-19_000_000, -18_750_000, 5_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    )


# ---------------------------------------------------------------------------
# Excellon: straight to the model, because there is nothing in between
# ---------------------------------------------------------------------------


def expected_hits(data: DrillData) -> list[tuple[int, int, int, int]]:
    """``(number, tool, x, y)`` in the lower-left frame, at Excellon's precision.

    ``with_origin`` is a model operation, so this expectation owes nothing to
    the emitter. Nothing here calls ``format_nm``: building the expected
    string with the writer's own formatter would let a wrong formatter cancel
    itself out. Sorted by drill number: that is what "the order the model
    numbered" means, and it is the order tool-block grouping actually
    produces in the file -- ``framed.holes``' own tuple order is deliberately
    scrambled and does not carry it.
    """
    framed = data.with_origin(Origin.LOWER_LEFT)
    tools = framed.tools()
    return [
        (
            index,
            tools[hole.diameter_nm],
            quantised(hole.x_nm, EXCELLON_QUANTUM_NM),
            quantised(hole.y_nm, EXCELLON_QUANTUM_NM),
        )
        for index, hole in sorted(framed.numbered(), key=lambda pair: pair[0])
    ]


def test_the_excellon_file_states_every_hole_the_model_holds():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert len(recovered.circles) == len(data.holes)


def test_the_excellon_file_states_each_hole_at_the_position_the_model_holds():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [(c.x_nm, c.y_nm) for c in recovered.circles] == [
        (x, y) for _, _, x, y in expected_hits(data)
    ]


def test_the_excellon_file_assigns_each_hole_the_tool_the_model_assigned():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [c.tool for c in recovered.circles] == [tool for _, tool, _, _ in expected_hits(data)]


def test_the_excellon_file_drills_in_the_order_the_model_numbered():
    """File position is the format's only statement of sequence, so this is
    where ``RouteHoles``' numbering reaches the machine."""
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [c.number for c in recovered.circles] == [n for n, _, _, _ in expected_hits(data)]


def test_the_excellon_file_states_each_tools_diameter():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert {c.diameter_nm for c in recovered.circles} == {5_000_000, 7_000_000}


def test_each_tool_occupies_one_contiguous_block_in_the_file():
    """CLAUDE.md's invariant, read off the artefact rather than the model.

    ``groupby`` collapses each run of one tool to a single entry, so a tool
    appearing in two separate runs shows up twice and the comparison with the
    sorted distinct set fails.
    """
    data = panel()

    sequence = [c.tool for c in read_excellon(ExcellonEmitter().emit(data)).circles]

    assert [tool for tool, _ in groupby(sequence)] == sorted(set(sequence))


def test_a_finer_precision_reaches_the_file_rather_than_being_rounded_away():
    """The quantum above is Excellon's default, not a property of the format.
    Raising it must change what the file states, or the comparison is testing
    a constant rather than the emitter."""
    data = make_data(
        at(1_234_567, 0, 5_000_000, index=1),
        reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(50_000_000)),
    )

    coarse = read_excellon(ExcellonEmitter(ExcellonOptions(decimals=3)).emit(data))
    fine = read_excellon(ExcellonEmitter(ExcellonOptions(decimals=6)).emit(data))

    assert coarse.circles[0].x_nm != fine.circles[0].x_nm


# ---------------------------------------------------------------------------
# the drawings: one scene, two codecs
# ---------------------------------------------------------------------------


def scene_of(data: DrillData) -> Scene:
    """The scene the SVG backend would build, resolved once and shared."""
    emitter = DrawingSvgEmitter(DrawingOptions(title="LAYER 3"))
    return build_scene(emitter.layout(data), data, SheetText(title="LAYER 3"))


def sheet_nm(value: float, quantum: int) -> int:
    """A scene millimetre as nanometres, at one format's stated precision.

    ``Decimal(repr(x))`` rather than ``x * 1e6``: ``repr`` gives the shortest
    decimal that round-trips to the float, which is the value ``_fmt`` and
    ``_num`` then format. Multiplying the float directly would reintroduce
    exactly the noise ``Decimal`` is here to remove.
    """
    return round(Decimal(repr(value)) * 1_000_000 / quantum) * quantum


def scene_circles(scene: Scene, quantum: int = 1) -> list[tuple[int, int, int]]:
    """Every circle the scene states, in sheet nanometres, sorted."""
    found: list[tuple[int, int, int]] = []

    def walk(item: Item) -> None:
        if isinstance(item, Group):
            for child in item.items:
                walk(child)
        elif isinstance(item, Circle):
            found.append(
                (
                    sheet_nm(item.cx, quantum),
                    sheet_nm(item.cy, quantum),
                    sheet_nm(2 * item.r, quantum),
                )
            )

    for item in scene.items:
        walk(item)
    return sorted(found)


def test_the_svg_states_every_circle_the_scene_holds():
    data = panel()
    scene = scene_of(data)

    recovered = read_svg(DrawingSvgEmitter(DrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert len(recovered.circles) == len(scene_circles(scene))


def test_the_svg_places_each_circle_where_the_scene_put_it():
    """``_render_item`` copies cx, cy and r straight through, so this is a
    check that the copy is faithful rather than that a transform is right."""
    data = panel()
    scene = scene_of(data)

    recovered = read_svg(DrawingSvgEmitter(DrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert sorted((c.x_nm, c.y_nm, c.diameter_nm) for c in recovered.circles) == scene_circles(scene)


def test_the_pdf_places_each_circle_where_the_scene_put_it():
    """The load-bearing one. Between the scene and these bytes sit a frame
    flip, a points matrix and a four-Bezier circle, and no other test reaches
    all three."""
    data = panel()
    scene = scene_of(data)

    recovered = read_pdf(DrawingPdfEmitter(PdfDrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert sorted(
        (c.x_nm, c.y_nm, c.diameter_nm) for c in recovered.circles
    ) == scene_circles(scene, PDF_QUANTUM_NM)


def test_both_codecs_state_the_same_outline_extent():
    """T4 at the byte level. The load-bearing form of this claim is at layer 2,
    between owned representations; this is the cheap confirmation that the two
    codecs did not diverge below it."""
    data = panel()
    scene = scene_of(data)

    from_svg = read_svg(DrawingSvgEmitter().render(scene, "L3")).outline_nm
    from_pdf = read_pdf(DrawingPdfEmitter().render(scene, "L3")).outline_nm

    assert from_svg is not None, "the SVG stated no outline at all"
    assert from_pdf == tuple(quantised(v, PDF_QUANTUM_NM) for v in from_svg)


# ---------------------------------------------------------------------------
# JSON: the codec is the standard library; check our own round trip
# ---------------------------------------------------------------------------


def test_the_json_bytes_rebuild_the_model_they_were_written_from():
    data = panel()

    rebuilt = from_document(json.loads(JsonEmitter().emit(data)))

    assert rebuilt == data


def test_the_json_bytes_preserve_a_drill_number_that_is_not_a_list_position():
    data = panel()

    rebuilt = from_document(json.loads(JsonEmitter().emit(data)))

    assert [hole.index for hole in rebuilt.holes] == [3, 4, 1, 2]


# ---------------------------------------------------------------------------
# STEP: the cut shape, by face interrogation against the uncut model
# ---------------------------------------------------------------------------


@pytest.mark.hammond
def test_every_hole_appears_as_a_cylinder_the_uncut_model_did_not_have(tmp_path):
    """``read_step`` returns placed solids, so the holes are recovered by
    interrogating faces. Taking the difference against the uncut model avoids
    having to decide which of the enclosure's own cylinders is a hole."""
    pytest.importorskip("OCP", reason="needs stompdrill[step]")

    from OCP.Precision import Precision

    from stompdrill.cad import load_case_model
    from stompdrill.cad.step import read_step
    from stompdrill.emitters.step import StepEmitter, StepOptions
    from tests.hammond import cylinders, require_model

    model_path = require_model("1590BB")
    model = load_case_model(model_path, face="box", margin_nm=Nanometre(1_000_000))
    # Two distinct diameters: a count that is right with wrong radii, and
    # radii that are right with a wrong count, must be different defects.
    data = make_data(
        at(0, 0, 6_000_000, index=1),
        at(20_000_000, 0, 8_000_000, index=2),
    )

    out = tmp_path / "out.stp"
    out.write_bytes(StepEmitter(StepOptions(model=model)).emit(data))

    def every_cylinder(path) -> set[tuple[int, int, int, int]]:
        found: set[tuple[int, int, int, int]] = set()
        for solid in read_step(path).solids:
            found |= cylinders(solid.shape)
        return found

    added = every_cylinder(out) - every_cylinder(model_path)

    tolerance_mm = Precision.Confusion_s()
    expected_radii = {
        round((hole.diameter_nm / 2) / 1_000_000 / tolerance_mm) for hole in data.holes
    }

    assert len(added) == len(data.holes)
    assert {radius for _, _, _, radius in added} == expected_radii
