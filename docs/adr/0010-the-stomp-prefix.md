# ADR-0010: The `stomp` prefix

**Status:** Accepted

## Context

Every package in the workspace was prefixed `ai`, and the prefix means three
different things depending on who reads it:

- **Adobe Illustrator**, the only input format `aidrill` currently read. This is
  the reading the code invites, and it is the one guaranteed to expire — nothing
  in the design ties the drill source to Illustrator, and a PDF or SVG source
  would retire the prefix's meaning the day it landed.
- **Artificial intelligence**, because most of the code was written by an agent.
  True, and irrelevant to anyone using the tool.
- A brand that does not exist.

A prefix that means three things means none of them. With five packages about to
be created and only one written, the rename is cheap now and triples in cost
after `stompmodel` and `stompgeom` are extracted.

## Decision

The prefix is `stomp`, after the stompbox these tools exist to build.

| Package | Contents |
| --- | --- |
| `stompmodel` | lengths, `DrillData`, diagnostics, the pipeline contracts |
| `stompgeom` | STEP reader and writer, coordinate frames, level analysis |
| `stompdrill` | artwork in, fabrication artefacts out |
| `stompcollider` | docking and collision |
| `stompcad` | the composing CLI |

The repository is named `stompcad`, per ADR-0008, and the user-facing command is
`stomp`:

```
    stomp drill tar.ai
    stomp dock tar.ai
```

**`stomp` is a command, never a package identifier.** A console-script name is
not a distribution name, so the bare command is available whatever the
distribution is called — and nothing else takes it. Anything that names the
project in code, in a path, or in an emitted artefact is `stompcad`: it says what
the thing is, where a bare `stomp` says only that it is loud.

**One `ai` survives, and it is the honest one.** `sources/ai_pdf.py` and
`AiPdfSource` read Adobe Illustrator's PDF-compatible stream. There the letters
mean exactly what they say, and a second vector source would sit beside that
module rather than replace it.

Two emitted-artefact identifiers change with the prefix, deliberately:

- the drill document's `format` becomes `stompcad-drill-data`, not
  `stompdrill-drill-data` — ADR-0009 moves the document to `stompmodel`, so
  naming it after the tool that happens to produce it would be wrong;
- the STEP writer's product-name prefix becomes `stompcad`, spelled once as
  `_PRODUCT_NAME` and read by both the writer that sets it and the pattern
  that renumbers the counter appended to it. Written twice, a later rename
  would silence the pattern and leave a volatile identifier in an artefact
  that still looked correct. OCC's STEP translator synthesises a product
  from this prefix for *any* shape reaching it with no usable XCAF name —
  nothing here is a wrapper, and which of two spellings appears depends on
  where that shape sits in the transfer, not on what it is. A top-level free
  shape gets a bare, dotless counter (`stompcad <n>`); a shape reaching the
  translator as a component inside an XCAF assembly gets a dotted one
  (`stompcad <n>.<m>`), because the assembly's own product carries the
  assembly's own name and nothing is wrapped around it. `stompgeom.build.
  build_document` adds every solid as a free shape, so this workspace writes
  the dotless form; the dotted form appears for the assemblies a supplied
  case model, or this package's own test fixtures, build. Both spellings are
  renumbered alike, in file order, to a fresh dotless `stompcad <k>`,
  because a document can hold several nameless shapes and they must stay
  distinguishable from each other in the written bytes.

## Rationale

**Why a product name rather than a neutral one.** Neutral candidates were
considered and one was preferred on paper: `kerf`, a machinist's term for the
material a cut removes, which says nothing that can expire. `stomp` was chosen
over it because the assembled system genuinely is domain-specific, and a neutral
name would misdescribe it. `stompdrill` carries a Hammond 1590 catalogue.
`stompcollider`'s Match phase pairs protruding control elements against holes in
a flat drilled face — a shape that is true of a pedal and not of machined parts
in general. Naming that `kerf` would have been an aspiration, not a description.

**The rule is not "no package knows about pedals".** That claim is false, was
never enforceable, and appears in earlier wording that this ADR corrects. The
rule is that **only the parts that must be domain-specific are**, and that domain
knowledge arrives as data or as a caller-supplied parameter wherever it can
rather than compiled in as a fact.

So `stompcollider` holds no component taxonomy and no part library, does not know
what a potentiometer is for, and receives its panel-reference group from the
caller — while knowing perfectly well that boards mount through a flat face on
cylindrical protrusions, because that is the problem it was built for. The
universal parts underneath — rigid transforms, radius-versus-depth profiles,
boolean clash measurement — are universal because that is the cheapest correct
way to write them, not because the system around them is.

**Why not defer.** `aidrill` is the only package written. Renaming it is
mechanical and its 1248 tests verify it. Every day of delay adds another package
to rename and another document to correct.

## Consequences

Import paths change throughout, `src/aidrill/` becomes `src/stompdrill/`, and the
console script is `stompdrill` until `stompcad` exists to own `stomp`.

**Byte identity is broken once, here, on purpose.** The drill document's `format`
string and the STEP writer's product name both appear in emitted artefacts, so
this rename changes them. ADR-0008's requirement that every artefact survive the
`stompgeom` extraction unchanged is measured *after* this commit, not across it.
No other emitted byte moves: positions, diameters, ordering and colour slots are
untouched.

The cached case-model directory moves from `~/.cache/aidrill/cases/` to
`~/.cache/stompcad/cases/`. Anything already downloaded is re-fetched once.
