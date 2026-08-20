"""Tests for SVG drawing layout and rendered drill information."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import fields

import pytest

from stompdrill.emitters import base as emitter_base
from stompdrill.emitters.drawing_svg import (
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    DrawingOptions,
    DrawingSvgEmitter,
    Sheet,
)
from stompdrill.pipeline import (
    DRILL_STANDARDS,
    Deduplicate,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from stompdrill.quantise import RawDrillData, quantise
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.errors import EmitterError
from stompmodel.model import (
    DrillData,
    EnclosureMatch,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from stompmodel.protocols import Emitter
from stompmodel.units import Millimetre, Nanometre, format_nm, mm_from_nm
from tests.conftest import at, holes, make_data

SVG_NS = "http://www.w3.org/2000/svg"

# The test's own estimate of glyph advance, deliberately independent of the
# emitter's (which is more conservative) so the overflow test can actually fail.
CHAR_W = 0.6


# --------------------------------------------------------------------------
# fixtures — the tar.ai panel, post-quantisation
# --------------------------------------------------------------------------


def _panel() -> DrillData:
    """Return the quantised fixture panel.

    Hole numbers are out of tuple order so a number and a list position
    cannot coincide.
    """
    return DrillData(
        holes=(
            at(-40_000_000, 18_000_000, index=12),
            at(-20_000_000, 18_000_000, index=5),
            at(0, 18_000_000, index=9),
            at(20_000_000, 18_000_000, index=3),
            at(40_000_000, 18_000_000, index=11),
            at(-19_000_000, -18_750_000, 5_000_000, index=7),
            at(19_000_000, -18_750_000, 5_000_000, index=1),
        ),
        reference=outline(113_000_000, 60_000_000),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (-40.000, 18.000); 1 hole dropped",
                location_nm=(-40_000_000, 18_000_000),
                data=(
                    ("diameter_nm", 7_000_000),
                    ("dropped", 1),
                ),
            ),
            Diagnostic.info("snap", "snapped 8 holes to a 0.250 mm grid"),
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


def measured(x: float, y: float, diameter: float = 7.0) -> RawHole:
    """One circle as a source would answer it: float millimetres, unquantised."""
    return RawHole(Millimetre(x), Millimetre(y), Millimetre(diameter))


def phase(
    *circles: RawHole,
    reference: RawOutline | None = None,
    enclosure: IdentifyHammondFootprint | None = None,
    diameters: SnapDiametersToDrillTable | None = None,
    positions: SnapPositions | None = None,
) -> DrillData:
    """One real quantisation phase, with the CLI's defaults unless named."""
    return quantise(
        RawDrillData(
            source=SourceInfo(path="panel.ai", drill_layer="Drill"),
            reference=reference,
            centre=(Millimetre(0.0), Millimetre(0.0)),
            holes=circles,
        ),
        enclosure=enclosure if enclosure is not None else IdentifyHammondFootprint(),
        diameters=diameters if diameters is not None else SnapDiametersToDrillTable(),
        positions=positions if positions is not None else SnapPositions(Nanometre(250_000)),
    )


def numbered(data: DrillData) -> DrillData:
    """Attach the numbers ``RouteHoles`` would assign, without engaging its
    grouping or ordering. Emitting requires a number and these tests are not
    about routing, so source order is numbered sequentially from one."""
    return data.with_holes(h.with_number(i) for i, h in enumerate(data.holes, start=1))


def outline(width_nm: int, height_nm: int) -> ReferenceOutline:
    """A reference outline whose nominal size is also its measurement."""
    return ReferenceOutline.from_measurement(Nanometre(width_nm), Nanometre(height_nm))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1]


def walk(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if tag(e) == name]


def classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def text_of(element: ET.Element) -> str:
    """The element's text, failing where it is missing rather than where it is parsed."""
    assert element.text is not None, f"<{tag(element)}> carries no text"
    return element.text


def attr_of(element: ET.Element, name: str) -> str:
    """The attribute's value, failing where it is missing rather than where it is parsed."""
    value = element.get(name)
    assert value is not None, f"<{tag(element)}> has no {name!r} attribute"
    return value


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


def extents(root: ET.Element) -> list[tuple[str, float, float, float, float]]:
    """Every drawn thing's estimated box, as ``(what, x0, y0, x1, y1)``."""
    boxes = [
        ((element.text or tag(element)), *text_box(element))
        for element in walk(root, "text")
    ]
    return boxes + [(name, px, py, px, py) for name, px, py in drawn_points(root)]


def assert_within(box: tuple[float, float, float, float], group: ET.Element, what: str) -> None:
    x0, y0, x1, y1 = box
    for label, bx0, by0, bx1, by1 in extents(group):
        assert x0 - 0.6 <= bx0 and bx1 <= x1 + 0.6, f"{label!r} escapes {what} sideways"
        assert y0 - 0.6 <= by0 and by1 <= y1 + 0.6, f"{label!r} escapes {what} vertically"


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


def test_the_emitter_refuses_data_that_was_never_routed():
    data = make_data(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
                     reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)))
    with pytest.raises(EmitterError, match="no drill number"):
        DrawingSvgEmitter().emit(data)


def test_default_options_match_the_spec_signature():
    options = DrawingOptions()
    assert options.sheet == A4_LANDSCAPE
    assert options.scale is None
    assert options.title == ""
    assert options.drawing_no == ""


def test_the_options_carry_no_grid_of_their_own():
    """The grid is a pipeline fact, and a second copy is a second answer."""
    assert "grid" not in {f.name for f in fields(DrawingOptions)}
    with pytest.raises(TypeError):
        DrawingOptions(grid=0.25)


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
    assert [float(v) for v in attr_of(root, "viewBox").split()] == [0.0, 0.0, 297.0, 210.0]


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
        px, py = layout.point(mm_from_nm(hole.x_nm), mm_from_nm(hole.y_nm))
        assert num(circle, "cx") == pytest.approx(px, abs=1e-6)
        assert num(circle, "cy") == pytest.approx(py, abs=1e-6)
        assert num(circle, "r") == pytest.approx(
            mm_from_nm(hole.diameter_nm) / 2 * layout.scale, abs=1e-6
        )


