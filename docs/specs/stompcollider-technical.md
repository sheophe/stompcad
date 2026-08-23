# stompcollider — technical specification

**Status:** accepted, unimplemented.

Decides the libraries, interfaces and internal architecture that
[`docs/specs/stompcollider.md`](stompcollider.md) deliberately left open. That document
remains the authority on *what* `stompcollider` is responsible for; where the two
disagree, it wins and this one is wrong.

Governed by [ADR-0009](../adr/0009-shared-model-package-and-dependency-order.md)
for package boundaries, [ADR-0003](../adr/0003-quantisation-boundary-and-ordering.md)
for the canonicalisation boundary, and
[ADR-0001](../adr/0001-pipeline-and-emitter-adapters.md) for the pipeline and
emitter shape.

## Inputs and outputs

`stompcollider` takes a **drilled** case model. It never drills one, and it never
synthesises one. This mirrors `stompdrill`, which takes an **undrilled** case model
and produces the drilled one (Figure 1).

```
      artwork (.ai)              undrilled case model (.stp)
            │                                │
            ▼                                ▼
   ┌─────────────────────────────────────────────────────┐
   │                       stompdrill                       │
   └─────────────────────────────────────────────────────┘
            │                                │
            ▼                                ▼
    drill document (.json)          drilled case model (.stp)
            │                                │
            │      board models (.stp …)     │
            │                │               │
            ▼                ▼               ▼
   ┌─────────────────────────────────────────────────────┐
   │                     stompcollider                      │
   └─────────────────────────────────────────────────────┘
            │                                │
            ▼                                ▼
     dock report (.json)            assembly model (.stp)
```

*Figure 1: the two tools' inputs and outputs. The drilled case model is an
input to `stompcollider` on equal footing with the boards and the drill document;
all three are required.*

Three required inputs, and the reason each is an input rather than something
derived:

| Input | Why it is given, not recovered |
| --- | --- |
| Drill document (`stompcad-drill-data` v6) | Those holes were cut *from* exact nanometre values. Reading them back out of the drilled geometry could only lose precision or fail. It also carries the face frame `stompdrill` cut in — see ADR-0009. |
| Drilled case model | `stompcollider` verifies clearance against real geometry; it has no catalogue from which to invent a casting, and the pre-spec forbids synthesising one. |
| Board models | KiCad emits solids. Nothing upstream knows a board's protrusion axes, so this side must be measured. |

Two outputs, and the split matters: **the report is the contract, the assembly
model is a view of it**. Both are emitters over one value, and shared facts are
computed once before the fan-out.

## Internal architecture

Deliberately `stompdrill`'s shape (Figure 2), with one honest difference named
below.

```
  board models  ──┐
  case model    ──┼──►  BoardSource  ──►  RawBoards  ──►  canonicalise()
  drill document──┘                                            │
                                                               ▼
                                                           DockData
                                                               │
                                                               ▼
                                                    Pipeline(Match, Seat)
                                                               │
                                                               ▼
                                                           DockData
                                                               │
                                             ┌─────────────────┴─────────────────┐
                                             ▼                                   ▼
                                       ReportEmitter                     AssemblyEmitter
                                             │                                   │
                                             ▼                                   ▼
                                     dock report (.json)              assembly model (.stp)
```

*Figure 2: `Source → Raw → canonicalise() → Pipeline → Emitter`, the flow
ADR-0001 fixes for `stompdrill`, instantiated for docking.*

**The boundary is `canonicalise()`, not `quantise()`.** It converts measured
millimetre floats to integer nanometres by exact decimal scaling before
representation rounding, exactly as ADR-0003 requires — and it **selects
nothing**, because a board's geometry has no answer set to snap to. Naming it
`quantise` would assert a catalogue that does not exist. The distinction is
worth a word: `stompdrill` compares measurements against enclosure, drill-size and
grid answer sets; `stompcollider` only changes representation.

### Module layout

