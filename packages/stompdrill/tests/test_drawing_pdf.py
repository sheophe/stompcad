"""The PDF drawing, parsed back out of the bytes it emitted."""

from __future__ import annotations

import functools
import io
import re

import pikepdf
import pytest

from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions, encode_text
from stompdrill.errors import EmitterError
from stompdrill.model import Diagnostic, DrillData, ReferenceOutline, SourceInfo
from stompdrill.units import Nanometre
from tests.conftest import at, make_data

PT_PER_MM = 72.0 / 25.4


def outline(width_nm: int, height_nm: int) -> ReferenceOutline:
    return ReferenceOutline.from_measurement(Nanometre(width_nm), Nanometre(height_nm))


def panel() -> DrillData:
    """The 1590B fixture: hole ids out of position order, as the house style asks."""
    return DrillData(
        holes=(
            at(-40_000_000, 18_000_000, index=12),
            at(0, 18_000_000, index=5),
            at(40_000_000, 18_000_000, index=9),
            at(19_000_000, -18_750_000, 5_000_000, index=1),
        ),
        reference=outline(112_400_000, 60_500_000),
        source=SourceInfo(path="/panels/tar.ai", drill_layer="Drill",
                          reference_layer="Background"),
    )


def render(data: DrillData, options: PdfDrawingOptions | None = None) -> bytes:
    return DrawingPdfEmitter(options or PdfDrawingOptions()).emit(data)


@functools.lru_cache(maxsize=None)
def _opened(payload: bytes) -> pikepdf.Pdf:
    """Cache the open ``Pdf`` by its bytes.

    A ``Page`` does not keep its owning ``Pdf`` alive, so returning a page from
    a ``Pdf`` with no other reference leaves it reading a destroyed object.
    """
    return pikepdf.open(io.BytesIO(payload))


def page_of(payload: bytes):
    return _opened(payload).pages[0]


def stream_of(payload: bytes) -> str:
    """The page's content stream as text. Uncompressed, so no decode step."""
    return bytes(page_of(payload).Contents.read_bytes()).decode("latin-1")


def field_value(payload: bytes, label: str) -> str:
    """The run drawn straight after a title-block label is that field's value.

    The block writes one label and then its own value per cell, so the pairing
    is what pins a field: the value alone can be a string some other feature
    puts on the sheet, and the label alone says nothing about what it carries.
    """
    shown = strings_in(payload)
    return shown[shown.index(label) + 1]


def strings_in(payload: bytes) -> list[str]:
    """Every literal string shown by a Tj operator, WinAnsi-decoded."""
    found = re.findall(r"\((?:[^()\\]|\\.)*\)\s*Tj", stream_of(payload))
    out = []
    for literal in found:
        body = literal[1 : literal.rindex(")")]
        body = body.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        out.append(body.encode("latin-1").decode("cp1252"))
    return out


# --- the artefact ---------------------------------------------------------


def test_the_emitter_refuses_data_that_was_never_routed():
    data = make_data(at(0, 0, 7_000_000), reference=outline(100_000_000, 100_000_000))
    with pytest.raises(EmitterError, match="RouteHoles"):
        render(data)


def test_the_emitter_returns_bytes_that_open_as_a_pdf():
    payload = render(panel())

    assert isinstance(payload, bytes)
    assert payload.startswith(b"%PDF-1.7")
    assert len(pikepdf.open(io.BytesIO(payload)).pages) == 1


def test_emitting_twice_produces_identical_bytes():
    """Two runs over one panel must agree, and tests assert on bytes."""
    data = panel()

    assert render(data) == render(data)


def test_the_document_carries_no_timestamp():
    """A clock in an emitter makes one panel produce two different artefacts."""
    payload = render(panel())

    assert b"CreationDate" not in payload
    assert b"ModDate" not in payload
    # XMP is what stamps xmp:ModifyDate, so its absence is the actual guard.
    assert b"<?xpacket" not in payload
    assert b"Metadata" not in payload


# --- the sheet ------------------------------------------------------------


def test_a_1590b_panel_is_drawn_on_a4_portrait_at_one_to_one():
    """112.40 x 60.50 fits A4's 180 x 277 drawing space without shrinking."""
    payload = render(panel())
    box = [float(v) for v in page_of(payload).MediaBox]

    assert box == pytest.approx([0.0, 0.0, 210.0 * PT_PER_MM, 297.0 * PT_PER_MM])
    assert "SCALE 1:1" in " ".join(strings_in(payload))


def test_a_larger_panel_grows_the_sheet_rather_than_the_scale():
    """Wider than A4's drawing space, and no taller than A3's, so A3 it is."""
    payload = render(make_data(at(0, 0, index=1),
                               reference=outline(300_000_000, 120_000_000)))
    box = [float(v) for v in page_of(payload).MediaBox]

    assert box == pytest.approx([0.0, 0.0, 420.0 * PT_PER_MM, 297.0 * PT_PER_MM])
    assert "SCALE 1:1" in " ".join(strings_in(payload))