def test_the_sheet_states_the_nominal_everywhere_and_the_measurement_nowhere():
    """The one fixture where a hole's two numbers do not coincide."""
    data = numbered(phase(
        measured(-39.9906, 17.99996, 6.998),
        measured(19.9942, 17.99996, 6.998),
        reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        enclosure=IdentifyHammondFootprint("1590B"),
    ))
    target = data.holes[0]
    assert (target.x_nm, target.y_nm) == (-40_000_000, 18_000_000)
    assert target.raw.x != mm_from_nm(target.x_nm)
    assert data.reference is not None
    assert data.reference.width_nm == 112_400_000 != data.reference.raw.width

    emitter = DrawingSvgEmitter()
    layout = emitter.layout(data)
    root = ET.fromstring(emitter.emit(data))

    circle = by_class(root, "hole", "circle")[0]
    assert num(circle, "cx") == pytest.approx(layout.point(-40.0, 18.0)[0], abs=1e-6)
    assert num(circle, "cx") != pytest.approx(
        layout.point(target.raw.x, 18.0)[0], abs=1e-6
    )

    # The measurements would have printed "-39.991" and "19.994" here.
    assert [e.text for e in by_class(root, "sched-x", "text")] == ["-40.000", "20.000"]
    assert [e.text for e in by_class(root, "sched-dia", "text")] == ["⌀7.00 mm"] * 2

    rect = by_class(root, "outline", "rect")[0]
    assert num(rect, "width") == pytest.approx(112.4 * layout.scale)
    assert num(rect, "height") == pytest.approx(60.5 * layout.scale)


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

    numbers = sorted(int(text_of(e)) for e in by_class(root, "balloon-no", "text"))
    assert numbers == sorted(number for number, _ in panel.numbered())


def test_balloons_read_the_number_through_numbered_not_list_position(
    panel: DrillData, root: ET.Element
):
    """One number, one hole, across all four artefacts."""
    balloons = [int(text_of(e)) for e in by_class(root, "balloon-no", "text")]
    assert balloons == [number for number, _ in panel.numbered()]
    assert balloons != list(range(1, len(panel.holes) + 1)), (
        "the fixture's numbers must not coincide with its positions, or this proves nothing"
    )


def test_the_sheet_numbers_the_flagged_hole_the_way_the_diagnostic_does(
    panel: DrillData, root: ET.Element
):
    """The one place the two numbering schemes can be caught disagreeing."""
    duplicate = next(d for d in panel.diagnostics if d.code == "duplicate-hole")
    flagged_hole = next(
        h for h in panel.holes if (h.x_nm, h.y_nm) == duplicate.location_nm
    )
    named = str(flagged_hole.index)

    red = [
        row
        for row in by_class(root, "sched-row")
        if any("fill:#c" in (e.get("style") or "") for e in walk(row, "text"))
    ]
    assert len(red) == 1, "exactly one hole is flagged on this panel"
    assert by_class(red[0], "sched-no", "text")[0].text == named
    assert named in [e.text for e in by_class(root, "balloon-no", "text")]


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
    """Post-``Deduplicate()`` state of ⌀7 @ (0,0), ⌀7 @ (0,0), ⌀5 @ (0.03,0)."""
    return DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(30_000), Nanometre(0), Nanometre(5_000_000)).with_number(2),
        ),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (0.000, 0.000); 1 hole dropped",
                location_nm=(0, 0),
                data=(
                    ("diameter_nm", 7_000_000),
                    ("dropped", 1),
                ),
            ),
        ),
    )


def test_a_neighbour_of_a_different_diameter_is_not_styled_as_a_duplicate():
    """The emitter must read the diagnostic, not re-derive the predicate."""
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
    assert red_rows == ["⌀7.00 mm"], "only the ⌀7 hole is a duplicate in the schedule"


def test_the_pipelines_duplicate_verdict_reaches_the_sheet_unchanged():
    """The pipeline's duplicate verdict reaches both artefacts unchanged.

    Real ``Deduplicate`` output ensures the sheet does not re-derive the rule.
    """
    raw = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(1),
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(2),
            Hole.from_measurement(Nanometre(30_000), Nanometre(0), Nanometre(5_000_000)).with_number(3),
        ),
        reference=outline(60_000_000, 40_000_000),
    )
    data = Deduplicate().apply(raw)
    assert [(h.x_nm, h.diameter_nm) for h in data.holes] == [
        (0, 7_000_000),
        (30_000, 5_000_000),
    ]
    assert [d.code for d in data.diagnostics] == ["duplicate-hole"]

    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    layout = emitter.layout(data)

    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    assert num(flagged[0], "r") == pytest.approx(layout.length(7.0) / 2.0)
    assert len(by_class(root, "dup-ring", "circle")) == 1


