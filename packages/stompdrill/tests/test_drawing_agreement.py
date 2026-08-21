"""One panel, two sheets, one set of facts.

The sheets are allowed to differ in how many rows fit — a PDF on A3 has more
room than an SVG on A4 — but never in what they say about a row they both show.
Room is the only difference this file admits: a value one sheet truncates must
still be a prefix of the value the other prints, never a different value.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing.content import (
    enclosure_note,
    grid_note,
    note_lines,
    schedule_rows,
    tool_summary,
)
from stompdrill.emitters.drawing.layout import choose_sheet
from stompdrill.emitters.drawing.scene import Circle, Group, Item, Scene
from stompdrill.emitters.drawing.sheet import ISO_5457_CANDIDATES, FrameStyle
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from stompdrill.emitters.drawing_pdf import _num as pdf_num
from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData, EnclosureMatch
from stompmodel.units import Nanometre
from tests.conftest import at, make_data
from tests.test_drawing_pdf import outline, panel, stream_of, strings_in

SVG_NS = "http://www.w3.org/2000/svg"
TITLE = "TAR PANEL"

#: SVG writes ⌀ (U+2300); the PDF writes Ø (U+00D8) because WinAnsi has no code
#: point for ⌀. The glyph is a backend fact, the value after it is a panel fact.
DIAMETER_SIGNS = "⌀Ø"


def svg_bytes(data: DrillData, scale: float | None = None) -> str:
    return DrawingSvgEmitter(DrawingOptions(title=TITLE, scale=scale)).emit(data)


def svg_strings(data: DrillData, scale: float | None = None) -> list[str]:
    root = ET.fromstring(svg_bytes(data, scale))
    return [node.text or "" for node in root.iter(f"{{{SVG_NS}}}text")]


def pdf_bytes(data: DrillData) -> bytes:
    return DrawingPdfEmitter(PdfDrawingOptions(title=TITLE)).emit(data)


def pdf_strings(data: DrillData) -> list[str]:
    return strings_in(pdf_bytes(data))


def pdf_field(data: DrillData, label: str) -> str:
    """The value drawn straight after a title-block label is that field's value."""
    shown = pdf_strings(data)
    return shown[shown.index(label) + 1]


def unsigned(text: str) -> str:
    """Drop the diameter sign so the value it introduces can be compared."""
    return text.lstrip(DIAMETER_SIGNS).replace("⌀", "").replace("Ø", "")


def truncates(shown: str, full: str) -> bool:
    """Whether ``shown`` is ``full`` or ``full`` cut short with an ellipsis."""
    return shown == full or (shown.endswith("…") and full.startswith(shown[:-1]))


def identified() -> DrillData:
    """The fixture panel with an identified enclosure, so the note names a part."""
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_400_000),
        width_nm=Nanometre(60_500_000),
        candidates=("1590B", "1590B2"),
        selected_part="1590B",
        rotated=False,
    )
    return panel().with_enclosure(match)


# --- the schedule -----------------------------------------------------------


def test_both_sheets_name_the_same_holes_by_the_same_identities():
    data = panel()
    identities = {str(hole.index) for hole in data.holes}

    assert identities <= set(svg_strings(data))
    assert identities <= set(pdf_strings(data))


def test_no_cell_of_a_row_both_sheets_show_differs_between_them():
    """The whole row, not just its coordinates: a tool or a diameter that
    disagreed would send the same hole to two different bits."""
    data = panel()
    svg = {unsigned(text) for text in svg_strings(data)}
    pdf = {unsigned(text) for text in pdf_strings(data)}

    for row in schedule_rows(data):
        for cell in (str(row.number), row.x, row.y, row.tool, row.diameter):
            assert unsigned(cell) in svg, f"hole {row.number}: {cell!r} missing from the SVG"
            assert unsigned(cell) in pdf, f"hole {row.number}: {cell!r} missing from the PDF"


