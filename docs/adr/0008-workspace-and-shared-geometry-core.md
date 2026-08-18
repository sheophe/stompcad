# ADR-0008: A workspace and a shared geometry core

**Status:** Accepted

## Context

`aidrill` reads drill geometry from Illustrator artwork and emits fabrication
artefacts. Two further tools are planned. `aicollider` seats PCB models inside a
drilled case and reports where they clash. `aicad` is the user-facing CLI that
drives both, manages the case-model cache, and turns a diagnostic into an
interactive question.

They share primitives. `aicollider` needs the branded length newtypes of
ADR-0004 exactly as `aidrill` defines them, needs a rigid transform, and needs
the level-based planar-face extraction that `cad/case.py` uses to find a drilled
face — a PCB's carrier plane is the same problem with a different solid. Without
a decision, each tool grows its own `Nanometre` and the three drift.

The repository is currently the `aidrill` package and nothing else, and is named
after it.

Three structures were available: three separate repositories; one repository
holding every package; or an umbrella repository consuming the others.

## Decision

This repository becomes a workspace and is renamed `aicad`, after the
user-facing tool. It holds four packages:

- `aigeom` — lengths, rigid transforms, and the geometry shared by the rest.
- `aidrill` — unchanged in scope: artwork in, fabrication artefacts out.
- `aicollider` — drilled case and PCB models in, placements and clashes out.
- `aicad` — the CLI that composes them.

Each package must install and pass its own tests **alone**. `aidrill` stays
usable without a collision engine, and `aicollider` without an Illustrator
parser.

`aicad` consumes `aidrill` and `aicollider` as **libraries**, not subprocesses.

`aigeom` is extracted **first**, before either new tool is written, starting
with the length newtypes and the primitives whose sharing is already certain.
It grows as real second consumers appear; its interface is not designed in
advance.

## Rationale

**Why not three repositories.** The seams between these tools will move
constantly in early life. Three repositories make every seam change a
cross-repository version negotiation, paid on every commit, by one maintainer,
for isolation nobody is asking for. One repository keeps those changes atomic.

**Why not let `aicollider` depend on `aidrill`.** It is the cheapest way to
share the primitives and the hardest to defend afterwards: a pure geometry
engine would acquire a dependency on a PDF parser, and the dependency graph
would stop describing anything real. The primitives are not `aidrill`'s by
right — it merely wrote them first.

**Why extract upfront rather than at the second consumer.** The usual argument
against early abstraction is that the second use case is unknown, so the seam is
guessed. That argument is weaker here in one specific way: `aidrill` has a large
test suite, so the extraction is *verifiable* now — a move that breaks something
says so immediately. Deferring the extraction does not make it safer; it makes
it larger, and it invites `aicollider` to define its own `Nanometre` in the
meantime. Extraction is bounded to what is certainly shared, so the interface is
still discovered rather than invented.

**Why "installs alone" is the governing test.** A boundary asserted in prose
erodes. A boundary that must survive `pip install aidrill` in a clean
environment does not: an unjustified dependency stops being a design opinion and
becomes a failing install. ADR-0007's optional `aidrill[step]` extra already
demonstrates the discipline, which is what let a STEP emitter arrive later
without the base tool growing a geometry kernel.

## Consequences

The repository is renamed, and the directory no longer shares a name with the
package it contains.

Documentation becomes multi-context. `CONTEXT-MAP.md` replaces the single root
`CONTEXT.md`, per-package ADR directories become possible alongside the
system-wide one, and `docs/agents/domain.md` — which currently describes a
single-context repository — needs editing. `docs/adr/` keeps its existing
numbering for decisions that span the workspace.

`aidrill` gains a dependency on `aigeom`, and its own modules lose the
primitives that move. Every artefact `aidrill` emits must be byte-identical
across the move; its suite is the instrument that proves it, and the extraction
is not complete until it does.

The risk carried is that `aigeom` accumulates whatever is convenient rather than
what is universal. `Frame` is the live example: it is a rigid transform, which
is universal, wrapped in a meaning — Y-up, originating at the reference-outline
centre — that belongs to panel artwork and says nothing about a PCB. Primitives
of that shape are split, not moved wholesale, and the test is whether the
`aigeom` type can be described without naming a panel.