def test_the_flagged_hole_is_the_one_at_the_exact_place_not_one_nearby():
    """Location decides, exactly, and a near neighbour is not close enough."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(1_000), Nanometre(0), Nanometre(7_000_000)).with_number(3),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(0), Nanometre(7_000_000)).with_number(8),
        ),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (20.000, 0.000)",
                location_nm=(20_000_000, 0),
                data=(("diameter_nm", 7_000_000), ("dropped", 1)),
            ),
        ),
    )
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    layout = emitter.layout(data)

    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    assert num(flagged[0], "cx") == pytest.approx(layout.point(20.0, 0.0)[0])
    assert len(by_class(root, "dup-ring", "circle")) == 1
    assert num(by_class(root, "dup-ring", "circle")[0], "cx") == pytest.approx(
        layout.point(20.0, 0.0)[0]
    )

    plain = [c for c in by_class(root, "hole", "circle") if "dup" not in classes(c)]
    assert len(plain) == 1
    assert num(plain[0], "cx") == pytest.approx(layout.point(0.001, 0.0)[0])
    assert "c00000" not in (plain[0].get("stroke") or "")


def _one_hole_with_a_duplicate_diagnostic(payload, location_nm=(0, 0)) -> DrillData:
    """Two ⌀7 holes, ids 3 and 0, and a ``duplicate-hole`` carrying ``payload``."""
    return DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(3),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(10_000_000), Nanometre(7_000_000)).with_number(1),
        ),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (0.000, 0.000)",
                location_nm=location_nm,
                data=payload,
            ),
        ),
    )


def test_a_duplicate_hole_diagnostic_without_a_location_flags_nothing():
    """No location, no ring — and emphatically no guess from an index."""
    data = _one_hole_with_a_duplicate_diagnostic(
        (("diameter_nm", 7_000_000), ("dropped", 1)), location_nm=None
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []
    assert "coincident" in all_text(root)  # the finding still reaches the sheet


def test_a_hole_sharing_only_one_axis_with_the_finding_is_not_rung():
    """Both coordinates select the hole, not either one of them.

    A column of holes shares an X and a row shares a Y, so a join that
    compared one axis would ring every hole in the finding's row or column.
    """
    data = DrillData(
        holes=(
            at(0, 0, 7_000_000, index=3),
            at(0, 20_000_000, 7_000_000, index=1),  # same X, different Y
            at(20_000_000, 0, 7_000_000, index=9),  # same Y, different X
        ),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (0.000, 0.000)",
                location_nm=(0, 0),
                data=(("diameter_nm", 7_000_000), ("dropped", 1)),
            ),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert len(by_class(root, "dup-ring", "circle")) == 1
    assert num(by_class(root, "dup-ring", "circle")[0], "cx") == pytest.approx(
        num([c for c in by_class(root, "hole", "circle") if "dup" in classes(c)][0], "cx")
    )


def test_a_finding_that_is_not_a_duplicate_rings_no_hole():
    """The ring means *duplicate*, so the code is what selects it."""
    data = DrillData(
        holes=(at(0, 0, 7_000_000, index=3),),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.error(
                "unknown-diameter",
                "no metric drill size within 0.150 mm of ⌀7.130 mm; hole dropped",
                location_nm=(0, 0),
                data=(("diameter_nm", 7_130_000),),
            ),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []
    assert by_class(root, "hole", "circle")[0].get("stroke") == "#111111"
    assert "no metric drill size" in all_text(root)  # the finding still reaches the sheet


def test_a_payload_of_tied_locations_rings_none_of_them():
    """``tied_locations`` names holes; only ``duplicate-hole`` is the ring."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(0), Nanometre(7_000_000)).with_number(1),
        ),
        reference=outline(60_000_000, 40_000_000),
        diagnostics=(
            Diagnostic.warning(
                "grid-ambiguous",
                "2 hole(s) sat exactly halfway between two 0.250 mm grid points",
                data=(("tied_locations", ((0, 0), (20_000_000, 0))),),
            ),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []
    assert "halfway between" in all_text(root)


def test_the_duplicate_verdict_survives_the_snap_that_produced_it():
    """The ring follows the place, not the coordinate the finding happened to keep."""
    after = Deduplicate().apply(
        phase(
            measured(10.03, 5.02),
            measured(10.06, 4.99),
        )
    )
    after = after.with_holes(h.with_number(6) for h in after.holes)
    assert [d.code for d in after.diagnostics] == ["duplicate-hole"]
    assert [h.index for h in after.holes] == [6]

    survivor = after.holes[0]
    duplicate = after.diagnostics[0]
    assert duplicate.get("hole_index") is None
    assert duplicate.get("dropped_indices") is None
    assert duplicate.location_nm == (survivor.x_nm, survivor.y_nm)

    root = ET.fromstring(DrawingSvgEmitter().emit(after))
    flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
    assert len(flagged) == 1
    assert len(by_class(root, "dup-ring", "circle")) == 1
    assert [e.text for e in by_class(root, "balloon-no", "text")] == ["6"]


# --------------------------------------------------------------------------
# outline, centrelines, origin
# --------------------------------------------------------------------------


def test_reference_outline_is_a_rounded_rect_at_scale(panel: DrillData):
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(panel))
    layout = emitter.layout(panel)

    outlines = by_class(root, "outline", "rect")
    assert len(outlines) == 1
    rect = outlines[0]
    assert num(rect, "width") == pytest.approx(113.0 * layout.scale)
    assert num(rect, "height") == pytest.approx(60.0 * layout.scale)
    assert num(rect, "rx") > 0


def test_the_reference_outline_is_the_only_outline_drawn(panel: DrillData):
    """One panel, one rectangle."""
    root = ET.fromstring(DrawingSvgEmitter().emit(panel))
    group = by_class(root, "outlines")[0]
    assert [tag(e) for e in group] == ["rect"]
    assert classes(group[0]) == {"outline"}


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
        dashes = [
            float(v)
            for v in re.split(r"[ ,]+", attr_of(line, "stroke-dasharray").strip())
        ]
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
    assert "20.000" in values, "⌀7 row is on a 20 mm pitch"
    assert "38.000" in values, "the two ⌀5 holes are 38 mm apart"


def test_a_chain_dimension_states_the_difference_of_two_hole_positions_exactly():
    """Chain labels use exact model subtraction.

    Out-of-order ids and unequal segments reject position lookup and segment reuse.
    """
    left, middle, right = -9_000_000, -2_125_000, 9_000_000
    data = DrillData(
        holes=(
            Hole.from_measurement(middle, Nanometre(0), Nanometre(3_000_000)).with_number(4),
            Hole.from_measurement(right, Nanometre(0), Nanometre(3_000_000)).with_number(1),
            Hole.from_measurement(left, Nanometre(0), Nanometre(3_000_000)).with_number(9),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    labels = [e.text for e in by_class(root, "dim-text", "text")]
    assert labels == [
        format_nm(middle - left, 3),
        format_nm(right - middle, 3),
    ], "left to right, and each the difference of the two integers"
    assert labels == ["6.875", "11.125"]


def test_a_hole_on_the_panel_edge_is_one_station_and_not_two():
    """A chain runs edge, hole, …, edge — and a hole *at* an edge is that edge."""
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(30_000_000), Nanometre(0), Nanometre(5_000_000)).with_number(7),),
        reference=outline(60_000_000, 40_000_000),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    # Scoped to the row chain: the chain of row levels states its own stations
    # in the same class, and this is a claim about the row's.
    chain = by_class(root, "dim-chain")[0]
    assert [e.text for e in by_class(chain, "dim-text", "text")] == ["60.000"]
    assert len(by_class(chain, "extension", "line")) == 2, "two stations, not three"


