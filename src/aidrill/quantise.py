"""Quantise raw millimetres into canonical nanometres.

Enclosure identification may abort; accepted holes then take drill-table
diameters before grid positions. Source identities remain unchanged.
"""

from __future__ import annotations

from .model import Diagnostic, DrillData, Hole, RawDrillData, Severity, StageRun
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
    for measurement in raw.holes:
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
                # Preserve the source identity even when earlier holes were dropped.
                raw=measurement,
                index=measurement.index,
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
