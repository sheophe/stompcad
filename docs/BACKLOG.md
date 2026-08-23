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
include it, so it was left rather than decided. "Decide whether `_total_order`'s tie-break
clauses are reachable at all" (below) bears directly on this and is now settled by direct
test: `quantise.py:60`'s entry sort is confirmed, by reverting it, to be what guards the
invariant — both the pre-existing fixtures and the new generative property fail without it.
What remains open there is narrower, and does not change on its own whether the shuffle
loop is redundant: whether `_total_order`'s tie-break clauses are reachable at all in the
shipped pipeline. Either way, the sort runs before either instrument's holes reach routing,
so this decision should be made on what the shuffle loop checks beyond permutation stability
(if anything), not on which one "really" guards the invariant.

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

## Decide whether `_total_order`'s tie-break clauses are reachable at all

**Status:** Open question, not scheduled. Raised by ruling T9-1 during the verification
framework plan, 2026-08-22; corrected 2026-08-22 after the original finding was checked
twice independently and found false.

**Constraint:** An earlier version of this entry claimed that removing `quantise.py:60`'s
entry sort was caught by neither the pre-existing fixtures nor the new generative
permutation property, and that five mutants went uncaught. That claim was wrong. Replacing
the sort with `measurements = list(raw.holes)` makes five tests in `test_invariant.py` fail:
`test_a_panel_with_diagnostics_and_a_duplicate_is_permutation_stable`,
`test_a_panel_whose_hole_breaks_out_of_the_outline_is_permutation_stable`,
`test_a_panel_whose_holes_sit_on_a_grid_tie_is_permutation_stable`,
`test_no_permutation_of_any_hole_set_reaches_any_artifact` (the generative property itself),
and `test_the_bare_dedupe_stage_is_order_sensitive_and_quantise_is_what_saves_it`. The sort's
responsibility for the invariant is already pinned by tests that exist, and the generative
property is not vacuous — keeping it was right.

What no instrument exercises is `_total_order`'s tie-break clauses specifically. The
diameter-clause mutant — `return (-hole.y_nm, hole.x_nm, hole.raw.x, hole.raw.y)` — survives
both `test_invariant.py` and `test_route.py` untouched. That is because the sort normalises
arrival order before routing ever sees it, and after `Deduplicate` no two holes in a tool
block share a nominal position, so the raw tie-break clauses are unreachable in the shipped
pipeline.

**Acceptance:** Either a test demonstrates an input that reaches `_total_order`'s tie-break
clauses through the shipped pipeline (two holes with equal nominal position in one tool
block surviving to routing), proving them live code; or the question is answered by
inspection, recorded here, and a decision made on whether unreachable tie-break clauses
should be simplified or removed.

## Consolidate the repeated four-hole fixture and the nested-`Group` circle walker

**Status:** Confirmed gap, not scheduled. Raised by the final whole-branch review of the
verification framework plan, 2026-08-22, and backlogged rather than fixed because
consolidating across three files is more churn than that review's fix wave should carry
without per-task review.

**Constraint:** The same four-hole, two-diameter fixture — holes at `(-20_000_000,
18_000_000, 7_000_000, index=3)`, `(20_000_000, 18_000_000, 7_000_000, index=4)`,
`(-19_000_000, -18_750_000, 5_000_000, index=1)`, `(19_000_000, -18_750_000, 5_000_000,
index=2)`, on the same `ReferenceOutline(112_400_000, 60_500_000)` — is defined three times
under three names: `panel()` in `test_layer2_owned.py`, `panel()` in
`test_layer3_codecs.py`, and `sheet_panel()` in `test_recovery.py`. Separately, the walk that
finds every `Circle` inside a scene's nested `Group` items exists three times with similar
names and different filter semantics: `_scene_hole_circles`'s `walk` in
`test_drawing_agreement.py` (keeps circles carrying the `hole` class token), `circles`'s
`walk` in `test_layer2_owned.py` (keeps circles carrying a caller-supplied token), and
`scene_circles`'s `walk` in `test_layer3_codecs.py` (keeps every circle, converting each to a
sheet-nanometre tuple). This suite is meant as an exemplar other packages will copy, so the
triplication is house style debt, not a one-off. The concrete cost of leaving it: if `Scene`
grows a second container type, all three walkers must change and a missed one under-reports
silently, since each is a private recursive helper with no shared test of its own.