```
src/stompcollider/
  __init__.py       exports Source, canonicalise, Match, Seat, and the emitters
  model.py          DockData, Board, Component, Protrusion, Profile,
                    Correspondence, Candidate, Placement, Clash
  designators.py    the panel-reference filter: expression → predicate
  boards.py         substrate identification, contact assignment, board ordinals
  protrude.py       perpendicular-cylinder stacks → axis and profile
  sources/step.py   BoardSource: STEP files and case model → RawBoards
  match.py          Match
  seat.py           Seat
  emitters/report.py, emitters/assembly.py
  cli.py, errors.py
```

Everything above `sources/` and `emitters/` is pure: `Match` and `Seat` operate
on `DockData` and never touch the kernel, so both are testable with hand-built
values.

## Reading boards

### Substrates and components

A solid that XCAF gave a name is a **component**, and that name is its reference
designator; a solid with no name is **substrate geometry**. This keys on the
*presence* of component identity, never on what a name says: KiCad writes a name
per footprint occurrence, and a board body is not a footprint. It is
threshold-free, and it matched `fixtures/tar-pcb.stp` 41 to 2 without tuning.

A file with no unnamed solid is refused as `no-substrate`. It is not guessed at.

### Grouping

A component belongs to the substrate it **contacts**: among substrates whose
footprint it overlaps in projection along the board normal, the nearest along
that normal. Overlap in projection implies a difference along the normal —
boards may overlap in two dimensions but never in three — so the ordering is
total and needs no threshold.

Board count and per-board composition are reported. A caller expecting one board
learns it passed two, as `multiple-boards`.

### Board ordinals

Boards carry no usable name; `tar-pcb.stp` labels its substrates `=>[0:1:1:34]`
and `=>[0:1:1:35]`, which are OCC indirection labels and change between exports.
Boards are therefore numbered from 1 by sorting on
`(min x_nm, min y_nm, min z_nm, −footprint area)` in the case's face frame.
The report lists each board's designators beside its ordinal, so a human reading
it can identify one; `--place` and `--pin` address boards by ordinal.

### Carrier planes

A board's **carrier plane** is its substrate's plane, found by `stompgeom.levels()`
— the same coplanar-face grouping `stompdrill` uses on a casting. A substrate is a
slab, so the two largest opposed levels are its faces and neither needs a
holedness judgement. The carrier normal is their shared axis.

## The panel-reference filter

A comma-separated list of terms, evaluated left to right over the set of
designators present, so that a later term overrides an earlier one.

```
    expression  := term ( "," term )*
    term        := [ "!" ] pattern
    pattern     := literal | glob | range
    literal     := IDENT                       D3
    glob        := IDENT with "*" or "?"       RV*, SW?
    range       := IDENT "(" INT ".." INT ")"  D(3..4)
```

A range is inclusive and expands over integers with no zero-padding semantics:
`D(3..4)` is exactly `D3` and `D4`. Globs are `fnmatch` semantics. Surrounding
whitespace is insignificant. Evaluation starts from the empty set; a positive
term adds every present designator it matches, a negated term removes them.

```
    RV*,SW*,D(3..4),!RV5
```

There is no grouping, no boolean operator and no precedence rule — a designator
either survives the last term that mentions it or it does not. The expression is
**required**; `stompcollider` holds no default, because a default would be a
pedal-specific fact compiled into a geometry engine. `stompcad` owns `RV*,SW*`.

An unparseable expression is exit 3, resolved before any file is opened. An
expression that parses but admits nothing is `empty-group`, exit 2, at run time —
the difference between a malformed flag and a flag that does not fit this board.

## Protrusions

Among a component's cylindrical faces, only those whose axis is parallel to the
carrier normal are considered — a cylinder at any other angle cannot pass through
a hole in a flat panel, so admitting one risks an axis that means nothing. This is
correctness, not optimisation, and on the fixture it reduces a footswitch from 534
faces to 124, a potentiometer from 72 to 43, and an ordinary diode from 7 to 2.

