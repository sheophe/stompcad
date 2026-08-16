"""The quantisation phase: measurements in, values the domain already holds out.

A source answers in float millimetres — what the artwork measured, nothing
rounded. Everything after this function works in whole nanometres, and every one
of those nanometres is a number the domain publishes: a catalogue footprint, a
row of a drill table, a multiple of the declared grid. This is the one place the
crossing happens.

**A function, and not three ``Stage``s.** ``Stage.apply`` is ``DrillData →
DrillData``, and the states in between here have no type worth naming: a document
whose outline is quantised but whose holes are still measurements, and one whose
diameters are exact but whose positions are not. Spelling those would cost two
single-use intermediate types, or a ``RawHole | Hole`` union that dedupe, sort
and three emitters would each have to narrow on a branch no run can reach. Two
things follow from being a function, and both are the point rather than a
consolation:

* **The order is internal and cannot be got wrong from outside.** "No stage may
  assert which stage ran before it" is an LSP rule these three could only ever
  have obeyed by luck, because their answers genuinely depend on each other's.
  Here enclosure → diameters → grid is one function's business, and a caller has
  no way to compose it differently.
* **Aborting is expressible.** A stage handed data it must not process has no
  way to say so and can only pass it on; a function returns early.

The order, and the only reasons for it:

1. **The enclosure first, because it can abort.** A contradicted ``--case`` is an
   ERROR (``unverifiable-enclosure``, ``unmatched-enclosure``,
   ``wrong-enclosure``), a run with any ERROR writes no artifacts at all, and so
   every hole quantised after one is work for a file nobody receives. It is *not*
   that identification settles the frame's origin: the source already centred
   every measurement on the outline it measured, and resizing a rectangle about
   its centre moves no origin.
2. **Diameters second**, because ``unknown-diameter`` is an ERROR that *drops*
   the hole, so asking it first spares the grid a hole that reaches no artifact.
3. **The grid last.** It needs nothing from either of the others.

**Identity is preserved by construction and asserted anyway.** Each finished
``Hole`` carries the ``RawHole`` it came from and that measurement's own
``index``; ``Hole.__post_init__`` refuses a hole whose two identities differ. The
guard is the only thing standing between a quantiser that reorders or renumbers
and a diagnostic that names a different hole than the drawing's balloon does, so
the tests number their fixtures out of order (4, 1, 9) rather than trusting a
list position to stand in for an identity.
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
    """Run the three quantisers over one read, in the one order that works.

    The three are keyword-only because they are not interchangeable and reading
    ``quantise(raw, a, b, c)`` would tell nobody which is which — the order they
    run in is this function's decision and not the call site's.

    ``raw.diagnostics`` is carried through ahead of everything this phase finds:
    the source's own findings — a missing reference layer, a layer that held no
    circles — are about the read and precede any conclusion drawn from it.
    """
    findings: list[Diagnostic] = list(raw.diagnostics)
    runs: list[StageRun] = []

    reference, match, identified = enclosure.quantise(raw.reference, raw.centre)
    findings.extend(identified)
    runs.append(enclosure.describe())

    if any(finding.severity is Severity.ERROR for finding in identified):
        # Nothing below runs, and nothing below is recorded as having run: a
        # record says what a quantiser *did*, so a phase that stopped here must
        # not leave a claim that the drill table and the grid were applied. The
        # holes go with them — the run writes no artifacts, and a document
        # listing quantised holes for a panel we have refused to identify is a
        # description of a panel nobody can drill.
        return DrillData(
            holes=(),
            reference=reference,
            diagnostics=tuple(findings),
            source=raw.source,
            processing=tuple(runs),
            enclosure=match,
        )

    # The first of two once-per-run findings, and the one that is known before
    # any hole is. ``SnapPositions`` raises it in its constructor when the
    # requested pitch was too fine to render and had to be clamped, because no
    # per-hole signature can carry it: returned from ``quantise(hole)`` it would
    # repeat for every circle on the panel and vanish entirely on a panel with
    # no circles — the run where the operator most needs telling that their grid
    # is not the one they typed.
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
                # The measurement, and its own number. Enumerating the holes
                # being built instead would renumber every hole the drill table
                # dropped, and the two consumers read different halves: a
                # refusal names the measurement it was handed, while the drill
                # file and the drawing's balloons iterate what survived.
                raw=measurement,
                index=measurement.index,
            )
        )

    # The second, and the reason it is collected here rather than beside the
    # first: "half the holes tied" is not a fact about any hole, so it can only
    # be asked once every hole has one. The rule still belongs to the quantiser
    # that owns the pitch, which is why it is a second method on
    # ``SnapPositions`` rather than four lines here: this phase composes, and
    # holds no domain knowledge of its own.
    findings.extend(positions.review_panel(holes))

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
