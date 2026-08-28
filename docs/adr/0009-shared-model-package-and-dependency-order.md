# ADR-0009: A shared model package and the workspace's dependency order

**Status:** Accepted, amended in place: `CoordinateFrame` and `FaceFrame` are
`stompmodel`'s rather than `stompgeom`'s, and ADR-0007's optional extra is now retired
rather than pending. Both amendments were decided in `docs/specs/stompgeom-technical.md`
and landed with `docs/plans/2026-08-22-stompgeom-extraction.md`; the reasoning for the
first is under "Why the frame values sit in `stompmodel`" below. **Amended again:** the
document's version bump to 6 and the `CaseRegistration` member land now rather than in
plan 3, the frame nests inside the registration rather than sitting bare on the
document, and a fourth admission rule governs the promotion. See "The drill document
gains the face frame", the Consequences section, and the admission rules below.
**Amended again:** the fourth admission rule gains its second half -- a promoted
member must also state the convention under which it is read -- with
`CaseRegistration.face` as the worked example: it was a bare string with no
published vocabulary until `stompmodel.model.CaseFace` closed it. See the admission
rules below.
**Amended again:** the behaviour rule and the provenance-versus-contract rule are
restated as obligations with a completion condition, not permissions to use once
convenient, and the Consequences gain a standing gate -- the human-facing report
must be reproducible from the document alone. `CaseRegistration`, promoted under
the provenance rule with no reader outside the codec, is the worked example: see
the admission rules and the Consequences section below.
**Amended again:** `FaceFrame.basis.w`'s sense is stated as a convention -- the
drilled face's outward normal, independent of `basis.origin_nm`'s inner-surface
datum -- because both senses satisfy the type's own checks equally and no
validator can choose between them. See "Why the frame values sit in
`stompmodel`" below.

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
stompmodel ──► stompgeom ──┬──► stompdrill ─────┐
                           └──► stompcollider ──┴──► stompcad
