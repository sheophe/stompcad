# aidrill

Guitar-pedal enclosure fabrication: reading drill geometry from Illustrator
artwork, cutting it into a real enclosure model, and seating the boards that
mount through it.

This glossary fixes the vocabulary. `CLAUDE.md` states the rules that govern
it, and `docs/adr/` records why they were chosen; neither is restated here.

## Panel and drilling

**Drill layer**:
The Illustrator layer whose circles are holes to be drilled.
_Avoid_: hole layer, cut layer

**Reference outline**:
The largest non-circular path on the reference layer, whose centre is the
origin of the canonical frame.
_Avoid_: bounding box, artboard, MediaBox

**Answer set**:
A finite set of permitted values a measurement is snapped to — a drill
standard, a grid pitch, or the enclosure catalogue. Not interchangeable with
one another.
_Avoid_: lookup table, allowed values

**Quantisation**:
Replacing measured floats with members of an answer set, producing canonical
integer-nanometre data.
_Avoid_: rounding, snapping (snapping is one step within it)

**Tool block**:
The contiguous run of holes sharing one drill diameter. Each tool occupies
exactly one.
_Avoid_: tool group, diameter batch

## Enclosure

**Case model**:
A supplied STEP model of a real enclosure. `aidrill` never synthesises one.
_Avoid_: enclosure model, case file, box model

**Footprint**:
An enclosure's published two-dimensional outline. It identifies a shape, not
necessarily a single part number.
_Avoid_: outline, size

**Drilled face**:
The face of the case that holes are cut through. Told to a tool, never
guessed when a caller already knows it.
_Avoid_: panel face, front face, working face

**Play area**:
The flat, drillable region of the drilled face, inside the draft-angle taper
and clear of the corner bosses.
_Avoid_: usable area, drillable region

**Boss**:
A thickened corner column carrying a screw. Confined to its corner; the walls
elsewhere are thin.
_Avoid_: pillar, post, standoff (a standoff is a separate part)

**Lettering**:
Cast text on the enclosure surface. Never an obstruction — pedals drill
straight through it.
_Avoid_: embossing, markings

## Docking

**Docking**:
Determining where each PCB sits inside a drilled case, by minimising the
energy of the charge system.
_Avoid_: mounting, fitting, placement solving, assembly

**Carrier plane**:
The flat face of a PCB that defines its plane. A board's placement keeps it
parallel to the drilled face.
_Avoid_: board plane, substrate, PCB surface

**Protruding element**:
A solid standing proud of the carrier plane — a potentiometer, jack,
footswitch, LED. Recognised by geometry, never by component identity.
_Avoid_: component, part, through-panel hardware

**Charge**:
The attraction term between a hole and a protruding element. Holes carry
negative charge, protruding elements positive; each carries its own direction.
_Avoid_: attractor, affinity, weight

**Placement**:
One rigid transform seating a PCB in the case — x, y, z and rotation about the
carrier plane's normal. A docking run may yield several.
_Avoid_: position, pose, solution

**Clash**:
Two solids occupying the same space in a completed placement. A finding to be
reported and shown, never a reason to compromise a placement.
_Avoid_: interference, overlap, collision (the *engine* collides; its finding
is a clash)

**Manifest**:
The record beside a project's artwork of how that pedal is built, making a run
reproducible and a re-run quiet.
_Avoid_: config, project file, settings