def test_a_row_with_one_station_gets_no_chain_at_all():
    """One station is a place, not a distance."""
    data = DrillData(holes=(Hole.from_measurement(Nanometre(3_000_000), Nanometre(4_000_000), Nanometre(5_000_000)).with_number(9),))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert by_class(root, "dim-chain") == []
    assert by_class(root, "dim-text", "text") == []


def test_a_panel_of_one_row_and_no_outline_is_still_dimensioned_across():
    """Height zero must not take the width dimension with it."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(-10_000_000), Nanometre(0), Nanometre(3_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(10_000_000), Nanometre(0), Nanometre(3_000_000)).with_number(1),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    assert [e.text for e in by_class(root, "dim-overall", "text")] == ["20.000"]


def test_a_panel_of_one_column_and_no_outline_is_still_dimensioned_down():
    """A panel of one column and no outline is still dimensioned down."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(-10_000_000), Nanometre(3_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(0), Nanometre(10_000_000), Nanometre(3_000_000)).with_number(1),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    vertical = by_class(root, "dim-overall", "text")
    assert [e.text for e in vertical] == ["20.000"]
    assert "rotate(-90" in (vertical[0].get("transform") or "")


def test_overall_width_and_height_dimensions(panel: DrillData, root: ET.Element):
    overall = {e.text for e in by_class(root, "dim-overall", "text")}
    assert panel.reference is not None
    assert format_nm(panel.reference.width_nm, 3) in overall
    assert format_nm(panel.reference.height_nm, 3) in overall
    assert overall == {"113.000", "60.000"}


def test_the_overall_dimension_is_the_outline_the_model_holds():
    """A footprint of Hammond's 0.05 mm, which two decimals could not have shown."""
    data = numbered(phase(measured(0.0, 0.0), reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
                 enclosure=IdentifyHammondFootprint("1590B")))
    assert data.reference is not None
    assert (data.reference.width_nm, data.reference.height_nm) == (112_400_000, 60_500_000)

    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    overall = {e.text for e in by_class(root, "dim-overall", "text")}
    assert overall == {"112.400", "60.500"}


def test_one_chain_of_row_levels_states_the_y_the_row_chains_never_do(
    panel: DrillData, root: ET.Element
):
    """Every row shares one Y, so one chain gives the height of every hole.

    The row chains run left to right and say nothing about how far up the panel
    a row sits; without this chain that distance is on no sheet at all.
    """
    chains = by_class(root, "dim-chain-y")
    assert len(chains) == 1, "one chain of levels, however many rows or columns"

    assert panel.reference is not None
    assert [e.text for e in by_class(chains[0], "dim-text", "text")] == [
        "11.250",  # bottom edge up to the -18.750 row
        "36.750",  # that row up to the 18.000 one
        "12.000",  # and on to the top edge
    ]
    # Four stations, four extension lines: two rows and the outline's own edges.
    assert len(by_class(chains[0], "extension", "line")) == 4


def test_the_chain_of_row_levels_reads_bottom_to_top(root: ET.Element):
    """ISO 129-1: a vertical dimension is read from the right of the sheet."""
    labels = by_class(by_class(root, "dim-chain-y")[0], "dim-text", "text")

    assert labels
    assert all("rotate(-90" in (e.get("transform") or "") for e in labels)


def test_the_chain_of_row_levels_stands_clear_of_the_panel_and_its_balloons(
    root: ET.Element,
):
    """It is drawn outboard of everything, so nothing it crosses is its own."""
    chain = by_class(root, "dim-chain-y")[0]
    dimension = by_class(chain, "dim-line", "line")
    assert dimension

    outline = by_class(root, "outline", "rect")[0]
    panel_right = num(outline, "x") + num(outline, "width")
    balloons = by_class(root, "balloon", "circle")
    reach = max(num(b, "cx") + num(b, "r") for b in balloons)

    assert reach < panel_right, "this fixture keeps every balloon inside the panel"
    assert all(num(line, "x1") > panel_right for line in dimension)


def test_vertical_dimension_text_is_rotated(root: ET.Element):
    vertical = [
        e
        for e in by_class(root, "dim-overall", "text")
        if e.text == "60.000"
    ]
    assert vertical
    assert all("rotate(-90" in (e.get("transform") or "") for e in vertical)


def _rows_of_five(count: int) -> DrillData:
    """``count`` rows of five holes, spread down a 112.40 × 60.50 panel.

    Each row is stepped 0.2 mm along X so no two share a pattern of stations:
    rows drilled alike share one chain, and a panel of identical rows would
    stack one chain deep however many rows it had.
    """
    pitch_nm = 56_000_000 // (count - 1) if count > 1 else 0
    return DrillData(
        holes=tuple(
            Hole.from_measurement(
                Nanometre(-40_000_000 + 20_000_000 * column + 200_000 * row),
                Nanometre(28_000_000 - pitch_nm * row),
                Nanometre(3_000_000)).with_number(500 - (row * 5 + column))
            for row in range(count)
            for column in range(5)
        ),
        reference=outline(112_400_000, 60_500_000),
    )


@pytest.mark.parametrize("rows", [5, 14, 15, 30])
def test_every_dimension_stays_inside_the_drawing_area(rows: int):
    """All row dimensions stay inside the drawing area.

    Counts 14 and 15 straddle capacity; 30 exercises overflow.
    """
    data = _rows_of_five(rows)
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert len(data.rows()) == rows
    assert_within(emitter.layout(data).area, by_class(root, "dimensions")[0], "the drawing area")


def test_the_drawing_says_how_many_dimension_chains_it_could_not_draw():
    """A hole with no dimension beside it is a hole nobody can locate.

    Same rule as the notes and the schedule: a fact that disappears without
    trace is worse than one that is visibly missing. The count is of chains,
    not rows: rows drilled to one pattern share a chain, so this fixture steps
    each row along X to keep the two numbers the same.
    """
    data = _rows_of_five(30)
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    chains = by_class(root, "dim-chain")
    marker = by_class(root, "dim-overflow", "text")

    assert len(chains) < 30, "this test only means anything if chains are dropped"
    assert len(marker) == 1, "truncation must be announced exactly once"
    omitted = int(re.search(r"(\d+)", marker[0].text or "").group(1))
    assert len(chains) + omitted == 30