```

*Figure 1: the workspace's dependency order. Each package installs and passes its
own tests alone, as ADR-0008 requires.*

Four of the five are built, in exactly this order: `stompmodel`, `stompgeom`,
`stompdrill` and `stompcollider`. `stompcollider` depends on `stompmodel` and
`stompgeom` and on neither of the others — it reads a drill document through
`stompmodel`'s codec, never through `stompdrill` — and it carries its own test,
type and mutation commands, as every member does. `stompcad` is the one package
this figure still anticipates rather than describes.

### `stompmodel`

Pure Python. No kernel, no parser, no I/O beyond serialisation. It holds:

- `Nanometre`, `Millimetre`, and their conversions (ADR-0004's newtypes).
- `CoordinateFrame` and `FaceFrame`, and the arithmetic that maps a point between
  a frame's axes and model space.
- `DrillData` and its members: `Hole`, `RawHole`, `ReferenceOutline`, `RawOutline`,
  `EnclosureMatch`, `SourceInfo`, `Origin`.
- The `DrillData` JSON codec, **both directions**.
- `Diagnostic`, `Severity`, `ParameterValue`, the plain-tuple `of_severity` and
  `worst_severity` reductions, and the severity-to-exit-code reduction.
- `Processable`, `Diagnosable`, `Stage[T]`, `Pipeline[T]`, `Emitter[T]`, `Payload`,
  `StageRun`.
- The workspace's error base: `StompError`, with `EmitterError` and
  `DocumentError` beneath it. Each tool's own base descends from it —
  `StompdrillError` does — so a package's errors stay identifiable while every
  one of them is catchable at once.

Four admission rules, and nothing else gets in:

1. **Interchange** — one package produces the value and another consumes it, and
   neither is its home.
2. **Contract** — a protocol or vocabulary both tools must implement identically
   for `stompcad` to treat them uniformly.
3. **Behaviour** — a rule both tools must agree on belongs beside the type it
   constrains, published there. `check_millimetres` and `check_nanometres` are
   this rule applied: the type they guard already lives in `stompmodel`, so a
   caller enforcing it again outside the module is one rule with two
   implementations that can drift, not a second rule.

   This is an obligation, not a permission to use once convenient: the rule
   is not satisfied by the shared implementation merely existing while a
   site it constrains keeps its own copy. **A publication under this rule is
   complete only once every site it constrains calls the published
   implementation instead of restating it.** `Hole.tie_break` joins
   `check_millimetres` and `check_nanometres` as the rule applied; ADR-0006
   records which sites it migrated.
4. **Provenance versus contract** — `StageRun.parameters` is provenance for the
   tool that produced it, a string-keyed bag nothing outside that tool should
   read. A fact a second consumer must read is a typed member with a codec
   inverse instead. `CaseRegistration` is this rule applied: the part, the face,
   the model's identity and the frame were reachable only as a clearance stage's
   parameters, string-keyed and unreconstructable, until a second consumer
   needed them and the rule said where they belonged.

   A promotion under this rule is not finished at the type declaration. **A
   fact promoted to a typed member must also state the convention under which
   it is read, or it is a member in name only.** `CaseRegistration.face` is
   the worked example: promoting it to a member said nothing about which
   faces are legal, so each of `stompdrill.cli`, `stompdrill.cad.case` and
   `stompdrill.emitters.step` spelled out its own answer, and the STEP
   emitter's answer was total where the other two were partial -- a face
   nobody recognised was silently drilled as the lid rather than refused.
   `stompmodel.model.CaseFace` closes the vocabulary once, published where the
   member lives, so a reader with only `stompmodel` installed can enumerate
   every legal face without reading `stompdrill`'s source, and a face the type
   does not hold is a construction failure everywhere, never a default.

   This rule too is an obligation, not a permission: **a promotion under it is
   complete only when every consumer that states the fact reads the typed
   member**, not only when the type exists and a codec can round-trip it. A
   typed member whose only reader is the codec is an unexercised promotion --
   a defect in its writer surfaces nowhere else in this workspace.
   `CaseRegistration` is the worked example: admitted under this rule with a
   codec inverse, it was left with no reader outside `to_document`/
   `from_document`, so the one place that states these facts to a human --
   `stompdrill.cli`'s report -- kept reading a live, kernel-backed case model
   instead of the document it was standing beside. The promotion completes
   only once that formatter reads `DrillData.case`, and the plate and play
   area recorded beside it in the clearance stage's own provenance, rather
   than the live handle it used to require.

A type a package owns and merely exposes to a library consumer **stays home**.
`stompcad` reading `stompcollider`'s `DockReport` is ordinary library consumption, not
interchange, so that type does not move.

### `stompgeom`

The kernel layer: the STEP reader (`read_step` from a path, `read_step_document` for a
document already in memory); the deterministic STEP writer with its OCC normalisation;
`shapes.compound`/`shapes.placed` for bundling and locating kernel shapes; `levels()` for
partitioning a solid's planar faces into the planes they lie in; `build.build_document`/
`build.solid_colour` for assembling a document from placed, named, coloured solids and
reading a solid's colour back; `assembly_spans`; bounding boxes; `KernelUnavailable`.

Frame *construction* is not here and is not coming. `build_frame` reads an
enclosure-shaped `Faces` and picks its `u` axis from the footprint spans, which is
enclosure reasoning wearing a geometric coat, so it stays in `stompdrill` under the
rule two paragraphs below. `stompmodel` owns the frame *type* and its transforms;
`stompgeom` owns neither. A reader looking here for a frame builder will not find one.

`levels()` arrived once `stompcollider`'s carrier-plane need shaped its interface, per
`docs/specs/foundation-docket-rulings.md`'s Ruling 2 — which stood in for that consumer
by measuring the repository's own fixtures rather than waiting for the consumer's code
to exist. It partitions, and keys each face's direction and offset to an integer bin
rather than clustering by a merge tolerance, which ADR-0006's order-independence
requires: two faces whose true normals differ by less than the bin's width land in
different levels however narrowly they straddle it. The measured window this can
affect is `5e-7`–`4.47e-5` radians of tilt, comfortably clear of every fixture measured.
Holedness does not move with it: `_plates` and `_HOLED_FRACTION_LIMIT` stay in
`stompdrill`, discriminating a casting plate from a casting ring, which is the same
enclosure reasoning that keeps `build_frame` out of this package.

No enclosure vocabulary crosses this boundary. `select_solid`'s box/lid keywords,
`CaseModel`, `Rejection` and the play-area reasoning in `region.py` stay in
`stompdrill`.

### The drill document gains the face frame

When a case model was supplied, `stompdrill` publishes the `FaceFrame` it cut in --
not as a bare member of the drill document, but nested inside `CaseRegistration`,
alongside the resolved part, the drilled face and the supplied model's file name. The
frame, the part, the face and the model's identity are one fact -- what the holes were
decided against -- not four independent members that happen to arrive together.
`stompcollider` reads that registration rather than recovering it.

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

**Why the frame values sit in `stompmodel` rather than `stompgeom`.** As accepted, this
ADR placed `CoordinateFrame` and `FaceFrame` in `stompgeom` while also having the drill
document carry a `FaceFrame`, keeping `DrillData` in a leaf that declares no dependencies
at all, and calling the graph linear and acyclic. Those four cannot all hold: a
`stompmodel` dataclass cannot carry a member defined above it without importing it, which
is a cycle in the graph Figure 1 draws. The frame *value* needs no kernel — it is a
frozen, slotted dataclass of `Nanometre` and float triples, with the arithmetic that maps
a point between its axes and model space — while the operation that reads OCC faces to
*build* one does. That is the division made for the length newtypes below, and its
rationale transfers verbatim: a registration is a value rather than an operation, and
putting it in the leaf keeps the graph linear and lets a consumer take a frame without
taking a CAD kernel. It also satisfies admission rule 1 without strain — `stompdrill`
produces the face frame, `stompcollider` consumes it, and neither is its home. This is
what unblocks "The drill document gains the face frame" above: `DrillData` can carry a
`FaceFrame` and the codec can serialise it without `stompmodel` growing a dependency on
OpenCASCADE.

**`FaceFrame`'s third axis states its own sense, per admission rule 4's obligation.**
Rule 4's second half applies to any promoted member, not only one that arrived by the
provenance route: a fact published without its reading convention is a member in name
only. `FaceFrame.basis.w` is fixed by convention to the drilled face's **outward**
normal -- pointing away from the material and out of the enclosure -- independent of
`basis.origin_nm`'s inner-surface datum. This is stated rather than derived because it
is unrecoverable: both senses of `w` satisfy `CoordinateFrame`'s own orthonormality and
right-handedness checks equally, so no validator over the type can choose between them.
Checked, not merely asserted: `packages/stompdrill/tests/test_cad_case.py` runs this
claim against the frame `stompdrill.cad.case.build_frame` actually publishes, over the
four catalogued Hammond models the kernel suite can fetch (1590BB, 1590B, 1590A,
1590Y), both box and lid faces -- narrowed to those four because no STEP model is
fetched for the catalogue's other parts, not because the convention is believed to
hold only there.

**Why lengths sit in `stompmodel` rather than `stompgeom`.** ADR-0008 listed lengths
among the geometry, which was reasonable when `stompgeom` was the only shared package.
A length is a unit, not an operation, and it is the most widely shared definition
here. Putting it in the leaf keeps the graph linear and lets a consumer take
`Nanometre` without taking a CAD kernel.

**Why the four admission rules stop where they do.** Rule 2 is the dangerous one: it
would justify moving anything two packages happen to resemble each other in. It is
bounded by its own wording — the uniformity must be something `stompcad` depends on.
`Pipeline` qualifies because `stompcad` reads both tools' `StageRun` provenance and
reduces both tools' diagnostics; `Source` does not, because `RawDrillData` is
artwork and `stompcollider`'s board reader returns something else entirely. Rule 3 is
bounded the same way it is stated: it admits a rule that constrains a type `stompmodel`
already owns, never a rule about behaviour a package happens to share for other reasons —
that would be rule 2 wearing a different name. Rule 4 is narrower still: it admits a
typed member only once a second consumer must read the fact back out of a stage's
provenance, never merely because a fact "could" be typed -- that would justify moving
every stage's parameters into `stompmodel` on spec.

**Why `Diagnosable` and its plain-tuple reduction are admitted.** Rule 3 is why:
`of_severity` and `worst_severity` constrain `Diagnostic`, which `stompmodel` already
owns, so a second implementation of either outside this module would be the same
drift `check_millimetres` and `check_nanometres` were published to stop. What is
specific here is the consequence for interoperability: the exit-code reduction's
vocabulary is part of `stompmodel`'s published contract, so a second tool's value
type is assured of interoperating with it.

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
ADR-0007's optional `stompdrill[step]` extra is retired now that `stompgeom` has
landed: `stompgeom` takes the kernel unconditionally, so `stompdrill` does too, and
ADR-0007's argument for the extra assumed `stompdrill` stood alone. That was plan 2's
change, as this ADR anticipated, and it is done.

`stompdrill`'s public import paths change. Nothing is re-exported for compatibility —
one name, one home — and the workspace is pre-release with one consumer.

The migration's test is byte identity: every artefact `stompdrill` emits must be
unchanged across the move, and its suite is the instrument. **Amended: the version
bump lands here, not deferred.** The document goes to version 6 in the same commit
that adds `CaseRegistration`, carrying the whole registration -- the resolved part,
the drilled face, the supplied model's file name and the frame -- so `stompcollider`
consumes a document it does not have to grow first. A version exists to signal a
change of shape, and a reader that validates against v5 is refused before any new
key is read rather than handed an unexpected member.

The risk is that `stompmodel` accumulates types on rule 2's authority. The check is
that a type admitted under rule 2 must name the `stompcad` behaviour that depends on
the uniformity; a type that cannot name one is being moved for tidiness. `format_nm` is
the worked example: it is a formatter rather than a conversion between the published
newtypes (`mm_from_nm` is that), so rule 2 is what admits it, and the behaviour it names
is that `stompcad` reduces both tools' nanometre quantities to one report — two
independent renderers would print one nanometre two ways.

**Amended again: a standing gate joins the four admission rules above.** The
human-facing report must be reproducible from the document alone: every fact
`stompdrill.cli.format_report` states comes from a typed member or from
provenance the document itself carries, never from a value only a live
pipeline run holds. `CaseRegistration`'s promotion above is one instance of
this gate; it names no member, so it binds every future typed member the
same way.