**Acceptance:** One shared four-hole fixture and one shared circle walker, living in
`tests/conftest.py` or a small helper module, replace all three copies of each. The walker's
interface accommodates the existing filter differences (by class token, or none) without
losing any of the three call sites' current behaviour, and the full stompdrill suite passes
unchanged.

## Build a text recovery, or accept the agreement test's coupling

**Status:** Open, unscheduled. Raised by the spec audit, 2026-08-22, which found
that §2's stated motive for the recovery subpackage was never fulfilled; §2 has
been amended to say so rather than to keep claiming it.

**Constraint:** `packages/stompdrill/tests/test_drawing_agreement.py:35` imports
`outline`, `panel`, `stream_of` and `strings_in` from `tests/test_drawing_pdf.py`.
That is the coupling the recovery subpackage was said to replace, and it could
not: the agreement test compares what two sheets *state* — schedule rows, notes,
title-block fields — while every recovery reads geometry. `read_pdf` returns
circles and an outline extent, and nothing under `tests/recovery/` extracts text
(no `Tj`, `LTChar` or `LTText` handling anywhere in it). `strings_in` would need
a `read_pdf_text` beside it, and `stream_of` exposes the raw content stream,
which is a different thing again and arguably belongs to the emitter's own tests.
Two of the four imports (`outline`, `panel`) are fixtures rather than parsers,
so even a text recovery leaves a fixture-sharing question behind it.

**Acceptance:** Either a `read_pdf_text` lands under `tests/recovery/`, the
agreement test migrates onto it, and the fixtures move somewhere neither test
module owns; or the coupling is accepted deliberately, with the reason recorded
next to the import so the next reader does not re-open this.

## Narrow `build_case_model`'s widened `except StompError`

**Status:** Deliberate deferral, not scheduled.

**Constraint:** `packages/stompdrill/src/stompdrill/cli.py`'s `build_case_model` catches
`StompError` where it once caught `StompdrillError`. The widening was forced rather than
chosen: the three error types that call can now raise share no base narrower than
`StompError`. Exit codes are unaffected, because `main` already funnels `StompError` to
the usage exit. The residual cost is precision — an `EmitterError` raised from that one
call would be relabelled a usage error rather than an emitter one.

**Acceptance:** The call catches `(StompdrillError, StompgeomError, DocumentError)`, each
of the three reachable failures still exits 3, and an `EmitterError` from that call is no
longer swallowed as a usage error.

## Give a `reframe` test a target frame that is not its own inverse

**Status:** Confirmed gap, not scheduled.

**Constraint:** No `reframe` test can detect its source and target arguments being
swapped. Every pair under test is a box/lid mirror, and a mirror transform is its own
inverse, so the swap is an identity. This holds in
`packages/stompdrill/tests/test_cad_region_synthetic.py` and in
`packages/stompmodel/tests/test_frames.py`, where it is cheapest to close. The argument
order is correct today; this is about what the tests would catch if it were not.

**Acceptance:** `packages/stompmodel/tests/test_frames.py` reframes through a target frame
carrying a genuine rotation rather than a pure mirror, and exchanging the two frame
arguments in `reframe` fails that test.

## Promote the kernel document builder into `stompgeom`, once plan 3 needs it

**Status:** Deliberate deferral, not scheduled. ADR-0008 records the same deferral.

**Constraint:** Assembling a document from placed, named, coloured solids ("build") has
exactly one caller today, and that caller is a test fixture — not a real second consumer,
so the interface is not yet designable. Plan 3's first geometry ticket is what supplies
one: it promotes the existing test-only builder into `stompgeom` with `placement` and
`colour` parameters, and the solid value gains whatever reading half that caller turns out
to need. `stompcollider`'s assembly emitter must not construct kernel documents itself.

