# Verification: technical specification

How this project establishes that identical inputs produce semantically identical
outputs, and that every artefact of one invocation agrees with the others about
the geometry it describes.

## Relationship to `docs/FOUNDATION.md`

`FOUNDATION.md` is a model, not a backlog. **This specification does not
implement it.** It uses it the way a rulebook is used: to decide what must be
true, to name the properties precisely enough to argue about, and to keep the
obligations derivable rather than enumerated by taste.

Where this document cites a theorem — T1, T2, T4 — it is naming a property, not
a deliverable. Nothing here creates a type called `F`; the fact space is a
mathematical object, and what the code holds is whatever the design finds
convenient for comparing geometry.

## Scope

One project, three specced plans and one unspecced interleaving. It covers the
verification framework, the concrete gaps three audits found, the instruments
those audits found broken, two domain changes the audits exposed, and one
performance repair. The audit reports are at `.scratch/test-audit/`.

**The suite is a deliverable, not only a safeguard.** `stompgeom`,
`stompcollider` and `stompcad` follow, and whoever writes their tests will read
these for the house style — that is how the present gaps would propagate, not by
anyone deciding to skip a check. So this project is run before layer 2 begins,
and the pattern it sets is as much the point as the coverage it adds.

**T5 and T6 are out of reach here and belong to `stompcad`.** Composability needs
two instances to compose and uniform reduction needs several to reduce over;
with one tool they are theorems about a system that does not exist yet. They are
`stompcad`'s done-criteria, recorded here so they are inherited rather than
rediscovered.

Out of scope, and recorded as such in the last section: typing the emitter
registry, moving `RawDrillData`, and replacing the hand-rolled SVG and PDF
serialisers with libraries.

---

## 1. The verification layers

Three layers. The middle one is the load-bearing addition and follows from a
distinction the audits did not have: **the project owns everything up to the
codec, and codecs it did not write are trusted by design.**

**Layer 1 — the model.** `P` produces `DrillData`. Determinism (T1) is two
emissions in fresh processes compared as bytes. Denotational invariance (T1′) is
the same, over inputs transformed within their equivalence class. One committed
golden document guards against drift in `P` itself.

**Layer 2 — the last representation the project owns.** One per emitter,
compared against the model. These are Python values, so comparison is exact and
needs no parser. **Cross-artefact agreement (T4) is established here**, between
owned representations, not by parsing artefacts back.

**Layer 3 — the codec.** Bytes, checked at the depth the format warrants with a
recovery derived independently of the emitter.

| Emitter | Layer 2 — owned | Codec | Owner | Layer 3 check |
| --- | --- | --- | --- | --- |
| JSON | the document mapping | `json.dumps` | stdlib — trusted | round trip through `from_document` |
| STEP | the cut shape | `STEPCAFControl_Writer` | OCC — trusted | `read_step` plus face interrogation |
| SVG | the `Scene` | our serialiser, verified arithmetic-free | ours | `ElementTree`, full geometry |
| PDF | the `Scene` | our serialiser, owns a Y-flip, a scale and a Bézier circle | ours | `pdfminer.six`, full geometry |
| Excellon | none — model straight to text | our writer | ours | hand-rolled reader, full geometry |

The asymmetries are earned, not assumed:

- `drawing_svg._render_item` copies `cx`, `cy` and `r` from the primitive to the
  attribute and performs no arithmetic. Verify the `Scene` and SVG follows.
- `drawing_pdf` does not. It owns a frame flip
  (`_y(sheet, value) = sheet.height - value`, applied uniformly to lines and to
  circles), a `PT_PER_MM` matrix, and a kappa-Bézier circle construction. The
  last of these matters most: a PDF circle is four curves, so recovering a radius
  from one cannot be done by reading a field. This is the only owned transform
  nothing else reaches, which is why PDF is the one format whose independent
  recovery is load-bearing rather than belt-and-braces.
- Excellon has no layer 2 at all, so its byte-level recovery carries full weight.

