# Glossary

The vocabulary of guitar-pedal enclosure fabrication as this workspace uses it:
reading drill geometry from Illustrator artwork, cutting it into a real
enclosure model, and seating the boards that mount through it.

## Scope

**Belongs here.** Terms whose meaning is specific to this domain, or general
words this workspace has narrowed to one meaning. A term earns an entry the
moment two people could reasonably read it two ways.

**Does not belong here.** General programming vocabulary, however heavily used.
Implementation detail of any kind — this is a glossary, not a specification.
The *rules* that govern these terms live in `CLAUDE.md`; the *reasons* they were
chosen live in `docs/adr/`. Neither is restated here.

**Authority.** Where this file and an ADR disagree, the ADR wins and this file
is wrong. Fix it rather than working around it.

## Entry format

```
**Term**:
What it is, in one or two sentences. Never what it does.
_Avoid_: rejected synonyms — words that mean this, which we do not use
_See also_: related terms, where the boundary between them matters
```

Entries are alphabetical within each section. A rejected synonym is not merely
unfashionable: using one in code, prose, a commit message or a test name is a
defect, because it reintroduces the ambiguity the entry exists to remove.

## Packages

**aicad**:
The user-facing command-line tool. Composes the other three, manages the case
model cache, and turns a diagnostic into an interactive question.
_Avoid_: the CLI, the frontend, the driver

**aicollider**:
The docking and collision engine. Seats boards inside a drilled case and
reports where they clash. Knows geometry and nothing about pedals.
_Avoid_: the solver, the physics engine

**aidrill**:
Artwork in, fabrication artefacts out. Owns the drill data and everything
derived from it.
_Avoid_: the parser, the extractor

**aigeom**:
The primitives shared by the others — lengths, rigid transforms, and the
geometry operations more than one package needs.
_Avoid_: core, common, utils

## Panel and drilling

**Answer set**:
A finite set of permitted values a measurement is snapped to — a drill
standard, a grid pitch, or the enclosure catalogue.
_Avoid_: lookup table, allowed values
_See also_: Quantisation. The sets are not interchangeable with one another.

**Drill layer**:
The Illustrator layer whose circles are holes to be drilled.
_Avoid_: hole layer, cut layer

**Quantisation**:
Replacing measured floats with members of an answer set, producing canonical
integer-nanometre data.
_Avoid_: rounding
_See also_: Answer set. Snapping is one step within quantisation, not a synonym
for it.

**Reference outline**:
The largest non-circular path on the reference layer, whose centre is the
origin of the canonical frame.
_Avoid_: bounding box, artboard, MediaBox

**Tool block**:
The contiguous run of holes sharing one drill diameter. Each tool occupies
exactly one.
_Avoid_: tool group, diameter batch

## Enclosure

**Boss**:
A thickened corner column carrying a screw. Confined to its corner; the walls
elsewhere are thin.
_Avoid_: pillar, post
_See also_: a standoff is a separate physical part, not a boss.

**Case model**:
A supplied STEP model of a real enclosure. Never synthesised — only ever read.
_Avoid_: enclosure model, case file, box model

**Drilled face**:
The face of the case that holes are cut through. Told to a tool, never guessed
when a caller already knows it.
_Avoid_: panel face, front face, working face

**Footprint**:
An enclosure's published two-dimensional outline. Identifies a shape, not
necessarily a single part number.
_Avoid_: outline, size

**Lettering**:
Cast text on the enclosure surface. Never an obstruction — pedals drill
straight through it.
_Avoid_: embossing, markings

**Play area**:
The flat, drillable region of the drilled face, inside the draft-angle taper
and clear of the corner bosses.
_Avoid_: usable area, drillable region
_See also_: Boss, Drilled face.

## Boards and docking

**Carrier plane**:
The flat face of a board that defines its plane. A placement keeps it parallel
to the drilled face.
_Avoid_: board plane, substrate, PCB surface
_See also_: Drilled face.

**Charge**:
The attraction term between a hole and a protruding element. Holes carry
negative charge, protruding elements positive; each carries its own direction.
_Avoid_: attractor, affinity, weight
_See also_: Protruding element.

**Clash**:
Two solids occupying the same space in a completed placement. A finding to be
reported and shown, never a reason to compromise a placement.
_Avoid_: interference, overlap
_See also_: the engine *collides*; what it finds is a clash.

**Docking**:
Determining where each board sits inside a drilled case, by minimising the
energy of the charge system.
_Avoid_: mounting, fitting, assembly, placement solving
_See also_: Placement is the result; docking is the act.

**Harness**:
Soldered wire or ribbon joining two boards. Excluded from the model entirely:
nothing represents a flexible part, and boards it joins are docked
independently.
_Avoid_: loom, cabling, flying leads

**Manifest**:
The record beside a project's artwork of how that pedal is built, making a run
reproducible and a re-run quiet.
_Avoid_: config, project file, settings

**Placement**:
One rigid transform seating a board in the case — x, y, z and rotation about
the carrier plane's normal. A docking run may yield several.
_Avoid_: position, pose, solution
_See also_: Docking.

**Protruding element**:
A solid standing proud of the carrier plane — a potentiometer, jack,
footswitch, LED. Recognised by geometry, never by component identity.
_Avoid_: component, part, through-panel hardware
_See also_: Charge.
