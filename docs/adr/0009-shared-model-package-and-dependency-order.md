# ADR-0009: A shared model package and the workspace's dependency order

**Status:** Accepted

Amends [ADR-0008](0008-workspace-and-shared-geometry-core.md), which decided four
packages. There are five.

## Context

ADR-0008 split the workspace before either new tool was designed, so it could only
name the sharing that was already certain: lengths, a rigid transform, and the
geometry `stompgeom` would hold. Designing `stompcollider` supplied the rest, and three
of its findings do not fit that shape.

**The interchange value is a whole model, not a new type.** `stompcollider` needs the
hole pattern `stompdrill` produces. The obvious move — give `stompcollider` its own
`HolePattern` and have `stompcad` adapt — creates a second serialised form of the same
facts, kept in step by prose. `stompdrill` already emits `DrillData` as versioned JSON,
and that document carries the frame, the tool table, the enclosure identity and the
hole numbering the report wants to cite.

**Two packages need one diagnostic vocabulary.** `stompcad` reduces findings from both
tools to one report and one exit code. Two independently defined `Severity` enums
and two exit-code tables would be two chances to disagree about what a warning is.

**`stompgeom` takes the kernel unconditionally.** That was the right call — a
kernel-free configuration is one nobody runs — but it means anything depending on
`stompgeom` pulls in OpenCASCADE. A package whose contents are frozen dataclasses
should not.

## Decision

Five packages, in a linear acyclic order (Figure 1).

```
stompmodel ──► stompgeom ──┬──► stompdrill ────┐
                     └──► stompcollider ─┴──► stompcad
```

*Figure 1: the workspace's dependency order. Each package installs and passes its
own tests alone, as ADR-0008 requires.*

### `stompmodel`

Pure Python. No kernel, no parser, no I/O beyond serialisation. It holds:

