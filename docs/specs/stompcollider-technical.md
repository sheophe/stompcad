# stompcollider — technical specification

**Status:** accepted and implemented, on `stompcad-collider` from `9180569`.

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
                                            Pipeline(Match, Seat, Clashes)
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
  __init__.py       exports BoardSource, canonicalise, Match, Seat, Clashes,
                    both emitters, and the Raw* values a source produces
  model.py          DockData, Board, Component, Protrusion, Profile,
                    Correspondence, Placement, Clash, admitting_radius
  raw.py            RawBoards: what a source measured, in millimetre floats
  canonicalise.py   RawBoards → DockData, changing representation only, and
                    board_order: the one statement of how boards are numbered
  designators.py    the panel-reference filter: expression → predicate
  boards.py         substrate identification, carrier frames, contact assignment
  protrude.py       axis from the admitted cylinders, profile from the solid
  sources/step.py   BoardSource: STEP files and case model → RawBoards
  match.py          Match
  seat.py           Seat
  clash.py          Clashes
  emitters/report.py, emitters/assembly.py
  cli.py, errors.py
```

**`Match` and `Seat` are pure**: both fold over `DockData` and never touch the
kernel, so both are testable with hand-built values. That is a claim about
those two stages, not about everything listed above `sources/`. `boards.py`,
`protrude.py` and `clash.py` read geometry, and read it through `stompgeom`
rather than through OCP — `Clashes` is the pipeline's one impure stage.

## Reading boards

### Substrates and components

A solid that XCAF gave a name is a **component**, and that name is its reference
designator; a solid with no name is **substrate geometry**. This keys on the
*presence* of component identity, never on what a name says: KiCad writes a name
per footprint occurrence, and a board body is not a footprint. It is
threshold-free, and it matched `tar-pcb.stp` 41 to 2 without tuning.

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
**axis**. That is all the cylinders decide.

**The profile is the whole solid's radial extent about that axis, not its
cylinders'.** A protrusion is a radius-versus-depth profile: the profile at depth
*d* is the greatest distance from the axis of any material of the component at
that depth. The **insertion depth** through a hole is the least *d* at which the
profile exceeds the hole's radius by more than the fit clearance below.

Deriving the profile from coaxial cylinders alone is withdrawn, and it was the
defect that made every real board seat flush against the panel. What arrests a
through-panel component is almost never a cylinder: a potentiometer is stopped by
its rectangular can, a footswitch by its body, a jack by a shell with no
axis-parallel cylindrical face at all. None of those contributed a step, so every
correspondence reported an unbounded insertion, `Seat` had nothing to seat
against, and both boards of the tar assembly came to rest at `z = 0` — coplanar,
inside the casting wall, with entire component bodies driven through holes far too
small to admit them. The cylinders answer *where the axis is*; only the solid
answers *what will not fit*.

**The radial extent is measured by an exact boolean, never by a mesh.** For a
radius *r*, the material of the solid lying strictly outside a cylinder of that
radius about the axis is `solid − cylinder`, and how far that residue reaches
along the outward direction is where material too wide for *r* begins. This is
`stompgeom.radial.radial_reach`, and it is exact where a triangulation is not:
mesh output varies with the deflection parameters it was built at and with the
kernel's version, which ADR-0006 forbids. Strictness comes free with it —
material lying *on* the cylinder is coincident with the tool and the cut removes
it — so a bush exactly filling its bore reaches nothing and passes.

**The radii probed are the radii this panel's holes admit.** A cut answers one
radius, so the set has to be finite and known before the solid is measured; it
is `{ admitting_radius(d, clearance) : d a hole diameter of this drill
document }`, which is exactly the set `Match` will later query. Every part is
probed at all of them, because which hole a part pairs with is not known until
the board is registered, and the reader is upstream of that. Each answer is
stated as one band of the profile: the material there is *strictly* wider than
the probe, which in whole nanometres is at least one nanometre wider, and that
lower bound is what the band records. The alternative — bounding each face
cylindrically and taking its greatest radius over its whole depth range —
over-approximates wherever a face's radius varies with depth, a cone or a
fillet or a thread flank, and would arrest such a part at the shallow end of
that face rather than where it really binds.

**A protrusion also carries its tip.** ``Protrusion.tip_nm`` is how far the
part's tip stands along the carrier normal in the board's own exported frame.
Every depth in the profile is measured back from that tip while a placement's
``z`` is measured to the board's own origin plane, so seating cannot be computed
without it — see "Seating depth".

### Fit clearance

A hole admits material narrower than itself. Material exactly as wide is the
interesting case, and it is common rather than exceptional: a 3PDT bush measures
12.000 mm into a 12.000 mm hole. Comparison is therefore strict — a profile
exactly equal to its hole radius passes — and equality is reported as
`zero-clearance`, an INFO finding, because a part fitting with nothing to spare is
worth seeing even though it is not a fault.

Strictness alone is not enough, because a modelled bushing need not be drawn at
nominal. On the tar fixture the footswitch bush measures exactly 6.0000 mm on
radius, but the potentiometer's measures 3.5271 — 7.054 mm across, in a hole
drilled to 7.000. Judged strictly it cannot pass, and the board cannot seat.

`--fit-clearance` names how much wider than a part its hole must be, **on
diameter**, as every other size in this tool is stated. It defaults to 0.1 mm,
which is what a builder allows when drilling for a bushing. The flag exists
because how much a part needs is a property of that part rather than a law, not
because its value was tuned.

**How insensitive the default is differs by part, and one of these two parts is
not insensitive at all.** Measured on the fixture, the potentiometer board seats
at -10.885 mm for every clearance from 0.06 mm to 5 mm: its bushing is 0.054 mm
over the hole and the next feature, the can, is 5.6 mm over, so the interval
between them is wide and flat. The footswitch board is not. Its bush crest
measures exactly 6.000 mm on radius, but the modelled M12 thread does not end
there -- the run-out where it meets the body flares to roughly 12.1 mm across,
about a tenth of a millimetre over, and *that* is the next feature rather than
the 25.5 mm body. So the footswitch board's seating moves with the clearance:
-17.715 mm at 0.06, -17.061 at the default 0.1, -16.886 at 0.2, -17.162 at 0.5
and -16.551 at 5 -- not even monotonically, because near a radius the thread
crest reaches exactly, the boolean is deciding tangency. The whole spread is
1.16 mm, and every value in it is within a millimetre of the 17.000 mm the
operator measured by hand, which is why this is worth stating rather than worth
tuning: the residual is bounded by that part's model fidelity, not by this flag.

The rule, restated against every panel-reference part on the fixture:

| Part | What stops it | Through |
| --- | --- | --- |
| 5 mm LED | the flange at 5.8 | ⌀5 seats on the flange; ⌀6 passes fully |
| Potentiometer | 6.35 shaft, 7.054 bushing, then the can at 12.6 | ⌀7 inserts to the can |
| 3PDT footswitch | 10 tip, 12 bush at exactly ⌀12, the thread run-out at about ⌀12.1, then the body at 25.5 | ⌀12 inserts to the run-out |

A largest-radius rule would name the LED's flange — precisely the feature that
must *not* pass through. **Match reads only the axis; the profile is Seat's.**

A component the filter admits but which yields no admissible cylinder has no axis
and cannot pair. It is reported as `unmatched-part`, the same finding as a part
whose axis pairs with no hole.

## Match

**Registration precedes recognition.** A board arrives in the frame its CAD tool
exported it in, and the rigid transform taking that frame onto the panel is the
unknown this section solves for. Until it is solved, no protrusion can be said to
lie near any hole at all, so the transform is found *before* pairing rather than
fitted to pairs afterwards.

An earlier version of this specification had it the other way round: pair each
axis with a hole within the recognition tolerance, then fit a transform to the
pairs that step made. That ordering is circular, and it is withdrawn. It could
only recognise a board already standing in panel coordinates, and no exported
board is: a layout tool places a substrate wherever the design sat on its own
sheet, tens of millimetres from the panel origin and turned by whatever multiple
of a right angle the two tools disagree about. On the tar panel's own boards
every admitted part stands between 6.9 and 23.5 mm from the nearest hole before
registration, and the whole layout is a quarter turn out — against a recognition
tolerance of 0.125 mm. So every real board reached `no-correspondence`, and the
rule was reachable only by a fixture authored in the answer's own coordinates.

For each board:

1. Reduce every admitted protrusion's axis to a two-dimensional coordinate in the
   carrier plane, which is parallel to the drilled face by construction. These
   coordinates are in the *board's own* frame. Their origin and rotation relative
   to the panel are exactly the unknown step 2 solves for, and no step before it
   may compare one against a hole.

2. **Seed a registration from every part pair against every hole pair.** For each
   unordered pair of admitted protrusions `{p₁,p₂}` and each *ordered* pair of
   distinct holes `(h₁,h₂)`, require `| p₁p₂ | = | h₁h₂ |` within twice the
   recognition tolerance — two independent recognition errors — then solve the
   unique rigid planar transform taking `p₁→h₁` and `p₂→h₂`. Both orderings of the
   hole pair are enumerated, because which of the two protrusions goes to which
   hole is itself part of the unknown. Only a proper rotation is solved for: a
   board cannot be mirrored in its own plane, and no reflected hypothesis is
   admissible either — the paragraph below derives the handedness instead of
   searching for it.

   Separation is the only quantity compared before a transform exists, and it is
   the one quantity invariant under that transform. That is what makes seeding
   possible at all: how far apart two points lie is knowable before either
   point's position is.

3. **Recognise under each seeded registration.** Apply the transform to every
   admitted axis and pair it with the hole nearest the result, when that hole
   lies within one recognition tolerance. That tolerance is half the drill grid
   pitch — derived, not chosen: holes are quantised to that grid, so two distinct
   holes are at least one pitch apart, and any offset below half a pitch
   identifies exactly one hole. The command line derives it from the pitch the
   drill document itself records, so nobody hand-computes a halving the document
   already determines; `--match-tolerance` overrides it, and a document recording
   no usable pitch is a usage failure naming that flag rather than a guess.
   `Match` still receives a length and never learns a lattice exists.

   **Every registration recognising as many protrusions as any other does
   survives, and nothing chooses between them.** A registration recognising
   fewer than another is strictly *dominated*: a rigid motion demonstrably
   exists putting more of this board's parts through holes, so the poorer one
   is no serious claim about where the board sits and is discarded. A tie *at*
   the maximum is different in kind — two genuinely symmetric seatings — and
   every one of those is returned, because `Ranking` below is where placements
   are ordered and handing back one silently is how a pedal gets assembled
   mirror-imaged. More than one surviving is `ambiguous-placement`, a warning:
   the operator is told there is a choice rather than left to notice it.

4. Two protrusions within tolerance of one hole is `ambiguous-pairing`, exit 2.
   Two parts cannot occupy one hole, and choosing between them would be the
   weighting the pre-spec refuses. It is raised when **any** surviving
   registration exposes it, which needs no one of them singled out: two parts
   within a tolerance of one hole stand closer together than the grid pitch
   itself, so the pathology is in the input rather than in the hypothesis that
   revealed it. A *dominated* seed routinely piles several parts onto one hole,
   and convicting a board over one of those would refuse nearly every real
   input — which is exactly what discarding them above prevents.

5. An admitted protrusion that **every** surviving registration leaves with no
   hole within tolerance is `unmatched-part`, a warning. Quantifying over the
   whole surviving set is what makes the finding independent of any choice
   between equally good seatings. The finding names the hole it came nearest
   and by how much it missed — the *smallest* miss any surviving registration
   achieves, because that is the useful number: a part a fraction of a
   millimetre outside tolerance is a misplaced footprint worth seeing, and the
   same part read through some other seating is metres away. Dropping it
   silently would let a real misalignment reach no artefact — the tar panel's
   two LEDs miss by 0.495 mm, four times the tolerance, and nothing said so.

**Which face points at the panel is derived, not searched.** A board is seatable
only when its components protrude *out* through the drilled face, so the rotation
placing it satisfies `R · w_board = w_panel`, where `w_board` is the direction
`_outward` measures the components protruding and `w_panel` is the face frame's
outward normal. Both bases are right-handed about their own normals, so that one
equation fixes the handedness of the planar map: step 2 solves a proper rotation
of the axes exactly as measured. `panel_face` is `+w` for every board this tool
can place, and a board recognising no hole at all is `no-correspondence`.

An earlier version tried both of a board's faces and took the one with strictly
more pairings, equal non-zero counts being `both-faced-group`. That search is
withdrawn, and the code with it. It was a hedge against `_outward` reading the
protrusion direction backwards, and it cannot pay: a board whose parts are
reflection-symmetric in the carrier plane — a row of collinear pots, a pair of
footswitches — registers equally well either way, so the count ties precisely
where the hedge would have had to decide; and a board whose `_outward` really
were reversed has already had every profile depth measured from the wrong tip,
which no choice of face repairs. Measured on the tar panel, where the reflected
hypothesis is not merely unnecessary but impossible: it lays each substrate
*inside* the 2 mm casting wall — 1189 mm³ and 6215 mm³ of solid intersection —
where the derived face leaves both in the cavity, intersecting the casting by
nothing at all. Reconstructing that placement reproduces the board-to-case
interference measured in the operator's own manual assembly, 29.13 mm³, a figure
it was not fitted to.

Recognition is deliberately more permissive than fit. Whether a shaft physically
passes through a hole is Seat's question, and asking it here would make the test
unsatisfiable: a 3PDT bush measures 12.000 mm into a 12.000 mm hole.

### Candidates

**Every seeded registration recognising as many protrusions as any other does
is a candidate placement.** Candidates are not built from correspondences; the
correspondences are what a candidate produces. Two remains the *floor* — the
rank of a rigid planar transform, not a threshold — but a candidate must also
reach the maximum any seed reaches, for the domination reason step 3 gives.
Candidates are returned in an order fixed by their correspondence sets, so that
the set is a function of the geometry rather than of enumeration order
(ADR-0006); that order states no preference, and `Seat` ranks them.

**A candidate is identified by the set of correspondences it validates.** Two
seeds reaching the same set are the same candidate. This deduplication is exact
and discrete — no rounding of x, y or θ, and therefore no angular resolution to
choose. The transform for a distinct candidate is recomputed from its two most
widely separated corresponded protrusions, which is the best-conditioned choice
available, with ties broken by designator order.

The enumeration is quadratic in each of the admitted protrusions and the holes,
and the separation test above rejects most seeds before a transform is built.
`--panel-reference` is required for this reason among others: it is the
operator's own bound on the first factor, and a board whose every part were
admitted would seed against holes no panel reference ever meant to reach.

A board offering fewer than two admitted protrusions is `under-constrained-board`
and earns no placement: one point leaves the board free to turn about itself, and
none seeds nothing. The same finding covers a board whose parts are too few to
fix a transform after recognition. `--place` is refused rather than honoured, for
the reason the command line section states, so nothing decides where such a board
goes and nothing writes it into the assembly.

A board whose every seed fails the separation test is `no-correspondence`: its
parts and this panel's holes do not stand in the same relation to one another,
under any rigid motion at all, so it is the wrong board for this case.

That is the only way a board with two or more admitted protrusions reaches no
placement, which retires `no-valid-placement`. The former algorithm could pair
protrusions with holes and then fail to fit a transform to those pairs, so the
two failures were distinct. Seeding cannot: a surviving seed carries its own two
protrusions onto their two holes exactly, so it always validates the two
correspondences a rigid planar transform has rank for. A candidate set is empty
precisely when no seed survived, and one finding says so.

## Seat

### What a placement is

A placement is a single rigid transform, composed in one fixed order:

1. Rotate the board so its carrier normal is antiparallel to the face frame's
   outward normal on the panel-facing side Match derived — the board is turned
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
    seating of one pairing = ( insertion depth of the profile through that
                               hole's radius widened by the fit clearance )
                             − ( that part's own tip stand-off )

    travel = min over correspondences of that seating
```

