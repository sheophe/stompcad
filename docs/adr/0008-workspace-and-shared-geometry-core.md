# ADR-0008: A workspace and a shared geometry core

**Status:** Accepted, amended by
[ADR-0009](0009-shared-model-package-and-dependency-order.md), which adds a fifth
package, `stompmodel`, and fixes the dependency order. The decisions to keep one
repository and extract shared primitives before building the new tools remain.

Of the three primitives originally assigned to `stompgeom`, lengths and frame
values now belong to `stompmodel`. The latter replace `Frame`'s rigid transform
for `stompdrill`'s canonical `(x, y)` coordinates on a drilled face.
`stompmodel` also publishes `RigidTransform` and the frame operations used to
compose one: `CoordinateFrame.translated_nm`, `rotated_about_w` and
`placement_onto`. `stompgeom` applies a composed transform to a kernel shape
through `shapes.placed`. The shared geometry core described below is now the
kernel layer: STEP reading, deterministic writing and OpenCASCADE operations.

## Context

`stompdrill` reads drill geometry from Illustrator artwork and emits fabrication
artefacts. At the time of this decision, two further tools were planned:
`stompcollider`, to seat PCB models inside a drilled case and report clashes;
and `stompcad`, a user-facing CLI to run both tools, manage the case-model cache
and turn diagnostics into interactive questions.

The tools need shared primitives. `stompcollider` needs ADR-0004's branded length
newtypes, a rigid transform composed from two frames to place one body against
another, and the level-based planar-face extraction in `cad/case.py`. Finding a
PCB's carrier plane uses the same geometric operation as finding a drilled face,
although the solids differ. Separate implementations would allow definitions
such as `Nanometre` to drift.

The repository contained only `stompdrill` and was named after it. The options
were separate repositories, one repository holding every package, or an umbrella
repository consuming the others.

## Decision

Rename this repository `stompcad`, after the user-facing tool, and make it a
workspace. The original four-package division was:

- `stompgeom`: lengths, rigid transforms and shared geometry.
- `stompdrill`: artwork in, fabrication artefacts out.
- `stompcollider`: drilled case and PCB models in, placements and clashes out.
- `stompcad`: the CLI that composes them.

ADR-0009 updates that division as noted in the status above.

Each package must install and pass its own tests alone. `stompdrill` must remain
usable without a collision engine, and `stompcollider` without an Illustrator
parser. Each structural rule must also be enforced by its owning package's
suite, run through that package's documented command. A breach in the owner's
source must fail that suite without requiring a consumer's tests.

`stompcad` consumes `stompdrill` and `stompcollider` as libraries.

Extract `stompgeom` before writing either new tool, starting with the length
newtypes and primitives already known to be shared. Extend its interface as
real second consumers appear.

## Rationale

### Keep changes to package boundaries in one repository

The boundaries between these tools will move frequently during early
development. Separate repositories would require version coordination for each
change, without providing isolation the sole maintainer needs. One repository
lets those changes remain atomic.

Making `stompcollider` depend on `stompdrill` would share the primitives cheaply,
but would also give a geometry engine a PDF-parser dependency. Extracting the
primitives gives the dependency graph a clearer meaning.

### Extract the known shared primitives first

Early abstraction usually risks designing for an unknown second use case.
Here, the shared primitives are already identifiable and `stompdrill` has a
large suite that can verify their extraction. Waiting would enlarge the move
and give `stompcollider` time to define duplicate types. Limiting extraction to
known shared needs keeps the interface grounded in actual use.

### Verify package independence by installing and testing it

A clean `pip install stompdrill` provides a practical check of the package
boundary. The original `stompdrill[step]` extra in ADR-0007 allowed the STEP
emitter to arrive without adding a kernel to the base install. That extra is
now retired, but dependencies remain explicit at the package boundary: the
kernel is declared by `stompgeom`, and a member that must avoid the kernel must
not depend on `stompgeom`.

## Consequences

### Repository and documentation layout

The repository's name no longer matches its original package.

Documentation stays under one root. A sectioned `docs/GLOSSARY.md` serves every
package because most vocabulary is shared. A `CONTEXT-MAP.md` pointing to
separate glossaries would duplicate those definitions. Per-package ADR
directories may be added; `docs/adr/` keeps its numbering for decisions that
span the workspace.

`stompdrill` gains a dependency on `stompgeom` and loses the primitives moved
there. Every emitted artefact must remain byte-identical across the extraction.
The move is complete only when its suite verifies that requirement.

### Read names and fields consistently

`stompgeom.step` owns the rule for reading a label's XCAF name. It distinguishes
an unnamed label from OCC's placeholder for an unnamed component occurrence.
The placeholder represents an indirection and provides no usable name, so it
reads back as empty too. All consumers, including `stompdrill`, must use this
implementation.

The reader must also round-trip every value the layer writes, reading the field
where the writer placed it. Each new reader for a written field must arrive
with a round-trip test.

The timestamp exposed the need for this rule. `stompgeom.writer.render_step`
writes the timestamp into `FILE_NAME`'s field, but
`stompgeom.step.source_timestamp` originally matched ST-Developer's
`/* time_stamp */` comment annotation. This workspace's writer emits no such
comment, so its own output read back with the epoch sentinel. The replacement
reads the field positionally, tolerating conforming comment annotations and
quoted-quote escaping. It replaces the comment-only pattern completely, keeping
one reader for the field.

### Own leaf traversal and label lifetimes

`stompgeom.step` publishes the walk from a document to its leaf labels,
including the `GetFreeShapes` prologue. A consumer reading, colouring or cutting
a leaf must use that walk. If the needed traversal is available only through a
private name, its public ownership needs correcting.

