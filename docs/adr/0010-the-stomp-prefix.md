# ADR-0010: The `stomp` prefix

**Status:** Accepted

## Context

Every package was prefixed `ai`, which had several possible readings:

- Adobe Illustrator, the format `aidrill` read. The source interface could also
  support PDF or SVG, so the name tied the tool to one input format.
- Artificial intelligence, because an agent wrote most of the code. That says
  little about what the tool does.
- A brand, although none had been established.

At the time of this decision, five packages were planned and only `aidrill`
existed. Renaming it before extracting `stompmodel` and `stompgeom` limited the
number of imports, paths and documents to change.

## Decision

Use the prefix `stomp`, after the stompboxes these tools help build.

| Package | Contents |
| --- | --- |
| `stompmodel` | lengths, `DrillData`, diagnostics, pipeline contracts and frame values |
| `stompgeom` | STEP reader and writer, kernel geometry, level analysis |
| `stompdrill` | artwork in, fabrication artefacts out |
| `stompcollider` | docking and collision |
| `stompcad` | the composing CLI |

The original package table placed coordinate frames in `stompgeom`.
ADR-0009's amendment assigns the frame values to `stompmodel`, as shown here.

The repository is named `stompcad`, following ADR-0008. The planned user-facing
command is `stomp`:

```
    stomp drill tar.ai
    stomp dock tar.ai
```

`stomp` is reserved for the command and is never a package identifier. Console
scripts can have a different name from their distribution. Project identifiers
in code, paths and emitted artefacts use `stompcad`.

The `ai` in `sources/ai_pdf.py` and `AiPdfSource` remains: it identifies the
Adobe Illustrator PDF-compatible stream those names represent. Another vector
source would sit beside that module.

Two emitted identifiers change with the prefix:

- The drill document's `format` becomes `stompcad-drill-data`. ADR-0009 moves
  the document to `stompmodel`, so `stompdrill-drill-data` would incorrectly tie
  it to one producer.
- The STEP writer's product-name prefix becomes `stompcad`. `_PRODUCT_NAME`
  defines it once for both the writer and the pattern that renumbers its
  appended counter. Separate spellings could drift during a rename and leave
  volatile identifiers in otherwise valid output.

OCC's STEP translator uses that prefix for any shape without a usable XCAF name.
The counter form depends on where the shape enters the transfer:

- A top-level free shape gets a dotless counter: `stompcad <n>`.
- A component inside an XCAF assembly gets a dotted counter:
  `stompcad <n>.<m>`. The assembly keeps its own product name; this does not add
  a wrapper around it.

`stompgeom.build.build_document` adds each solid as a free shape, so documents
assembled by this workspace use the dotless form. Supplied case assemblies and
test fixtures can produce the dotted form. Both are renumbered in file order
to fresh dotless names, `stompcad <k>`. Multiple unnamed shapes remain distinct
in the resulting bytes.

## Rationale

### Name the domain the tools serve

A neutral name was considered. `kerf`, the machinist's term for material removed
by a cut, was initially preferred because it was independent of input format.
`stomp` was chosen because the assembled system is specific to pedals.
`stompdrill` carries a Hammond 1590 catalogue, and `stompcollider`'s Match phase
pairs protruding controls with holes in a flat drilled face. These are useful
pedal-building assumptions, beyond general machining geometry.

The earlier claim that no package knows about pedals is corrected here. The
rule is that only the parts requiring domain knowledge should contain it, and
that knowledge must arrive as data or a caller-supplied parameter wherever
possible.

`stompcollider` therefore has no component taxonomy or part library, does not
need to know what a potentiometer does, and receives its panel-reference group
from the caller. It does assume boards mount through a flat face using
cylindrical protrusions. The supporting rigid transforms, radius-versus-depth
profiles and boolean clash measurements remain general geometric operations.

### Rename before extracting the packages

Only `aidrill` existed when this decision was made. Its rename was mechanical
and verifiable with the existing suite of 1248 tests. Deferring it would add
packages and documentation to the migration.

## Consequences

Imports change throughout, and `src/aidrill/` becomes `src/stompdrill/`. The
console script remains `stompdrill` until `stompcad` exists to provide `stomp`.

The drill document's `format` string and the STEP product-name prefix change
emitted bytes deliberately. ADR-0008's requirement for byte identity across the
`stompgeom` extraction is measured after this rename commit. No other emitted
bytes change: positions, diameters, ordering and colour slots remain identical.

The case-model cache moves from `~/.cache/aidrill/cases/` to
`~/.cache/stompcad/cases/`. Previously downloaded models are fetched again once.
