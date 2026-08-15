"""Tests for the Excellon emitter (SPEC §7, PLAN task D).

The regression this file exists to guard is spelled out in SPEC §2: an earlier
version of this tool clustered near-identical measured diameters *inside* the
Excellon writer, so a panel drawn with one 7 mm bit came back as ``T2C7.000``
and ``T3C7.000`` — the same bit loaded twice, two drilling passes. Normalisation
now belongs to the pipeline. The emitter reads ``DrillData.tools()`` and
serialises; it must not round, cluster, dedupe or renumber anything.
"""

from __future__ import annotations

import re

import pytest

from aidrill.emitters.base import REGISTRY, get_emitter
from aidrill.emitters.excellon import ExcellonEmitter, ExcellonOptions
from aidrill.errors import EmitterError
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    Origin,
    RawHole,
    ReferenceOutline,
    SourceInfo,
    Units,
)
from aidrill.protocols import Emitter
from tests.conftest import at, holes, make_data

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

TOOL_DEF = re.compile(r"^T(\d+)C([0-9.]+)$")


def fixture_data() -> DrillData:
    """The ``tests/fixtures/tar.ai`` ground truth from SPEC §9.

    Reference outline 113.000 x 60.000 mm; five ⌀7.00 at y = +18.00 and two
    ⌀5.00 at y = −18.75, already snapped, normalised, deduped and sorted by the
    pipeline. Exactly two distinct tools.
    """
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
        reference=ReferenceOutline(width=113.0, height=60.0),
        diagnostics=(
            Diagnostic.warning("duplicate-hole", "1 coincident hole collapsed", (-40.0, 18.0)),
        ),
        source=SourceInfo(path="tests/fixtures/tar.ai", drill_layer="Drill"),
    )


def lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def tool_definitions(text: str) -> dict[int, str]:
    """{tool number: diameter as written} from the header's ``T..C..`` lines."""
    out: dict[int, str] = {}
    for line in lines(text):
        m = TOOL_DEF.match(line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def emit(data: DrillData, **kwargs) -> str:
    options = ExcellonOptions(**kwargs) if kwargs else None
    return ExcellonEmitter(options).emit(data)


# --------------------------------------------------------------------------
# registration and protocol conformance
# --------------------------------------------------------------------------


def test_emitter_self_registers_as_excellon():
    import aidrill.emitters  # noqa: F401  (importing the package must register)

    assert REGISTRY["excellon"] is ExcellonEmitter
    assert get_emitter("excellon") is ExcellonEmitter


def test_emitter_declares_name_media_type_and_extension():
    assert ExcellonEmitter.name == "excellon"
    assert ExcellonEmitter.media_type
    assert ExcellonEmitter.extension.startswith(".")
    assert isinstance(ExcellonEmitter(), Emitter)


def test_default_options_match_the_spec():
    options = ExcellonOptions()
    assert options.origin is Origin.LOWER_LEFT
    assert options.units is Units.MILLIMETRES
    assert options.decimals == 3


# --------------------------------------------------------------------------
# file structure
# --------------------------------------------------------------------------


def test_header_and_footer_appear_in_the_documented_order():
    out = lines(emit(fixture_data()))

    assert out[0] == "M48"
    assert out[1].startswith(";DRILL file for ")
    assert out[2] == ";FORMAT={-:-/ absolute / metric / decimal}"
    assert out[3] == "FMAT,2"
    assert out[4] == "METRIC,TZ"
    assert out[5].startswith(";ORIGIN=")
    assert out[6] == "T1C5.000"
    assert out[7] == "T2C7.000"
    assert out[8] == "%"
    assert out[9] == "G90"
    assert out[10] == "G05"
    assert out[-2] == "T0"
    assert out[-1] == "M30"


def test_output_ends_with_a_newline():
    assert emit(fixture_data()).endswith("M30\n")


def test_title_comment_uses_the_option_then_falls_back_to_the_source_path():
    assert ";DRILL file for Tar panel" in emit(fixture_data(), title="Tar panel")
    assert ";DRILL file for tests/fixtures/tar.ai" in emit(fixture_data())


def test_data_without_holes_still_produces_a_valid_file():
    data = make_data(reference=ReferenceOutline(113.0, 60.0))
    out = lines(emit(data))

    assert out[0] == "M48"
    assert tool_definitions(emit(data)) == {}
    assert out[-2:] == ["T0", "M30"]


# --------------------------------------------------------------------------
# THE regression: one tool per nominal diameter, numbering owned by the model
# --------------------------------------------------------------------------


def test_regression_no_two_tool_definitions_share_a_diameter():
    """SPEC §9 invariant. 6.9998 and 7.0000 were normalised to one nominal by the
    pipeline; the file must therefore load one 7 mm bit, once."""
    normalised = (
        Hole(x=-40.0, y=18.0, diameter=7.0, raw=RawHole(-40.0, 18.0, 6.9998), index=0),
        Hole(x=-20.0, y=18.0, diameter=7.0, raw=RawHole(-20.0, 18.0, 7.0000), index=1),
        at(0.0, -18.75, 5.0, index=2),
    )
    data = make_data(*normalised, reference=ReferenceOutline(113.0, 60.0))

    definitions = tool_definitions(emit(data))

    assert len(definitions) == 2
    assert len(set(definitions.values())) == len(definitions), definitions
    assert sorted(definitions.values()) == ["5.000", "7.000"]


def test_regression_holds_for_the_fixture():
    definitions = tool_definitions(emit(fixture_data()))

    assert len(definitions) == 2
    assert len(set(definitions.values())) == len(definitions)


def test_tool_numbers_are_exactly_drilldata_tools():
    data = fixture_data()
    definitions = tool_definitions(emit(data))

    assert definitions == {number: f"{d:.3f}" for d, number in data.tools().items()}
    assert sorted(definitions) == list(range(1, len(data.tools()) + 1))


def test_emitter_does_not_cluster_diameters_the_pipeline_kept_apart():
    """Two nominals 0.002 mm apart are two tools, because the pipeline handed
    over two. Deciding that two sizes are 'really' one is a pipeline decision
    taken once, before any emitter sees the data; an emitter that took it again
    could define a different number of bits than the drawing lists — ADR-0001's
    incident exactly."""
    data = make_data(
        at(-10.0, 0.0, 6.998, index=0),
        at(10.0, 0.0, 7.000, index=1),
        reference=ReferenceOutline(113.0, 60.0),
    )

    definitions = tool_definitions(emit(data))

    assert definitions == {1: "6.998", 2: "7.000"}
    assert len(definitions) == len(data.tools())


def test_emitter_does_not_renumber_after_a_gap_in_diameters():
    data = make_data(
        at(0.0, 0.0, 3.2, index=0),
        at(10.0, 0.0, 12.5, index=1),
        at(20.0, 0.0, 5.0, index=2),
        reference=ReferenceOutline(113.0, 60.0),
    )

    assert tool_definitions(emit(data)) == {1: "3.200", 2: "5.000", 3: "12.500"}


def test_emitter_does_not_deduplicate_coincident_holes():
    """Deduplication is ``pipeline.Deduplicate``'s job. If two coincident holes
    survive to the emitter, the operator asked for two hits."""
    data = make_data(
        at(0.0, 0.0, 7.0, index=0),
        at(0.0, 0.0, 7.0, index=1),
        reference=ReferenceOutline(113.0, 60.0),
    )

    out = lines(emit(data))

    assert out.count("X56.500Y30.000") == 2


# --------------------------------------------------------------------------
# representability: two nominals the chosen format cannot tell apart
# --------------------------------------------------------------------------


def test_two_nominals_that_render_to_the_same_token_are_refused():
    """A measured 6.9998 and 7.0000 that no stage merged are two tools to the
    model and one ``C7.000`` on the page — the ``T2C7.000`` / ``T3C7.000`` defect
    reached through formatting instead of clustering. The message must name both
    nominals and the token, so the operator need not re-derive the collision;
    lookaheads rather than a sequence, because the order it names them in is
    presentation, and a test that fails when prose is reordered is a nuisance."""
    data = make_data(
        at(0.0, 0.0, 6.9998, index=1),
        at(10.0, 0.0, 7.0000, index=3),
        reference=ReferenceOutline(50.0, 50.0),
    )

    assert len(data.tools()) == 2  # the model still sees two nominals

    with pytest.raises(EmitterError, match=r"(?=.*6\.9998)(?=.*\b7\.0\b)(?=.*C7\.000)"):
        emit(data)


def test_inch_output_refuses_diameters_it_cannot_separate():
    """The collision depends on the units, so the token must be built *after*
    conversion. ``decimals=3`` in inches is only 0.0254 mm of resolution: 3.02
    and 3.03 mm are two comfortably distinct tools in millimetres and one
    ``0.119`` in inches."""
    data = make_data(
        at(0.0, 0.0, 3.02, index=0),
        at(10.0, 0.0, 3.03, index=1),
        reference=ReferenceOutline(50.0, 50.0),
    )

    assert tool_definitions(emit(data)) == {1: "3.020", 2: "3.030"}  # fine in mm

    with pytest.raises(EmitterError, match="0.119"):
        emit(data, units=Units.INCHES)


def test_raising_the_precision_makes_the_same_two_nominals_representable():
    """The refusal is about representability, not about clustering. The emitter
    must never quietly raise the precision itself — but when the caller does,
    the very same data emits, with two genuinely distinct tools."""
    data = make_data(
        at(0.0, 0.0, 6.9998, index=1),
        at(10.0, 0.0, 7.0000, index=3),
        reference=ReferenceOutline(50.0, 50.0),
    )

    assert tool_definitions(emit(data, decimals=4)) == {1: "6.9998", 2: "7.0000"}


# --------------------------------------------------------------------------
# a finding the pipeline already made: ERROR means no drill file
# --------------------------------------------------------------------------


def error_bearing_data() -> DrillData:
    """What ``SnapDiametersToDrillTable`` leaves behind after a bad diameter.

    Two holes were drawn; the ⌀7 matched no size in the declared standard, so
    the stage recorded an ERROR and *dropped it*. Only the ⌀5 remains, and the
    surviving hole keeps its own identity — 6, not 0 — so nothing here can be
    read as a position in the tuple.
    """
    return make_data(
        at(-19.0, -18.75, 5.0, index=6), reference=ReferenceOutline(113.0, 60.0)
    ).with_diagnostics(
        Diagnostic.error(
            "unknown-diameter",
            "hole 2: dia 7.000 mm matches no metric drill size",
            (0.0, 18.0),
            data=(("hole_index", 2), ("diameter", 7.0)),
        )
    )


def test_data_carrying_an_error_is_refused_rather_than_written():
    """The CLI checks ``worst_severity`` before it renders; a library consumer
    calling the emitter directly does not, and this is the emitter that cannot
    afford it. Excellon renders no diagnostics whatsoever, so the file left by
    a dropped hole is not a damaged file a machinist would question — it is a
    complete-looking drill file for a panel with one hole fewer than the artwork
    has. The refusal names the code, so the caller need not re-derive why."""
    with pytest.raises(EmitterError, match="unknown-diameter"):
        emit(error_bearing_data())


def test_the_refusal_names_every_distinct_error_code_once():
    """Two findings of one code and one of another: the caller is told what is
    wrong with the data, not handed a repetition of the commonest failure."""
    data = error_bearing_data().with_diagnostics(
        Diagnostic.error("unknown-diameter", "another one", (10.0, 18.0)),
        Diagnostic.error("wrong-enclosure", "declared 1590B, drawn 1590BB"),
    )

    with pytest.raises(EmitterError) as raised:
        emit(data)

    text = str(raised.value)
    assert text.count("unknown-diameter") == 1
    assert "wrong-enclosure" in text


def test_warnings_and_information_still_produce_a_drill_file():
    """The refusal is about ERROR, not about diagnostics. A duplicate-hole
    warning is the fixture's ordinary state and exits 1 with artifacts written;
    a guard keyed on ``data.diagnostics`` rather than on their severity would
    refuse the panel this project ships as its worked example."""
    data = make_data(
        at(0.0, 18.0, 7.0, index=3), reference=ReferenceOutline(113.0, 60.0)
    ).with_diagnostics(
        Diagnostic.warning("duplicate-hole", "1 coincident hole collapsed", (0.0, 18.0)),
        Diagnostic.info("no-reference-outline", "nothing to check against"),
    )

    assert "X56.500Y48.000" in lines(emit(data))


# --------------------------------------------------------------------------
# representability again: a value no coordinate can carry
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_x_is_refused(value):
    """``format_mm(nan)`` is ``"nan"`` and ``format_mm(inf)`` is ``"inf"``:
    neither starts with a minus, so the lower-left promise sees nothing wrong
    and ``Xnan`` reaches the file. It is syntactically plausible and drills
    nowhere. ``-inf`` is checked here too, because it *is* caught by the sign
    test — as a hole outside the outline, which is the wrong diagnosis of a
    value that is not a position at all."""
    data = make_data(
        at(value, 0.0, 7.0, index=8), reference=ReferenceOutline(50.0, 50.0)
    )

    with pytest.raises(EmitterError, match=r"hole 8\b.*non-finite"):
        emit(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_y_is_refused(value):
    """The other axis, alone, so a check that lost half of itself is visible."""
    data = make_data(
        at(0.0, value, 7.0, index=5), reference=ReferenceOutline(50.0, 50.0)
    )

    with pytest.raises(EmitterError, match=r"hole 5\b.*non-finite"):
        emit(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_non_finite_diameter_is_refused(value):
    """``T1Cnan`` is the same defect one column over: the tool table is where a
    machinist reads which bit to load."""
    data = make_data(
        at(0.0, 0.0, value, index=2), reference=ReferenceOutline(50.0, 50.0)
    )

    with pytest.raises(EmitterError, match=r"hole 2\b.*non-finite"):
        emit(data)


def test_a_non_finite_coordinate_is_refused_in_the_centre_frame_too():
    """Nothing about ``Xnan`` is a lower-left concern. The sign test returns
    early for CENTRE — correctly, because negative coordinates are the whole
    point of that frame — so a check folded into it would pass ``nan`` straight
    through whenever the caller asked for the canonical frame."""
    data = make_data(at(0.0, float("nan"), 7.0, index=1))

    with pytest.raises(EmitterError, match="non-finite"):
        emit(data, origin=Origin.CENTRE)


def test_a_non_finite_reference_outline_is_refused_through_its_holes():
    """The holes are finite; the frame they are translated into is not. The
    check therefore reads the reframed data, which is what will be written,
    rather than the data as handed in."""
    data = make_data(
        at(0.0, 0.0, 7.0, index=4), reference=ReferenceOutline(float("nan"), 60.0)
    )

    with pytest.raises(EmitterError, match=r"hole 4\b.*non-finite"):
        emit(data)


# --------------------------------------------------------------------------
# coordinates: frame, order, grouping
# --------------------------------------------------------------------------


def test_a_hole_outside_the_reference_outline_is_refused_in_lower_left():
    """SPEC §7 promises LOWER_LEFT keeps every coordinate positive. A hole
    outside the reference outline breaks that promise silently — the file still
    parses, and the machine drives off the fixture. The offender is named by
    ``index``, the stable identity, not by position in the tuple.

    Both axes are exercised, one alone each time: a check that tested only the
    pair would still pass while half of it was missing, and a hole to the left
    of the outline is at least as likely in the field as one below it.
    """
    y_only = make_data(
        at(0.0, 0.0, 5.0, index=9),
        at(0.0, -60.0, 5.0, index=4),
        reference=ReferenceOutline(50.0, 50.0),
    )

    with pytest.raises(EmitterError, match=r"hole 4\b"):
        emit(y_only)

    x_only = make_data(
        at(-60.0, 0.0, 5.0, index=7), reference=ReferenceOutline(50.0, 50.0)
    )

    with pytest.raises(EmitterError, match=r"hole 7\b"):
        emit(x_only)


def test_a_hole_a_fraction_of_a_print_unit_outside_the_outline_is_not_refused():
    """The promise is about the coordinates as *written*, so the check reads the
    rendered token, not the float behind it. A hole four ten-thousandths of a
    millimetre past the edge prints ``0.000`` and drills exactly where it should;
    refusing it would turn representation noise into an operator-facing failure.
    """
    data = make_data(
        at(-25.0004, 0.0, 7.0, index=0), reference=ReferenceOutline(50.0, 50.0)
    )

    assert "X0.000Y25.000" in lines(emit(data))


def test_lower_left_matches_the_fixture_ground_truth():
    """113.0 x 60.0 reference: canonical (−40.0, +18.0) → X16.500 Y48.000."""
    out = lines(emit(fixture_data()))

    assert "X16.500Y48.000" in out
    assert "X37.500Y11.250" in out  # the ⌀5 at (−19.0, −18.75)


def test_lower_left_keeps_every_coordinate_non_negative():
    for line in lines(emit(fixture_data())):
        if line.startswith("X"):
            x, y = re.match(r"^X(-?[0-9.]+)Y(-?[0-9.]+)$", line).groups()
            assert float(x) >= 0.0 and float(y) >= 0.0, line


def test_a_coordinate_that_rounds_to_zero_never_prints_a_negative_zero():
    """Shared with the drawing's schedule via ``formatting.format_mm``."""
    out = lines(emit(make_data(at(-0.0004, -0.0004, 7.0, index=0)), origin=Origin.CENTRE))

    assert "X0.000Y0.000" in out
    assert not any("-0.000" in line for line in out)


def test_lower_left_without_a_reference_outline_raises_emitter_error():
    """The message is asserted, not merely the exception type.

    Without it this test cannot tell its own guard from the one two lines
    below: strip the check and ``with_origin``'s ``ValueError`` is caught and
    re-raised as an ``EmitterError`` just the same, so a bare ``pytest.raises``
    stays green while the only thing the guard produces — the sentence telling
    the caller which of the two ways out to take — has gone.
    """
    data = make_data(at(0.0, 0.0, 7.0, index=0))

    with pytest.raises(EmitterError, match="origin=Origin.CENTRE or supply a reference layer"):
        emit(data)


def test_an_origin_the_model_rejects_surfaces_as_an_emitter_error():
    """Frame translation is delegated to ``DrillData.with_origin``; whatever it
    refuses to do must reach the caller as an emitter failure, not a ValueError
    leaking the model's internals."""
    data = fixture_data()

    with pytest.raises(EmitterError, match="unknown origin"):
        ExcellonEmitter(ExcellonOptions(origin="upper-right")).emit(data)


def test_centre_origin_leaves_the_canonical_frame_alone():
    out = lines(emit(fixture_data(), origin=Origin.CENTRE))

    assert "X-40.000Y18.000" in out


def test_centre_origin_needs_no_reference_outline():
    data = make_data(at(-5.0, -5.0, 7.0, index=0))

    assert "X-5.000Y-5.000" in lines(emit(data, origin=Origin.CENTRE))


def test_the_header_says_which_frame_the_coordinates_are_in():
    """The drill file and the sheet beside it describe one panel in two frames.

    The fixture's first ⌀7 is ``-40.00, 18.00`` on the drawing and in the JSON,
    and ``X16.500Y48.000`` here: every number differs, by exactly the half-width
    and half-height of the outline. The file already declares ``absolute``,
    ``metric`` and ``decimal`` and says nothing at all about where zero is, so
    a machinist cross-checking the two documents has nothing to reconcile them
    with. The shift is stated as well as the corner, because naming the frame
    only tells them *that* the numbers differ.
    """
    out = lines(emit(fixture_data()))
    stated = [ln for ln in out if ln.startswith(";ORIGIN=")]

    assert len(stated) == 1
    assert "lower-left" in stated[0]
    assert "56.500" in stated[0] and "30.000" in stated[0]
    assert "X16.500Y48.000" in out  # the frame it actually wrote


def test_the_header_says_centre_when_the_centre_frame_was_written():
    """Two frames, two statements. A header hard-coding the common one would be
    wrong precisely for the caller who asked for the other."""
    out = lines(emit(fixture_data(), origin=Origin.CENTRE))
    stated = [ln for ln in out if ln.startswith(";ORIGIN=")]

    assert len(stated) == 1
    assert "centre" in stated[0]
    assert "lower-left" not in stated[0]
    assert "X-40.000Y18.000" in out


def test_the_stated_shift_is_in_the_units_the_file_is_written_in():
    """56.500 mm is 2.224 inches. A shift stated in millimetres in an inch file
    would be a second frame statement disagreeing with the coordinates under
    it — the disagreement this line exists to end."""
    stated = [ln for ln in lines(emit(fixture_data(), units=Units.INCHES)) if ln.startswith(";ORIGIN=")]

    assert f"{56.5 * Units.INCHES.per_mm:.3f}" in stated[0]
    assert "56.500" not in stated[0]


def test_coordinates_are_grouped_under_their_tool_ascending_by_diameter():
    out = lines(emit(fixture_data()))
    body = out[out.index("G05") + 1 :]

    assert body[0] == "T1"
    assert body[1:3] == ["X37.500Y11.250", "X75.500Y11.250"]  # the two ⌀5
    assert body[3] == "T2"
    assert len(body[4:-2]) == 5  # the five ⌀7
    assert body[-2:] == ["T0", "M30"]


def test_hole_order_is_preserved_not_re_sorted():
    """Ordering is ``pipeline.SortHoles``' decision, not this emitter's.

    The emitter used to carry a byte-identical copy of ``_reading_order`` and
    apply it unconditionally, so any order the pipeline chose — a custom
    ``SortHoles`` key, or none at all — was silently discarded. The drawing's
    balloon numbers and the JSON both follow pipeline order; a drill file that
    does not is a drill file whose sequence disagrees with the sheet beside it.
    """
    data = make_data(
        at(10.0, -10.0, 7.0, index=0),
        at(-10.0, 10.0, 7.0, index=1),
        at(10.0, 10.0, 7.0, index=2),
        at(-10.0, -10.0, 7.0, index=3),
        reference=ReferenceOutline(100.0, 100.0),
    )

    out = lines(emit(data))
    coords = [ln for ln in out if ln.startswith("X")]

    assert coords == [
        "X60.000Y40.000",
        "X40.000Y60.000",
        "X60.000Y60.000",
        "X40.000Y40.000",
    ]


def test_tool_blocks_stay_ascending_while_order_inside_them_is_untouched():
    """Grouping is the emitter's job; sequence is not."""
    data = make_data(
        at(0.0, -20.0, 7.0, index=0),
        at(-30.0, 20.0, 5.0, index=1),
        at(30.0, 20.0, 7.0, index=2),
        at(0.0, 20.0, 5.0, index=3),
        reference=ReferenceOutline(100.0, 100.0),
    )

    out = lines(emit(data))
    body = out[out.index("G05") + 1 : -2]

    assert body == [
        "T1",
        "X20.000Y70.000",  # the ⌀5, in the order the pipeline left them
        "X50.000Y70.000",
        "T2",
        "X50.000Y30.000",  # the ⌀7, likewise — not reading order
        "X80.000Y70.000",
    ]


def test_decimals_option_controls_coordinate_and_diameter_precision():
    out = lines(emit(fixture_data(), decimals=4))

    assert "T1C5.0000" in out
    assert "X16.5000Y48.0000" in out


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def test_inches_write_inch_tz_and_divide_by_25_4():
    out = lines(emit(fixture_data(), units=Units.INCHES))

    assert "INCH,TZ" in out
    assert "METRIC,TZ" not in out
    assert ";FORMAT={-:-/ absolute / inch / decimal}" in out
    assert f"T1C{5.0 / 25.4:.3f}" in out
    assert f"X{16.5 / 25.4:.3f}Y{48.0 / 25.4:.3f}" in out


def test_inch_conversion_uses_the_models_units_per_mm():
    out = emit(fixture_data(), units=Units.INCHES, decimals=5)

    assert f"T2C{7.0 * Units.INCHES.per_mm:.5f}" in lines(out)


# --------------------------------------------------------------------------
# purity
# --------------------------------------------------------------------------


def test_emit_does_not_mutate_the_input_data():
    data = fixture_data()
    before = tuple(data.holes)

    emit(data)

    assert data.holes == before
    assert data.holes[0].x == -40.0


def test_emit_is_deterministic():
    data = fixture_data()

    assert emit(data) == emit(data)