Parallelism is tested with `gp_Dir.IsParallel` at `Precision::Angular()` — the
kernel's own declaration of when two directions are the same, not a tolerance
chosen here. Coaxiality likewise uses `Precision::Confusion()` on the axis
position.

The admitted cylinder reaching furthest along the outward direction fixes the
**axis**. Every cylinder coaxial with it forms the **stack**.

A protrusion is a **radius-versus-depth profile**, not a diameter. Each cylinder
in the stack contributes `(radius_nm, depth_from_tip_min_nm, depth_from_tip_max_nm)`,
and the profile at depth *d* is the greatest radius of any cylinder covering *d*.
The **insertion depth** through a hole of radius *r* is the least *d* at which the
profile exceeds *r*.

The rule was validated against every panel-reference part on the fixture, first
attempt, without tuning:

| Part | Profile | Through |
| --- | --- | --- |
| 5 mm LED | 4.9 to the flange, then 5.8 | ⌀5 seats on the flange; ⌀6 passes fully |
| Potentiometer | 6.35 shaft, 6.188 bushing, then the body | ⌀7 inserts to the body |
| 3PDT footswitch | 10 tip, 8 shaft, 12 bush | ⌀12, full depth |

A largest-radius rule would name the LED's flange — precisely the feature that
must *not* pass through. **Match reads only the axis; the profile is Seat's.**

A component the filter admits but which yields no admissible cylinder has no axis
and cannot pair. It is reported as `unmatched-part`, the same finding as a part
whose axis pairs with no hole.

## Match

For each board, and for each of its two faces:

1. Project every admitted protrusion's axis into the face frame's plane.
2. Pair each axis with a hole whose centre lies within the **recognition
   tolerance**. That tolerance is half the drill grid pitch — derived, not
   chosen: holes are quantised to that grid, so two distinct holes are at least
   one pitch apart, and any offset below half a pitch identifies exactly one
   hole. `stompcollider` receives it as a length and never learns a lattice exists.
3. Two protrusions within tolerance of the same hole is `ambiguous-pairing`,
   exit 2. Two parts cannot occupy one hole, and choosing between them would be
   the weighting the pre-spec refuses.

**Pairing is a predicate, not a score.** The face with strictly more pairings is
the face that points at the panel. Equal non-zero counts on both faces is
`both-faced-group`; zero on both is `no-correspondence`. Neither is broken by a
majority or a fallback.

Recognition is deliberately more permissive than fit. Whether a shaft physically
passes through a hole is Seat's question, and asking it here would make the test
unsatisfiable: a 3PDT bush measures 12.000 mm into a 12.000 mm hole.

### Candidates

Each unordered pair of correspondences implies exactly one placement. For a pair
`{(p₁,h₁), (p₂,h₂)}`, require `| p₁p₂ | = | h₁h₂ |` within twice the recognition
tolerance — two independent recognition errors — then solve the unique rigid
planar transform taking `p₁→h₁` and `p₂→h₂`. A transform that fits only under
reflection is rejected: a board cannot be mirrored in its own plane.

Every other correspondence is then tested against that transform and kept when it
lands within tolerance.

**A candidate is identified by the set of correspondences it validates.** Two
seed pairs validating the same set are the same candidate. This deduplication is
exact and discrete — no rounding of x, y or θ, and therefore no angular
resolution to choose. The transform for a distinct candidate is computed from its
two most widely separated corresponded protrusions, which is the best-conditioned
choice available, with ties broken by designator order.

Fewer than two correspondences is `under-constrained-board`: one leaves the board
free to turn about that point. Two is the rank of a rigid planar transform, not a
threshold. An under-constrained board is placed explicitly through `--place` and
otherwise held at its exported position, and is treated as a fixed body that
others must avoid.

## Seat

### What a placement is

A placement is a single rigid transform, composed in one fixed order:

