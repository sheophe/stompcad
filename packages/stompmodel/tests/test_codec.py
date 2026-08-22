"""The drill document, both directions."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stompmodel.codec import FORMAT, VERSION, from_document, to_document
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.errors import DocumentError
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
from stompmodel.units import Millimetre, Nanometre

MM = 1_000_000

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _data() -> DrillData:
    """One fully-populated value. Holes are numbered out of tuple order, so a
    codec that recomputes a number from list position fails."""
    holes = (
        Hole.from_measurement(Nanometre(19 * MM), Nanometre(-18 * MM), Nanometre(5 * MM)).with_number(2),
        Hole.from_measurement(Nanometre(-19 * MM), Nanometre(-18 * MM), Nanometre(5 * MM)).with_number(1),
    )
    return DrillData(
        holes=holes,
        reference=ReferenceOutline(
            width_nm=Nanometre(112_400_000),
            height_nm=Nanometre(60_500_000),
            raw=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        ),
        diagnostics=(Diagnostic(Severity.WARNING, "duplicate-hole", "1 hole dropped"),),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )


def _at(x_nm: int, y_nm: int, diameter_nm: int = 7 * MM, *, index: int | None = None) -> Hole:
    """One quantised hole, numbered as if RouteHoles had already run.

    Plain integers are branded here so a test may write the literal it means;
    this helper is the suite's nanometre boundary.
    """
    hole = Hole.from_measurement(Nanometre(x_nm), Nanometre(y_nm), Nanometre(diameter_nm))
    return hole if index is None else hole.with_number(index)


def _make_data(*given: Hole) -> DrillData:
    """Build ``DrillData`` with fixed source provenance."""
    return DrillData(holes=tuple(given), source=SourceInfo(path="panel.ai", drill_layer="Drill"))


def _fixture_data() -> DrillData:
    """A DrillData exercising every field: nominal-vs-raw drift, a reference outline, one
    diagnostic of each severity, full source info, and the stages that produced it.
    """
    given = (
        Hole(
            x_nm=Nanometre(-40_000_000),
            y_nm=Nanometre(18_000_000),
            diameter_nm=Nanometre(7_000_000),
            raw=RawHole(Millimetre(-39.9906), Millimetre(18.0021), Millimetre(6.9998)),
            index=4,
        ),
        Hole(
            x_nm=Nanometre(-19_000_000),
            y_nm=Nanometre(-18_750_000),
            diameter_nm=Nanometre(5_000_000),
            raw=RawHole(Millimetre(-19.0), Millimetre(-18.75), Millimetre(5.0002)),
            index=1,
        ),
    )
    return DrillData(
        holes=given,
        reference=ReferenceOutline.from_measurement(
            Nanometre(120_000_000), Nanometre(93_000_000), centre_x_nm=Nanometre(297_600_000), centre_y_nm=Nanometre(421_000_000)
        ).resized(Nanometre(119_500_000), Nanometre(94_000_000)),
        diagnostics=(
            Diagnostic.info("no-reference-outline", "nothing to check against"),
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (-40.000, 18.000)",
                (-40_000_000, 18_000_000),
                data=(
                    ("diameter_nm", 7_000_000),
                    ("dropped", 1),
                ),
            ),
            Diagnostic.warning(
                "grid-ambiguous",
                "2 hole(s) sat exactly halfway between two grid points",
                data=(("tied_locations", ((-40_000_000, 18_000_000), (1_000_000, -1_000_000))),),
            ),
            Diagnostic.error(
                "broken", "something gave up", (1_500_000, -2_500_000), data=(("stage", "snap"),)
            ),
        ),
        source=SourceInfo(
            path="tests/fixtures/tar.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill", "Graphics", "Hardware"),
            producer="a source 1.0.0",
        ),
        processing=(
            StageRun(
                "identify-enclosure",
                (
                    ("tolerance_nm", 1_500_000),
                    ("catalogue", "Hammond 1590"),
                    ("expected_part", "1590BBS"),
                ),
            ),
            StageRun(
                "snap-diameters",
                (
                    ("standard", "metric"),
                    ("tolerance_nm", 250_000),
                    ("size_count", 2),
                    ("sizes_nm", (5_000_000, 7_000_000)),
                ),
            ),
            StageRun("snap", (("grid_nm", 250_000), ("warn_over_nm", 62_500))),
        ),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(119_500_000),
            width_nm=Nanometre(94_000_000),
            candidates=("1590C", "1590BB", "1590BBS", "1590BB2"),
            rotated=False,
            selected_part="1590BBS",
        ),
    )


def _rotated_fixture_data() -> DrillData:
    """A portrait panel, no case declared, and a catalogue this build cannot emit."""
    return replace(
        _fixture_data(),
        reference=ReferenceOutline.from_measurement(
            Nanometre(60_000_000), Nanometre(113_000_000), centre_x_nm=Nanometre(297_600_000), centre_y_nm=Nanometre(421_000_000)
        ).resized(Nanometre(60_500_000), Nanometre(112_400_000)),
        enclosure=EnclosureMatch(
            family="Hammond 1550",
            length_nm=Nanometre(112_400_000),
            width_nm=Nanometre(60_500_000),
            candidates=("1550S", "1550A", "1550B"),
            rotated=True,
            selected_part=None,
        ),
    )


def _square_fixture_data() -> DrillData:
    """Return a rotated square footprint with a declared case.

    Equal axes prevent rotation being inferred from transposed dimensions.
    """
    return replace(
        _fixture_data(),
        reference=ReferenceOutline.from_measurement(
            Nanometre(121_000_000), Nanometre(119_000_000), centre_x_nm=Nanometre(297_600_000), centre_y_nm=Nanometre(421_000_000)
        ).resized(Nanometre(120_000_000), Nanometre(120_000_000)),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(120_000_000),
            width_nm=Nanometre(120_000_000),
            candidates=("1590U", "1590Q", "1590V"),
            rotated=True,
            selected_part="1590Q",
        ),
    )


# --------------------------------------------------------------------------
# document shape
# --------------------------------------------------------------------------


def test_the_document_names_its_format_and_version() -> None:
    document = to_document(_data())

    assert document["format"] == FORMAT == "stompcad-drill-data"
    assert document["version"] == VERSION


def test_top_level_key_order_is_stable_and_documented() -> None:
    document = to_document(_fixture_data())

    assert list(document) == [
        "format",
        "version",
        "units",
        "origin",
        "source",
        "reference",
        "tools",
        "holes",
        "diagnostics",
        "processing",
        "enclosure",
    ]


def test_document_declares_its_format_and_canonical_frame() -> None:
    """``units`` is the frame's unit, and the frame is nanometres."""
    document = to_document(_fixture_data())

    assert document["format"] == "stompcad-drill-data"
    assert document["version"] == 5
    assert document["units"] == "nm"
    assert document["origin"] == "centre"