measured against the inner surface of the drilled plate, which the face frame
registers. **The tip subtraction is not a detail.** An insertion depth is
measured from the part's tip and a placement's `z` translates the board's own
origin plane, so the two are quantities in different frames: the arresting
feature stands `tip − insertion` above the board, and the board travels the
negative of that. Reducing the insertion depths directly is wrong wherever a
part's tip does not sit in the board's origin plane, which is every real part;
on the tar boards it seats them 7.3 and 3.8 mm too deep. Each correspondence
therefore states its own `seat_nm` beside its `insertion_nm`, negative into the
cavity, and `Seat` reduces one number per pairing rather than looking a
protrusion back up — which is what keeps that stage reading nothing but
`DockData.placements`. The tallest obstruction is the one that arrives at the
face first, so the least seating is the travel.

Depth is a fact about one board's own parts, so two boards of one
assembly seat at their own depths and are coplanar only by coincidence: on the
tar assembly the footswitch board comes to rest about 6 mm deeper than the board
carrying the pots, because a 3PDT body is the larger obstruction. **No kernel query and no descent.** A shaft ends up centred in its
hole because that is the only configuration in which the board seats, not because
anything was told what a shaft is.

Seating depth is fixed by the panel-reference correspondences **alone**. Anything
else that would foul at that depth is a clash to report, not a constraint to yield
to — which is what "collisions left in place" already says about the emitted
model. This resolves the pre-spec's open question about cases where seating is
more than a single query: the set is empty, because the question was mis-framed.
A standoff is not a seating constraint; it is a solid that clashes.

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
`ambiguous-placement` so `stompcad` can offer a picker; the model is written at
rank 1, and `--pin N=RANK` is refused rather than honoured, for the reason the
command line section states.

