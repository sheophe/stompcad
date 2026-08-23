# ADR-0008: A workspace and a shared geometry core

**Status:** Accepted, amended by
[ADR-0009](0009-shared-model-package-and-dependency-order.md), which adds a fifth
package, `stompmodel`, and fixes the workspace's dependency order. The reasoning here
for one repository and for extracting before the new tools is unchanged.

Two of the three primitives this ADR named as certainly shared have since settled in
`stompmodel`: the length newtypes, and the frame values that replaced `Frame`'s rigid
transform. What `stompgeom` holds is therefore the kernel layer — the STEP reader, the
deterministic writer, and the operations that need OpenCASCADE — so read "shared geometry
core" below as that layer rather than as one package holding every shared primitive.

## Context

`stompdrill` reads drill geometry from Illustrator artwork and emits fabrication
artefacts. Two further tools are planned. `stompcollider` seats PCB models inside a
drilled case and reports where they clash. `stompcad` is the user-facing CLI that
drives both, manages the case-model cache, and turns a diagnostic into an
interactive question.

They share primitives. `stompcollider` needs the branded length newtypes of
ADR-0004 exactly as `stompdrill` defines them, needs a rigid transform, and needs
the level-based planar-face extraction that `cad/case.py` uses to find a drilled
face — a PCB's carrier plane is the same problem with a different solid. Without
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
parser.

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

On the writing side, `stompgeom` now owns a document it can **render to bytes**:
`stompgeom.writer.render_step` is the one serialising entry point, returning the
finished STEP payload rather than a path — the scratch file its OCC-backed writer needs
along the way is an implementation detail forced by that kernel's own path-only API, not
part of this function's contract. The fourth verb, **build** — assembling a document
from placed, named, coloured solids — is deliberately **not yet owned**. ADR-0008's own
rule is why: the interface grows when a real second consumer arrives, and today the only
caller of that shape is a test fixture. The builder is expected, not omitted: plan 3's
first geometry ticket promotes that fixture's construction into `stompgeom` once
`stompcollider` gives it a real caller to be designed against.

The risk carried is that `stompgeom` accumulates whatever is convenient rather than
what is universal. `Frame` is the live example: it is a rigid transform, which
is universal, wrapped in a meaning — Y-up, originating at the reference-outline
centre — that belongs to panel artwork and says nothing about a PCB. Primitives
of that shape are split, not moved wholesale, and the test is whether the
`stompgeom` type can be described without naming a panel.