def test_source_info_round_trips() -> None:
    source = to_document(_fixture_data())["source"]

    assert list(source) == [
        "path",
        "drill_layer",
        "reference_layer",
        "layers_found",
        "producer",
    ]
    assert source["path"] == "tests/fixtures/tar.ai"
    assert source["layers_found"] == ["Background", "Drill", "Graphics", "Hardware"]
    assert source["producer"] == "a source 1.0.0"


def test_reference_outline_round_trips() -> None:
    reference = to_document(_fixture_data())["reference"]

    assert list(reference) == [
        "width_nm",
        "height_nm",
        "centre_x_nm",
        "centre_y_nm",
        "raw",
    ]
    assert reference["width_nm"] == 119_500_000
    assert reference["height_nm"] == 94_000_000
    assert reference["centre_x_nm"] == 297_600_000
    assert reference["centre_y_nm"] == 421_000_000


def test_reference_outline_carries_what_was_measured_not_only_what_was_snapped() -> None:
    """The nominal size is a catalogue decision; ``raw`` is the artwork."""
    reference = to_document(_fixture_data())["reference"]

    assert reference["raw"] == {"width": 120.0, "height": 93.0}
    assert reference["width_nm"] < reference["raw"]["width"] * 1_000_000
    assert reference["height_nm"] > reference["raw"]["height"] * 1_000_000


def test_missing_reference_outline_is_null_not_omitted() -> None:
    document = to_document(DrillData(holes=(_at(0, 0, index=4),)))

    assert "reference" in document
    assert document["reference"] is None


# --------------------------------------------------------------------------
# the enclosure match
# --------------------------------------------------------------------------


