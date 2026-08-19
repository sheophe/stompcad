# ADR-0009: A shared model package and the workspace's dependency order

**Status:** Accepted

Amends [ADR-0008](0008-workspace-and-shared-geometry-core.md), which decided four
packages. There are five.

## Context

ADR-0008 split the workspace before either new tool was designed, so it could only
name the sharing that was already certain: lengths, a rigid transform, and the
geometry `aigeom` would hold. Designing `aicollider` supplied the rest, and three
of its findings do not fit that shape.

**The interchange value is a whole model, not a new type.** `aicollider` needs the
hole pattern `aidrill` produces. The obvious move — give `aicollider` its own
`HolePattern` and have `aicad` adapt — creates a second serialised form of the same
facts, kept in step by prose. `aidrill` already emits `DrillData` as versioned JSON,
and that document carries the frame, the tool table, the enclosure identity and the
hole numbering the report wants to cite.

**Two packages need one diagnostic vocabulary.** `aicad` reduces findings from both
tools to one report and one exit code. Two independently defined `Severity` enums
and two exit-code tables would be two chances to disagree about what a warning is.

**`aigeom` takes the kernel unconditionally.** That was the right call — a
kernel-free configuration is one nobody runs — but it means anything depending on
`aigeom` pulls in OpenCASCADE. A package whose contents are frozen dataclasses
should not.

## Decision

Five packages, in a linear acyclic order (Figure 1).

```
aimodel ──► aigeom ──┬──► aidrill ────┐
                     └──► aicollider ─┴──► aicad
```

*Figure 1: the workspace's dependency order. Each package installs and passes its
own tests alone, as ADR-0008 requires.*

### `aimodel`

Pure Python. No kernel, no parser, no I/O beyond serialisation. It holds:

- `Nanometre`, `Millimetre`, and their conversions (ADR-0004's newtypes).
- `DrillData` and its members: `Hole`, `RawHole`, `ReferenceOutline`, `RawOutline`,
  `EnclosureMatch`, `SourceInfo`, `Origin`.
- The `DrillData` JSON codec, **both directions**.
- `Diagnostic`, `Severity`, and the severity-to-exit-code reduction.
- `Stage[T]`, `Pipeline[T]`, `Emitter[T]`, `Payload`, `StageRun`.

Two admission rules, and nothing else gets in:

1. **Interchange** — one package produces the value and another consumes it, and
   neither is its home.
2. **Contract** — a protocol or vocabulary both tools must implement identically
   for `aicad` to treat them uniformly.

A type a package owns and merely exposes to a library consumer **stays home**.
`aicad` reading `aicollider`'s `DockReport` is ordinary library consumption, not
interchange, so that type does not move.

### `aigeom`

The kernel layer: the STEP reader, the deterministic STEP writer with its OCC
normalisation, `CoordinateFrame` and `FaceFrame`, `levels()` for grouping coplanar
faces and measuring holedness, bounding boxes, `KernelUnavailable`.

No enclosure vocabulary crosses this boundary. `select_solid`'s box/lid keywords,
`CaseModel`, `Rejection` and the play-area reasoning in `region.py` stay in
`aidrill`.

### The drill document gains the face frame

When a case model was supplied, `aidrill` publishes the `FaceFrame` it cut in as a
member of the drill document. `aicollider` reads that registration rather than
recovering it.

### What leaves `aidrill`

`model.py` is deleted. `RawDrillData` — pre-canonical, touched only by the source
and the quantiser — moves to `quantise.py`. `Micron` stays: its definition is a
statement about `aidrill`'s grid policy, not about length. `JsonEmitter` remains a
registered emitter but becomes a wrapper over `aimodel`'s codec, owning only
`indent`.

## Rationale

**Why `DrillData` whole, rather than a narrower `HolePattern`.** A narrower type
would have to carry the frame, the tool table, the hole numbering and the enclosure
identity anyway — that is most of the document — and the remainder is provenance a
consumer can ignore for free. What it would add is a second schema, a second codec
and a second version number, all describing holes that were already described. The
cost of the wide type is that `aicollider` imports fields it never reads. The cost
of the narrow one is two documents that must not drift. The second is worse, and it
is worse in the way this workspace cares about: `aidrill`'s artefacts agree because
they are computed from one value, and an adapter between two hole representations
is exactly where that guarantee would end.

**Why the codec moves with the type.** A type in `aimodel` whose only serialiser
lives in `aidrill` forces `aicollider` either to import `aidrill` or to write a
second reader — the duplication `aimodel` exists to prevent, reintroduced through
the back door. Moving it also supplies the reader the emitter never had, and makes
"one document, and back again" a round-trip property test rather than a claim.

**Why `aimodel` is not part of `aigeom`.** They answer to different constraints.
`aigeom` exists because geometry is expensive to get right twice; `aimodel` exists
because a shared value must have one definition. Merging them would make the
lightest package in the workspace depend on the heaviest, and would put the
admission rules above in competition with ADR-0008's "can it be described without
naming a panel?" — two tests for one package, which is how a dumping ground starts.

**Why lengths sit in `aimodel` rather than `aigeom`.** ADR-0008 listed lengths
among the geometry, which was reasonable when `aigeom` was the only shared package.
A length is a unit, not an operation, and it is the most widely shared definition
here. Putting it in the leaf keeps the graph linear and lets a consumer take
`Nanometre` without taking a CAD kernel.

**Why the two admission rules stop where they do.** Rule 2 is the dangerous one: it
would justify moving anything two packages happen to resemble each other in. It is
bounded by its own wording — the uniformity must be something `aicad` depends on.
`Pipeline` qualifies because `aicad` reads both tools' `StageRun` provenance and
reduces both tools' diagnostics; `Source` does not, because `RawDrillData` is
artwork and `aicollider`'s board reader returns something else entirely.

**Why the face frame is published rather than re-derived.** It is the same argument
the hole positions make. Those holes were cut *from* exact values, so reading them
back out of geometry could only lose precision or fail; the frame they were cut in
is equally known and equally lossy to recover. Re-deriving it would also drag
enclosure policy — which solid is the box, which coplanar level is the drilled face
— across a boundary that otherwise carries none, and would let two tools disagree
about where a panel is while both being self-consistent.

## Consequences

ADR-0004's newtypes are `aimodel`'s. ADR-0001's pipeline and emitter protocols
become generic in the value they fold over, and both tools instantiate them.
ADR-0007's optional `aidrill[step]` extra is retired: `aigeom` takes the kernel
unconditionally, so `aidrill` does too, and ADR-0007's argument for the extra
assumed `aidrill` stood alone.

`aidrill`'s public import paths change. Nothing is re-exported for compatibility —
one name, one home — and the workspace is pre-release with one consumer.

The migration's test is byte identity: every artefact `aidrill` emits must be
unchanged across the move, and its suite is the instrument — with one intended
exception. The drill document gains the face frame, so it goes to version 6. A
version exists to signal a change of shape, and a reader that validates against
v5 should be told rather than handed an unexpected member.

The risk is that `aimodel` accumulates types on rule 2's authority. The check is
that a type admitted under rule 2 must name the `aicad` behaviour that depends on
the uniformity; a type that cannot name one is being moved for tidiness.