def test_a_panel_whose_rows_all_fit_carries_no_dimension_marker(root: ET.Element):
    assert by_class(root, "dim-overflow", "text") == []


# --------------------------------------------------------------------------
# hole schedule
# --------------------------------------------------------------------------


def test_schedule_has_one_row_per_hole(panel: DrillData, root: ET.Element):
    assert len(by_class(root, "sched-row")) == len(panel.holes)


def test_schedule_columns_are_no_x_y_diameter_tool(root: ET.Element):
    headers = [text_of(e) for e in by_class(root, "sched-head", "text")]
    assert headers[0].upper().startswith("NO")
    assert [h.upper() for h in headers[1:3]] == ["X", "Y"]
    assert "⌀" in headers[3]
    assert headers[4].upper() == "TOOL"


def test_schedule_cells_carry_the_hole_data(panel: DrillData, root: ET.Element):
    rows = by_class(root, "sched-row")
    for hole, row in zip(panel.holes, rows):
        cells = {
            cls: e.text
            for e in walk(row, "text")
            for cls in classes(e)
            if cls.startswith("sched-") and cls != "sched-row"
        }
        assert cells["sched-no"] == str(hole.index)
        # The cell against ``format_nm`` of the integer the model holds, not
        # against a float the test worked out: a second rendering here would
        # agree with a second rendering in the emitter and prove nothing.
        assert cells["sched-x"] == format_nm(hole.x_nm, 3)
        assert cells["sched-y"] == format_nm(hole.y_nm, 3)
        # The whole cell, not a number parsed out of it: the units are part of
        # what the column says, and a fractional standard spells the same column
        # ``⌀9/32"``.
        assert cells["sched-dia"] == f"⌀{format_nm(hole.diameter_nm, 2)} mm"


def test_a_schedule_cell_states_a_position_the_micron_apart():
    """Three decimals, because a micron is the finest grid the pipeline allows."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(-9_000_000), Nanometre(18_000_000), Nanometre(3_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(9_000_000), Nanometre(18_001_000), Nanometre(3_000_000)).with_number(1),
        ),
        reference=outline(60_000_000, 40_000_000),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    ys = [e.text for e in by_class(root, "sched-y", "text")]
    assert ys == ["18.000", "18.001"]
    assert len(set(ys)) == 2, "two positions the model holds apart print apart"


def test_schedule_tool_numbers_come_from_drilldata_tools(panel: DrillData, root: ET.Element):
    tools = panel.tools()
    rows = by_class(root, "sched-row")
    for hole, row in zip(panel.holes, rows):
        cell = by_class(row, "sched-tool", "text")[0]
        assert text_of(cell).lstrip("T") == str(tools[hole.diameter_nm])

    used = {
        int(text_of(by_class(r, "sched-tool", "text")[0]).lstrip("T")) for r in rows
    }
    assert used == set(tools.values())


def test_schedule_never_prints_a_negative_zero():
    """One hole, two artefacts, one number."""
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(-400), Nanometre(-400), Nanometre(5_000_000)).with_number(1),),
        reference=outline(60_000_000, 40_000_000),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    row = by_class(root, "sched-row")[0]

    assert by_class(row, "sched-x", "text")[0].text == "0.000"
    assert by_class(row, "sched-y", "text")[0].text == "0.000"


def test_schedule_has_a_per_tool_summary_with_quantities(root: ET.Element):
    summary = [text_of(e) for e in by_class(root, "sched-summary", "text")]
    assert len(summary) == 2
    joined = " | ".join(summary)
    assert "T1" in joined and "T2" in joined
    assert "5.00" in joined and "7.00" in joined
    assert "2" in summary[0] and "5" in summary[1]  # quantities, ascending by size


def test_the_summary_quantities_are_the_models_tool_counts(panel: DrillData, root: ET.Element):
    """``QTY`` is read off ``tool_counts()``, never counted again here."""
    counts = panel.tool_counts()
    tools = panel.tools()
    assert sorted(counts.values()) == [2, 5], "the fixture must have two unequal counts"

    summary = [e.text or "" for e in by_class(root, "sched-summary", "text")]
    assert summary == [
        f"T{tools[diameter_nm]}  ⌀{format_nm(diameter_nm, 2)} mm  QTY {quantity}"
        for diameter_nm, quantity in counts.items()
    ]


def _two_size_panel() -> DrillData:
    """Three holes, two sizes, ids that are not positions — the sheet in
    miniature, small enough that a stubbed answer is legible in every cell."""
    return DrillData(
        holes=(
            at(-20_000_000, 18_000_000, 7_000_000, index=12),
            at(20_000_000, 18_000_000, 7_000_000, index=5),
            at(0, -18_000_000, 5_000_000, index=9),
        ),
        reference=outline(113_000_000, 60_000_000),
    )


def test_the_schedule_tool_numbers_are_read_from_the_model_and_not_re_derived(monkeypatch):
    """The numbering is looked up, not recomputed to agree."""
    data = _two_size_panel()
    monkeypatch.setattr(DrillData, "tools", lambda self: {7_000_000: 4, 5_000_000: 9})

    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [e.text for e in by_class(root, "sched-tool", "text")] == ["T4", "T4", "T9"]
    assert [e.text for e in by_class(root, "sched-summary", "text")] == [
        "T4  ⌀7.00 mm  QTY 2",
        "T9  ⌀5.00 mm  QTY 1",
    ]


def test_the_summary_quantities_are_read_from_the_model_and_not_recounted(monkeypatch):
    """``QTY`` is ``tool_counts()``'s answer, not this emitter's tally."""
    data = _two_size_panel()
    monkeypatch.setattr(DrillData, "tool_counts", lambda self: {5_000_000: 90, 7_000_000: 40})

    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [e.text for e in by_class(root, "sched-summary", "text")] == [
        "T1  ⌀5.00 mm  QTY 90",
        "T2  ⌀7.00 mm  QTY 40",
    ]


def _sched_diameters(root: ET.Element) -> list[str]:
    return [e.text or "" for e in by_class(root, "sched-dia", "text")]


def test_schedule_diameters_are_spelled_the_way_the_drill_standard_spells_them():
    """A fractional bit's honest name is its fraction, and the standard knows it."""
    after = numbered(phase(
        measured(-20.0, 0.0, 3.18),
        measured(20.0, 0.0, 7.13),
        diameters=SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]),
    ))
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    assert _sched_diameters(root) == ['⌀1/8"', '⌀9/32"']
    summary = " | ".join(e.text or "" for e in by_class(root, "sched-summary", "text"))
    assert '⌀1/8"' in summary and '⌀9/32"' in summary