def test_both_sheets_assign_the_same_tool_to_the_same_diameter():
    data = panel()
    svg = " ".join(unsigned(t) for t in svg_strings(data))
    pdf = " ".join(unsigned(t) for t in pdf_strings(data))

    for line in tool_summary(data):
        pairing = f"{line.tool}  {unsigned(line.diameter)}  QTY {line.quantity}"
        assert pairing in svg
        assert pairing in pdf


def test_the_diameter_sign_differs_only_in_glyph_never_in_value():
    """SVG writes ⌀; PDF writes Ø because WinAnsi has no ⌀. Same number after it."""
    data = panel()
    svg_dia = [t for t in svg_strings(data) if "⌀" in t]
    pdf_dia = [t for t in pdf_strings(data) if "Ø" in t]

    assert svg_dia, "the SVG has no diameter strings to compare"
    assert pdf_dia, "the PDF has no diameter strings to compare"
    assert "Ø" not in " ".join(svg_strings(data))
    assert "⌀" not in " ".join(pdf_strings(data))
    assert {unsigned(t) for t in svg_dia} == {unsigned(t) for t in pdf_dia}


# --- the sheet's claims about the panel -------------------------------------


def test_both_sheets_state_the_same_grid_note():
    """The PDF rules a labelled cell and the SVG writes a line, so the fact is
    compared as label and value rather than as one rendered string."""
    data = panel()
    note = grid_note(data)

    assert any(note in text for text in svg_strings(data))
    assert f"GRID {pdf_field(data, 'GRID')}" == note


def test_both_sheets_state_the_same_enclosure_note():
    """One cell is narrower than the other line, so one may drop the footprint
    or the family to fit — but the part this panel is for is not negotiable:
    a prefix predicate cannot tell "shortened" from "the answer is gone", so
    this checks for the designator itself, on both sheets."""
    data = identified()
    full = enclosure_note(data, 200)

    assert "PART 1590B" in full
    shown_svg = [t for t in svg_strings(data) if t.startswith("HAMMOND 1590")]
    assert len(shown_svg) == 1
    assert truncates(shown_svg[0], full)
    assert "1590B" in pdf_field(data, "ENCLOSURE")


def test_both_sheets_carry_the_same_diagnostic_text():
    """A warning an operator reads on one sheet and not the other is the whole
    reason the two share one set of facts."""
    data = panel().with_diagnostics(
        Diagnostic.warning("off-grid", "hole 12 moved 0.120 mm"),
        Diagnostic.warning("off-grid", "hole 9 moved 0.080 mm"),
    )
    svg, pdf = svg_strings(data), pdf_strings(data)

    notes = note_lines(data)
    assert len(notes) == 2
    for note in notes:
        assert note.text in svg
        assert note.text in pdf


def test_both_sheets_state_the_same_row_levels():
    """The SVG fits a scale to its sheet and the PDF walks the ISO ladder at 1:1,
    so the chain of levels is drawn at two sizes. Its values are differences of
    stations rather than of sheet coordinates, so the numbers must still agree —
    a level the two sheets disagreed about is a row drilled at two heights.
    """
    data = panel()
    # 60.500 tall, rows at -18.750 and 18.000: bottom edge, both rows, top edge.
    levels = ["11.500", "36.750", "12.250"]

    svg, pdf = svg_strings(data), pdf_strings(data)
    for level in levels:
        assert level in svg, f"the SVG sheet never states the level {level}"
        assert level in pdf, f"the PDF sheet never states the level {level}"


def test_both_sheets_report_the_same_hole_count_and_source():
    data = panel()

    svg = " ".join(svg_strings(data))
    assert f"HOLES {len(data.holes)}" in svg
    assert pdf_field(data, "HOLES") == str(len(data.holes))
    assert data.source.path in svg
    assert pdf_field(data, "SOURCE") == data.source.path


# --- direction, which neither sheet reveals alone ---------------------------


def _svg_rotated(data: DrillData) -> list[tuple[str, float]]:
    """Every rotated run as (content, angle), read out of its transform."""
    root = ET.fromstring(svg_bytes(data))
    found = []
    for node in root.iter(f"{{{SVG_NS}}}text"):
        transform = node.get("transform")
        if transform is None:
            continue
        angle = float(re.findall(r"rotate\((-?[\d.]+)", transform)[0])
        found.append((node.text or "", angle))
    return found


