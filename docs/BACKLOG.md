# Backlog

Current work that is agreed or recorded but not scheduled.

## Paired redundancy review

**Status:** Agreed, not started.

**Constraint:** Claude and Codex review the source together, preserving behaviour and
public interfaces. Target about a 15% reduction in source lines through consolidation,
especially repeated drawing, formatting, parsing, and test helpers. Architectural
rationale belongs in ADRs; source reduction must not remove required documentation or
features.

**Acceptance:** The source is about 15% smaller with no loss of function. The full suite
passes, and targeted mutation checks demonstrate that each refactor preserved behaviour.

## Adopt mypy `strict` on `packages/stompdrill/src/stompdrill`

**Status:** Agreed, not started.

**Constraint:** Annotate one module at a time and keep the type gate green throughout.
Enable `strict` only after the implementation is clean. Keep each module's typing
change in its own commit.

**Acceptance:** `strict = true` is enabled for `packages/stompdrill/src/stompdrill`,
`mypy packages/stompdrill/src/stompdrill` reports no errors, and the test suite passes.

## Measure and, if necessary, reduce package import cost

**Status:** Noted; no implementation agreed.

**Constraint:** `import stompdrill` currently imports `pikepdf` because the package root
exports `AiPdfSource`. Do not introduce lazy loading without evidence that this cost is
material. If measurement justifies a change, preserve the root import contract and keep
`__all__`, `dir()`, and attribute access consistent.

**Acceptance:** A reproducible benchmark closes the item if the cost is immaterial. If the
cost is material, the implemented change demonstrates an improvement, avoids eager
`pikepdf` loading, preserves `AiPdfSource` at the package root, and passes the full suite.

## Cover every chain-dimension segment

**Status:** Confirmed gap, not scheduled.

**Constraint:** Exercise a row with at least three holes so omitting the first or last
consecutive pair cannot pass accidentally.

**Acceptance:** The test checks that each row has `len(stations) - 1` `dim-line` elements,
and a mutation that skips the first pair fails that test.

## ISO 3098 lettering

**Status:** Noted; no implementation agreed.

**Constraint:** The PDF sheet letters in base-14 Helvetica, so it is not ISO 3098
conformant. A true technical face (osifont, ISOCPEUR) means vendoring a TTF, subsetting
it, and clearing its licence — and, because both drawing backends share one text-fitting
estimate, adopting real font metrics for one would make the two sheets truncate the same
string at different points. Both backends move together or neither does.

**Acceptance:** Both sheets letter in the same conformant face, the licence is recorded
alongside the vendored file, and the agreement tests still show the two sheets stating the
same facts about every row they both list.

## Clarify what ADR-0001 means by the pipeline's "fixed composition"

**Status:** Noted; no implementation agreed. Downgraded 2026-08-21 after measurement.

**Constraint:** ADR-0001's Rationale says the stages' "fixed composition" is "read at the
invocation boundary". A review of every live restatement of the stage order — ADR-0001's
prose and Figure 1, ADR-0007, CLAUDE.md, the `cli` module and `build_pipeline` docstrings —
found all of them current and in agreement, including the conditional `CheckCaseClearance`
edge. Nothing here is stale, so this is a wording question and not a correction: "fixed"
could be read as denying that the fifth stage is conditional, when what the sentence means
is that the composition is settled *at* the boundary rather than negotiated between stages.
If it is touched at all, adjust only that connotation. Do not retrofit the Context or
Rationale's narration of the original decision, which is history.

**Acceptance:** Either the sentence is left alone with this entry closed as
"measured, no change needed", or one clause distinguishes "settled at the invocation
boundary" from "identical on every invocation", and Figure 1 is untouched because it is
already right.

## Run the unscoped `stompdrill` mutation survey once

**Status:** Confirmed gap, not scheduled.