**Acceptance:** The builder moves into `stompgeom`, taking `placement` and `colour`
parameters, once `stompcollider`'s assembly emitter is its real caller; the assembly
emitter calls it rather than building a document itself; and
`docs/specs/stompcollider-technical.md`'s Order of work section and ADR-0008 agree about
why it waited.

## Defer moving the CLI's usage/IO policy below `stompdrill`, until a second consumer exists

**Status:** Deliberate deferral, not scheduled.

**Constraint:** `stompdrill.cli` translates domain and IO failures into the workspace's
exit-code contract and withholds every artefact on any error. A second CLI-shaped consumer
would need the same policy, which argues for a shared layer below `stompdrill` — but today
`stompdrill` is the only implementation, and a shared layer with one implementation is the
speculative generality this repo's design rules forbid.

**Acceptance:** The policy moves below `stompdrill` once a second CLI-shaped consumer
exists to shape the interface against, not before; the ADR that governs it is amended in
the same change that moves it.

**Rediscovered, wave 2 (2026-08):** the transactional-write ticket considered folding its
own cross-file write policy into a shared command-line layer below `stompdrill` and
declined, for the identical reason recorded above — the coordinator's adjudication records
this rediscovery as a rejection by name. A future rediscovery of the same shape is Settled
by citing this entry, not re-argued from scratch.

## Two verified OCP kernel-binding segfault hazards

**Status:** Confirmed gap, not scheduled. Verified by experiment during the 2026-08
architecture review's ticket 04; recorded again at `stompgeom.step.label_name`'s docstring
and at `test_step.py`'s `_new_shape_tool` docstring, where a kernel-test author meets them.

**Constraint:** Two independent OCP behaviours fault the interpreter (exit 139) instead of
raising, so no `except` can catch either. A `TDF_Label` outliving the `TDocStd_Document` it
was drawn from dangles and faults on next use. `FindAttribute` on a live label carrying no
`TDataStd_Name` attribute faults rather than returning `False`, which is why `label_name`
checks `IsAttribute` first.

**Acceptance:** Not independently closeable — see "`stompgeom` should own kernel lifetimes
rather than expose them" below, which removes the hazard rather than merely documenting it.

## `stompgeom` should own kernel lifetimes rather than expose them

**Status:** Agreed direction, not scheduled. Raised by the user during the 2026-08
architecture review, on the strength of the two hazards above.

**Constraint:** Neither hazard above is guardable by a caller who only remembers a
convention — the penalty for forgetting is a process death with no traceback, enforced by
neither the type system nor an exception. `stompgeom` should never publish a bare label or
shape whose owning document a caller must keep alive by discipline; it should publish a
Python object that holds the document reference itself, so the lifetime is structural
rather than remembered. This generalises the kernel document builder's own deferral above
to every kernel handle `stompgeom` publishes, not only the builder's output.

**Acceptance:** Every public `stompgeom` value that wraps a kernel handle also holds
(directly or transitively) the document that handle depends on, so a caller cannot
construct a dangling reference by discarding the wrong object, and the two hazards above no
longer need a "keep both alive" convention to stay safe.

## Order "ban `Any` at package boundaries" behind "`stompgeom` owns kernel lifetimes"

**Status:** Agreed direction, ordered, not scheduled. Raised by the user during the 2026-08
architecture review; refines "Adopt mypy `strict` on `packages/stompdrill/src/stompdrill`"
above with where its argument actually lands.

**Constraint:** The `CaseModel` defect's own `Any` lived in `stompdrill`
(`StepOptions.model: Any | None`), which the strict-adoption item above already reaches —
`disallow_any_explicit` on `stompmodel` would not have caught it, and `stompmodel` carries
exactly one explicit `Any` in its source, so banning it there is nearly free. `stompgeom`'s
`Any`s sit at the kernel seam (`StepSolid.shape`, `StepDocument.document`, label parameters
throughout) and are honest — OCP ships no stubs — until the lifetime item above wraps them;
banning `Any` there first just pushes authors to an unsearchable `# type: ignore`.