The published surface originally had seven names exposing bare kernel handles,
including traversal labels, `StepSolid.shape` and `StepDocument.document`.
Their lifetime requirements differ. Shapes are independently reference-counted
and measure identically after their source document is released. A held
document remains valid. A label, however, points into the document's label tree
and can dangle silently: it still reports not-null, but returns the document's
root entry and a null shape.

Labels therefore reach callers only inside `StepLabel`, which holds the
`TDocStd_Document` they came from. Holding the document's `ShapeTool` or root
label, `document.Main()`, is insufficient. `StepLabel` computes its name and
entry string on access rather than caching them.

Separate kernel calls can return labels for the same node that compare unequal
with `==`, because that comparison uses kernel object identity. Their entry
strings agree and `IsEqual` returns true. For this reason,
`stompgeom.writer.render_step`'s `replaced_labels` parameter continues to use
entry strings to identify nodes.

The other six kernel-typed names retain bare handles. They are annotated with
their OCP types under `TYPE_CHECKING`, which documents intent but adds no type
checking: `cadquery-ocp` has no `py.typed` marker, and both workspace mypy
configurations set `ignore_missing_imports` for `OCP.*`. Removing that override
would fail imports without checking the handles more closely.

This ownership guarantee is specific to labels: the published surface never
hands out an already-dangling label. It does not manage kernel lifetimes in
general. The raw handle field, `StepSolid.shape` and `bounding_box_mm`'s parameter
remain `Any` to mypy; only the owned label value gains checking. A caller can
still create a dangling reference by retaining `StepLabel.label` and discarding
the wrapper.

`StepLabel.label` remains public because the cutting path needs four XCAF
operations the package does not yet wrap. At the time of the lifetime change,
the build operation was also deferred; its later promotion is recorded below.
Hiding the field while requiring callers to access it would not improve this
boundary.

### Enforce each shared rule in its owner's suite

Five structural gates enforce rules that must have one implementation:

- The whole-nanometre guard.
- The case-face vocabulary.
- XCAF leaf traversal.
- ADR-0006's raw-measurement tie-break.
- ADR-0005's atomic-write mechanism.

Four belong to `stompmodel`'s suite; leaf traversal belongs to `stompgeom`'s.
A gate may read a sibling's source as text, but must never import a package
above its owner in the dependency graph. Thus `stompmodel` gates locate and
read `stompgeom` and `stompdrill` files without importing those packages.

Every gate discovers its scan targets through
`tools.workspace_membership.member_package_dirs`: directories under `packages/`
that ship their own `src`. New workspace packages must be covered without edits
to existing gates.

A gate's reach control must also avoid a fixed list of members. It checks that
each discovered member has the `src` it claims, and that its scan roots cover
every relevant `src` and, where applicable, `tests` directory found by an
independent walk. That walk is
`tools.workspace_membership.member_area_roots`; it never calls
`member_package_dirs`, so it can detect a narrowing of the latter's discovery.

`packages/stompdrill/tests/test_ownership_gate_convention.py` checks this
convention across the gate family. It discovers gates through their
reach-control marker rather than a fixed list of files. It then runs two probe
packages: one breaching every rule the family checks and one breaching none.
Adding a package or a gate must require no edits to existing gates or this
convention test.

### Render deterministic STEP bytes

`stompgeom.writer.render_step` is the single serialisation entry point. It
returns the completed STEP payload. The scratch file needed by OCC's path-only
writer API is an implementation detail.

For a document assembled by this workspace, output is byte-identical across
processes. The writer refuses documents with an unparsed presentation entity in
the colour region or a STEP pre-defined colour instead of inline `COLOUR_RGB`.
This workspace produces neither. Among supported colour chains, it
canonicalises ownership so repeated colours remain deterministic.

`render_step` suppresses the parametric-curve representation of every trimmed
edge. OCC's default emits a 3D curve and a curve in the parameter space of each
adjoining surface, each with a definitional representation and context. The
3D curve and its surface already determine the pcurve, so the output keeps one
representation.

Only OCC's own reader has been verified to recover the solid without pcurves.
Seam edges have historically been an exception for third-party readers, and
`SEAM_CURVE` is suppressed too. FreeCAD ships with the same preference off,
which supports the choice but does not verify untested readers. This is a fixed
setting because no downstream need for a switch has been identified.

### Build documents and recover colours

`stompgeom` also owns document construction.
`stompgeom.build.build_document` assembles placed, named, coloured solids;
`stompgeom.build.solid_colour` reads a solid's colour. These operations were
promoted when `stompcollider-technical.md` established the assembly emitter's
need for `placement` and `colour`.

Colour recovery needs several lookups. `build_document` assigns colour to the
label owning the whole shape, so querying that shape answers directly. In a
supplied assembly, a component's shape may be located while its colour belongs
to the unlocated product. A component modelled face by face may have no
whole-solid colour.

`solid_colour` queries the given shape, then its unlocated base, then its faces.
For face colours it weights by surface area, so a large body outweighs many
small leads. Ties use the lowest RGB triple, keeping the result independent of
kernel traversal order under ADR-0006. An uncoloured solid returns `None`.

`STEPCAFControl_Writer` writes a separate style for each solid in a coloured
shape. The writer's colour census must therefore count solids per coloured
label, not assignments. A board component can be one leaf containing a dozen
solids; counting labels would reject correctly written output.

### Keep the geometry boundary narrow

The risk is that `stompgeom` collects convenient helpers with tool-specific
meaning. `Frame` illustrates the boundary: a rigid transform is general, but
Y-up coordinates originating at a reference-outline centre belong to artwork.
Split such primitives instead of moving them wholesale. A `stompgeom` type must
be describable without naming a panel.
