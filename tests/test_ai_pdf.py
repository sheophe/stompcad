"""Tests for the Illustrator/PDF source.

The bulk of these run against ``tests/fixtures/tar.ai``, a genuine Illustrator
30.7 native save whose contents have been verified independently. Where the
fixture cannot exercise a rule — the ``v``/``y`` curve shorthands, Form XObjects,
an empty drill layer — a minimal PDF is built in-test with pikepdf, because a
synthetic file is the only way to state those cases exactly.

Nothing here dedupes, snaps or clusters. Eight circles are drawn on the drill
layer of the fixture and eight holes must come back; collapsing the coincident
pair is the pipeline's job (SPEC 5), and a source that did it would hide the
duplicate from the diagnostics that are supposed to report it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pikepdf
import pytest

from aidrill.errors import EmptyLayerError, LayerNotFoundError, SourceError
from aidrill.geometry import CurveTo, MoveTo, fit_circle
from aidrill.model import RawDrillData, RawHole, RawOutline, Severity
from aidrill.protocols import Source
from aidrill.sources import AiPdfSource
from aidrill.units import mm_from_pt
from tests.conftest import build_pdf, circle_ops

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

#: Verified ground truth for the fixture: (x, y, diameter) in millimetres,
#: relative to the centre of the reference outline, Y up. The first entry is
#: drawn twice — identically — and both occurrences must survive the source.
#:
#: An independent human measurement of the artwork, taken in millimetres, which
#: is what the source now reports in — so it is compared field for field with no
#: conversion in between to agree with by construction.
EXPECTED_HOLES = [
    (-39.9906, 18.0000, 6.9998),
    (-39.9906, 18.0000, 6.9998),
    (-19.9998, 18.0000, 6.9998),
    (0.0000, 18.0000, 7.0000),
    (20.0002, 18.0000, 6.9998),
    (40.0000, 18.0000, 7.0000),
    (-18.9907, -18.7500, 5.0001),
    (19.0047, -18.7500, 5.0001),
]

#: One thousandth of a millimetre: the last digit the drill file and the drawing
#: print, and therefore the smallest disagreement either artifact can show. A
#: difference this tolerance swallows is one nothing downstream could render, so
#: tightening it would only pin arithmetic no reader of an output can see.
TOL_MM = 0.001

#: The fixture's artboard. Present so the tests can assert it is *not* used as
#: the frame: A4 landscape is the sheet Illustrator happened to be set to, not
#: the enclosure.
A4_LANDSCAPE_PT = (841.89, 595.276)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def match_multiset(holes, expected, tol=TOL_MM):
    """Pair each expected (x, y, d) with a distinct hole, or fail loudly.

    Order is not asserted — the source reports stream order, which is a
    property of Illustrator's save, not of this library. Multiplicity *is*
    asserted, which is how the duplicated hole is pinned down.
    """
    remaining = list(holes)
    unmatched = []
    for x, y, d in expected:
        for hole in remaining:
            if (
                abs(hole.x - x) <= tol
                and abs(hole.y - y) <= tol
                and abs(hole.diameter - d) <= tol
            ):
                remaining.remove(hole)
                break
        else:
            unmatched.append((x, y, d))
    assert not unmatched, f"no hole matched {unmatched}; left over: {remaining}"
    assert not remaining, f"unexpected extra holes: {remaining}"


def warnings(data):
    """The WARNING diagnostics of a read.

    Spelt here rather than borrowed from ``DrillData.of_severity``: a
    ``RawDrillData`` carries findings but answers no questions about them, and
    reaching for a query method the type does not have is how a source ends up
    being asked to behave like the thing it is quantised into.
    """
    return [d for d in data.diagnostics if d.severity is Severity.WARNING]


@pytest.fixture(scope="module")
def data():
    return AiPdfSource(FIXTURE).read()


# ---------------------------------------------------------------------------
# protocol and provenance
# ---------------------------------------------------------------------------


def test_satisfies_the_source_protocol():
    assert isinstance(AiPdfSource(FIXTURE), Source)


def test_what_comes_back_is_a_measurement(data):
    """A source measures. Everything it hands over is still in millimetres.

    ``isinstance`` against ``Source`` cannot say this — a ``Protocol`` checks
    that ``read`` exists, never what it returns — so the one structural fact
    the quantisation phase depends on is asserted directly.
    """
    assert isinstance(data, RawDrillData)
    assert isinstance(data.reference, RawOutline)
    assert all(isinstance(h, RawHole) for h in data.holes)


def test_default_layer_names_match_the_spec():
    source = AiPdfSource(FIXTURE)
    assert source.drill_layer == "Drill"
    assert source.reference_layer == "Background"


def test_layers_can_be_listed_without_reading_geometry():
    assert AiPdfSource(FIXTURE).layers() == ("Background", "Drill", "Graphics", "Hardware")


def test_repr_states_both_layer_choices():
    text = repr(AiPdfSource(FIXTURE, drill_layer="D", reference_layer="B"))
    assert "drill_layer='D'" in text and "reference_layer='B'" in text


def test_source_info_records_every_layer_found(data):
    assert data.source.layers_found == ("Background", "Drill", "Graphics", "Hardware")
    assert data.source.drill_layer == "Drill"
    assert data.source.reference_layer == "Background"
    assert data.source.path == str(FIXTURE)


def test_reading_twice_gives_the_same_answer():
    source = AiPdfSource(FIXTURE)
    assert source.read() == source.read()


def test_missing_file_raises_source_error(tmp_path):
    with pytest.raises(SourceError):
        AiPdfSource(tmp_path / "nope.ai").read()


# ---------------------------------------------------------------------------
# the reference frame
# ---------------------------------------------------------------------------


def test_reference_outline_is_the_largest_non_circular_background_path(data):
    reference = data.reference
    assert reference is not None
    assert reference.width == pytest.approx(113.0000, abs=TOL_MM)
    assert reference.height == pytest.approx(60.0001, abs=TOL_MM)
    assert data.centre == pytest.approx((148.4999, 105.0000), abs=TOL_MM)


def test_the_artboard_is_not_the_frame(data):
    """A4 landscape is the sheet, not the enclosure (SPEC 6.6)."""
    assert data.reference is not None
    assert data.reference.width != pytest.approx(mm_from_pt(A4_LANDSCAPE_PT[0]), abs=0.5)
    assert data.reference.height != pytest.approx(mm_from_pt(A4_LANDSCAPE_PT[1]), abs=0.5)


# ---------------------------------------------------------------------------
# the holes
# ---------------------------------------------------------------------------


def test_eight_circles_are_read_not_seven(data):
    """Dedupe belongs to the pipeline; the source must not pre-empt it."""
    assert len(data.holes) == 8


def test_hole_positions_and_diameters(data):
    match_multiset(data.holes, EXPECTED_HOLES)


def test_the_duplicated_hole_is_reported_twice(data):
    """Same geometry, different identity.

    The two circles are indistinguishable as measurements — which is why
    ``raw`` cannot serve as a hole's key — so what separates them is
    ``index``, assigned by the source in traversal order.
    """
    coincident = [
        h
        for h in data.holes
        if abs(h.x - (-39.9906)) <= TOL_MM and abs(h.y - 18.0) <= TOL_MM
    ]
    assert len(coincident) == 2
    # Every field but ``index``, and it stays exhaustive as RawHole gains more.
    assert replace(coincident[0], index=coincident[1].index) == coincident[1]
    assert coincident[0].index != coincident[1].index


def test_the_identity_counter_runs_over_circles_not_over_paths(tmp_path):
    """A path that is not a hole must not spend a hole's identity.

    Counting drill-layer *paths* instead of the circles fitted out of them is
    the plausible slip, and on this layer it shifts every index by one: the two
    holes come back as 1 and 2. Nothing about them looks wrong afterwards —
    both are still distinct, still deterministic, still in traversal order —
    but every diagnostic that names a hole names the wrong one, and the
    stray line that caused it is not in any artifact to be blamed.
    """
    pdf = build_pdf(
        tmp_path / "counter.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "20 20 m 40 40 l S " + circle_ops(60, 35, 10) + " " + circle_ops(150, 35, 8),
        },
    )
    holes = AiPdfSource(pdf).read().holes
    assert [h.index for h in holes] == [0, 1]


def test_diameters_are_not_clustered(data):
    """6.9998 and 7.0000 must both survive; SnapDiametersToDrillTable resolves them."""
    diameters = {h.diameter for h in data.holes}
    assert len(diameters) > 2


def test_no_snapping_has_happened(data):
    """The source reports where a circle is, not where a grid would put it.

    The leftmost hole is at -39.9906 mm, which no 0.25 grid contains. Snapping
    it belongs to the quantisation phase and would move it to -40.0 — 0.0094 mm,
    nine times the last digit the drill file prints, so this is a difference an
    artifact shows rather than one only arithmetic can see.
    """
    assert min(h.x for h in data.holes) == pytest.approx(-39.9906, abs=TOL_MM)


def test_the_source_adds_no_warnings(data):
    assert warnings(data) == []


# ---------------------------------------------------------------------------
# clip paths
# ---------------------------------------------------------------------------


def test_clip_rectangles_are_not_geometry():
    """The drill layer holds two full-MediaBox clips (``re W n``) — SPEC 6.3."""
    source = AiPdfSource(FIXTURE)
    paths = source.layer_subpaths("Drill")
    assert len(paths) == 8
    for path in paths:
        assert fit_circle(path) is not None
        x0, y0, x1, y1 = path.bbox
        assert (x1 - x0, y1 - y0) != pytest.approx(A4_LANDSCAPE_PT, abs=0.5)


def test_a_clip_only_layer_yields_nothing(tmp_path):
    pdf = build_pdf(
        tmp_path / "clips.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "q 0 0 400 400 re W n Q 0 0 400 400 re W n " + circle_ops(50, 50, 10),
        },
    )
    # the circle is real geometry, the two clip rectangles are not
    assert len(AiPdfSource(pdf).layer_subpaths("Drill")) == 1


def test_an_invisible_no_paint_rectangle_cannot_become_the_reference_outline(tmp_path):
    """``n`` paints nothing, so its path is not artwork (PDF 8.5.3.1).

    An artboard-sized ``re n`` with no ``W`` is invisible in every viewer, yet it
    is the largest rectangle on the layer. Counted as geometry it wins on area,
    the frame becomes the artboard, and every hole is then measured from the
    wrong centre — the failure this test exists to catch.
    """
    pdf = build_pdf(
        tmp_path / "nopaint.pdf",
        {
            "Background": "10 10 100 50 re f 0 0 400 400 re n",
            "Drill": circle_ops(60, 35, 10),
        },
    )
    data = AiPdfSource(pdf).read()

    assert len(AiPdfSource(pdf).layer_subpaths("Background")) == 1
    assert data.reference is not None
    assert data.reference.width == mm_from_pt(100.0)
    assert data.reference.height == mm_from_pt(50.0)
    # The filled rectangle's centre is the circle's centre, so the hole is at
    # exactly 0,0.
    hole = data.holes[0]
    assert (hole.x, hole.y) == (0.0, 0.0)


def test_a_bare_n_path_on_the_drill_layer_is_not_a_hole(tmp_path):
    """An unpainted circle is not a drilled one."""
    pdf = build_pdf(
        tmp_path / "nopaintdrill.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": circle_ops(200, 200, 20, paint="n") + " " + circle_ops(60, 35, 10),
        },
    )
    assert len(AiPdfSource(pdf).layer_subpaths("Drill")) == 1
    holes = AiPdfSource(pdf).read().holes
    assert len(holes) == 1
    assert holes[0].diameter == pytest.approx(mm_from_pt(20.0), abs=TOL_MM)


def test_a_bare_n_still_ends_the_path_it_discards(tmp_path):
    """``n`` paints nothing but *does* end the path; the next one starts clean.

    Dropping the operator instead of flushing on it would leave the discarded
    line pending, and the circle after it would come out as a two-subpath blob
    that no longer fits.
    """
    pdf = build_pdf(
        tmp_path / "discharge.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "10 10 m 90 90 l n " + circle_ops(60, 35, 10),
        },
    )
    paths = AiPdfSource(pdf).layer_subpaths("Drill")
    assert len(paths) == 1
    assert fit_circle(paths[0]) is not None
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_path_that_clips_and_paints_is_kept(tmp_path):
    """SPEC 6.3 discards ``W``/``W*`` *followed by* ``n``.

    ``W`` is not what makes a path invisible — ``n`` is. ``re W f`` is the
    ordinary way to fill a shape and clip the group to it at once, and it marks
    real ink. Throwing it away on the ``W`` alone left the panel outline
    missing and every hole measured from the page corner instead.
    """
    pdf = build_pdf(
        tmp_path / "clipfill.pdf",
        {
            "Background": "10 10 200 100 re W f",
            "Drill": circle_ops(60, 35, 10),
        },
    )
    data = AiPdfSource(pdf).read()
    assert data.reference is not None
    assert data.reference.width == pytest.approx(70.556, abs=TOL_MM)
    assert data.reference.height == pytest.approx(35.278, abs=TOL_MM)
    assert warnings(data) == []


def test_a_stroked_circle_that_also_clips_is_still_a_hole(tmp_path):
    """``h W S`` strokes the circle *and* clips to it — the stroke is the hole.

    Discarding it raised ``EmptyLayerError``, whose default message tells the
    operator to give the drill circles a stroke they had already given them.
    """
    pdf = build_pdf(
        tmp_path / "clipstroke.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": circle_ops(60, 35, 10, paint="W S"),
        },
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_clip_that_paints_nothing_is_still_discarded(tmp_path):
    """The other side of the same rule, kept honest: ``W n`` marks nothing.

    An artboard-sized ``re W n`` is what Illustrator brackets nearly every
    group with. If keeping ``W f`` were done by keeping every ``W``, this
    rectangle would out-area the panel and hijack the frame (SPEC 6.6).
    """
    pdf = build_pdf(
        tmp_path / "clipmixed.pdf",
        {
            "Background": "0 0 400 400 re W n 10 10 200 100 re W f",
            "Drill": "0 0 400 400 re W n " + circle_ops(60, 35, 10),
        },
    )
    data = AiPdfSource(pdf).read()
    assert len(AiPdfSource(pdf).layer_subpaths("Background")) == 1
    assert len(AiPdfSource(pdf).layer_subpaths("Drill")) == 1
    assert data.reference is not None
    assert data.reference.width == pytest.approx(70.556, abs=TOL_MM)


def test_clip_rectangles_cannot_become_the_reference_outline():
    """Ask for the frame from the drill layer: its only rectangles are clips."""
    data = AiPdfSource(FIXTURE, reference_layer="Drill").read()
    assert data.reference is None
    codes = [d.code for d in data.diagnostics]
    assert "reference-outline-not-found" in codes


def test_without_a_reference_the_frame_falls_back_to_the_page():
    """Coordinates stay honest: page space, measured from the MediaBox corner."""
    data = AiPdfSource(FIXTURE, reference_layer="Drill").read()
    assert data.centre == (0.0, 0.0)
    shifted = [(x + 148.4999, y + 105.0000, d) for x, y, d in EXPECTED_HOLES]
    match_multiset(data.holes, shifted)
    warning = next(d for d in data.diagnostics if d.code == "reference-outline-not-found")
    assert warning.severity is Severity.WARNING


def test_the_source_does_not_reuse_the_validate_stage_diagnostic_code():
    """One key, one meaning (SPEC 3): ``code`` is what consumers match on.

    ``CheckReferenceSize`` reports ``no-reference-outline`` at INFO for a
    different finding — there was nothing to check against. This one is the
    reference layer arriving with no usable outline, and it is a WARNING, which
    is what pushes the run to exit 1. Sharing the key made severity depend on
    which half of the pipeline happened to emit it.
    """
    data = AiPdfSource(FIXTURE, reference_layer="Drill").read()
    assert [d.code for d in data.diagnostics] == ["reference-outline-not-found"]


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


def test_unknown_drill_layer_lists_every_real_layer():
    with pytest.raises(LayerNotFoundError) as exc:
        AiPdfSource(FIXTURE, drill_layer="Holes").read()
    assert exc.value.wanted == "Holes"
    assert set(exc.value.available) == {"Background", "Drill", "Graphics", "Hardware"}
    for name in ("Background", "Drill", "Graphics", "Hardware"):
        assert name in str(exc.value)


def test_unknown_reference_layer_raises_too():
    with pytest.raises(LayerNotFoundError):
        AiPdfSource(FIXTURE, reference_layer="Panel").read()


def test_unknown_layer_in_layer_subpaths_raises():
    with pytest.raises(LayerNotFoundError):
        AiPdfSource(FIXTURE).layer_subpaths("Holes")


def test_drill_layer_with_paths_but_no_circles_says_so(tmp_path):
    """Drawn but not round: the operator must be sent to the shapes, not the swatches.

    Blaming "no fill and no stroke" here is a misdiagnosis — the line *is*
    stroked, it is simply not a circle — and it costs the operator a hunt
    through appearance settings that are already correct.
    """
    pdf = build_pdf(
        tmp_path / "empty.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "0 0 400 400 re W n 10 10 m 90 90 l S",
        },
    )
    with pytest.raises(EmptyLayerError) as exc:
        AiPdfSource(pdf).read()
    message = str(exc.value)
    assert exc.value.layer == "Drill"
    assert "1 path" in message
    assert "circle" in message
    assert "stroke" not in message


def test_a_layer_present_but_undrawn_blames_the_missing_paint(tmp_path):
    """The Illustrator trap: no fill and no stroke means no PDF stream at all."""
    pdf = build_pdf(
        tmp_path / "undrawn.pdf",
        {"Background": "10 10 100 50 re f", "Drill": ""},
    )
    with pytest.raises(EmptyLayerError) as exc:
        AiPdfSource(pdf).read()
    assert exc.value.layer == "Drill"
    assert "stroke" in str(exc.value)


def test_the_two_empty_layer_causes_read_differently(tmp_path):
    """One message for both causes sends half the users to the wrong place."""

    def message(content: str) -> str:
        pdf = build_pdf(
            tmp_path / f"cause{abs(hash(content))}.pdf",
            {"Background": "10 10 100 50 re f", "Drill": content},
        )
        with pytest.raises(EmptyLayerError) as exc:
            AiPdfSource(pdf).read()
        return str(exc.value)

    assert message("") != message("10 10 m 90 90 l S")


def test_non_circular_drill_geometry_is_reported_but_ignored(tmp_path):
    pdf = build_pdf(
        tmp_path / "mixed.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "10 10 m 90 90 l S " + circle_ops(60, 35, 10),
        },
    )
    data = AiPdfSource(pdf).read()
    assert len(data.holes) == 1
    note = next(d for d in data.diagnostics if d.code == "non-circular-path")
    assert note.severity is Severity.INFO


def test_a_pdf_without_layers_raises_layer_not_found(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(400, 400))
    pdf.save(tmp_path / "flat.pdf")
    with pytest.raises(LayerNotFoundError) as exc:
        AiPdfSource(tmp_path / "flat.pdf").read()
    assert exc.value.available == ()


# ---------------------------------------------------------------------------
# content-stream semantics the fixture cannot reach
# ---------------------------------------------------------------------------


def test_v_and_y_shorthand_curves_expand_correctly(tmp_path):
    """``v`` reuses the current point; ``y`` reuses the endpoint (SPEC 6, PDF 8.5.2.2).

    Swapping them is silent — the path still closes, it just bulges the wrong
    way — so this is asserted at segment level rather than through a circle.
    """
    pdf = build_pdf(
        tmp_path / "shorthand.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "10 10 m 20 20 30 10 v 40 0 50 10 y S " + circle_ops(60, 35, 10),
        },
    )
    paths = AiPdfSource(pdf).layer_subpaths("Drill")
    shorthand = next(p for p in paths if fit_circle(p) is None)
    assert shorthand.segments == (
        MoveTo((10.0, 10.0)),
        CurveTo(c1=(10.0, 10.0), c2=(20.0, 20.0), end=(30.0, 10.0)),
        CurveTo(c1=(40.0, 0.0), c2=(50.0, 10.0), end=(50.0, 10.0)),
    )


def test_the_ctm_is_applied(tmp_path):
    pdf = build_pdf(
        tmp_path / "ctm.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "q 2 0 0 2 100 100 cm " + circle_ops(0, 0, 5) + " Q",
        },
    )
    circle = fit_circle(AiPdfSource(pdf).layer_subpaths("Drill")[0])
    assert circle is not None
    assert (circle.cx, circle.cy) == (100.0, 100.0)
    assert circle.diameter == 20.0


def test_nested_cm_operators_compose_in_stream_order(tmp_path):
    """``cm`` concatenates *inside* the CTM already in force, not outside it.

    Composing the other way round survives every file whose outer matrix is a
    translation, then silently misplaces everything the first time one scales.
    """
    pdf = build_pdf(
        tmp_path / "nestedcm.pdf",
        {
            "Background": "10 10 380 380 re f",
            "Drill": "q 2 0 0 2 0 0 cm 1 0 0 1 50 0 cm " + circle_ops(0, 0, 5) + " Q",
        },
    )
    circle = fit_circle(AiPdfSource(pdf).layer_subpaths("Drill")[0])
    assert circle is not None
    # inner translate first: (0,0) -> (50,0) -> scaled -> (100,0)
    assert (circle.cx, circle.cy) == (100.0, 0.0)
    assert circle.diameter == 20.0


def test_the_ctm_stack_unwinds(tmp_path):
    """``Q`` restores; a circle after the restore must land unscaled."""
    pdf = build_pdf(
        tmp_path / "stack.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "q 3 0 0 3 0 0 cm Q " + circle_ops(50, 50, 5),
        },
    )
    circle = fit_circle(AiPdfSource(pdf).layer_subpaths("Drill")[0])
    assert circle is not None
    assert (circle.cx, circle.cy, circle.diameter) == (50.0, 50.0, 10.0)


def test_an_unbalanced_restore_does_not_crash(tmp_path):
    """The fixture's own stream pops past the base state; real files do this."""
    pdf = build_pdf(
        tmp_path / "underflow.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "Q Q " + circle_ops(50, 50, 5),
        },
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_form_xobjects_are_walked_with_their_matrix(tmp_path):
    """SPEC 6.5: the CTM must be applied inside Form XObjects too."""
    pdf = build_pdf(
        tmp_path / "form.pdf",
        {
            "Background": "0 0 400 400 re f",
            "Drill": "q 2 0 0 2 100 100 cm /Fm0 Do Q",
        },
        form=([1, 0, 0, 1, 10, 0], circle_ops(0, 0, 5)),
    )
    paths = AiPdfSource(pdf).layer_subpaths("Drill")
    assert len(paths) == 1
    circle = fit_circle(paths[0])
    assert circle is not None
    assert (circle.cx, circle.cy) == (120.0, 100.0)
    assert circle.diameter == 20.0