Inter-board clashes are **reported, never compromised away**. A hole pattern is a
hard constraint, so two boards that fight is a fault in the pedal, and the useful
output says where and by how much.

## Clashes

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

A 12.000 mm bush meets a 12.000 mm hole exactly, and the exact boolean answers
that pair with **nothing at all**: a non-null compound carrying no vertex, no
face and no solid, off which a bounding box cannot even be read. Contact is
therefore decided by the kernel's own result, not by comparing an extent
against a tolerance chosen here — there is no extent to compare.

Zero-nanometre depth is contact too, for any region that does arrive with an
extent ADR-0003's canonical representation cannot express. Anything that
representation cannot state is not a fact, so the resolution is the test and no
threshold is introduced. One whole nanometre is a fact, and is reported.

**This claim is verified, not assumed.** The implementation carries the named
test — a 12.000 mm shaft in a 12.000 mm bore, curved contact rather than
planar — beside the probe a rule discarding everything would fail: one micron
of radial interference is a clash, and so is a one-nanometre overlap.

Where a corresponded protrusion's profile exactly equals its hole radius, the
report records `zero-clearance` at INFO. It is an interference fit by design, and
it is why a fit report is optimistic wherever a thread is involved: a
potentiometer's M7 bushing is modelled at its 6.188 mm thread minor diameter, not
the 7 mm the real part occupies. Model fidelity is the caller's responsibility;
naming where the report inherits it is not.

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
    "panel_face": "+w",
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
    "message": "D3 lands 0.495 mm from hole 1, its nearest",
    "location_nm": null,
    "data": {"designator": "D3", "nearest_hole": 1, "offset_nm": 495000}}]}
