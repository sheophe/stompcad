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

The `Background` outline is drawn to enclosure backplate dimensions. A face-drawn 1590B
is approximately 1.9 mm from both its own backplate and the nearby 1590BS footprint.
Below that tolerance neither footprint is accepted; at that tolerance both are accepted.
Widening the tolerance therefore cannot identify the enclosure uniquely.

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
