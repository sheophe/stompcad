# Foundation docket: the seven rulings that gate plan 3

**Status:** accepted and executed. Settles every question on the 2026-08 foundation
audit's ruling docket; plan 3 carried out the consolidated work list below, on
`stompcad-collider` from `9180569`. The amendments table near the end is the record
of what was changed, not a list of outstanding work.

**Spec:** the work itself is specified by
[`stompcollider-technical.md`](stompcollider-technical.md); this document supplies the
answers that specification leaves open, and nothing else.

**Governed by:** [ADR-0001](../adr/0001-pipeline-and-emitter-adapters.md),
[ADR-0006](../adr/0006-toolpath-ordering-and-hole-numbering.md),
[ADR-0008](../adr/0008-workspace-and-shared-geometry-core.md) and
[ADR-0009](../adr/0009-shared-model-package-and-dependency-order.md). This design
**amends ADR-0001, ADR-0008 and ADR-0009**; each amendment is named where it is incurred.

## Scope

Plans 1 and 2 extracted `stompmodel` and `stompgeom`. Plan 3 builds `stompcollider`. The
audit that reviewed the first two plans closed with seven questions it declined to answer,
each because it had a documented answer and a spoken one and an audit cannot rule between
a document and a preference. Those seven gate plan 3: every one of them decides a module's
contents, a package boundary or a signature, and each is cheaper to settle now than to
discover mid-ticket.

This document rules all seven. It does not schedule the work; that is plan 3's job.

**Method.** Where a question could be decided by measuring the repository or its fixtures,
it was, and the measurement governs — including where it overturned the premise it was
meant to confirm. Where it could not, the ruling is a maintainer's decision and says so.

## Evidence