def test_enclosure_names_the_footprint_the_panel_was_identified_as() -> None:
    """The whole product of the matching stage, or the consumer cannot see it."""
    enclosure = to_document(_fixture_data())["enclosure"]

    assert list(enclosure) == [
        "family",
        "length_nm",
        "width_nm",
        "candidates",
        "rotated",
        "selected_part",
    ]
    assert enclosure["family"] == "Hammond 1590"
    assert enclosure["length_nm"] == 119_500_000
    assert enclosure["width_nm"] == 94_000_000


def test_enclosure_dimensions_are_nanometres_and_not_millimetres() -> None:
    """A 1590B is 112.40 mm, so there is no whole millimetre to fall back on."""
    document = to_document(_rotated_fixture_data())
    enclosure = document["enclosure"]

    assert enclosure["length_nm"] == 112_400_000
    assert type(enclosure["length_nm"]) is int
    assert type(enclosure["width_nm"]) is int
    assert type(document["reference"]["raw"]["width"]) is float
    text = json.dumps(document)
    assert '"length_nm": 112400000,' in text
    assert '"width": 60.0,' in text


def test_enclosure_candidates_keep_the_order_they_were_matched_in() -> None:
    """A 2-D outline identifies a footprint, never a part, so every part sharing it is
    named — in the order the match holds them.
    """
    candidates = to_document(_fixture_data())["enclosure"]["candidates"]

    assert candidates == ["1590C", "1590BB", "1590BBS", "1590BB2"]
    assert candidates != sorted(candidates)


def test_enclosure_records_whether_the_panel_was_drawn_rotated() -> None:
    """``rotated`` says the panel is the catalogue footprint turned 90°."""
    assert to_document(_fixture_data())["enclosure"]["rotated"] is False
    assert to_document(_rotated_fixture_data())["enclosure"]["rotated"] is True
    assert to_document(_square_fixture_data())["enclosure"]["rotated"] is True
    assert to_document(_rotated_fixture_data())["enclosure"]["family"] == "Hammond 1550"


def test_enclosure_rotation_is_reported_against_an_untransposed_footprint() -> None:
    """A rotated match keeps the catalogue's own length and width."""
    document = to_document(_rotated_fixture_data())

    assert (document["reference"]["width_nm"], document["reference"]["height_nm"]) == (
        60_500_000,
        112_400_000,
    )
    assert (document["enclosure"]["length_nm"], document["enclosure"]["width_nm"]) == (
        112_400_000,
        60_500_000,
    )


def test_rotation_is_not_re_derivable_from_the_outline_or_the_declared_part() -> None:
    """``rotated`` must be read off the match, never worked out from the data."""
    document = to_document(_square_fixture_data())
    enclosure = document["enclosure"]

    assert document["reference"]["width_nm"] == document["reference"]["height_nm"]
    assert enclosure["length_nm"] == enclosure["width_nm"]
    assert enclosure["rotated"] is True
    assert enclosure["selected_part"] == "1590Q"


def test_enclosure_carries_the_declared_part_and_its_absence() -> None:
    """``selected_part`` is operator knowledge, never inferred from geometry."""
    declared = to_document(_fixture_data())["enclosure"]

    assert declared["selected_part"] == "1590BBS"
    assert declared["selected_part"] in declared["candidates"]
    assert to_document(_rotated_fixture_data())["enclosure"]["selected_part"] is None


def test_unmatched_enclosure_is_null_not_omitted() -> None:
    """No match is a value a consumer reads, not a key it has to test for."""
    document = to_document(DrillData(holes=(_at(0, 0, index=4),)))

    assert "enclosure" in document
    assert document["enclosure"] is None


# --------------------------------------------------------------------------
# holes
# --------------------------------------------------------------------------


def test_holes_carry_nominal_and_raw_provenance() -> None:
    emitted = to_document(_fixture_data())["holes"]

    assert list(emitted[0]) == ["x_nm", "y_nm", "diameter_nm", "tool", "raw", "index"]
    assert emitted[0]["x_nm"] == -40_000_000
    assert emitted[0]["y_nm"] == 18_000_000
    assert emitted[0]["diameter_nm"] == 7_000_000
    assert emitted[0]["raw"] == {"x": -39.9906, "y": 18.0021, "diameter": 6.9998}