**Acceptance:** `stompgeom` bans `Any` at its public boundary only after the kernel-lifetime
item above wraps the kernel handles it currently exposes bare; `stompmodel` can ban it
independently at any time, since the ordering does not apply there.

## A mutmut/hypothesis incompatibility blocks `dedupe` and `geometry`'s mutation surveys

**Status:** Confirmed gap, not scheduled. Found during the 2026-08 architecture review's
ticket 09.

**Constraint:** A `@given` method inside a pytest class trips hypothesis's
`HealthCheck.differing_executors` during mutmut's clean-baseline pass, aborting the survey
outright — reproduced at `test_snap.py`'s `TestSnapPositions`. This blocks `stompdrill`'s
`dedupe` and `geometry` mutation surveys, the two modules CLAUDE.md itself names as most
worth chasing, and it is a pre-existing incompatibility this review did not introduce:
`[tool.mutmut]` already documents two other cases where test structure aborts a survey.

**Acceptance:** Either the affected `@given` methods move out of their pytest class so
mutmut's baseline pass succeeds, or the incompatibility is reported upstream and worked
around, and `dedupe`/`geometry` get a real scoped mutation reading afterwards.

## Ticket 01's nanometre-guard singularity test is textual, not semantic

**Status:** Confirmed gap, not scheduled. Found during the 2026-08 architecture review's
ticket 01.

**Constraint:** `test_nanometre_guard_is_singular.py` detects a duplicate nanometre guard
by grepping for the literal phrase "whole number of nanometres" inside a
`raise TypeError(...)`; a future duplicate written with different wording (for example
`type(x) is not int: raise TypeError(...)`) evades it silently. The test enforces the
rule's wording, not the rule.

**Acceptance:** The test detects a duplicate guard by what it does — rejects a non-int
nanometre value — rather than by its message text, and a duplicate guard written with
different wording still fails it.

## `stompdrill`'s package root re-exports a signature naming a type it does not export

**Status:** Confirmed gap, not scheduled. Found during the 2026-08 architecture review's
ticket 06; relevant to plan 3, which reads this root.

**Constraint:** `stompdrill/__init__.py` re-exports `CaseModel` and `load_case_model`, but
not `OcpCaseModel` — and `load_case_model`'s return type is now `OcpCaseModel`.
`stompdrill.cad` exports `OcpCaseModel`, so the ticket's own wording ("exported from the
package that owns it") is satisfied, but a consumer reading only the package root meets a
return type the root itself will not give it.

**Acceptance:** Either `stompdrill/__init__.py` also re-exports `OcpCaseModel`, or
`load_case_model`'s published return type at the root is `CaseModel` (the protocol), and a
test at the root proves whichever is chosen.

## Take the `levels()` cut a level below where plan 3 currently plans it

**Status:** Confirmed gap, not scheduled. Found independently by two lenses in the 2026-08
architecture review's wave 1 (its own findings F1-07 and F2-04).

**Constraint:** `_levels` (planned for `stompgeom`) consumes an unnamed
`(area, position, outward, face)` clump, and the ~22 lines that build that clump — the
planar filter, the axis test, `TopAbs_REVERSED`'s sign, the area and the bbox position —
are inline in `stompdrill`'s `find_faces`. Whoever makes plan 3's `levels()` cut should take
the harvest along with the grouping and name the clump; sizing the task as "move `_levels`"
under-estimates it.

**Acceptance:** The cut moves both the clump's construction and `_levels` into `stompgeom`,
the clump is a named type rather than a bare tuple, and `stompdrill`'s suite passes
unchanged.

## Give `assembly_spans` and `_part_of` a home wider than `stompdrill.cad`

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F1-06).

**Constraint:** Both are private to `stompdrill.cad` today, and both feed a diagnostic that
more than one tool raises — the same duplication rule `check_millimetres`/
`check_nanometres` were published to close.

**Acceptance:** Either the two helpers move to a package both tools depend on, with an
admission rule naming the `stompcad`-visible reason, or the decision to leave them is
recorded with why the duplication is acceptable here.