def test_schedule_diameters_use_the_standard_that_actually_ran():
    """A second standard, so the first test cannot be passing on a constant."""
    after = numbered(phase(
        measured(-20.0, 0.0, 3.18),
        measured(20.0, 0.0, 7.13),
        diameters=SnapDiametersToDrillTable(DRILL_STANDARDS["metric"]),
    ))
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    assert _sched_diameters(root) == ["⌀3.20 mm", "⌀7.10 mm"]


def test_schedule_diameters_fall_back_to_millimetres_when_no_standard_was_recorded():
    """A hand-built ``DrillData`` never met the drill table. Nothing to look up."""
    data = make_data(*holes((0, 0, 7_000_000)))
    assert data.last_run("snap-diameters") is None
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert _sched_diameters(root) == ["⌀7.00 mm"]


@pytest.mark.parametrize("recorded", ["gauge", "", True, 3.0, (3.0, 5.0)])
def test_a_recorded_standard_that_does_not_resolve_is_not_a_standard(recorded):
    """``StageRun`` payloads are generic; a name is only a name until it resolves."""
    data = make_data(*holes((0, 0, 7_000_000))).with_processing(
        StageRun("snap-diameters", (("standard", recorded), ("size_count", 80)))
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert _sched_diameters(root) == ["⌀7.00 mm"]


def test_the_diameter_column_does_not_promise_millimetres_it_cannot_keep():
    """The heading carried ``mm`` while the rows can carry inch fractions."""
    after = numbered(phase(
        measured(0.0, 0.0, 3.18),
        diameters=SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]),
    ))
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    headers = [text_of(e) for e in by_class(root, "sched-head", "text")]
    assert headers[3] == "⌀"
    assert _sched_diameters(root) == ['⌀1/8"']


# --------------------------------------------------------------------------
# title block
# --------------------------------------------------------------------------


def _title_block_lines(root: ET.Element) -> list[str]:
    """Return title-block text in sheet order, excluding dimension labels."""
    groups = by_class(root, "title-block-group")
    assert len(groups) == 1, "expected exactly one title block"
    return [(e.text or "") for e in walk(groups[0], "text")]


def _title_block_text(root: ET.Element) -> str:
    """The title block's strings joined, for assertions about a fragment."""
    return "\n".join(_title_block_lines(root))


def test_title_block_carries_the_required_fields(panel: DrillData):
    emitter = DrawingSvgEmitter(DrawingOptions(title="TAR PANEL", drawing_no="AI-0001"))
    root = ET.fromstring(emitter.emit(panel))
    text = _title_block_text(root)
    assert by_class(root, "title-block", "rect")
    assert "ARTIFACT" in text.upper()
    assert "TAR PANEL" in text
    assert "AI-0001" in text
    assert "SHEET" in text.upper()
    assert "mm" in text
    assert "PROJECTION" in text.upper()
    assert "tar.ai" in text


def test_the_title_block_states_the_grid_the_holes_were_actually_snapped_to():
    """The pitch printed on the sheet is read out of the run that did the work."""
    after = numbered(phase(measured(10.03, 5.02), positions=SnapPositions(Nanometre(500_000))))
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID 0.500 mm" in text


def test_the_title_block_states_a_grid_of_0_1_when_that_is_what_ran():
    """A second pitch, so the first test cannot be passing on a constant."""
    after = numbered(phase(measured(10.03, 5.02), positions=SnapPositions(Nanometre(100_000))))
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID 0.100 mm" in text
    # Scoped to the grid line: the title block also carries SCALE, so a bare
    # substring check would be pinned to layout fitting rather than to the grid.
    assert "GRID 0.500 mm" not in text and "GRID 0.250 mm" not in text


def test_the_title_block_states_the_effective_pitch_not_the_one_that_was_asked_for():
    """A pitch below the micron floor is clamped, and the sheet says the clamp."""
    after = numbered(phase(measured(10.03, 5.02), positions=SnapPositions(Nanometre(100))))
    assert [d.code for d in after.diagnostics] == ["grid-too-fine"]

    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID 0.001 mm" in text
    assert "0.0001" not in text


def test_the_title_block_does_not_invent_a_grid_when_none_was_recorded():
    """A hand-built ``DrillData`` never met the quantisation phase. 0.25 would be a lie."""
    data = make_data(*holes((0, 0)))
    assert data.processing == ()
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text
    assert "0.25" not in text


def test_a_snap_run_that_recorded_no_pitch_at_all_is_not_a_grid():
    """A record can exist and still not answer the question."""
    data = make_data(*holes((0, 0))).with_processing(StageRun("snap", ()))
    assert data.last_run("snap") is not None
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text


@pytest.mark.parametrize("recorded", [(250_000, 500_000), 0, -250_000])
def test_a_recorded_grid_that_is_not_a_single_positive_pitch_is_not_a_grid(recorded):
    """``StageRun`` payloads are generic, and an ``_nm`` key admits a *tuple*."""
    data = make_data(*holes((0, 0))).with_processing(
        StageRun("snap", (("grid_nm", recorded),))
    )
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text
    assert "0.250" not in text and "0.000" not in text


# -- the enclosure the panel was identified as ------------------------------


def _identified(
    *,
    length_nm: Nanometre = Nanometre(112_400_000),
    width_nm: Nanometre = Nanometre(60_500_000),
    candidates: tuple[str, ...] = ("1590B", "1590B2"),
    rotated: bool = False,
    selected_part: str | None = None,
    reference: ReferenceOutline | None = None,
) -> DrillData:
    """A panel whose *measured* outline is not its *catalogue* footprint."""
    return DrillData(
        holes=holes((0, 0)),
        reference=reference if reference is not None else outline(113_000_000, 60_000_000),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=length_nm,
            width_nm=width_nm,
            candidates=candidates,
            rotated=rotated,
            selected_part=selected_part,
        ),
    )


