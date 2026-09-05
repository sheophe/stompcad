# Glossary

These terms describe reading drill geometry from Illustrator artwork, cutting
holes into an enclosure model and checking how boards fit inside it.

## Packages and tools

**stompcad**:
The name of this project and its proposed command-line orchestrator. The design
calls for an orchestrator that uses `stompdrill` and `stompcollider` as libraries,
manages the case model cache and turns diagnostics into interactive questions.
No orchestration command is implemented in this workspace. The available
commands are `stompdrill` and `stompcollider`; see
[ADR-0008](adr/0008-workspace-and-shared-geometry-core.md) for the orchestration
design.

**stompcollider**:
The tool that docks boards inside a drilled case and reports clashes. Its docking
rules describe how board geometry meets a panel, without assigning meanings to
component types such as potentiometers or switches.

**stompdrill**:
The tool that reads artwork and produces fabrication artefacts. It decides hole
positions and diameters; the shared `DrillData` type carries those decisions.

**stompgeom**:
The shared geometry package, including STEP reading and deterministic writing.
Its operations use the OpenCASCADE kernel. Values that need no kernel belong in
`stompmodel`.

**stompmodel**:
The shared values and contracts: lengths, coordinate frames, drill data and its
JSON representation, diagnostics and pipeline contracts. It is a pure Python
package with no geometry kernel or artwork parser.

## Geometry

**Canonicalisation**:
Converting measured floating-point lengths to integer nanometres. This changes
the representation without selecting a drill size, grid position or other domain
value. Quantisation also selects a value from an answer set.

**Coordinate frame**:
An origin and a right-handed basis, represented by `CoordinateFrame` in
`stompmodel`. The frame itself does not say what it registers. A face frame adds
that meaning for a drilled face.

## Panel and drilling

**Answer set**:
A finite set of permitted values to which a measurement can snap, such as a
drill standard, the positions on a declared grid or the enclosure catalogue.
Each set answers a different question: a grid selects positions, while a drill
standard selects diameters. See Quantisation.

**Containment**:
Whether the whole extent of a hole lies inside a boundary. Leaving the reference
outline produces a warning; leaving the drilled face produces an error. The
second check needs a case model because the artwork outline does not describe
the drilled face.

**Drill document**:
The serialised record of a drill run, including its holes, cutting frame and
registered enclosure. It passes from `stompdrill` to `stompcollider`. `DrillData`
is the in-memory value; the drill document is its JSON representation.

**Drill layer**:
The Illustrator layer whose circles mark the holes to drill.

**Quantisation**:
Selecting values from domain answer sets using measured floating-point lengths,
then producing canonical integer-nanometre data. Snapping is the selection step;
canonicalisation converts the representation. Where no answer set applies, only
canonicalisation is needed.

**Reference outline**:
The largest non-circular path on the reference layer. Its centre is the origin
of the canonical coordinate frame. The artboard and PDF MediaBox do not define
this outline.

**Tool block**:
A contiguous run of holes with the same drill diameter. Each tool has exactly
one block in the drill sequence.

## Enclosure

**Boss**:
A thickened corner column that carries a screw. The enclosure walls away from
these corners are thinner. A standoff is a separate physical part.

**Case model**:
A STEP model of a real enclosure. You supply an undrilled model to `stompdrill`,
which cuts the holes and emits the drilled model used by `stompcollider`. The
tools do not synthesise an enclosure from catalogue dimensions.

**Case registration**:
The record of the case model used to decide a drill document's holes. It combines
the resolved part, drilled face, model filename and face frame in one value,
`CaseRegistration` in `stompmodel`.

**Drilled face**:
The face of the enclosure through which the holes are cut. A caller that knows
which face is being drilled supplies it explicitly.

**Face frame**:
The coordinate frame registered to the drilled face, with its third axis
pointing along that face's outward normal. It is represented by `FaceFrame` in
`stompmodel`.

**Footprint**:
An enclosure's published two-dimensional outline. Several part numbers can share
one footprint, so a matching outline does not always identify a single part.

**Lettering**:
Cast text on an enclosure surface. Clearance checks allow drilling through it
and do not classify it as an obstruction.

**Play area**:
The flat, drillable region of the drilled face, inside the draft-angle taper
and clear of the corner bosses.

## Boards and docking

**Board**:
One substrate and its mounted components, treated as a single rigid body.
Several boards can arrive in one model file, and each has its own docking
placement. The substrate is the bare body alone.

**Carrier plane**:
The plane of a board's substrate. A placement keeps it parallel to the drilled
face.

**Clash**:
Two solids occupying the same space in a completed placement. Clashes are
reported and shown so you can adjust the design. The tool does not deform parts
or shift a seated board to remove them.

**Correspondence**:
One protruding element paired with one hole. Match produces these pairs, which
define candidate placements and let reports identify the part and hole involved.

**Docking**:
Determining where each board sits inside a drilled case. Match recognises the
hole pattern and Seat determines insertion depth; clash checks then report
interference at the resulting placements.

**Harness**:
Soldered wire or ribbon joining boards. Flexible parts are excluded from the
model, so a harness does not constrain the docking of the boards it joins.

**Manifest**:
The proposed record beside a project's artwork describing how the pedal is
built. It is intended to make runs reproducible and retain choices for later
runs. The current tools take their settings through command-line options or
library calls.

**Match**:
The first docking phase, which checks whether a board's protruding elements
match the case's hole pattern. It allows near fits so Seat can report how far a
recognised board falls short. Recognition therefore uses a more permissive test
than seating.

**Panel-reference group**:
The components whose reference designators identify them as hardware facing the
panel. This declaration selects which side of the board faces the drilled
face; protruding elements are then recognised geometrically. The current
`stompcollider` command requires `--panel-reference` and supplies no default.
The proposed design places the pedal-specific `RV*,SW*` default in `stompcad`.

**Placement**:
One rigid transform seating a board in the case: which face points at the panel,
its x, y and z coordinates, and its rotation about the carrier plane's normal.
A docking run can produce several candidate placements.

**Profile**:
A protruding element's radius at each depth from its tip. The first depth where
the profile exceeds a hole's radius predicts insertion depth from the hole
geometry. Actual seating is determined by contact with the enclosure along the
insertion path; the profile prediction is also the reference for reporting
insertion shortfall.

**Protruding element**:
A solid extending beyond the carrier plane, such as a potentiometer, jack,
footswitch or LED. Recognition uses geometry, without needing to know the
component type. Its profile describes radius against depth; membership of the
panel-reference group is a separate declaration.

**Seat**:
The second docking phase, which finds how far a matched board can enter the
case. The board stops at the first enclosure contact along the insertion path.
If the enclosure never touches it, the hole geometry determines the seat.
Subsequent clash checks report interference with the case, lid and other boards.

**Substrate**:
A board's bare body, to which components are mounted. The reader selects solids
without component identity and checks that they have slab geometry. It does not
look for a particular board name. A board includes both this substrate and its
components.