## Delete `cli._options_for`'s type-hint introspection

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F2-05).

**Constraint:** `_options_for` inspects a constructor's type hints to route options, over a
map (`_OPTION_BUILDERS`) already one-to-one with the emitter registry — a Middle Man a
deletion test shows is not load-bearing.

**Acceptance:** `_options_for` is replaced by the direct one-to-one lookup, the deletion
test passes, and every existing emitter still receives its options unchanged.

## Give `Pipeline` a per-stage observation point

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F2-06).

**Constraint:** `Pipeline` exposes no per-stage hook, so `cli.run_pipeline` iterates it a
second time to produce `-v` output, and `stompcollider` would have to write the same
duplicated iteration to get the same five lines.

**Acceptance:** `Pipeline` (or `Stage`) exposes a seam a caller can observe each stage's
`StageRun` through as it runs, `cli.run_pipeline` uses it instead of its second iteration,
and both tools' `-v` output is unchanged.

## Refuse a zero or negative `--grid`, rather than clamping it

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F3-05).

**Constraint:** A zero or negative `--grid` is silently clamped to one micron with a
warning, while every neighbouring flag refuses nonsense outright as a usage error.

**Acceptance:** A zero or negative `--grid` is a usage error (exit 3) like its neighbouring
flags, the clamp-with-warning behaviour is deleted, and a test proves the refusal.

## Delete `_OPTION_BUILDERS`'s redundant `JsonOptions` entry

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F5-M1).

**Constraint:** `_OPTION_BUILDERS` carries a `JsonOptions` entry that the documented "New
emitter" rule says it should not need.

**Acceptance:** The redundant entry is deleted, `JsonEmitter` still receives its options
exactly as before, and the full suite passes unchanged.

## Correct the two docstrings that say the play area is pre-eroded

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F3-M1).

**Constraint:** `stompdrill.cad.base.CaseModel.margin_nm`'s docstring says "Clearance the
play area was already eroded by, at construction," and `CheckCaseClearance.describe`'s
docstring in `pipeline/clearance.py` repeats the claim (the margin "already eroded the
play area by it at construction"). Neither is true: `stompdrill.cad.loader.load_case_model`
builds `play_area_nm` as the flat face's raw `region_bbox_nm`, with no margin subtracted,
and the margin is applied only at query time, inside `region.contains`'s call from
`classify()`. The CLI's printed play-area line and the JSON provenance both restate this
same unenroded rectangle, so both overstate the usable area by twice the margin along each
axis. ADR-0007's own wording — the clearance rule is "the flat inner face's outer boundary
eroded by the margin" — describes `classify()`'s rule correctly and is not at fault.

**Acceptance:** Both docstrings state that `play_area_nm` is the face's raw extent and
that the margin is applied only inside `classify()`/`contains()`, not at construction, and
the CLI's play-area line and the JSON provenance either restate this plainly or carry the
same correction beside them.

## Make `region.build_region` refuse a structure wire it cannot subtract, instead of dropping it

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F3-M2).

**Constraint:** `stompdrill.cad.region.build_region` rebuilds the outer wire first and
raises `StompdrillError` when that rebuild does not complete (`if not builder.IsDone():
raise ...`). A few lines later, subtracting each structure wire (a boss boundary) uses
`if adder.IsDone(): region = adder.Face()` with no `else` — a subtraction that does not
complete is silently skipped, so that boss's boundary never narrows the drillable region.
`CheckCaseClearance` explicitly refuses to guess in the direction that would hide a real
obstruction; this fail-open path biases the other way.

**Acceptance:** A structure-wire subtraction that does not complete raises
`StompdrillError`, the same way the outer-wire rebuild already does, and a test drives an
`adder.IsDone()` failure directly (not through a real kernel geometry that happens to
trigger it) to prove the refusal.

## Give the model-side geometry helpers a real tie-break instead of kernel traversal order

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F3-M3). Adjacent to "`stompgeom` should own kernel lifetimes rather
than expose them" above; worth attaching to any future work that already touches
`build_frame`.