**Constraint:** CLAUDE.md instructs the reader to run
`cd packages/stompdrill && mutmut run`, an unscoped survey of the whole package. Every
recorded run has been scoped to a handful of modules, so the documented command has never
been executed and its runtime, survivor profile, and any tests it aborts are all unknown.
Run it out of band before citing it again. Mutation testing is a survey and not a numeric
gate, so the output is a reading to record, not a threshold to meet.

**Acceptance:** The unscoped command has been run to completion, its wall-clock runtime
and per-module survivor counts are recorded, and CLAUDE.md's mutation-survey guidance
either matches what the run actually produced or is corrected to match it.

## Decide whether `numbered()` should validate its index set

**Status:** Confirmed gap, not scheduled. Raised by the test-repair review of 2026-08-21.

**Constraint:** `DrillData.numbered()` refuses unrouted data and pairs each hole with
`hole.index` in tuple order. It does not check that the indices it returns form a
permutation of 1..n, so duplicates and gaps pass; `Hole.__post_init__` only rejects an
index below 1. `RouteHoles` is the only assigner and does produce 1..n, so the gap is
currently unreachable through the shipped pipeline — but the accessor is the contract
every emitter reads numbers through, and it states less than its callers assume. Deciding
either way changes `stompmodel`'s published contract, so ADR-0006 is amended and accepted
before any code moves.

**Acceptance:** ADR-0006 records the decision. If validation is adopted, `numbered()`
refuses a non-permutation with a diagnostic naming the offending index, a test proves the
refusal, and the emitters' existing behaviour is unchanged. If it is declined, the ADR says
why, and the accessor's docstring states plainly that the index set is the router's
guarantee and not its own.

## Pass the case model to `build_pipeline` explicitly

**Status:** Noted; no implementation agreed. Raised by the test-repair review of 2026-08-21.

**Constraint:** `build_pipeline(args)` decides whether to append `CheckCaseClearance` by
reading `args.case_model_object`, a namespace attribute that no command-line flag names —
`build_case_model` stashes it there earlier in the run. Three call sites now read it, one of
them a test module that has to know the private convention in order to build the five-stage
composition. An explicit `build_pipeline(args, model=None)` would state the dependency in the
signature. Weigh that against the churn at `settings_from` and the two tests, and against
whether `args` should be the only parameter a builder takes.

**Acceptance:** Either the attribute is documented as the deliberate convention with the
reason recorded, or `build_pipeline` takes the model as a parameter, every call site passes
it, no caller reads `case_model_object` off the namespace, and the CLI's behaviour is
unchanged.

## Chase the four remaining `geometry` mutation survivors

**Status:** Confirmed gap, not scheduled. Raised by the test-repair review of 2026-08-21.

**Constraint:** A scoped survey of `_kappa_consistent` settled its fourteen survivors — six
killed by new tests, eight proved equivalent and left alive with the proof recorded. Four
survivors elsewhere in `geometry` were measured as untouched by that work and are not
covered by it: `fit_circle` mutmut_44 and mutmut_52, and `_quarter_turns` mutmut_11 and
mutmut_17. Each needs its own analysis. CLAUDE.md names `geometry` as a module where a
survivor is worth chasing, because it holds cited constants rather than placement, so these
are signal rather than noise. Classify each as killable or equivalent before writing a test,
and record any equivalence with its proof rather than reporting a clean sweep.

**Acceptance:** Each of the four is classified with evidence. Killable ones have a test that
fails against that mutant and no other; equivalent ones have a written argument for why no
input distinguishes them. The residual count for `geometry` is recorded as a number, not
implied to be zero.

## Give the shared stage contracts even depth per stage

**Status:** Confirmed gap, not scheduled. Raised by the test-repair review of 2026-08-21.

**Constraint:** `test_pipeline.ALL_STAGES` drives five parametrised cross-cutting contracts over
six stages, and the fixtures are generic, so which branch of a stage each contract reaches is
uneven by construction rather than by design. Instrumentation found one thin cell:
`test_stages_preserve_existing_diagnostics` builds data with no reference outline, so
`CheckOutlineContainment` takes its bare `return data` early exit and the contract holds
trivially — a "drop prior diagnostics" mutation of that stage is not caught by the contract
named for it, though it *is* caught by `test_stages_survive_empty_input`, so the property is
guarded. `CheckCaseClearance` is clean on the same measure, and `CheckReferenceSize` has ridden
these fixtures since before the grid was scrutinised.