def test_the_title_block_states_the_enclosure_the_pipeline_identified():
    """Straight off a real run: outline in, footprint on the sheet."""
    after = numbered(phase(measured(10.0, 5.0), reference=RawOutline(Millimetre(119.6), Millimetre(94.1))))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "HAMMOND 1590  119.50 × 94.00 mm  CANDIDATES BB / BB2 / BBS / C" in lines


def test_the_enclosure_line_states_the_catalogue_footprint_not_the_measured_outline():
    """112.40 × 60.50 is what the case is; 113.000 × 60.000 is what the artwork came to."""
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(_identified())))
    assert "HAMMOND 1590  112.40 × 60.50 mm  CANDIDATES B / B2" in lines
    assert not [line for line in lines if "113.000" in line or "60.000" in line]


def test_the_enclosure_line_renders_the_candidates_in_the_order_it_was_handed():
    """Render enclosure candidates in caller order.

    Opposing input and lexical orders ensure re-sorting cannot pass.
    """
    data = _identified(candidates=("1590BS", "1590B", "1590B2"))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112.40 × 60.50 mm  CANDIDATES BS / B / B2" in lines


def test_a_candidate_that_does_not_carry_the_series_is_printed_whole():
    """``1590B`` under a ``HAMMOND 1590`` heading is that series' ``B``."""
    data = _identified(candidates=("1590B", "1590", "PB-61"))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112.40 × 60.50 mm  CANDIDATES B / 1590 / PB-61" in lines


def test_the_enclosure_line_names_the_one_part_when_the_operator_declared_one():
    """``--case`` is the only thing that can ever narrow a footprint to a part.

    The declared part replaces the candidate list rather than joining it: the
    operator has answered the question the list was asking.
    """
    data = _identified(selected_part="1590B")
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112.40 × 60.50 mm  PART 1590B" in lines


def test_the_declared_case_reaches_the_sheet_from_a_real_run():
    """``--case 1590B`` is what resolves the fixture panel's own ambiguity."""
    after = numbered(phase(
        measured(10.0, 5.0),
        reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        enclosure=IdentifyHammondFootprint("1590B"),
    ))
    assert after.diagnostics == ()
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "HAMMOND 1590  112.40 × 60.50 mm  PART 1590B" in lines


def test_the_enclosure_line_does_not_name_a_part_when_none_was_declared():
    """``selected_part`` is ``None`` on every run that did not declare a case."""
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(_identified())))
    assert "HAMMOND 1590  112.40 × 60.50 mm  CANDIDATES B / B2" in lines
    assert not [line for line in lines if "PART" in line]


def test_the_enclosure_line_says_the_panel_is_turned_when_it_is():
    """The match keeps the catalogue's orientation; the artwork keeps its own."""
    data = _identified(rotated=True, reference=outline(60_500_000, 112_400_000))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112.40 × 60.50 mm ROTATED  CANDIDATES B / B2" in lines


def test_a_rotated_panel_keeps_every_candidate_in_the_title_block():
    """A rotated panel keeps every candidate in the title block."""
    data = numbered(phase(measured(0.0, 0.0), reference=RawOutline(Millimetre(94.1), Millimetre(119.6))))
    assert data.enclosure is not None
    assert data.enclosure.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")

    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert (
        "HAMMOND 1590  119.50 × 94.00 mm ROTATED  CANDIDATES BB / BB2 / BBS / C" in lines
    )


def test_a_candidate_list_that_cannot_fit_says_how_many_it_dropped():
    """Beyond shrinking, the line still has to end somewhere — honestly."""
    candidates = tuple(
        f"1590{suffix}"
        for suffix in ("B", "B2", "BS", "BB", "BB2", "BBS", "C", "D", "N1", "P", "Q", "R")
    )
    data = _identified(candidates=candidates)
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))

    line = next(line for line in lines if "CANDIDATES" in line)
    assert "…" not in line, "an ellipsis names no number"
    dropped = int(re.search(r"\+(\d+) MORE", line).group(1))
    listed = line.split("CANDIDATES ")[1].split(" / +")[0].split(" / ")
    assert len(listed) + dropped == len(candidates)
    assert listed[0] == "B"


def test_the_title_block_says_so_when_no_enclosure_was_identified():
    """No match, or no reference layer at all: the sheet says which, honestly."""
    data = make_data(*holes((0, 0)), reference=outline(200_000_000, 33_000_000))
    assert data.enclosure is None
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "ENCLOSURE NOT IDENTIFIED" in lines
    assert not [line for line in lines if "HAMMOND" in line.upper()]


def test_a_panel_that_matches_nothing_still_says_so_after_a_real_run():
    """The warning path end to end: ``unknown-enclosure`` leaves the field unset.

    The hand-built case above cannot prove the quantiser leaves it unset — only
    that the emitter reads it — so the two tests are not one test twice.
    """
    after = numbered(phase(measured(0.0, 0.0), reference=RawOutline(Millimetre(200.0), Millimetre(33.0))))
    assert [d.code for d in after.diagnostics] == ["unknown-enclosure"]
    assert "ENCLOSURE NOT IDENTIFIED" in _title_block_lines(
        ET.fromstring(DrawingSvgEmitter().emit(after))
    )


def test_a_line_too_long_even_at_the_smallest_font_is_still_truncated():
    """Shrinking buys width; it does not buy an unlimited amount of it."""
    emitter = DrawingSvgEmitter(DrawingOptions(title="PANEL " * 40))
    root = ET.fromstring(emitter.emit(_identified()))

    line = next(line for line in _title_block_lines(root) if line.startswith("TITLE"))
    assert line.endswith("…")
    assert_within(emitter.layout(_identified()).title_block, by_class(root, "title-block-group")[0],
                  "the title block")


def test_title_block_reports_the_scale(panel: DrillData):
    emitter = DrawingSvgEmitter(DrawingOptions(scale=0.5))
    root = ET.fromstring(emitter.emit(panel))
    assert "1:2" in all_text(root)
    assert emitter.layout(panel).scale == 0.5