def test_a_holes_measurement_is_distinguishable_from_its_nominal_position() -> None:
    """``raw`` is the artwork, and it must not read as a copy of the nominal."""
    first, second = to_document(_fixture_data())["holes"]

    assert first["raw"]["x"] * 1_000_000 != first["x_nm"]
    assert first["raw"]["diameter"] * 1_000_000 != first["diameter_nm"]
    assert second["raw"]["x"] * 1_000_000 == second["x_nm"]
    assert second["raw"]["diameter"] * 1_000_000 != second["diameter_nm"]


def test_each_hole_names_its_tool_number_from_drilldata_tools() -> None:
    data = _fixture_data()
    emitted = to_document(data)["holes"]

    tools = data.tools()
    assert [h["tool"] for h in emitted] == [tools[h.diameter_nm] for h in data.holes]


def test_each_hole_carries_the_number_it_was_routed_with_not_its_position() -> None:
    """``index`` is the drill number ``RouteHoles`` assigned, read here through
    the model rather than recomputed from the hole's position in the tuple."""
    data = _make_data(
        _at(10_000_000, -10_000_000, index=7),
        _at(-10_000_000, 10_000_000, 5_000_000, index=2),
        _at(0, 0, index=5),
    )

    emitted = to_document(data)["holes"]

    assert [h["index"] for h in emitted] == [7, 2, 5]


def test_tool_table_matches_drilldata_tools_exactly() -> None:
    data = _fixture_data()

    tools = to_document(data)["tools"]

    assert [list(t) for t in tools] == [["number", "diameter_nm", "count"]] * len(tools)
    assert [(t["number"], t["diameter_nm"]) for t in tools] == [
        (number, diameter_nm) for diameter_nm, number in data.tools().items()
    ]
    assert [t["count"] for t in tools] == [1, 1]


def test_tool_quantities_are_the_models_tool_counts() -> None:
    """"Holes per nominal diameter" is one computation, on the model."""
    data = DrillData(
        holes=(
            _at(0, 0, index=4),
            _at(10_000_000, 0, 5_000_000, index=1),
            _at(20_000_000, 0, index=9),
            _at(30_000_000, 0, index=6),
        )
    )

    tools = to_document(data)["tools"]

    assert [(t["diameter_nm"], t["count"]) for t in tools] == list(data.tool_counts().items())
    assert [t["count"] for t in tools] == [1, 3]


def test_the_tool_numbering_is_read_from_the_model_and_not_re_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The numbering is looked up, not recomputed to agree."""
    data = _make_data(
        _at(0, 0, 7_000_000, index=5),
        _at(10_000_000, 0, 5_000_000, index=2),
        _at(20_000_000, 0, 7_000_000, index=8),
    )
    monkeypatch.setattr(DrillData, "tools", lambda self: {7_000_000: 4, 5_000_000: 9})

    document = to_document(data)

    assert [(t["number"], t["diameter_nm"]) for t in document["tools"]] == [
        (4, 7_000_000),
        (9, 5_000_000),
    ]
    assert [h["tool"] for h in document["holes"]] == [4, 9, 4]


def test_the_tool_quantities_are_read_from_the_model_and_not_recounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``count`` is ``tool_counts()``'s answer, not this codec's tally."""
    data = _make_data(
        _at(0, 0, 7_000_000, index=5),
        _at(10_000_000, 0, 5_000_000, index=2),
        _at(20_000_000, 0, 7_000_000, index=8),
    )
    monkeypatch.setattr(DrillData, "tool_counts", lambda self: {5_000_000: 90, 7_000_000: 40})

    tools = to_document(data)["tools"]

    assert [(t["diameter_nm"], t["count"]) for t in tools] == [
        (5_000_000, 90),
        (7_000_000, 40),
    ]


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------


def test_diagnostics_round_trip_with_severity_code_message_and_location() -> None:
    diagnostics = to_document(_fixture_data())["diagnostics"]

    assert list(diagnostics[0]) == ["severity", "code", "message", "location_nm", "data"]
    assert [d["severity"] for d in diagnostics] == ["info", "warning", "warning", "error"]
    assert diagnostics[0]["location_nm"] is None
    assert diagnostics[1]["code"] == "duplicate-hole"
    assert diagnostics[1]["location_nm"] == [-40_000_000, 18_000_000]