def _pdf_rotated(data: DrillData) -> list[tuple[float, float]]:
    """Every rotated placement's baseline direction, from its text matrix."""
    stream = stream_of(pdf_bytes(data))
    return [
        (float(a), float(b))
        for a, b in re.findall(r"(\S+) (\S+) \S+ \S+ \S+ \S+ Tm", stream)
    ]


def test_a_rotated_label_advances_the_same_physical_way_on_both_sheets():
    """The scene states rotation in a Y-down frame, which SVG reads directly and
    PDF must negate: mirroring one axis reverses a rotation's sense. Nothing
    about either sheet alone shows it, so only the pair can pin the direction.
    """
    data = panel()
    rotated = _svg_rotated(data)
    placements = _pdf_rotated(data)

    assert rotated, "expected a rotated run on the SVG sheet"
    assert len(rotated) == len(placements), "one sheet rotated a label the other did not"

    shown = pdf_strings(data)
    for (content, angle), (cos_pdf, sin_pdf) in zip(rotated, placements, strict=True):
        assert content in shown
        # The SVG advance is (cos, sin) with Y running down the page; the PDF's
        # is (a, b) with Y running up. Comparing them flips one of the two.
        across = math.cos(math.radians(angle))
        up_the_page = -math.sin(math.radians(angle))

        assert (across, up_the_page) == pytest.approx((cos_pdf, sin_pdf), abs=1e-3)
        # And it really is a label running up the page, not two agreeing zeros.
        assert up_the_page > 0.9


# --- what a crowded sheet is allowed to differ about ------------------------


def crowded() -> DrillData:
    """More holes than either schedule box can list, all of one diameter."""
    return make_data(
        *(at(i * 1_000_000 - 50_000_000, 0, index=i) for i in range(1, 60)),
        reference=outline(112_400_000, 60_500_000),
    )


def _listed_and_omitted(texts: list[str]) -> tuple[int, int]:
    """Rows listed, and the count the sheet says it dropped.

    Every hole is drilled by one tool, so a schedule row is exactly a cell
    reading ``T1``: the balloons carry numbers and the summary line carries the
    tool with its diameter and quantity, so neither is counted here.
    """
    listed = sum(1 for text in texts if text == "T1")
    markers = [re.search(r"… (\d+) further holes not listed", text) for text in texts]
    found = next((m for m in markers if m), None)
    return listed, 0 if found is None else int(found.group(1))


def test_a_crowded_schedule_counts_what_it_omits_on_both_sheets():
    """The legitimate divergence, pinned so nobody "fixes" it later.

    Room differs, so how many rows survive allotment differs. What may never
    differ is a row both sheets show, which every test above pins. What both
    must do is account for every hole: a row that vanishes without trace is how
    an operator never learns a hole exists.
    """
    data = crowded()
    counts = {
        "SVG": _listed_and_omitted(svg_strings(data)),
        "PDF": _listed_and_omitted(pdf_strings(data)),
    }

    for sheet, (listed, omitted) in counts.items():
        assert listed > 0, f"the {sheet} sheet listed no holes at all"
        assert listed + omitted == len(data.holes), f"the {sheet} sheet lost a hole"
    # The premise of the test: this panel really does crowd one of the two, so a
    # marker that always read zero would not pass unnoticed.
    assert sum(omitted for _, omitted in counts.values()) > 0


def test_a_row_shown_on_both_crowded_sheets_says_the_same_thing():
    data = crowded()
    svg = set(svg_strings(data))
    pdf = set(pdf_strings(data))

    for row in schedule_rows(data):
        if row.x in svg and row.x in pdf:
            assert row.y in svg, f"hole {row.number}: Y missing from the SVG despite a shared X"
            assert row.y in pdf, f"hole {row.number}: Y missing from the PDF despite a shared X"


# --- the overflow marker, which speaks for the sheet it is drawn on ---------