```

`unmatched-part` takes two shapes under one code. A part whose axis every
surviving registration leaves near no hole carries `nearest_hole` and `offset_nm`,
as above.
A part yielding no admissible cylinder has no axis, so it has no distance to any
hole and carries neither key — the reader tells them apart by their presence, not
by a second code.

`location_nm` is written on **every** diagnostic, `null` where the finding names
no position — the same unconditional field `stompmodel`'s codec writes for the
same shared `Diagnostic`, so a consumer can tell a finding with no position from
a key that was dropped.

`case.face` is echoed from the drill document, never chosen here.
`panel_face` is which side of the carrier plane points at the panel, as a sign
along the board's own carrier normal in the file it was exported from. It is
`+w` for every placed board, derived rather than searched — see Match — and is
written because a reader must be able to see the convention a placement assumed
rather than infer it. Angles are serialised at six decimal places, which is the only float in
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
| `ambiguous-pairing` | ERROR | Two protrusions within tolerance of one hole |
| `no-substrate` | ERROR | Every solid is named; no board body to group onto |
| `unreadable-board` | ERROR | Not a readable STEP file, or no solids |
| `degenerate-geometry` | ERROR | A boolean or profile could not be evaluated |
| `wrong-case-model` | ERROR | The model's footprint is not the enclosure the drill document identifies |
| `clash` | WARNING | Two solids occupy the same space in a completed placement |
| `unmatched-part` | WARNING | An admitted part with no axis, or whose axis every surviving registration leaves near no hole |
| `unmatched-hole` | WARNING | A hole no board covers |
| `multiple-boards` | WARNING | The input held more boards than one file suggests |
| `under-constrained-board` | WARNING | Fewer than two correspondences |
| `ambiguous-placement` | WARNING | More than one distinct placement survives |
| `zero-clearance` | INFO | A profile exactly equals its hole radius; it passes, with nothing to spare |

**A board with correspondences but no candidate is an error, not a silence.**
Two correspondences are the rank of a rigid planar transform, so a board
carrying two or more that no single transform fits is one this tool cannot
place. Saying nothing would leave it with no placement, no finding, and no
mention anywhere in either artefact.

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
    --match-tolerance MM       optional; overrides the derived half-pitch
    --fit-clearance MM         optional; how much wider than a part its hole
                               must be, on diameter. Default 0.1
    --place N=X,Y,THETA        repeatable; an under-constrained board
    --pin N=RANK               repeatable; choose among ranked placements
    --report PATH
    --assembly PATH
    -v
```