def test_a_diagnostic_without_a_payload_carries_an_empty_object() -> None:
    """Absent, not omitted: a consumer reads ``data`` on every diagnostic."""
    diagnostics = to_document(_fixture_data())["diagnostics"]

    assert diagnostics[0]["data"] == {}
    assert diagnostics[3]["data"] == {"stage": "snap"}


def test_a_payload_of_locations_is_emitted_as_an_array_of_pairs() -> None:
    """``tied_locations`` is a tuple of coordinate tuples in the model."""
    ambiguous = to_document(_fixture_data())["diagnostics"][2]

    assert ambiguous["data"]["tied_locations"] == [
        [-40_000_000, 18_000_000],
        [1_000_000, -1_000_000],
    ]


# --------------------------------------------------------------------------
# stage provenance
# --------------------------------------------------------------------------


def test_processing_records_what_the_pipeline_did() -> None:
    """The document states the grid these holes were snapped to."""
    document = to_document(_fixture_data())

    assert [list(run) for run in document["processing"]] == [["name", "parameters"]] * 3
    assert document["processing"] == [
        {
            "name": "identify-enclosure",
            "parameters": {
                "tolerance_nm": 1_500_000,
                "catalogue": "Hammond 1590",
                "expected_part": "1590BBS",
            },
        },
        {
            "name": "snap-diameters",
            "parameters": {
                "standard": "metric",
                "tolerance_nm": 250_000,
                "size_count": 2,
                "sizes_nm": [5_000_000, 7_000_000],
            },
        },
        {"name": "snap", "parameters": {"grid_nm": 250_000, "warn_over_nm": 62_500}},
    ]


def test_a_pipeline_that_never_ran_leaves_processing_empty_not_absent() -> None:
    document = to_document(_make_data(_at(0, 0, index=4)))

    assert document["processing"] == []


# --------------------------------------------------------------------------
# full round trip
# --------------------------------------------------------------------------


def test_a_document_round_trips_back_to_an_equal_value() -> None:
    original = _data()

    assert from_document(to_document(original)) == original


def test_the_round_trip_preserves_a_number_that_is_not_the_list_position() -> None:
    restored = from_document(to_document(_data()))

    assert [hole.index for hole in restored.holes] == [2, 1]


@given(st.integers(min_value=-500_000_000, max_value=500_000_000))
def test_any_hole_position_survives_the_round_trip(x_nm: int) -> None:
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(x_nm), Nanometre(0), Nanometre(5 * MM)).with_number(1),),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )

    assert from_document(to_document(data)).holes[0].x_nm == x_nm


#: Scalar shapes ``StageRun.parameters`` and ``Diagnostic.data`` may hold.
#: Keys never end ``_nm``: that suffix has its own int-only contract, already
#: exercised elsewhere, and is not a shape this property is about.
_SIMPLE_PARAM = st.one_of(
    st.integers(-1_000, 1_000),
    st.floats(-1_000.0, 1_000.0, allow_nan=False, allow_infinity=False),
    st.text(max_size=8),
    st.booleans(),
)


@st.composite
def _holes_strategy(draw):
    """A handful of holes, indices drawn as a permutation out of list order."""
    count = draw(st.integers(0, 5))
    built = []
    for index in draw(st.permutations(range(1, count + 1))):
        raw = RawHole(
            Millimetre(draw(st.floats(-60.0, 60.0, allow_nan=False, allow_infinity=False))),
            Millimetre(draw(st.floats(-60.0, 60.0, allow_nan=False, allow_infinity=False))),
            Millimetre(draw(st.floats(0.5, 12.0, allow_nan=False, allow_infinity=False))),
        )
        built.append(
            Hole(
                x_nm=Nanometre(draw(st.integers(-50_000_000, 50_000_000))),
                y_nm=Nanometre(draw(st.integers(-50_000_000, 50_000_000))),
                diameter_nm=Nanometre(draw(st.integers(1_000_000, 10_000_000))),
                raw=raw,
                index=index,
            )
        )
    return tuple(built)


