# ADR-0002: Domain quantisers — drill standards and the enclosure catalogue

**Status:** Accepted
**Date:** 2026-08-15
**Deciders:** Pavlo Vakhnivskyi (Artifact Instruments)
**Amends:** ADR-0001 (the pipeline stays; what the stages quantise onto changes)
**Supersedes:** the `DiameterStrategy` family — `ClusterDiameters`, `TableDiameters`,
`NoNormalization`
**Amended in place 2026-08-15** — the decision stands unchanged; one *fact* it rested on
does not. The per-part product PDFs it records as absent are now in `docs/parts/`, so the
0.05 mm catalogue work is unblocked. Marked at both places it is stated, below and in
Action Item 6, rather than edited away: an ADR is a dated record of what was known.

---

## Context

ADR-0001 established that all normalisation happens once, in the pipeline. It did not say
what a nominal value should be normalised *to*, and the answer it shipped with —
`ClusterDiameters`, which groups measurements and takes the mean of each group — turned
out to be an answer to a different question.

**The driving observation.** Clustering answers *"which of these measurements are the same
hole?"*, which is a question about the artwork. The question that gets a panel drilled is
*"which bit do I put in the chuck?"*, and its answer set is fixed by a bit series nobody
here gets to invent. Clustering 5.02 and 5.04 into a nominal 5.03 produces a size that
exists in no drawer on earth, and it does so silently, in the number the machinist reads.
Nothing downstream can tell that 5.03 from a real one. The tool had removed a
*disagreement between artifacts*, which is what ADR-0001 was about, and left a
*disagreement with the physical world*, which nothing was watching.

The same defect existed one level up. The reference outline is measured artwork: the
bounding box of a stroked path in a PDF, off by a fraction of a millimetre in both axes.
`tests/fixtures/tar.ai` measures 113.000 × 60.000 mm for a 1590B whose datasheet
footprint is 112 × 61. Everything downstream inherited that: the drawing dimensioned a
panel that does not exist, and a consumer computing edge clearance from
`reference.width` was out by half a millimetre on the axis where a jack barrel has least
to spare.

**Forces at play.**

- Two of the three quantities on a panel have an answer set that is *not ours*: drill
  sizes belong to a bit series, panel outlines belong to an enclosure catalogue. Only the
  hole *positions* are free, and those are already quantised onto a grid the operator
  declares.
- We cannot know another builder's needs. A talk-box pedal legitimately wants a 20 mm hole
  for the mic tube; the world holds far more enclosures than the 22 Hammond footprints we
  ship.
- The expensive failure remains the one ADR-0001 named — an artifact that states something
  false and looks perfectly well-formed.
- Single-operator project. A refusal costs a re-run; scrap aluminium costs a case, a
  panel and an evening.

---

## Decision

**Quantise each quantity onto the domain's own answer set, in its own stage.**

| Quantity | Answer set | Stage |
|---|---|---|
| Hole position | a grid the operator declares | `SnapPositions` (`snap`) |
| Hole diameter | a declared drill standard's sizes | `SnapDiametersToDrillTable` (`snap-diameters`) |
| Panel outline | the Hammond 1590 catalogue's footprints | `IdentifyHammondFootprint` (`identify-enclosure`) |

Five supporting decisions follow.

1. **A registry of drill standards, never one merged table.** `DRILL_STANDARDS` holds
   `metric` (183 sizes, generated from `METRIC_BANDS`) and `fractional` (64 sizes,
   `n · 25.4 / 64`). The operator declares one with `--drill-standard` and narrows it with
   `--drill-sizes` / `--no-drill-sizes`.
2. **A measurement matching no size in the declared standard is an ERROR and the hole is
   dropped**, and a run with any ERROR writes no artifacts at all.
3. **The catalogue stores the datasheet's whole millimetres**, generated from
   `docs/1590.pdf` by `tools/extract_1590.py`, never typed. Adopting Hammond's 0.05 mm
   per-part values is agreed and pending data (below).
4. **Silence is scoped to a unique match, and a declaration changes what silence means.**
   A unique match says nothing. On an undeclared run, no match is a WARNING and a tie is
   an ERROR. On a run that declared `--case`, every path ends in a confirmed match or an
   ERROR — nothing to check against, nothing that fits, or something else entirely.
5. **`EnclosureMatch` is a first-class field on `DrillData`**, not a `StageRun` parameter
   and not part of `SourceInfo`.