**Verification effort is inversely proportional to how much of a codec was
outsourced.** That is a consequence of build-versus-buy decisions taken before
testing was in view, and it is the reason to spend unevenly rather than evenly.

## 2. The recoveries

Two exist already, written for other reasons: `stompmodel.codec.from_document`
and `stompgeom.step.read_step`. `read_step` returns placed solids, so hole geometry
needs face interrogation on top; that is the only new work on the STEP side.

Three are built, all test-support under `packages/stompdrill/tests/recovery/` as
uncollected helper modules:

| Format | Built from | Size |
| --- | --- | --- |
| Excellon | the format's definition — nine statement kinds, explicit decimals | ~35 lines |
| SVG | stdlib `ElementTree` over `<circle>` and `<rect>` | trivial |
| PDF | `pdfminer.six`, applying the CTM | ~11 lines of circle recognition |

They live in a subpackage rather than in test modules so that one place holds
every reader and one gate can enforce their independence, rather than each
reader living beside the test that first wanted it.

**This does not remove the coupling in `test_drawing_agreement.py`**, which was
the original motive and is not what was delivered. That test still imports
`outline`, `panel`, `stream_of` and `strings_in` from `tests/test_drawing_pdf.py`,
and no recovery here could replace them: it compares what two sheets *say* —
schedule rows, notes, title-block fields — and every recovery reads geometry.
`read_pdf` returns circles and an outline extent; there is no text recovery.
Closing that coupling needs one, and would be new work rather than a caller
migration.

**Independence is a gate, not a convention.** A test asserts that nothing under
`tests/recovery/` imports from `stompdrill.emitters`, by AST inspection — the
same shape as the package-boundary gate. A recovery that inverts its emitter's
own transform proves the emitter self-consistent and nothing more; the gate makes
that failure loud rather than invisible.

**Precision is declared per format and comparison is exact.** Each recovery
reports what its format states; the comparison rounds the canonical nanometre the
way that format rounds and demands equality. No epsilon anywhere except STEP,
which uses the kernel's `Precision::Confusion()`. This extends ADR-0003's
discipline to the readback.

That rule governs **comparisons**, and one threshold in the recoveries is not
one. `_MAX_RADIUS_SPREAD_PT` in `tests/recovery/pdf.py` decides whether four
on-curve endpoints describe a circle at all — a classifier, applied before
there is a measurement to compare, and the only threshold in the subpackage.
It cannot move a reported value: at 0.35% of the 100 nm the PDF recovery
reports to, the worst shape it can wrongly admit is off by 0.16 nm. A tolerance
that relaxed a comparison would be a violation however small it was; this one
decides what is measurable, not what a measurement is.

The comparison shape is a small frozen dataclass of recovered holes and outline
in canonical units, named-field rather than positional because transposing x and
y is the characteristic bug in a test helper. It is a comparison vocabulary for
the suite and does not go in `stompmodel`.

**What is deliberately not built:** a general artefact-reading capability. Each
recovery reads what this project's emitters write and nothing else. The Excellon
reader is short precisely because it declines slots, routing, unknown statements
and units other than `METRIC,TZ`, none of which our writer can produce. Implied
decimals are not among the rejections: `_HIT`'s pattern matches a coordinate with
no decimal point, and a real one would parse silently at the wrong scale — it is
unreachable from our own writer's `_coordinates`, which always states one, rather
than rejected by the reader. Hardening a test helper against inputs its only
supplier cannot generate is how a test becomes complex enough to need its own
tests.

## 3. Extractions

Refactor under test, except where the test cannot be written until the refactor
happens. That exception is narrow and dictates the order.

**Phase A, before any new test.** `render(scene, title)` on both drawing
emitters. `emit()` fuses layout, build and serialise, which is why the agreement
test reaches for `_serialise`, `_num` and `_render_item`; `layout()` is already
public, so this finishes a split that is half done. It must be a **pure split**:
byte-identical output, no redesign.

