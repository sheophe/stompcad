"""Tests for JSON serialisation and reconstruction of drill data."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from aidrill.emitters.base import REGISTRY, get_emitter
from aidrill.emitters.json_out import JsonEmitter, JsonOptions
from aidrill.model import (
    Diagnostic,
    DrillData,
    EnclosureMatch,
    Hole,
    RawDrillData,
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.pipeline import (
    Deduplicate,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from aidrill.protocols import Emitter, Pipeline
from aidrill.quantise import quantise
from tests.conftest import at, holes, make_data

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def fixture_data() -> DrillData:
    """A DrillData exercising every field: nominal-vs-raw drift, a reference outline, one
    diagnostic of each severity, full source info, and the stages that produced it.
    """
    given = (
        Hole(
            x_nm=-40_000_000,
            y_nm=18_000_000,
            diameter_nm=7_000_000,
            raw=RawHole(-39.9906, 18.0021, 6.9998, 4),
            index=4,
        ),
        Hole(
            x_nm=-19_000_000,
            y_nm=-18_750_000,
            diameter_nm=5_000_000,
            raw=RawHole(-19.0, -18.75, 5.0002, 1),
            index=1,
        ),
    )
    return DrillData(
        holes=given,
        reference=ReferenceOutline.from_measurement(
            120_000_000, 93_000_000, centre_x_nm=297_600_000, centre_y_nm=421_000_000
        ).resized(119_500_000, 94_000_000),
        diagnostics=(
            Diagnostic.info("no-reference-outline", "nothing to check against"),
            Diagnostic.warning(
                "duplicate-hole",
                "2 coincident ⌀7.000 mm holes at (-40.000, 18.000)",
                (-40_000_000, 18_000_000),
                data=(
                    ("hole_index", 4),
                    ("diameter_nm", 7_000_000),
                    ("dropped", 1),
                    ("dropped_indices", (9,)),
                    ("kept", 1),
                ),
            ),
            Diagnostic.warning(
                "grid-ambiguous",
                "2 hole(s) sat exactly halfway between two grid points",
                data=(("tied_indices", (4, 1)),),
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
            producer="aidrill 1.0.0",
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
            length_nm=119_500_000,
            width_nm=94_000_000,
            candidates=("1590C", "1590BB", "1590BBS", "1590BB2"),
            rotated=False,
            selected_part="1590BBS",
        ),
    )


def rotated_fixture_data() -> DrillData:
    """A portrait panel, no case declared, and a catalogue this build cannot emit."""
    return replace(
        fixture_data(),
        reference=ReferenceOutline.from_measurement(
            60_000_000, 113_000_000, centre_x_nm=297_600_000, centre_y_nm=421_000_000
        ).resized(60_500_000, 112_400_000),
        enclosure=EnclosureMatch(
            family="Hammond 1550",
            length_nm=112_400_000,
            width_nm=60_500_000,
            candidates=("1550S", "1550A", "1550B"),
            rotated=True,
            selected_part=None,
        ),
    )


def square_fixture_data() -> DrillData:
    """Return a rotated square footprint with a declared case.

    Equal axes prevent rotation being inferred from transposed dimensions.
    """
    return replace(
        fixture_data(),
        reference=ReferenceOutline.from_measurement(
            121_000_000, 119_000_000, centre_x_nm=297_600_000, centre_y_nm=421_000_000
        ).resized(120_000_000, 120_000_000),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=120_000_000,
            width_nm=120_000_000,
            candidates=("1590U", "1590Q", "1590V"),
            rotated=True,
            selected_part="1590Q",
        ),
    )


def emit(data: DrillData, **kwargs) -> str:
    options = JsonOptions(**kwargs) if kwargs else None
    return JsonEmitter(options).emit(data)


def parse(data: DrillData, **kwargs) -> dict:
    return json.loads(emit(data, **kwargs))


def read_panel(
    outline: RawOutline | None, *, case: str | None = None, measured: RawHole | None = None
) -> DrillData:
    """One measured panel put through the real quantisation phase."""
    raw = RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=outline,
        centre=(297.6, 421.0),
        holes=(measured if measured is not None else RawHole(0.0, 0.0, 7.0, 4),),
    )
    return quantise(
        raw,
        enclosure=IdentifyHammondFootprint(case),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(250_000),
    )


def nominal_lengths(node, path: str = "") -> list[tuple[str, object]]:
    """Every value under an ``_nm`` key anywhere in the document, with its path."""
    found: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            where = f"{path}.{key}"
            if key.endswith("_nm"):
                if isinstance(value, list):
                    found.extend((f"{where}[{i}]", v) for i, v in enumerate(value))
                elif value is not None:
                    found.append((where, value))
            found.extend(nominal_lengths(value, where))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(nominal_lengths(item, f"{path}[{index}]"))
    return found


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
        "enclosure",
    ]


def test_document_declares_its_format_and_canonical_frame():
    """``units`` is the frame's unit, and the frame is nanometres."""
    document = parse(fixture_data())

    assert document["format"] == "aidrill-drill-data"
    assert document["version"] == 5
    assert document["units"] == "nm"
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