A second, related gap: neither `test_containment.py` nor `test_clearance.py` can attach a prior
diagnostic, because both build data only through `make_data(...)`, which always sets
`diagnostics=()`. So no test anywhere exercises "a real finding-producing call still preserves
what came before" for those stages.

Widening the shared fixture is not a one-line change: it alters the branch every other stage
takes, so it needs evidence that coverage does not regress for the other four.

**Acceptance:** Either each (stage, contract) cell is shown to reach a meaningful branch, with
the mutation that proves it; or the redundancy argument is accepted in writing and the thin
cells are recorded so the grid is not mistaken for uniform depth.

## Retire `_kappa_consistent`'s eight equivalent mutants, if the file opens anyway

**Status:** Analysed and deliberately declined as standalone work, 2026-08-21. Do it only as a
rider on other work in `geometry.py`.

**Constraint:** Eight of the seventy mutants in `_kappa_consistent` are provably equivalent and
are recorded as the module's honest floor. Four double `travel` or `sense`; four turn `* ±1.0`
into `/ ±1.0`. Both families reach exactly one sign test, and both are unkillable without
asserting something with no observable manifestation. They can only be removed by making the
magnitude unrepresentable — carrying `travel` and `sense` as booleans and negating the tangent
conditionally, rather than multiplying by a unit float. That form has been checked equivalent
across all four sign combinations, signed zero included, and signed zero is immaterial anyway
because the guard is `dot <= 0.0`.

Declined standalone for three reasons. It buys no behavioural or readability gain — the
multiplication arguably reads better than a conditional negation. It trades eight *documented*
equivalent mutants for an unknown number of new ones, because the boolean literals, the
inequality and the negations are all fresh mutation sites whose survivor count cannot be known
until the survey is re-run. And the risk is asymmetric: the tangent direction is what makes
mirrored circles recognisable, so an inverted condition would make mirrored artwork stop
registering as circles and holes would vanish from a drill file. That failure is guarded — a
mirror test exists — but the reward is only a rounder survey number, and mutation testing is a
survey rather than a gate.

The containment is good and is what makes it cheap as a rider: the function is private, has one
production caller, changes no signature, and needs no ADR. The cost is entirely in re-proving
the verification surface — rotation invariance, mirrored recognition, and byte-identical
artefacts — which any other change to this file must re-prove regardless.

**Trigger:** take it when `geometry.py` is already open for another reason, such as the
generative conversion or the routing performance repair.

**Acceptance:** `_kappa_consistent` carries no unit-magnitude literal. The mirrored-circle and
rotation-invariance tests pass unchanged, the drawing-agreement and invariance harnesses show
byte-identical artefacts, and the scoped survey is re-run with every new survivor classified as
killable or equivalent — the residual stated as a number, never implied to be zero.

## Adopt the nightly symbolic tier

**Status:** Noted; adoption is conditional, not scheduled. Ruled out for the verification
framework plan, 2026-08-22.

**Constraint:** CrossHair over the integer core only — `dedupe.py`, `route.py`, and any
property expressible in nanometres. `units.py` and `snap.py` as written are excluded:
`Decimal(str(mm))` realises the symbolic float, and the spike measured one assertion going
from 0.20 s solvable to unsolvable-but-reported-passing. Evidence is in
`.scratch/test-audit/spike-symbolic.md`. Every property must carry a canary, because the
backend silently degrades to concrete execution on constructs it cannot handle — no timeout,
no warning, `metadata.backend` reporting `null` — so an un-canaried property that stops
failing would be measuring nothing rather than passing.

**Trigger:** take it when a bug is found that a property test missed at a boundary, not on a
schedule.

**Acceptance:** The tier runs nightly over the named modules, every property carries a canary
that is itself verified to fail against the CrossHair backend, and
`docs/specs/verification-technical.md` §5 records the tier as adopted rather than not adopted.