Phase A carries an obligation the other phases do not. It changes shipped code
before the semantic checks exist, and the migration's byte-comparison instrument
was deliberately deleted. So byte-identity across the split is proved by the same
throwaway method the migration used — emit before, emit after, diff — and the
instrument is discarded again afterwards.

**Phase B.** Sections 1 and 2.

**Phase C, protected by Phase B.**

- `write_payload(path, payload) -> int` into `stompmodel`. ADR-0005's dispatch is
  private in `cli.py`, tests reach for it, and `stompcad` needs the same
  byte-count convention for T6.
- Both drawing options types carry a `SheetText`. They are **not merged**:
  `sheet`/`scale` and `candidates`/`frame` feed genuinely different solvers, as
  `layout.py` and CLAUDE.md both record. Their real overlap is the ISO 7200 text,
  and moving that into the type that already exists takes the duplication to zero
  without pretending one solver is two.
- Title-block facts composed in `build.py` that belong in `content` per
  CLAUDE.md's own division, and the `'—'` literal hardcoded four times against a
  documented `ABSENT` constant.

**Declined and recorded:** the interface review's first recommendation was a
recovery per format in production. Only the seams ship; §2 addresses the
underlying complaint instead.

## 4. Disposition of the audit findings

| Group | Items | Lands as |
| --- | --- | --- |
| Contract coverage | layer flags never driven through the CLI; `hole-obstructed` and `wrong-case-model` never proved to exit 2; `unverifiable-enclosure` reaching no exit code; `drawing-svg` never asserted withheld on an error run; STEP's unrouted-data refusal; A1 sheet selection; `W*` clips; flag resolution before file open; the case model parsed once | acceptance tests |
| Hollow tests | `test_quantise.py:185`; `test_geometry.py:340`; `test_diagnostics.py:131`; the untested `duplicate-hole` message at `dedupe.py:47`; two half-matched refusals at `test_codec.py:630,639`; the redundant compound at `test_drawing_svg.py:1096`; four further compounds CLAUDE.md asks to be split; and `test_excellon.py:25`'s tuple-ordered fixture | repairs |
| Broken instruments | both mutmut configs; `[tool.mypy] exclude` missing `mutants/`; the boundary gate aborting the member survey | fixes |
| Generative | snap restated in nanometres; permutation invariant made generative; codec round trip widened; dedupe idempotence deleted for a distinct-keys property | conversions |
| End-to-end | console script, entry point, both `py.typed` markers | one `subprocess` test |
| Documentation | ADR-0001's "one to four emitters" and its three-stage diagram; ADR-0007's status | amendments |

### Domain changes

**Containment.** A hole outside the reference outline is a **warning**, reaching
exit 1 with artefacts written, checked whenever an outline exists and against the
hole's extent rather than its centre so that an edge breakout is caught. Face
containment remains the stronger model-based check. The code is
`hole-outside-outline`, joining the warnings that reach exit 1 in CLAUDE.md's
command-line contract, with an ADR amendment.

**Form nesting.** `_MAX_FORM_DEPTH` becomes `DEFAULT_FORM_DEPTH`, overridable
with `--form-depth`, which joins the flags resolved before the input file is
opened. The code is `nesting-truncated`, named for the condition that fires it
rather than for the limit. On
reaching the limit the reader **checks whether a deeper layer exists and warns
only if it does** — the fact worth reporting is that recursion was truncated, not
that a limit exists. Not an error.

The two are diagnosed differently for a reason worth recording. An off-outline
hole is observed and judged: it reaches the model and every artefact, and the
operator could in principle see it. A hole below the depth limit is never
observed at all — absent from the model, the artefacts and the report — so
silence there is indistinguishable from correctness. Both are warnings, but only
the second is invisible without one.

### The routing repair