def test_reference_outline_carries_what_was_measured_not_only_what_was_snapped():
    """The nominal size is a catalogue decision; ``raw`` is the artwork."""
    reference = parse(fixture_data())["reference"]

    assert reference["raw"] == {"width": 120.0, "height": 93.0}
    assert reference["width_nm"] < reference["raw"]["width"] * 1_000_000
    assert reference["height_nm"] > reference["raw"]["height"] * 1_000_000


def test_missing_reference_outline_is_null_not_omitted():
    document = parse(DrillData(holes=(at(0, 0, index=4),)))

    assert "reference" in document
    assert document["reference"] is None


# --------------------------------------------------------------------------
# every nominal length is a whole number of nanometres
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        fixture_data,
        rotated_fixture_data,
        square_fixture_data,
        lambda: read_panel(RawOutline(113.0, 60.0), case="1590b2"),
    ],
    ids=["landscape", "rotated", "square", "real-run"],
)
def test_no_nominal_length_is_a_float(build):
    """One sweep over the whole document, rather than a list of fields."""
    document = parse(build())

    assert [(where, value) for where, value in nominal_lengths(document) if type(value) is not int] == []


def test_the_sweep_reaches_every_kind_of_length_there_is():
    """The length sweep reaches every document section.

    Named paths prevent an empty or partially narrowed sweep passing vacuously.
    """
    document = parse(read_panel(RawOutline(113.0, 60.0), case="1590b2"))

    where = {path for path, _ in nominal_lengths(document)}

    assert ".reference.width_nm" in where
    assert ".reference.centre_x_nm" in where
    assert ".tools[0].diameter_nm" in where
    assert ".holes[0].x_nm" in where
    assert ".enclosure.length_nm" in where
    assert ".processing[0].parameters.tolerance_nm" in where


# --------------------------------------------------------------------------
# the enclosure match
# --------------------------------------------------------------------------


def test_enclosure_names_the_footprint_the_panel_was_identified_as():
    """The whole product of the matching stage, or the consumer cannot see it."""
    enclosure = parse(fixture_data())["enclosure"]

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


def test_enclosure_dimensions_are_nanometres_and_not_millimetres():
    """A 1590B is 112.40 mm, so there is no whole millimetre to fall back on."""
    document = parse(rotated_fixture_data())
    enclosure = document["enclosure"]

    assert enclosure["length_nm"] == 112_400_000
    assert type(enclosure["length_nm"]) is int
    assert type(enclosure["width_nm"]) is int
    assert type(document["reference"]["raw"]["width"]) is float
    text = emit(rotated_fixture_data())
    assert '"length_nm": 112400000,' in text
    assert '"width": 60.0,' in text


