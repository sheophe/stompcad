# ADR-0008: A workspace and a shared geometry core

**Status:** Accepted, amended by
[ADR-0009](0009-shared-model-package-and-dependency-order.md), which adds a fifth
package, `stompmodel`, and fixes the workspace's dependency order. The reasoning here
for one repository and for extracting before the new tools is unchanged.

Two of the three primitives this ADR named as certainly shared have since settled in
`stompmodel`: the length newtypes, and the frame values that replaced `Frame`'s rigid
transform. That settles `stompdrill`'s own spatial need — canonical `(x, y)` on a drilled
face — not the workspace's: `stompmodel` also publishes `RigidTransform` itself and the
frame-to-frame composition that builds one (`CoordinateFrame.translated_nm`,
`rotated_about_w`, `placement_onto`), and `stompgeom` publishes the kernel realisation
that applies a composed transform to a shape (`shapes.placed`). What `stompgeom` holds is
therefore the kernel layer — the STEP reader, the deterministic writer, and the
operations that need OpenCASCADE — so read "shared geometry core" below as that layer
rather than as one package holding every shared primitive.

## Context

`stompdrill` reads drill geometry from Illustrator artwork and emits fabrication
artefacts. Two further tools are planned. `stompcollider` seats PCB models inside a
drilled case and reports where they clash. `stompcad` is the user-facing CLI that
drives both, manages the case-model cache, and turns a diagnostic into an
interactive question.

They share primitives. `stompcollider` needs the branded length newtypes of
ADR-0004 exactly as `stompdrill` defines them, needs a rigid transform composed from two
frames — placing one body against another, not `stompdrill`'s single canonical origin —
and needs the level-based planar-face extraction that `cad/case.py` uses to find a
drilled face — a PCB's carrier plane is the same problem with a different solid. Without
a decision, each tool grows its own `Nanometre` and the three drift.

The repository is currently the `stompdrill` package and nothing else, and is named
after it.

Three structures were available: three separate repositories; one repository
holding every package; or an umbrella repository consuming the others.

## Decision

This repository becomes a workspace and is renamed `stompcad`, after the
user-facing tool. It holds four packages:

- `stompgeom` — lengths, rigid transforms, and the geometry shared by the rest.
- `stompdrill` — unchanged in scope: artwork in, fabrication artefacts out.
- `stompcollider` — drilled case and PCB models in, placements and clashes out.
- `stompcad` — the CLI that composes them.

Each package must install and pass its own tests **alone**. `stompdrill` stays
usable without a collision engine, and `stompcollider` without an Illustrator
parser. This extends to a structural rule a member owns, not only to its
distribution's runtime dependencies: the gate enforcing that rule is run by
the *owning* member's own documented command, never by a consumer's, so a
breach of the rule inside the owner's own source fails the owner's own suite
without any other member's tests having to run at all.

`stompcad` consumes `stompdrill` and `stompcollider` as **libraries**, not subprocesses.

`stompgeom` is extracted **first**, before either new tool is written, starting
with the length newtypes and the primitives whose sharing is already certain.
It grows as real second consumers appear; its interface is not designed in
advance.

## Rationale

**Why not three repositories.** The seams between these tools will move
constantly in early life. Three repositories make every seam change a
cross-repository version negotiation, paid on every commit, by one maintainer,
for isolation nobody is asking for. One repository keeps those changes atomic.

**Why not let `stompcollider` depend on `stompdrill`.** It is the cheapest way to
share the primitives and the hardest to defend afterwards: a pure geometry
engine would acquire a dependency on a PDF parser, and the dependency graph
would stop describing anything real. The primitives are not `stompdrill`'s by
right — it merely wrote them first.

**Why extract upfront rather than at the second consumer.** The usual argument
against early abstraction is that the second use case is unknown, so the seam is
guessed. That argument is weaker here in one specific way: `stompdrill` has a large
test suite, so the extraction is *verifiable* now — a move that breaks something
says so immediately. Deferring the extraction does not make it safer; it makes
it larger, and it invites `stompcollider` to define its own `Nanometre` in the
meantime. Extraction is bounded to what is certainly shared, so the interface is
still discovered rather than invented.

**Why "installs alone" is the governing test.** A boundary asserted in prose
erodes. A boundary that must survive `pip install stompdrill` in a clean
environment does not: an unjustified dependency stops being a design opinion and
becomes a failing install. ADR-0007's optional `stompdrill[step]` extra already
demonstrates the discipline, which is what let a STEP emitter arrive later
without the base tool growing a geometry kernel. That extra is now retired — see
ADR-0007's status — and the discipline it demonstrated is carried by the package
boundary instead: the kernel is `stompgeom`'s declared dependency, and a member that
must not take one does not depend on `stompgeom`.