def test_only_drill_data_is_drawn_never_the_artwork(panel: DrillData, root: ET.Element):
    """This is a drawing *of the drill data*, not a render of the panel artwork."""
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
    notes = [text_of(e) for e in by_class(root, "note", "text")]
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
    assert "something is very wrong" in "\n".join(text_of(e) for e in errors)
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
        Hole.from_measurement(
            Nanometre(-40_000_000 + 2_000_000 * i),
            Nanometre(0),
            Nanometre(3_000_000)).with_number(i + 1)
        for i in range(count)
    )
    return DrillData(
        holes=drilled,
        reference=outline(113_000_000, 60_000_000),
        diagnostics=tuple(
            Diagnostic.warning(
                "off-grid",
                "a hole moved 0.120 mm to reach the 0.250 mm grid",
                location_nm=(-40_000_000 + 2_000_000 * i, 0),
                data=(("moved_nm", 120_000), ("grid_nm", 250_000)),
            )
            for i in range(count)
        ),
    )


def test_notes_that_do_not_fit_say_how_many_were_left_off():
    """A note that silently vanishes is worse than one that is visibly missing."""
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
    """Schedule overflow reports the exact number of omitted holes."""
    drilled = tuple(
        Hole.from_measurement(
            -55_000_000 + 500_000 * i, 20_000_000 - 400_000 * (i // 40), Nanometre(3_000_000)).with_number(i + 1)
        for i in range(240)
    )
    data = DrillData(holes=drilled, reference=outline(120_000_000, 60_000_000))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    listed = by_class(root, "sched-row")
    overflow = by_class(root, "sched-overflow", "text")

    assert len(listed) < 240, "this test only means anything if rows are truncated"
    assert len(overflow) == 1
    omitted = int(re.search(r"(\d+)", overflow[0].text or "").group(1))
    assert len(listed) + omitted == 240


def _every_hole_a_different_size(count: int) -> DrillData:
    """``count`` holes, no two the same diameter, so the tool table is as long as the
    schedule itself.
    """
    return DrillData(
        holes=tuple(
            Hole.from_measurement(
                Nanometre(-50_000_000 + 800_000 * i),
                Nanometre(20_000_000),
                Nanometre(3_000_000 + 100_000 * i)).with_number(count - i)
            for i in range(count)
        ),
        reference=outline(112_400_000, 60_500_000),
    )


@pytest.mark.parametrize("tools", [2, 83, 120])
def test_every_element_of_the_schedule_stays_inside_its_box(tools: int):
    """Every schedule element stays inside its box across capacity boundaries.

    Counts 2, 83 and 120 exercise compact, boundary and heavily truncated layouts.
    """
    data = _every_hole_a_different_size(tools)
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert_within(emitter.layout(data).schedule, by_class(root, "schedule")[0], "the schedule box")


def test_the_schedule_says_how_many_tools_it_could_not_list():
    """A tool the sheet does not name is a bit the machinist does not fit."""
    data = _every_hole_a_different_size(120)
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    listed = by_class(root, "sched-summary", "text")
    marker = by_class(root, "sched-tool-overflow", "text")

    assert len(listed) < 120, "this test only means anything if the summary is truncated"
    assert len(data.tools()) == 120, "the drill file defines all 120"
    assert len(marker) == 1, "truncation must be announced exactly once"

    text = marker[0].text or ""
    omitted = int(re.search(r"(\d+)", text).group(1))
    assert len(listed) + omitted == 120
    assert "tool" in text.lower(), f"the marker must name what was dropped, got {text!r}"
    assert "hole" not in text.lower(), "a dropped tool is not a dropped hole"


def test_a_schedule_that_fits_carries_neither_overflow_marker(root: ET.Element):
    assert by_class(root, "sched-overflow", "text") == []
    assert by_class(root, "sched-tool-overflow", "text") == []


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

    # The outline is the widest thing on this panel, so it is what the fitted
    # scale has to be fitted around. Leave it out of the extents and the sheet
    # is scaled to the holes, with the rectangle drawn past the drawing area.
    assert panel.reference is not None
    assert layout.half_width == pytest.approx(mm_from_nm(panel.reference.width_nm) / 2)
    assert layout.half_height == pytest.approx(mm_from_nm(panel.reference.height_nm) / 2)


def test_scale_none_fits_a_panel_far_bigger_than_the_sheet(panel: DrillData):
    big = panel.with_holes(
        holes(
            *(
                (x, y, 12_000_000)
                for x in (-400_000_000, 0, 400_000_000)
                for y in (-200_000_000, 200_000_000)
            )
        )
    )
    big = DrillData(
        holes=big.holes,
        reference=outline(900_000_000, 500_000_000),
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
    half_nm = width * 500_000 - 6_000_000
    data = DrillData(
        holes=holes(
            *(
                (x, y, 6_000_000)
                for x in (-half_nm, 0, half_nm)
                for y in (12_000_000, -12_000_000)
            )
        ),
        # a seven-character height label is the widest thing on the left-hand side
        reference=outline(width * 1_000_000, 100_250_000),
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
    rect = by_class(root, "outline", "rect")[0]
    assert num(rect, "width") == pytest.approx(226.0)


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
    data = DrillData(holes=(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(3_000_000)).with_number(1),))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    assert len(by_class(root, "hole", "circle")) == 1
    assert by_class(root, "outline", "rect") == []


def test_single_hole_does_not_divide_by_zero():
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(3_000_000), Nanometre(4_000_000), Nanometre(5_000_000)).with_number(1),),
        reference=outline(50_000_000, 40_000_000),
    )
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert len(by_class(root, "hole", "circle")) == 1
    assert emitter.layout(data).scale > 0


def test_a_sheet_with_no_room_for_a_title_block_says_nothing_rather_than_guessing():
    """A 10 mm square sheet leaves the title block a negative width."""
    data = _identified()
    emitter = DrawingSvgEmitter(DrawingOptions(sheet=Sheet("mini", 10.0, 10.0)))
    root = ET.fromstring(emitter.emit(data))

    assert emitter.layout(data).title_block[2] - emitter.layout(data).title_block[0] < 4.0
    assert _title_block_lines(root) == [""] * len(_title_block_lines(root))
    assert "HAMMOND" not in all_text(root)


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
        Hole.from_measurement(
            -50_000_000 + 5_000_000 * i, 20_000_000 - 4_000_000 * (i // 20), Nanometre(3_000_000)).with_number(i + 1)
        for i in range(60)
    )
    data = DrillData(holes=drilled, reference=outline(120_000_000, 60_000_000))
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
