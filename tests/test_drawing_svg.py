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
from dataclasses import fields

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
    EnclosureMatch,
    Hole,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.pipeline import (
    DRILL_STANDARDS,
    Deduplicate,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from aidrill.protocols import Emitter, Pipeline
from tests.conftest import at, holes, make_data

SVG_NS = "http://www.w3.org/2000/svg"

# The test's own estimate of glyph advance, deliberately independent of the
# emitter's (which is more conservative) so the overflow test can actually fail.
CHAR_W = 0.6


# --------------------------------------------------------------------------
# fixtures — the SPEC §9 panel (tar.ai), post-pipeline
# --------------------------------------------------------------------------


def _panel() -> DrillData:
    """The SPEC §9 panel, post-pipeline.

    The hole ids are deliberately neither sequential nor in position order. A
    fixture numbered 0, 1, 2… makes ``hole.index`` indistinguishable from the
    hole's place in the tuple, so an emitter that flagged the wrong one of the
    two would still look right. Here the flagged hole is id 12, which is not a
    position at all.
    """
    return DrillData(
        holes=(
            at(-40.0, 18.0, index=12),
            at(-20.0, 18.0, index=5),
            at(0.0, 18.0, index=9),
            at(20.0, 18.0, index=3),
            at(40.0, 18.0, index=11),
            at(-19.0, -18.75, 5.0, index=7),
            at(19.0, -18.75, 5.0, index=1),
        ),
        reference=ReferenceOutline(113.0, 60.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (-40.000, 18.000) within 0.05 mm; "
                "kept 1, dropped 1",
                location=(-40.0, 18.0),
                data=(("hole_index", 12), ("diameter", 7.0), ("dropped", 1)),
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


def extents(root: ET.Element) -> list[tuple[str, float, float, float, float]]:
    """Every drawn thing's estimated box, as ``(what, x0, y0, x1, y1)``.

    ``drawn_points`` and ``text_box`` each cover half the sheet, and a
    containment claim that consults only one of them is half a claim: the tool
    summary that ran off the bottom of the schedule box was text, and the chain
    dimensions that ran off the drawing area were lines. ``what`` carries the
    element's own text or tag so a failure names the thing that escaped.
    """
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


def test_default_options_match_the_spec_signature():
    options = DrawingOptions()
    assert options.sheet == A4_LANDSCAPE
    assert options.scale is None
    assert options.title == ""
    assert options.drawing_no == ""


def test_the_options_carry_no_true_size_of_their_own():
    """The overlay is gone, and with it the only thing that drew a second outline.

    On a successful match the dashed rectangle sat exactly on the normalised
    reference — two identical outlines, one of them claiming to be a check on
    the other. On a mismatch the facts worth having are which enclosure was
    asked for and which one the artwork is, and those are now the title block's
    enclosure line and a ``wrong-enclosure`` note, neither of which needs the
    operator to retype a datasheet.
    """
    assert "true_size" not in {f.name for f in fields(DrawingOptions)}
    with pytest.raises(TypeError):
        DrawingOptions(true_size=(112.0, 61.0))


def test_the_options_carry_no_grid_of_their_own():
    """The grid is a pipeline fact, and a second copy is a second answer.

    A library consumer who snaps at 0.5 and calls ``DrawingSvgEmitter().emit``
    got a sheet stamped 0.25, because the option defaulted rather than asking
    the data. There is nowhere to pass a grid now; the drawing reads the one the
    holes were actually snapped to.
    """
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
    assert numbers == sorted(hole.index for hole in panel.holes)


def test_balloons_number_holes_by_identity_not_by_position(panel: DrillData, root: ET.Element):
    """One number, one hole, across all four artifacts.

    The balloons counted 1..n down the tuple while the JSON and every
    diagnostic used ``Hole.index``, so "hole 2" named the duplicate at
    (−40, 18) to one reader, the clean hole at (−20, 18) to another, and a
    third hole to anyone indexing the array. Gaps in the numbering are the
    point: an id missing from the sheet is a hole the pipeline dropped.
    """
    balloons = [int(e.text) for e in by_class(root, "balloon-no", "text")]
    assert balloons == [hole.index for hole in panel.holes]
    assert balloons != list(range(1, len(panel.holes) + 1)), (
        "the fixture's ids must not coincide with its positions, or this proves nothing"
    )


def test_the_sheet_numbers_the_flagged_hole_the_way_the_diagnostic_does(
    panel: DrillData, root: ET.Element
):
    """The one place the two numbering schemes can be caught disagreeing.

    ``duplicate-hole`` names hole 12. Under positional numbering the schedule
    called that same hole 1, and the sheet and the report described the panel in
    two incompatible languages.
    """
    duplicate = next(d for d in panel.diagnostics if d.code == "duplicate-hole")
    named = str(duplicate.get("hole_index"))

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
    """Post-``Deduplicate(0.05)`` state of ⌀7 @ (0,0), ⌀7 @ (0,0), ⌀5 @ (0.03,0).

    ``Deduplicate`` collapses on proximity **and** equal diameter, so it keeps
    the ⌀7 at (0, 0) and the ⌀5 at (0.03, 0), and raises one ``duplicate-hole``
    naming the survivor by its id, 4.
    """
    return DrillData(
        holes=(
            Hole.from_measurement(0.0, 0.0, 7.0, index=4),
            Hole.from_measurement(0.03, 0.0, 5.0, index=2),
        ),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (0.000, 0.000) within 0.05 mm; "
                "kept 1, dropped 1",
                location=(0.0, 0.0),
                data=(("hole_index", 4), ("diameter", 7.0), ("dropped", 1)),
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
    assert red_rows == ["⌀7.00 mm"], "only the ⌀7 hole is a duplicate in the schedule"


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


def test_the_flagged_hole_is_the_one_the_diagnostic_names_not_the_one_beside_it():
    """Identity decides, and ``location`` is human context the emitter ignores.

    The diagnostic names hole 8, which sits 20 mm away; hole 3 sits 0.001 mm
    from ``location`` and is not the hole the pipeline kept. An emitter matching
    on coordinates rings hole 3 — or, once a later stage has moved the survivor,
    rings nothing at all. Both are the sheet disagreeing with the pipeline.
    """
    data = DrillData(
        holes=(
            Hole.from_measurement(0.001, 0.0, 7.0, index=3),
            Hole.from_measurement(20.0, 0.0, 7.0, index=8),
        ),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (0.000, 0.000)",
                location=(0.0, 0.0),
                data=(("hole_index", 8), ("diameter", 7.0), ("dropped", 1)),
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


def _one_hole_with_a_duplicate_diagnostic(payload) -> DrillData:
    """Two ⌀7 holes, ids 3 and 0, and a ``duplicate-hole`` carrying ``payload``.

    Id 0 is in the panel deliberately. A payload that names no hole must ring
    nothing, and the obvious way to break that is a lookup that falls back to a
    default — ``d.get("hole_index", 0)`` — which a panel numbered from 3 upwards
    would absorb in silence. The hole that would then light up is here.
    """
    return DrillData(
        holes=(
            Hole.from_measurement(0.0, 0.0, 7.0, index=3),
            Hole.from_measurement(20.0, 10.0, 7.0, index=0),
        ),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7 mm holes at (0.000, 0.000)",
                location=(0.0, 0.0),
                data=payload,
            ),
        ),
    )


def test_a_duplicate_hole_diagnostic_without_an_id_flags_nothing():
    """No id, no ring — and emphatically no guess from the coordinates.

    A payload naming no hole is a finding this emitter cannot place. The NOTES
    block still carries the warning, so nothing is lost silently; what must not
    happen is the sheet ringing a hole the pipeline never named.
    """
    data = _one_hole_with_a_duplicate_diagnostic((("diameter", 7.0), ("dropped", 1)))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []
    assert "coincident" in all_text(root)  # the finding still reaches the sheet


def test_a_finding_that_is_not_a_duplicate_rings_no_hole():
    """The ring means *duplicate*, so the code is what selects it.

    ``hole_index`` is carried by other findings too — ``unknown-diameter``
    already does — and dropping the code clause turns every one of them into a
    duplicate ring on a hole that is nothing of the sort. The CLI withholds
    artifacts on an ERROR, so the guard is masked there; a library consumer
    calling ``emit`` on the ``DrillData`` it was handed has no such cover, and
    CLAUDE.md's "match on ``code``, never on ``message``" exists for exactly
    this clause.
    """
    data = DrillData(
        holes=(at(0.0, 0.0, 7.0, index=3),),
        reference=ReferenceOutline(60.0, 40.0),
        diagnostics=(
            Diagnostic.error(
                "unknown-diameter",
                "no metric drill size within 0.15 mm of ⌀7.13 mm; hole dropped",
                location=(0.0, 0.0),
                data=(("hole_index", 3), ("diameter", 7.13)),
            ),
        ),
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)] == []
    assert by_class(root, "dup-ring", "circle") == []
    assert by_class(root, "hole", "circle")[0].get("stroke") == "#111111"
    assert "no metric drill size" in all_text(root)  # the finding still reaches the sheet


def test_an_id_that_arrived_as_a_float_still_rings_its_hole():
    """3.0 is hole 3. Being strict about the type would drop the ring in silence.

    ``Diagnostic.data`` is a generic payload and a round trip through a document
    format is entitled to hand back 3.0 where 3 went in. The lookup is by value,
    so it costs nothing to accept — and the whole point of this task is that a
    ring must not vanish without anything failing.
    """
    data = _one_hole_with_a_duplicate_diagnostic((("hole_index", 3.0), ("diameter", 7.0)))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert len([c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]) == 1
    assert len(by_class(root, "dup-ring", "circle")) == 1


def test_duplicates_are_highlighted_whatever_order_the_pipeline_ran_in():
    """``protocols.py`` fixes no stage order, so neither may the drawing.

    ``Deduplicate`` writes the survivor's coordinates into ``location`` at the
    moment it reports. Snap the panel afterwards and the survivor moves, so an
    emitter matching on coordinates ringed nothing — while the CLI report and
    the JSON still said "duplicate". The ring vanished from the one artifact a
    machinist actually reads.
    """
    data = make_data(at(10.03, 5.02, index=6), at(10.04, 5.02, index=2))
    for pipeline in (
        Pipeline([SnapPositions(grid=0.25), Deduplicate(tolerance=0.05)]),
        Pipeline([Deduplicate(tolerance=0.05), SnapPositions(grid=0.25)]),
    ):
        after = pipeline.run(data)
        assert [d.code for d in after.diagnostics] == ["duplicate-hole"], pipeline
        assert [h.index for h in after.holes] == [6], pipeline

        root = ET.fromstring(DrawingSvgEmitter().emit(after))
        flagged = [c for c in by_class(root, "hole", "circle") if "dup" in classes(c)]
        assert len(flagged) == 1, f"no duplicate ring for {pipeline!r}"
        assert len(by_class(root, "dup-ring", "circle")) == 1, f"no ring for {pipeline!r}"


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


def test_the_reference_outline_is_the_only_outline_drawn(panel: DrillData):
    """One panel, one rectangle. The dashed true-size overlay is gone.

    Structural rather than ``"true-size" not in svg``: what matters is not that
    a class name is absent but that nothing draws a *second* outline, whatever
    it might be called.
    """
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


def _rows_of_five(count: int) -> DrillData:
    """``count`` rows of five holes, spread down a 112 × 61 panel.

    A 15-row panel is ordinary work — five controls in three banks is already
    three rows, and a row here is any distinct Y. Ids run backwards so nothing
    in the drawing can pass by treating a position as an identity.
    """
    pitch = 56.0 / (count - 1) if count > 1 else 0.0
    return DrillData(
        holes=tuple(
            Hole.from_measurement(
                -40.0 + 20.0 * column,
                28.0 - pitch * row,
                3.0,
                index=500 - (row * 5 + column),
            )
            for row in range(count)
            for column in range(5)
        ),
        reference=ReferenceOutline(112.0, 61.0),
    )


@pytest.mark.parametrize("rows", [5, 14, 15, 30])
def test_every_dimension_stays_inside_the_drawing_area(rows: int):
    """Measured thresholds: 14 rows passed the border, 15 left the sheet.

    ``layout`` clamps the room it reserves for chain dimensions to half the
    drawing area; ``_draw_row_chains`` stacked one chain per row regardless. And
    because the chains are drawn from the bottom row up, the ones that vanish
    are the *topmost* rows — whose holes are still drawn, with no dimension and
    nothing saying one was left off.
    """
    data = _rows_of_five(rows)
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert len(data.rows()) == rows
    assert_within(emitter.layout(data).area, by_class(root, "dimensions")[0], "the drawing area")


def test_the_drawing_says_how_many_row_dimensions_it_could_not_draw():
    """A hole with no dimension beside it is a hole nobody can locate.

    Same rule as the notes and the schedule: a fact that disappears without
    trace is worse than one that is visibly missing.
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
    headers = [e.text for e in by_class(root, "sched-head", "text")]
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
        assert float(cells["sched-x"]) == pytest.approx(hole.x)
        assert float(cells["sched-y"]) == pytest.approx(hole.y)
        # The whole cell, not a float parsed out of it: the units are part of
        # what the column says, and a fractional standard spells the same column
        # ``⌀9/32"``.
        assert cells["sched-dia"] == f"⌀{hole.diameter:.2f} mm"


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


def _sched_diameters(root: ET.Element) -> list[str]:
    return [e.text or "" for e in by_class(root, "sched-dia", "text")]


def test_schedule_diameters_are_spelled_the_way_the_drill_standard_spells_them():
    """A fractional bit's honest name is its fraction, and the standard knows it.

    Deliberately the *fractional* standard: 1/8" is 3.175 mm and 9/32" is
    7.14375, so a millimetre spelling of either is a rounding of a size that is
    exact — and, at the schedule's two decimals, ``⌀7.14 mm`` is a bit nobody
    stocks. The metric standard could not prove this test at all, because its
    label and the millimetre fallback are the same string.
    """
    data = make_data(*holes((-20.0, 0.0, 3.18), (20.0, 0.0, 7.13)))
    after = Pipeline([SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"])]).run(data)
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    assert _sched_diameters(root) == ['⌀1/8"', '⌀9/32"']
    summary = " | ".join(e.text or "" for e in by_class(root, "sched-summary", "text"))
    assert '⌀1/8"' in summary and '⌀9/32"' in summary


def test_schedule_diameters_use_the_standard_that_actually_ran():
    """A second standard, so the first test cannot be passing on a constant.

    The same two holes quantised against the metric drawer get metric labels,
    which is the same fact from the other side: the spelling is read out of the
    run, not chosen by the emitter.
    """
    data = make_data(*holes((-20.0, 0.0, 3.18), (20.0, 0.0, 7.13)))
    after = Pipeline([SnapDiametersToDrillTable(DRILL_STANDARDS["metric"])]).run(data)
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    assert _sched_diameters(root) == ["⌀3.20 mm", "⌀7.10 mm"]


def test_schedule_diameters_fall_back_to_millimetres_when_no_standard_was_recorded():
    """A hand-built ``DrillData`` never met the drill table. Nothing to look up.

    The fallback states millimetres because that is the frame the numbers are
    in; guessing a standard would put a bit designation on the sheet that no
    stage ever chose.
    """
    data = make_data(*holes((0.0, 0.0, 7.0)))
    assert data.last_run("snap-diameters") is None
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert _sched_diameters(root) == ["⌀7.00 mm"]


@pytest.mark.parametrize("recorded", ["gauge", "", True, 3.0, (3.0, 5.0)])
def test_a_recorded_standard_that_does_not_resolve_is_not_a_standard(recorded):
    """``StageRun`` payloads are generic; a name is only a name until it resolves.

    A run recorded against a hand-built standard — or a document from a later
    version of this tool — names something this build cannot expand into sizes
    or a spelling. Millimetres, then, rather than a label invented here.

    Every ``ParameterValue`` shape is passed through, because the registry
    lookup is the one place a payload reaches a dict key: a value it choked on
    would take out the whole sheet, not just this column.
    """
    data = make_data(*holes((0.0, 0.0, 7.0))).with_processing(
        StageRun("snap-diameters", (("standard", recorded), ("size_count", 80)))
    )
    root = ET.fromstring(DrawingSvgEmitter().emit(data))

    assert _sched_diameters(root) == ["⌀7.00 mm"]


def test_the_diameter_column_does_not_promise_millimetres_it_cannot_keep():
    """The heading carried ``mm`` while the rows can carry inch fractions."""
    data = make_data(*holes((0.0, 0.0, 3.18)))
    after = Pipeline([SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"])]).run(data)
    root = ET.fromstring(DrawingSvgEmitter().emit(after))

    headers = [e.text for e in by_class(root, "sched-head", "text")]
    assert headers[3] == "⌀"
    assert _sched_diameters(root) == ['⌀1/8"']


# --------------------------------------------------------------------------
# title block
# --------------------------------------------------------------------------


def _title_block_lines(root: ET.Element) -> list[str]:
    """Every string inside the title block, one per ``<text>``, in sheet order.

    Scoped deliberately: ``all_text`` would let a dimension label elsewhere on
    the drawing satisfy an assertion about what the title block states.

    Lines rather than one blob, because the title block is where the sheet makes
    its claims and a claim is a whole line. ``"112 × 61" in text`` is satisfied
    by a line that also carries a truncation ellipsis, or by two facts that
    happen to abut across a join; ``line in lines`` is not.
    """
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
    data = make_data(*holes((10.03, 5.02)))
    after = Pipeline([SnapPositions(grid=0.5)]).run(data)
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID 0.5 mm" in text


def test_the_title_block_states_a_grid_of_0_1_when_that_is_what_ran():
    """A second pitch, so the first test cannot be passing on a constant.

    0.25 was the old hardcoded default and 0.5 the obvious replacement; neither
    on its own distinguishes "reads the provenance" from "prints something
    plausible".
    """
    after = Pipeline([SnapPositions(grid=0.1)]).run(make_data(*holes((10.03, 5.02))))
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID 0.1 mm" in text
    # Scoped to the grid line: the title block also carries SCALE, so a bare
    # substring check would be pinned to layout fitting rather than to the grid.
    assert "GRID 0.5 mm" not in text and "GRID 0.25 mm" not in text


def test_the_title_block_says_the_grid_was_off_when_snapping_was_disabled():
    """``grid <= 0`` makes ``SnapPositions`` the identity; the sheet says so.

    Printing "GRID 0 mm" would read as a pitch. The holes are wherever the
    artwork put them, which is a different claim.
    """
    after = Pipeline([SnapPositions(grid=0.0)]).run(make_data(*holes((10.03, 5.02))))
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "GRID OFF" in text
    assert "GRID 0.25 mm" not in text and "GRID 0 mm" not in text


def test_the_title_block_does_not_invent_a_grid_when_none_was_recorded():
    """A hand-built ``DrillData`` never went through a pipeline. Saying 0.25 would be a lie.

    The literal is pinned, not merely the absence of 0.25: SPEC §7 promises
    ``GRID NOT RECORDED``, and "says nothing at all" satisfies "does not lie"
    while breaking that promise. A blank line where the grid should be also
    leaves the machinist to assume one.
    """
    data = make_data(*holes((0.0, 0.0)))
    assert data.processing == ()
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text
    assert "0.25" not in text


def test_a_recorded_grid_that_is_not_a_number_is_not_a_grid():
    """``StageRun`` payloads are generic, so "0.5" is a string, not a pitch.

    Reported the same way as no record at all. Printing it would put a number on
    the sheet that nothing guarantees is a millimetre value, and coercing it
    would be the emitter deciding what the pipeline meant.
    """
    data = make_data(*holes((0.0, 0.0))).with_processing(
        StageRun("snap", (("grid_mm", "0.5"), ("enabled", True)))
    )
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text
    assert "0.5" not in text


def test_a_recorded_grid_of_true_is_not_a_pitch_of_one_millimetre():
    """``bool`` is a legal ``ParameterValue`` and, in Python, also an ``int``.

    A naive numeric guard admits ``True`` and stamps the sheet ``GRID 1 mm`` —
    a plausible, wrong, drillable number. That is worse than saying nothing.
    """
    data = make_data(*holes((0.0, 0.0))).with_processing(
        StageRun("snap", (("grid_mm", True),))
    )
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "GRID NOT RECORDED" in text
    assert "GRID 1 mm" not in text


# -- the enclosure the panel was identified as ------------------------------


def _identified(
    *,
    length_mm: int = 112,
    width_mm: int = 61,
    candidates: tuple[str, ...] = ("1590B", "1590B2", "1590BS"),
    rotated: bool = False,
    selected_part: str | None = None,
    reference: ReferenceOutline | None = None,
) -> DrillData:
    """A panel whose *measured* outline is not its *catalogue* footprint.

    113 × 60 against a 112 × 61 match, which is the fixture panel's own error and
    the whole reason the identification stage exists. Kept apart on purpose: an
    emitter that printed ``data.reference`` instead of the match would be
    indistinguishable from a correct one if the two agreed.
    """
    return DrillData(
        holes=holes((0.0, 0.0)),
        reference=reference if reference is not None else ReferenceOutline(113.0, 60.0),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_mm=length_mm,
            width_mm=width_mm,
            candidates=candidates,
            rotated=rotated,
            selected_part=selected_part,
        ),
    )


def test_the_title_block_states_the_enclosure_the_pipeline_identified():
    """Straight off a real run: outline in, footprint on the sheet.

    The stage does the identifying; the drawing reads ``DrillData.enclosure``.
    Asserted as a whole line, because the sheet's claim is the line.
    """
    data = make_data(*holes((10.0, 5.0)), reference=ReferenceOutline(113.0, 60.0))
    after = Pipeline([IdentifyHammondFootprint()]).run(data)
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(after)))
    assert "HAMMOND 1590  112 × 61 mm  CANDIDATES B / B2 / BS" in lines


def test_the_enclosure_line_states_the_catalogue_footprint_not_the_measured_outline():
    """112 × 61 is what the case is; 113 × 60 is what the artwork came to.

    The datasheet number is the one a machinist can order a box by, and it is
    the one every other consumer of this panel has already agreed on.
    """
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(_identified())))
    assert "HAMMOND 1590  112 × 61 mm  CANDIDATES B / B2 / BS" in lines
    assert not [line for line in lines if "113" in line or "60" in line]


def test_the_enclosure_line_renders_the_candidates_in_the_order_it_was_handed():
    """A claim about the emitter: it passes the tuple through, it does not order it.

    ``enclosures.footprints()`` sorts, so all 22 production footprints arrive
    alphabetical and no fixture drawn from the catalogue can tell passthrough
    from sorting — ``("1590BB", "1590BB2", "1590BBS", "1590C")`` sorts to
    itself. These candidates are therefore hand-built out of alphabetical order,
    which is the only fixture that distinguishes the two, and the contract it
    pins is the emitter's: whoever builds an ``EnclosureMatch`` — a future
    matcher, a library caller, a changed ``footprints()`` — decides the order,
    and the drawing renders it.
    """
    data = _identified(candidates=("1590BS", "1590B", "1590B2"))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112 × 61 mm  CANDIDATES BS / B / B2" in lines


def test_a_candidate_that_does_not_carry_the_series_is_printed_whole():
    """``1590B`` under a ``HAMMOND 1590`` heading is that series' ``B``.

    The shorthand is the datasheet's, and it buys the width that keeps a
    four-candidate footprint inside the title block. It is not a substring
    operation, though, and the difference shows on anything the series does not
    prefix: blind slicing turns ``PB-61`` into ``61`` — a designator that reads
    like a dimension — and a designator that *is* the series into nothing at all.
    """
    data = _identified(candidates=("1590B", "1590", "PB-61"))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112 × 61 mm  CANDIDATES B / 1590 / PB-61" in lines


def test_the_enclosure_line_names_the_one_part_when_the_operator_declared_one():
    """``--case`` is the only thing that can ever narrow a footprint to a part.

    The declared part replaces the candidate list rather than joining it: the
    operator has answered the question the list was asking.
    """
    data = _identified(selected_part="1590B")
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112 × 61 mm  PART 1590B" in lines


def test_the_enclosure_line_does_not_name_a_part_when_none_was_declared():
    """``selected_part`` is ``None`` on every run that did not declare a case.

    A 2-D outline identifies a footprint and never a part, so a sheet naming one
    it was never told is claiming knowledge that is not in the artwork — and it
    is the plausible half of the pair a machinist would act on.
    """
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(_identified())))
    assert "HAMMOND 1590  112 × 61 mm  CANDIDATES B / B2 / BS" in lines
    assert not [line for line in lines if "PART" in line]


def test_the_enclosure_line_says_the_panel_is_turned_when_it_is():
    """The match keeps the catalogue's orientation; the artwork keeps its own.

    So a portrait panel is dimensioned 61 × 112 on the drawing while its
    enclosure line says 112 × 61 — two true numbers that read as a contradiction
    unless the sheet says which way round the panel sits.
    """
    data = _identified(rotated=True, reference=ReferenceOutline(60.0, 113.0))
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  112 × 61 mm ROTATED  CANDIDATES B / B2 / BS" in lines


def test_a_rotated_panel_keeps_every_candidate_in_the_title_block():
    """The one footprint in the catalogue that used to lose candidates.

    120 × 94 is 1590BB, 1590BB2, 1590BBS and 1590C — four of them, which
    ``_designator``'s elision was sized to fit. Turn the panel portrait and
    ``ROTATED`` joins the same line, pushing the last two past the title block,
    where they were replaced by an ellipsis that did not say how many had gone.
    The JSON, meanwhile, listed all four.
    """
    data = Pipeline([IdentifyHammondFootprint()]).run(
        make_data(*holes((0.0, 0.0)), reference=ReferenceOutline(94.0, 120.0))
    )
    assert data.enclosure is not None
    assert data.enclosure.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")

    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "HAMMOND 1590  120 × 94 mm ROTATED  CANDIDATES BB / BB2 / BBS / C" in lines


def test_a_candidate_list_that_cannot_fit_says_how_many_it_dropped():
    """Beyond shrinking, the line still has to end somewhere — honestly.

    A bare ellipsis leaves the reader unable to tell one missing candidate from
    three, which is the difference between ordering the right box and the wrong
    one. Twelve candidates is not a catalogue footprint; it is the width the
    real four-candidate case is one datasheet revision away from.
    """
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
    """No match, or no reference layer at all: the sheet says which, honestly.

    The literal is pinned rather than the absence of a footprint, for the reason
    ``GRID NOT RECORDED`` is: a line missing from the title block leaves the
    machinist to assume the panel is a Hammond case, and "unknown enclosure" is
    a legitimate outcome — the world holds more cases than this catalogue does.
    """
    data = make_data(*holes((0.0, 0.0)), reference=ReferenceOutline(200.0, 33.0))
    assert data.enclosure is None
    lines = _title_block_lines(ET.fromstring(DrawingSvgEmitter().emit(data)))
    assert "ENCLOSURE NOT IDENTIFIED" in lines
    assert not [line for line in lines if "HAMMOND" in line.upper()]


def test_a_panel_that_matches_nothing_still_says_so_after_a_real_run():
    """The warning path end to end: ``unknown-enclosure`` leaves the field unset.

    The hand-built case above cannot prove the stage leaves it unset — only that
    the emitter reads it — so the two tests are not one test twice.
    """
    data = make_data(*holes((0.0, 0.0)), reference=ReferenceOutline(200.0, 33.0))
    after = Pipeline([IdentifyHammondFootprint()]).run(data)
    assert [d.code for d in after.diagnostics] == ["unknown-enclosure"]
    assert "ENCLOSURE NOT IDENTIFIED" in _title_block_lines(
        ET.fromstring(DrawingSvgEmitter().emit(after))
    )


def test_a_line_too_long_even_at_the_smallest_font_is_still_truncated():
    """Shrinking buys width; it does not buy an unlimited amount of it.

    A title block line is shrunk to earn its room and only then chopped, and the
    chop still has to happen — at 1.6 mm the block holds 88 characters and this
    title is longer than that on any sheet. Without a case that reaches the
    floor, nothing distinguishes "fits the line" from "prints the line straight
    through the border", because every other line on the sheet is short enough
    that shrinking alone saves it.
    """
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


def _every_hole_a_different_size(count: int) -> DrillData:
    """``count`` holes, no two the same diameter, so the tool table is as long
    as the schedule itself.

    The truncation test above uses 240 holes of *one* diameter, which is why it
    never saw this: with one tool the summary is one line, and the capacity
    arithmetic that subtracts the summary from the box never bites. Ids run
    backwards so the NO. column cannot pass by coinciding with a position.
    """
    return DrillData(
        holes=tuple(
            Hole.from_measurement(-50.0 + 0.8 * i, 20.0, 3.0 + 0.1 * i, index=count - i)
            for i in range(count)
        ),
        reference=ReferenceOutline(112.0, 61.0),
    )


@pytest.mark.parametrize("tools", [2, 83, 120])
def test_every_element_of_the_schedule_stays_inside_its_box(tools: int):
    """Measured thresholds: 82 tools left the box, 83 reached the title block
    and 118 left the page altogether — while the drill file defined every one.

    ``layout`` clamped the capacity arithmetic to zero and the summary loop
    below it drew one line per tool regardless, so the deficit was thrown away
    rather than reported. Asserted on *where the elements land*, because the
    escaping branch executes on every run: line coverage said 100%.
    """
    data = _every_hole_a_different_size(tools)
    emitter = DrawingSvgEmitter()
    root = ET.fromstring(emitter.emit(data))
    assert_within(emitter.layout(data).schedule, by_class(root, "schedule")[0], "the schedule box")


def test_the_schedule_says_how_many_tools_it_could_not_list():
    """A tool the sheet does not name is a bit the machinist does not fit.

    The wording is its own: the only overflow the schedule used to print said
    "further holes not listed", which is a true statement about a different
    quantity and was printed while 39 tools were missing.
    """
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


def test_a_sheet_with_no_room_for_a_title_block_says_nothing_rather_than_guessing():
    """A 10 mm square sheet leaves the title block a negative width.

    Every string in it is composed to a character capacity, and a box of no
    width has a capacity of nothing — which must come out as an empty line, not
    as a lie fitted to a width the sheet does not have. Absurd as the sheet is,
    ``Sheet`` is a public option and the arithmetic is the same arithmetic the
    enclosure note trusts to decide how many candidates it may name.
    """
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
