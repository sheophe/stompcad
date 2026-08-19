"""Tests for Excellon emission from quantised drill data."""

from __future__ import annotations

import re

import pytest

from stompdrill.emitters.base import REGISTRY, get_emitter
from stompdrill.emitters.excellon import ExcellonEmitter, ExcellonOptions
from stompdrill.errors import EmitterError
from stompdrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    Origin,
    RawHole,
    ReferenceOutline,
    SourceInfo,
)
from stompdrill.protocols import Emitter
from stompdrill.units import Millimetre, Nanometre, format_nm
from tests.conftest import at, holes, make_data

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

TOOL_DEF = re.compile(r"^T(\d+)C([0-9.]+)$")


def fixture_data() -> DrillData:
    """Return the expected quantised data for ``tests/fixtures/tar.ai``."""
    return DrillData(
        holes=holes(
            (-40_000_000, 18_000_000),
            (-20_000_000, 18_000_000),
            (0, 18_000_000),
            (20_000_000, 18_000_000),
            (40_000_000, 18_000_000),
            (-19_000_000, -18_750_000, 5_000_000),
            (19_000_000, -18_750_000, 5_000_000),
        ),
        reference=ReferenceOutline(width_nm=Nanometre(113_000_000), height_nm=Nanometre(60_000_000)),
        diagnostics=(
            Diagnostic.warning(
                "duplicate-hole", "1 coincident hole collapsed", (-40_000_000, 18_000_000)
            ),
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
    import stompdrill.emitters  # noqa: F401  (importing the package must register)

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
    data = make_data(reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)))
    out = lines(emit(data))

    assert out[0] == "M48"
    assert tool_definitions(emit(data)) == {}
    assert out[-2:] == ["T0", "M30"]


@pytest.mark.parametrize("origin", [Origin.LOWER_LEFT, Origin.CENTRE])
def test_the_emitter_refuses_data_that_was_never_routed(origin):
    """ADR-0006: an emitter given unrouted data raises, on every path — not
    only ``LOWER_LEFT``, whose negative-coordinate check happens to call
    ``numbered()``. ``CENTRE`` must refuse too, or it would emit artwork order
    as if it were a drilling sequence.
    """
    data = make_data(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
                     reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)))
    with pytest.raises(EmitterError, match="RouteHoles"):
        emit(data, origin=origin)


# --------------------------------------------------------------------------
# one tool per nominal diameter, numbering owned by the model
# --------------------------------------------------------------------------


def test_regression_no_two_tool_definitions_share_a_diameter():
    """The pipeline maps 6.9998 and 7.0000 mm to one nominal and one tool."""
    normalised = (
        Hole(
            x_nm=Nanometre(-40_000_000),
            y_nm=Nanometre(18_000_000),
            diameter_nm=Nanometre(7_000_000),
            raw=RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(6.9998)),
            index=1,
        ),
        Hole(
            x_nm=Nanometre(-20_000_000),
            y_nm=Nanometre(18_000_000),
            diameter_nm=Nanometre(7_000_000),
            raw=RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0000)),
            index=2,
        ),
        at(0, -18_750_000, 5_000_000, index=3),
    )
    data = make_data(*normalised, reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)))

    definitions = tool_definitions(emit(data))

    assert len(definitions) == 2
    assert len(set(definitions.values())) == len(definitions), definitions
    assert sorted(definitions.values()) == ["5.000", "7.000"]


def test_regression_holds_for_the_fixture():
    definitions = tool_definitions(emit(fixture_data()))

    assert len(definitions) == 2
    assert len(set(definitions.values())) == len(definitions)


def test_tool_numbers_are_exactly_drilldata_tools():
    """The table written is the model's table, size for size and number for number."""
    data = make_data(
        at(0, 0, 12_500_000, index=4),
        at(10_000_000, 0, 3_200_000, index=1),
        at(20_000_000, 0, 5_000_000, index=9),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    )
    definitions = tool_definitions(emit(data))

    assert definitions == {
        number: format_nm(diameter_nm, 3) for diameter_nm, number in data.tools().items()
    }
    assert sorted(definitions) == list(range(1, len(data.tools()) + 1))
    assert list(definitions.values()) == ["3.200", "5.000", "12.500"]


def test_the_tool_table_is_read_from_the_model_and_not_re_derived(monkeypatch):
    """The numbering is looked up, not recomputed to agree."""
    data = make_data(
        at(0, 0, 7_000_000, index=5),
        at(10_000_000, 0, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)),
    )
    monkeypatch.setattr(DrillData, "tools", lambda self: {7_000_000: 4, 5_000_000: 9})

    text = emit(data)
    body = lines(text)[lines(text).index("G05") + 1 : -2]

    assert tool_definitions(text) == {4: "7.000", 9: "5.000"}
    assert body == ["T4", "X50.000Y50.000", "T9", "X60.000Y50.000"]


