# ADR-0009: A shared model package and the workspace's dependency order

**Status:** Accepted, amended in place.

This ADR adds `stompmodel` to the four packages decided in
[ADR-0008](0008-workspace-and-shared-geometry-core.md). Later amendments:

- Place `CoordinateFrame` and `FaceFrame` in `stompmodel` and retire ADR-0007's
  optional kernel extra.
- Bring the document's version bump to 6 and `CaseRegistration` forward from
  plan 3. The frame nests inside the registration, and a fourth admission rule
  governs facts promoted from provenance.
- Require promoted members to publish their reading conventions, including the
  `CaseFace` vocabulary and the sense of `FaceFrame.basis.w`.
- Define completion conditions for the behaviour and provenance rules, and
  require the human-facing report to be reproducible from the document alone.

The decisions and their reasons are set out below.

## Context

ADR-0008 established the workspace before the new tools were designed. It could
identify shared lengths, rigid transforms and geometry, but designing
`stompcollider` exposed three further needs.

First, the interchange value is the whole drill model. `stompcollider` needs the
hole pattern `stompdrill` produces, including its frame, tool table, enclosure
identity and hole numbering. These already exist in `DrillData` and its
versioned JSON. Defining another `HolePattern` and adapting it in `stompcad`
would create a second serialised form of the same facts.

Second, both tools need one diagnostic vocabulary. `stompcad` combines their
findings into one report and exit code. Separate `Severity` enums and exit-code
tables could disagree.

Third, `stompgeom` takes OpenCASCADE unconditionally. The workspace had no users
of a kernel-free geometry configuration, but a package of frozen dataclasses
should remain usable without that dependency.

## Decision

The workspace has five packages in an acyclic dependency order, shown in
ADR-0009, Figure 1.

```
stompmodel ──► stompgeom ──┬──► stompdrill ─────┐
                           └──► stompcollider ──┴──► stompcad
```

*Figure 1: the workspace's dependency order. Each package installs and passes its
own tests alone, as ADR-0008 requires.*

The first four were built in this order: `stompmodel`, `stompgeom`, `stompdrill`,
then `stompcollider`. `stompcollider` depends on `stompmodel` and `stompgeom`.
It reads drill documents through `stompmodel`'s codec and does not depend on
`stompdrill` or `stompcad`. Like every member, it has its own test, type and
mutation commands. `stompcad` remains planned.

### `stompmodel`

`stompmodel` is pure Python, with no kernel, parser or I/O beyond serialisation.
It holds:

- `Nanometre`, `Millimetre` and their conversions: ADR-0004's newtypes.
- `CoordinateFrame`, `FaceFrame` and the arithmetic mapping points between frame
  axes and model space.
- `DrillData` and its members: `Hole`, `RawHole`, `ReferenceOutline`,
  `RawOutline`, `EnclosureMatch`, `SourceInfo`, `Origin` and the case registration
  described below.
- Both directions of the `DrillData` JSON codec.
- `Diagnostic`, `Severity`, `ParameterValue`, the plain-tuple `of_severity` and
  `worst_severity` reductions, and the severity-to-exit-code reduction.
- `Processable`, `Diagnosable`, `Stage[T]`, `Pipeline[T]`, `Emitter[T]`,
  `Payload`, `StageRun` and the plain-tuple `latest_run` reduction.
- `SNAP_STAGE` and `SNAP_GRID_PARAMETER`, naming the snapping stage and its
  effective-pitch parameter, with `DrillData.grid_nm` as their single accessor.
- `StompError`, with `EmitterError` and `DocumentError` beneath it. Each tool's
  error base, including `StompdrillError`, descends from `StompError`. Callers can
  catch all workspace errors together while retaining tool-specific types.

Only the following four admission rules permit additions to `stompmodel`.

#### 1. Interchange

One package produces a value and another consumes it, and neither package is its
home.

#### 2. Contract

A protocol or vocabulary belongs here when both tools must implement it
identically for `stompcad` to treat them uniformly. Each addition must name the
`stompcad` behaviour that depends on that uniformity.

#### 3. Behaviour

A rule both tools must agree on belongs beside the type it constrains, provided
`stompmodel` already owns that type. `check_millimetres` and `check_nanometres`
apply this rule to the shared length types. Reimplementing either in a caller
would create a second version of the same rule.

Publication is complete only when every site the rule constrains calls the
shared implementation. `Hole.tie_break` is another example; ADR-0006 records
its migrated callers.

#### 4. Provenance versus contract

`StageRun.parameters` records provenance for the producing tool. A fact a
second consumer must obtain from the document belongs in a typed member with a
codec inverse, rather than being recovered from string-keyed stage parameters.

`CaseRegistration` applies this rule. The part, face, model identity and frame
were previously available only in the clearance stage's parameters and could
not be reconstructed. A second consumer's need for them required their
promotion to a typed member.