---

## Options Considered

### Option A: One generic `Quantize(values, tolerance)` stage

| Dimension | Assessment |
|---|---|
| Complexity | Low — one stage, three configurations |
| Cost | ~2 hours |
| Extensibility | Poor — every new domain arrives as a new argument |
| Testability | Medium — one code path, but each domain's rules untested separately |

**Pros:** The arithmetic really is the same in all three cases: find the nearest member of
a set, accept it if it is within tolerance. DRY at the level of the formula.

**Cons:** The formula is the only thing they share. The three differ in every decision that
matters — what the set *is* (operator-declared, physical constant, physical catalogue),
what a miss means (nothing, a dropped hole, a warning), what tolerance means (a quarter of
the grid pitch, half a bit step, a per-axis slack bounded by the catalogue's own closest
pair), and what a match produces (a moved hole, a rewritten diameter, a named enclosure
plus a resized outline). A generic stage would carry all of that as configuration, which
is the domain knowledge relocated rather than removed — and `Pipeline` stays clean only
because the mess moved to the caller.

Two concrete consequences settled it. `SnapDiametersToDrillTable` must **drop** an
unmatched hole while `SnapPositions` must **keep** one and `IdentifyHammondFootprint` must
leave the outline exactly as drawn; that is not a parameter, it is three different
behaviours. And `describe()` is a per-stage contract the drawing reads by name —
`last_run("snap")` for the grid, `last_run("snap-diameters")` for how a diameter is
spelled. Under one stage those three records would share a name and a shape, and the
drawing would be parsing a generic payload to find out which one it had.

### Option B (chosen): Three domain stages, each owning its own answer set

| Dimension | Assessment |
|---|---|
| Complexity | Medium — three stages, one catalogue module, one generated table |
| Cost | ~1 day |
| Extensibility | High — a new enclosure family is a new catalogue and a new stage |
| Testability | High — every rule is unit-testable, and the datasheet is re-extracted per run |

**Pros:** Each stage's docstring can name the specific failure it prevents, which is this
codebase's house style and has repeatedly proved load-bearing in review. Each carries its
own diagnostics, its own severity policy and its own `describe()` payload. The one thing
they genuinely share — "are these two floats the same?" — is already shared, in
`tolerance.within`.

**Cons:** Three stages of similar *shape*, which reads as duplication to anyone who has
not needed the differences yet. The stage list in `cli.build_pipeline` grows, and stage
order becomes a slightly longer thing to get right.

### Option C: Snap diameters onto the same grid as positions

| Dimension | Assessment |
|---|---|
| Complexity | Lowest — the code already exists |
| Cost | ~0 |
| Extensibility | n/a |
| Testability | High, and beside the point |

**Rejected outright, and it is worth writing down why**, because the arithmetic is
identical and the temptation is real. At `--grid 0.25` a measured 6.9998 snaps to 7.00,
which is correct — and a measured 3.15 snaps to 3.25, which is a bit nobody stocks, and a
measured 12.7 (1/2″) snaps to 12.75, which is a bit that does not exist in either drawer.
A grid is a property of the *drawing*; the drill table is a property of the *world*. We
can no more make a custom bit than we can make a custom case. Positions may be snapped to
a grid precisely because a position is ours to choose.

---

## Trade-off Analysis

**Why an unmatched diameter is an ERROR that drops the hole.** The old stage kept the
measurement and warned. That cannot survive the invariant the new stage carries: if every
nominal comes from the table, then a retained 30.0 is a nominal that came from nowhere,
and the drill file would define a tool for a bit that does not exist. Keeping it would
also make the *warning* the only thing standing between a fictional tool and a machine.

Dropping the hole creates the opposite risk, and it is the reason `_run` now writes
nothing when any ERROR exists. The Excellon format renders no diagnostics at all: a drill
file missing a hole looks perfectly well-formed. The drawing's NOTES block and the JSON
document would both carry the finding, and the file that actually goes to the machine
would carry a shorter panel. So the exit code is not the only guard — the artifacts are
withheld, and every path that was *not* written is printed, so nothing looks stale. Only
ERROR withholds; an enclosure we do not stock is a warning and must still produce a drill
file.