@st.composite
def _reference_strategy(draw):
    """``None``, a reference with an auto-derived ``raw``, or one with its own."""
    if not draw(st.booleans()):
        return None
    outline = ReferenceOutline(
        width_nm=Nanometre(draw(st.integers(1_000_000, 500_000_000))),
        height_nm=Nanometre(draw(st.integers(1_000_000, 500_000_000))),
        centre_x_nm=Nanometre(draw(st.integers(-500_000_000, 500_000_000))),
        centre_y_nm=Nanometre(draw(st.integers(-500_000_000, 500_000_000))),
    )
    if not draw(st.booleans()):
        return outline
    measured = RawOutline(
        Millimetre(draw(st.floats(0.1, 600.0, allow_nan=False, allow_infinity=False))),
        Millimetre(draw(st.floats(0.1, 600.0, allow_nan=False, allow_infinity=False))),
    )
    return replace(outline, raw=measured)


@st.composite
def _diagnostics_strategy(draw):
    """Every severity, a location present or absent, ``data`` empty or one entry."""
    built = []
    for _ in range(draw(st.integers(0, 4))):
        location = None
        if draw(st.booleans()):
            location = (
                Nanometre(draw(st.integers(-10_000_000, 10_000_000))),
                Nanometre(draw(st.integers(-10_000_000, 10_000_000))),
            )
        payload = ()
        if draw(st.booleans()):
            key = draw(st.sampled_from(("note", "count", "reason", "flag")))
            payload = ((key, draw(_SIMPLE_PARAM)),)
        built.append(
            Diagnostic(
                severity=draw(st.sampled_from(list(Severity))),
                code=draw(st.text(min_size=1, max_size=10)),
                message=draw(st.text(max_size=20)),
                location_nm=location,
                data=payload,
            )
        )
    return tuple(built)


@st.composite
def _processing_strategy(draw):
    """Zero stage runs, or several, each with parameters present or absent."""
    built = []
    for _ in range(draw(st.integers(0, 3))):
        params = ()
        if draw(st.booleans()):
            key = draw(st.sampled_from(("standard", "tolerance", "size_count")))
            params = ((key, draw(_SIMPLE_PARAM)),)
        name = draw(st.sampled_from(("identify-enclosure", "snap-diameters", "snap", "deduplicate")))
        built.append(StageRun(name, params))
    return tuple(built)


@st.composite
def _enclosure_strategy(draw):
    """``None``, or a match with candidates and a declared or absent part."""
    if not draw(st.booleans()):
        return None
    candidates = tuple(draw(st.lists(st.sampled_from(("1590B", "1590BB", "1590C", "1590Q")), max_size=4)))
    return EnclosureMatch(
        family=draw(st.sampled_from(("Hammond 1590", "Hammond 1550"))),
        length_nm=Nanometre(draw(st.integers(1_000_000, 500_000_000))),
        width_nm=Nanometre(draw(st.integers(1_000_000, 500_000_000))),
        candidates=candidates,
        rotated=draw(st.booleans()),
        selected_part=draw(st.one_of(st.none(), st.sampled_from(("1590B", "1590BB", "1590C")))),
    )


@st.composite
def _source_strategy(draw):
    return SourceInfo(
        path=draw(st.text(max_size=15)),
        drill_layer=draw(st.text(max_size=8)),
        reference_layer=draw(st.text(max_size=8)),
        layers_found=tuple(draw(st.lists(st.text(max_size=6), max_size=3))),
        producer=draw(st.text(max_size=8)),
    )


@st.composite
def drill_data_strategy(draw):
    """Every ``DrillData`` shape the codec must round-trip -- hole counts,
    indices permuted out of list order, diagnostics with and without a
    location, ``data`` empty and populated, an enclosure present and absent,
    a reference with and without its own ``raw``, and processing with zero
    and many stage runs. Magnitude is held fixed and simple throughout: the
    single-integer property above already varies that axis, and shape is
    what ``from_document``'s 100%-covered lines cannot see for themselves.
    """
    return DrillData(
        holes=draw(_holes_strategy()),
        reference=draw(_reference_strategy()),
        diagnostics=draw(_diagnostics_strategy()),
        source=draw(_source_strategy()),
        processing=draw(_processing_strategy()),
        enclosure=draw(_enclosure_strategy()),
    )


@given(drill_data_strategy())
def test_the_round_trip_holds_over_every_documents_shape(data: DrillData) -> None:
    """Complements the single-integer property above rather than subsuming
    it: that one varies magnitude on a one-hole document, this one holds
    magnitude fixed and varies every field's shape instead.
    """
    assert from_document(to_document(data)) == data


