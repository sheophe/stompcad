"""Tests for the JSON emitter (SPEC §7, PLAN task D).

JSON is the integration surface for the wider toolchain, so these tests pin the
document *shape*, not just its contents: key order, key names and the presence of
raw provenance are all part of the contract other tools code against.
"""

from __future__ import annotations

import json

from aidrill.emitters.base import REGISTRY, get_emitter
from aidrill.emitters.json_out import JsonEmitter, JsonOptions
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.pipeline import Deduplicate
from aidrill.protocols import Emitter, Pipeline
from tests.conftest import at, holes, make_data


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def fixture_data() -> DrillData:
    """A DrillData exercising every field: nominal-vs-raw drift, a reference
    outline, one diagnostic of each severity, full source info, and the stages
    that produced it.

    Three details are deliberate. The hole identities are 4 and 1 — neither
    sequential nor equal to their position in the document — because a fixture
    numbered 0, 1 in the order it lists its holes cannot tell a serialised
    identity from a serialised list index; gaps are what survives a
    Deduplicate anyway. Two of the three diagnostics carry a payload,
    because a document that drops ``data`` still round-trips empty ones. And
    the outline is *snapped* — measured 113 × 60, resized to a catalogue
    112 × 61 — because an outline whose ``raw`` equals its nominal size cannot
    tell a serialised measurement from a re-derived one, and the round-trip
    test stayed green for exactly that reason while ``reference.raw`` was being
    dropped on the way out.
    """
    given = (
        Hole(x=-40.0, y=18.0, diameter=7.0, raw=RawHole(-39.9906, 18.0021, 6.9998), index=4),
        Hole(x=-19.0, y=-18.75, diameter=5.0, raw=RawHole(-19.0, -18.75, 5.0002), index=1),
    )
    return DrillData(
        holes=given,
        reference=ReferenceOutline.from_measurement(
            113.0, 60.0, centre_x=297.6, centre_y=421.0
        ).resized(112.0, 61.0),
        diagnostics=(
            Diagnostic.info("no-reference-outline", "nothing to check against"),
            Diagnostic.warning(
                "duplicate-hole",
                "1 coincident hole collapsed",
                (-40.0, 18.0),
                data=(("hole_index", 4), ("diameter", 7.0), ("dropped", 1), ("kept", 1)),
            ),
            Diagnostic.error("broken", "something gave up", (1.5, -2.5), data=(("stage", "snap"),)),
        ),
        source=SourceInfo(
            path="tests/fixtures/tar.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill", "Graphics", "Hardware"),
            producer="aidrill 1.0.0",
        ),
        processing=(
            StageRun("snap", (("grid_mm", 0.25), ("warn_over_mm", 0.0625), ("enabled", True))),
            StageRun(
                "normalize-diameters",
                (("strategy", "TableDiameters"), ("sizes_mm", (5.0, 7.0))),
            ),
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
        "processing",
    ]


def test_document_declares_its_format_and_canonical_frame():
    document = parse(fixture_data())

    assert document["format"] == "aidrill-drill-data"
    assert document["version"] == 3
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

    assert list(reference) == ["width", "height", "centre_x", "centre_y", "raw"]
    assert reference["width"] == 112.0
    assert reference["height"] == 61.0
    assert reference["centre_x"] == 297.6
    assert reference["centre_y"] == 421.0


def test_reference_outline_carries_what_was_measured_not_only_what_was_snapped():
    """The nominal size is a catalogue decision; ``raw`` is the artwork.

    A hole's ``raw`` has been in this document since version 1. The outline's
    was not, so a snapped panel went out stating 112 × 61 with nothing left
    saying it had been measured at 113 × 60 — provenance leaving the system
    through the one emitter CLAUDE.md calls the integration contract.
    """
    reference = parse(fixture_data())["reference"]

    assert reference["raw"] == {"width": 113.0, "height": 60.0}
    assert (reference["width"], reference["height"]) != (
        reference["raw"]["width"],
        reference["raw"]["height"],
    )


def test_missing_reference_outline_is_null_not_omitted():
    document = parse(DrillData(holes=(Hole.from_measurement(0.0, 0.0, 7.0, index=0),)))

    assert "reference" in document
    assert document["reference"] is None


def test_holes_carry_nominal_and_raw_provenance():
    emitted = parse(fixture_data())["holes"]

    assert list(emitted[0]) == ["x", "y", "diameter", "tool", "raw", "index"]
    assert emitted[0]["x"] == -40.0
    assert emitted[0]["y"] == 18.0
    assert emitted[0]["diameter"] == 7.0
    assert emitted[0]["raw"] == {"x": -39.9906, "y": 18.0021, "diameter": 6.9998}


def test_each_hole_names_its_tool_number_from_drilldata_tools():
    data = fixture_data()
    emitted = parse(data)["holes"]

    tools = data.tools()
    assert [h["tool"] for h in emitted] == [tools[h.diameter] for h in data.holes]


def test_each_hole_carries_its_identity_not_its_position():
    """``index`` is the hole's stable identity, and nothing else.

    A consumer joins a diagnostic's ``hole_index`` back to a hole with it, so
    emitting the position in the array — which agrees with the identity in any
    fixture numbered 0..n-1 in document order — would silently mis-join every
    document whose holes were sorted or deduplicated first.
    """
    data = make_data(at(10.0, -10.0, index=7), at(-10.0, 10.0, 5.0, index=2), at(0.0, 0.0, index=5))

    emitted = parse(data)["holes"]

    assert [h["index"] for h in emitted] == [7, 2, 5]


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

    assert list(diagnostics[0]) == ["severity", "code", "message", "location", "data"]
    assert [d["severity"] for d in diagnostics] == ["info", "warning", "error"]
    assert diagnostics[0]["location"] is None
    assert diagnostics[1]["code"] == "duplicate-hole"
    assert diagnostics[1]["message"] == "1 coincident hole collapsed"
    assert diagnostics[1]["location"] == [-40.0, 18.0]