**Why the datasheet's whole millimetres.** The catalogue is generated from
`docs/1590.pdf`, because hand-transcribing 37 part numbers and 111 dimensions is exactly
the task a human gets wrong silently, and a wrong length means a panel drilled for a case
the operator does not own — discovered in aluminium rather than in a test. The whole
millimetre is also the number printed on the box the operator ordered.

**Why the values are not reconstructed as "imperial-exact".** Because Hammond specifies in
**metric** and derives imperial, which is the opposite of what the shape of the numbers
suggests. The 1590B product PDF gives 112.40 × 60.50 mm and 4.425″ × 2.382″: a clean
metric value producing an odd imperial one. Our 112 × 61 is a faithful rounding of that.
Reconstructing an inch-exact value would invent precision the datasheet does not claim,
and would invent it from the derived column rather than the specified one.

**The incident that proves the point: 113 × 60.** Hammond's *product web page* shows
113 × 60 mm for the same 1590B, which is derivable from neither the metric original nor
the series table. It is a double conversion, and it reproduces exactly on all three axes:

| Axis | True metric | ÷ 25.4 | Published inches (2 dp) | × 25.4 | Rounded |
|---|---|---|---|---|---|
| L | 112.40 | 4.4252 | 4.43 | 112.52 | **113** |
| W | 60.50 | 2.3819 | 2.38 | 60.45 | **60** |
| H | 31.00 | 1.2205 | 1.22 | 30.99 | 31 |

So a single 0.05 mm source produced **three** different published figures depending on the
rounding path: the series table's 112 × 61, the web page's 113 × 60, and the true value
itself. `tests/fixtures/tar.ai` was evidently drawn from the worst of the three — it
measures 113.000 × 60.000 and needs a 1 mm snap in each axis, *in opposite directions*.
That is why the catalogue is extracted from the series datasheet the repo ships and not
trusted to a per-part page: the failure is systematic, not a one-off typo, and it lands
inside the tolerance where it silently becomes the panel's dimensions.

**Why the catalogue was cross-checked by an independent derivation, not merely re-run.**
`tools/extract_1590.py` reads `page.extract_tables()`, which depends on pdfplumber's cell
geometry. Re-running it proves only that it is deterministic. The catalogue was therefore
also derived a second way, deliberately sharing no code with the first: a regular
expression over `page.extract_text()` lines, ignoring cell geometry entirely, anchored on
a part number at the start of a line and the three integers after the colour word. It
finds **144 dimensioned rows**, collapsing to the same **37 base parts** and the same
**36 distinct L × W × H triples** as the shipped table, with **zero difference** in either
direction. The next datasheet revision should know the method was cross-checked rather
than repeated — a table extractor and a text extractor failing identically is a far
stronger claim than the same extractor agreeing with itself.

**0.05 mm catalogue values: agreed, and blocked on data.** Hammond's per-part product PDFs
give dimensions to 0.05 mm (1590B: 112.40 × 60.50). Adopting them is agreed. It cannot be
done from what the repo holds: `docs/1590.pdf` contains exactly **two** decimal numbers in
the whole document, both of them `0.16` — the lid-height note — so the series table cannot
supply them, and the per-part PDFs are not in the repo.

> **Amended 2026-08-15 — the blocking condition no longer holds.** The per-part PDFs *are*
> in the repo: `docs/parts/` carries all 37 drawings, and `docs/parts/dimensions.tsv`
> carries the 0.05 mm L/W/H they yield, for every part, with a `source` column recording how
> each was obtained. Adoption is therefore unblocked, and what is left is a decision rather
> than a data hunt — `docs/BACKLOG.md` records it, including the ruling that the adopted
> values are stored as **integer microns** rather than floats. The paragraph above stands as
> the state of things when this ADR was accepted. **The two records below are unaffected and
> still bind**: they are about what adoption costs, not about whether the data exists.

Two things must be recorded now, because both are cheap to write down and expensive to
rediscover:

- **It is not a data swap.** `Enclosure.length_mm` / `width_mm` and
  `EnclosureMatch.length_mm` / `width_mm` are `int` *deliberately* — the JSON emitter
  documents `112` beside a `reference.width` of `112.0` as the distinction between the
  catalogue's nominal figure and the artwork's measurement, the drawing prints them
  unformatted, and `isinstance` assertions in the tests pin the type. Adopting floats
  ripples through the model, both emitters and their tests.