@pytest.mark.parametrize(
    "build",
    [_fixture_data, _rotated_fixture_data, _square_fixture_data],
    ids=["landscape-declared", "rotated-undeclared", "square-rotated-declared"],
)
def test_document_rebuilds_an_identical_drilldata(build) -> None:
    """Every ``DrillData`` field survives serialisation and reconstruction."""
    data = build()

    rebuilt = from_document(json.loads(json.dumps(to_document(data))))

    run = rebuilt.last_run("snap-diameters")

    assert rebuilt == data
    assert rebuilt.diagnostics[1].location_nm == (-40_000_000, 18_000_000)
    assert run is not None, "the snap-diameters run did not survive the round trip"
    assert run.get("sizes_nm") == (5_000_000, 7_000_000)


def test_the_locations_in_a_rebuilt_payload_are_tuples_again() -> None:
    """A rebuilt finding must be usable, not merely printable."""
    data = _fixture_data()

    rebuilt = from_document(json.loads(json.dumps(to_document(data)))).diagnostics

    assert rebuilt[2].get("tied_locations") == (
        (-40_000_000, 18_000_000),
        (1_000_000, -1_000_000),
    )
    assert rebuilt == data.diagnostics
    assert {hash(d) for d in rebuilt} == {hash(d) for d in data.diagnostics}


def test_the_tool_table_is_not_read_back_but_derived_again() -> None:
    """``DrillData.tools()`` owns the numbering; the written table is a copy.

    A document whose table contradicts its holes still restores the value it
    was written from, which is only true of a reader that ignores the table.
    """
    document = to_document(_data())
    document["tools"] = [{"number": 9, "diameter_nm": 999, "count": 40}]

    assert from_document(document) == _data()


def test_a_document_of_another_format_is_refused() -> None:
    """A reader that guesses at an unknown shape is how two tools disagree."""
    document = to_document(_data())
    document["format"] = "some-other-tool"

    with pytest.raises(
        DocumentError, match="not a stompcad-drill-data document: 'some-other-tool'"
    ):
        from_document(document)


def test_a_document_of_an_unknown_version_is_refused() -> None:
    """The version is the promise about the shape, so an unknown one is refused."""
    document = to_document(_data())
    document["version"] = VERSION + 1

    with pytest.raises(DocumentError, match=f"version {VERSION + 1}, expected {VERSION}"):
        from_document(document)


def test_a_document_missing_a_section_is_refused_by_name() -> None:
    """A document this reader cannot read is one kind of failure, not two.

    ``KeyError`` is outside ``StompError``, so it would escape the handler a
    caller wrote around the codec.
    """
    document = to_document(_data())
    del document["processing"]

    with pytest.raises(DocumentError, match="has no 'processing'"):
        from_document(document)


def test_a_document_missing_a_field_inside_a_section_is_refused_too() -> None:
    """Truncation is not only a top-level accident; the readers nest."""
    document = to_document(_data())
    del document["holes"][0]["diameter_nm"]

    with pytest.raises(DocumentError, match="has no 'diameter_nm'"):
        from_document(document)


def test_a_document_whose_location_is_short_is_refused_rather_than_indexed() -> None:
    """A one-value location would raise ``IndexError`` past the handler.

    The pair is the finding's position, so half of one is not a position at
    all and must fail where the document is read.
    """
    document = to_document(_data())
    document["diagnostics"][0]["location_nm"] = [1_000_000]

    with pytest.raises(DocumentError, match="location_nm has 1 value"):
        from_document(document)


def test_a_document_whose_location_is_long_is_refused_rather_than_truncated() -> None:
    """Reading the first two of three would accept a frame this codec never wrote."""
    document = to_document(_data())
    document["diagnostics"][0]["location_nm"] = [1_000_000, 2_000_000, 3_000_000]

    with pytest.raises(DocumentError, match="location_nm has 3 value"):
        from_document(document)


def test_a_document_naming_an_unknown_severity_is_refused() -> None:
    """``Severity`` raises ``ValueError``, which is outside ``StompError``."""
    document = to_document(_data())
    document["diagnostics"][0]["severity"] = "catastrophe"

    with pytest.raises(DocumentError, match="catastrophe"):
        from_document(document)


