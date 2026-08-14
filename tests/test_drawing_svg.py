"""Tests for the ``drawing-svg`` emitter (SPEC §7, PLAN task E).

The emitter produces an *engineering drawing* of drill data — not a render of
the artwork. Everything asserted here is therefore about drill data and drawing
furniture: hole circles, balloons, dimensions, a schedule keyed to
``DrillData.tools()``, a title block and the diagnostics as notes.

No renderer is imported. The output is parsed with ``xml.etree.ElementTree`` and
asserted on as XML, which is the only thing the emitter promises.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from aidrill.emitters import base as emitter_base
from aidrill.emitters.drawing_svg import (
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    DrawingOptions,
    DrawingSvgEmitter,
    Sheet,
)
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    ReferenceOutline,
    Severity,
    SourceInfo,
)
from aidrill.pipeline import Deduplicate
from aidrill.protocols import Emitter
from tests.conftest import holes

SVG_NS = "http://www.w3.org/2000/svg"

# The test's own estimate of glyph advance, deliberately independent of the
# emitter's (which is more conservative) so the overflow test can actually fail.
CHAR_W = 0.6


# --------------------------------------------------------------------------
# fixtures — the SPEC §9 panel (tar.ai), post-pipeline
# --------------------------------------------------------------------------


def _panel() -> DrillData:
    return DrillData(
        holes=holes(
            (-40.0, 18.0),
            (-20.0, 18.0),
            (0.0, 18.0),
            (20.0, 18.0),
            (40.0, 18.0),
            (-19.0, -18.75, 5.0),
            (19.0, -18.75, 5.0),
        ),
        reference=ReferenceOutline(113.0, 60.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (-40.000, 18.000) within 0.05 mm; "
                "kept 1, dropped 1",
                location=(-40.0, 18.0),
                data=(("diameter", 7.0), ("dropped", 1)),
            ),
            Diagnostic.info("snap", "snapped 8 holes to a 0.25 mm grid"),
        ),
        source=SourceInfo(
            path="/panels/tar.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill", "Graphics", "Hardware"),
        ),
    )


@pytest.fixture
def panel() -> DrillData:
    return _panel()


@pytest.fixture
def svg(panel: DrillData) -> str:
    return DrawingSvgEmitter(DrawingOptions(title="TAR PANEL", drawing_no="AI-0001")).emit(panel)


@pytest.fixture
def root(svg: str) -> ET.Element:
    return ET.fromstring(svg)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1]


def walk(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if tag(e) == name]


def classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def by_class(root: ET.Element, cls: str, name: str | None = None) -> list[ET.Element]:
    return [
        e
        for e in root.iter()
        if cls in classes(e) and (name is None or tag(e) == name)
    ]


def all_text(root: ET.Element) -> str:
    return "\n".join((e.text or "") for e in walk(root, "text"))


def num(element: ET.Element, attr: str, default: float | None = None) -> float:
    raw = element.get(attr)
    if raw is None:
        assert default is not None, f"<{tag(element)}> is missing {attr!r}"
        return default
    return float(re.sub(r"[a-z%]+$", "", raw))


def text_box(element: ET.Element) -> tuple[float, float, float, float]:
    """Estimated (x0, y0, x1, y1) of a <text>, honouring anchor and rotation."""
    size = num(element, "font-size")
    content = element.text or ""
    width = CHAR_W * size * len(content)
    anchor = element.get("text-anchor", "start")
    x = num(element, "x")
    y = num(element, "y")
    x0 = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
    corners = [
        (x0, y - size * 0.8),
        (x0 + width, y - size * 0.8),
        (x0, y + size * 0.25),
        (x0 + width, y + size * 0.25),
    ]

    transform = element.get("transform") or ""
    match = re.match(r"rotate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)", transform)
    if match:
        angle, cx, cy = (float(v) for v in match.groups())
        radians = math.radians(angle)
        cos, sin = math.cos(radians), math.sin(radians)
        corners = [
            (
                cx + (px - cx) * cos - (py - cy) * sin,
                cy + (px - cx) * sin + (py - cy) * cos,
            )
            for px, py in corners
        ]

    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def drawn_points(root: ET.Element) -> list[tuple[str, float, float]]:
    """Extreme points of every drawn shape, as (tag, x, y)."""
    points: list[tuple[str, float, float]] = []
    for element in root.iter():
        name = tag(element)
        if name == "circle":
            cx, cy, r = num(element, "cx"), num(element, "cy"), num(element, "r")
            points += [(name, cx - r, cy - r), (name, cx + r, cy + r)]
        elif name == "rect":
            x, y = num(element, "x"), num(element, "y")
            points += [(name, x, y), (name, x + num(element, "width"), y + num(element, "height"))]
        elif name == "line":
            points += [
                (name, num(element, "x1"), num(element, "y1")),
                (name, num(element, "x2"), num(element, "y2")),
            ]
        elif name in ("polygon", "polyline"):
            for pair in (element.get("points") or "").split():
                px, py = pair.split(",")
                points.append((name, float(px), float(py)))
    return points


# --------------------------------------------------------------------------
# registry / protocol
# --------------------------------------------------------------------------


def test_registered_under_drawing_svg():
    assert emitter_base.REGISTRY["drawing-svg"] is DrawingSvgEmitter
    assert "drawing-svg" in emitter_base.available()
    assert emitter_base.get_emitter("drawing-svg") is DrawingSvgEmitter


def test_satisfies_the_emitter_protocol():
    emitter = DrawingSvgEmitter()
    assert isinstance(emitter, Emitter)
    assert DrawingSvgEmitter.name == "drawing-svg"
    assert DrawingSvgEmitter.media_type == "image/svg+xml"
    assert DrawingSvgEmitter.extension == ".svg"


def test_default_options_match_the_spec_signature():
    options = DrawingOptions()
    assert options.sheet == A4_LANDSCAPE
    assert options.scale is None
    assert options.title == ""
    assert options.drawing_no == ""
    assert options.true_size is None
    assert options.grid == 0.25


# --------------------------------------------------------------------------
# sheet
# --------------------------------------------------------------------------


def test_output_parses_as_xml_and_is_an_svg(svg: str):
    root = ET.fromstring(svg)
    assert svg.startswith("<?xml")
    assert root.tag == f"{{{SVG_NS}}}svg"


def test_sheet_is_a4_landscape_by_default(root: ET.Element):
    assert root.get("width") == "297mm"
    assert root.get("height") == "210mm"
    assert [float(v) for v in root.get("viewBox").split()] == [0.0, 0.0, 297.0, 210.0]


def test_sheet_is_configurable(panel: DrillData):
    root = ET.fromstring(DrawingSvgEmitter(DrawingOptions(sheet=A3_LANDSCAPE)).emit(panel))
    assert root.get("width") == "420mm"
    assert root.get("height") == "297mm"

    custom = Sheet("CUSTOM", 200.0, 150.0)
    root = ET.fromstring(DrawingSvgEmitter(DrawingOptions(sheet=custom)).emit(panel))
    assert root.get("width") == "200mm"


def test_sheet_has_a_border_inside_the_page(root: ET.Element):
    borders = by_class(root, "border", "rect")
    assert len(borders) == 1
    border = borders[0]
    assert num(border, "x") > 0
    assert num(border, "x") + num(border, "width") < 297.0


# --------------------------------------------------------------------------
# holes
# --------------------------------------------------------------------------


def test_one_hole_circle_per_hole_at_true_diameter_and_position(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)

    circles = by_class(root, "hole", "circle")
    assert len(circles) == len(panel.holes)

    for hole, circle in zip(panel.holes, circles):
        px, py = layout.point(hole.x, hole.y)
        assert num(circle, "cx") == pytest.approx(px, abs=1e-6)
        assert num(circle, "cy") == pytest.approx(py, abs=1e-6)
        assert num(circle, "r") == pytest.approx(hole.diameter / 2 * layout.scale, abs=1e-6)


def test_hole_positions_are_y_up_in_model_and_y_down_on_the_sheet(panel: DrillData):
    emitter = DrawingSvgEmitter()
    layout = emitter.layout(panel)
    left = layout.point(-40.0, 18.0)
    right = layout.point(40.0, 18.0)
    below = layout.point(-40.0, -18.75)
    assert left[0] < right[0]
    assert left[1] < below[1]
    assert left[1] == pytest.approx(right[1])


def test_every_hole_has_a_centre_mark_and_a_numbered_balloon(panel: DrillData, root: ET.Element):
    assert len(by_class(root, "balloon", "circle")) == len(panel.holes)
    assert len(by_class(root, "leader", "line")) == len(panel.holes)
    # centre mark = two crossing lines per hole
    assert len(by_class(root, "centre-mark", "line")) == 2 * len(panel.holes)

    numbers = sorted(int(e.text) for e in by_class(root, "balloon-no", "text"))
    assert numbers == list(range(1, len(panel.holes) + 1))


def test_duplicate_flagged_holes_are_red_with_a_dashed_ring(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)

    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    px, py = layout.point(-40.0, 18.0)
    assert num(flagged[0], "cx") == pytest.approx(px)
    assert num(flagged[0], "cy") == pytest.approx(py)
    assert "c" in (flagged[0].get("stroke") or "").lower()  # some red

    rings = by_class(root, "dup-ring", "circle")
    assert len(rings) == 1
    assert rings[0].get("stroke-dasharray")
    assert num(rings[0], "r") > num(flagged[0], "r")


def test_undflagged_holes_are_not_red(root: ET.Element):
    plain = [c for c in by_class(root, "hole", "circle") if "dup" not in classes(c)]
    assert plain
    for circle in plain:
        assert "c00000" not in (circle.get("stroke") or "")


def _reviewers_three_hole_case() -> DrillData:
    """Post-``Deduplicate(0.05)`` state of ⌀7 @ (0,0), ⌀7 @ (0,0), ⌀5 @ (0.03,0).

    ``Deduplicate`` collapses on proximity **and** equal diameter, so it keeps
    the ⌀7 at (0, 0) and the ⌀5 at (0.03, 0), and raises one ``duplicate-hole``
    naming the survivor: position (0, 0), diameter 7.
    """
    return DrillData(
        holes=(
            Hole.from_measurement(0.0, 0.0, 7.0, index=0),
            Hole.from_measurement(0.03, 0.0, 5.0, index=1),
        ),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (0.000, 0.000) within 0.05 mm; "
                "kept 1, dropped 1",
                location=(0.0, 0.0),
                data=(("diameter", 7.0), ("dropped", 1)),
            ),
        ),
    )


def test_a_neighbour_of_a_different_diameter_is_not_styled_as_a_duplicate():
    """The emitter must read the diagnostic, not re-derive the predicate.

    Matching on position alone painted the ⌀5 red as well: it sits 0.03 mm from
    the flagged point, inside any positional tolerance, but ``Deduplicate``
    never called it a duplicate because its diameter differs. The pipeline
    decided; the sheet the machinist reads has to say the same thing.
    """
    data = _reviewers_three_hole_case()
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    layout = emitter.layout(data)

    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    assert num(flagged[0], "r") == pytest.approx(layout.length(7.0) / 2.0)
    assert num(flagged[0], "cx") == pytest.approx(layout.point(0.0, 0.0)[0])
    assert len(by_class(root, "dup-ring", "circle")) == 1

    plain = [c for c in by_class(root, "hole", "circle") if "dup" not in classes(c)]
    assert len(plain) == 1
    assert num(plain[0], "r") == pytest.approx(layout.length(5.0) / 2.0)
    assert "c00000" not in (plain[0].get("stroke") or "")

    red_rows = [
        e.text
        for e in by_class(root, "sched-dia", "text")
        if "#c" in (e.get("style") or "").lower()
    ]
    assert red_rows == ["⌀7.00"], "only the ⌀7 hole is a duplicate in the schedule"


def test_the_pipelines_duplicate_verdict_reaches_the_sheet_unchanged():
    """The same case again, but decided by ``Deduplicate`` rather than by hand.

    Whatever the stage keeps and whatever it flags is what the machinist sees:
    two artifacts, one verdict, and no second implementation of the rule.
    """
    raw = DrillData(
        holes=(
            Hole.from_measurement(0.0, 0.0, 7.0, index=0),
            Hole.from_measurement(0.0, 0.0, 7.0, index=1),
            Hole.from_measurement(0.03, 0.0, 5.0, index=2),
        ),
        reference=ReferenceOutline(60.0, 40.0),
    )
    data = Deduplicate(0.05).apply(raw)
    assert [(h.x, h.diameter) for h in data.holes] == [(0.0, 7.0), (0.03, 5.0)]
    assert [d.code for d in data.diagnostics] == ["duplicate-hole"]

    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    layout = emitter.layout(data)

    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    assert num(flagged[0], "r") == pytest.approx(layout.length(7.0) / 2.0)
    assert len(by_class(root, "dup-ring", "circle")) == 1


def test_a_hole_merely_near_the_flagged_position_is_not_styled_as_a_duplicate():
    """No tolerance lives in the emitter: the match is exact, on both keys.

    A 0.001 mm offset means this is a *different* hole from the one the
    pipeline kept — and the pipeline's tolerance is ``--dedupe-tolerance``,
    which the emitter has no access to and must not guess at.
    """
    data = DrillData(
        holes=(
            Hole.from_measurement(0.001, 0.0, 7.0, index=0),
            Hole.from_measurement(20.0, 0.0, 7.0, index=1),
        ),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (0.000, 0.000)",
                location=(0.0, 0.0),
                data=(("diameter", 7.0), ("dropped", 1)),
            ),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []


# --------------------------------------------------------------------------
# outline, centrelines, origin
# --------------------------------------------------------------------------


def test_reference_outline_is_a_rounded_rect_at_scale(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)

    outlines = by_class(root, "outline", "rect")
    assert len(outlines) == 1
    outline = outlines[0]
    assert num(outline, "width") == pytest.approx(113.0 * layout.scale)
    assert num(outline, "height") == pytest.approx(60.0 * layout.scale)
    assert num(outline, "rx") > 0


def test_true_size_overlay_only_when_requested(panel: DrillData):
    plain = ET.fromstring(DrawingSvgEmitter().emit(panel))
    assert by_class(plain, "true-size") == []

    emitter = DrawingSvgEmitter(DrawingOptions(true_size=(112.0, 60.5)))
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)
    overlay = by_class(root, "true-size", "rect")
    assert len(overlay) == 1
    assert num(overlay[0], "width") == pytest.approx(112.0 * layout.scale)
    assert num(overlay[0], "height") == pytest.approx(60.5 * layout.scale)
    assert overlay[0].get("stroke-dasharray"), "true-size overlay must be dashed"
    assert overlay[0].get("stroke") != by_class(root, "outline", "rect")[0].get("stroke")


def test_centrelines_are_chain_dashed_and_cross_the_origin(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)
    ox, oy = layout.point(0.0, 0.0)

    lines = by_class(root, "centreline", "line")
    assert len(lines) == 2
    horizontal = [ln for ln in lines if num(ln, "y1") == num(ln, "y2")]
    vertical = [ln for ln in lines if num(ln, "x1") == num(ln, "x2")]
    assert len(horizontal) == 1 and len(vertical) == 1
    assert num(horizontal[0], "y1") == pytest.approx(oy)
    assert num(vertical[0], "x1") == pytest.approx(ox)
    for line in lines:
        dashes = [float(v) for v in re.split(r"[ ,]+", line.get("stroke-dasharray").strip())]
        assert len(dashes) >= 4, "centrelines must be chain-dash (long-short-long)"


def test_origin_symbol_is_drawn_at_zero_zero(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)
    ox, oy = layout.point(0.0, 0.0)

    marks = by_class(root, "origin", "circle")
    assert marks
    assert num(marks[0], "cx") == pytest.approx(ox)
    assert num(marks[0], "cy") == pytest.approx(oy)
    assert "0,0" in all_text(root)


# --------------------------------------------------------------------------
# dimensions
# --------------------------------------------------------------------------


def test_one_dimension_chain_per_row_with_extension_lines(panel: DrillData, root: ET.Element):
    chains = by_class(root, "dim-chain")
    assert len(chains) == len(panel.rows()) == 2
    for chain in chains:
        assert by_class(chain, "extension", "line")
        assert by_class(chain, "dim-line", "line")
        assert by_class(chain, "dim-text", "text")


def test_chain_dimension_values_are_hole_to_hole_distances(root: ET.Element):
    values = {e.text for e in by_class(root, "dim-text", "text")}
    assert "20.00" in values, "⌀7 row is on a 20 mm pitch"
    assert "38.00" in values, "the two ⌀5 holes are 38 mm apart"


def test_overall_width_and_height_dimensions(root: ET.Element):
    overall = {e.text for e in by_class(root, "dim-overall", "text")}
    assert "113.00" in overall
    assert "60.00" in overall


def test_vertical_dimension_text_is_rotated(root: ET.Element):
    vertical = [
        e
        for e in by_class(root, "dim-overall", "text")
        if e.text == "60.00"
    ]
    assert vertical
    assert all("rotate(-90" in (e.get("transform") or "") for e in vertical)


# --------------------------------------------------------------------------
# hole schedule
# --------------------------------------------------------------------------


def test_schedule_has_one_row_per_hole(panel: DrillData, root: ET.Element):
    assert len(by_class(root, "sched-row")) == len(panel.holes)


def test_schedule_columns_are_no_x_y_diameter_tool(root: ET.Element):
    headers = [e.text for e in by_class(root, "sched-head", "text")]
    assert headers[0].upper().startswith("NO")
    assert [h.upper() for h in headers[1:3]] == ["X", "Y"]
    assert "⌀" in headers[3]
    assert headers[4].upper() == "TOOL"


def test_schedule_cells_carry_the_hole_data(panel: DrillData, root: ET.Element):
    rows = by_class(root, "sched-row")
    for index, (hole, row) in enumerate(zip(panel.holes, rows), start=1):
        cells = {
            cls: e.text
            for e in walk(row, "text")
            for cls in classes(e)
            if cls.startswith("sched-") and cls != "sched-row"
        }
        assert cells["sched-no"] == str(index)
        assert float(cells["sched-x"]) == pytest.approx(hole.x)
        assert float(cells["sched-y"]) == pytest.approx(hole.y)
        assert float(cells["sched-dia"].lstrip("⌀")) == pytest.approx(hole.diameter)


def test_schedule_tool_numbers_come_from_drilldata_tools(panel: DrillData, root: ET.Element):
    tools = panel.tools()
    rows = by_class(root, "sched-row")
    for hole, row in zip(panel.holes, rows):
        cell = by_class(row, "sched-tool", "text")[0]
        assert cell.text.lstrip("T") == str(tools[hole.diameter])

    used = {int(by_class(r, "sched-tool", "text")[0].text.lstrip("T")) for r in rows}
    assert used == set(tools.values())


def test_schedule_never_prints_a_negative_zero():
    """One hole, two artifacts, one number.

    A hole at −0.0004 mm rounds to zero at two decimals. The Excellon writer
    normalised the sign away and the schedule did not, so the drill file said
    ``X0.000`` and the sheet beside it said ``-0.00`` — the same hole,
    contradicted in print. Both now go through ``formatting.format_mm``.
    """
    data = DrillData(
        holes=(Hole.from_measurement(-0.0004, -0.0004, 5.0, index=0),),
        reference=ReferenceOutline(60.0, 40.0),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    row = by_class(root, "sched-row")[0]

    assert by_class(row, "sched-x", "text")[0].text == "0.00"
    assert by_class(row, "sched-y", "text")[0].text == "0.00"


def test_schedule_has_a_per_tool_summary_with_quantities(root: ET.Element):
    summary = [e.text for e in by_class(root, "sched-summary", "text")]
    assert len(summary) == 2
    joined = " | ".join(summary)
    assert "T1" in joined and "T2" in joined
    assert "5.00" in joined and "7.00" in joined
    assert "2" in summary[0] and "5" in summary[1]  # quantities, ascending by size


# --------------------------------------------------------------------------
# title block
# --------------------------------------------------------------------------


def test_title_block_carries_the_required_fields(panel: DrillData):
    emitter = DrawingSvgEmitter(
        DrawingOptions(title="TAR PANEL", drawing_no="AI-0001", grid=0.25)
    )
    root = ET.fromstring(emitter.emit(panel))
    text = all_text(root)
    assert by_class(root, "title-block", "rect")
    assert "ARTIFACT" in text.upper()
    assert "TAR PANEL" in text
    assert "AI-0001" in text
    assert "SHEET" in text.upper()
    assert "mm" in text
    assert "0.25" in text
    assert "PROJECTION" in text.upper()
    assert "tar.ai" in text


def test_title_block_reports_the_scale(panel: DrillData):
    emitter = DrawingSvgEmitter(DrawingOptions(scale=0.5))
    root = ET.fromstring(emitter.emit(panel))
    assert "1:2" in all_text(root)
    assert emitter.layout(panel).scale == 0.5


def test_only_drill_data_is_drawn_never_the_artwork(panel: DrillData, root: ET.Element):
    """This is a drawing *of the drill data*, not a render of the panel artwork.

    Asserted structurally rather than by searching the serialised text for a
    layer name: ``"Graphics" not in svg`` passes for an emitter that returns
    ``<svg/>`` and fails for a panel whose file path happens to contain the
    word. What actually matters is that every element on the sheet is drawing
    furniture, and that no artwork — raster or vector — was imported.
    """
    assert "Graphics" in panel.source.layers_found  # the source did carry artwork

    assert len(by_class(root, "hole", "circle")) == len(panel.holes)
    assert by_class(root, "border", "rect")

    assert walk(root, "image") == []
    assert walk(root, "path") == []
    assert walk(root, "use") == []
    assert {tag(e) for e in root.iter()} <= {
        "svg", "title", "style", "g", "rect", "line", "circle", "polygon", "text"
    }

    drawn_text = all_text(root)
    for layer in panel.source.layers_found:
        if layer not in (panel.source.drill_layer, panel.source.reference_layer):
            assert layer not in drawn_text, f"artwork layer {layer!r} named on the sheet"


# --------------------------------------------------------------------------
# notes
# --------------------------------------------------------------------------


def test_every_warning_message_appears_as_a_numbered_note(panel: DrillData, root: ET.Element):
    notes = [e.text for e in by_class(root, "note", "text")]
    joined = "\n".join(notes)
    for diagnostic in panel.diagnostics:
        if diagnostic.severity is Severity.WARNING:
            assert diagnostic.message in joined
    assert any(note.strip().startswith("1.") for note in notes)


def test_warning_notes_are_red_via_inline_style_not_a_fill_attribute(root: ET.Element):
    """A CSS rule in <style> beats a fill= presentation attribute — inline style
    is the only reliable way to colour text here."""
    stylesheet = "\n".join(e.text or "" for e in walk(root, "style"))
    assert re.search(r"text\s*\{[^}]*fill:", stylesheet), (
        "this test only means something if the stylesheet does set a text fill"
    )

    warnings = [e for e in by_class(root, "note", "text") if "note-warning" in classes(e)]
    assert warnings
    for element in warnings:
        style = element.get("style") or ""
        assert re.search(r"fill:\s*#[0-9a-fA-F]{3,6}", style), (
            f"warning note must carry an inline style fill, got style={style!r} "
            f"fill={element.get('fill')!r}"
        )
        assert style.lower().replace(" ", "").startswith("fill:#c")


def test_error_notes_are_red_too(panel: DrillData):
    data = panel.with_diagnostics(Diagnostic.error("boom", "something is very wrong"))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    errors = [e for e in by_class(root, "note", "text") if "note-error" in classes(e)]
    assert errors
    assert "something is very wrong" in "\n".join(e.text for e in errors)
    for element in errors:
        assert (element.get("style") or "").lower().replace(" ", "").startswith("fill:#c")


def test_info_notes_are_not_red(root: ET.Element):
    infos = [e for e in by_class(root, "note", "text") if "note-info" in classes(e)]
    assert infos
    for element in infos:
        assert "#c" not in (element.get("style") or "").lower()


def test_notes_block_is_labelled(root: ET.Element):
    assert "NOTES" in all_text(root).upper()


def _many_warnings(count: int) -> DrillData:
    drilled = tuple(
        Hole.from_measurement(-40.0 + 2.0 * i, 0.0, 3.0, index=i) for i in range(count)
    )
    return DrillData(
        holes=drilled,
        reference=ReferenceOutline(113.0, 60.0),
        diagnostics=tuple(
            Diagnostic.warning(
                "off-grid",
                f"hole {i} moved 0.12 mm to reach the 0.25 mm grid",
                location=(-40.0 + 2.0 * i, 0.0),
            )
            for i in range(count)
        ),
    )


def test_notes_that_do_not_fit_say_how_many_were_left_off():
    """A note that silently vanishes is worse than one that is visibly missing.

    Forty ``off-grid`` warnings cannot fit the NOTES block. Dropping the tail
    without a word means the operator never learns that holes were moved, and
    has no way to know the sheet is incomplete. The schedule already prints
    "… N further holes not listed" for exactly this reason.
    """
    data = _many_warnings(40)
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    notes = [e for e in by_class(root, "note", "text")]
    overflow = [e for e in notes if "note-overflow" in classes(e)]
    listed = [e for e in notes if "note-overflow" not in classes(e)]

    assert len(listed) < 40, "this test only means anything if notes are truncated"
    assert len(overflow) == 1, "truncation must be announced exactly once"

    omitted = int(re.search(r"(\d+)", overflow[0].text or "").group(1))
    assert len(listed) + omitted == 40
    assert "further" in (overflow[0].text or "")


def test_notes_that_all_fit_carry_no_overflow_marker(root: ET.Element):
    assert by_class(root, "note-overflow", "text") == []


def test_the_notes_overflow_marker_stays_inside_the_notes_box():
    data = _many_warnings(40)
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    nx0, ny0, nx1, ny1 = emitter.layout(data).notes

    marker = by_class(root, "note-overflow", "text")[0]
    tx0, ty0, tx1, ty1 = text_box(marker)
    assert nx0 - 0.6 <= tx0 and tx1 <= nx1 + 0.6
    assert ny0 - 0.6 <= ty0 and ty1 <= ny1 + 0.6


def test_the_schedule_says_how_many_holes_it_could_not_list():
    """The schedule's own truncation path, which was never covered."""
    drilled = tuple(
        Hole.from_measurement(-55.0 + 0.5 * i, 20.0 - 0.4 * (i // 40), 3.0, index=i)
        for i in range(240)
    )
    data = DrillData(holes=drilled, reference=ReferenceOutline(120.0, 60.0))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    listed = by_class(root, "sched-row")
    overflow = by_class(root, "sched-overflow", "text")

    assert len(listed) < 240, "this test only means anything if rows are truncated"
    assert len(overflow) == 1
    omitted = int(re.search(r"(\d+)", overflow[0].text or "").group(1))
    assert len(listed) + omitted == 240


# --------------------------------------------------------------------------
# fitting and overflow
# --------------------------------------------------------------------------


def test_scale_none_fits_the_drawing_inside_the_sheet(panel: DrillData):
    emitter = DrawingSvgEmitter()
    layout = emitter.layout(panel)
    assert layout.scale > 0
    root = ET.fromstring(emitter.emit(panel))

    x0, y0, x1, y1 = layout.border
    for name, px, py in drawn_points(root):
        assert x0 - 0.6 <= px <= x1 + 0.6, f"<{name}> x={px} outside border"
        assert y0 - 0.6 <= py <= y1 + 0.6, f"<{name}> y={py} outside border"


def test_layout_content_extent_stays_inside_the_drawing_area(panel: DrillData):
    layout = DrawingSvgEmitter().layout(panel)
    cx0, cy0, cx1, cy1 = layout.content
    ax0, ay0, ax1, ay1 = layout.area
    assert cx1 - cx0 == pytest.approx(2 * layout.half_width * layout.scale)
    assert cy1 - cy0 == pytest.approx(2 * layout.half_height * layout.scale)
    assert ax0 < cx0 and cx1 < ax1
    assert ay0 < cy0 and cy1 < ay1


def test_scale_none_fits_a_panel_far_bigger_than_the_sheet(panel: DrillData):
    big = panel.with_holes(
        holes(*((x, y, 12.0) for x in (-400.0, 0.0, 400.0) for y in (-200.0, 200.0)))
    )
    big = DrillData(
        holes=big.holes,
        reference=ReferenceOutline(900.0, 500.0),
        diagnostics=(),
        source=big.source,
    )
    emitter = DrawingSvgEmitter()
    layout = emitter.layout(big)
    assert layout.scale < 1.0
    root = ET.fromstring(emitter.emit(big))
    x0, y0, x1, y1 = layout.border
    for name, px, py in drawn_points(root):
        assert x0 - 0.6 <= px <= x1 + 0.6
        assert y0 - 0.6 <= py <= y1 + 0.6


def test_no_text_overflows_the_sheet_border(panel: DrillData):
    emitter = DrawingSvgEmitter(
        DrawingOptions(
            title="A DELIBERATELY VERY LONG DRAWING TITLE THAT WOULD OVERFLOW",
            drawing_no="AI-0001-REV-C-SUPERSEDES-EVERYTHING",
        )
    )
    root = ET.fromstring(emitter.emit(panel))
    x0, y0, x1, y1 = emitter.layout(panel).border
    for element in walk(root, "text"):
        tx0, ty0, tx1, ty1 = text_box(element)
        assert tx0 >= x0 - 0.6, f"text {element.text!r} overflows the left border"
        assert tx1 <= x1 + 0.6, f"text {element.text!r} overflows the right border"
        assert ty0 >= y0 - 0.6, f"text {element.text!r} overflows the top border"
        assert ty1 <= y1 + 0.6, f"text {element.text!r} overflows the bottom border"


@pytest.mark.parametrize("width", list(range(40, 320, 11)))
def test_no_text_overflows_for_any_panel_width(width: int):
    """Sweeps the fitted scale through the width-constrained regime, where the
    left-hand height dimension sits hard against the border. An unrotated label
    there runs off the sheet."""
    half = width / 2 - 6
    data = DrillData(
        holes=holes(*((x, y, 6.0) for x in (-half, 0.0, half) for y in (12.0, -12.0))),
        # a six-digit height label is the widest thing on the left-hand side
        reference=ReferenceOutline(float(width), 100.25),
    )
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    x0, y0, x1, y1 = emitter.layout(data).border
    for element in walk(root, "text"):
        tx0, ty0, tx1, ty1 = text_box(element)
        assert tx0 >= x0 - 0.6, f"{element.text!r} at x={tx0} overflows the left border"
        assert tx1 <= x1 + 0.6, f"{element.text!r} overflows the right border"
        assert ty0 >= y0 - 0.6, f"{element.text!r} overflows the top border"
        assert ty1 <= y1 + 0.6, f"{element.text!r} overflows the bottom border"


def test_every_text_declares_its_own_font_size(root: ET.Element):
    """Font size must be a presentation attribute per element: a stylesheet rule
    would win over it and silently break the layout estimates."""
    for element in walk(root, "text"):
        assert element.get("font-size") is not None
    stylesheet = "\n".join(e.text or "" for e in walk(root, "style"))
    assert "font-size" not in stylesheet


def test_explicit_scale_is_used_verbatim(panel: DrillData):
    emitter = DrawingSvgEmitter(DrawingOptions(scale=2.0))
    assert emitter.layout(panel).scale == 2.0
    root = ET.fromstring(emitter.emit(panel))
    outline = by_class(root, "outline", "rect")[0]
    assert num(outline, "width") == pytest.approx(226.0)


# --------------------------------------------------------------------------
# degenerate inputs
# --------------------------------------------------------------------------


def test_empty_drilldata_does_not_crash():
    svg = DrawingSvgEmitter().emit(DrillData())
    root = ET.fromstring(svg)
    assert by_class(root, "border", "rect")
    assert by_class(root, "hole", "circle") == []
    assert by_class(root, "sched-row") == []
    assert "NOTES" in all_text(root).upper()


def test_data_without_a_reference_outline_still_draws_holes():
    data = DrillData(holes=(Hole.from_measurement(0.0, 0.0, 3.0, index=0),))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    assert len(by_class(root, "hole", "circle")) == 1
    assert by_class(root, "outline", "rect") == []


def test_single_hole_does_not_divide_by_zero():
    data = DrillData(
        holes=(Hole.from_measurement(3.0, 4.0, 5.0, index=0),),
        reference=ReferenceOutline(50.0, 40.0),
    )
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert len(by_class(root, "hole", "circle")) == 1
    assert emitter.layout(data).scale > 0


def test_text_is_xml_escaped():
    data = DrillData(
        holes=(),
        diagnostics=(Diagnostic.warning("x", "5 < 7 & \"quoted\" <b>"),),
        source=SourceInfo(path="a&b.ai"),
    )
    svg = DrawingSvgEmitter().emit(data)
    root = ET.fromstring(svg)  # would raise if unescaped
    assert '5 < 7 & "quoted" <b>' in all_text(root)


def test_emit_is_deterministic(panel: DrillData):
    emitter = DrawingSvgEmitter(DrawingOptions(title="T"))
    assert emitter.emit(panel) == emitter.emit(panel)


def test_many_holes_still_fit_the_schedule_and_the_sheet():
    drilled = tuple(
        Hole.from_measurement(-50 + 5 * i, 20.0 - 4 * (i // 20), 3.0, index=i)
        for i in range(60)
    )
    data = DrillData(holes=drilled, reference=ReferenceOutline(120.0, 60.0))
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    x0, y0, x1, y1 = emitter.layout(data).border
    for element in walk(root, "text"):
        tx0, ty0, tx1, ty1 = text_box(element)
        assert x0 - 0.6 <= tx0 and tx1 <= x1 + 0.6
        assert y0 - 0.6 <= ty0 and ty1 <= y1 + 0.6
    for name, px, py in drawn_points(root):
        assert x0 - 0.6 <= px <= x1 + 0.6
        assert y0 - 0.6 <= py <= y1 + 0.6
