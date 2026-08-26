# Substrate identification and the shape of `stompgeom.levels()`

**Status:** accepted, not executed. Rules questions 1 and 2 of the 2026-08 foundation
audit's ruling docket. The code lands inside plan 3, beside the carrier-plane consumer.

**Spec:** governs two open questions in
[`stompcollider-technical.md`](stompcollider-technical.md) and one in
[`stompgeom-technical.md`](stompgeom-technical.md).

**Governed by:** [ADR-0006](../adr/0006-toolpath-ordering-and-hole-numbering.md),
[ADR-0008](../adr/0008-workspace-and-shared-geometry-core.md) and
[ADR-0009](../adr/0009-shared-model-package-and-dependency-order.md). This design
**amends ADR-0009**, whose `stompgeom` inventory assigns holedness to `levels()`.

## Scope

Two questions the audit refused to settle, because each had a documented answer and a
spoken one and an audit cannot rule between a document and a preference:

1. Is a board's substrate identified by the absence of an XCAF name, or by geometry —
   the largest horizontal plane with less than half its surface cut away?
2. Does carrier-plane detection need holedness, and does the promoted `levels()` take a
   direction or a kernel-axis index?

Both are prerequisites of plan 3's first geometry ticket. Ruling after `boards.py` is
written means rewriting it.

ADR-0009 says `levels()` "comes last, once `stompcollider`'s carrier-plane code exists to
shape its interface". No such code exists yet. What shaped the interface instead was
measurement against `fixtures/tar-pcb.stp` and the four cached Hammond models, which
turned out to answer questions a design discussion would not have reached — see
**Evidence** below. That substitution is deliberate and is recorded in ADR-0009's
amendment; it is not licence to skip a consumer generally.

## Evidence

Every figure below is a property of a committed fixture, not a run-dependent count. **The
implementing ticket carries each as a test assertion**, so a figure that drifts fails a
suite rather than quietly staling this document.

**`fixtures/tar-pcb.stp` is two boards.** 43 solids: 41 named with reference designators
(`R5`, `C3`, `D2`, …), 2 unnamed. The unnamed pair measure 91.50 x 17.00 x 1.51 mm and
106.50 x 53.75 x 1.51 mm, both spanning z 0.000–1.510, disjoint in y by 4.25 mm. A main
board and a strip, side by side and coplanar — not one board exported in two pieces.

**Holedness does not separate a board from a component.** Grouping every z-normal level
across the assembly and measuring each level's holed fraction:

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
rings. What the geometry rule attributes to holedness is done entirely by **area**.

**Global grouping is semantically empty.** That 576.79 mm² level is seven faces belonging
to D3, D4, RV1 and four other components that merely happen to be coplanar. A level is
meaningful only within one solid.

**A per-solid partition finds the carriers with no axis and no threshold.** Partitioning
each substrate's planar faces by their own outward direction and offset:

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

Equal areas, opposed directions, a 15–32x gap to anything else.

**Real normals deviate further from an axis than float noise.** Across every fixture, the
worst deviation from a kernel axis among faces the shipped acceptance test admits:

```
tar-pcb  strip substrate    worst off-axis  3.846e-08     levels 1e-9: 22, 1e-6: 21
tar-pcb  main substrate     worst off-axis  0.000e+00     levels 1e-9: 47, 1e-6: 47
1590B    BOX / LID / screws worst off-axis <6.8e-16       stable at every granularity
1590Y    Box / Lid / screws worst off-axis <1.3e-16       stable at every granularity
```

The strip carries one face tilted 38 nanoradians — export noise, not geometry. Every
Hammond solid is float-noise clean, so **`stompdrill`'s artefact bytes are safe at any
granularity considered here**; only the PCB fixture is sensitive.

## Decision 1 — name selects, slab-ness verifies

A solid XCAF gave a name is a component; an unnamed solid is a substrate **candidate**.
`stompcollider-technical.md:123-129` stands as written.

Each candidate is then **verified to be a slab**: its two largest levels must be
**exactly opposed**, of comparable area, and their offsets must sum to a thickness small
against the carrier's own extent. A candidate failing that test is not a board.

