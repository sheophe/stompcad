# stompcollider — product-level specification

**Status:** pre-spec. Describes what `stompcollider` is and is responsible for.
Libraries, interfaces and internal architecture are decided from this document,
not in it.

## Purpose

`stompcollider` seats printed circuit boards inside a drilled enclosure and reports
where they clash. Its job is to answer, before aluminium is cut and boards are
ordered, whether a pedal actually assembles.

It is domain-specific only where it must be. Pairing protruding control
elements against holes in a flat drilled face is the problem it was built for,
and that shape is compiled in. What is *not* compiled in is component identity:
no taxonomy, no part library, no notion of what a potentiometer is for. Domain
knowledge of that kind arrives as a caller-supplied parameter.

## Two phases, two questions

Docking is two algorithms with separate roles, distinguished by the question
each answers rather than by the mechanism each uses.

> **Match** — *is it even possible to dock this board into this case, judging by
> the hole pattern?* Someone holding two parts up and deciding whether they are
> the same pattern at all.
>
> **Seat** — *how exactly do these boards sit, and does anything collide?*
> Someone actually assembling it, already expecting each individual board to
> fit.

Match is openly domain-aware and confined to recognition. Seat is naive and does
all the physics. Because Seat runs only after a pattern matched, single-board
fit is rarely where it earns its keep — everything a board can foul once it is
actually in the case is.

### Match

1. Receive the hole pattern as input: centres, diameters, in the drilled face's
   frame.
2. For each board, extract the protrusion pattern **for both faces**, admitting
   only components the panel-reference filter selects.
3. Pair the patterns. The face pairing more holes is the face that points at the
   panel.
4. Each surviving correspondence implies exactly one position and rotation.

**Pairing is a predicate, not a score.** A protrusion and a hole either pair
within tolerance or they do not; the count of valid pairings selects the face. A
weighted trade-off between "most holes" and "least misalignment" would be a
tunable nobody can justify. A genuine tie is refused, not broken.

**Recognition is deliberately more permissive than fit.** Whether a shaft
physically passes through a hole is Seat's question. Asking it during Match
would mean a board that *nearly* fits produces no correspondence at all, and the
tool would report "no valid placement" where it should report "RV3 is 0.15 mm
off and will bind". This is not hypothetical: a 3PDT footswitch bush measures
12.000 mm into a 12.000 mm hole, so a fit-based recognition test is
unsatisfiable on any board with a footswitch.

The recognition tolerance is **half the drill grid pitch**, and it is derived
rather than chosen: holes are quantised to that grid, so two distinct holes are
at least one pitch apart, and any offset below half a pitch identifies exactly
one hole. `stompcollider` receives it as a length and never learns a lattice
exists.

**Rotation is proposed, not swept.** Each correspondence implies one angle;
there is no angular step and nothing is tried exhaustively. Match hands Seat a
small exact set of candidates, not a single answer.

### Seat

Seat chooses among Match's candidates, then places the winner.

Choosing cannot be separated from collision checking: a symmetric pattern
matches at 0° and 180°, and only wall interference reveals that a board is too
long one way round. So Seat first rejects candidates whose outline fouls the
cavity — cheap, and answerable in two dimensions — before computing any depth.

With position and rotation fixed, seating is one-dimensional: how far the board
travels along the face normal before something touches. In the ordinary case
that is **a single clearance query, not a descent**. A shaft ends up centred in
its hole because that is the only configuration in which the board seats — not
because anything was told what a shaft is.

**Seat checks each board against the whole of the rest of the assembly:** every
solid of the case model, and every other board. No part of the enclosure is
privileged or exempt — walls, corner bosses, the floor and the lid are all
simply geometry, and so is a neighbouring board. The rule is stated this way
deliberately: an enumerated list of things worth checking would eventually omit
one, and the omission would look like a passing result.

## What is compared is declared; the comparison is measured

A **panel-reference group** narrows the geometry Match considers: components
whose reference designators match a caller-supplied filter.

Neither signal is sufficient alone, and one real board demonstrates both
failures. Designators cannot separate user-facing LEDs from ordinary diodes when
a designer numbers both `D`. Geometry cannot separate a pot shaft from a
capacitor mounted coaxially behind it at similar height. So the group is
**enumerated per project**; `RV*` and `SW*` are a starting default, never an
answer.

The filter is an expression, not a prefix list. It must support globs, explicit
names, inclusive ranges, and exclusions — a designer's convention is a
convention, not a law.

`stompcollider` never learns what the letters mean. It receives "these designators
are the panel-reference group" and nothing more.

Two rules are built in and not configurable:

- **Only axes perpendicular to the carrier plane are considered.** A cylinder at
  any other angle cannot pass through a hole in a flat panel. This is
  correctness, not optimisation.
- **A protrusion's axis is its furthest-reaching perpendicular cylinder.**
  Coaxiality is sufficient; a fused solid needs no separately named feature.

**A protrusion is a radius-versus-depth profile, not a diameter.** Insertion
depth through a hole is where the profile first exceeds the hole's radius. A
5 mm LED's 5.8 mm flange is the feature that *stops* against the panel, so any
single-diameter rule names the wrong thing. Match needs only the axis; the
profile belongs to Seat.

