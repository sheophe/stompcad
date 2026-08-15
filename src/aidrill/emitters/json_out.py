"""JSON emitter (SPEC §7) — the integration surface for the wider toolchain.

Everything in ``DrillData`` comes out: nominal positions *and* the raw measured
values behind them, the reference outline, the tool table, every diagnostic, and
where the data came from. A consumer can rebuild an identical ``DrillData`` from
this document, which is what ``test_json_emitter.py`` asserts.

Document shape (version 3)::

    {
      "format": "aidrill-drill-data",
      "version": 3,
      "units": "mm",                     # always; canonical frame, never inches
      "origin": "centre",                # centre of the reference outline, Y up
      "source":     {"path", "drill_layer", "reference_layer",
                     "layers_found", "producer"},
      "reference":  {"width", "height", "centre_x", "centre_y",
                     "raw": {"width", "height"}} | null,
      "tools":     [{"number", "diameter", "count"}, …],   # ascending diameter
      "holes":     [{"x", "y", "diameter", "tool",
                     "raw": {"x", "y", "diameter"},
                     "index"}, …],                         # pipeline order
      "diagnostics": [{"severity", "code", "message", "location", "data"}, …],
      "processing":  [{"name", "parameters": {…}}, …]       # in the order run
    }

Version 2 added three things, each of them something a consumer would otherwise
have to reconstruct from geometry — which is the founding bug of this project,
displaced one layer out into the toolchain:

``index`` is the hole's stable identity, not its position in the array. It is
what a diagnostic's ``hole_index`` joins to, and the two stop agreeing the
moment a stage sorts or drops holes, so a consumer must never substitute one
for the other.

``data`` is the diagnostic's machine-readable payload, always present, ``{}``
when the diagnostic had none. Without it, a consumer asked which holes were
duplicates had only their positions to go on and had to re-implement
``Deduplicate``'s rule to find out — a second, divergent copy of the rule, which
is exactly the mistake the drawing emitter made inside this codebase.

``processing`` is what the pipeline actually did, in order, with *effective*
parameter values. A consumer that has to be told the grid out of band can be
told the wrong one; a document that states it cannot disagree with itself.

Version 3 added ``reference.raw``, the outline as measured off the artwork. A
hole's ``raw`` had been serialised since version 1 while the outline's was not,
and once a stage snaps the outline to a catalogue enclosure — the fixture panel
measures 113.000 × 60.000 mm where the datasheet says 112 × 61 — that omission
sent a *nominal* size out as though it were what the artwork said. Nothing
downstream could then recover the measurement, which is the same class of
defect as re-deriving a pipeline fact, only worse: the fact is gone, not merely
recomputed. The round-trip test did not notice for the classic reason — its
fixture outline was unsnapped, so ``raw`` and nominal coincided and a dropped
key rebuilt itself.

Key order is fixed and part of the contract, so diffing two runs shows real
changes rather than dictionary reshuffling. New keys are appended — at the top
level, within a hole, within a diagnostic — so a v1 reader indexing by position
sees the shape it knows before the additions. ``location`` is ``[x, y]`` in
canonical millimetres or ``null``.

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

from ..model import Diagnostic, DrillData, Hole, ReferenceOutline, SourceInfo, StageRun
from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter", "FORMAT", "VERSION"]

FORMAT = "aidrill-drill-data"
VERSION = 3


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
            "units": "mm",
            "origin": "centre",
            "source": _source(data.source),
            "reference": _reference(data.reference),
            "tools": [
                {"number": number, "diameter": diameter, "count": counts[diameter]}
                for diameter, number in tools.items()
            ],
            "holes": [_hole(h, tools[h.diameter]) for h in data.holes],
            "diagnostics": [_diagnostic(d) for d in data.diagnostics],
            "processing": [_stage_run(r) for r in data.processing],
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

    ``raw`` is emitted for the same reason a hole's is: once a stage snaps the
    outline to a catalogue enclosure, the nominal width is no longer what the
    artwork said, and a consumer cannot recover the difference from a document
    that only carries the snapped value. Appended after ``centre_y`` so a reader
    of the older shape sees the keys it knows in the order it knew them.
    """
    if reference is None:
        return None
    return {
        "width": reference.width,
        "height": reference.height,
        "centre_x": reference.centre_x,
        "centre_y": reference.centre_y,
        "raw": {"width": reference.raw.width, "height": reference.raw.height},
    }


def _hole(hole: Hole, tool: int) -> dict[str, Any]:
    """One hole, identity included.

    ``index`` is emitted as the model holds it, never as the loop counter that
    happens to agree with it in unsorted data: after ``SortHoles`` or
    ``Deduplicate`` the two differ, and a consumer joining a diagnostic's
    ``hole_index`` against the array position would then point at the wrong
    hole while looking entirely plausible.
    """
    return {
        "x": hole.x,
        "y": hole.y,
        "diameter": hole.diameter,
        "tool": tool,
        "raw": {"x": hole.raw.x, "y": hole.raw.y, "diameter": hole.raw.diameter},
        "index": hole.index,
    }


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    """One finding, payload included.

    ``data`` is an object rather than the model's pair list because that is what
    a consumer indexes by key, and it is always present — ``{}`` for a finding
    that carried none — so nobody has to branch on its absence.
    """
    return {
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "location": None if diagnostic.location is None else list(diagnostic.location),
        "data": dict(diagnostic.data),
    }


def _stage_run(run: StageRun) -> dict[str, Any]:
    """One stage's record. Parameter values pass through untouched.

    A diameter table stays a list of numbers: flattening it to a string would
    make every consumer parse the provenance back out again, which is the same
    re-derivation this document exists to stop. It becomes a ``list`` here, as
    ``layers_found`` and ``location`` do, so that the mapping ``document()``
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