def test_the_content_stream_speaks_millimetres():
    """One scale-only CTM, so a 0.7 in the stream is ISO 128-24's 0.7 mm."""
    stream = stream_of(render(panel()))
    first = stream.strip().splitlines()[0]

    assert first.endswith("cm")
    numbers = [float(v) for v in first.split()[:6]]
    assert numbers == pytest.approx([PT_PER_MM, 0.0, 0.0, PT_PER_MM, 0.0, 0.0])
    # No vertical flip in the matrix: that would mirror every glyph.
    assert numbers[3] > 0


def test_the_drawing_is_not_mirrored_top_to_bottom():
    """A mark near the scene's top must sit high in PDF's Y-up y, and one near
    the scene's bottom must sit low — not merely under some fixed bound, which
    an unflipped ``_y`` also satisfies, since every scene coordinate is already
    inside the sheet. The frame border is a mark whose scene position is known:
    its Y-down top edge is ``layout.border``'s ``y0`` (small, near the scene's
    top) and its bottom edge is ``y1`` (larger, near the scene's bottom)."""
    data = panel()
    emitter = DrawingPdfEmitter()
    layout = emitter.layout(data)
    x0, y0, x1, y1 = layout.border
    stream = stream_of(emitter.emit(data))

    # Every plain rectangle in the stream, then the one whose width and height
    # are the border's: locating it by draw order would quietly test some other
    # box the day the frame stops being drawn first.
    rectangles = [
        tuple(float(v) for v in found)
        for found in re.findall(r"^(\S+) (\S+) (\S+) (\S+) re S$", stream, re.MULTILINE)
    ]
    border = [r for r in rectangles if (r[2], r[3]) == pytest.approx((x1 - x0, y1 - y0))]
    assert len(border) == 1, "expected exactly one rectangle the size of the frame border"
    _, rect_y, _, height = border[0]

    # A correct flip sends the scene-bottom edge (y1) to the *smaller* PDF y
    # and the scene-top edge (y0) to the *larger* one; an unflipped ``_y``
    # would instead leave the rectangle at (y0, y0 + height) unchanged.
    assert rect_y == pytest.approx(layout.sheet.height - y1, abs=1e-2)
    assert rect_y + height == pytest.approx(layout.sheet.height - y0, abs=1e-2)


def test_every_rotated_label_advances_up_the_page():
    """The overall height and the chain of row levels are the sheet's rotated
    text, all drawn with ``rotate=-90`` so they read bottom-to-top like an
    engineering drawing's vertical dimensions. ``text.rotate`` is defined in the
    scene's Y-down frame, so every text matrix must still advance toward *larger*
    PDF y — the direction an un-negated angle gets backwards, silently, because
    nothing about the SVG sheet or this PDF alone looks wrong in isolation."""
    stream = stream_of(render(panel()))

    matches = re.findall(r"(\S+) (\S+) \S+ \S+ \S+ \S+ Tm", stream)
    assert matches, "expected the sheet to place rotated text at all"
    for match in matches:
        cos_component, sin_component = (float(v) for v in match)

        assert sin_component > 0
        assert (cos_component, sin_component) == pytest.approx((0.0, 1.0), abs=1e-3)


# --- what it says ---------------------------------------------------------


def test_the_schedule_names_holes_by_their_routed_number_not_their_position():
    shown = strings_in(render(panel()))

    assert "12" in shown
    assert "9" in shown


def test_the_diameter_column_uses_a_glyph_winansi_can_encode():
    """⌀ (U+2300) is outside WinAnsi; Ø (U+00D8) is the sign a title block prints."""
    shown = " ".join(strings_in(render(panel())))

    assert "Ø" in shown
    assert "⌀" not in shown


def test_encode_text_escapes_the_three_characters_pdf_reserves():
    assert encode_text("a(b)c\\d") == b"a\\(b\\)c\\\\d"


def test_encode_text_substitutes_rather_than_corrupting_the_stream():
    assert encode_text("⌀7.000") == "Ø7.000".encode("cp1252")
    # × … — are all in WinAnsi and pass through.
    assert encode_text("112 × 60") == "112 × 60".encode("cp1252")
    assert encode_text("…") == "…".encode("cp1252")


def test_an_unencodable_character_becomes_a_question_mark():
    """Better a visible ? than a byte the viewer reads as a different glyph."""
    assert encode_text("温度") == b"??"


def test_a_title_with_reserved_characters_survives_into_the_document():
    options = PdfDrawingOptions(title="PANEL (REV\\A)")
    shown = " ".join(strings_in(render(panel(), options)))

    assert "PANEL (REV\\A)" in shown


def test_notes_state_that_none_were_raised_rather_than_leaving_a_blank_box():
    shown = " ".join(strings_in(render(panel())))

    assert "No diagnostics" in shown