def test_the_source_is_re_exported_from_the_package_root():
    """There is no source registry, so the root is the only place to find one.

    ``aidrill`` exports the ``Source`` protocol, and ``AiPdfSource`` is the only
    thing that satisfies it. Nothing enumerates the implementations, so a
    consumer who cannot name it from the root cannot start the flow at all.
    """
    import aidrill

    assert aidrill.AiPdfSource is AiPdfSource
    assert "AiPdfSource" in aidrill.__all__


@pytest.mark.parametrize("paint", ["s", "b", "b*"])
def test_the_closing_painters_mark_ink(tmp_path, paint):
    """``s``, ``b`` and ``b*`` paint, so a circle ended by any of them is a hole.

    The stakes are higher than a misclassified path. An operator this source
    does not recognise as *ending* the path leaves it pending, so it is never
    flushed and the hole is absent from every artifact with nothing said — the
    silent-loss failure the whole module is arranged to avoid.
    """
    pdf = build_pdf(
        tmp_path / f"closepaint-{paint.replace('*', 'star')}.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": circle_ops(60, 35, 10, paint=paint),
        },
    )
    assert AiPdfSource(pdf).read().holes[0].diameter == pytest.approx(
        mm_from_pt(20.0), abs=TOL_MM
    )


def test_malformed_operators_are_skipped_not_fatal(tmp_path):
    """Half an operator is not worth losing the rest of the artwork over."""
    pdf = build_pdf(
        tmp_path / "malformed.pdf",
        {
            "Background": "10 10 100 50 re f 1 2 3 re f",
            "Drill": (
                "1 0 0 1 5 cm 10 m 10 10 m 20 l 1 2 3 4 5 c 1 2 3 v 1 2 3 y 1 2 3 re S "
                + circle_ops(60, 35, 10)
            ),
        },
    )
    data = AiPdfSource(pdf).read()
    assert len(data.holes) == 1
    assert data.reference is not None
    assert data.reference.width == mm_from_pt(100.0)