## Consequences

The repository is renamed, and the directory no longer shares a name with the
package it contains.

Documentation stays single-rooted. One sectioned `docs/GLOSSARY.md` serves every
package, rather than a `CONTEXT-MAP.md` pointing at one glossary per context:
these packages share most of their vocabulary, and splitting it would duplicate
the shared half and invite the copies to drift. Per-package ADR directories
become possible alongside the system-wide one, and `docs/adr/` keeps its
existing numbering for decisions that span the workspace.

`stompdrill` gains a dependency on `stompgeom`, and its own modules lose the
primitives that move. Every artefact `stompdrill` emits must be byte-identical
across the move; its suite is the instrument that proves it, and the extraction
is not complete until it does.

On the reading side, `stompgeom` now owns a document it can **read and enumerate
faithfully**: `stompgeom.step` publishes the one rule for what XCAF recorded as a
label's name, distinguishing "nobody named this" from "the kernel synthesised an
indirection" — OCC's own placeholder for an unnamed component occurrence, which
names nothing and reads back as empty like any other unnamed label. That rule has
exactly one implementation; a caller reading a label's name, in `stompdrill` or a
future consumer, goes through it rather than keeping a private copy that could
drift from the reader's own.

The reading side must also be **closed under its own round trip**: every value
this layer writes into a document or a file is read back from the field it was
actually written to, never from a second producer's labelling convention for
that field, and a reader added for a field the writer sets arrives with the
round trip that proves it. The timestamp was the counter-example that forced
this paragraph: `stompgeom.writer.render_step` sets the timestamp into
`FILE_NAME`'s own field, but `stompgeom.step.source_timestamp` matched only
ST-Developer's `/* time_stamp */` comment annotation — a different producer's
label for that field, which this workspace's own writer never emits — so a
file this layer had just written read its own timestamp back as the epoch
sentinel. The fix is one rule reading one field, positionally, tolerant of a
conforming file's comment annotations and of the field's own quoted-quote
escaping; the comment-only pattern is deleted rather than kept as a second,
narrower reader for the same field, because two readers for one written field
is this defect's exact shape.

The document's **traversal** is owned on the same terms as its names:
`stompgeom.step` publishes the one walk from a document to its leaf labels,
`GetFreeShapes` prologue included, and a caller that must act on a leaf — read
it, colour it, cut it — goes through that walk rather than re-deriving it. A
consumer that can only reach `stompgeom`'s own enumeration through a private
name is evidence that a rule is owned in the wrong place, not that the
consumer was impolite.

The traversal's own labels were bare kernel handles too, alongside
`StepSolid.shape` and `StepDocument.document` — **seven published names, and
not one debt.** A shape is independently reference-counted and measures
identically whether or not the document that produced it is still held; a
document is the anchor and cannot dangle by being held. Only a label points
into a document's own label tree, and only a label dangles — **silently**: a
label drawn from a released document still answers not-null, and reports the
document's own root entry and a null shape rather than faulting. Wrapping the
shape or the document would buy nothing and would weaken the honest sentence
that they owe nothing to a caller's discipline.

`stompgeom.step` now publishes no bare label: one reaches a caller only
inside `StepLabel`, which holds the `TDocStd_Document` it was drawn from —
that object specifically, since neither the document's own `ShapeTool` nor
its own root label (`document.Main()`) keeps a label valid — and which
answers its own name and its own entry string, computed on access rather
than cached. Two labels drawn for one node by separate kernel calls compare
unequal by `==` (kernel object identity, not `IsEqual`) even though their
entry strings agree and `IsEqual` answers true; this is why "the same label"
is tested and carried as an entry string, not as a set of owned labels, in
the one place a caller still needs it — `stompgeom.writer.render_step`'s
`replaced_labels` parameter, unchanged in shape by this ticket.

The other six kernel-typed names keep their bare kernel handle, now spelled
with its real OCP type under a `TYPE_CHECKING` guard for readability.
**This spelling documents intent and checks nothing:** `cadquery-ocp` ships
no `py.typed` marker and both this workspace's mypy configurations already
set `ignore_missing_imports` for `OCP.*`, so removing that override would
make the gate red at the import for zero additional checking, and nobody
should "fix" that later expecting it to buy safety.

None of this is a claim that `stompgeom` owns kernel lifetimes in general —
it owns a label's, by design — or that no `Any` crosses this boundary (the
raw handle field, `StepSolid.shape` and `bounding_box_mm`'s parameter stay
`Any` to mypy, honestly), or that the kernel handles generally are now
type-checked (exactly one value is), or that a caller can no longer
construct a dangling reference (one who keeps the raw handle and drops
`StepLabel` still can). The true claim is narrower: **the *published
surface* offers no route that hands out a label already dangling.**
`StepLabel.label` stays a public, raw field for the same reason the ADR's
build verb stays deferred — the cutting path needs four XCAF verbs this
package does not yet wrap, and a private field plus a reach-in would be the
same convention, unnamed, plus a lie about encapsulation.