def test_emitter_does_not_cluster_diameters_the_pipeline_kept_apart():
    """The emitter preserves two nominals only 0.002 mm apart as two tools."""
    data = make_data(
        at(-10_000_000, 0, 6_998_000, index=1),
        at(10_000_000, 0, 7_000_000, index=2),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    )

    definitions = tool_definitions(emit(data))

    assert definitions == {1: "6.998", 2: "7.000"}
    assert len(definitions) == len(data.tools())


def test_emitter_does_not_renumber_after_a_gap_in_diameters():
    data = make_data(
        at(0, 0, 3_200_000, index=1),
        at(10_000_000, 0, 12_500_000, index=2),
        at(20_000_000, 0, 5_000_000, index=3),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    )

    assert tool_definitions(emit(data)) == {1: "3.200", 2: "5.000", 3: "12.500"}


def test_emitter_does_not_deduplicate_coincident_holes():
    """Deduplication is ``pipeline.Deduplicate``'s job. If two coincident holes
    survive to the emitter, the operator asked for two hits."""
    data = make_data(
        at(0, 0, 7_000_000, index=1),
        at(0, 0, 7_000_000, index=2),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    )

    out = lines(emit(data))

    assert out.count("X56.500Y30.000") == 2


# --------------------------------------------------------------------------
# representability: two nominals the chosen format cannot tell apart
# --------------------------------------------------------------------------


def test_two_nominals_that_render_to_the_same_token_are_refused():
    """Refuse distinct nominals that both render as ``C7.000``.

    6.9998 and 7.0000 mm remain separate in the model, so one token would be false.
    """
    data = make_data(
        at(0, 0, 6_999_800, index=1),
        at(10_000_000, 0, 7_000_000, index=3),
        reference=ReferenceOutline(Nanometre(50_000_000), Nanometre(50_000_000)),
    )

    assert len(data.tools()) == 2  # the model still sees two nominals

    with pytest.raises(
        EmitterError, match=r"(?=.*6\.999800)(?=.*7\.000000)(?=.*C7\.000)(?=.*3 decimals)"
    ):
        emit(data)


def test_raising_the_precision_makes_the_same_two_nominals_representable():
    """The refusal is about representability, not about clustering. The emitter
    must never quietly raise the precision itself — but when the caller does,
    the very same data emits, with two genuinely distinct tools."""
    data = make_data(
        at(0, 0, 6_999_800, index=1),
        at(10_000_000, 0, 7_000_000, index=3),
        reference=ReferenceOutline(Nanometre(50_000_000), Nanometre(50_000_000)),
    )

    assert tool_definitions(emit(data, decimals=4)) == {1: "6.9998", 2: "7.0000"}


# --------------------------------------------------------------------------
# a finding the pipeline already made: ERROR means no drill file
# --------------------------------------------------------------------------


def error_bearing_data() -> DrillData:
    """What ``SnapDiametersToDrillTable`` leaves behind after a bad diameter."""
    return make_data(
        at(-19_000_000, -18_750_000, 5_000_000, index=6),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    ).with_diagnostics(
        Diagnostic.error(
            "unknown-diameter",
            "dia 7.000 mm at (0.000, 18.000) matches no metric drill size",
            (0, 18_000_000),
            data=(("diameter_nm", 7_000_000),),
        )
    )


def test_data_carrying_an_error_is_refused_rather_than_written():
    """Data carrying an error is refused rather than written."""
    with pytest.raises(EmitterError, match="unknown-diameter"):
        emit(error_bearing_data())


def test_the_refusal_names_every_distinct_error_code_once():
    """Two findings of one code and one of another: the caller is told what is
    wrong with the data, not handed a repetition of the commonest failure."""
    data = error_bearing_data().with_diagnostics(
        Diagnostic.error("unknown-diameter", "another one", (10_000_000, 18_000_000)),
        Diagnostic.error("wrong-enclosure", "declared 1590B, drawn 1590BB"),
    )

    with pytest.raises(EmitterError) as raised:
        emit(data)

    text = str(raised.value)
    assert text.count("unknown-diameter") == 1
    assert "wrong-enclosure" in text


def test_warnings_and_information_still_produce_a_drill_file():
    """Only ERROR diagnostics forbid Excellon artefacts.

    WARNING and INFO together ensure a non-empty diagnostic list still emits.
    """
    data = make_data(
        at(0, 18_000_000, 7_000_000, index=3),
        reference=ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)),
    ).with_diagnostics(
        Diagnostic.warning("duplicate-hole", "1 coincident hole collapsed", (0, 18_000_000)),
        Diagnostic.info("no-reference-outline", "nothing to check against"),
    )

    assert "X56.500Y48.000" in lines(emit(data))


# --------------------------------------------------------------------------
# coordinates: frame, order, grouping
# --------------------------------------------------------------------------