1. Rotate the board so its carrier normal is antiparallel to the face frame's
   outward normal on the panel-facing side Match selected — the board is turned
   to face the panel.
2. Rotate by θ about that normal, and translate by `(x, y)` in the face frame.
3. Translate by `z` along the normal, which seating fixes.

Steps 1 and 2 are exact consequences of Match; only `z` is Seat's to compute.
Because a board is rigid and its carrier plane is parallel to the drilled face
by construction, no other degree of freedom exists.

### Seating depth

With `(x, y, θ)` fixed, seating is one-dimensional and closed-form. Travel along
the face normal is

```
    travel = min over correspondences of ( insertion depth of the profile
                                           through that hole's radius )
```

measured against the inner surface of the drilled plate, which the face frame
registers. **No kernel query and no descent.** A shaft ends up centred in its
hole because that is the only configuration in which the board seats, not because
anything was told what a shaft is.

Seating depth is fixed by the panel-reference correspondences **alone**. Anything
else that would foul at that depth is a clash to report, not a constraint to yield
to — which is what "collisions left in place" already says about the emitted
model. This resolves the pre-spec's open question about cases where seating is
more than a single query: the set is empty, because the question was mis-framed.
A standoff is not a seating constraint; it is a solid that clashes.

### Clashes

Each board is checked against **the whole of the rest of the assembly**: every
solid of the case model, and every other board. No part of the enclosure is
privileged or exempt — walls, corner bosses, the floor and the lid are all simply
geometry, and so is a neighbouring board. The rule is stated this way
deliberately: an enumerated list of things worth checking would eventually omit
one, and the omission would look like a passing result.

Bounding boxes filter pairs; a surviving pair gets an exact
`BRepAlgoAPI_Common`. A clash is that common region's axis-aligned bounding box
in the case's face frame. **Depth is its least extent and direction is that
axis** — defined as the least distance along a face-frame axis that would clear
the overlap. It is an exact answer to that definition and an honest upper bound
on true penetration depth, it needs no meshing, and it degrades sensibly: a board
2 mm too long reports 2 mm along the long axis; a lid 3 mm too shallow reports
3 mm along the normal.

A clash against the lid is **named as such** in the report. That is emphasis in
the wording, not a narrowing of the check.

### Contact is not a clash, and needs no threshold

A 12.000 mm bush meets a 12.000 mm hole exactly, so their common region's extents
lie at the kernel's modelling tolerance and round to **0 nm** under ADR-0003's
canonical representation. Zero-nanometre depth is contact. Anything the canonical
representation cannot express is not a fact, so the resolution is the test and no
threshold is introduced.

**This claim must be verified, not assumed.** The implementation carries a test
that seats `tar-pcb.stp`'s footswitches through nominal ⌀12 holes and asserts the
measured depth rounds to zero. If OCC's boolean returns more than that, the fix is
to state the kernel's actual guarantee — not to add a tolerance.

Where a corresponded protrusion's profile exactly equals its hole radius, the
report records `zero-clearance` at INFO. It is an interference fit by design, and
it is why a fit report is optimistic wherever a thread is involved: a
potentiometer's M7 bushing is modelled at its 6.188 mm thread minor diameter, not
the 7 mm the real part occupies. Model fidelity is the caller's responsibility;
naming where the report inherits it is not.

### Ranking

Placements are ranked lexicographically ascending on

```
    (clash count, total clash volume, greatest clash depth, θ, x_nm, y_nm)
```

Clean placements sort first; a genuinely symmetric pair falls through to the
transform, which is exact comparison rather than a measured quantity, so the
order never depends on kernel round-off. Rank is a reported field, not a verdict:
**every** distinct placement is returned. A symmetric hole pattern genuinely
admits two seatings, and handing back one silently is how a pedal gets assembled
mirror-imaged.

### Several boards

Each board is ranked against the case **alone**. The assembly is then formed from
each board's rank-1 placement, and inter-board clashes are computed once on that
assembly.