def test_a_do_that_names_nothing_is_ignored(tmp_path):
    pdf = build_pdf(
        tmp_path / "nodo.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "/Fm9 Do " + circle_ops(60, 35, 10),
        },
        form=([1, 0, 0, 1, 0, 0], ""),
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_do_without_any_xobject_resource_is_ignored(tmp_path):
    pdf = build_pdf(
        tmp_path / "noxobj.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "/Fm0 Do " + circle_ops(60, 35, 10),
        },
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_placed_image_is_not_walked_as_a_content_stream(tmp_path):
    """Illustrator files carry linked images; only Form XObjects hold paths."""
    pdf = build_pdf(
        tmp_path / "image.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "q 20 0 0 20 0 0 cm /Im0 Do Q " + circle_ops(60, 35, 10),
        },
        image=True,
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_marked_content_that_is_not_optional_content_carries_no_layer(tmp_path):
    """``BDC /Artifact`` and a dangling ``/OC`` name must not claim a layer."""
    pdf = build_pdf(
        tmp_path / "artifact.pdf",
        {"Background": "10 10 100 50 re f", "Drill": circle_ops(60, 35, 10)},
        extra=(
            " /Artifact <</Type /Pagination>> BDC " + circle_ops(200, 200, 20) + " EMC"
            " /OC /MC9 BDC " + circle_ops(300, 300, 20) + " EMC"
        ),
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_pdf_with_no_pages_raises_source_error(tmp_path):
    pdf = pikepdf.new()
    pdf.save(tmp_path / "blank.pdf")
    with pytest.raises(SourceError):
        AiPdfSource(tmp_path / "blank.pdf").read()


def test_geometry_outside_the_layer_is_ignored(tmp_path):
    """Marked content nesting decides membership — not proximity in the stream."""
    pdf = build_pdf(
        tmp_path / "outside.pdf",
        {"Background": "10 10 100 50 re f", "Drill": circle_ops(60, 35, 10)},
        extra="\n" + circle_ops(200, 200, 20),
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_nested_marked_content_keeps_the_layer(tmp_path):
    """``BMC``/``EMC`` inside a layer must not orphan the geometry it wraps."""
    pdf = build_pdf(
        tmp_path / "nested.pdf",
        {
            "Background": "10 10 100 50 re f",
            "Drill": "/Tx BMC " + circle_ops(60, 35, 10) + " EMC",
        },
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_an_unbalanced_emc_inside_a_form_does_not_unwind_the_caller(tmp_path):
    """A form inherits the layer stack; it must not be allowed to pop off it.

    ``/Fm0 Do`` is invoked inside ``BDC /OC /MC1``, so the form's own content is
    on the drill layer. An ``EMC`` the form never opened used to pop that
    inherited entry, and everything the form drew afterwards lost its layer —
    the drill circles simply vanished from the layer they were drawn on.
    """
    pdf = build_pdf(
        tmp_path / "emcform.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "/Fm0 Do",
        },
        form=([1, 0, 0, 1, 0, 0], "EMC " + circle_ops(60, 35, 10)),
    )
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_form_may_still_close_the_marked_content_it_opened(tmp_path):
    """The floor stops at the inherited depth; it does not freeze the stack.

    The form opens the Background layer, draws inside it, then closes it and
    draws again. That second circle belongs to the caller's layer only — a
    floor implemented as "never pop" would leave it on Background too.
    """
    pdf = build_pdf(
        tmp_path / "formbdc.pdf",
        {
            "Background": "10 10 200 100 re f",
            "Drill": "/Fm0 Do",
        },
        form=(
            [1, 0, 0, 1, 0, 0],
            "/OC /MC0 BDC " + circle_ops(60, 35, 10) + " EMC " + circle_ops(150, 35, 8),
        ),
    )
    assert len(AiPdfSource(pdf).layer_subpaths("Background")) == 2
    assert len(AiPdfSource(pdf).layer_subpaths("Drill")) == 2


def test_a_forms_own_properties_outrank_the_pages(tmp_path):
    """``/MCn`` means whatever the *current* resource dictionary says it means.

    Page and form both define ``/MC1``, and they define it differently: on the
    page it is Decor, inside the form it is Drill. The ``Do`` sits on Decor, so
    the two readings are distinguishable — the circle reaches the drill layer
    only if the form's own ``/Properties`` was consulted. Resolving it against
    the page's table instead leaves the circle on the layer the ``Do`` happens
    to be on, and the drill layer comes up short with nothing said.
    """
    pdf = build_pdf(
        tmp_path / "formprops.pdf",
        {"Background": "10 10 200 100 re f", "Decor": "/Fm0 Do", "Drill": ""},
        form=([1, 0, 0, 1, 0, 0], "/OC /MC1 BDC " + circle_ops(60, 35, 10) + " EMC"),
        form_properties={"/MC1": "Drill"},
    )
    source = AiPdfSource(pdf)
    assert len(source.layer_subpaths("Drill")) == 1
    # not lost, merely also on the layer the ``Do`` was invoked from
    assert len(source.layer_subpaths("Decor")) == 1


def test_a_form_without_its_own_resources_falls_back_to_the_pages(tmp_path):
    """Most forms carry no ``/Resources``, and their ``/MCn`` is still a layer.

    Illustrator writes plenty of them. With nothing to resolve the name against,
    every path the form draws is attributed to no layer at all — which is not an
    error anywhere, just a drill layer that quietly comes up short.
    """
    pdf = build_pdf(
        tmp_path / "formnoprops.pdf",
        {"Background": "10 10 200 100 re f", "Decor": "/Fm0 Do", "Drill": ""},
        form=([1, 0, 0, 1, 0, 0], "/OC /MC2 BDC " + circle_ops(60, 35, 10) + " EMC"),
    )
    assert len(AiPdfSource(pdf).layer_subpaths("Drill")) == 1


def test_lengths_arrive_in_millimetres(tmp_path):
    """72 pt to the inch: the source names the unit, and the name is millimetres.

    283.4646 pt is 100 mm to four decimals, and the panel is built out of the
    point values a drawing tool would write for a round metric size — so a
    source that forgot the conversion, or applied it twice, misses by a factor
    of 2.8 rather than by anything a tolerance argument could cover.
    """
    pdf = build_pdf(
        tmp_path / "units.pdf",
        {
            "Background": "0 0 283.4646 141.7323 re f",  # 100 x 50 mm
            "Drill": circle_ops(141.7323 + 28.34646, 70.86615, 14.17323),
        },
    )
    data = AiPdfSource(pdf).read()
    assert data.reference is not None
    assert data.reference.width == pytest.approx(100.0, abs=TOL_MM)
    assert data.reference.height == pytest.approx(50.0, abs=TOL_MM)
    hole = data.holes[0]
    assert (hole.x, hole.y, hole.diameter) == pytest.approx((10.0, 0.0, 10.0), abs=TOL_MM)


def test_y_is_up(tmp_path):
    """PDF user space is Y-up from the MediaBox corner, and stays that way."""
    pdf = build_pdf(
        tmp_path / "yup.pdf",
        {
            "Background": "0 0 200 100 re f",
            "Drill": circle_ops(100, 80, 5),  # above the outline's centre
        },
    )
    assert AiPdfSource(pdf).read().holes[0].y > 0.0


def test_a_non_zero_mediabox_origin_is_handled(tmp_path):
    """Positions are relative to the reference outline, so the corner cancels."""
    pdf = build_pdf(
        tmp_path / "offset.pdf",
        {
            "Background": "100 100 200 100 re f",
            "Drill": circle_ops(210, 150, 10),
        },
        media=(100, 100, 500, 400),
    )
    data = AiPdfSource(pdf).read()
    assert data.holes[0].x == pytest.approx(mm_from_pt(10.0), abs=TOL_MM)
    assert data.holes[0].y == 0.0


def test_the_largest_non_circular_path_wins(tmp_path):
    pdf = build_pdf(
        tmp_path / "largest.pdf",
        {
            "Background": "0 0 20 20 re f 0 0 283.4646 141.7323 re f 5 5 30 30 re f",
            "Drill": circle_ops(141.7323, 70.86615, 10),
        },
    )
    reference = AiPdfSource(pdf).read().reference
    assert reference is not None
    assert reference.width == pytest.approx(100.0, abs=TOL_MM)


def test_circles_on_the_reference_layer_are_not_the_outline(tmp_path):
    """The fixture's Background carries two 12 mm circles beside the outline."""
    pdf = build_pdf(
        tmp_path / "refcircles.pdf",
        {
            "Background": circle_ops(200, 200, 190) + " 0 0 283.4646 141.7323 re f",
            "Drill": circle_ops(141.7323, 70.86615, 10),
        },
    )
    reference = AiPdfSource(pdf).read().reference
    assert reference is not None
    assert reference.width == pytest.approx(100.0, abs=TOL_MM)


def test_the_source_rounds_nothing(data):
    """What comes back is the measurement, and no quantiser's opinion of it.

    ``113.00001388888887`` is the panel as ``tar.ai`` draws it. What the value
    rules out is every rounding that could have been done early: 113.000014 is
    the outline put through the nanometre boundary before anything asked it to
    be, and 112 is the outline snapped to the Hammond footprint it turns out to
    match. That snap is ``IdentifyHammondFootprint``'s to make, and it needs a
    measurement to make it from — a source that pre-empted either rounding
    would leave the stage choosing a case from a number already moved.

    ``float``, because ``RawOutline`` refuses an ``int``: the JSON emitter and
    the drawing both print the measurement, so a nanometre count reaching a
    millimetre field puts 113 000 014.000 mm on a sheet a machinist reads.

    The two rulings out are not worth the same. A pre-empted *footprint* snap
    changes every artifact — the panel becomes a 112 mm one. A pre-empted
    *nanometre* rounding changes none: both spellings print 113.000, and the
    half nanometre between them cannot flip which grid multiple, drill size or
    catalogue footprint is nearest. So the trailing digits here are an
    architectural tripwire and are kept deliberately as one, not a claim that
    the precision matters. Do not build anything else on them.
    """
    reference = data.reference
    assert reference is not None
    assert type(reference.width) is float
    assert reference.width == 113.00001388888887


def test_fixture_reference_matches_its_measured_outline(data):
    """Cross-check: the frame centre is where the drill row says it is."""
    row = [h for h in data.holes if abs(h.y - 18.0) <= TOL_MM]
    assert len(row) == 6
    assert abs(min(h.x for h in row) - (-39.9906)) <= TOL_MM
    assert abs(max(h.x for h in row) - 40.0000) <= TOL_MM