def test_enclosure_candidates_keep_the_order_they_were_matched_in():
    """A 2-D outline identifies a footprint, never a part, so every part sharing it is
    named — in the order the match holds them.
    """
    candidates = parse(fixture_data())["enclosure"]["candidates"]

    assert candidates == ["1590C", "1590BB", "1590BBS", "1590BB2"]
    assert candidates != sorted(candidates)


def test_enclosure_records_whether_the_panel_was_drawn_rotated():
    """``rotated`` says the panel is the catalogue footprint turned 90°."""
    assert parse(fixture_data())["enclosure"]["rotated"] is False
    assert parse(rotated_fixture_data())["enclosure"]["rotated"] is True
    assert parse(square_fixture_data())["enclosure"]["rotated"] is True
    assert parse(rotated_fixture_data())["enclosure"]["family"] == "Hammond 1550"


def test_enclosure_rotation_is_reported_against_an_untransposed_footprint():
    """A rotated match keeps the catalogue's own length and width."""
    document = parse(rotated_fixture_data())

    assert (document["reference"]["width_nm"], document["reference"]["height_nm"]) == (
        60_500_000,
        112_400_000,
    )
    assert (document["enclosure"]["length_nm"], document["enclosure"]["width_nm"]) == (
        112_400_000,
        60_500_000,
    )


def test_rotation_is_not_re_derivable_from_the_outline_or_the_declared_part():
    """``rotated`` must be read off the match, never worked out from the data."""
    document = parse(square_fixture_data())
    enclosure = document["enclosure"]

    assert document["reference"]["width_nm"] == document["reference"]["height_nm"]
    assert enclosure["length_nm"] == enclosure["width_nm"]
    assert enclosure["rotated"] is True
    assert enclosure["selected_part"] == "1590Q"


def test_enclosure_carries_the_declared_part_and_its_absence():
    """``selected_part`` is operator knowledge, never inferred from geometry."""
    declared = parse(fixture_data())["enclosure"]

    assert declared["selected_part"] == "1590BBS"
    assert declared["selected_part"] in declared["candidates"]
    assert parse(rotated_fixture_data())["enclosure"]["selected_part"] is None


def test_unmatched_enclosure_is_null_not_omitted():
    """No match is a value a consumer reads, not a key it has to test for."""
    document = parse(DrillData(holes=(at(0, 0, index=4),)))

    assert "enclosure" in document
    assert document["enclosure"] is None


def test_enclosure_is_what_the_quantisation_phase_found():
    """End to end, against the real catalogue rather than a hand-built match."""
    document = parse(read_panel(RawOutline(113.0, 60.0), case="1590b2"))

    assert document["enclosure"] == {
        "family": "Hammond 1590",
        "length_nm": 112_400_000,
        "width_nm": 60_500_000,
        "candidates": ["1590B", "1590B2"],
        "rotated": False,
        "selected_part": "1590B2",
    }
    assert document["reference"]["width_nm"] == 112_400_000
    assert document["reference"]["raw"] == {"width": 113.0, "height": 60.0}


def test_an_unrecognised_outline_leaves_the_enclosure_null_and_says_so():
    """The warning and the null are one finding, not two computations.

    A panel this catalogue has never heard of is left exactly as measured, so
    the document must carry both halves of that: no match, and the reason.
    """
    document = parse(read_panel(RawOutline(200.0, 45.0)))

    assert document["enclosure"] is None
    assert [d["code"] for d in document["diagnostics"]] == ["unknown-enclosure"]
    assert document["reference"]["width_nm"] == 200_000_000


# --------------------------------------------------------------------------
# holes
# --------------------------------------------------------------------------