**A rule a member owns is enforced by that member's own tests, not by
whichever member's suite happened to notice the duplication first.** Five
structural gates enforce "this rule is stated once" — the whole-nanometre
guard, the case-face vocabulary, this section's own XCAF leaf descent,
ADR-0006's raw-measurement tie-break, and ADR-0005's atomic-write mechanism
— and each now lives in the suite of the package that owns the rule it
polices: four in `stompmodel`'s own suite, one (the leaf descent) in
`stompgeom`'s. A gate may read a sibling's source as text to reach a rule's
every possible violator; it may never *import* a package above its own,
which is why a gate homed in `stompmodel` resolves `stompgeom` and
`stompdrill` by reading their files rather than importing them. Every gate
derives the packages it scans from one shared statement,
`tools.workspace_membership.member_package_dirs` — a directory under
`packages/` shipping its own `src` — so a package this workspace gains later
is scanned by every existing gate with no edit to any of them.

**The claim above binds a gate's reach control too, not only its scan.**
Deriving the scan from `member_package_dirs` is not enough on its own: each
gate's reach control — the assertion that the scan reached something it
could have missed, rather than nothing — must itself avoid naming the
member set, or the scan is variable while the instrument that proves it
reached anything is not. Each gate's reach control instead checks two
properties: every member the scan discovered really ships the `src` it
claims to, and the scan's own roots cover every `src` (and, where the
gate's reach includes it, `tests`) directory an independent walk of
`packages/` finds — `tools.workspace_membership.member_area_roots`, which
never calls `member_package_dirs` and so can disagree with it if that
function's own discovery narrows. The ownership-gate convention test
(`packages/stompdrill/tests/test_ownership_gate_convention.py`) carries the
same discipline one level up: it finds the gate family itself by the
reach-control marker every gate defines, not by a literal list of gate
files, and runs a matched pair of probe packages — one breaching every
rule the family polices, one breaching none — so its own coverage of "every
gate" cannot silently narrow either. A package or a gate this workspace
gains later needs no edit to any existing gate or to this convention test.
`stompgeom` now owns a document it can **render to bytes**:
`stompgeom.writer.render_step` is the one serialising entry point, returning the
finished STEP payload rather than a path — the scratch file its OCC-backed writer needs
along the way is an implementation detail forced by that kernel's own path-only API, not
part of this function's contract. Its determinism guarantee is scoped, not universal: it
is byte-identical across processes for a document this workspace assembles, and it
**refuses** a document carrying an unparsed presentation entity in its colour region, or
one whose colour is a STEP pre-defined colour rather than an inline `COLOUR_RGB` —
neither of which anything in this workspace produces. The writer canonicalises colour
ownership among the chains it does parse, which is what makes a repeated colour safe.

`stompgeom` now owns the fourth verb too: **build**, assembling a document from placed,
named, coloured solids. `stompgeom.build.build_document` does the assembling and
`stompgeom.build.solid_colour` reads a solid's colour back, promoted once
`stompcollider-technical.md`'s own build contract fixed the shape a real second caller —
the assembly emitter — needs: a `placement` and a `colour`.

Reading that colour back is not one lookup, because a file does not record colour in one
place. `build_document` sets it on the label owning the whole shape, and asking XCAF for
that shape answers directly. A real file mostly does neither: an assembly component's
shape is its product's shape carried under a location while the colour sits on the
product, and a component modelled face by face carries no whole-solid colour at all.
`solid_colour` therefore asks for the shape as given, then for its unlocated base, and
only then weighs the colours its faces carry — by **surface area**, since a part is the
colour of its body rather than of its many small leads. Ties fall to the lowest RGB
triple, so the answer never depends on the order the kernel walks a shape in (ADR-0006).
A solid nothing coloured is still `None`; no default is invented for it.

One colour assignment is not one written colour chain, either. `STEPCAFControl_Writer`
styles each solid of a coloured shape in its own right, so the writer's census counts
solids per coloured label rather than labels — an ordinary board component reaches the
reader as one leaf holding a dozen solids. A census counting assignments refuses a file
it has just written correctly, which is what the guard exists to prevent.

The risk carried is that `stompgeom` accumulates whatever is convenient rather than
what is universal. `Frame` is the live example: it is a rigid transform, which
is universal, wrapped in a meaning — Y-up, originating at the reference-outline
centre — that belongs to panel artwork and says nothing about a PCB. Primitives
of that shape are split, not moved wholesale, and the test is whether the
`stompgeom` type can be described without naming a panel.