Board-level ranking is therefore independent and order-free — determinism does not
rest on a traversal order, and the Cartesian product of every board's candidates
never appears. This keeps the pre-spec's meaning of "sequential": one board at a
time, never jointly optimised. A board with more than one placement is reported as
`ambiguous-placement` so `stompcad` can offer a picker, and a caller pins one with
`--pin N=RANK` on re-run.

Inter-board clashes are **reported, never compromised away**. A hole pattern is a
hard constraint, so two boards that fight is a fault in the pedal, and the useful
output says where and by how much.

## Emitters

Two fixed outputs, no registry. `stompdrill`'s registry earns its keep across six
formats where a seventh is expected; here it would be ceremony around a
two-element set, and it would flatten a distinction the pre-spec draws
deliberately.

### The report

`stompcollider-dock-report` v1. Integer nanometres, a `format`/`version` header, and
diagnostics matched by `code` — the same conventions as the drill document.

```json
{"format": "stompcollider-dock-report", "version": 1, "units": "nm",
 "case": {"part": "1590BB", "face": "box", "model": "1590BB.stp"},
 "boards": [
   {"ordinal": 1,
    "designators": ["C1", "…", "RV5"],
    "extent_nm": [106500000, 53750000, 1510000],
    "panel_face": "-w",
    "placements": [
      {"rank": 1,
       "x_nm": 0, "y_nm": 0, "z_nm": -28085000, "theta_deg": 180.0,
       "correspondence": [
         {"designator": "RV3", "hole_index": 4,
          "hole_xy_nm": [12400000, 30000000],
          "insertion_nm": 9000000, "offset_nm": 150000}],
       "clashes": [
         {"with": "LID", "kind": "case",
          "bbox_nm": [-4000000, 20000000, -2100000, 4000000, 26000000, 0],
          "depth_nm": 2100000, "axis": "w", "volume_nm3": 42000000000000000000}]}]}],
 "unmatched_holes": [7, 9],
 "diagnostics": [
   {"severity": "warning", "code": "unmatched-part",
    "message": "RV5 has no hole", "data": {"designator": "RV5"}}]}
```

`case.face` is echoed from the drill document, never chosen here.
`panel_face` is which side of the carrier plane points at the panel, as a sign
along the board's own carrier normal in the file it was exported from — `-n` or
`+n`. Angles are serialised at six decimal places, which is the only float in
the document and the only place byte-identity depends on formatting.

`offset_nm` is the recognition miss for that correspondence. It is a field, not a
message, because it is what turns "no valid placement" into "RV3 is 0.15 mm off
and will bind" — the answer the tool exists to give when a board nearly fits.

`with` names a case solid by its STEP product name, or another board as
`board:2`; `kind` is `case` or `board`, so a consumer never parses that string.

Holes with no part are normal per board — each board covers a subset by
construction — so `unmatched_holes` is reported **once across the assembly**,
where a leftover hole means either panel-mounted hardware on no PCB or a board
missing from the run.

### The assembly model

The case model's solids plus each board's solids, transformed by the placement
chosen for that board, written through `stompgeom`'s deterministic STEP writer so
names and colours survive and volatile OCC identifiers do not reach the file.
**Collisions are left in place.** Docking rules are respected, interference is
not resolved away, and seeing the clash is the point.

## Diagnostics and exit codes

The workspace contract from ADR-0009: `0` clean, `1` findings, `2` error, `3`
usage or IO. Severity maps as `stompdrill`'s does — INFO to 0, WARNING to 1, ERROR
to 2 — through `stompmodel`'s shared reduction.

