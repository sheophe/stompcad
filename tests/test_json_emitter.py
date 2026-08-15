"""Tests for the JSON emitter (SPEC §7, PLAN task D).

JSON is the integration surface for the wider toolchain, so these tests pin the
document *shape*, not just its contents: key order, key names and the presence of
raw provenance are all part of the contract other tools code against.
"""

from __future__ import annotations

import json

import pytest

from aidrill.emitters.base import REGISTRY, get_emitter
from aidrill.emitters.json_out import JsonEmitter, JsonOptions
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    RawHole,
    ReferenceOutline,
    Severity,
    SourceInfo,
)
from aidrill.protocols import Emitter


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def fixture_data() -> DrillData:
    """A DrillData exercising every field: nominal-vs-raw drift, a reference
    outline, one diagnostic of each severity, and full source info."""
    holes = (
        Hole(x=-40.0, y=18.0, diameter=7.0, raw=RawHole(-39.9906, 18.0021, 6.9998), index=0),
        Hole(x=-19.0, y=-18.75, diameter=5.0, raw=RawHole(-19.0, -18.75, 5.0002), index=1),
    )
    return DrillData(
        holes=holes,
        reference=ReferenceOutline(width=113.0, height=60.0, centre_x=297.6, centre_y=421.0),
        diagnostics=(
            Diagnostic.info("no-reference-outline", "nothing to check against"),
            Diagnostic.warning("duplicate-hole", "1 coincident hole collapsed", (-40.0, 18.0)),
            Diagnostic.error("broken", "something gave up", (1.5, -2.5)),
        ),
        source=SourceInfo(
            path="tests/fixtures/tar.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill", "Graphics", "Hardware"),
            producer="aidrill 1.0.0",
        ),
    )


def emit(data: DrillData, **kwargs) -> str:
    options = JsonOptions(**kwargs) if kwargs else None
    return JsonEmitter(options).emit(data)


def parse(data: DrillData, **kwargs) -> dict:
    return json.loads(emit(data, **kwargs))


# --------------------------------------------------------------------------
# registration and protocol conformance
# --------------------------------------------------------------------------


def test_emitter_self_registers_as_json():
    import aidrill.emitters  # noqa: F401  (importing the package must register)

    assert REGISTRY["json"] is JsonEmitter
    assert get_emitter("json") is JsonEmitter


def test_emitter_declares_name_media_type_and_extension():
    assert JsonEmitter.name == "json"
    assert JsonEmitter.media_type == "application/json"
    assert JsonEmitter.extension == ".json"
    assert isinstance(JsonEmitter(), Emitter)


# --------------------------------------------------------------------------
# document shape
# --------------------------------------------------------------------------


def test_output_parses_as_json():
    assert isinstance(parse(fixture_data()), dict)


def test_top_level_key_order_is_stable_and_documented():
    document = parse(fixture_data())

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
    ]


def test_document_declares_its_format_and_canonical_frame():
    document = parse(fixture_data())

    assert document["format"] == "aidrill-drill-data"
    assert document["version"] == 1
    assert document["units"] == "mm"
    assert document["origin"] == "centre"


def test_source_info_round_trips():
    source = parse(fixture_data())["source"]

    assert list(source) == [
        "path",
        "drill_layer",
        "reference_layer",
        "layers_found",
        "producer",
    ]
    assert source["path"] == "tests/fixtures/tar.ai"
    assert source["layers_found"] == ["Background", "Drill", "Graphics", "Hardware"]
    assert source["producer"] == "aidrill 1.0.0"


def test_reference_outline_round_trips():
    reference = parse(fixture_data())["reference"]

    assert list(reference) == ["width", "height", "centre_x", "centre_y"]
    assert reference["width"] == 113.0
    assert reference["height"] == 60.0
    assert reference["centre_x"] == 297.6
    assert reference["centre_y"] == 421.0


def test_missing_reference_outline_is_null_not_omitted():
    document = parse(DrillData(holes=(Hole.from_measurement(0.0, 0.0, 7.0, index=0),)))

    assert "reference" in document
    assert document["reference"] is None


def test_holes_carry_nominal_and_raw_provenance():
    holes = parse(fixture_data())["holes"]

    assert list(holes[0]) == ["x", "y", "diameter", "tool", "raw"]
    assert holes[0]["x"] == -40.0
    assert holes[0]["y"] == 18.0
    assert holes[0]["diameter"] == 7.0
    assert holes[0]["raw"] == {"x": -39.9906, "y": 18.0021, "diameter": 6.9998}


def test_each_hole_names_its_tool_number_from_drilldata_tools():
    data = fixture_data()
    holes = parse(data)["holes"]

    tools = data.tools()
    assert [h["tool"] for h in holes] == [tools[h.diameter] for h in data.holes]


