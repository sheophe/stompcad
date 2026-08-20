"""Quantise raw millimetres into canonical nanometres.

Enclosure identification may abort; accepted holes then take drill-table
diameters before grid positions. Holes leave this stage unnumbered.
"""

from __future__ import annotations

from stompmodel.diagnostics import Diagnostic, Severity

from .model import DrillData, Hole, RawDrillData, StageRun
from .pipeline import IdentifyHammondFootprint, SnapDiametersToDrillTable, SnapPositions

__all__ = ["quantise"]


def quantise(
    raw: RawDrillData,
    *,
    enclosure: IdentifyHammondFootprint,
    diameters: SnapDiametersToDrillTable,
    positions: SnapPositions,
) -> DrillData:
    """Apply enclosure, diameter, and position quantisers in that order.

    Source diagnostics precede quantisation findings. An enclosure error stops
    the phase before holes, diameter records, or position records are produced.
    """
    findings: list[Diagnostic] = list(raw.diagnostics)
    runs: list[StageRun] = []
    # ADR-0006: geometry alone determines output. Sorting here, before any
    # hole is quantised, is what stops artwork traversal order from reaching
    # per-hole diagnostics, the survivor Deduplicate keeps, and the ties
    # ReviewGridTies reports — three leaks, one source, fixed once.
    measurements = sorted(raw.holes, key=lambda hole: (hole.x, hole.y, hole.diameter))

    reference, match, identified = enclosure.quantise(raw.reference, raw.centre)
    findings.extend(identified)
    runs.append(enclosure.describe())

    if any(finding.severity is Severity.ERROR for finding in identified):
        # Record only quantisers that ran; an unidentified panel has no holes.
        return DrillData(
            holes=(),
            reference=reference,
            diagnostics=tuple(findings),
            source=raw.source,
            processing=tuple(runs),
            enclosure=match,
        )

    # Position configuration diagnostics apply once to the panel, not per hole.
    findings.extend(positions.diagnostics)

    holes: list[Hole] = []
    for measurement in measurements:
        diameter_nm, refused = diameters.quantise(measurement)
        findings.extend(refused)
        if diameter_nm is None:
            continue
        (x_nm, y_nm), moved = positions.quantise(measurement)
        findings.extend(moved)
        holes.append(
            Hole(
                x_nm=x_nm,
                y_nm=y_nm,
                diameter_nm=diameter_nm,
                raw=measurement,
            )
        )

    runs.append(diameters.describe())
    runs.append(positions.describe())
    return DrillData(
        holes=tuple(holes),
        reference=reference,
        diagnostics=tuple(findings),
        source=raw.source,
        processing=tuple(runs),
        enclosure=match,
    )