`_two_opt` (`route.py:71-74`) scores each candidate reversal by rebuilding the
route and rescoring it end to end, when a 2-opt reversal changes exactly two
edges and is scorable in O(1). Line 74 is 97% of per-candidate cost and 99.96%
of candidates are rejected after paying it. Measured growth is Θ(n³) per
improvement sweep, with the sweep count data-dependent at 1–5 rather than
scaling with n; cost is cubic **per tool block**, and blocks partition n.

Not live — a 30-hole panel routes in 0.3 ms — but the repair is roughly ten
lines and takes Θ(P·n³) to Θ(P·n²). A prototype produced 96/96 identical routes
and byte-identical artefacts.

Three things constrain it:

- **ADR-0006 pins the algorithm**, not only the output: first improving
  reversal, fixed start, sweeping i&lt;j. An O(1) edge delta preserves all three
  and needs no amendment. Best-improvement or neighbour-list pruning would
  change the algorithm and must amend the ADR first.
- **Bit-exact reproduction has a weak float dependency.** Summing four terms is
  not guaranteed to compare identically to summing n square roots at a tie.
  Determinism itself does not depend on this — it comes from `_total_order` —
  but today's exact routes might. Unanimous across the prototype's testing, not
  provable by inspection, which is why the repair lands after the golden and the
  invariance tests exist. Measured, not proved: 86 synthetic blocks in total —
  the implementer's 32 up to n=90, plus 54 more across nine sizes up to n=140
  with six seeds each — compared hole by hole before and after, and both
  fixture panels byte-identical across all four formats; no route moved
  anywhere in that evidence. The risk stands unfalsified, not eliminated.
- **No existing test routes more than six holes.** The repair adds one at a
  realistic panel size.

The comment at `route.py:67-69` is corrected with it. Commit `ba44744` hoisted a
loop-invariant length, halved the constant, left the exponent, and left a comment
that reads as though the recomputation was dealt with — the artefact most likely
to stop the next reader from looking.

**Domain-edge preconditions.** `nm_from_mm` raises `decimal.InvalidOperation`
around 1e22, and `route.py`'s `_leg` raises `OverflowError` on absurd
nanometres. Neither is reachable from real artwork. Both are **documented as
preconditions** rather than guarded; a panel is physically bounded and inventing
a limit invites arguing about its value.

## 5. What runs when

| Tier | Contents | Cost |
| --- | --- | --- |
| Default | both suites: unit, acceptance, layers 1–3, recoveries, e2e | ~7.4 s + 0.4 s |
| `--hammond` | the above plus kernel tests against real enclosure models | ~65 s |
| Mutation survey | per package, run deliberately, read by module | minutes |
| Nightly symbolic — **not adopted** | integer-domain properties under the CrossHair backend | 7–25 s per property |

The default and `--hammond` costs are measurements, taken on one machine at one
commit, not budgets; they drift as the suites this programme added grow, and a
later reading is not a regression merely for disagreeing with the one recorded
here.

**The mutation survey must actually run.** Today the root config produces no
scored mutants and the member survey aborts, because the package-boundary gate
rejects the `import mutmut` that instrumentation injects — the same interaction
the root config already documents for `enclosures.py`. The gate is deselected
from the mutation run rather than given an exemption -- the shipped assertion
then stays exactly "stdlib or this package, no third name", and the anomaly
sits beside `do_not_mutate` where the other one already does. `[tool.mypy]
exclude` gains `mutants/` so that running a survey does not then break the
type gate.

**Every symbolic property carries a canary.** CrossHair degrades to concrete
execution on constructs it cannot handle, with no timeout, no warning, and
`metadata.backend` reporting `null`. A canary is a property with a known
symbolic-only counterexample; if it stops failing, the backend has disengaged and
the tier is measuring nothing. Adoption is conditional on it, and this plan does
not adopt it — see `docs/BACKLOG.md`, "Adopt the nightly symbolic tier".

Symbolic checking applies to the integer core only. `units.py` is excluded:
`Decimal(str(mm))` realises the symbolic float, and the spike measured the same
assertion going from 0.20 s solvable to unsolvable-but-reported-passing.