Figures below describing `tar-pcb.stp` (homed in
`packages/stompcollider/tests/fixtures/` by plan 3's `boards.py` ticket) and the
cached Hammond models are
properties of immutable inputs, and **the implementing ticket carries each as a test
assertion** so a figure that drifts fails a suite rather than quietly staling this
document. Figures describing the repository itself are deliberately given as *commands*
rather than counts, because a count is stale on the next commit.

**`tar-pcb.stp` is two boards.** 43 solids: 41 named with reference designators
(`R5`, `C3`, `D2`, …), 2 unnamed. The unnamed pair measure 91.50 x 17.00 x 1.51 mm and
106.50 x 53.75 x 1.51 mm, both spanning z 0.000–1.510, disjoint in y by 4.25 mm. A main
board and a strip, side by side and coplanar — not one board exported in two pieces.

**Holedness does not separate a board from a component.** Every z-normal level across the
assembly, with each level's holed fraction:

```
  area mm2     z mm  out   holed  owners
   5352.20    1.510   +1   3.13%  <unnamed>      <- both boards, merged
   5352.20    0.000   -1   3.13%  <unnamed>
    733.40    1.815   -1   2.24%  J1,J4
    633.17  -10.485   +1   0.00%  SW1,SW2
    576.79   -3.085   +1   0.11%  D3,D4,RV1 +4
    526.18   -7.085   +1   0.00%  RV1,RV2,RV3 +2
```

The board face is the **most** holed of the top candidates. Connectors, switches and
potentiometers are solid slabs; a 50% limit admits every one of them. `stompdrill`'s
`_HOLED_FRACTION_LIMIT` says why in its own docstring: it was calibrated to separate a
casting **plate from a ring** (plates ≤3.7%, rings ≥83.3%), and a PCB assembly contains no
rings. What the geometry rule credits to holedness is done entirely by **area**.

**Global grouping is semantically empty.** That 576.79 mm² level is seven faces belonging
to D3, D4, RV1 and four other components that merely happen to be coplanar. A level is
meaningful only within one solid.

**A per-solid partition finds the carriers with no axis and no threshold:**

```
strip:  55 planar faces -> 22 levels
        1007.23 mm2  dir (0,0,-1)  offset 0.000     <- carrier
        1007.23 mm2  dir (0,0,+1)  offset 1.510     <- carrier
          64.17 mm2  dir (0,1,0)   offset -29.500      (15.7x drop)

board:  51 planar faces -> 47 levels
        4344.96 mm2  dir (0,0,-1)  offset 0.000
        4344.96 mm2  dir (0,0,+1)  offset 1.510
         133.63 mm2  dir (0,1,0)   offset 37.500        (32.5x drop)
```

**Real normals deviate further from an axis than float noise.** Worst deviation from a
kernel axis among faces the shipped acceptance test admits:

```
tar-pcb  strip substrate    worst off-axis  3.846e-08     levels 1e-9: 22, 1e-6: 21
tar-pcb  main substrate     worst off-axis  0.000e+00     levels 1e-9: 47, 1e-6: 47
1590B    BOX / LID / screws worst off-axis <6.8e-16       stable at every granularity
1590Y    Box / Lid / screws worst off-axis <1.3e-16       stable at every granularity
```

The strip carries one face tilted 38 nanoradians — export noise, not geometry. Every
Hammond solid is float-noise clean, so **`stompdrill`'s artefact bytes are safe at any
granularity considered here**; only the PCB fixture is sensitive.

**No rigid transform is constructed anywhere in the workspace.**

```bash
grep -rn "gp_Trsf\|TopLoc_Location\|BRepBuilderAPI_Transform\|gp_Ax3\|gp_Quaternion" packages/*/src/ tools/
```

returns nothing. The only executable use of a location in any `src/` inverts one, to undo
a placement before writing unplaced geometry.

**`stompdrill` performs no boolean.**

```bash
grep -n "BRepAlgoAPI\|VolumeProperties\|Extrema" packages/stompdrill/src/stompdrill/pipeline/clearance.py
```

returns nothing. Clearance is a point-classification check, not an intersection.

**The direction transform returns a wrong answer, silently and `mypy`-clean.** On a frame
with origin (10, 20, 30) mm, `to_canonical((1.0, 0.0, 0.0))` returns
`(-9.0, -20.0, -30.0)`. For a point that is correct; for a normal it is the origin
subtracted from a direction. Ticket 54 widened the return to three values and did not
change this.

## Ruling 1 — a substrate is selected by name and verified by slab-ness

A solid XCAF gave a name is a component; an unnamed solid is a substrate **candidate**.
`stompcollider-technical.md`'s "Substrates and components" stands as written.

Each candidate is then **verified to be a slab**: its two largest levels must be
**exactly opposed**, of comparable area, and their offsets must sum to a thickness small
against the carrier's own extent. A candidate failing that test is not a board.

"Exactly opposed" is unambiguous and needs no tolerance: directions are integer keys, so
opposition is component-wise negation of one key by the other. The two proportions are
not: this document fixes the *form* of the test and leaves both constants to the
implementing ticket, which calibrates them the way Ruling 2 calibrates its granularity —
from a measured gap across every available fixture, stated with what lies on each side,
and carrying both probes. Writing a ratio here from one board would be the tuning this
document elsewhere refuses. The evidence it starts from: both substrates' opposed levels
measure *equal* areas to two decimals, and the next level down is 15.7x and 32.5x smaller.

Holedness plays no part in substrate identification.

**Why.** The name rule is threshold-free, matched the fixture 41 to 2 with no tuning, and
partitions faces by solid for free — which the evidence shows is the only granularity at
which a level means anything. The geometry rule cannot count boards: the two substrates
are coplanar, so any global grouping merges them into one 5352.20 mm² plane, and
recovering two would need face-connectivity analysis. And holedness, measured, does not
discriminate.

The verification step is what the name rule alone lacks. Its two failure modes are an
exporter that names nothing (43 substrates) and one that names everything (a clean
`no-substrate` refusal). The second is already correct; slab-ness catches the first, since
a resistor body is not a slab. The carrier normal falls out of the same test as its key.

`no-substrate` at `spec:129` and its diagnostic-table row stay live.

## Ruling 2 — `levels()` is a partition, not a filter

```python
def levels(solid: StepSolid, axis: Direction | None = None) -> tuple[Level, ...]
```

Partitions the solid's planar faces by **their own outward direction and offset**. There
is no axis index and no three-axis sweep. `axis` is an optional unsigned filter.

```python
@dataclass(frozen=True)
class Level:
    direction: tuple[float, float, float]   # unit, outward-facing
    offset_nm: Nanometre                    # signed, measured along direction
    area_mm2: float
    faces: tuple[Any, ...]                  # TopoDS_Face
```

Three consequences, each measured rather than argued:

- **`outward` ceases to exist.** Today's `(position, outward)` pair becomes one direction;
  a face's `TopAbs_REVERSED` orientation flips the direction rather than setting a
  separate sign field. One fact, one place. This retires the field ticket 55 repaired.
- **Offset is signed along the outward normal**, so two opposed levels' offsets *sum* to
  the thickness — 0.000 + 1.510 above. Slab-ness is one addition, and `find_faces`'
  `abs(inner.position - drilled.position)` becomes a sum with no absolute value.
- **The harvest clump stops existing.** `docs/BACKLOG.md:662-676` requires the ~22-line
  clump move with `_levels` and become "a named type rather than a bare tuple". Under a
  partition taking a solid there is nothing to name: the harvest is `levels()`' own body.
  That entry's Acceptance is rewritten, not ticked.

**Granularity is a millionth, with a control.** The key is integer, per the rule that no
composite key holds a float: direction components rounded to millionths, offset to whole
nanometres. The granularity is chosen from the gap the evidence measures: the largest real
coplanar deviation is 3.846e-08 and the tolerance the shipped acceptance test already
embodies is ~4.5e-5 rad, so a millionth sits 26x above the noise and 45x below the
tolerance — near the geometric midpoint of a three-order gap. This is the form of argument
`_HOLED_FRACTION_LIMIT` uses for 50%. A billionth was considered and **rejected by
measurement**: it splits the strip's 98.15 mm² side wall into 58.89 + 39.26 mm² — the same
physical feature that produced ticket 55's float-key defect.

Because a granularity that merges everything and a correct one are indistinguishable from
a pass rate, the constant carries both probes: at a billionth the strip's side wall splits
in two; at a millionth it stays one.

**Keying, not clustering.** A distance-based cluster is order-dependent, which ADR-0006
forbids outright ("No rule may consult input order"). The price of keying is that two
faces straddling a rounding boundary split; `_levels` already accepts exactly that hazard
for position, so the precedent licenses it rather than the argument being made fresh.

**The published `direction`** is the quantised key reconstructed and re-normalised to unit
length, so members of one level share a bit-identical direction and `CoordinateFrame`'s
1e-9 unit-length check has margin.

**Residual risk, named rather than engineered against:** two genuinely distinct planes less
than a microradian apart, through the same point, merge. Fillets and drafts are degrees.

**Why not the kernel-axis index.** The audit graded it as reaching the artefact as a wrong
placement rather than an error. Ruling 1 removes that: a detector that verifies slab-ness
finds no slab on any swept axis when a board is tilted, and refuses loudly. Its remaining
cost is duplication — every consumer that must learn a normal writes the same sweep —
which is the duplication ADR-0008 exists to prevent. **Why not a required direction:** the
collider must learn the direction before it could pass one, so the sweep moves into the
caller rather than disappearing.

**Holedness stays in `stompdrill`.** `_plates` and `_HOLED_FRACTION_LIMIT` stay where they
are, operating on `list[Level] -> list[Level]`. **This amends ADR-0009**, whose inventory
reads "`levels()` for grouping coplanar faces and measuring holedness". That sentence
anticipated carrier-plane detection as holedness's second consumer; Ruling 1 rules that
consumer does not want it. Holedness therefore has exactly one caller, discriminating a
casting plate from a casting ring — enclosure reasoning wearing a geometric coat, which is
the test ADR-0009 applies four paragraphs later to keep `build_frame` out of `stompgeom`.

Stated fairly, the counter-case: "what fraction of a level's boundary is not real surface"
*is* describable without naming a panel, which is ADR-0008's admission test. If a third
tool wants it, it is promoted then, with a consumer in the room.

**`stompdrill`'s call site.** `find_faces(solid, axis)` keeps its signature and return
type, calling `levels(solid, axis=…)` in place of its inline harvest and `_levels`, then
applying `_plates`, `_drilled_level`, `_inner_level` and `_nearest_companion_level`
unchanged but for reading `Level`. **The `axis` filter carries `cad/case.py:151`'s
parallelism test unchanged and inherited.** Exact equality on the quantised direction is
*not* equivalent: a face tilted a millionth off axis quantises to a non-axis key and
renormalises to `direction[2] = 0.9999999999995`, which exact equality rejects where the
shipped code accepts. Narrowing `stompdrill`'s acceptance is not this work's to do. Two
tolerances with distinct jobs, each stated where it acts: the millionth granularity decides
*are these faces the same plane as each other*; the inherited 1e-9 parallelism test decides
*is this plane aligned with the caller's axis*.

## Ruling 3 — `CoordinateFrame` gains composition; the kernel realisation lives in `stompgeom`

`CoordinateFrame` is an origin plus a right-handed orthonormal basis, which is a `gp_Ax3`
in all but name. The placement `stompcollider-technical.md`'s "What a placement is"
specifies — rotate the
carrier normal antiparallel to the face normal, rotate θ about it, translate by `(x, y)`
then `z` — is exactly the rigid transform taking one frame to another. **The workspace is
not missing a transform type. It is missing composition.**

That gap splits along the seam `frames.py`'s own docstring already draws: *"the value lives
in the leaf and the kernel code that builds one lives above it."*

- **`stompmodel`** gains frame-to-frame composition: pure arithmetic, no kernel, testable
  with hand-built values.
- **`stompgeom`** gains the one function realising a composed transform as a
  `TopLoc_Location` and applying it to a shape.

**This amends ADR-0008**, whose preamble says the rigid transform it named has "settled in
`stompmodel`". That is true of `stompdrill`, whose only spatial need is "where on this face
is canonical (x, y)". It is not true of a tool that places one body against another, and
the amendment says which of the two the sentence describes.

Neither package acquires a new concept; both extend an existing one. The promoted document
builder's `placement` parameter now has something a caller can construct, which it did not
before — half a seam is what the audit called it.

## Ruling 4 — the frame layer gains depth additively; the direction transform comes free

Ruling 3 subsumes the direction transform: a rigid transform applied to a direction drops
the translation by construction, so no separate translation-free method is designed. The
silent wrong answer in **Evidence** is fixed by having a direction-shaped operation at all.

The depth half is a different defect from the one the audit described. These three shipped
sites are not a missing reframe — they are the missing **third argument to `to_model`**,
which is asymmetric with a `to_canonical` that already returns three values:

```python
point: list[float] = list(frame.basis.to_model(x_nm, y_nm))
point[axis] = plane_at          # region.py:166, region.py:232, emitters/step.py:244
```

And they are correct only by luck: setting one *kernel* component equals translating along
`w` **only when `w` is axis-aligned**, which holds for Hammond enclosures
(`normal[axis] = float(drilled.outward)`) and need not hold otherwise.

So `to_model(x_nm, y_nm, depth_nm=0)` — purely additive, no call site forced to change,
collapses all three patches and fixes the latent bug. `reframe` stays two-dimensional: its
own comment says "widen this only with its callers", and the collider wants `to_canonical`
directly, which already carries depth. The clash bounding box in the case's face frame is
`to_canonical` over eight corners, which needs nothing further.

## Ruling 5 — the clash is `stompcollider`'s, as a stage; `Seat` stays pure

`BRepAlgoAPI_Common` has exactly **one** prospective consumer — see **Evidence** — so
ADR-0008's rule that an interface grows when a real second consumer arrives says do not
promote it. `stompgeom`'s inventory does not grow here.

An impure `clash.py` sits between `Seat` and the emitters, taking placements in and clash
records out. Consequences: the purity and coverage claims in
`stompcollider-technical.md`'s "Module layout" become true as written; `Seat`'s cheap property tests keep their whole subject;
`### Clashes` moves out from under `## Seat` in the specification; and one module joins a
layout the specification presents as settled.

The shape is deliberate rather than incidental. A clash check is structurally what
`CheckCaseClearance` already is — a stage consulting a supplied model and emitting
diagnostics — so the collider reuses `stompdrill`'s pipeline-into-fanout architecture
rather than inventing a second one. That is the property `stompcad` will need from both
tools.

If `stompdrill` ever grows a real interference check, the boolean promotes then, with two
consumers in the room.

## Ruling 6 — `scaled_nm` goes home; `format_nm` stays and gains its missing sentence

`scaled_nm` returns a `Decimal` rather than a length, its docstring cites ADR-0003 —
`stompdrill`'s quantisation-boundary ADR — and its only callers are `stompdrill`'s three
quantisers (`grep -rn "scaled_nm" packages/*/src/`). By ADR-0009's own `Micron` test, that
a definition stating "`stompdrill`'s grid policy, not … length" stays home, it should never
have left. It moves back.

`format_nm` stays. It is a formatter rather than a conversion between the newtypes —
`mm_from_nm` is that — so it is admitted under rule 2, which ADR-0009:308-310 requires be
justified by a nameable `stompcad`-visible behaviour. **That sentence has never been
written, and this ruling writes it:** the collider's report prints nanometre quantities
(`depth_nm`, `bbox_volume_nm3` in `stompcollider-technical.md`'s "The report"), `stompcad` reduces both
tools' output to one report, and two independent renderers would print one nanometre two
ways.

This is what "and their conversions" means, and the next promotion cites it: a *conversion*
between the published length types is admitted by rule 1; anything else needs a named
rule-2 behaviour, written down at the time of admission rather than inferred later.

## Ruling 7 — three promotions, one deferral, and a self-terminating grant

**The compound builder promotes now.** It is not a deferred seam; it is live duplication in
shipped source, in `stompdrill`'s `cad/region.py` (twice), `cad/case.py` and
`emitters/step.py`, with further copies in tests
(`grep -rn "MakeCompound" packages --include="*.py"`). `stompgeom` publishes one
`compound(shapes)` and every copy collapses onto it.

**`assembly_spans` promotes.** `stompgeom-technical.md:296-303` lists it under "What does
not move" and states the governing test in the next sentence — *"whether it can be
described without naming a panel"* — which "the bounding-box span of every solid together,
per axis, in millimetres" plainly passes. The document contradicts its own criterion, and
`docs/BACKLOG.md:678-689`'s deferral condition, "a diagnostic more than one tool raises",
has arrived with `wrong-case-model`.

**`_part_of` does not promote.** It is `product_name.split()[0]` — naming policy, not
geometry. `BACKLOG:678-689`'s second Acceptance branch explicitly permits recording that,
and this is that record: a shared home for three tokens of string handling costs more than
it saves, and no geometric rule is duplicated by leaving it.

**The cylinder enumerator is written inside plan 3.** One implementation exists, in
`stompdrill`'s test helpers (`tests/hammond.py:179`), returning axis location and radius
without direction or axial extent — which is precisely what `protrude.py` needs. It is
written properly in that ticket, published from `stompgeom`, and the test helper collapses
onto it. Writing it earlier would design it against the one consumer that does not need
its missing half.

**The CLI target-set policy promotes, by ADR-0001's own words.** `ADR-0001:88-90` grants
the set-level transaction to `stompdrill`'s command line *"for as long as `stompdrill` is
the only caller composing a set of several artefact paths for one invocation."* `--report`
plus `--assembly` ends that condition. The grant is self-terminating and the collider
terminates it, so the NFD-casefold collision key and the regular-file check move to
`stompmodel` beside `stage_payload`. **This amends ADR-0001**, which records the condition
as met rather than having its rule rewritten.

## Consolidated work list

Ordered by dependency, not by priority. Plan 3 schedules it.

| # | Change | Package |
|---|---|---|
| 1 | `compound(shapes)` published; four `stompdrill` copies collapse | `stompgeom` |
| 2 | `assembly_spans` moves; `stompdrill` imports it | `stompgeom` |
| 3 | `scaled_nm` moves home; three call sites re-import | `stompdrill` |
| 4 | CLI target-set validation moves beside `stage_payload` | `stompmodel` |
| 5 | Frame-to-frame composition (pure) | `stompmodel` |
| 6 | `to_model(x, y, depth=0)`; three patch sites collapse | `stompmodel` |
| 7 | Composed transform realised as a location, applied to a shape | `stompgeom` |
| 8 | `levels()` + `Level`; `find_faces` rewritten onto it | `stompgeom` |
| 9 | Document builder promoted with `placement` and `colour` | `stompgeom` |
| 10 | Cylinder enumerator with direction and axial extent | `stompgeom` |
| 11 | `boards.py`: name selection + slab-ness verification | `stompcollider` |
| 12 | `clash.py` as an impure stage; `Seat` stays pure | `stompcollider` |

Items 1–4 are independent of every other row and of each other. Items 5–7 are Ruling 3 and
4 together. Item 8 depends on nothing but is the largest. Items 9–12 are plan 3 proper.

## Document amendments this ruling requires

| Document | Change |
|---|---|
| `docs/adr/0001-…:88-90` | Record the condition as met: a second caller composes a set of artefact paths. |
| `docs/adr/0008-…:8-10, 22-23` | The rigid transform "settled in `stompmodel`" describes `stompdrill`'s need, not the workspace's; composition is added by Ruling 3. |
| `docs/adr/0009-…:146-148` | Drop "and measuring holedness"; record Ruling 2's measurement. Record that measurement stood in for the consumer, per **Method**. |
| `docs/adr/0009-…:308-310` | Add `format_nm`'s rule-2 behaviour, per Ruling 6. |
| `docs/specs/stompcollider-technical.md:115-117` | Purity and coverage claims stand; `### Clashes` moves out from under `## Seat`. |
| `docs/specs/stompcollider-technical.md:123-129` | Confirmed; gains Ruling 1's slab-ness verification. |
| `docs/specs/stompcollider-technical.md:155-156` | Confirmed correct; gains the carrier normal's provenance as the level's own direction key. |
| `docs/specs/stompcollider-technical.md:585` | Drop "and holedness" from carrier-plane detection. |
| `docs/specs/stompcollider-technical.md` module layout | Add `clash.py`. |
| `docs/specs/stompgeom-technical.md:296-303` | `assembly_spans` moves off the "does not move" list, per Ruling 7. |
| `docs/specs/stompgeom-technical.md` | Three ADR links read `../../adr/`, which resolves outside the repository. |
| `docs/BACKLOG.md:662-676` | Acceptance rewritten: no clump survives a partition that takes a solid. |
| `docs/BACKLOG.md:678-689` | Closed by Ruling 7, both branches: `assembly_spans` moves, `_part_of` is recorded as staying. |
| `packages/stompgeom/src/stompgeom/__init__.py` | "The format side of geometry" widens; a partition is analysis, not format. |

## What this ruling does not decide

The **constants** in Ruling 1's slab test, deliberately — they are calibrated by the
implementing ticket from a measured gap, the way Ruling 2's granularity was.

The **schedule**. Which of the twelve rows share a ticket, in what order, and behind which
gates is plan 3's question, and this document is its input.