- **Hammond rounds half *up*; Python rounds half to *even*.** `round(112.40) == 112`
  agrees with the series table, but `round(60.50) == 60` while the series table says 61.
  Every other axis in the catalogue agrees under either mode, so this is invisible until a
  value lands exactly on the .5 boundary — and whoever checks the new 0.05 mm values
  against the shipped whole-millimetre table with the obvious `round()` will find exactly
  one axis of one part disagreeing and read it as a transcription error in the new data.
  Any future re-derivation must use `decimal.ROUND_HALF_UP`.

**Why silence is scoped to a unique match, and why the failures are not one severity.**
Saying "matched 1590B" on every run trains the operator to skim past the runs that matter,
so a unique match within tolerance says nothing at all. The failures are then not
variations of one finding:

- **A tie** (`ambiguous-enclosure`) and **a declared part the artwork contradicts**
  (`wrong-enclosure`) are ERRORs naming every candidate. Both are statements about *the
  operator's panel*, both are answerable by the operator, and a panel drilled for the
  wrong case is scrap aluminium.
- **No match at all** (`unknown-enclosure`) is a WARNING, and the asymmetry is the
  argument. A panel that omits a reference layer reaches the end of the pipeline untouched
  and exits 0, because no stage may assume a predecessor ran. An ERROR here would mean
  that *drawing* your outline is punished while *not* drawing it is not — backwards at any
  severity. Underneath: "two footprints fit yours" is about the panel, but "we have never
  heard of your enclosure" is about **our catalogue**, which holds 22 footprints where the
  world holds rather more. It is the same rule the drill table follows for a 20 mm mic
  tube: we cannot know what another builder is working in.

**A declaration is checked on every outcome, which is what makes `--case` worth typing,
and it adds two ERRORs of its own.** An operator who says nothing is owed a usable run; one
who claims the panel is a 1590B is owed the check they asked for, and a check that silently
does not happen is indistinguishable from one that passed. So:

- **`unverifiable-enclosure`** (ERROR) — a case was declared and there is no reference
  outline to compare it against. Same missing layer as the undeclared run that says
  nothing; the declaration is the whole difference, and the reference layer is what has to
  change.
- **`unmatched-enclosure`** (ERROR) — a case was declared and the outline does not single
  that part out, either because nothing fitted or because several footprints did and none
  was the declared one. Deliberately not `wrong-enclosure`: that code asserts we know what
  *was* drawn, and here nothing is identified, so the accusation would be unfounded — by
  the backplate convention below, the likeliest panel here is the declared case measured
  across its drilled face, and sending that operator to change `--case` sends them away
  from the fix.

Because a part belongs to exactly one footprint, a declaration always ends a tie — it
either resolves it or matches nothing — so `ambiguous-enclosure` and `unknown-enclosure`
are reachable **only from an undeclared run**. Neither is reused at ERROR for the declared
case: one `code` at two severities meaning two things is a key a consumer cannot route on.

**Why `EnclosureMatch` is a first-class model value.** It is neither provenance nor
configuration. `SourceInfo` says where the bytes came from and would be lying if it
carried a conclusion reached three stages later. A `StageRun` records what a stage was
*configured* to do — `identify-enclosure` ran, with a 1.5 mm tolerance — and never what it
concluded; `processing` is history, and a stage may legitimately run twice, whereas the
question "which enclosure is this panel?" must have one answer. Leaving the answer in the
execution log would send the drawing and every downstream consumer hunting through a
generic key/value history for a domain fact, which is the very inference `processing` was
introduced to stop. So `DrillData.enclosure` is replaced rather than appended, and it is
`None` — never a match naming no candidates — when nothing was identified.

**A 2-D outline identifies a footprint, never a part.** 37 catalogue parts collapse into
22 footprints because many differ only in height: 112 × 61 is 1590B, 1590B2 *and* 1590BS.
So the match carries `candidates`, and `selected_part` can only ever be filled in from
what the operator declared. Nothing may infer it from geometry; the artwork does not
contain it.

---

## The backplate convention

**The `Background` layer must be drawn to the enclosure's BACKPLATE dimensions.** This is
a convention the tool does not enforce and cannot infer, and it is the one piece of this
design a careful operator will get wrong, because the careful thing to do is to measure
the face you are about to drill.