Every flag resolves before any file is opened, so an unparseable filter
expression, a malformed `--place`, or a `--pin` naming a board ordinal that
cannot exist is exit 3 rather than a diagnostic. A `--match-tolerance` that was
*supplied* is resolved there too; only the derived one is necessarily settled
after the drill document is read, because that document is where it comes
from. Both are usage failures, so the distinction costs no exit code.

The tolerance the run actually matched with is stated in the report's `CASE`
block, read back from `Match`'s own record rather than from the command line.
A value that is usually derived and decides which hole belongs to which part
may not also be invisible.

**`--place` and `--pin` are parsed, validated, and then refused.** Neither has
a consumer: nothing places a board explicitly, so `Match` gives an
under-constrained board no placement at all, and `Clashes` re-ranks every
placement once its clashes are known, so no pinned rank could survive to the
report. Both are refused with the reason stated, as a usage failure. An
accepted flag that silently changed nothing would be the worse failure — the
operator would read back a placement they never asked for and believe they
did. They are validated *before* they are refused, so a bad ordinal is still
reported as the bad ordinal it is rather than being hidden behind the refusal.

This falls short of [`stompcollider.md`](stompcollider.md), which requires that an
under-constrained board be explicitly placed and treated as a fixed body others
must avoid. That document wins, so this one records the shortfall rather than
restating the refusal as though it were the intended design; `docs/BACKLOG.md`
carries the gap as work.