def test_a_document_whose_payload_is_not_a_mapping_is_refused() -> None:
    """``data`` is read with ``.items()``; a list has none, so ``AttributeError``."""
    document = to_document(_data())
    document["diagnostics"][0]["data"] = ["dropped", 1]

    with pytest.raises(DocumentError, match="is malformed"):
        from_document(document)


def test_a_document_whose_stage_parameters_are_not_a_mapping_is_refused() -> None:
    """The same read, in the other reader: one failure, not two."""
    document = to_document(_data())
    document["processing"] = [{"name": "Deduplicate", "parameters": ["tolerance_nm", 0]}]

    with pytest.raises(DocumentError, match="is malformed"):
        from_document(document)


def test_a_document_whose_candidates_are_a_scalar_is_refused() -> None:
    """``tuple()`` of a scalar raises ``TypeError``, not a one-element tuple."""
    document = to_document(_fixture_data())
    assert document["enclosure"] is not None
    document["enclosure"]["candidates"] = 1590

    with pytest.raises(DocumentError, match="is malformed"):
        from_document(document)


def test_a_document_whose_length_is_not_whole_is_refused() -> None:
    """``Nanometre`` is a no-op brand, so only the model's guard catches a float.

    That guard raises ``TypeError``, which would escape the codec's handler
    from inside a constructor rather than from a read.
    """
    document = to_document(_data())
    document["holes"][0]["x_nm"] = 19_000_000.5

    with pytest.raises(DocumentError, match="whole number of nanometres"):
        from_document(document)


def test_a_document_numbering_a_hole_from_zero_is_refused() -> None:
    """``Hole`` raises ``ValueError`` for an index below 1; same escape, same base."""
    document = to_document(_data())
    document["holes"][0]["index"] = 0

    with pytest.raises(DocumentError, match="numbered from 1"):
        from_document(document)


def test_a_refused_document_keeps_the_failure_it_was_refused_for() -> None:
    """The handler re-attributes a failure, so it must not also erase it.

    Chaining is what keeps a defect inside a reader diagnosable if one ever
    raises one of the widened classes for a reason the document did not cause.
    """
    document = to_document(_data())
    document["diagnostics"][0]["severity"] = "catastrophe"

    with pytest.raises(DocumentError) as refused:
        from_document(document)

    assert isinstance(refused.value.__cause__, ValueError)


def test_a_document_measured_in_another_unit_is_refused() -> None:
    """This format at this version in inches clears both guards above.

    Every length would then be read as nanometres, which is a wrong hole
    rather than a failed read, so the unit is checked and not assumed.
    """
    document = to_document(_data())
    document["units"] = "inch"

    with pytest.raises(DocumentError, match="units 'inch'"):
        from_document(document)


def test_a_document_in_another_frame_is_refused() -> None:
    """A lower-left document read as centred puts every hole half a panel out."""
    document = to_document(_data())
    document["origin"] = "lower-left"

    with pytest.raises(DocumentError, match="origin 'lower-left'"):
        from_document(document)


# --------------------------------------------------------------------------
# purity and determinism
# --------------------------------------------------------------------------


def test_hole_order_is_preserved_not_re_sorted() -> None:
    """Ordering is the routing stage's decision, not this codec's."""
    data = DrillData(
        holes=(
            _at(10_000_000, -10_000_000, index=4),
            _at(-10_000_000, 10_000_000, 5_000_000, index=1),
            _at(0, 0, index=9),
        )
    )

    assert [(h["x_nm"], h["y_nm"]) for h in to_document(data)["holes"]] == [
        (10_000_000, -10_000_000),
        (-10_000_000, 10_000_000),
        (0, 0),
    ]


def test_the_codec_does_not_round_or_cluster_values() -> None:
    data = DrillData(
        holes=(
            Hole(
                x_nm=Nanometre(123_457),
                y_nm=Nanometre(-765_432),
                diameter_nm=Nanometre(6_999_800),
                raw=RawHole(Millimetre(0.1234567), Millimetre(-0.7654321), Millimetre(6.9998)),
                index=4,
            ),
            _at(1_000_000, 1_000_000, index=1),
        )
    )
    document = to_document(data)

    assert document["holes"][0]["x_nm"] == 123_457
    assert document["holes"][0]["diameter_nm"] == 6_999_800
    assert document["holes"][0]["raw"]["x"] == 0.1234567
    assert len(document["tools"]) == 2
