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

**stompcad**:
The user-facing command-line tool. Drives `stompdrill` and `stompcollider` as
libraries, manages the case model cache, and turns a diagnostic into an
interactive question.
_Avoid_: the CLI, the frontend, the driver

**stompcollider**:
The docking and collision engine. Seats boards inside a drilled case and
reports where they clash. Domain-specific about how a board meets a panel;
carries no component identity.
_Avoid_: the solver, the physics engine

**stompdrill**:
Artwork in, fabrication artefacts out. Owns every decision about where a hole
goes, though not the type the answer is carried in.
_Avoid_: the parser, the extractor

**stompgeom**:
The kernel layer shared by the others — the STEP reader and writer, coordinate
frames, and the geometry operations more than one package needs.
_Avoid_: core, common, utils

**stompmodel**:
The values every package exchanges — lengths, the drill data and its JSON,
diagnostics, and the pipeline contracts. Pure Python; no kernel, no parser.
_Avoid_: types, schema, dto

## Geometry

**Canonicalisation**:
Converting measured floats to integer nanometres, changing representation and
nothing else.
_Avoid_: normalisation, conversion
_See also_: Quantisation, which also snaps to an answer set. Where there is no
answer set there is no quantisation, only this.

**Coordinate frame**:
An origin and a right-handed basis. Carries no meaning about what it registers —
that is the point. `CoordinateFrame` in `stompgeom`.
_Avoid_: frame (this repo has used the word for three unrelated things), axes,
basis
_See also_: Face frame, which adds the meaning.

## Panel and drilling

**Answer set**:
A finite set of permitted values a measurement is snapped to — a drill
standard, a grid pitch, or the enclosure catalogue.
_Avoid_: lookup table, allowed values
_See also_: Quantisation. The sets are not interchangeable with one another.

**Drill document**:
The serialised form of one drill run: the holes, the frame they were cut in, and
the enclosure they were cut for. What passes from `stompdrill` to `stompcollider`.
_Avoid_: drill data (that is the type), hole pattern, drill file

**Drill layer**:
The Illustrator layer whose circles are holes to be drilled.
_Avoid_: hole layer, cut layer

**Quantisation**:
Replacing measured floats with members of an answer set, producing canonical
integer-nanometre data.
_Avoid_: rounding
_See also_: Answer set. Snapping is one step within quantisation, not a synonym
for it; canonicalisation is what remains when no answer set exists.

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
A STEP model of a real enclosure. Never synthesised: one is supplied undrilled,
and `stompdrill` emits the drilled one that `stompcollider` docks into.
_Avoid_: enclosure model, case file, box model

**Drilled face**:
The face of the case that holes are cut through. Told to a tool, never guessed
when a caller already knows it.
_Avoid_: panel face, front face, working face

**Face frame**:
The drilled face's registration: a coordinate frame whose third axis is that
face's outward normal. `FaceFrame` in `stompgeom`.
_Avoid_: frame, drill frame, case frame
_See also_: Coordinate frame, Drilled face.

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

**Board**:
One substrate and the components mounted to it, treated as a single rigid body.
Several may arrive in one file, and each docks independently.
_Avoid_: PCB, card, module
_See also_: Substrate, which is the bare body alone.

**Carrier plane**:
The plane of a board's substrate. A placement keeps it parallel to the drilled
face.
_Avoid_: board plane, PCB surface
_See also_: Substrate, whose plane this is; Drilled face.

**Clash**:
Two solids occupying the same space in a completed placement. A finding to be
reported and shown, never a reason to compromise a placement.
_Avoid_: interference, overlap
_See also_: the engine *collides*; what it finds is a clash.

**Correspondence**:
One protruding element paired with one hole. Match's primary output, and what
lets the report name a part rather than a proximity.
_Avoid_: pairing, mapping, assignment
_See also_: Placement, which a set of correspondences implies.

**Docking**:
Determining where each board sits inside a drilled case. Two phases, Match then
Seat.
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

**Match**:
The first docking phase, and a question: can this board dock into this case at
all, judging by the hole pattern? Someone holding two parts up and deciding
whether they are the same pattern.
_Avoid_: stage A, alignment, registration
_See also_: Seat. Match is deliberately more permissive than Seat — a board that
nearly fits must still be recognised, so that Seat can report by how much it
misses.

**Panel-reference group**:
The components whose reference designators mark them as user-facing hardware.
Declares which face of a board points at the panel. Enumerated per project;
`stompcad` owns the `RV*,SW*` default, and `stompcollider` holds none.
_Avoid_: panel parts, through-hole group, controls
_See also_: Protruding element, which is geometric; this is declared.

**Placement**:
One rigid transform seating a board in the case: which face it presents to the
panel, then x, y, z and rotation about the carrier plane's normal. A docking run
may yield several.
_Avoid_: position, pose, solution
_See also_: Docking.

**Profile**:
A protruding element's radius against depth from its tip. Not a diameter: the
depth at which the profile first exceeds a hole's radius is how far it inserts.
_Avoid_: diameter, shaft size, envelope
_See also_: Protruding element.

**Protruding element**:
A solid standing proud of the carrier plane — a potentiometer, jack,
footswitch, LED. Recognised by geometry, never by component identity.
_Avoid_: component, part, through-panel hardware
_See also_: Panel-reference group, which is declared where this is geometric;
Profile, which is what a protruding element measures as.

**Seat**:
The second docking phase, and a question: how exactly do these boards sit, and
does anything collide? Someone assembling the pedal, already expecting each
individual board to fit.
_Avoid_: stage B, settling, placement solving
_See also_: Match. Because Seat runs only after a pattern matched, its value is
mostly in everything a board can foul once it is in the case, not single-board
fit.

**Substrate**:
A board's bare body, the solid its components are mounted to. Recognised by
carrying no component identity, never by name.
_Avoid_: PCB, panel
_See also_: Board, which is this plus everything mounted to it; Carrier plane,
which is this one's plane.
