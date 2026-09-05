# ADR-0002: Domain answer sets and validation policy

**Status:** Accepted

## Context

Measured artwork is not by itself a safe nominal specification. Hole positions must
respect the operator's grid, hole diameters must name available drill bits, and an
outline must name a catalogue footprint. These quantities have different answer sets
and different failure consequences.

Enclosure geometry also has an inherent limit: a two-dimensional outline can identify a
footprint shared by several parts, but it cannot establish a unique three-dimensional
part. The enclosure catalogue and its declaration policy must preserve that distinction
without guessing.

## Decision

Each measured quantity is resolved against its own domain answer set:

| Quantity | Authoritative answer set | Required result |
|---|---|---|
| Hole position | Multiples of the declared grid | Every accepted position lands on that grid. |
| Hole diameter | The selected drill standard, optionally narrowed by the operator | Accept a member of the selected standard. An unmatched diameter is an error and its hole is excluded; larger accepted adjustments are warnings, as described below. |
| `Background` outline | Catalogue footprints distributed in `docs/parts/dimensions.tsv` | Matching follows the enclosure outcomes below. |

Any error withholds every requested artefact. Excluding a hole whose diameter is
unmatched therefore cannot silently produce an otherwise valid-looking partial artefact.

### Diameter acceptance and reporting

The acceptance tolerance determines whether a stocked bit is close enough to the drawn
diameter. A separate, tighter threshold determines whether to report the adjustment.
An accepted size can still differ enough from the artwork to matter when drilling
aluminium.

The reporting threshold is one quarter of the effective drill table's local pitch at
the selected size: the gap to its nearer neighbour in the operator's possibly narrowed
selection. It follows the table because the metric series changes pitch at two points,
from 0.05 mm at the fine end to 0.5 mm at the coarse end. A selection containing only
one size has no neighbour, so every non-zero adjustment is reported.

An adjustment past this threshold produces a WARNING with its signed movement,
following `Hole.residual_nm`: positive means the bit is larger than the drawn diameter;
negative means it is smaller. The accepted hole is still drilled.

This reporting policy applies only to diameters. The enclosure quantiser snaps an outline
to a footprint without reporting its movement, within a tolerance an order of magnitude
wider than diameter reporting thresholds. No other quantiser in this pipeline reports a
measurement's departure.

### Enclosure identification

Undeclared enclosure matching distinguishes three outcomes, while a declaration changes
the question from identification to positive verification:

| Declaration | Geometric outcome | Policy |
|---|---|---|
| None | Unique footprint | Accept the footprint without inferring a unique part. |
| None | Unknown footprint | Retain the outline, report a warning, and leave the enclosure unidentified. |
| None | Ambiguous footprints | Report an error; do not choose a footprint. |
| Declared case | The declared part's footprint is positively verified | Accept the footprint and record the declared part as selected. |
| Declared case | Any other outcome | Report an error. |

Catalogue dimensions follow the order in Hammond's drawing. The published length is
not necessarily the larger dimension: `1590LB` lists the smaller one first. A comparison
with a supplied model must put both pairs in the same order. The cross-check in
[ADR-0007](0007-case-model-and-clearance.md) sorts both pairs in descending order because
the measured pair has already lost its orientation at that point.

Frame comparisons also need an explicit convention. The panel's canonical axes and the
supplied model's independently chosen axes can register the same drilled face differently.
Sorting a span pair discards axis identity, so the footprint check cannot detect a pure
axis swap, such as a panel drawn a quarter turn from the model's orientation.
[ADR-0007](0007-case-model-and-clearance.md)'s axis-correspondence convention handles that
case.

The `Background` outline is drawn to enclosure backplate dimensions. A face-drawn 1590B
is approximately 1.9 mm from both its own backplate and the nearby 1590BS footprint.
Below that tolerance neither footprint is accepted; at that tolerance both are accepted.
Widening the tolerance therefore cannot identify the enclosure uniquely.

Whenever an outline exists, `hole-outside-outline` warns if any part of a hole extends
beyond it, including a hole whose centre is inside but whose edge crosses the boundary.
Face containment checks the actual drilled face and reports an error. It requires a
supplied model; see
[ADR-0007](0007-case-model-and-clearance.md).

`docs/parts/dimensions.tsv` is the distributed catalogue authority. Hammond's website is
the upstream source from which maintainers obtain published dimensions. Manufacturer
PDFs are neither repository data nor a build-time or run-time dependency.

## Rationale

A grid, a drill standard, and a catalogue answer different physical questions. Keeping
their answer sets separate prevents a mathematically plausible value from becoming a
position, bit, or enclosure that the relevant domain does not recognise.

Artefact withholding makes errors fail safely. A rejected diameter removes only the
unsafe hole from the canonical result, while the invocation-level policy prevents that
partial result from being mistaken for a complete fabrication artefact.

The enclosure outcomes reflect what the evidence can support. An undeclared outline may
be uniquely known, outside the catalogue, or consistent with several footprints. A
declaration is useful only when it is verified on every path. Treating a footprint as a
unique part, or widening the tolerance past genuine neighbours, would replace evidence
with a guess.

Outline containment can only justify a warning. The outline represents the backplate,
and the die-cast face is smaller. A hole inside the outline may still miss the face;
a hole slightly outside it may still be drillable. An error could stop a legitimate
panel, while silence would leave a possible edge breakout unreported.

Keeping the distributed authority in a compact text table makes catalogue construction
reproducible without distributing manufacturer documents. The upstream website supplies
the published facts; the repository consumes the reviewed table.

## Consequences

Operators must declare the grid and drill standard that govern the panel, and may narrow
the available drill sizes. A diameter outside that selection is never passed through as
a nominal size.

Library callers can override the diameter reporting threshold with
`SnapDiametersToDrillTable(warn_over_nm=…)`. As with `SnapPositions.warn_over_nm`, an
unset value means “derive the threshold”. There is no corresponding CLI flag.

The reported defect concerned missing adjustment warnings; it did not establish a need
to tune the derived default from the command line. This follows the drawing emitters'
`DrawingOptions(scale=…)`, which is available to library callers without a `--scale`
flag. Add a CLI flag when an operator needs it, rather than exposing every constructor
parameter automatically.

Operators drawing a catalogue enclosure must use its backplate outline. Uncatalogued
enclosures remain usable when undeclared, but ambiguous outlines require a declaration,
and every declared case requires positive geometric verification.

Catalogue maintenance updates `docs/parts/dimensions.tsv` from Hammond's website and
regenerates downstream catalogue data. No repository workflow may require a manufacturer
PDF.

A panel whose holes reach past its own outline still produces every requested
artefact and exits 1. An operator who wants that refused rather than reported
supplies a case model, whose face check is an error.

Containment is checked against the identified footprint, so it inherits the enclosure
quantiser's inclusive 1.5 mm per-axis tolerance: a hole within half that distance of
the drawn edge may be reported or not, depending on which catalogue footprint the
outline snapped to. Checking the measured outline instead would report against a
boundary no artefact states.