- `Nanometre`, `Millimetre`, and their conversions (ADR-0004's newtypes).
- `DrillData` and its members: `Hole`, `RawHole`, `ReferenceOutline`, `RawOutline`,
  `EnclosureMatch`, `SourceInfo`, `Origin`.
- The `DrillData` JSON codec, **both directions**.
- `Diagnostic`, `Severity`, `ParameterValue`, and the severity-to-exit-code
  reduction.
- `Processable`, `Stage[T]`, `Pipeline[T]`, `Emitter[T]`, `Payload`, `StageRun`.
- The workspace's error base: `StompError`, with `EmitterError` and
  `DocumentError` beneath it. Each tool's own base descends from it —
  `StompdrillError` does — so a package's errors stay identifiable while every
  one of them is catchable at once.

Two admission rules, and nothing else gets in:

1. **Interchange** — one package produces the value and another consumes it, and
   neither is its home.
2. **Contract** — a protocol or vocabulary both tools must implement identically
   for `stompcad` to treat them uniformly.

A type a package owns and merely exposes to a library consumer **stays home**.
`stompcad` reading `stompcollider`'s `DockReport` is ordinary library consumption, not
interchange, so that type does not move.

### `stompgeom`

The kernel layer: the STEP reader, the deterministic STEP writer with its OCC
normalisation, `CoordinateFrame` and `FaceFrame`, `levels()` for grouping coplanar
faces and measuring holedness, bounding boxes, `KernelUnavailable`.

`levels()` arrives last, once `stompcollider`'s carrier-plane code exists to
shape its interface. It belongs here; it is not part of the upfront extraction.
The technical specification's order of work says why.

No enclosure vocabulary crosses this boundary. `select_solid`'s box/lid keywords,
`CaseModel`, `Rejection` and the play-area reasoning in `region.py` stay in
`stompdrill`.

### The drill document gains the face frame

When a case model was supplied, `stompdrill` publishes the `FaceFrame` it cut in as a
member of the drill document. `stompcollider` reads that registration rather than
recovering it.

### What leaves `stompdrill`

`model.py` is deleted. `RawDrillData` — pre-canonical, touched only by the source
and the quantiser — moves to `quantise.py`. `Micron` stays: its definition is a
statement about `stompdrill`'s grid policy, not about length. `JsonEmitter` remains a
registered emitter but becomes a wrapper over `stompmodel`'s codec, owning only
`indent`. `SourceInfo.producer` stops defaulting to `"stompdrill"`: a default tool
name in a shared model would let a `stompcollider` document that never set the
field claim provenance from a tool that never touched it, so naming the producer
becomes the job of whoever read the artwork.

## Rationale

**Why `DrillData` whole, rather than a narrower `HolePattern`.** A narrower type
would have to carry the frame, the tool table, the hole numbering and the enclosure
identity anyway — that is most of the document — and the remainder is provenance a
consumer can ignore for free. What it would add is a second schema, a second codec
and a second version number, all describing holes that were already described. The
cost of the wide type is that `stompcollider` imports fields it never reads. The cost
of the narrow one is two documents that must not drift. The second is worse, and it
is worse in the way this workspace cares about: `stompdrill`'s artefacts agree because
they are computed from one value, and an adapter between two hole representations
is exactly where that guarantee would end.

**Why the codec moves with the type.** A type in `stompmodel` whose only serialiser
lives in `stompdrill` forces `stompcollider` either to import `stompdrill` or to write a
second reader — the duplication `stompmodel` exists to prevent, reintroduced through
the back door. Moving it also supplies the reader the emitter never had, and makes
"one document, and back again" a round-trip property test rather than a claim.

**Why `stompmodel` is not part of `stompgeom`.** They answer to different constraints.
`stompgeom` exists because geometry is expensive to get right twice; `stompmodel` exists
because a shared value must have one definition. Merging them would make the
lightest package in the workspace depend on the heaviest, and would put the
admission rules above in competition with ADR-0008's "can it be described without
naming a panel?" — two tests for one package, which is how a dumping ground starts.

**Why lengths sit in `stompmodel` rather than `stompgeom`.** ADR-0008 listed lengths
among the geometry, which was reasonable when `stompgeom` was the only shared package.
A length is a unit, not an operation, and it is the most widely shared definition
here. Putting it in the leaf keeps the graph linear and lets a consumer take
`Nanometre` without taking a CAD kernel.

**Why the two admission rules stop where they do.** Rule 2 is the dangerous one: it
would justify moving anything two packages happen to resemble each other in. It is
bounded by its own wording — the uniformity must be something `stompcad` depends on.
`Pipeline` qualifies because `stompcad` reads both tools' `StageRun` provenance and
reduces both tools' diagnostics; `Source` does not, because `RawDrillData` is
artwork and `stompcollider`'s board reader returns something else entirely.

**Why one error base rather than one per tool.** `stompcad` runs both tools
behind a single command and reduces their failures to one report and one exit
code, so it needs `except StompError` to be a complete catch — two independent
bases would make it two clauses that a third tool silently falsifies. That is
the `stompcad` behaviour rule 2 demands a candidate name, and it is why
`EmitterError` and `DocumentError` sit beside the base rather than in the
package that happens to raise them first: producing an artefact and refusing a
foreign document are failures any member can have.

**Why the face frame is published rather than re-derived.** It is the same argument
the hole positions make. Those holes were cut *from* exact values, so reading them
back out of geometry could only lose precision or fail; the frame they were cut in
is equally known and equally lossy to recover. Re-deriving it would also drag
enclosure policy — which solid is the box, which coplanar level is the drilled face
— across a boundary that otherwise carries none, and would let two tools disagree
about where a panel is while both being self-consistent.

## Consequences

ADR-0004's `Nanometre` and `Millimetre` are `stompmodel`'s; its `Micron` is not, for
the reason "What leaves `stompdrill`" gives above. ADR-0001's pipeline and emitter
protocols become generic in the value they fold over, and both tools instantiate them.
ADR-0007's optional `stompdrill[step]` extra is retired when `stompgeom` lands:
`stompgeom` takes the kernel unconditionally, so `stompdrill` will too, and
ADR-0007's argument for the extra assumed `stompdrill` stood alone. Until then the
extra is still declared and still documented, and removing it is plan 2's change,
not plan 1's.

`stompdrill`'s public import paths change. Nothing is re-exported for compatibility —
one name, one home — and the workspace is pre-release with one consumer.

The migration's test is byte identity: every artefact `stompdrill` emits must be
unchanged across the move, and its suite is the instrument — with one intended
exception. The drill document gains the face frame, so it goes to version 6. A
version exists to signal a change of shape, and a reader that validates against
v5 should be told rather than handed an unexpected member.

The risk is that `stompmodel` accumulates types on rule 2's authority. The check is
that a type admitted under rule 2 must name the `stompcad` behaviour that depends on
the uniformity; a type that cannot name one is being moved for tidiness.