There is no `--case-face`: the drill document carries the face frame `stompdrill`
cut in, so `stompcollider` reads the registration instead of choosing a face. It
checks against every solid of the case model and never selects one.

`wrong-case-model` compares the footprint the drill document's `enclosure` records —
`length_nm` and `width_nm` — with the footprint measured from the supplied case model,
both pairs reduced to descending order before an exact nanometre comparison. Product
names never enter it, so the code means one thing in both tools: this is exactly the
check `stompdrill`'s `CheckCaseClearance._cross_check` already makes. A drill document
that identified no enclosure carries none to check against, and the comparison is
skipped rather than guessed at.

## Determinism

Identical inputs produce a geometrically and byte-identical result. This binds
algorithm choice, not merely output.

- **No iterative numerical step anywhere.** Every stage is an enumeration or a
  closed-form query. Correspondence is enumerated, rotation is implied rather
  than swept, seating is arithmetic on profiles, and clash depth is a bounding
  box of an exact boolean. A profile's own bands are the same kind of answer:
  one boolean per probe radius, over a probe set the drill document fixes, with
  no search or bisection over radius anywhere.
- **No mesh, for anything measured.** A triangulation is a function of the
  deflection parameters it was built at and of the kernel's version, so a
  quantity read off one is not a fact about the input. `radial_reach` and
  `axial_extent` read exact geometry, and every bounding box they take is taken
  with triangulation disabled.