def test_holes_carry_nominal_and_raw_provenance():
    emitted = parse(fixture_data())["holes"]

    assert list(emitted[0]) == ["x_nm", "y_nm", "diameter_nm", "tool", "raw", "index"]
    assert emitted[0]["x_nm"] == -40_000_000
    assert emitted[0]["y_nm"] == 18_000_000
    assert emitted[0]["diameter_nm"] == 7_000_000
    assert emitted[0]["raw"] == {"x": -39.9906, "y": 18.0021, "diameter": 6.9998}


def test_a_holes_measurement_is_distinguishable_from_its_nominal_position():
    """``raw`` is the artwork, and it must not read as a copy of the nominal."""
    first, second = parse(fixture_data())["holes"]

    assert first["raw"]["x"] * 1_000_000 != first["x_nm"]
    assert first["raw"]["diameter"] * 1_000_000 != first["diameter_nm"]
    assert second["raw"]["x"] * 1_000_000 == second["x_nm"]
    assert second["raw"]["diameter"] * 1_000_000 != second["diameter_nm"]


def test_each_hole_names_its_tool_number_from_drilldata_tools():
    data = fixture_data()
    emitted = parse(data)["holes"]

    tools = data.tools()
    assert [h["tool"] for h in emitted] == [tools[h.diameter_nm] for h in data.holes]


def test_each_hole_carries_its_identity_not_its_position():
    """``index`` is the hole's stable identity, and nothing else."""
    data = make_data(
        at(10_000_000, -10_000_000, index=7),
        at(-10_000_000, 10_000_000, 5_000_000, index=2),
        at(0, 0, index=5),
    )

    emitted = parse(data)["holes"]

    assert [h["index"] for h in emitted] == [7, 2, 5]


def test_tool_table_matches_drilldata_tools_exactly():
    data = fixture_data()

    tools = parse(data)["tools"]

    assert [list(t) for t in tools] == [["number", "diameter_nm", "count"]] * len(tools)
    assert [(t["number"], t["diameter_nm"]) for t in tools] == [
        (number, diameter_nm) for diameter_nm, number in data.tools().items()
    ]
    assert [t["count"] for t in tools] == [1, 1]


def test_tool_quantities_are_the_models_tool_counts():
    """"Holes per nominal diameter" is one computation, on the model."""
    data = DrillData(
        holes=(
            at(0, 0, index=4),
            at(10_000_000, 0, 5_000_000, index=1),
            at(20_000_000, 0, index=9),
            at(30_000_000, 0, index=6),
        )
    )

    tools = parse(data)["tools"]

    assert [(t["diameter_nm"], t["count"]) for t in tools] == list(data.tool_counts().items())
    assert [t["count"] for t in tools] == [1, 3]


def test_the_tool_numbering_is_read_from_the_model_and_not_re_derived(monkeypatch):
    """The numbering is looked up, not recomputed to agree."""
    data = make_data(
        at(0, 0, 7_000_000, index=5),
        at(10_000_000, 0, 5_000_000, index=2),
        at(20_000_000, 0, 7_000_000, index=8),
    )
    monkeypatch.setattr(DrillData, "tools", lambda self: {7_000_000: 4, 5_000_000: 9})

    document = parse(data)

    assert [(t["number"], t["diameter_nm"]) for t in document["tools"]] == [
        (4, 7_000_000),
        (9, 5_000_000),
    ]
    assert [h["tool"] for h in document["holes"]] == [4, 9, 4]


def test_the_tool_quantities_are_read_from_the_model_and_not_recounted(monkeypatch):
    """``count`` is ``tool_counts()``'s answer, not this emitter's tally."""
    data = make_data(
        at(0, 0, 7_000_000, index=5),
        at(10_000_000, 0, 5_000_000, index=2),
        at(20_000_000, 0, 7_000_000, index=8),
    )
    monkeypatch.setattr(DrillData, "tool_counts", lambda self: {5_000_000: 90, 7_000_000: 40})

    tools = parse(data)["tools"]

    assert [(t["diameter_nm"], t["count"]) for t in tools] == [
        (5_000_000, 90),
        (7_000_000, 40),
    ]


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------


