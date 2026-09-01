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
  solids.py         placing and naming one run's solids: the body three
                    modules reason about, stated once
  match.py          Match
  seat.py           Seat
  insert.py         the insertion search: Cavity, CaseCavity, contact_depth
  clash.py          Clashes
  emitters/report.py, emitters/assembly.py
  cli.py, errors.py
```

**`Match` is pure**: it folds over `DockData` and never touches the kernel, so
it is testable with hand-built values. **`Seat` is pure in its arithmetic and
impure in one query**: the reduction over correspondences touches nothing, and
the insertion search it then runs is handed to it as a `Cavity` — a
kernel-free protocol, so every seating *rule* is still testable with
arithmetic, and a `Seat()` built without one is exactly the pure stage it was.
That is a claim about those two stages, not about everything listed above
`sources/`. `boards.py`, `protrude.py`, `insert.py` and `clash.py` read
geometry, and read it through `stompgeom` rather than through OCP.

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
profile exceeds the hole's own radius. It is a **reported measurement**, not the
seat: where a board comes to rest is what the insertion search finds against the
supplied enclosure — see "Seating depth".

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
is `{ admitting_radius(d) : d a hole diameter of this drill document }` — each
hole's own radius, with nothing added to it — which is exactly the set `Match`
will later query. Every part is
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

### Material exactly as wide as its hole

A hole admits material narrower than itself. Material exactly as wide is the
interesting case, and it is common rather than exceptional: a 3PDT bush measures
12.000 mm into a 12.000 mm hole. Comparison is therefore strict — a profile
exactly equal to its hole radius passes — and equality is reported as
`zero-clearance`, an INFO finding, because a part fitting with nothing to spare is
worth seeing even though it is not a fault.

**There is no fit allowance, and there was one.** `--fit-clearance` widened every
hole a profile was judged against, by a tenth of a millimetre on diameter by
default, because a modelled bushing need not be drawn at nominal: the tar
potentiometer's bushing measures 3.5271 mm on radius in a hole drilled to 3.500,
and judged strictly its board could not seat. The flag is withdrawn, because the
insertion search made it unnecessary and the search reads the metal rather than a
prediction about it. That pot's bushing binds on the drilled plate, which the
search finds; the allowance only moved the *prediction* out of the way.

**The prediction is not reliable enough to govern, and this is why.** Probed at
exactly its hole radius, the tar footswitch reads two ways for one part: `SW2`
states an insertion of 20.992 mm and `SW1`, the same 3PDT through the same
⌀12.000 hole, states 9.499 mm. The bush is tangent to its bore, the radial cut is
deciding a tangency, and the boolean leaves a degenerate sliver on one of them and
not the other. Reduced by the least seating, that board would come to rest 11 mm
short of where it goes. The search does not repeat the error, because contact is
not interference and a tangent bush passes: measured against the drilled 1590B, it
stops that board at −17.1444 mm, which is where the flag's default put it and
where the operator's own assembly has it.

So the profile is measured, reported per correspondence as `insertion_nm`, and
does **not** decide where a board rests. The rule, restated against every
panel-reference part on the fixture:

| Part | What stops it | Through |
| --- | --- | --- |
| 5 mm LED | the flange at 5.8 | ⌀5 seats on the flange; ⌀6 passes fully |
| Potentiometer | 6.35 shaft, 7.054 bushing, then the can at 12.6 | ⌀7 inserts to the bushing |
| 3PDT footswitch | 10 tip, 12 bush at exactly ⌀12, the thread run-out at about ⌀12.1, then the body at 25.5 | ⌀12 is a tangency the cut answers two ways |

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

With `(x, y, θ)` fixed, seating is one-dimensional, and **the enclosure answers
it**: a board is pushed in until something stops it, and the search of the
subsection below is what finds where. The hole geometry answers it in closed form
too, and that answer is kept for two jobs — it is what a shortfall is stated
against, and it is where a board rests that the enclosure never touches, which is
also what a run given no case model gets. Travel along the face normal, as the
holes alone fix it, is

```
    seating of one pairing = ( insertion depth of the profile through that
                               hole's own radius )
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

Seating depth is fixed by the panel-reference correspondences **and the
enclosure**, and by nothing else: no stand-off, no neighbouring board and no other
board's parts move a board. Anything else that would foul at the resting depth is
a clash to report, not a constraint to yield to — which is what "collisions left in place" already says about the emitted
model. This resolves the pre-spec's open question about cases where seating is
more than a single query: the set is empty, because the question was mis-framed.
A standoff is not a seating constraint; it is a solid that clashes.

### The case is what stops a board, and finding where is a search

Hole geometry says how deep a board *would* sit if the enclosure were not in the
way. It is in the way of every real board: a board enters through the case's open
back and rises toward the drilled face, and anything it meets on that path
arrests it — a component's own shoulder on the inside of the drilled plate, a
footswitch body grazing the wall's inner fillet, a boss, a screw.

**The path is not bounded by the hole seat.** It is bounded by the last travel at
which any contact is geometrically possible, taken from the same boxes the entry
pose comes from, and the board rests at the first contact found within it —
which may be *deeper* than the profile predicted as well as shallower. The
alternative was tried and is withdrawn: bounding the walk at the hole seat lets a
profile that mis-measures a tangency hold a board 11 mm out of its case, and the
plate is the thing that really stops it. Where the whole path is clear the search
says so by reaching that bound, and the hole seat is what the board rests at.

**The travel is `+w`, toward the panel, not into it.** The board is inserted from
the open end and its controls emerge through the face; a 1590B's box spans −25 to
+2 mm along `w` with its cavity mouth at −25, and no board passes through the
drilled face itself — the tar boards measure 91.5 × 17 and 106.5 × 53.75 mm and
there is no aperture that admits either. A model that pushes a board inward from
outside the panel is not this assembly.

**Seat-then-retreat is wrong.** Testing the hole seat for interference and
backing off until it clears finds *a* clear depth, not the *reachable* one: a
board can pass an obstruction and be clear again beyond it, and retreat cannot
see that it never got there. The question is where contact happens **first**
along the path, and only a search from the entry pose answers it.

This is an argument about the two rules rather than a reading of one fixture,
and the record should say so, because a measurement was once offered here that
does not support it. Board 1 of the tar assembly reads as *clear at its own hole
seat and blocked over a band below it* under the kernel's default tolerance —
which is retreat's counterexample exactly — and reads as blocked continuously
from the seat down to 4.2 mm below it under the tolerance this tool's predicate
actually uses, where retreat would reach the same depth the search does. Only
one of those two readings can be a continuous overlap, and the fuzz note in
`stompgeom.shapes` measures which. The disproof therefore rests on the rule and
on a control the suite carries — a synthetic band a board is clear on both sides
of — not on this enclosure.

**Contact is not interference.** The predicate is a positive shared volume; two
bodies meeting on a surface share none and the board may advance to that pose.
This is rule 3 of `Contact is not a clash` applied to the path rather than to a
resting place.

#### Why it is a search and not a formula

A swept volume would answer this in one query, and it cannot be built here.
`BRepPrimAPI_MakePrism` refuses a solid, and sweeping a solid's boundary faces
instead yields a degenerate prism for every cylindrical wall that contains the
sweep direction — which every bushing on a board has — so the boolean against
that sweep does not merely cost too much, it fails. Exact directional clearance
is likewise unavailable: `BRepExtrema_DistShapeShape` answers the Euclidean
distance, not the axial one, and returns zero for a bushing that fills its hole,
so advancing by it advances by nothing. Solving the directional case exactly
means a contact solver, which this kernel does not offer.

So the depth is searched for. **The domain makes that exact rather than
approximate**: canonical lengths are whole nanometres (ADR-0003, ADR-0004), a
finite ordered set, so the refinement below is a binary search over that set and
not a numerical descent with a convergence tolerance. It terminates in
`⌈log₂ pitch⌉` steps and lands on an integer nanometre, and its determinism is
structural.

#### Coarse to fine, bounded from above

Sampling every candidate depth at the finest pitch would be wasteful, because
almost all of the path is clear and the useful information is the *shallowest*
blocked depth. So:

1. Scan from the entry pose toward the hole seat at `--seat-pitch-max`. The hole
   seat itself is always one of the samples, however the pitch divides the path:
   a band ending exactly at the seat is the common case, and a scan stopping one
   pitch short of it would report a clear path.
2. **Every blocked sample is an upper bound on the answer**, so the moment one is
   found the remaining search is bounded above by it and nothing beyond it is
   ever sampled again. The interval shrinks rather than being rescanned.
3. Sweep the bracket that pass leaves — between the last clear sample and the
   first blocked one — once at `--seat-pitch-min`, from its clear end, stopping
   at the first blocked sample. This is where the fine pitch does its work, and
   it subsumes the intermediate halvings: a sweep at `pitch_min` already sees
   every band a halved sequence ending there would, in one pass instead of
   `⌈log₂(pitch_max / pitch_min)⌉` of them.
4. Bisect between the last clear sample and the first blocked one, over whole
   nanometres, for the exact contact depth.

A board that reaches its hole seat unobstructed is governed by the hole geometry
alone, as before; the search costs one pass and finds nothing.

**Rescanning `[entry, upper]` at each halved pitch is what this replaces, and it
is not affordable.** Measured on the tar assembly: board 1's path from its entry
pose to its hole seat is 44.2 mm, an interference query on that board against the
1590B box costs between 0.15 and 3 s, and a sequence of scans of the whole
interval at 2.0, 1.0, … , 0.05 mm issues on the order of 1400 of them — some ten
minutes for one of the four placements a two-board run seats. The step above
costs the whole run's four searches about 230 queries between them. The
difference in what they see is bounded and named in the next section.

#### What the search cannot see, stated plainly

**A blocked band the coarse pass steps over is stepped over.** The fine sweep
refines the bracket the coarse pass found, so a band lying wholly between two
`--seat-pitch-max` samples and *below* the first blocked one is never reached at
any fine pitch; a band inside that bracket and at least `--seat-pitch-min` wide
always is. A band's width is the sum of the two bodies' extents along `w` at the
offending column, and a glancing edge-on-edge crossing has no positive lower
bound, so no choice of pitch makes this vanish. Silence about a band below either
pitch is not evidence of clearance, exactly as `nesting-truncated` is not
evidence about artwork below a refused form level. This is measured, not
hypothetical: a 0.5 mm pitch steps straight over board 1's 4.10 mm-short blocked
sample, which a 0.25 mm pitch finds.

Two kernel conditions the search must hold to, both measured on this fixture.
The boolean is asked for one pair at many depths, which the clash stage never
does, and under that use it must be **non-destructive** — the placement shares a
`TShape` with the solid it was placed from, and a destructive boolean lets one
query change the answer to the next. It must also carry a **fuzzy value**, or an
ill-conditioned pose reports an empty shape rather than the region it holds: at
default tolerance a 0.07 mm window of board 1's path reads exactly clear between
two blocked samples on either side, which a volume predicate reads as a way
through. Both settings are part of the definition of the predicate, not tuning.

**The fuzzy value does not make contact into interference, and that is
measured rather than assumed.** The pair the claim is about is a 12.000 mm 3PDT
bush in a 12.000 mm hole — the same interference fit `zero-clearance` reports —
and it reads identically at both tolerances, at every depth of board 2's path:
nothing shared, so the board travels to within 0.083 mm of its seat and is
stopped by a footswitch body grazing a wall fillet instead. What the tolerance
does change is a bushing standing 0.027 mm proud in its own bore, which is
interference and not contact, and which the default tolerance fails to build.

**The fuzzy value is the resolution of the answer, and shows in one place.**
Geometry closer than it is coincident to the kernel, so the last depth the
predicate calls clear can lie up to that much beyond true contact: a board
arrested on a plate reads 0.0001 mm past it. The depth is still an exact whole
nanometre and still the same on every run; it is the predicate that is
tolerant, not the search. One consequence is worth naming rather than
discovering: a board stopped short comes to rest a fuzz *inside* what stopped
it, so `Clashes` measures a sub-micron overlap there and the seating is not
case-clean. `every-seating-clashes` therefore reports of a board the enclosure
arrested, which is true and is why that finding is an INFO rather than a fault.

#### Three outcomes

| Outcome | Meaning |
| --- | --- |
| reaches its seat | Nothing on the path obstructs it; the hole geometry governs |
| stopped short | First contact before the seat. The achieved depth, the shortfall, the blocking pair, and which correspondences go unmet are all reported |
| cannot enter | The entry pose itself interferes, so no travel is defined |

A board stopped short is a finding, never a correction: `seated-short` states how
far it fell and what stopped it. `cannot-enter` is an error, and it is never
reported as a travel of zero — a board that cannot go in at all and a board that
seats immediately are different facts.

**`cannot-enter` does not arise from a supplied model, and that is a property of
the entry pose rather than an omission.** The entry pose is *derived*: it is the
deepest travel at which any pair of bounding boxes meets at all, and a bounding
box contains its own solid, so at that depth no material can be shared. The
outcome is modelled and reported end to end because the entry pose is a choice
this version derives and a later one might be given.

#### The lid is not part of this

Insertion runs against the enclosure the board is fitted into — the box, its
bosses and its screws — and never against the lid. The assembly order is
physical: boards go into an open case, and the backplate closes over them
afterwards. Checking insertion against a closed case makes a real design
unanalysable rather than wrong: board 1's pot bodies reach `w = −28.15 mm` while
the tar 1590B's backplate begins at `−25.0`, so with the lid present that board
is obstructed at its entry pose and no depth is defined for it — while the same
board goes into the open box and stops 4.2 mm short for reasons worth reporting.

**Which solid that is, is measured, never named.** Product names take no part:
the drilled solid is the one whose material straddles the face frame's own
plane, the cavity's mouth is how deep that solid reaches, and what closes over
the cavity is a solid whose **centre of mass lies beyond that mouth** *and*
which **spans at least as much as the board in both lateral directions**. Both
halves are needed and neither is a threshold. A plane alone cannot do it,
because the screws that fasten the backplate on occupy exactly the depths it
does — measured on the tar case, the backplate's centre of mass sits at
`w = −27.39` and each screw's at `−24.12`, either side of the `−25.0` mouth,
which the plane does separate; but the span test is what keeps a boss or a post
standing *inside* a shallow cavity from reading as a closure, and a bare drilled
plate with a post under it is exactly that case. A closure narrower than the
board it covers is read as an obstruction instead, which states the same
measured overlap as a shortfall rather than as a case that will not close —
a different finding, never silence.

A board meeting the lid is a different finding and reads as one: the enclosure is
too shallow for this design, by the amount stated — the extent of the shared
region along the face normal, which is the dimension of the enclosure that is
short. It never removes a seating from consideration in `Several boards`, because
a lid that will not close is precisely what an operator runs this tool to
discover.

**And it never ranks one seating above another.** The same split decides both:
a clash against the enclosure a board is inserted into is `kind: "case"` and one
against what closes over it is `kind: "closure"`, and only the first is read by
the ranking key or by stage one's filter. Measured on the tar assembly, the lid
was the *only* thing separating board 1's two seatings, and it separated them the
wrong way round: the seating whose pots never reach their holes fouls the
backplate less, precisely because it never entered the case. A closure clash is
reported exactly as it always was.

### Ranking

Placements are ranked lexicographically ascending on

```
    (insertion shortfall, clash count, total clash volume,
     greatest clash depth, θ, x_nm, y_nm)
```

where the shortfall is the seat that placement's own holes fix less the depth it
came to rest at, and is negative where the enclosure let the board further in
than its profile predicted.

**The shortfall leads, and it dominates.** A seating that never entered the case
fouls less of it *because* it never entered, so a key led by the clash fields
prefers the board whose parts are nowhere near their holes. Measured on the tar
assembly, board 1's two seatings differ by 19.020 mm of shortfall and the
clash-led key chose the one 19 mm out — the wrong orientation, written into the
assembly model at rank 1. Only clashes against the enclosure the board is
inserted into are counted; see "The lid is not part of this".

Behind the shortfall, clean placements sort first; a genuinely symmetric pair
falls through to the transform, which is exact comparison rather than a measured
quantity, so the order never depends on kernel round-off. Rank is a reported field, not a verdict:
**every** distinct placement is returned. A symmetric hole pattern genuinely
admits two seatings, and handing back one silently is how a pedal gets assembled
mirror-imaged.

### Several boards

Seating an assembly is **two stages, and the first is a filter**.

**Stage one ranks each board against the case alone**, exactly as `Ranking`
states. Its output is not one placement but a set: every seating of that board
that does not interfere with the enclosure it is inserted into.

**That is the search's own predicate, and it has to be.** A board the search
advanced to rest at first contact lies within a nanometre of what stopped it, and
the exact intersection every measured quantity is read from finds a sliver
there — 99 and 305 nanometres, measured on the tar assembly's two boards. Asking
a second definition of interference here left *every* real seating failing the
filter, `every-seating-clashes` firing for every board, and stage two never
running at all. One predicate, asked by the search and by the filter, and a board
seated at contact passes it by construction. Not a volume threshold: a threshold
would be a third rule, and the sliver would still be a rule nobody stated.

A seating that fouls the enclosure is not a seating, so it cannot be improved by
anything a neighbouring board does, and it takes no part in what follows. What
closes over the cavity takes no part either, in this filter or in the ranking
above it.

**And neither is a seating that does not seat.** A board the case arrests well
out of it clears the cavity by leaning on it, and it fouls a neighbour *less*
than the seating that really goes in — precisely because it never went in.
Measured on the tar assembly, that is board 1's 14 mm shortfall taking stage two
outright and being written into the assembly model, after the ranking key had
already put the right seating first. So stage one keeps a seating only if it
inserts as far as any other seating of that board does, compared on the same
shortfall the ranking key leads with and by exact equality of whole nanometres,
which leaves a genuinely symmetric pair whole. What stage two then chooses among
are boards that are all equally seated, and mutual interference alone decides
between them — as stated below.

**Stage two chooses among the survivors on mutual interference alone.** Over the
combinations of stage one's candidate sets, one per board, the assembly taken is
the one of least total inter-board clash volume. The case plays no part here; it
was already answered, and a candidate that reached this stage clears it and is as
deeply inserted as any seating of its own board.

The filter is what makes the second stage affordable. The Cartesian product is
real — *k* candidates per board over *n* boards is *kⁿ* combinations — but it is
formed over seatings that already clear the enclosure, which is a small set and
frequently a single element. Where it is not small the count is bounded and
stated, never silently truncated: the combinations are enumerated in stage-one
rank order and the first `_COMBINATION_LIMIT` of them are tried, so the fallback
when the bound bites is every board's own rank 1 rather than an arbitrary
assembly, and `seating-search-bounded` says how many there were.

Ties are broken on the stage-one ranks, which are themselves a function of the
geometry, so which assembly a tie yields never depends on the order the product
enumerated (ADR-0006).

**A board no seating clears the case for skips stage two entirely.** Its clashes
are reported, the assembly is written at its stage-one rank 1, and
`every-seating-clashes` says so, because otherwise a reader could not tell a
chosen seating from a defaulted one. This is deliberate rather than a
degradation: a board that fights the enclosure in every orientation is a fault to
fix, and the mutual-interference question is worth asking again once it is fixed
and the tool re-run. Withholding the model instead would take away the very
artefact that shows what to fix.

Ordering within a board is still independent and order-free — determinism does
not rest on a traversal order. What is now joint is only the choice *between*
already-clean seatings. A board with more than one surviving candidate is
reported as `ambiguous-placement` so `stompcad` can offer a picker; the model is
written at rank 1, and `--pin N=RANK` is refused rather than honoured, for the
reason the command line section states.

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
`BRepAlgoAPI_Common`. The filtering box of a *placed* solid is the solid's own
box carried through the placement corner by corner, which bounds the moved shape
without measuring it: a box too large can only send a pair to the boolean that
would have decided it anyway, and the filter may never discard a pair that
boolean would have kept. Nothing measured is read off it — a clash's own box
comes from the region the boolean returned, boxed with triangulation disabled as
"Determinism" requires. A clash is that common region's axis-aligned bounding box
in the case's face frame. **Depth is its least extent and direction is that
axis** — defined as the least distance along a face-frame axis that would clear
the overlap. It is an exact answer to that definition and an honest upper bound
on true penetration depth, it needs no meshing, and it degrades sensibly: a board
2 mm too long reports 2 mm along the long axis; a lid 3 mm too shallow reports
3 mm along the normal.

A clash against the lid is **named as such** in the report. That is emphasis in
the wording, not a narrowing of the check.

### A clash carries its true volume as well as its box

The bounding box gives depth and direction, which no cheaper measure does, but it
is only a bound on how much material actually overlaps — and over a whole board
against a whole board it is a poor one. On the tar assembly the box measures
2684.80 mm³ where the material meeting is 53.44 mm³, a factor of fifty. So a
clash states both: the box, which answers *how far to move*, and the exact volume
of the common region, which answers *how much is in the way*. The second costs
nothing extra — the common shape is already built, and its volume is one query on
it. Selection between seatings reads the exact volume; depth and direction still
come from the box.

### Between two boards, per solid and stated once

An inter-board finding names the two solids that meet, not the two boards. "Board
1 clashes with board 2" is not something a person can act on; "C7 meets board 2's
substrate by 25.94 mm³" is. The aggregate remains, because an assembly of many
parts needs a line that says *these two boards interfere* without reading every
pair, but it is a summary over the detail rather than the only statement.

Each unordered pair is **stated once**, against the lower of the two ordinals. The
same interference recorded against both boards is one fact printed twice, and a
reader counting findings would count it twice. The geometry was never computed
twice — the pairing is over `combinations`, not over an ordered product — so this
is a reporting rule, not an optimisation.

The aggregate is a diagnostic and not a second clash record: summing the exact
volumes of the pair's own findings, it would otherwise be counted twice by
anything reducing over `clashes`, which is exactly what stage two does.

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

`stompcollider-dock-report` v2. Integer nanometres, a `format`/`version` header, and
diagnostics matched by `code` — the same conventions as the drill document.

**Version 2 is what a clash now states.** Each clash carries `common_volume_nm3`
beside `bbox_volume_nm3` and `part` beside `with`; every clash object in the
document gains three keys and loses v1's `volume_nm3`, so a v1 reader modelling
exactly the keys it knows would refuse it. That is the version's whole content —
no other field moved, and both volumes are named for what they measure rather
than one keeping the unqualified name it held while it was the only one.

```json
{"format": "stompcollider-dock-report", "version": 2, "units": "nm",
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
         {"with": "LID", "kind": "case", "part": null,
          "bbox_nm": [-4000000, 20000000, -2100000, 4000000, 26000000, 0],
          "depth_nm": 2100000, "axis": "w",
          "bbox_volume_nm3": 42000000000000000000,
          "common_volume_nm3": 13000000000000000000}]}]}],
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

`insertion_nm` is how far that part's profile passes through that hole's own
radius, measured back from the part's tip. It is a **reported measurement and not
the seat**: the placement's `z_nm` comes from the insertion search against the
supplied enclosure, and the two disagree wherever a profile is deciding a
tangency. `null` there means the hole admits the part entirely, which is a
geometric fact rather than a missing measurement.

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

`with` names a case solid by its STEP product name, or a solid of another board
as `board:2:SW1` — the very name the assembly model writes that solid under, so a
reader can find it in the file. `kind` is `case`, `closure` or `board`, so a
consumer never parses that string to learn what it is looking at: `case` is the
enclosure the board is inserted into, `closure` what closes over the cavity, and
that distinction is the one thing ranking and stage one's filter read — see
"The lid is not part of this". `part` names this board's own
solid, under the same rule, and is `null` where the whole board was checked at
once; a board-against-case finding is stated per case solid, because a wall is one
thing to move a board away from however many of its parts reach into it.

`bbox_volume_nm3` is the stated box's own volume, exact by construction as the
product of three canonical lengths. `common_volume_nm3` is the material the boolean
actually found, converted from the kernel's own integration, so the two agree only
where the region really is its box.

An inter-board finding is recorded against the **lower** of the two ordinals, once.
The report therefore holds no clash under the higher-numbered board for a pair the
lower one already states, and `part`/`with` say which way round it is without a
reader having to know that rule.

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
| `every-seating-clashes` | INFO | No seating of this board clears the case, so it took no part in choosing the assembly |
| `seated-short` | WARNING | The enclosure stops this board before its holes would, by the amount stated |
| `cannot-enter` | ERROR | The board interferes with the enclosure at its entry pose, so no insertion depth exists |
| `enclosure-too-shallow` | WARNING | A seated board meets the lid: the case will not close over this design |
| `seating-search-bounded` | INFO | More combinations of case-clean seatings exist than stage two tried; the assembly chosen is the best of those it did |

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
    --seat-pitch-max MM        optional; the insertion scan's coarsest step.
                               Default 2.0
    --seat-pitch-min MM        optional; the pitch the bracket that scan
                               leaves is swept at, and so the width of the
                               narrowest obstruction visible inside it.
                               Default 0.05
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

Both seat pitches are positive lengths and an ordered pair: a coarse step finer
than the fine one describes no scan, so it is a usage failure rather than a
search that silently reverses them. Equal is legal — one pitch for both passes
is still a scan. `Seat` records the pair it ran with in its own `describe()`,
because a search that happened must be legible as one.

**There is no `--fit-clearance`.** It widened a hole in the *profile* and never
in the model, and it was withdrawn once the insertion search made the profile a
reported measurement rather than the seat: the metal the search reads is what a
bushing drawn proud of its bore really meets. See "Material exactly as wide as
its hole" for the measurements, and note that removing it changed no radius the
reader probes at — the probe set is one radius per distinct hole diameter either
way — so it bought no work back.

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

- **No numerical descent anywhere, and the one search is over a finite set.**
  Every stage is an enumeration, a closed-form query, or a bisection over whole
  nanometres. Correspondence is enumerated, rotation is implied rather than
  swept, seating is arithmetic on profiles, and clash depth is a bounding box of
  an exact boolean. A profile's own bands are the same kind of answer: one
  boolean per probe radius, over a probe set the drill document fixes, with no
  search or bisection over radius anywhere. The insertion depth is the exception
  and is exact for the reason "Why it is a search and not a formula" gives: the
  candidate depths are a finite ordered set, the sample schedule is fixed by two
  stated pitches, and the last step lands on an integer rather than at a
  convergence tolerance.
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
  model rather than of the rule, and it is why the profile is reported rather
  than obeyed. The footswitch measured above is this case -- two of one part
  read 20.992 and 9.499 mm through the same hole -- and it is named here rather
  than smoothed away.
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

- `Match` and `Seat`'s own rules are pure, and their *unit* tests use hand-built
  `DockData` with no kernel and no fixture file — `Seat`'s take a fake `Cavity`
  answering arithmetic, the arrangement `stompdrill`'s clearance stage already
  uses for `CaseModel`. The insertion search is tested in two halves for the same
  reason: `contact_depth` against a synthetic blocked set, which is where the
  control lives that tells this design from seat-then-retreat — a band the board
  is clear on both sides of, so retreating from the seat reports no correction
  while the search reports the band's near edge — and `CaseCavity` against solids
  built in the test rather than read from the fixture, so both run in a standard
  suite. Those fixtures state a board in its **own**
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
- **The two seat pitches each have a test that fails when the other is used.**
  A flag that changed no answer would be worse than an absent one, and the fine
  sweep is the only thing `--seat-pitch-min` moves: the paired test states one
  geometry, two pitches and two different depths.
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