A Hammond 1590 is die-cast with tapered walls — the datasheet calls out a "low side wall
draft angle (2° or less)" — so the drilled **face is smaller than the backplate**, by
`2 · d · tan θ` per axis, where `d` is the internal wall depth (catalogue heights include
the 4 mm lid). At the datasheet's 2°: 1.5 mm on the shallowest part (1590LLB, 25 mm),
**1.9 mm on a 1590B** (31 mm), 6.3 mm on the deepest (1590V, 94 mm). The catalogue stores
backplate dimensions, because that is what the datasheet's table gives.

The arithmetic says no tolerance can accept a face-drawn outline:

- **Required.** A face-drawn 1590B measures about 110.5 × 58.6 against a catalogue
  112 × 61, so matching it needs a per-axis tolerance of at least **2.4 mm** — on the
  shallowest common part, before any drawing error of the operator's own. Deeper cases
  need several times more, and no single value covers a catalogue spanning 25 mm to 94 mm
  of depth.
- **Permitted.** Two footprints tie when `2 × tolerance ≥ separation`, and the closest
  approach in the 22 footprints is 4 mm (1590B3 116 × 77 against 1590T 120 × 80). So the
  ambiguity ceiling is **below 2.0 mm**, which `tests/test_pipeline.py` pins directly:
  at 2.0 mm the tie is reported, at 1.99 mm it is not.

Required ≥ 2.4, permitted < 2.0. There is no value, at any depth, and widening the
tolerance to fit the shallow case would make the tool guess between two real enclosures on
every panel. So the convention is the fix rather than a number, and
`unknown-enclosure`'s message names it — a failure that teaches the fix costs a re-run,
where a silent one costs a case.

---

## Consequences

**Easier**

- Every nominal diameter on every artifact is a bit somebody can actually buy, and every
  reference outline is a case somebody can actually order.
- A drill file cannot silently contain a hole nobody can drill: the diagnostic is an ERROR
  and no artifact is written.
- A consumer reads the enclosure straight out of the JSON document rather than
  re-implementing the matcher against the catalogue.
- A datasheet revision is a re-run of `tools/extract_1590.py` and a red test, not a
  re-typing.

**Harder**

- The operator must declare their drawer when it is not the metric default, and must
  narrow it if their bench is narrower than the standard. The default is deliberately the
  widest practical union: a table that is too narrow refuses real work, whereas one that
  is too wide only ever offers a bit somebody has to buy.
- The backplate convention is undocumented in the artwork itself. Nothing in an `.ai` file
  says which face was drawn.
- Three stages of similar shape now sit beside each other, and the difference between them
  lives in their docstrings rather than in their signatures.

**To revisit**

- **0.05 mm catalogue values** — agreed, blocked on the per-part product PDFs. See the
  int/float ripple and the `ROUND_HALF_UP` note above.
- **A second, tighter diameter threshold** — "this snapped further than a real drawing
  ought to" as a WARNING is a genuinely different idea from `tolerance_mm`, which is a
  match/no-match bound. Tightening `tolerance_mm` to catch it would make a legitimate
  14.3 mm panel an ERROR and, by the drop rule, cost it the hole.
- **A second enclosure family.** `IdentifyHammondFootprint` names its catalogue in its own
  class name, which is honest today and is the seam to cut when a second family arrives.
- **Enforcing the backplate convention.** If a face-sized outline could be recognised *as
  such* — matched against a derived face table and reported as "this looks like the face
  of a 1590B; draw the backplate" — the convention would teach itself without a tolerance
  wide enough to guess. That needs per-part draft data we do not have.

---

## Action Items

1. [x] Replace the `DiameterStrategy` family with `DRILL_STANDARDS` and
       `SnapDiametersToDrillTable`
2. [x] Generate the Hammond 1590 catalogue from the shipped datasheet, and cross-check it
       by an independent derivation path
3. [x] `IdentifyHammondFootprint`, with the severity policy above
4. [x] Withhold every artifact from a run carrying an ERROR, and print the paths not
       written
5. [x] Carry the match into the JSON document (v4) and the drawing's title block
6. [ ] Adopt the 0.05 mm catalogue values — model, both emitters and their tests, with
       `decimal.ROUND_HALF_UP`. **Amended 2026-08-15:** the precondition this item was
       written against ("once the per-part product PDFs are in the repo") is met;
       `docs/parts/` and its `dimensions.tsv` hold all 37 parts, and the storage decision
       is integer microns. Still open, no longer blocked.
7. [ ] Decide whether the face-panel case can be recognised and named rather than merely
       refused