| Code | Severity | Meaning |
| --- | --- | --- |
| `no-correspondence` | ERROR | Wrong board for this case; nothing to show |
| `empty-group` | ERROR | The filter parsed but admitted nothing — set the flag |
| `both-faced-group` | ERROR | Equal pairings on both faces; the side must be declared |
| `ambiguous-pairing` | ERROR | Two protrusions within tolerance of one hole |
| `no-substrate` | ERROR | Every solid is named; no board body to group onto |
| `unreadable-board` | ERROR | Not a readable STEP file, or no solids |
| `degenerate-geometry` | ERROR | A boolean or profile could not be evaluated |
| `wrong-case-model` | ERROR | The model is not the part the drill document names |
| `clash` | WARNING | Two solids occupy the same space in a completed placement |
| `unmatched-part` | WARNING | An admitted part with no hole |
| `unmatched-hole` | WARNING | A hole no board covers |
| `multiple-boards` | WARNING | The input held more boards than one file suggests |
| `under-constrained-board` | WARNING | Fewer than two correspondences |
| `ambiguous-placement` | WARNING | More than one distinct placement survives |
| `zero-clearance` | INFO | A profile exactly equals its hole radius |

**Matching and fitting fail differently, and only one is an error.** A matched
board whose every candidate clashes is the *right* board with a misaligned design:
exit 1, every candidate reported and drawn. Withholding the model there would
defeat the tool, because that is a main reason to run it.

`multiple-boards` is a WARNING rather than INFO on purpose: you asked that a
caller expecting one board learn it passed two, and an exit code of 0 would not
tell them.

Any error withholds every requested artefact, as `stompdrill` does.

## Command line

```
stompcollider DRILL.json BOARD.stp [BOARD.stp …]
    --case-model PATH          the drilled case model
    --panel-reference EXPR     required; no default
    --match-tolerance MM       required; half the drill grid pitch
    --place N=X,Y,THETA        repeatable; an under-constrained board
    --pin N=RANK               repeatable; choose among ranked placements
    --report PATH
    --assembly PATH
    -v
```

Every flag resolves before any file is opened, so an unparseable filter
expression, a malformed `--place`, or a `--pin` naming a board ordinal that
cannot exist is exit 3 rather than a diagnostic.

There is no `--case-face`: the drill document carries the face frame `stompdrill`
cut in, so `stompcollider` reads the registration instead of choosing a face. It
checks against every solid of the case model and never selects one.

`wrong-case-model` compares the drill document's declared enclosure part against
the model's own product name — the same check `stompdrill` already makes.

## Determinism

Identical inputs produce a geometrically and byte-identical result. This binds
algorithm choice, not merely output.

- **No iterative numerical step anywhere.** Every stage is an enumeration or a
  closed-form query. Correspondence is enumerated, rotation is implied rather
  than swept, seating is arithmetic on profiles, and clash depth is a bounding
  box of an exact boolean.
- **No noise source and no stochastic search.**
- **No hash-ordered iteration.** Every traversal is over an explicitly sorted
  sequence; solids sort by designator, boards by ordinal, correspondences by
  designator, clashes by `(kind, with, depth_nm)`.
- **No dependence on input order.** Two files listing the same solids in a
  different order produce byte-identical artefacts, as ADR-0006 requires of
  `stompdrill`.
- Volatile OCC identifiers are normalised by `stompgeom`'s writer, which already
  solved this for `stompdrill`.

## Testing

TDD throughout, following the repository's existing rules.

- `Match` and `Seat` are pure and are tested with hand-built `DockData`. No
  kernel is involved, and no fixture file is read.
- **Property tests:** filter parse-and-apply idempotence; profile monotonicity in
  depth; insertion depth non-increasing as hole radius decreases; candidate
  deduplication idempotence; placement ranking is a total order.
- Fixtures break accidental equality: boards are numbered out of tuple order and
  correspondences are stored unsorted, so a test only passes an emitter that
  reads the ordering the model states rather than recomputing one from list
  position.
- **Kernel-backed tests are opt-in behind `--boards`**, mirroring `--hammond`,
  and run against `fixtures/tar-pcb.stp`. Coverage for `sources/` and
  `emitters/assembly.py` is measured under that command, not the default one.
