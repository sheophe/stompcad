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
| Hole diameter | The selected drill standard, optionally narrowed by the operator | Every accepted diameter is a member; an unmatched diameter is an error and its hole is excluded. |
| `Background` outline | Catalogue footprints distributed in `docs/parts/dimensions.tsv` | Matching follows the enclosure outcomes below. |

Any error withholds every requested artifact. Excluding a hole whose diameter is
unmatched therefore cannot silently produce an otherwise valid-looking partial artifact.

Undeclared enclosure matching distinguishes three outcomes, while a declaration changes
the question from identification to positive verification:

| Declaration | Geometric outcome | Policy |
|---|---|---|
| None | Unique footprint | Accept the footprint without inferring a unique part. |
| None | Unknown footprint | Retain the outline, report a warning, and leave the enclosure unidentified. |
| None | Ambiguous footprints | Report an error; do not choose a footprint. |
| Declared case | The declared part's footprint is positively verified | Accept the footprint and record the declared part as selected. |
| Declared case | Any other outcome | Report an error. |

A catalogue footprint and a measured span pair are two orderings of the same pair, not a
length and a width in the everyday sense. `docs/parts/dimensions.tsv` publishes each row
in whatever order Hammond's own drawing states, and nothing asserts that the published
length is always the larger figure — `1590LB` publishes it smaller. A rule that compares
a supplied model's measured footprint against an identified catalogue footprint must
state which convention it holds both sides to; the cross-check in
[ADR-0007](0007-case-model-and-clearance.md) reduces both pairs to the same descending
order before comparing, because a measured pair's own orientation is already gone by the
time it reaches that check.

The same rule extends from footprint pairs to frames: two registrations of one drilled
face — the panel's own canonical axes and the supplied model's independently-chosen
ones — are two orderings of the same thing, not already the same thing, and must be
named before they are compared. The descending-sort cross-check above is blind to a
pure axis swap **by construction** — reducing a pair to a sorted order is exactly what
discards which axis is which — so it is not, and never was, the place that catches a
panel drawn a quarter turn from the model's own orientation. [ADR-0007](0007-case-model-and-clearance.md)'s
axis-correspondence convention is the rule that does.

The `Background` outline is drawn to enclosure backplate dimensions. A face-drawn 1590B
is approximately 1.9 mm from both its own backplate and the nearby 1590BS footprint.
Below that tolerance neither footprint is accepted; at that tolerance both are accepted.
Widening the tolerance therefore cannot identify the enclosure uniquely.

A hole whose **extent** leaves that outline is a warning, `hole-outside-outline`,
checked whenever an outline exists. The extent and not the centre, so a hole
that straddles the boundary is caught. Face containment is the stronger check,
against the real drilled face rather than the published top view; it needs a
supplied model and it is an error. See
[ADR-0007](0007-case-model-and-clearance.md).

`docs/parts/dimensions.tsv` is the distributed catalogue authority. Hammond's website is
the upstream source from which maintainers obtain published dimensions. Manufacturer
PDFs are neither repository data nor a build-time or run-time dependency.

## Rationale

A grid, a drill standard, and a catalogue answer different physical questions. Keeping
their answer sets separate prevents a mathematically plausible value from becoming a
position, bit, or enclosure that the relevant domain does not recognise.

Artifact withholding makes errors fail safely. A rejected diameter removes only the
unsafe hole from the canonical result, while the invocation-level policy prevents that
partial result from being mistaken for a complete fabrication artifact.

The enclosure outcomes reflect what the evidence can support. An undeclared outline may
be uniquely known, outside the catalogue, or consistent with several footprints. A
declaration is useful only when it is verified on every path. Treating a footprint as a
unique part, or widening the tolerance past genuine neighbours, would replace evidence
with a guess.

Containment warns because its evidence is weak in a known direction. The outline
is the backplate footprint and a die-cast face is smaller than it, so a hole
inside the outline may still miss the face and a hole a fraction outside it may
still be drillable. Withholding every artifact on that evidence would stop a
legitimate panel; saying nothing would let an edge breakout through unremarked.
A warning reports what was observed without claiming more than the outline can
support.

Keeping the distributed authority in a compact text table makes catalogue construction
reproducible without distributing manufacturer documents. The upstream website supplies
the published facts; the repository consumes the reviewed table.

## Consequences

Operators must declare the grid and drill standard that govern the panel, and may narrow
the available drill sizes. A diameter outside that selection is never passed through as
a nominal size.

Operators drawing a catalogue enclosure must use its backplate outline. Uncatalogued
enclosures remain usable when undeclared, but ambiguous outlines require a declaration,
and every declared case requires positive geometric verification.

Catalogue maintenance updates `docs/parts/dimensions.tsv` from Hammond's website and
regenerates downstream catalogue data. No repository workflow may require a manufacturer
PDF.

A panel whose holes reach past its own outline still produces every requested
artifact and exits 1. An operator who wants that refused rather than reported
supplies a case model, whose face check is an error.

Containment is checked against the identified footprint, so it inherits the enclosure
quantiser's inclusive 1.5 mm per-axis tolerance: a hole within half that distance of
the drawn edge may be reported or not, depending on which catalogue footprint the
outline snapped to. Checking the measured outline instead would report against a
boundary no artifact states.