def test_diagnostics_round_trip_with_severity_code_message_and_location():
    diagnostics = parse(fixture_data())["diagnostics"]

    assert list(diagnostics[0]) == ["severity", "code", "message", "location_nm", "data"]
    assert [d["severity"] for d in diagnostics] == ["info", "warning", "warning", "error"]
    assert diagnostics[0]["location_nm"] is None
    assert diagnostics[1]["code"] == "duplicate-hole"
    assert diagnostics[1]["location_nm"] == [-40_000_000, 18_000_000]


def test_a_diagnostic_without_a_payload_carries_an_empty_object():
    """Absent, not omitted: a consumer reads ``data`` on every diagnostic."""
    diagnostics = parse(fixture_data())["diagnostics"]

    assert diagnostics[0]["data"] == {}
    assert diagnostics[3]["data"] == {"stage": "snap"}


def test_a_payload_of_hole_identities_is_emitted_as_an_array():
    """``dropped_indices`` and ``tied_indices`` are tuples in the model."""
    document = parse(fixture_data())
    duplicate, ambiguous = document["diagnostics"][1], document["diagnostics"][2]

    assert duplicate["data"]["dropped_indices"] == [9]
    assert ambiguous["data"]["tied_indices"] == [4, 1]
    embedded = JsonEmitter().document(fixture_data())
    assert embedded["diagnostics"][2]["data"]["tied_indices"] == [4, 1]


def test_diagnostic_payloads_survive_serialisation():
    """The duplicate's payload is the whole point of Diagnostic.data."""
    data = make_data(*holes((0, 0), (0, 0)))
    after = Pipeline([Deduplicate()]).run(data)
    doc = json.loads(JsonEmitter().emit(after))

    assert doc["version"] == 5
    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"]["dropped"] == 1
    assert duplicate["data"]["hole_index"] == doc["holes"][0]["index"]


def test_the_duplicates_payload_names_the_surviving_hole_by_identity():
    """The duplicates payload names the surviving hole by identity."""
    data = make_data(at(50_000_000, 0, index=3), at(0, 0, index=6), at(0, 0, index=9))
    after = Pipeline([Deduplicate()]).run(data)

    doc = json.loads(JsonEmitter().emit(after))

    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"] == {
        "hole_index": 6,
        "diameter_nm": 7_000_000,
        "dropped": 1,
        "dropped_indices": [9],
        "kept": 1,
    }
    assert [h["index"] for h in doc["holes"]] == [3, 6]


def test_error_bearing_data_is_serialised_rather_than_refused():
    """JSON serialises error-bearing data for inspection."""
    raw = RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=None,
        centre=(0.0, 0.0),
        holes=(RawHole(0.0, 18.0, 26.0, 2), RawHole(-19.0, -18.75, 5.0, 6)),
    )
    doc = parse(
        quantise(
            raw,
            enclosure=IdentifyHammondFootprint(),
            diameters=SnapDiametersToDrillTable(),
            positions=SnapPositions(250_000),
        )
    )

    dropped = next(d for d in doc["diagnostics"] if d["severity"] == "error")
    assert dropped["code"] == "unknown-diameter"
    assert dropped["data"]["hole_index"] == 2
    assert [h["index"] for h in doc["holes"]] == [6]


# --------------------------------------------------------------------------
# stage provenance
# --------------------------------------------------------------------------


def test_processing_records_what_the_pipeline_did():
    """The document states the grid these holes were snapped to."""
    document = parse(fixture_data())

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


def test_processing_records_the_stages_a_real_pipeline_ran():
    data = make_data(*holes((0, 0), (0, 0)))

    after = Pipeline([Deduplicate()]).run(data)

    assert parse(after)["processing"] == [{"name": "deduplicate", "parameters": {}}]


def test_a_pipeline_that_never_ran_leaves_processing_empty_not_absent():
    document = parse(make_data(at(0, 0, index=4)))

    assert document["processing"] == []