def test_a_diagnostic_without_a_payload_carries_an_empty_object():
    """Absent, not omitted: a consumer reads ``data`` on every diagnostic."""
    diagnostics = parse(fixture_data())["diagnostics"]

    assert diagnostics[0]["data"] == {}
    assert diagnostics[2]["data"] == {"stage": "snap"}


def test_diagnostic_payloads_survive_serialisation():
    """The duplicate's payload is the whole point of Diagnostic.data.

    Without it a JSON consumer must re-derive which holes were duplicates from
    positions alone — the exact defect ADR-0001 exists to eliminate, displaced
    one layer out into the toolchain.
    """
    data = make_data(*holes((0.0, 0.0), (0.01, 0.0)))
    after = Pipeline([Deduplicate(tolerance=0.05)]).run(data)
    doc = json.loads(JsonEmitter().emit(after))

    assert doc["version"] == 3
    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"]["dropped"] == 1
    assert duplicate["data"]["hole_index"] == doc["holes"][0]["index"]


def test_the_duplicates_payload_names_the_surviving_hole_by_identity():
    """The same join as above, on holes whose identities are not their positions.

    ``holes()`` numbers 0..n-1, so the survivor of the first pair is hole 0 at
    array position 0 and a serialiser emitting either would pass. Here the
    survivor is hole 6, second in the document.
    """
    data = make_data(at(50.0, 0.0, index=3), at(0.0, 0.0, index=6), at(0.01, 0.0, index=9))
    after = Pipeline([Deduplicate(tolerance=0.05)]).run(data)

    doc = json.loads(JsonEmitter().emit(after))

    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"] == {"hole_index": 6, "diameter": 7.0, "dropped": 1, "kept": 1}
    assert [h["index"] for h in doc["holes"]] == [3, 6]


# --------------------------------------------------------------------------
# stage provenance
# --------------------------------------------------------------------------


def test_processing_records_what_the_pipeline_did():
    """The document states the grid these holes were snapped to.

    A JSON consumer that has to be told the parameters out of band gets the
    drawing's old bug: data snapped at 0.5 described as 0.25 by whoever wrote
    the consumer's config.
    """
    document = parse(fixture_data())

    assert [list(run) for run in document["processing"]] == [["name", "parameters"]] * 2
    assert document["processing"] == [
        {
            "name": "snap",
            "parameters": {"grid_mm": 0.25, "warn_over_mm": 0.0625, "enabled": True},
        },
        {
            "name": "normalize-diameters",
            "parameters": {"strategy": "TableDiameters", "sizes_mm": [5.0, 7.0]},
        },
    ]


def test_processing_records_the_stages_a_real_pipeline_ran():
    data = make_data(*holes((0.0, 0.0), (0.01, 0.0)))

    after = Pipeline([Deduplicate(tolerance=0.05)]).run(data)

    assert parse(after)["processing"] == [
        {"name": "deduplicate", "parameters": {"tolerance_mm": 0.05}}
    ]


def test_a_pipeline_that_never_ran_leaves_processing_empty_not_absent():
    document = parse(make_data(at(0.0, 0.0, index=0)))

    assert document["processing"] == []


def test_the_exposed_mapping_is_already_json_shaped():
    """``document()`` is public so callers can embed it; what they embed must
    equal what a reader parses back, not merely dump to the same text."""
    data = fixture_data()

    assert JsonEmitter().document(data) == parse(data)


# --------------------------------------------------------------------------
# full round trip
# --------------------------------------------------------------------------


def test_document_rebuilds_an_identical_drilldata():
    """Nothing in DrillData may be lost on the way out — this is the whole point
    of the format.

    ``==`` on a frozen dataclass is only as strong as the fixture: it passed for
    a while over holes with no identity, diagnostics with empty payloads and no
    stage records at all, which made "nothing is lost" a claim about three
    absent fields. It then passed over an *unsnapped* reference outline, where
    ``raw`` equals the nominal size — so a document that dropped the outline's
    measurement rebuilt it from the nominal values and compared equal, and the
    claim in the first paragraph was false for a fourth field while this test
    stayed green. The fixture now carries all four, the outline snapped.
    """
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
        reference=ReferenceOutline(
            width=document["reference"]["width"],
            height=document["reference"]["height"],
            centre_x=document["reference"]["centre_x"],
            centre_y=document["reference"]["centre_y"],
            raw=RawOutline(
                document["reference"]["raw"]["width"],
                document["reference"]["raw"]["height"],
            ),
        ),
        diagnostics=tuple(
            Diagnostic(
                severity=Severity(d["severity"]),
                code=d["code"],
                message=d["message"],
                location=None if d["location"] is None else tuple(d["location"]),
                data=tuple(d["data"].items()),
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
        processing=tuple(
            StageRun(run["name"], list(run["parameters"].items()))
            for run in document["processing"]
        ),
    )

    assert rebuilt == data
    assert rebuilt.diagnostics[1].get("hole_index") == 4
    assert rebuilt.last_run("normalize-diameters").get("sizes_mm") == (5.0, 7.0)


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