## 6. Decisions and their reasons

| Decision | Reason |
| --- | --- |
| Recoveries: seams ship, the rest are test-support | no caller outside a test will parse an Excellon file or a drawing; the shipped surface stays minimal |
| One golden, of the model | with T2 holding per format, a golden per artefact is redundant; one file, and updating it is a reviewable diff |
| Golden is a fact-set, not bytes | the panel path is provenance in four of five artefacts (STEP falls back to the literal `"stompdrill"` instead), so byte-golden fails on legitimate change |
| Recoveries independent of emitters | an inverted recovery proves self-consistency; the failure it must catch is a transform wrong in both directions |
| `pdfminer.six` as a dev dependency | five `uv.lock` entries, four of them transitive (`cryptography`, `cffi`, `pycparser`, `charset-normalizer`), buys the only independent view of the one owned transform nothing else reaches |
| Dedupe idempotence deleted | no plausible bug in `Deduplicate` breaks it; `diffbehavior` independently confirmed it survives both mutants |
| Containment warns rather than errors | the outline is the published top-view dimension, not the drilled face; the strong check needs a model |
| `_two_opt` repaired in Phase C, not earlier | its one risk is a float-summation tie changing a route, and the instruments that would catch that are what Phase B builds |

## 7. Order of work

Three specced plans, written and executed in order, with one unspecced plan
interleaved between the second and the third.

| Plan | Contents | Done when |
| --- | --- | --- |
| 1 — instruments and repairs | both mutmut configs, the mypy exclusion, the boundary-gate exemption, the three hollow tests, the fixture lapse, the ADR corrections | both surveys run and are read by module; the repaired tests fail when their named behaviour is removed |
| 2 — domain changes | containment, `DEFAULT_FORM_DEPTH` and its flag, the documented preconditions, contract and ADR amendments | both warnings reach exit 1 with tests that fail when either is removed |
| — test repairs (`docs/plans/2026-08-21-test-repairs.md`, merged as `0311209`) | four test-quality defects carried forward from Plans 1 and 2, closed alongside the wider classes each belonged to. States plainly that it "has no spec" — recon reports and a rulings file under `.scratch/test-repairs/` stand in its place | the four carried items closed; the two not worth fixing recorded in `docs/BACKLOG.md` instead |
| 3 — the framework | Phase A's split, the three recoveries, the independence gate, layers 1–3, the golden, the acceptance tests, e2e, the generative conversions, Phase C's cleanup and the routing repair | every emitter's owned representation checked against the model; the golden committed; every contract-coverage gap in §4 exercised by an acceptance test; one e2e drives the console script; `_two_opt` is Θ(P·n²) with routes unchanged |

**Why three.** Plan 1 is a prerequisite in fact: a survey that cannot run cannot
adjudicate whether Plan 3's tests are better, which is Plan 3's whole claim. Plan
2 changes behaviour while Plans 1 and 3 must not, and a reviewer applies a
different rubric to "prove nothing moved" than to "build a thing" — the same
split that made the three plans of the `stompcollider` specification work. The
interleaved test-repairs plan is orthogonal to this split: it neither adjudicates
a survey nor changes domain behaviour, so it does not disturb the rubric that
governs the other three.

## 8. Out of scope

- **Typing the emitter registry**, and with it `make_emitter`'s return
  annotation. One change, when someone wants it.
- **Moving `RawDrillData` to `stompdrill/raw.py`.** ADR-0009 explicitly placed it
  in `quantise.py`; there is no cycle today, and the move needs an ADR amendment
  when a stage first needs it in a signature.
- **Replacing the hand-rolled SVG and PDF serialisers with libraries.** Named
  here because §1 makes the position visible for the first time — two of five
  codecs are ours, and that is why two of five checks are expensive. Not
  proposed; the ISO 5457 sheet is bespoke and the change is large.