"Exactly opposed" is unambiguous and needs no tolerance: directions are integer keys, so
opposition is component-wise negation of one key by the other. The two proportions are
not: this spec fixes the *form* of the test and leaves both constants to the implementing
ticket, which calibrates them the way Decision 3 calibrates its granularity — from a
measured gap across every available fixture, stated with what lies on each side, and
carrying both probes. Writing a ratio here from one board would be the tuning this
document elsewhere refuses. The evidence it starts from: both substrates' opposed levels
measure *equal* areas to two decimals (1007.23 and 4344.96 mm²), and the next level down
is 15.7x and 32.5x smaller.

Holedness plays no part in substrate identification.

**Why.** The name rule is threshold-free, matched the fixture 41 to 2 with no tuning, and
partitions the faces by solid for free — which the evidence above shows is the only
granularity at which a level means anything. The geometry rule cannot count boards: the
two substrates are coplanar, so any global grouping merges them into one 5352.20 mm² plane
and recovering two would need face-connectivity analysis. And holedness, measured, does not
discriminate.

The verification step is what the name rule alone lacks. Its two failure modes are an
exporter that names nothing (43 substrates) and one that names everything (a clean
`no-substrate` refusal). The second is already correct; slab-ness catches the first, since
a resistor body is not a slab. The carrier normal falls out of the same test as its key.

`no-substrate` at `spec:129` and its row in the diagnostic table stay live.

## Decision 2 — `levels()` is a partition, not a filter

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
  separate sign field. One fact, one place. This retires the field ticket 55 had to repair.
- **Offset is signed along the outward normal**, so two opposed levels' offsets *sum* to
  the thickness — 0.000 + 1.510 above. Slab-ness is one addition, and `find_faces`'
  `abs(inner.position - drilled.position)` becomes a sum with no absolute value.
- **The harvest clump stops existing.** `docs/BACKLOG.md:662-676` requires that the ~22-line
  clump move with `_levels` and become "a named type rather than a bare tuple". Under a
  partition that takes a solid there is nothing to name: the harvest is `levels()`' own
  body. That entry's Acceptance is rewritten, not ticked.

**Why not the kernel-axis index.** The audit graded it as reaching the artefact as a wrong
placement rather than an error. Decision 1 removes that: a detector that verifies slab-ness
finds no slab on any swept axis when a board is tilted, and refuses loudly. Its remaining
cost is duplication — every consumer that must learn a normal writes the same sweep — which
is the duplication ADR-0008 exists to prevent.

**Why not a required direction.** The collider has to learn the direction before it could
pass one, so the sweep moves into the caller rather than disappearing.

## Decision 3 — coplanarity granularity is a millionth, with a control

The grouping key is integer, per the rule that no composite key holds a float: direction
components rounded to **millionths**, offset to whole nanometres.

The granularity is chosen from the gap the evidence measures, not picked round. The largest
real coplanar deviation is 3.846e-08; the tolerance the shipped acceptance test already
embodies is ~4.5e-5 rad. A millionth is 26x above the noise and 45x below the tolerance —
near the geometric midpoint of a three-order gap. This is the same form of argument
`_HOLED_FRACTION_LIMIT` uses for 50%.

A billionth was considered and **rejected by measurement**: it splits the strip's 98.15 mm²
side wall into 58.89 + 39.26 mm² — the same physical feature that produced ticket 55's
float-key defect.

**Keying, not clustering.** A distance-based cluster is order-dependent, which ADR-0006
forbids outright. The price of keying is that two faces straddling a rounding boundary
split; `_levels` already accepts exactly that hazard for position, so the precedent
licenses it rather than the argument being made fresh.

**The published `direction`** is the quantised key reconstructed and re-normalised to unit
length, so members of one level share a bit-identical direction and `CoordinateFrame`'s
1e-9 unit-length check has margin.

**Residual risk, named rather than engineered against:** two genuinely distinct planes less
than a microradian apart, through the same point, merge. Fillets and drafts are degrees.

**The control.** A granularity that merges everything and a correct one are
indistinguishable from a pass rate, so the constant gets both probes: at a billionth the
strip's side wall splits in two (guilty); at a millionth it stays one (innocent).

