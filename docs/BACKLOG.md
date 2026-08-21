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