OVERFLOW = re.compile(r"SCALE (\S+) — CONTENT EXCEEDS (\S+);")


def test_the_svg_overflow_marker_names_the_scale_its_own_sheet_states():
    """Shared code drawing this marker cannot assume the PDF's 1:1: an SVG sheet
    forced to 20:1 would then contradict its own title block."""
    texts = svg_strings(panel(), 20.0)
    marker = next(m for m in (OVERFLOW.search(t) for t in texts) if m)

    assert marker.group(1) == "20:1"
    assert any("SCALE 20:1" in text for text in texts if not OVERFLOW.search(text))


def test_the_pdf_overflow_marker_names_the_scale_its_own_sheet_states():
    data = make_data(at(0, 0, index=1), reference=outline(2_000_000_000, 1_500_000_000))
    marker = next(m for m in (OVERFLOW.search(t) for t in pdf_strings(data)) if m)

    assert marker.group(1) == pdf_field(data, "SCALE") == "1:1"
    assert marker.group(2) == pdf_field(data, "PAPER SIZE") == "A0"


# --- where the marks are, not just what the sheet says ----------------------


def _scene_hole_circles(scene: Scene) -> list[Circle]:
    """Every ``hole``-class circle in the scene, wherever its group nests it."""
    found: list[Circle] = []

    def walk(item: Item) -> None:
        if isinstance(item, Group):
            for child in item.items:
                walk(child)
        elif isinstance(item, Circle) and "hole" in item.cls.split():
            found.append(item)

    for item in scene.items:
        walk(item)
    return found


def _svg_circles(scene: Scene, cls_token: str) -> list[tuple[float, float, float]]:
    """Render ``scene`` through the SVG backend and read its circles back.

    ``render`` is the seam ``emit`` fuses: it takes the scene the test built
    rather than resolving one of its own, so the PDF and SVG halves of the
    comparison are reading a single scene.
    """
    root = ET.fromstring(DrawingSvgEmitter(DrawingOptions(title=TITLE)).render(scene, TITLE))
    return [
        (float(e.attrib["cx"]), float(e.attrib["cy"]), float(e.attrib["r"]))
        for e in root.iter(f"{{{SVG_NS}}}circle")
        if cls_token in (e.get("class") or "").split()
    ]


def test_a_holes_mark_lands_at_the_same_sheet_point_on_both_backends():
    """Both backends walk one ``Scene``, so a divergence can only enter at a
    serialiser: ``_circle_path``, ``_rect_path``'s corner arcs, or the ``_y``
    flip. Each is otherwise tested only against itself, so a mislocated mark
    on one sheet would have nothing to catch it. SVG is Y-down in sheet
    millimetres; PDF is Y-up, so ``y_pdf = sheet.height - y_svg``."""
    data = panel()
    layout = choose_sheet(data, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)
    scene = build_scene(layout, data, SheetText(title=TITLE))

    scene_holes = _scene_hole_circles(scene)
    assert len(scene_holes) == len(data.holes) == 4

    svg_holes = _svg_circles(scene, "hole")
    assert len(svg_holes) == len(scene_holes)

    pdf_stream = stream_of(DrawingPdfEmitter(PdfDrawingOptions(title=TITLE)).render(scene, TITLE))

    by_position = sorted(scene_holes, key=lambda c: (c.cx, c.cy))
    for hole, svg_circle in zip(by_position, sorted(svg_holes)):
        # The scene is the one source both backends read, so the SVG circle
        # must simply carry the scene's own sheet-millimetre numbers through.
        assert svg_circle == pytest.approx((hole.cx, hole.cy, hole.r))
        # The PDF's own frame is Y-up: the same centre reappears as the first
        # point of its Bézier path at (cx + r, sheet.height - cy).
        moveto = f"{pdf_num(hole.cx + hole.r)} {pdf_num(scene.sheet.height - hole.cy)} m"
        assert moveto in pdf_stream, f"hole at {(hole.cx, hole.cy)}: {moveto!r} not in the PDF"