## Decision 4 — holedness stays in `stompdrill`

`_plates` and `_HOLED_FRACTION_LIMIT` stay where they are, operating on
`list[Level] -> list[Level]` and reading `Level.faces`.

**This amends ADR-0009**, whose inventory reads "`levels()` for grouping coplanar faces and
measuring holedness". That sentence anticipated carrier-plane detection as holedness's
second consumer; Decision 1 rules that consumer does not want it. Holedness therefore has
exactly one caller, discriminating a casting plate from a casting ring — enclosure reasoning
wearing a geometric coat, which is the test ADR-0009 applies four paragraphs later to keep
`build_frame` out of `stompgeom`.

The counter-case, stated fairly: "what fraction of a level's boundary is not real surface"
*is* describable without naming a panel, which is ADR-0008's admission test. If a third tool
wants it, it is promoted then, with a consumer in the room.

## Decision 5 — slab-ness lives in `stompcollider`

Decision 1's verification is four lines over `levels()` output and has one consumer. It goes
in the collider's `boards.py`. ADR-0009's `stompgeom` inventory grows by `levels()` and by
nothing else in this ticket — a five-item inventory that silently grows is the drift
ADR-0008:231-236 names as this package's own risk.

## `stompdrill`'s call site

`find_faces(solid, axis)` keeps its signature and its return type. It calls
`levels(solid, axis=...)` in place of its inline harvest and `_levels`, then applies
`_plates`, `_drilled_level`, `_inner_level` and `_nearest_companion_level` unchanged but for
reading `Level` instead of `_Level`.

**The `axis` filter carries `cad/case.py:151`'s parallelism test unchanged and inherited.**
Exact equality on the quantised direction is *not* equivalent: a face tilted a millionth off
axis quantises to a non-axis key and renormalises to `direction[2] = 0.9999999999995`, which
exact equality rejects where the shipped code accepts. Narrowing `stompdrill`'s acceptance
is not this ticket's to do.

Two tolerances, each with a distinct job, both stated where they act: the millionth
granularity decides *are these faces the same plane as each other*; the inherited 1e-9
parallelism test decides *is this plane aligned with the caller's axis*.

## Testing obligations

- **Partition properties**, which `_Level` never had and `stompgeom` can own without naming
  a panel: every planar face appears in exactly one level; levels are disjoint; the result
  is invariant under face traversal order, per ADR-0006.
- **The granularity control** of Decision 3, both probes, in `stompgeom`'s own suite.
- **The fixture assertions** of **Evidence**, so those figures fail a suite rather than
  stale this document. Both `tar-pcb` substrates yield two opposed equal-area levels whose
  offsets sum to 1.510.
- **Byte identity** through `stompdrill`'s suite under `--hammond` and `tools/verify-lock.sh`.
  The lock's verdict here is *predicted, not hoped for*: every Hammond solid is stable at
  every granularity measured, so a break means the port is wrong, not that the constant is.

## Document amendments this spec requires

| Document | Change |
|---|---|
| `docs/adr/0009-…:146-148` | Drop "and measuring holedness"; record Decision 4 and its measurement. Record that measurement stood in for the consumer, per **Scope**. |
| `docs/specs/stompcollider-technical.md:585` | Drop "and holedness" from carrier-plane detection. |
| `docs/specs/stompcollider-technical.md:155-156` | Confirmed correct; gains the carrier normal's provenance as the level's own direction key. |
| `docs/specs/stompcollider-technical.md:123-129` | Confirmed; gains the slab-ness verification of Decision 1. |
| `docs/BACKLOG.md:662-676` | Acceptance rewritten: no clump survives a partition that takes a solid. |
| `packages/stompgeom/src/stompgeom/__init__.py` | "The format side of geometry" widens; a partition is analysis, not format. |

## What this spec does not decide

Docket questions 3 through 7 — rigid placement, the clash boolean, the frame layer's third
dimension, `stompmodel`'s admission rule, and the kernel-helper promotions. Question 3 is a
prerequisite of the assembly emitter and question 4 depends on it.
