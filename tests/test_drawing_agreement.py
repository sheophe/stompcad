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

from aidrill.emitters.drawing.content import (
    enclosure_note,
    grid_note,
    note_lines,
    schedule_rows,
    tool_summary,
)
from aidrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from aidrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
from aidrill.model import Diagnostic, DrillData, EnclosureMatch
from aidrill.units import Nanometre
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

    assert svg_dia and pdf_dia
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
    """One cell is narrower than the other line, so one may be cut short — but
    what it shows must still be the start of the very same claim."""
    data = identified()
    full = enclosure_note(data, 200)

    assert "PART 1590B" in full
    shown_svg = [t for t in svg_strings(data) if t.startswith("HAMMOND 1590")]
    assert len(shown_svg) == 1
    assert truncates(shown_svg[0], full)
    assert truncates(pdf_field(data, "ENCLOSURE"), full)


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

    assert len(rotated) == 1, "expected exactly one rotated run on the SVG sheet"
    assert len(placements) == 1, "expected exactly one rotated placement in the PDF"

    (content, angle), (cos_pdf, sin_pdf) = rotated[0], placements[0]
    assert content in pdf_strings(data)
    # The SVG advance is (cos, sin) with Y running down the page; the PDF's is
    # (a, b) with Y running up. Comparing them means flipping one of the two.
    across = math.cos(math.radians(angle))
    up_the_page = -math.sin(math.radians(angle))

    assert (across, up_the_page) == pytest.approx((cos_pdf, sin_pdf), abs=1e-3)
    # And it really is a label running up the page, not merely two agreeing zeros.
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
            assert row.y in svg and row.y in pdf, f"hole {row.number}: only one Y shown"


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