- **A near-tangent boolean is deterministic but not robust.** Cutting a solid
  against a cylinder whose radius all but equals a face of it -- a ⌀12 thread
  crest probed at 12.000 mm -- leaves slivers, and the residue's reach then
  names a feature nearer the tip than the one that really binds. It is the same
  answer on every run, so determinism holds; it is a fidelity limit of the
  model rather than of the rule, and the fit clearance is what normally keeps a
  probe away from a crest. The footswitch measured above is this case, and it
  is named here rather than smoothed away.
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

- `Match` and `Seat` are pure, and their *unit* tests use hand-built `DockData`
  with no kernel and no fixture file. Those fixtures state a board in its **own**
  frame — an origin and rotation away from the panel — and never in the answer's
  coordinates. A builder taking a part's position in panel coordinates cannot
  express an undocked board at all, which is how the registration defect above
  survived a suite that was otherwise careful: every hand-built board was already
  standing on its holes, so the pairing rule was never asked the question it got
  wrong.
- **The reader-to-`Match` seam is itself a test, behind `--boards`.** Real
  geometry from `tar-pcb.stp` goes through `substrates`, `group`, `protrude` and
  `canonicalise` into `Match` against holes from a drill document, and the
  correspondences it reaches are asserted. Purity is a property of the stage, not
  a reason to leave the join between two stages unexercised: `Match`'s unit tests
  and the board reader's unit tests were both green and complete while the one
  path a real run takes through them was broken. A stage tested only on inputs
  another stage never produces is tested against a contract nothing implements.
- **Property tests:** filter parse-and-apply idempotence; profile monotonicity in
  depth; insertion depth non-increasing as hole radius decreases; candidate
  deduplication idempotence; placement ranking is a total order.
- Fixtures break accidental equality: boards are numbered out of tuple order and
  correspondences are stored unsorted, so a test only passes an emitter that
  reads the ordering the model states rather than recomputing one from list
  position.
- **Kernel-backed tests are opt-in behind `--boards`**, mirroring `--hammond`,
  and run against `packages/stompcollider/tests/fixtures/tar-pcb.stp`.
  Coverage for `sources/` and
  `emitters/assembly.py` is measured under that command, not the default one.
- Cross-artefact claims are asserted by parsing both emitted artefacts and
  comparing what they say about one assembly, as
  `packages/stompdrill/tests/test_drawing_agreement.py` does today. The two
  readers live in `packages/stompcollider/tests/recovery/` and may import
  neither `stompcollider`, which wrote the report, nor `stompgeom`, whose
  writer produced the STEP: a recovery that inverts its own writer's transform
  proves that writer self-consistent and nothing more.
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
| 2 — `stompgeom` | the STEP reader, the deterministic writer with its OCC normalisation, and the kernel guard; the `CoordinateFrame` / `FaceFrame` split moved *down* into `stompmodel`, not into `stompgeom` — see ADR-0009 as amended | done — 277ac8d |
| 3 — `stompcollider` | everything this document specifies, built test-first | done — its own suite passes under `--boards`, the coverage targets above are met, and `tests/test_dock_agreement.py` compares the two artefacts through two independent readers |

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

**`tar-pcb.stp` waited at the repository root until plan 3.** Plan 1's
bulk move swept it into `stompdrill`, where no test read it and mutmut copied
it into every survey. Plan 3's `boards.py` ticket homed it in
`packages/stompcollider/tests/fixtures/` alongside the first test that opens
it; the root is where a fixture with no member waits, not where one lives.
`stompgeom`'s two granularity probes read it across the workspace from there,
as a file and never as an import.

## Not decided here

- **Recovering a hole pattern from a case's own geometry.** Deferred, not
  forbidden. A future extractor is simply another producer of the drill document.
- **Side-mounted jacks and multi-face drilling.** A protrusion carries its axis
  and a hole its plane, so pairing generalises without rework. That is a change
  to `stompdrill`'s contract before it is one to `stompcollider`'s.
- **Anything flexible.** Harnesses and ribbon cables are excluded from the model
  entirely; nothing represents a flexible part and no rule may assume one
  connects anything.