## Execute ADR-0008's governing test against a clean install

**Status:** Confirmed gap, not scheduled.

**Constraint:** ADR-0008's governing test is that each workspace member installs and passes
its own tests alone. `kinds.md` Gap 3's fourth check — `pip install packages/stompmodel` into
a throwaway venv — has never actually been run: it needs the network and tens of seconds, so
it belongs behind an opt-in marker beside `--hammond`, not the default run.

**Acceptance:** An opt-in test (or a documented manual command) performs the install into a
fresh venv and imports `stompmodel` from it, is marked so a standard run skips it, and passes.

## Decide whether the hole-reordering shuffle loop is redundant

**Status:** Confirmed gap, not scheduled.

**Constraint:** `kinds.md` argues the 20-shuffle loop in `test_pipeline.py` is subsumed by the
generative permutation property this plan added. The spec's list of four conversions did not
include it, so it was left rather than decided. "Confirm where ADR-0006's permutation
invariant is actually guarded" (below) bears directly on this: the permutation property
currently passes because `quantise.py:60` sorts every hole before routing ever sees it, not
because of tie-break machinery, so neither instrument may exercise tool-stability the way
either looks like it does.

**Acceptance:** A written decision either deletes the shuffle loop with the generative
property named as its replacement, or keeps both with a stated reason the property does not
subsume it — made after, not instead of, resolving the guard-location question below.

## Type the emitter registry

**Status:** Noted; no implementation agreed. Spec §8, out of scope.

**Constraint:** `make_emitter`'s return annotation and the registry it resolves through are
untyped. One change, when someone wants it.

**Acceptance:** The registry and `make_emitter`'s return type are annotated, `mypy packages`
stays clean, and no call site's behaviour changes.

## Move `RawDrillData` out of `quantise.py`

**Status:** Noted; no implementation agreed. Spec §8, out of scope.

**Constraint:** ADR-0009 explicitly placed `RawDrillData` in `quantise.py`; there is no import
cycle today, so the move has no forcing function. It needs an ADR amendment, taken when a
stage first needs `RawDrillData` in its own signature rather than as a hypothetical.

**Acceptance:** ADR-0009 is amended to record the new location and the reason a stage needed
it, `RawDrillData` moves to `stompdrill/raw.py`, and every import site updates in the same
change.

## Message `read_excellon`'s tool-lookup `KeyError`

**Status:** Confirmed gap, not scheduled. Found while building the Excellon recovery.

**Constraint:** `read_excellon` raises a bare `KeyError` when a body coordinate selects a tool
the header never defined. `_coordinates` cannot structurally produce this input today, and the
reader's stated scope excludes routing and slots regardless, but the surrounding reader is
otherwise strict about refusing informatively.

**Acceptance:** The lookup raises a messaged `ValueError` naming the undefined tool number,
and a test constructs the malformed input directly — not through `_coordinates` — to prove it.

## Separate layer 3's bundled `(x, y, diameter)` comparison

**Status:** Confirmed gap, not scheduled. Inherited from the plan text.

**Constraint:** Layer 3's SVG and PDF placement tests compare `(x, y, diameter)` as one tuple,
so a wrong diameter and a wrong position report as the same failure. Task 5's equivalent test
already separates the three; the SVG and PDF tests were written before that pattern settled.

**Acceptance:** Each of the three fields is asserted independently, and a mutation of any one
field alone fails only its own assertion.

## Give layer 3's order test a clean failure under a uniform-offset mutant

**Status:** Confirmed gap, not scheduled.

**Constraint:** Layer 3's rewritten order test currently fails via an unhandled `KeyError`
under a uniform-offset mutant, rather than a clean assertion message. The defect is still
caught; only the failure's legibility suffers.

**Acceptance:** The lookup uses `.get()` with a dedicated "position not found" assertion, and
the same mutant now fails with that message rather than a bare traceback.

