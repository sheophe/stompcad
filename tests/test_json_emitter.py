"""Tests for the JSON emitter (SPEC §7, PLAN task D).

JSON is the integration surface for the wider toolchain, so these tests pin the
document *shape*, not just its contents: key order, key names and the presence of
raw provenance are all part of the contract other tools code against.
"""

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
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.pipeline import Deduplicate, IdentifyHammondFootprint
from aidrill.protocols import Emitter, Pipeline
from tests.conftest import at, holes, make_data


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def fixture_data() -> DrillData:
    """A DrillData exercising every field: nominal-vs-raw drift, a reference
    outline, one diagnostic of each severity, full source info, and the stages
    that produced it.

    Every detail here exists to break a coincidence, because this fixture is
    what the round-trip test's ``==`` is worth.

    The hole identities are 4 and 1 — neither sequential nor equal to their
    position in the document — because a fixture numbered 0, 1 in the order it
    lists its holes cannot tell a serialised identity from a serialised list
    index; gaps are what survives a Deduplicate anyway. Two of the three
    diagnostics carry a payload, because a document that drops ``data`` still
    round-trips empty ones. The outline is *snapped* — measured 113 × 60,
    resized to a catalogue 112 × 61 — because an outline whose ``raw`` equals
    its nominal size cannot tell a serialised measurement from a re-derived
    one, and the round-trip test stayed green for exactly that reason while
    ``reference.raw`` was being dropped on the way out.

    The enclosure match is the same lesson applied a third time. Its
    ``selected_part`` is set, and set to a candidate that is neither the first
    nor the last of the three, so neither a dropped key nor ``candidates[0]``
    can impersonate it — ``rotated_fixture_data`` covers the ``None`` half.
    Its ``candidates`` are listed out of alphabetical order, because a tuple
    already in the order ``sorted()`` would produce cannot tell a passthrough
    from a re-sort, and ADR-0001 forbids an emitter the second. And
    ``length_mm``/``width_mm`` differ from one another, so a document that
    transposed them would not read back identically.
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
                "snap-diameters",
                (("standard", "metric"), ("size_count", 2), ("sizes_mm", (5.0, 7.0))),
            ),
        ),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_mm=112,
            width_mm=61,
            candidates=("1590BS", "1590B", "1590B2"),
            rotated=False,
            selected_part="1590B",
        ),
    )


def rotated_fixture_data() -> DrillData:
    """A portrait panel, no case declared, and a catalogue this build cannot emit.

    Only the outline and the match differ from ``fixture_data``, so both go
    through one round-trip test. They differ in the two fields whose defaults
    make a dropped key invisible: ``rotated`` is ``True`` here where it is
    ``False`` there, and ``selected_part`` is ``None`` here where it names a
    part there. A serialiser that omitted either would rebuild one fixture
    correctly and the other silently wrong, which is the whole reason there
    are two.

    ``length_mm``/``width_mm`` stay in the catalogue's orientation — 112 × 61
    — while the outline is the 61 × 112 the artwork was drawn as. That is not
    an inconsistency to tidy up: transposing the match would make the footprint
    unfindable in the datasheet it came from, and it is the one thing
    ``rotated`` is for.

    The ``family`` is deliberately **not** the shipped catalogue's, and neither
    are the designators. ``EnclosureMatch.family`` is a free string, but
    ``IdentifyHammondFootprint`` can only ever set it to one value, so a
    fixture repeating that value cannot tell a serialised ``family`` from a
    hard-coded literal — the same coincidence as an outline whose ``raw``
    equals its nominal size. A name this build could never produce is what
    makes the passthrough checkable; ``fixture_data`` and the end-to-end test
    still pin the real one. These figures and designators are the fixture's
    own — ``enclosures.py`` is the only place that carries datasheet values.
    """
    return replace(
        fixture_data(),
        reference=ReferenceOutline.from_measurement(
            60.0, 113.0, centre_x=297.6, centre_y=421.0
        ).resized(61.0, 112.0),
        enclosure=EnclosureMatch(
            family="Hammond 1550",
            length_mm=112,
            width_mm=61,
            candidates=("1550S", "1550A", "1550B"),
            rotated=True,
            selected_part=None,
        ),
    )


def square_fixture_data() -> DrillData:
    """A square footprint, rotated, with a case declared. It breaks a correlation.

    Two fixtures were not enough, and the way they failed is the lesson. Across
    both, ``rotated is True`` held exactly when ``selected_part is None`` and
    exactly when the outline was portrait — so three re-derivations passed the
    whole suite: ``match.selected_part is None``, ``match.candidates[1]``
    keyed on rotation, and worst of all
    ``data.reference.width < data.reference.height``. That last one is an
    emitter computing a pipeline fact from geometry, which is the founding
    rule of ADR-0001, and every *safe* spelling of the bug — dropping the key,
    hard-coding either value — died while the *dangerous* one lived.

    A square footprint decouples all three at once: 120 × 120 is neither
    portrait nor landscape, so no comparison of the outline's axes can produce
    ``rotated``; ``rotated`` is ``True`` here *with* a declared part, so
    neither field can be computed from the other. Note this is the exact
    inverse of the usual warning about square fixtures — a square is useless
    for telling length from width, and is precisely what is needed to tell
    rotation from portrait-ness.

    1590Q, 1590U and 1590V really are all 120 × 120, so the footprint is a real
    one. The matcher would not itself report a square as rotated — it prefers
    the unrotated reading when both fit, because calling it a rotation would
    put "rotated" on a drawing for a panel nobody turned — and that is the
    point: this emitter serialises what it is handed, and must not infer that
    combination away.
    """
    return replace(
        fixture_data(),
        reference=ReferenceOutline.from_measurement(
            121.0, 119.0, centre_x=297.6, centre_y=421.0
        ).resized(120.0, 120.0),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_mm=120,
            width_mm=120,
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
    """Version 4 is the release that added ``enclosure``.

    The number is how a consumer knows the key is there to read: a document
    that grew ``enclosure`` while still calling itself version 3 would tell a
    v3 reader nothing had changed, and tell the toolchain that a document
    *without* the key is the same document as one with it.
    """
    document = parse(fixture_data())

    assert document["format"] == "aidrill-drill-data"
    assert document["version"] == 4
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


# --------------------------------------------------------------------------
# the enclosure match
# --------------------------------------------------------------------------


def test_enclosure_names_the_footprint_the_panel_was_identified_as():
    """The whole product of the matching stage, or the consumer cannot see it.

    ``DrillData.enclosure`` reached no output at all: a library consumer was
    handed a panel snapped to 112 × 61 with nothing in the document saying it
    had been identified as a Hammond footprint, let alone which one. Re-deriving
    it means re-implementing the matcher's tolerance rule against the catalogue
    — a second, divergent copy of the decision, which is the defect ADR-0001
    exists to stop.
    """
    enclosure = parse(fixture_data())["enclosure"]

    assert list(enclosure) == [
        "family",
        "length_mm",
        "width_mm",
        "candidates",
        "rotated",
        "selected_part",
    ]
    assert enclosure["family"] == "Hammond 1590"
    assert enclosure["length_mm"] == 112
    assert enclosure["width_mm"] == 61


def test_enclosure_candidates_keep_the_order_they_were_matched_in():
    """A 2-D outline identifies a footprint, never a part, so every part sharing
    it is named — in the order the match holds them.

    Sorting here would be an emitter deciding a pipeline fact, which ADR-0001
    forbids for the same reason it forbids rounding: the drawing and this
    document would then present two orders of one list and the operator would
    have to guess which was the matcher's. The fixture is deliberately not in
    alphabetical order, because a list that already is cannot tell a
    passthrough from a ``sorted()``.
    """
    candidates = parse(fixture_data())["enclosure"]["candidates"]

    assert candidates == ["1590BS", "1590B", "1590B2"]
    assert candidates != sorted(candidates)


def test_enclosure_dimensions_stay_the_catalogues_whole_millimetres():
    """``length_mm`` is an ``int``; ``reference.width`` is a ``float``.

    The distinction is the datasheet's: Hammond's metric column is whole
    millimetres, and the outline is measured artwork. A document that emitted
    ``112.0`` would read back as a measurement of exactly 112 rather than the
    catalogue's nominal figure, and — since ``112 == 112.0`` in Python — the
    round-trip test would compare equal while the type went out wrong.
    """
    document = parse(fixture_data())
    enclosure = document["enclosure"]

    assert isinstance(enclosure["length_mm"], int)
    assert isinstance(enclosure["width_mm"], int)
    assert isinstance(document["reference"]["width"], float)
    assert isinstance(document["reference"]["raw"]["height"], float)
    # And in the artifact itself, per CLAUDE.md: a consumer in a language with
    # one number type sees 112 either way, so the distinction only survives if
    # it is in the bytes. The same figure, spelled twice, one line apart.
    text = emit(fixture_data())
    assert '"length_mm": 112,' in text
    assert '"width": 112.0,' in text


def test_enclosure_records_whether_the_panel_was_drawn_rotated():
    """``rotated`` says the panel is the catalogue footprint turned 90°.

    It defaults to ``False``, so a document that dropped the key would describe
    every portrait panel as landscape and nothing would contradict it. Both
    values are asserted for that reason: the ``False`` case alone proves only
    that something absent looks like the default.

    ``family`` rides along here because the rotated fixture is the one that
    names a catalogue this build cannot produce, and a passthrough is only
    distinguishable from a literal where the two differ.
    """
    assert parse(fixture_data())["enclosure"]["rotated"] is False
    assert parse(rotated_fixture_data())["enclosure"]["rotated"] is True
    assert parse(square_fixture_data())["enclosure"]["rotated"] is True
    assert parse(rotated_fixture_data())["enclosure"]["family"] == "Hammond 1550"


def test_enclosure_rotation_is_reported_against_an_untransposed_footprint():
    """A rotated match keeps the catalogue's own length and width.

    Transposing them to agree with the artwork would make the footprint
    unfindable in the datasheet it was read from — the panel is 61 × 112 and
    the enclosure is still the 112 × 61 1590B.
    """
    document = parse(rotated_fixture_data())

    assert (document["reference"]["width"], document["reference"]["height"]) == (61.0, 112.0)
    assert (document["enclosure"]["length_mm"], document["enclosure"]["width_mm"]) == (112, 61)


def test_rotation_is_not_re_derivable_from_the_outline_or_the_declared_part():
    """``rotated`` must be read off the match, never worked out from the data.

    An emitter that computed ``reference.width < reference.height`` would agree
    with every portrait fixture in this file and be an ADR-0001 violation
    outright — a pipeline fact re-derived downstream. One that computed
    ``selected_part is None`` would agree just as well, because a rotated panel
    happened to be the undeclared one in both earlier fixtures.

    The square footprint refuses both readings at once: 120 × 120 is neither
    portrait nor landscape, and it is rotated *and* declared. This is the
    positive claim, made where the coincidences have been removed.
    """
    document = parse(square_fixture_data())
    enclosure = document["enclosure"]

    assert document["reference"]["width"] == document["reference"]["height"]
    assert enclosure["length_mm"] == enclosure["width_mm"]
    assert enclosure["rotated"] is True
    assert enclosure["selected_part"] == "1590Q"


def test_enclosure_carries_the_declared_part_and_its_absence():
    """``selected_part`` is operator knowledge, never inferred from geometry.

    The artwork cannot say which of three parts sharing a footprint the panel
    is for, so this is either what the operator declared or ``None``. Both are
    asserted: an emitter that dropped the key, and one that hard-coded
    ``None``, each survive a fixture that only ever declares nothing.
    """
    declared = parse(fixture_data())["enclosure"]

    assert declared["selected_part"] == "1590B"
    assert declared["selected_part"] in declared["candidates"]
    assert parse(rotated_fixture_data())["enclosure"]["selected_part"] is None


def test_unmatched_enclosure_is_null_not_omitted():
    """No match is a value a consumer reads, not a key it has to test for."""
    document = parse(DrillData(holes=(Hole.from_measurement(0.0, 0.0, 7.0, index=0),)))

    assert "enclosure" in document
    assert document["enclosure"] is None


def test_enclosure_is_what_the_matching_stage_found():
    """End to end, against the real catalogue rather than a hand-built match.

    The fixtures above are written by hand, so they pin the document's shape but
    could describe an enclosure the matcher would never produce. Here the stage
    runs: 113 × 60 of measured artwork comes out as the 112 × 61 footprint, the
    three parts that share it, and the case the operator declared — normalised
    to catalogue form on the way through.
    """
    data = make_data(
        at(0.0, 0.0, index=0),
        reference=ReferenceOutline.from_measurement(113.0, 60.0),
    )

    after = Pipeline([IdentifyHammondFootprint(expected_part="1590b2")]).run(data)

    assert parse(after)["enclosure"] == {
        "family": "Hammond 1590",
        "length_mm": 112,
        "width_mm": 61,
        "candidates": ["1590B", "1590B2", "1590BS"],
        "rotated": False,
        "selected_part": "1590B2",
    }


def test_an_unrecognised_outline_leaves_the_enclosure_null_and_says_so():
    """The warning and the null are one finding, not two computations.

    A panel this catalogue has never heard of is left exactly as measured, so
    the document must carry both halves of that: no match, and the reason.
    """
    data = make_data(
        at(0.0, 0.0, index=0),
        reference=ReferenceOutline.from_measurement(200.0, 45.0),
    )

    after = Pipeline([IdentifyHammondFootprint()]).run(data)
    document = parse(after)

    assert document["enclosure"] is None
    assert [d["code"] for d in document["diagnostics"]] == ["unknown-enclosure"]
    assert document["reference"]["width"] == 200.0


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

    assert doc["version"] == 4
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


def test_error_bearing_data_is_serialised_rather_than_refused():
    """The deliberate opposite of the Excellon emitter, for the reason that
    separates the two formats.

    ``SnapDiametersToDrillTable`` reports an unmatched diameter as an ERROR and
    drops the hole, so the drill file it would produce is one hole short and
    says nothing about it — which is why that emitter refuses error-bearing data
    outright. This document has ``diagnostics``, so it is not silent about
    anything: the finding, its payload and the gap it left are all readable, and
    hole 2 is visibly absent from a hole list that still names its identities.
    Refusing here would deny a consumer the one artifact that can tell it *why*
    the run failed, and would break the round trip this file is built on — the
    fixture carries an ERROR precisely so that severity is exercised.
    """
    data = make_data(
        at(-19.0, -18.75, 5.0, index=6), reference=ReferenceOutline(113.0, 60.0)
    ).with_diagnostics(
        Diagnostic.error(
            "unknown-diameter",
            "hole 2: dia 7.000 mm matches no metric drill size",
            (0.0, 18.0),
            data=(("hole_index", 2), ("diameter", 7.0)),
        )
    )

    doc = parse(data)

    dropped = next(d for d in doc["diagnostics"] if d["severity"] == "error")
    assert dropped["code"] == "unknown-diameter"
    assert dropped["data"] == {"hole_index": 2, "diameter": 7.0}
    assert [h["index"] for h in doc["holes"]] == [6]


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
            "name": "snap-diameters",
            "parameters": {"standard": "metric", "size_count": 2, "sizes_mm": [5.0, 7.0]},
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


@pytest.mark.parametrize(
    "build",
    [fixture_data, rotated_fixture_data, square_fixture_data],
    ids=["landscape-declared", "rotated-undeclared", "square-rotated-declared"],
)
def test_document_rebuilds_an_identical_drilldata(build):
    """Nothing in DrillData may be lost on the way out — this is the whole point
    of the format.

    ``==`` on a frozen dataclass is only as strong as the fixture: it passed for
    a while over holes with no identity, diagnostics with empty payloads and no
    stage records at all, which made "nothing is lost" a claim about three
    absent fields. It then passed over an *unsnapped* reference outline, where
    ``raw`` equals the nominal size — so a document that dropped the outline's
    measurement rebuilt it from the nominal values and compared equal, and the
    claim in the first paragraph was false for a fourth field while this test
    stayed green.

    ``enclosure`` is the same trap three times over, which is why this runs
    over three fixtures rather than one. ``rotated`` defaults to ``False`` and
    ``selected_part`` to ``None``, so a single fixture leaving either at its
    default would rebuild a dropped key out of the default and compare equal
    again — that takes two. The third is the square footprint: with only the
    first two, ``rotated`` was ``True`` in exactly the fixture that was
    portrait and exactly the fixture that declared no part, so a serialiser
    *computing* it from either would have rebuilt both correctly. Every field
    below is read back **out of the document** — nothing is recomputed from
    ``data``, or this would be testing the fixture.
    """
    data = build()
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
        enclosure=EnclosureMatch(
            family=document["enclosure"]["family"],
            length_mm=document["enclosure"]["length_mm"],
            width_mm=document["enclosure"]["width_mm"],
            # The list ``json.loads`` hands back, not a tuple built here: the
            # coercion belongs to the model, and a deserialiser that had to
            # know to make tuples would be one more place to forget.
            candidates=document["enclosure"]["candidates"],
            rotated=document["enclosure"]["rotated"],
            selected_part=document["enclosure"]["selected_part"],
        ),
    )

    assert rebuilt == data
    assert rebuilt.diagnostics[1].get("hole_index") == 4
    assert rebuilt.last_run("snap-diameters").get("sizes_mm") == (5.0, 7.0)


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