def test_a_warning_reaches_the_notes():
    data = make_data(at(0, 0, index=1), reference=outline(112_400_000, 60_500_000))
    flagged = data.with_diagnostics(
        Diagnostic.warning("off-grid", "hole 1 moved 0.120 mm to the grid")
    )

    shown = " ".join(strings_in(render(flagged)))

    assert "WARNING" in shown
    assert "moved 0.120 mm" in shown


# --- sheet furniture --------------------------------------------------------


def test_the_pdf_sheet_carries_the_iso_frame_and_the_svg_sheet_does_not():
    """The furniture is about paper, so it is the PDF sheet that gets it."""
    from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter

    assert "A4" in strings_in(render(panel()))
    assert "centring-mark" not in DrawingSvgEmitter(DrawingOptions()).emit(panel())


# --- overflow ----------------------------------------------------------------


def test_a_panel_past_a0_is_still_drawn_1_to_1_and_says_it_overflowed():
    """1:1 is a fabrication guarantee, so the sheet reports rather than shrinks."""
    huge = make_data(at(0, 0, index=1), reference=outline(2_000_000_000, 1_500_000_000))
    payload = render(huge)
    shown = " ".join(strings_in(payload))
    box = [float(v) for v in page_of(payload).MediaBox]

    assert box == pytest.approx([0.0, 0.0, 1189.0 * PT_PER_MM, 841.0 * PT_PER_MM])
    assert "SCALE 1:1" in shown
    assert "CONTENT EXCEEDS A0" in shown
    # The overflow names the size actually required, so it is actionable.
    assert "2000.000" in shown and "1500.000" in shown


def test_a_panel_that_fits_carries_no_overflow_marker():
    assert "CONTENT EXCEEDS" not in " ".join(strings_in(render(panel())))


# --- the title block --------------------------------------------------------


def test_the_sheet_states_its_units_scale_and_that_it_must_not_be_scaled():
    shown = " ".join(strings_in(render(panel())))

    assert "UNITS mm" in shown
    assert "SCALE 1:1" in shown
    assert "DO NOT SCALE" in shown


def test_the_paper_size_field_names_the_sheet_that_was_chosen():
    """The field itself, not the size designation ISO 5457 puts in the border."""
    assert field_value(render(panel()), "PAPER SIZE") == "A4"


def test_the_mandatory_fields_a_caller_supplies_reach_the_printed_sheet():
    """A title block states them; nothing else on the sheet does."""
    options = PdfDrawingOptions(title="TAR PANEL", drawing_no="AI-0001",
                                issue_date="2026-08-16", approved_by="P VAKHNIVSKYI",
                                creator="STOMPDRILL")
    shown = strings_in(render(panel(), options))

    for value in ("TAR PANEL", "AI-0001", "2026-08-16", "P VAKHNIVSKYI", "STOMPDRILL"):
        assert value in shown
    for label in ("LEGAL OWNER", "IDENT NO", "DATE OF ISSUE", "SHEET", "TITLE",
                  "APPROVED", "CREATOR", "DOC TYPE"):
        assert label in shown


def test_a_mandatory_field_with_no_source_prints_an_em_dash_rather_than_a_gap():
    """Unset by default: stompdrill reads artwork, not an organisation.

    Each field is asserted with its own value, because four of them print an
    em dash and any one of the four would satisfy a bare search for one.
    """
    payload = render(panel())

    for label in ("DATE OF ISSUE", "APPROVED", "CREATOR"):
        assert field_value(payload, label) == "—"
    assert field_value(payload, "LEGAL OWNER") == "ARTIFACT INSTRUMENTS"


def test_the_block_spans_the_full_drawing_space_width_at_the_foot_of_the_a4_sheet():
    """ISO 7200 6 with ISO 5457 Table 1: 180 mm is A4's whole drawing space."""
    data = panel()
    emitter = DrawingPdfEmitter()
    layout = emitter.layout(data)
    x0, y0, x1, y1 = layout.title_block

    assert (x1 - x0, x1, y1) == pytest.approx((180.0, layout.border[2], layout.border[3]))
    # The drawing itself keeps clear of it.
    assert layout.area[3] <= y0
    stream = stream_of(emitter.emit(data))
    bottom = layout.sheet.height - y1
    assert f"{x0:.0f} {bottom:.0f} 180 {y1 - y0:.0f} re S" in stream


def test_notes_past_the_band_are_counted_rather_than_given_a_larger_sheet():
    """The paper a panel needs is a fact about the panel, not about its findings."""
    noisy = panel().with_diagnostics(
        *(Diagnostic.warning("off-grid", f"hole {n} moved 0.120 mm to the grid")
          for n in range(1, 21))
    )
    payload = render(noisy)
    box = [float(v) for v in page_of(payload).MediaBox]

    assert box == pytest.approx([0.0, 0.0, 210.0 * PT_PER_MM, 297.0 * PT_PER_MM])
    assert "further notes not listed" in " ".join(strings_in(payload))