Every promoted fact must also publish the convention needed to interpret it.
`CaseRegistration.face` initially remained a bare string, leaving
`stompdrill.cli`, `stompdrill.cad.case` and `stompdrill.emitters.step` to define
legal faces independently. The STEP emitter treated an unrecognised face as a
lid, while the other two rejected it. `stompmodel.model.CaseFace` now defines
the vocabulary beside the member. A consumer with only `stompmodel` installed
can enumerate the legal faces, and any other value fails construction
everywhere.

Promotion is complete only when every consumer that states the fact reads the
typed member. A codec round trip alone is insufficient: it leaves errors in
the writer unexercised elsewhere. `CaseRegistration` initially had no reader
outside `to_document`/`from_document`; `stompdrill.cli`'s human-facing report
still read a live kernel model. Completing the promotion requires that
formatter to read `DrillData.case`, plus the plate and play area recorded in the
clearance stage's provenance.

An optional provenance read is allowed when the consumer can obtain the fact
another way. `stompcollider` derives its recognition tolerance from the snapping
stage's recorded pitch, but `--match-tolerance` supplies the same length
directly. If the document has no pitch, the caller must supply that flag or
receive a usage failure naming it. `CaseRegistration` had no equivalent
fallback: `stompcollider` deliberately has no `--case-face`.

Thus promotion depends on whether a second consumer requires the recorded fact,
not merely whether it reads it. An allowed provenance read still needs one
published spelling and accessor under rule 3. `SNAP_STAGE`,
`SNAP_GRID_PARAMETER` and `DrillData.grid_nm` live in `stompmodel`, so a renamed
stage breaks one accessor instead of silently leaving several readers empty.
The pitch must become a typed member as soon as a consumer needs it without a
flag fallback.

A type that belongs to a package and is exposed through its library stays there.
For example, `stompcad` consuming `stompcollider`'s `DockReport` does not make
that report an interchange value.

### `stompgeom`

`stompgeom` owns kernel operations:

- STEP reading: `read_step` from a path and `read_step_document` from a document
  already in memory.
- Deterministic STEP writing, including OCC normalisation.
- `shapes.compound` and `shapes.placed`, for bundling and locating shapes.
- `shapes.common`, the exact boolean intersection used by clash checking. It
  returns `None` when bodies share no region, rather than an untopologised empty
  compound.
- `levels()`, which partitions a solid's planar faces by their planes.
- `cylinders.Cylinder` and `cylinders.cylindrical_faces`, which expose each
  cylindrical face's axis, radius and axial trim for protrusion profiles.
- `build.build_document` and `build.solid_colour`, for constructing documents
  from placed, named, coloured solids and reading colours back.
- `assembly_spans`, bounding boxes and `KernelUnavailable`.

Frame construction stays in `stompdrill`. `build_frame` reads an
enclosure-shaped `Faces` and selects `u` from footprint spans, which requires
enclosure policy. `stompmodel` owns the frame types and transforms;
`stompgeom` owns neither those nor the frame builder.

`levels()` was introduced after measurements of the repository's fixtures
established `stompcollider`'s carrier-plane needs. It maps each face's direction
and offset to integer bins. A merge-tolerance clustering algorithm could depend
on traversal order, violating ADR-0006.

Binning has a boundary cost: two normals separated by less than a bin's width
can belong to different levels if they straddle its edge. The measured affected
window is `5e-7`–`4.47e-5` radians of tilt, clear of every measured fixture.
`_plates` and `_HOLED_FRACTION_LIMIT` stay in `stompdrill`, because distinguishing
a casting plate from a casting ring is enclosure policy.

No enclosure vocabulary crosses this boundary. `select_solid`'s box/lid
keywords, `CaseModel`, `Rejection` and the play-area rules in `region.py` also
remain in `stompdrill`.

### The drill document gains the face frame

When a case model is supplied, `stompdrill` publishes the `FaceFrame` used for
cutting inside `CaseRegistration`, alongside the resolved part, drilled face
and supplied model's file name. Together these identify what the holes were
decided against. `stompcollider` reads that registration directly.

### What leaves `stompdrill`

`model.py` is deleted. `RawDrillData`, the pre-canonical value used only by the
source and quantiser, moves to `quantise.py`. `Micron` stays in `stompdrill`
because it expresses grid policy.

`JsonEmitter` remains a registered emitter but wraps `stompmodel`'s codec,
owning only `indent`. `SourceInfo.producer` no longer defaults to
`"stompdrill"`. Whoever reads the artwork must name the producer, so a document
from another tool cannot accidentally claim `stompdrill` provenance.

## Rationale

### Share the whole drill document and its codec

A narrower `HolePattern` would still need the frame, tool table, hole numbers
and enclosure identity: most of `DrillData`. Its remaining provenance can simply
be ignored by a consumer. The wider type costs unused fields in `stompcollider`;
a narrower type costs a second schema, codec and version number. Keeping one
value preserves the agreement between artefacts without an adapter that could
change the hole representation.