- Cross-artefact claims are asserted by parsing both emitted artefacts and
  comparing what they say about one assembly, as
  `packages/stompdrill/tests/test_drawing_agreement.py` does today.
- The contact-is-not-a-clash claim above is a named test, not an assumption.
- Coverage targets match the workspace: 90% overall, 100% for `Match`, `Seat`
  and the emitters.

## Order of work

**Three implementation plans, not one**, written and executed in order. This is
a deliberate departure from the usual one-spec-one-plan shape, so the reasoning
is recorded rather than left to be rediscovered.

| Plan | Contents | Done when |
| --- | --- | --- |
| 1 — `stompmodel` | lengths, `DrillData` and its members, diagnostics, the JSON codec plus the reader it never had, and the generic `Stage[T]` / `Pipeline[T]` / `Emitter[T]` contracts | done — 3af2bd9 |
| 2 — `stompgeom` | the STEP reader, the deterministic writer with its OCC normalisation, and the `CoordinateFrame` / `FaceFrame` split | done — 277ac8d |
| 3 — `stompcollider` | everything this document specifies, built test-first | its own suite, and the cross-artefact agreement test |

**Why three.** Plans 1 and 2 succeed when *nothing observable changes*; plan 3
succeeds when new behaviour appears. One plan would interleave "prove nothing
moved" tasks with "build a thing" tasks, and a reviewer applies a different
rubric to each. They are also verified by different instruments — the
extractions borrow a suite that already exists, the build brings its own — and
each extraction leaves the repository better on its own, which is the test for
whether work deserves its own plan.

**Write each plan after executing the one before it.** The extractions will
teach us something about the boundary, and a plan written before that lesson is
one we would revise.

**`levels()` moves last, inside plan 3.** ADR-0009 places it in `stompgeom` and
that is where it ends up, but it is deliberately not part of the upfront
extraction. Grouping coplanar faces is the strongest sharing candidate and the
one whose interface is least obvious: `find_faces` currently returns a
case-shaped plate with an inner level, a position and a thickness, where
carrier-plane detection wants levels and holedness. Cutting that seam in plan 2
would mean designing it with no second consumer in the room. So plan 3 extracts
it as a task placed immediately after the carrier-plane code that consumes it —
which is what ADR-0008 means by an interface discovered rather than invented.

`stompdrill`'s suite is the instrument for the first two plans: a move that
breaks something says so immediately, which is the whole reason ADR-0008
extracts before the new tools rather than after.

**The kernel document builder promotes on plan 3's first geometry ticket, not
before.** ADR-0008 defers `stompgeom` owning "build" — assembling a document
from placed, named, coloured solids — because today's only caller of that
shape is a test fixture, not a real second consumer, so the interface is not
yet designable. Plan 3's first geometry ticket is what supplies one: it
promotes the existing test-only builder into `stompgeom` with `placement` and
`colour` parameters, and the solid value gains whatever reading half that
caller turns out to need. The assembly emitter must not construct kernel
documents itself; it calls the promoted builder.

**`fixtures/tar-pcb.stp` sits at the repository root until plan 3.** Plan 1's
bulk move swept it into `stompdrill`, where no test reads it and mutmut copied
it into every survey. Plan 3 homes it in `stompcollider`'s own `tests/fixtures/`
alongside the first test that opens it; the root is where a fixture with no
member waits, not where one lives.

## Not decided here

- **Recovering a hole pattern from a case's own geometry.** Deferred, not
  forbidden. A future extractor is simply another producer of the drill document.
- **Side-mounted jacks and multi-face drilling.** A protrusion carries its axis
  and a hole its plane, so pairing generalises without rework. That is a change
  to `stompdrill`'s contract before it is one to `stompcollider`'s.
- **Anything flexible.** Harnesses and ribbon cables are excluded from the model
  entirely; nothing represents a flexible part and no rule may assume one
  connects anything.