**Constraint:** `stompdrill.cad.case._inner_level` and `_nearest_companion_level`, and
`stompdrill.cad.region._floor_face` and `_proud_mm`, each pick among several kernel faces
or wires with a `max`/comparison over one property (area, position) and no explicit
tie-break clause. Where two candidates tie, Python's stable `max` returns whichever one
`TopExp_Explorer` happened to enumerate first — kernel traversal order, not a geometric
rule. A tie here decides the plate thickness, the drillable region, and the
relief-versus-structure verdict: the same class of ordering defect wave 1 closed on the
reader side with ADR-0006's total order over `Hole`.

**Acceptance:** Each of the four helpers breaks a tie on a stated geometric property,
never on enumeration order, and a test constructs two candidates with equal area/position
and asserts the same winner regardless of which one the kernel enumerates first.

## `wrong-case-model` names the operator's `--case` designator as the model's own

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F3-M4).

**Constraint:** `cli.build_case_model` passes the declared `--case` designator into
`load_case_model(part=...)`, so `OcpCaseModel.part` holds the operator's typed value
rather than a value read from the model file itself. When the footprint check in
`pipeline/clearance.py` raises `wrong-case-model`, its message ("the supplied {part}
model is...") therefore repeats the same designator on both sides of the mismatch whenever
`--case` was supplied. The refusal itself is correct and the payload's dimensions are the
model's true, measured ones — only the designator half of the sentence is misleading.

**Acceptance:** Either the message is worded so it cannot be read as comparing two
different designators when `--case` made them the same one (for example, naming the
supplied model by file rather than by declared part), or `part` falls back to a value read
from the model file (`_part_of(solid.name)`, already used when `--case` is absent) so the
two sides can genuinely differ; either way a test drives a mismatch with `--case` supplied
and inspects the message text.

## `route._two_opt`'s improvement threshold sits below its own floating-point noise floor

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F3-M5). Latent, not live: no artefact has been observed to change.

**Constraint:** `_two_opt` accepts a swap only when `delta < -1e-9`, an absolute
nanometre threshold. Over panel-sized legs, coordinate arithmetic carried out in
nanometres already accumulates roughly `1e-8` nm of representation error — an order of
magnitude above the threshold — so the comparison can in principle accept or reject a
swap on floating-point noise rather than a real improvement. Output stays deterministic
(the same arithmetic runs the same way on every invocation), which is why this is latent
rather than an observed defect.

**Acceptance:** The threshold is either justified in a comment, with the arithmetic
shown, as safely below any realistic panel's noise floor, or restated relative to the
route's own scale (for example a relative threshold, or one derived from the nanometre
representation error at the panel's size) so it cannot fall below the noise it exists to
filter.

## The AI-PDF reader's inherited graphics state is a four-value clump

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F2-05). **Considered and rejected as a fold, in the same wave**:
recorded so a future wave does not re-derive the fold and meet the same rejection again.

**Constraint:** `sources.ai_pdf._walk` threads four positional arguments — `ctm`, `clip`,
`marks`, `depth` — through every recursive call: one graphics state a nested form
inherits, carried as separate parameters rather than as one value. A `_GraphicsState`
value object was considered and does not clear this repository's folding guard: it
*relocates* the four values into one object rather than *concentrating* any behaviour, and
it adds a concept the reader does not otherwise need. `clip` joined the other three once
the page-clip theme landed, which makes the clump marginally worse, not better.
`stompcollider` does not inherit the AI-PDF reader, so this is local to `stompdrill` only.

**Acceptance:** Not scheduled as a fold. If `_walk` gains a fifth inherited value later,
re-weigh the fold then against that new shape, rather than treating this entry as already
having decided it.

## Give `Diagnosable` its first real adapter, without touching the deferred CLI half

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2 (its own finding F2-06). Not litigated: ADR-0009 admits `Diagnosable` explicitly
under its own admission rules, so the protocol having no consumer today is not itself a
defect.