def test_the_exposed_mapping_is_already_json_shaped():
    """``document()`` is public so callers can embed it; what they embed must
    equal what a reader parses back, not merely dump to the same text."""
    data = fixture_data()

    assert JsonEmitter().document(data) == parse(data)


# --------------------------------------------------------------------------
# full round trip
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [fixture_data, rotated_fixture_data, square_fixture_data],
    ids=["landscape-declared", "rotated-undeclared", "square-rotated-declared"],
)
def test_document_rebuilds_an_identical_drilldata(build):
    """Every ``DrillData`` field survives serialisation and reconstruction."""
    data = build()
    document = parse(data)

    rebuilt = DrillData(
        holes=tuple(
            Hole(
                x_nm=h["x_nm"],
                y_nm=h["y_nm"],
                diameter_nm=h["diameter_nm"],
                raw=RawHole(h["raw"]["x"], h["raw"]["y"], h["raw"]["diameter"], h["index"]),
                index=h["index"],
            )
            for h in document["holes"]
        ),
        reference=ReferenceOutline(
            width_nm=document["reference"]["width_nm"],
            height_nm=document["reference"]["height_nm"],
            centre_x_nm=document["reference"]["centre_x_nm"],
            centre_y_nm=document["reference"]["centre_y_nm"],
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
                location_nm=d["location_nm"],
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
        enclosure=EnclosureMatch(
            family=document["enclosure"]["family"],
            length_nm=document["enclosure"]["length_nm"],
            width_nm=document["enclosure"]["width_nm"],
            candidates=document["enclosure"]["candidates"],
            rotated=document["enclosure"]["rotated"],
            selected_part=document["enclosure"]["selected_part"],
        ),
    )

    assert rebuilt == data
    assert rebuilt.diagnostics[1].get("hole_index") == 4
    assert rebuilt.last_run("snap-diameters").get("sizes_nm") == (5_000_000, 7_000_000)


def test_the_identities_in_a_rebuilt_payload_are_tuples_again():
    """A rebuilt finding must be usable, not merely printable."""
    data = fixture_data()
    document = parse(data)

    rebuilt = tuple(
        Diagnostic(
            severity=Severity(d["severity"]),
            code=d["code"],
            message=d["message"],
            location_nm=d["location_nm"],
            data=tuple(d["data"].items()),
        )
        for d in document["diagnostics"]
    )

    assert rebuilt[1].get("dropped_indices") == (9,)
    assert rebuilt[2].get("tied_indices") == (4, 1)
    assert rebuilt == data.diagnostics
    assert {hash(d) for d in rebuilt} == {hash(d) for d in data.diagnostics}


# --------------------------------------------------------------------------
# purity and determinism
# --------------------------------------------------------------------------


def test_hole_order_is_preserved_not_re_sorted():
    """Ordering is ``pipeline.SortHoles``' decision, not this emitter's."""
    data = DrillData(
        holes=(
            at(10_000_000, -10_000_000, index=4),
            at(-10_000_000, 10_000_000, 5_000_000, index=1),
            at(0, 0, index=9),
        )
    )

    assert [(h["x_nm"], h["y_nm"]) for h in parse(data)["holes"]] == [
        (10_000_000, -10_000_000),
        (-10_000_000, 10_000_000),
        (0, 0),
    ]


def test_emitter_does_not_round_or_cluster_values():
    data = DrillData(
        holes=(
            Hole(
                x_nm=123_457,
                y_nm=-765_432,
                diameter_nm=6_999_800,
                raw=RawHole(0.1234567, -0.7654321, 6.9998, 4),
                index=4,
            ),
            at(1_000_000, 1_000_000, index=1),
        )
    )
    document = parse(data)

    assert document["holes"][0]["x_nm"] == 123_457
    assert document["holes"][0]["diameter_nm"] == 6_999_800
    assert document["holes"][0]["raw"]["x"] == 0.1234567
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