## Boards

`stompcollider` accepts several files; each may hold one board or many, and it
groups solids into boards itself. The caller cannot pre-split, because a
multi-board layout is a single KiCad project and KiCad exports per board file.

A component belongs to the substrate it **contacts** — among substrates whose
footprint it overlaps, the nearest along the board normal. That covers a
connector overhanging its board's edge and two stacked overlapping boards
alike. Board count and per-board composition are reported: a caller expecting
one board should learn it passed two.

Two boards joined by a soldered harness are **two independent rigid bodies**.
Harnesses and ribbon cables are excluded from the model entirely; nothing
represents a flexible part and no rule may assume one connects anything.

Docking is sequential, each board against the case. A hole pattern is a hard
constraint, so inter-board clashes are *reported*, never compromised away: two
boards that fight is a fault in the pedal, and the useful output says where and
by how much.

A board with **no** panel-reference parts, or exactly **one**, is
under-constrained — one correspondence leaves it free to turn about that point.
It is explicitly placed rather than solved, and treated as a fixed body others
must avoid.

## Outputs

Two, and the split matters: the report is the contract, the model is a view of
it.

**A machine-readable report.** It states the correspondence, not merely a
verdict: which protrusion passes through which hole, named; and for each clash,
the parts by reference designator, the direction, and the depth. Match produces
the pairing as its primary output, so this costs nothing — reconstructed
afterwards by proximity it would be guesswork dressed as a result.

Reference designators are available and must be used. A report saying
"RV3 (ALPHA-RD901F-40) collides with LID by 2.1 mm" is worth more than one
naming an anonymous solid.

**An assembled model, with collisions left in place.** Docking rules respected,
interference not resolved away. Seeing the clash is the point.

A clash against the **lid** is named as such in the report. This is emphasis in
the wording, not a narrowing of what is checked — mechanically it is one
collision among all the others, but it is the most common real-world build
failure and deserves the words. Every clash is reported with the geometry it
involves, whether that is a wall, a boss, the floor, the lid, or another
board.

All distinct placements are returned, ranked. A symmetric hole pattern genuinely
admits two seatings, and handing back one silently is how a pedal gets assembled
mirror-imaged.

## Failure semantics

The workspace exit-code contract applies: `0` clean, `1` findings, `2` error,
`3` usage or IO.

**Matching and fitting fail differently, and only one is an error.**

| Situation | Meaning | Exit |
| --- | --- | --- |
| No correspondence at all | Wrong board for this case | `2` — nothing to show |
| Matched; every candidate clashes | Right board, misaligned design | `1` — reported and drawn |
| Clashes in a valid placement | Findings | `1` — artefacts written |
| Unmatched panel-reference part | A finding: "RV5 has no hole" | `1` |
| Empty or both-faced group | Refused, with the cause named | `2` |
| Unreadable model, degenerate geometry | Could not answer | `2` |

Correspondence is **partial**. A curated part with no hole is nearly always a
design error, and "RV5 has no hole" is a better answer than "no correspondence
found". Holes with no part are normal per board — each board covers a subset by
construction — and are reported once across the assembly, where a leftover hole
means either panel-mounted hardware on no PCB or a board missing from the run.

Zero-clearance fits are **normal, not faults**. A threaded bush is modelled at
the nominal hole diameter. Fit findings also inherit the model's fidelity: a
pot's M7 bushing may appear as 6.188 mm rather than 7 mm, so a fit report is
optimistic wherever a thread is involved.

## Constraints

**Deterministic.** Identical inputs produce a geometrically and visually
identical result. This binds algorithm choice, not just output: no noise
sources, no stochastic search, no hash-ordered iteration. The design as
specified contains **no iterative numerical step anywhere** — every stage is an
enumeration or a closed-form query.

**Stateless.** A pure input-to-output pipeline. No cache, no run record, no
memory between invocations.

**No tunables.** Every constant must be derived from something real or be the
rank of a problem. Half a grid pitch is where hole ambiguity begins. Two
pairings is the rank of a rigid planar transform. Neither was chosen.

**Correct input is the caller's responsibility.** No machinery detects,
compensates for, or works around a defective input. A STEP export missing a
component's 3D model is fixed by assigning the model and re-exporting.

**Installs and tests alone**, without `stompdrill`, `stompcad`, or any pedal-specific
package.

## Out of scope

- **Side-mounted jacks and multi-face drilling.** Planned for a later version.
  The design keeps the door open at no cost: a protrusion carries its axis and a
  hole its plane, so pairing generalises without rework. Assuming a single plane
  would not.
- **Recovering the hole pattern from a case's own geometry.** Deferred, not
  forbidden. `stompcollider` takes a hole pattern; where it came from is the
  caller's problem, and a future extractor is simply another producer of that
  input.
- **Anything flexible.** Harnesses, ribbon cables, wires.
- **Deciding what to drill.** That is `stompdrill`'s.

## Left to the technical specification

- The filter expression grammar.
- Which cases make seating more than a single clearance query — a standoff
  fixing the height, an ordering constraint between parts. The set may be empty.
- The report's serialised form.
- How placements are ranked when several are valid.
