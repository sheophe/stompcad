"""JSON emitter (SPEC §7) — the integration surface for the wider toolchain.

Everything in ``DrillData`` comes out: nominal positions *and* the raw measured
values behind them, the reference outline, the tool table, every diagnostic, and
where the data came from. A consumer can rebuild an identical ``DrillData`` from
this document, which is what ``test_json_emitter.py`` asserts.

Document shape (version 5)::

    {
      "format": "aidrill-drill-data",
      "version": 5,
      "units": "nm",                     # the canonical frame's unit
      "origin": "centre",                # centre of the reference outline, Y up
      "source":     {"path", "drill_layer", "reference_layer",
                     "layers_found", "producer"},
      "reference":  {"width_nm", "height_nm", "centre_x_nm", "centre_y_nm",
                     "raw": {"width", "height"}} | null,
      "tools":     [{"number", "diameter_nm", "count"}, …],  # ascending
      "holes":     [{"x_nm", "y_nm", "diameter_nm", "tool",
                     "raw": {"x", "y", "diameter"},
                     "index"}, …],                         # pipeline order
      "diagnostics": [{"severity", "code", "message", "location_nm", "data"},
                      …],
      "processing":  [{"name", "parameters": {…}}, …],      # in the order run
      "enclosure":  {"family", "length_nm", "width_nm", "candidates",
                     "rotated", "selected_part"} | null
    }

**The key names carry the unit, exactly as the model's field names do.** A
nominal length — a position, a diameter, a footprint, a grid pitch recorded in
``processing`` — is a whole number of nanometres under a key ending ``_nm``, and
it is an ``int`` in the JSON rather than a decimal. That is the same contract
``model.py`` states and ``_check_payload_lengths`` enforces one layer in, and it
is here for the reason it is there: a float is a quantity two readers can round
differently, and this document is read by tools that will render it beside a
drill file this project also wrote. A consumer wanting millimetres divides by a
million, once, where it prints.

The unsuffixed values under ``raw`` are the other kind of length and are
deliberately *not* nanometres: they are the float millimetres the artwork
measured, before anything was quantised. The suffix is what tells the two apart
at a glance, in a document as in the model, so ``"width_nm": 112400000`` beside
``"width": 113.0`` is a catalogue footprint beside the measurement it replaced
and neither can be mistaken for the other.

``enclosure.length_nm``/``width_nm`` are nanometres for that same reason and not
for symmetry. The catalogue holds Hammond's own 0.05 mm figures — a 1590B is
112.40 mm — so there is no whole-millimetre integer to emit, and a float
millimetre would put the one class of value this project refuses to hold into
the one document a consumer parses.

Four things are here because a consumer would otherwise reconstruct them from
geometry, which is the founding bug of this project displaced one layer out into
the toolchain:

``index`` is the hole's stable identity, not its position in the array. It is
what a diagnostic's ``hole_index`` joins to, and the two stop agreeing the
moment a stage sorts or drops holes, so a consumer must never substitute one
for the other. The identity on the hole's ``raw`` is not serialised beside it
because ``Hole.__post_init__`` refuses a hole whose two identities differ —
there is one number, written once.

``data`` is the diagnostic's machine-readable payload, always present, ``{}``
when the diagnostic had none. Without it, a consumer asked which holes were
duplicates had only their positions to go on and had to re-implement
``Deduplicate``'s rule to find out — a second, divergent copy of the rule, which
is exactly the mistake the drawing emitter made inside this codebase.

``processing`` is what the pipeline actually did, in order, with *effective*
parameter values. A consumer that has to be told the grid out of band can be
told the wrong one; a document that states it cannot disagree with itself.

``reference.raw`` is the outline as measured off the artwork. A hole's ``raw``
was serialised while the outline's was not, and once quantising snaps the
outline to a catalogue footprint — the fixture panel measures 113.000 × 60.000
mm where 1590B is 112.400 × 60.500 — that omission sent a *nominal* size out as
though it were what the artwork said. Nothing downstream could then recover the
measurement, which is the same class of defect as re-deriving a pipeline fact,
only worse: the fact is gone, not merely recomputed. The round-trip test did not
notice for the classic reason — its fixture outline was unsnapped, so ``raw``
and nominal coincided and a dropped key rebuilt itself.

``enclosure`` is that hole one step further on: the entire product of enclosure
matching once reached no output whatsoever. A consumer was handed a snapped
outline with nothing saying it had been identified as anything, so the only
route back to "which enclosure is this panel?" was to re-implement the matcher's
tolerance rule against the catalogue — a second, divergent copy of a decision,
which is precisely what ADR-0001 was written about. ``processing`` cannot stand
in: it records that ``identify-enclosure`` ran and with what tolerance, never
what it concluded.

``version`` names this shape, and it is the one version number this project
carries: something outside the repository parses this document, so a consumer
needs to be able to say which spelling of it it understands. It changes whenever
a key is added, removed or renamed.

Key order is fixed and part of the contract, so diffing two runs shows real
changes rather than dictionary reshuffling. ``location_nm`` is ``[x_nm, y_nm]``
in the canonical frame, or ``null`` for a finding about the panel as a whole.

Sequences are emitted as JSON arrays, which is what a tuple in the model becomes
— ``candidates``, a diameter table in ``processing``, and the tuples of hole
identities a ``duplicate-hole`` or ``grid-ambiguous`` finding carries in its
payload. The mapping :meth:`JsonEmitter.document` hands a caller holds ``list``
for every one of them rather than the model's ``tuple``, so that what a caller
embeds is the same object a reader gets back from :func:`json.loads` instead of
one that only compares equal after a round trip through the text.

Like every emitter, this one only serialises: hole order is whatever the pipeline
left behind, values are passed through unrounded, and both the tool numbers and
the per-tool quantities come from the model — :meth:`DrillData.tools` and
:meth:`DrillData.tool_counts` — so this document, the drawing's schedule and the
CLI report cannot disagree about how many holes a bit drills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from ..model import (
    Diagnostic,
    DrillData,
    EnclosureMatch,
    Hole,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter", "FORMAT", "VERSION"]

FORMAT = "aidrill-drill-data"
VERSION = 5


@dataclass(frozen=True, slots=True)
class JsonOptions:
    """``indent`` is passed straight to :func:`json.dumps`; ``None`` is compact."""

    indent: int | None = 2


@register_emitter
class JsonEmitter:
    """Emit the whole of ``DrillData`` as JSON."""

    name: ClassVar[str] = "json"
    media_type: ClassVar[str] = "application/json"
    extension: ClassVar[str] = ".json"

    def __init__(self, options: JsonOptions | None = None) -> None:
        self.options = options if options is not None else JsonOptions()

    # -- public ----------------------------------------------------------
    def emit(self, data: DrillData) -> str:
        return json.dumps(self.document(data), indent=self.options.indent) + "\n"

    def document(self, data: DrillData) -> dict[str, Any]:
        """The JSON-ready mapping, exposed so callers can embed it elsewhere."""
        tools = data.tools()
        counts = data.tool_counts()

        return {
            "format": FORMAT,
            "version": VERSION,
            "units": "nm",
            "origin": "centre",
            "source": _source(data.source),
            "reference": _reference(data.reference),
            "tools": [
                {
                    "number": number,
                    "diameter_nm": diameter_nm,
                    "count": counts[diameter_nm],
                }
                for diameter_nm, number in tools.items()
            ],
            "holes": [_hole(h, tools[h.diameter_nm]) for h in data.holes],
            "diagnostics": [_diagnostic(d) for d in data.diagnostics],
            "processing": [_stage_run(r) for r in data.processing],
            "enclosure": _enclosure(data.enclosure),
        }


def _source(source: SourceInfo) -> dict[str, Any]:
    return {
        "path": source.path,
        "drill_layer": source.drill_layer,
        "reference_layer": source.reference_layer,
        "layers_found": list(source.layers_found),
        "producer": source.producer,
    }


def _reference(reference: ReferenceOutline | None) -> dict[str, Any] | None:
    """The outline, measurement included.

    ``raw`` is emitted for the same reason a hole's is: once quantising snaps
    the outline to a catalogue footprint, the nominal width is no longer what
    the artwork said, and a consumer cannot recover the difference from a
    document that only carries the snapped value.

    The four nominal keys carry ``_nm`` and the two under ``raw`` do not, and
    that asymmetry is the point rather than an oversight: 112 400 000 is the
    catalogue's figure held exactly, 113.0 is what a bounding box of a stroked
    path came to. A document that spelled both the same way would let a reader
    treat a snap as a measurement, which is the whole reason ``raw`` exists.
    """
    if reference is None:
        return None
    return {
        "width_nm": reference.width_nm,
        "height_nm": reference.height_nm,
        "centre_x_nm": reference.centre_x_nm,
        "centre_y_nm": reference.centre_y_nm,
        "raw": {"width": reference.raw.width, "height": reference.raw.height},
    }


def _hole(hole: Hole, tool: int) -> dict[str, Any]:
    """One hole, identity included.

    ``index`` is emitted as the model holds it, never as the loop counter that
    happens to agree with it in unsorted data: after ``SortHoles`` or
    ``Deduplicate`` the two differ, and a consumer joining a diagnostic's
    ``hole_index`` against the array position would then point at the wrong
    hole while looking entirely plausible.

    It is written once, though the model carries it twice: ``raw`` gets the
    three measured lengths and not the identity beside them, because
    ``Hole.__post_init__`` refuses a hole whose two identities differ. Two
    copies of a number nothing can make disagree would only invite a reader to
    ask which one wins.
    """
    return {
        "x_nm": hole.x_nm,
        "y_nm": hole.y_nm,
        "diameter_nm": hole.diameter_nm,
        "tool": tool,
        "raw": {"x": hole.raw.x, "y": hole.raw.y, "diameter": hole.raw.diameter},
        "index": hole.index,
    }


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    """One finding, payload included.

    ``data`` is an object rather than the model's pair list because that is what
    a consumer indexes by key, and it is always present — ``{}`` for a finding
    that carried none — so nobody has to branch on its absence.

    A payload *value* becomes a ``list`` when it is a sequence, for the same
    reason ``_stage_run`` converts a diameter table: ``duplicate-hole`` carries
    ``dropped_indices`` and ``grid-ambiguous`` carries ``tied_indices``, both
    tuples of hole identities, and leaving them as tuples would make the mapping
    ``document()`` returns differ from the one :func:`json.loads` gives back
    while both print identically. ``Diagnostic.__post_init__`` coerces the list
    to a tuple again on the way in, so a finding rebuilt from this document
    compares equal to the one the pipeline produced and hashes with it.
    """
    return {
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "location_nm": (
            None if diagnostic.location_nm is None else list(diagnostic.location_nm)
        ),
        "data": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in diagnostic.data
        },
    }


def _stage_run(run: StageRun) -> dict[str, Any]:
    """One stage's record. Parameter values pass through untouched.

    A diameter table stays a list of numbers: flattening it to a string would
    make every consumer parse the provenance back out again, which is the same
    re-derivation this document exists to stop. It becomes a ``list`` here, as
    ``layers_found`` and ``location_nm`` do, so that the mapping ``document()``
    hands a caller is the same shape as the one that comes back from
    :func:`json.loads` rather than one holding tuples that only compare equal
    after a round trip through the text.
    """
    return {
        "name": run.name,
        "parameters": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in run.parameters
        },
    }


def _enclosure(match: EnclosureMatch | None) -> dict[str, Any] | None:
    """Which catalogue enclosure the panel was identified as, ``null`` if none.

    ``null`` rather than an absent key, and never an object naming nothing: "no
    footprint matched" is an answer a consumer reads, and a match with an empty
    ``candidates`` would be a second spelling of it that some reader eventually
    treats as a match.

    Every field is passed through as the matcher left it. ``candidates`` keeps
    its order — sorting here would be an emitter re-deciding a pipeline fact,
    and the drawing and this document would then print two orders of one list.
    ``length_nm``/``width_nm`` are whole nanometres like every other nominal
    length in the document, and specifically not millimetres: Hammond publish a
    1590B as 112.40 mm, so there is no whole-millimetre integer to emit and the
    only alternative would be the float this project refuses to hold anywhere
    else. They also stay in the catalogue's orientation when ``rotated`` is set
    — transposing them would make the footprint unfindable in the drawing it
    came from.

    ``selected_part`` is ``None`` unless the operator declared a case. Nothing
    here may fill it in from ``candidates``: a 2-D outline identifies a
    footprint and never a part, so a plausible-looking guess would put a part
    number the artwork cannot support onto a machinist's sheet.
    """
    if match is None:
        return None
    return {
        "family": match.family,
        "length_nm": match.length_nm,
        "width_nm": match.width_nm,
        "candidates": list(match.candidates),
        "rotated": match.rotated,
        "selected_part": match.selected_part,
    }