def test_a_hole_outside_the_reference_outline_is_refused_in_lower_left():
    """LOWER_LEFT refuses holes that would produce negative coordinates.

    Identity 4 differs from its tuple position so the error cannot name position.
    """
    y_only = make_data(
        at(0, 0, 5_000_000, index=9),
        at(0, -60_000_000, 5_000_000, index=4),
        reference=ReferenceOutline(Nanometre(50_000_000), Nanometre(50_000_000)),
    )

    with pytest.raises(EmitterError, match=r"hole 4\b"):
        emit(y_only)

    x_only = make_data(
        at(-60_000_000, 0, 5_000_000, index=7),
        reference=ReferenceOutline(Nanometre(50_000_000), Nanometre(50_000_000)),
    )

    with pytest.raises(EmitterError, match=r"hole 7\b"):
        emit(x_only)


def test_a_hole_a_fraction_of_a_print_unit_outside_the_outline_is_not_refused():
    """The promise is about the coordinates as *written*, so the check reads the
    rendered token, not the position behind it. A hole four ten-thousandths of a
    millimetre past the edge prints ``0.000`` and drills exactly where it should;
    refusing it would turn representation noise into an operator-facing failure.
    """
    data = make_data(
        at(-25_000_400, 0, 7_000_000, index=1),
        reference=ReferenceOutline(Nanometre(50_000_000), Nanometre(50_000_000)),
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
    """Shared with the drawing's schedule via ``units.format_nm``."""
    out = lines(emit(make_data(at(-400, -400, 7_000_000, index=1)), origin=Origin.CENTRE))

    assert "X0.000Y0.000" in out
    assert not any("-0.000" in line for line in out)


def test_a_coordinate_on_an_exact_half_rounds_by_the_unit_boundarys_rule():
    """One conversion, the model's own, and not a float millimetre on the way."""
    data = make_data(at(16_500_500, -30_000_500, 7_000_000, index=1))

    assert "X16.501Y-30.001" in lines(emit(data, origin=Origin.CENTRE))


def test_lower_left_without_a_reference_outline_raises_emitter_error():
    """The message is asserted, not merely the exception type."""
    data = make_data(at(0, 0, 7_000_000, index=1))

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
    data = make_data(at(-5_000_000, -5_000_000, 7_000_000, index=1))

    assert "X-5.000Y-5.000" in lines(emit(data, origin=Origin.CENTRE))


def test_the_header_says_which_frame_the_coordinates_are_in():
    """The drill file and the sheet beside it describe one panel in two frames."""
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


def test_the_stated_shift_is_the_shift_the_coordinates_were_moved_by():
    """An odd outline has no exact half, and the header must quote the one ``with_origin``
    actually applied.
    """
    outline = ReferenceOutline(width_nm=Nanometre(100_000_001), height_nm=Nanometre(60_000_001))
    data = make_data(at(0, 0, 7_000_000, index=2), reference=outline)

    out = lines(emit(data, decimals=6))
    stated = next(ln for ln in out if ln.startswith(";ORIGIN="))
    written = next(ln for ln in out if ln.startswith("X"))

    shift_x, shift_y = re.search(r"X(\S+) Y(\S+) from its centre", stated).groups()
    at_x, at_y = re.match(r"^X(\S+?)Y(\S+)$", written).groups()

    assert (shift_x, shift_y) == (at_x, at_y) == ("50.000000", "30.000000")


def test_coordinates_are_grouped_under_their_tool_ascending_by_diameter():
    out = lines(emit(fixture_data()))
    body = out[out.index("G05") + 1 :]

    assert body[0] == "T1"
    assert body[1:3] == ["X37.500Y11.250", "X75.500Y11.250"]  # the two ⌀5
    assert body[3] == "T2"
    assert len(body[4:-2]) == 5  # the five ⌀7
    assert body[-2:] == ["T0", "M30"]


def test_hole_order_is_preserved_not_re_sorted():
    """Ordering is ``pipeline.RouteHoles``' decision, not this emitter's."""
    data = make_data(
        at(10_000_000, -10_000_000, 7_000_000, index=1),
        at(-10_000_000, 10_000_000, 7_000_000, index=2),
        at(10_000_000, 10_000_000, 7_000_000, index=3),
        at(-10_000_000, -10_000_000, 7_000_000, index=4),
        reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)),
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
        at(0, -20_000_000, 7_000_000, index=1),
        at(-30_000_000, 20_000_000, 5_000_000, index=2),
        at(30_000_000, 20_000_000, 7_000_000, index=3),
        at(0, 20_000_000, 5_000_000, index=4),
        reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)),
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
# purity
# --------------------------------------------------------------------------


def test_emit_does_not_mutate_the_input_data():
    data = fixture_data()
    before = tuple(data.holes)

    emit(data)

    assert data.holes == before
    assert data.holes[0].x_nm == -40_000_000


def test_emit_is_deterministic():
    data = fixture_data()

    assert emit(data) == emit(data)
