"""Tests for the JSON emitter: its registration, its wrapping, and what a real run states.

The document's own shape belongs to the codec that writes it, and is tested
beside it in stompmodel. What is left here is the emitter as an emitter, and
the documents this package's quantisation and pipeline actually produce.
"""

from __future__ import annotations

import json

import pytest

from stompdrill.emitters.base import REGISTRY, get_emitter
from stompdrill.emitters.json_out import JsonEmitter, JsonOptions
from stompdrill.pipeline import (
    Deduplicate,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from stompdrill.protocols import Emitter, Pipeline
from stompdrill.quantise import RawDrillData, quantise
from stompmodel.codec import to_document
from stompmodel.errors import EmitterError
from stompmodel.model import (
    DrillData,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
)
from stompmodel.units import Millimetre, Nanometre
from tests.conftest import at, holes, make_data

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def emit(data: DrillData, **kwargs) -> str:
    options = JsonOptions(**kwargs) if kwargs else None
    return JsonEmitter(options).emit(data)


def parse(data: DrillData, **kwargs) -> dict:
    return json.loads(emit(data, **kwargs))


def read_panel(
    outline: RawOutline | None, *, case: str | None = None, measured: RawHole | None = None
) -> DrillData:
    """One measured panel put through the real quantisation phase, numbered
    as if ``RouteHoles`` had already run — the JSON emitter requires a number."""
    raw = RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=outline,
        centre=(Millimetre(297.6), Millimetre(421.0)),
        holes=(measured if measured is not None else RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(7.0)),),
    )
    data = quantise(
        raw,
        enclosure=IdentifyHammondFootprint(case),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(Nanometre(250_000)),
    )
    return data.with_holes(h.with_number(i) for i, h in enumerate(data.holes, start=1))


def a_real_panel() -> DrillData:
    """The document a real run of this package produces, outline and all."""
    return read_panel(RawOutline(Millimetre(113.0), Millimetre(60.0)), case="1590b2")


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
    import stompdrill.emitters  # noqa: F401  (importing the package must register)

    assert REGISTRY["json"] is JsonEmitter
    assert get_emitter("json") is JsonEmitter


def test_emitter_declares_name_media_type_and_extension():
    assert JsonEmitter.name == "json"
    assert JsonEmitter.media_type == "application/json"
    assert JsonEmitter.extension == ".json"
    assert isinstance(JsonEmitter(), Emitter)


def test_the_emitter_refuses_data_that_was_never_routed():
    data = make_data(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
                     reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000)))
    with pytest.raises(EmitterError, match="RouteHoles"):
        emit(data)


# --------------------------------------------------------------------------
# what the emitter adds to the document
# --------------------------------------------------------------------------


def test_output_parses_as_json():
    assert isinstance(parse(a_real_panel()), dict)


def test_the_emitted_text_is_the_codecs_mapping_and_nothing_else():
    """The emitter serialises; it does not decide what the document says."""
    data = a_real_panel()

    assert parse(data) == to_document(data)


def test_emit_is_deterministic_and_does_not_mutate_its_input():
    data = a_real_panel()
    before = tuple(data.holes)

    first = emit(data)

    assert first == emit(data)
    assert data.holes == before


def test_indent_option_controls_formatting_only():
    data = a_real_panel()

    compact = emit(data, indent=None)

    assert "\n" not in compact.strip()
    assert json.loads(compact) == parse(data)


def test_output_ends_with_a_newline():
    assert emit(a_real_panel()).endswith("\n")


# --------------------------------------------------------------------------
# every nominal length a real run emits is a whole number of nanometres
# --------------------------------------------------------------------------


def test_no_nominal_length_is_a_float():
    """One sweep over the whole document, rather than a list of fields."""
    document = parse(a_real_panel())

    assert [(where, value) for where, value in nominal_lengths(document) if type(value) is not int] == []


def test_the_sweep_reaches_every_kind_of_length_there_is():
    """The length sweep reaches every document section.

    Named paths prevent an empty or partially narrowed sweep passing vacuously.
    """
    document = parse(a_real_panel())

    where = {path for path, _ in nominal_lengths(document)}

    assert ".reference.width_nm" in where
    assert ".reference.centre_x_nm" in where
    assert ".tools[0].diameter_nm" in where
    assert ".holes[0].x_nm" in where
    assert ".enclosure.length_nm" in where
    assert ".processing[0].parameters.tolerance_nm" in where


# --------------------------------------------------------------------------
# the document a real run produces
# --------------------------------------------------------------------------


def test_enclosure_is_what_the_quantisation_phase_found():
    """End to end, against the real catalogue rather than a hand-built match."""
    document = parse(a_real_panel())

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
    document = parse(read_panel(RawOutline(Millimetre(200.0), Millimetre(45.0))))

    assert document["enclosure"] is None
    assert [d["code"] for d in document["diagnostics"]] == ["unknown-enclosure"]
    assert document["reference"]["width_nm"] == 200_000_000


def test_diagnostic_payloads_survive_serialisation():
    """The duplicate's payload is the whole point of Diagnostic.data."""
    data = make_data(*holes((0, 0), (0, 0)))
    after = Pipeline([Deduplicate()]).run(data)
    doc = json.loads(JsonEmitter().emit(after))

    assert doc["version"] == 5
    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"]["dropped"] == 1
    assert duplicate["location_nm"] == [doc["holes"][0]["x_nm"], doc["holes"][0]["y_nm"]]


def test_the_duplicates_payload_names_the_surviving_hole_by_location():
    """The duplicate's location names the surviving hole, not a number."""
    data = make_data(at(50_000_000, 0, index=3), at(0, 0, index=6), at(0, 0, index=9))
    after = Pipeline([Deduplicate()]).run(data)

    doc = json.loads(JsonEmitter().emit(after))

    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"] == {
        "diameter_nm": 7_000_000,
        "dropped": 1,
    }
    assert duplicate["location_nm"] == [0, 0]
    assert [h["index"] for h in doc["holes"]] == [3, 6]


def test_error_bearing_data_is_serialised_rather_than_refused():
    """JSON serialises error-bearing data for inspection."""
    raw = RawDrillData(
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
        reference=None,
        centre=(0.0, 0.0),
        holes=(RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(26.0)), RawHole(Millimetre(-19.0), Millimetre(-18.75), Millimetre(5.0))),
    )
    data = quantise(
        raw,
        enclosure=IdentifyHammondFootprint(),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(Nanometre(250_000)),
    )
    doc = parse(data.with_holes(h.with_number(6) for h in data.holes))

    dropped = next(d for d in doc["diagnostics"] if d["severity"] == "error")
    assert dropped["code"] == "unknown-diameter"
    assert dropped["location_nm"] == [0, 18_000_000]
    assert [h["index"] for h in doc["holes"]] == [6]


def test_processing_records_the_stages_a_real_pipeline_ran():
    data = make_data(*holes((0, 0), (0, 0)))

    after = Pipeline([Deduplicate()]).run(data)

    assert parse(after)["processing"] == [{"name": "deduplicate", "parameters": {}}]
