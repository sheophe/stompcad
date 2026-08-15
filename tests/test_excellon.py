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
    assert out[5] == "T1C5.000"
    assert out[6] == "T2C7.000"
    assert out[7] == "%"
    assert out[8] == "G90"
    assert out[9] == "G05"
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
    """If the pipeline chose ``NoNormalization`` the emitter must still report
    every nominal it was handed — deciding two sizes are 'really' one is a
    pipeline decision, and no longer this module's business."""
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
    data = make_data(at(0.0, 0.0, 7.0, index=0))

    with pytest.raises(EmitterError):
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
