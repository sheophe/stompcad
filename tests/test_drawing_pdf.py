"""The PDF drawing, parsed back out of the bytes it emitted."""

from __future__ import annotations

import functools
import io
import re

import pikepdf
import pytest

from aidrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions, encode_text
from aidrill.model import Diagnostic, DrillData, ReferenceOutline, SourceInfo
from aidrill.units import Nanometre
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
    payload = render(make_data(at(0, 0, index=1),
                               reference=outline(300_000_000, 200_000_000)))
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
    """Y is flipped in Python, so a mark near the sheet top has a high PDF y."""
    stream = stream_of(render(panel()))
    ys = [float(m) for m in re.findall(r"^\S+ (\S+) m$", stream, re.MULTILINE)]

    assert ys, "expected at least one moveto"
    assert max(ys) <= 297.0 + 1e-6


# --- what it says ---------------------------------------------------------


def test_the_schedule_names_holes_by_their_stable_identity():
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