def test_tool_table_matches_drilldata_tools_exactly():
    data = fixture_data()

    tools = parse(data)["tools"]

    assert [list(t) for t in tools] == [["number", "diameter", "count"]] * len(tools)
    assert [(t["number"], t["diameter"]) for t in tools] == [
        (number, diameter) for diameter, number in data.tools().items()
    ]
    assert [t["count"] for t in tools] == [1, 1]


def test_tool_quantities_are_the_models_tool_counts():
    """"Holes per nominal diameter" is one computation, on the model.

    It was written out three times — here, in the drawing's schedule and in the
    CLI report — so a JSON consumer and the sheet in the operator's hand could
    disagree about how many holes a bit drills.
    """
    data = DrillData(
        holes=(
            Hole.from_measurement(0.0, 0.0, 7.0, index=0),
            Hole.from_measurement(10.0, 0.0, 5.0, index=1),
            Hole.from_measurement(20.0, 0.0, 7.0, index=2),
            Hole.from_measurement(30.0, 0.0, 7.0, index=3),
        )
    )

    tools = parse(data)["tools"]

    assert [(t["diameter"], t["count"]) for t in tools] == list(data.tool_counts().items())
    assert [t["count"] for t in tools] == [1, 3]


def test_diagnostics_round_trip_with_severity_code_message_and_location():
    diagnostics = parse(fixture_data())["diagnostics"]

    assert list(diagnostics[0]) == ["severity", "code", "message", "location"]
    assert [d["severity"] for d in diagnostics] == ["info", "warning", "error"]
    assert diagnostics[0]["location"] is None
    assert diagnostics[1]["code"] == "duplicate-hole"
    assert diagnostics[1]["message"] == "1 coincident hole collapsed"
    assert diagnostics[1]["location"] == [-40.0, 18.0]


# --------------------------------------------------------------------------
# full round trip
# --------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="Task 3: json_out does not serialise Hole.index")
def test_document_rebuilds_an_identical_drilldata():
    """Nothing in DrillData may be lost on the way out — this is the whole point
    of the format."""
    data = fixture_data()
    document = parse(data)

    rebuilt = DrillData(
        holes=tuple(
            Hole(
                x=h["x"],
                y=h["y"],
                diameter=h["diameter"],
                raw=RawHole(h["raw"]["x"], h["raw"]["y"], h["raw"]["diameter"]),
                index=h["index"],
            )
            for h in document["holes"]
        ),
        reference=ReferenceOutline(**document["reference"]),
        diagnostics=tuple(
            Diagnostic(
                severity=Severity(d["severity"]),
                code=d["code"],
                message=d["message"],
                location=None if d["location"] is None else tuple(d["location"]),
            )
            for d in document["diagnostics"]
        ),
        source=SourceInfo(
            path=document["source"]["path"],
            drill_layer=document["source"]["drill_layer"],
            reference_layer=document["source"]["reference_layer"],
            layers_found=tuple(document["source"]["layers_found"]),
            producer=document["source"]["producer"],
        ),
    )

    assert rebuilt == data


# --------------------------------------------------------------------------
# purity and determinism
# --------------------------------------------------------------------------


def test_hole_order_is_preserved_not_re_sorted():
    """Ordering is ``pipeline.SortHoles``' decision, not this emitter's."""
    data = DrillData(
        holes=(
            Hole.from_measurement(10.0, -10.0, 7.0, index=0),
            Hole.from_measurement(-10.0, 10.0, 5.0, index=1),
            Hole.from_measurement(0.0, 0.0, 7.0, index=2),
        )
    )

    assert [(h["x"], h["y"]) for h in parse(data)["holes"]] == [
        (10.0, -10.0),
        (-10.0, 10.0),
        (0.0, 0.0),
    ]


def test_emitter_does_not_round_or_cluster_values():
    data = DrillData(
        holes=(
            Hole.from_measurement(0.1234567, -0.7654321, 6.9998, index=0),
            Hole.from_measurement(1.0, 1.0, 7.0000, index=1),
        )
    )
    document = parse(data)

    assert document["holes"][0]["x"] == 0.1234567
    assert document["holes"][0]["diameter"] == 6.9998
    assert len(document["tools"]) == 2


def test_emit_is_deterministic_and_does_not_mutate_its_input():
    data = fixture_data()
    before = tuple(data.holes)

    first = emit(data)

    assert first == emit(data)
    assert data.holes == before


def test_indent_option_controls_formatting_only():
    data = fixture_data()

    compact = emit(data, indent=None)

    assert "\n" not in compact.strip()
    assert json.loads(compact) == parse(data)


def test_output_ends_with_a_newline():
    assert emit(fixture_data()).endswith("\n")