Moving the codec with the type also avoids forcing `stompcollider` to import
`stompdrill` or write another reader. It adds the inverse the emitter lacked and
makes document round trips testable as a property.

### Separate shared values from kernel operations

`stompgeom` shares geometry operations; `stompmodel` gives shared values one
definition. Combining them would give dataclass consumers a kernel dependency
and mix the admission rules with ADR-0008's requirement that geometry types be
describable without naming a panel.

The original version of this ADR placed `CoordinateFrame` and `FaceFrame` in
`stompgeom` while requiring dependency-free `DrillData` to contain a
`FaceFrame`. That would introduce a cycle in ADR-0009, Figure 1.

A frame value needs no kernel: it is a frozen, slotted dataclass of `Nanometre`
and float triples, with arithmetic mapping points between its axes and model
space. Building one from OCC faces does need the kernel. Placing the value in
`stompmodel` keeps the graph acyclic and lets its codec serialise the frame
without OpenCASCADE. It satisfies rule 1: `stompdrill` produces it and
`stompcollider` consumes it.

Lengths follow the same division. ADR-0008 grouped them with geometry when
`stompgeom` was the only shared package. `Nanometre` and `Millimetre` belong in
`stompmodel` so consumers can use these common units without the kernel.

### Publish the face normal convention

Rule 4's reading-convention requirement applies to every promoted member,
including those admitted through other rules. `FaceFrame.basis.w` is the
drilled face's outward normal, pointing away from the material and out of the
enclosure. Its sense is independent of `basis.origin_nm`, which lies on the
inner surface.

This must be stated because either sense of `w` can satisfy `CoordinateFrame`'s
orthonormality and right-handedness checks. The type cannot choose between
them. `packages/stompdrill/tests/test_cad_case.py` verifies the frames published
by `stompdrill.cad.case.build_frame` for both box and lid faces on the four
Hammond models fetched by the kernel suite: 1590BB, 1590B, 1590A and 1590Y. The
test scope reflects model availability; the convention applies to all parts.

### Bound the admission rules

Rule 2 requires a specific `stompcad` need. `Pipeline` qualifies because
`stompcad` reads both tools' `StageRun` provenance and reduces their diagnostics.
`Source` does not: `RawDrillData` represents artwork, while `stompcollider`'s
board reader produces a different value.

Rule 3 covers only rules constraining types already owned by `stompmodel`.
Rule 4 requires a second consumer that needs a fact from the recorded provenance;
the possibility of typing a parameter is insufficient.

`Diagnosable` and the plain-tuple `of_severity` and `worst_severity` reductions
qualify under rule 3 because they constrain the existing `Diagnostic` type.
Sharing them prevents the same drift as the length guards. It also gives a
second tool's value type a published vocabulary for interoperating with the
exit-code reduction.

`StompError` qualifies under rule 2 because `stompcad` must catch either tool's
failures and produce one report and exit code. Every tool-specific base must
descend from it, so adding a tool preserves the completeness of
`except StompError`. `EmitterError` and `DocumentError` belong beside it because
any member can fail to produce an artefact or refuse a foreign document.

### Publish the frame used to cut the holes

Hole positions are already known exactly; recovering them from the cut model
could lose precision or fail. The cutting frame has the same property.
Re-deriving it would also bring enclosure rules into `stompcollider`, including
which solid is the box and which planar level is the drilled face. Publishing
it prevents two otherwise self-consistent tools from choosing different panel
positions.

## Consequences

ADR-0004's `Nanometre` and `Millimetre` move to `stompmodel`; `Micron` remains in
`stompdrill` as grid policy. ADR-0001's pipeline and emitter protocols become
generic over their values and are instantiated by both tools.

ADR-0007's optional `stompdrill[step]` extra is retired. `stompgeom` takes the
kernel unconditionally, so `stompdrill` now does too. The extra's rationale
assumed a standalone `stompdrill`; plan 2 completed this dependency change.

Public import paths change without compatibility re-exports. The workspace is
pre-release and has one consumer, so each name has one home.

The migration requires byte identity for every emitted artefact, verified by the
suite. **Amended:** the registration schema change is included here, with its
version bump brought forward from plan 3. The document moves to version 6 in
the commit adding `CaseRegistration`, including the resolved part, drilled
face, model file name and frame. This gives `stompcollider` the complete document
it needs. A reader validating v5 refuses the new version before reading new
keys.

The main risk is admitting too much through rule 2. Each candidate must identify
the `stompcad` behaviour requiring uniformity. `format_nm`, for example, is a
formatter, while `mm_from_nm` converts between newtypes. Rule 2 admits
`format_nm` because `stompcad` combines both tools' nanometre quantities in one
report and needs a consistent rendering.

A standing gate also applies: every fact in `stompdrill.cli.format_report` must
come from a typed document member or recorded provenance. The human-facing
report must be reproducible from the document alone, without values held only
by a live pipeline run. `CaseRegistration` prompted this requirement, but it
applies to every future member.