**Constraint:** `stompmodel.protocols.Diagnosable` is implemented only by test fixtures.
`cli.format_diagnostics` and `cli.format_summary` already use exactly its surface
(`data.diagnostics`, `data.of_severity`) but are typed against the concrete `DrillData`.
Retyping those two annotations to `Diagnosable` would give the protocol its first real
production adapter without moving a line of code and without touching "Defer moving the
CLI's usage/IO policy below `stompdrill`" above, which stays deferred either way.

**Acceptance:** `cli.format_diagnostics` and `cli.format_summary` are typed against
`Diagnosable` rather than `DrillData`, both functions' behaviour is unchanged, and the
full suite passes.

## Make `make_emitter`'s failure handler cause-aware

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's
wave 2; the lens that found it deliberately did not file it as a theme. Recorded here so
the decision not to act on it this wave is visible rather than invisible.

**Constraint:** `cli.make_emitter` catches `TypeError` raised while constructing an
emitter and reports it as a usage failure at exit 3 (ruling 5 of the 2026-08 architecture
review's wave 1 settled that exit code for a registered emitter that cannot be
constructed). An emitter whose own `__init__` body raises a `TypeError` for a reason of
its own — not a missing or mismatched option the CLI failed to supply — is reported
identically, as if the CLI itself had passed the wrong arguments.

**Acceptance:** Either `make_emitter` distinguishes a `TypeError` raised by argument
binding (a genuine usage failure) from one raised inside an already-constructed emitter's
own body, with a test proving the distinction; or the decision to leave the two
indistinguishable is confirmed here in writing, with the reason.

## A reference-outline candidate straddling the page clip contributes its whole unclipped bounds

**Status:** Confirmed gap, not scheduled. Named by the 2026-08 architecture review's
page-clip theme and deliberately left unfixed there: no artwork reproducing it exists, and
the theme's own extent rule (a non-circular candidate is judged by its extent, a circle by
its centre) already governs the case; inventing a remedy for an exposure nobody has
reproduced would outrun the evidence.

**Constraint:** `sources.ai_pdf._largest_non_circular` compares reference-outline
candidates by `path.bbox` — the path's own unclipped bounding box — and `_entirely_outside`
only culls a candidate that shares no extent at all with the current clip. A candidate
that is only partly inside the clip (a rectangle bisected by a form's `/BBox` or the
page's crop box) is kept, and contributes its *entire* unclipped bounds rather than the
extent actually painted inside the clip. Because the reference outline sets the panel's
frame and centre, this one candidate can move every hole's reported coordinate.

**Acceptance:** Either reproduced with real artwork (a bisected reference-outline
candidate) and then fixed by clipping the candidate's contributed bounds to the region it
is judged in before comparison, or left recorded here until such artwork exists — not
fixed speculatively against a synthetic case alone.

## Promote the kernel compound-builder idiom into `stompgeom`, once a second consumer needs it

**Status:** Deliberate deferral, not scheduled. Recorded in the 2026-08 architecture
review's ticket 01 out-of-scope text; re-derived, and Settled, in wave 2 (its finding
F4-W2-01 — REFUTED as a claim that the deferral went unrecorded, but the underlying
duplication is real and unchanged). **A wave re-finding this triplication must cite this
entry and mark it Settled**, unless it now has a second consumer that makes the promotion
arrive as recognition — matching "Promote the kernel document builder into `stompgeom`"
above, a related but separate idiom.

**Constraint:** `stompdrill.cad.case` and `stompdrill.cad.region` each build a
`TopoDS_Compound` from several shapes with the identical `BRep_Builder()` /
`builder.MakeCompound(compound)` pair, at three call sites: `case.py`'s `_compound`
helper, `region.py`'s `_boundary` helper, and the `nearest_mm` closure inside
`region.py`'s `clearance_reason`. This is real, unchanged duplication, deliberately
deferred rather than folded: it has no second consumer yet to design the promoted
interface against, and folding it now would be Speculative Generality.

**Acceptance:** The three sites promote to one `stompgeom` helper once a real second
consumer (for example `stompcollider`'s assembly emitter) needs the same idiom; until
then this entry stands.