## Give `cad/step.py` a public seam for an in-memory document's solids

**Status:** Confirmed gap, not scheduled.

**Constraint:** `read_step` takes a path; there is no public way to enumerate an in-memory
XCAF document's solids. The STEP recovery arm therefore reuses the private `_collect` plus
five lines of shape-tool glue that mirrors `read_step`'s own.

**Acceptance:** A small public function takes an in-memory XCAF document and returns its
solids, both `read_step` and the STEP recovery arm call it, and the duplicated glue is
deleted.

## Comment `fact_set`'s `"tools"` key before the golden is next regenerated

**Status:** Confirmed gap, not scheduled.

**Constraint:** `fact_set`'s `"tools"` key maps diameter to tool number, not to a
per-diameter hole count, and reads as counts on a fast skim.

**Acceptance:** A one-line comment at the key's construction states what it maps, so whoever
next regenerates `packages/stompdrill/tests/golden/tar-1590b.json` is not misled by the name.

## Triage acceptance rows 1, 6, 7 and 9 for a dedicated mutant

**Status:** Confirmed gap, not scheduled.

**Constraint:** The acceptance-test brief scoped a dedicated mutant to only two of its
contract-coverage rows; rows 1, 6, 7 and 9 have none. The implementer reported the gap
plainly rather than fabricating coverage.

**Acceptance:** Each of the four rows is triaged; any that needs a mutant gets one that fails
only against the behaviour the row names, and any row declined is recorded with the reason.

## Comment the distinct-keys dedupe property's coverage boundary

**Status:** Confirmed gap, not scheduled.

**Constraint:** The distinct-keys dedupe property does not, alone, catch an over-merging
defect that drops `diameter_nm` from the comparison key — a single wrongly-merged survivor is
trivially distinct from the rest. Coverage is sound in practice: the pre-existing
`test_does_not_collapse_different_diameters_at_the_same_place` and the new near-miss example
both close it, so the property complements adjacent tests rather than subsuming the
idempotence loop it replaced.

**Acceptance:** A comment beside the property states which named test carries the
diameter-key case, so a future reader does not mistake the property for standalone proof of
it.

## Shorten the `LATTICE_MM` comment, if the file opens anyway

**Status:** Informational; not a rule violation. Not scheduled.

**Constraint:** The 12-line `#:` comment above `LATTICE_MM` in
`packages/stompdrill/tests/test_invariant.py` is long, though `tools/check_docstrings.py`
walks `ast.Constant` docstrings only and does not flag it.

**Acceptance:** Closed by shortening the comment, or moving the rationale into a referenced
note, the next time the file is open for another reason — not worth a standalone change.

## Confirm where ADR-0006's permutation invariant is actually guarded

**Status:** Open question, not scheduled. Raised by ruling T9-1 during the verification
framework plan, 2026-08-22.

**Constraint:** Across five experiments, the generative permutation property added to replace
the reordering shuffle loop caught none of: the diameter-clause mutant at its shipped budget,
at a rebalanced budget, or with a diameter-jittered generator; three further `_total_order`
mutants; or the outright removal of `quantise.py`'s entry sort. Neither the pre-existing
fixtures nor the new property caught any of these five. The likely architectural reason is
that `quantise.py:60` sorts every hole before anything downstream — including routing — ever
sees it, so arrival order never reaches the tie-break machinery either instrument appears to
exercise. If that is right, the invariant ADR-0006 requires is guarded by that one sort
statement, not by `_total_order` or by either test — but no test yet isolates the sort as the
sole guard, so this is a documented finding rather than a proven one. (Snap's own conversion
is not in question here: a tie-step mutant demonstrably separates its old idempotence loop
from its new property, which the permutation case does not.)

**Acceptance:** Either a test is written that pins responsibility for the invariant on
`quantise.py:60`'s sort specifically — failing when the sort is removed and nothing downstream
compensates, passing otherwise — or the question is answered by inspection and the reasoning
recorded here, so the next reader does not mistake the generative permutation property for
evidence that tie-break machinery is exercised.
