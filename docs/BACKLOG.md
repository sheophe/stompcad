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

**Status:** Resolved by ticket 43 (2026-08). Raised by the test-repair review of
2026-08-21.

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

**Resolution (ticket 43, `a79d9d1`):** Satisfied in full, and both branches of the
Acceptance were taken at different seams. Declined at the accessor: `numbered()`'s
docstring now states plainly that the index set is the router's guarantee and not its
own. Enforced at the reader: the new `codec._read_holes` refuses a numbering no routing
stage could produce -- none absent, none repeated, none above the hole count -- with
`Hole`'s existing floor supplying the fourth fact, so the four together admit only
`1...n`. ADR-0006 is amended a fifth time, ahead of the code and in the same commit, with
the reasons for refusing the accessor: a fixture that numbers a lone hole out of range is
this workspace's own "read the number, not the position" instrument, and a legal
`Deduplicate`-after-`RouteHoles` composition owes a diagnostic rather than a constructor
refusal. `VERSION` stays 6 because every refusal added is over input no conforming v6
writer can produce. Closed; nothing further to do.

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

**Status:** Resolved by ticket 42 (2026-08).

**Constraint:** No `reframe` test can detect its source and target arguments being
swapped. Every pair under test is a box/lid mirror, and a mirror transform is its own
inverse, so the swap is an identity. This holds in
`packages/stompdrill/tests/test_cad_region_synthetic.py` and in
`packages/stompmodel/tests/test_frames.py`, where it is cheapest to close. The argument
order is correct today; this is about what the tests would catch if it were not.

**Acceptance:** `packages/stompmodel/tests/test_frames.py` reframes through a target frame
carrying a genuine rotation rather than a pure mirror, and exchanging the two frame
arguments in `reframe` fails that test.

**Resolution (ticket 42, `6e725b5`):** Delivered in full. `ROTATED`'s target is now a
quarter turn about `v` standing at a different origin rather than a half turn sharing its
origin, so the fixture is no longer an involution, and both clauses of the test were shown
failing independently under the argument swap this entry names -- shown by running it, not
by reading it. The branch's own report records the red run. Ticket 42's commit message asks
for this section to be deleted; it is closed in place instead, because this backlog's
"Rulings, for citation" preamble and ticket 46's own scope both keep an entry citable on
rediscovery rather than removing it. Closed; nothing further to do.

## Promote the kernel document builder into `stompgeom`, once plan 3 needs it

**Status:** Closed — the caller arrived and the builder moved. Recorded before that as a
deliberate deferral, which ADR-0008 recorded too.

**Constraint, as originally found:** Assembling a document from placed, named, coloured solids ("build") has
exactly one caller today, and that caller is a test fixture — not a real second consumer,
so the interface is not yet designable. Plan 3's first geometry ticket is what supplies
one: it promotes the existing test-only builder into `stompgeom` with `placement` and
`colour` parameters, and the solid value gains whatever reading half that caller turns out
to need. `stompcollider`'s assembly emitter must not construct kernel documents itself.

**Acceptance, as originally written:** The builder moves into `stompgeom`, taking
`placement` and `colour` parameters, once `stompcollider`'s assembly emitter is its real
caller; the assembly emitter calls it rather than building a document itself; and
`docs/specs/stompcollider-technical.md`'s Order of work section and ADR-0008 agree about
why it waited.

**Resolution:** All three. `stompgeom.build.build_document` takes
`PlacedSolid(shape, name, colour, placement)`, and `stompgeom.build.solid_colour` is the
reading half that caller turned out to need; `stompcollider`'s assembly emitter calls the
builder and constructs no kernel document of its own; and both documents record why it
waited. Closed; nothing further to do.

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

**Rediscovered, wave 3 (2026-08):** T13's design verdict (relocating the write mechanism into
`stompmodel.protocols.stage_payload`/`StagedWrite.commit`) weighed a batch-write helper or a
shared-CLI write layer again and rejected both, for the same reason — see "Wave 3's declined
and rejected design proposals" below. Two rediscoveries now cite this entry; a third should
too, unless it names a real second consumer the first two did not have.

**Rediscovered, wave 5 (2026-08):** ticket 40's design panel weighed giving
`stompcollider` its own duplicate-target rule -- it will need one, since
`docs/specs/stompcollider-technical.md` gives it two output paths in one invocation --
and refused to design it now, citing this entry rather than re-arguing it. That is the
third rediscovery this entry has absorbed, and the ticket left the note for the
coordinator to land here. A fourth should cite it too, unless it names the real second
consumer the first three did not have: `stompcollider`'s own command line, once it
exists, is exactly that consumer, so this entry is expected to become schedulable at
plan 3 rather than to be refused a fourth time.

## Two verified OCP kernel-binding segfault hazards

**Status:** One hazard closed by ticket 34 (2026-08); the other confirmed and still open,
not scheduled. Originally verified during the 2026-08 architecture review's ticket 04.

**Correction (ticket 34):** this entry's first hazard was factually wrong about its own
penalty. A `TDF_Label` outliving the `TDocStd_Document` it was drawn from does **not**
fault on next use, for every reachable label operation this workspace performs — it
answers **silently and wrongly**: not-null, an empty name, the document's own root entry,
and a null shape. Reproduced directly (`.scratch/architecture-review/design/wave4-t18-
probes-judge-v2.py`, P1/P5) and again by `packages/stompgeom/tests/test_step.py`'s
`StepLabel` tests. `stompgeom.step.StepLabel` closes it: a label reaches a caller only
inside the value that holds its document, so the published surface has no route to a
dangling one — see ADR-0008.

**Still real, untouched:** `FindAttribute` on a *live* label carrying no `TDataStd_Name`
attribute faults (exit 139) rather than returning `False`. `StepLabel.name` keeps the
`IsAttribute` guard that avoids it, unchanged by this ticket.

**Acceptance:** The dangling-label hazard's acceptance is met by `StepLabel`. The
`FindAttribute` hazard is not independently closeable by wrapping — it is a live-label
attribute-presence check, not a lifetime one — and stays open, guarded by convention at
its one call site.

## `stompgeom` should own kernel lifetimes rather than expose them

**Status:** Narrowed to labels and closed for that scope by ticket 34 (2026-08). Raised by
the user during the review, on the strength of the two hazards above.

**Correction (ticket 34):** the acceptance below as originally written ("*every* public
value that wraps a kernel handle") is too strong. A shape is independently
reference-counted and measures identically after its document is released; a document is
the anchor and cannot dangle by being held. Neither owes anything to a wrapper. Only a
label dangles, and only a label needed this.

**Constraint:** The hazard above is not guardable by a caller who only remembers a
convention — the penalty for forgetting is a silent wrong answer, not an exception.
`stompgeom.step.StepLabel` publishes the Python object that holds the document a label
depends on, so the lifetime is structural rather than remembered.

**Acceptance (narrowed, met):** Every public `stompgeom` value that wraps a kernel
*label* also holds the document that label depends on. Shapes and the document itself are
excluded by name: they do not dangle by being held, and wrapping them is not part of this
acceptance. Closed.

## Order "ban `Any` at package boundaries" behind "`stompgeom` owns kernel lifetimes"

**Status:** Unblocked, not scheduled — not deleted. Raised by the user during the 2026-08
architecture review; refines "Adopt mypy `strict` on `packages/stompdrill/src/stompdrill`"
above with where its argument actually lands.

**Constraint:** The `CaseModel` defect's own `Any` lived in `stompdrill`
(`StepOptions.model: Any | None`), which the strict-adoption item above already reaches —
`disallow_any_explicit` on `stompmodel` would not have caught it, and `stompmodel` carries
exactly one explicit `Any` in its source, so banning it there is nearly free. `stompgeom`'s
`Any`s sit at the kernel seam and are honest — OCP ships no stubs. Ticket 34 wrapped the
one handle whose validity depended on document lifetime (the label); the remaining six
names (`StepSolid.shape`, `StepDocument.document`, `bounding_box_mm`'s parameter and
others) stay bare `Any` **on purpose** — they owe nothing to a wrapper, so wrapping them
buys no safety and banning `Any` there would just push authors to an unsearchable
`# type: ignore`.

**Acceptance:** Unblocked now that the kernel-lifetime item above is closed for the class
of handle that needed it. Scheduling this item is still a separate decision: banning `Any`
at `stompgeom`'s boundary would apply only to the six honestly-bare names above, which is
a real trade-off for whoever schedules it to weigh, not a blocked precondition any more.

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

**Status:** Resolved by ticket 42 (2026-08). Found during the 2026-08 architecture
review's ticket 01.

**Constraint:** `test_nanometre_guard_is_singular.py` detects a duplicate nanometre guard
by grepping for the literal phrase "whole number of nanometres" inside a
`raise TypeError(...)`; a future duplicate written with different wording (for example
`type(x) is not int: raise TypeError(...)`) evades it silently. The test enforces the
rule's wording, not the rule.

**Acceptance:** The test detects a duplicate guard by what it does — rejects a non-int
nanometre value — rather than by its message text, and a duplicate guard written with
different wording still fails it.

**Resolution (ticket 42, `6e725b5`):** Delivered in full. The gate now decides on the
union of the rule's own mechanism -- an exact-int test whose body raises `TypeError` --
and the retained text match. Either arm alone is decided by wording or by spelling; the
union is the point. The family's guilty probe is paraphrased so it shares no wording with
any owner, so a gate that decides on prose fails against it, and that control runs in the
same suite by the same command. As with the `reframe` entry above, ticket 42 asked for the
section to be deleted and it is closed in place instead, for the same citability reason.
Closed; nothing further to do.

## `stompdrill`'s package root re-exports a signature naming a type it does not export

**Status:** Resolved by ticket 45 (2026-08). Found during the 2026-08 architecture
review's ticket 06; relevant to plan 3, which reads this root.

**Constraint:** `stompdrill/__init__.py` re-exports `CaseModel` and `load_case_model`, but
not `OcpCaseModel` — and `load_case_model`'s return type is now `OcpCaseModel`.
`stompdrill.cad` exports `OcpCaseModel`, so the ticket's own wording ("exported from the
package that owns it") is satisfied, but a consumer reading only the package root meets a
return type the root itself will not give it.

**Acceptance:** Either `stompdrill/__init__.py` also re-exports `OcpCaseModel`, or
`load_case_model`'s published return type at the root is `CaseModel` (the protocol), and a
test at the root proves whichever is chosen.

**Resolution (ticket 45, `03a19bd`):** The re-export branch was taken -- `OcpCaseModel` is
published from `stompdrill/__init__.py`. Narrowing the root's return type to `CaseModel`
was refused instead of chosen: it would replace an `ImportError` with the one value
`StepEmitter.__init__` refuses, and it contradicts ADR-0007:279-282's root-export mandate.
The name costs no new import and pulls in no kernel, because `stompdrill.cad` already
imports `.loader`. The root test this entry's Acceptance demands now exists:
`test_pipeline.py`'s `_unreachable_signature_types` gate, with two guilty probes (one per
clause of its compound condition) and one innocent probe; the gate was watched red against
the real root, reporting exactly `('load_case_model', 'return', 'OcpCaseModel')`, and it
finds six already-satisfied obligations, so it cannot pass by finding nothing. ADR-0007
gains the matching amended paragraph. Closed; nothing further to do.

## Take the `levels()` cut a level below where plan 3 currently plans it

**Status:** Closed — its own premise does not hold under the shape the cut took. Found
independently by two lenses in the 2026-08 architecture review's wave 1 (its own findings
F1-07 and F2-04).

**Constraint, as originally found:** `_levels` (planned for `stompgeom`) consumes an
unnamed `(area, position, outward, face)` clump, and the ~22 lines that build that clump
— the planar filter, the axis test, `TopAbs_REVERSED`'s sign, the area and the bbox
position — are inline in `stompdrill`'s `find_faces`. Whoever makes plan 3's `levels()`
cut should take the harvest along with the grouping and name the clump; sizing the task
as "move `_levels`" under-estimates it.

**Acceptance, as originally written:** The cut moves both the clump's construction and
`_levels` into `stompgeom`, the clump is a named type rather than a bare tuple, and
`stompdrill`'s suite passes unchanged.

**Why it closes instead of ticking:** `stompgeom.levels()` takes a solid and partitions
its planar faces directly into `Level`s keyed on their own outward direction and offset —
see ADR-0009's `stompgeom` inventory. There is no intermediate clump between the walk and
the grouping for this Acceptance to name: the harvest is `levels()`'s own body, and its
result is already the named type the Acceptance asked for. The premise — that a clump
survives the cut and merely lacks a name — does not hold, so the entry closes on that
ground. Closed; nothing further to do.

## Give `assembly_spans` and `_part_of` a home wider than `stompdrill.cad`

**Status:** Closed, one helper on each branch of its own Acceptance. Found in the 2026-08
architecture review's wave 1 (its own finding F1-06).

**Constraint, as originally found:** Both are private to `stompdrill.cad` today, and both
feed a diagnostic that more than one tool raises — the same duplication rule
`check_millimetres`/`check_nanometres` were published to close.

**Acceptance, as originally written:** Either the two helpers move to a package both
tools depend on, with an admission rule naming the `stompcad`-visible reason, or the
decision to leave them is recorded with why the duplication is acceptable here.

**Resolution:** `assembly_spans` moved: it is `stompgeom.step.assembly_spans` now — the
bounding-box span of every solid together, per axis, in millimetres, describable without
naming a panel — and its named `stompcad`-visible reason is `wrong-case-model`, raised by
`stompdrill`'s clearance stage today and specified for `stompcollider`'s own model check
(`docs/specs/stompcollider-technical.md`'s diagnostic table), so one span computation
serves both rather than two. `_part_of` did not move: it is `product_name.split()[0]`,
naming policy rather than geometry, and no geometric rule is duplicated by leaving it in
`stompdrill.cad` — the record this Acceptance's second branch asked for. Closed; nothing
further to do.

## Delete `cli._options_for`'s type-hint introspection

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 1
(its own finding F2-05).

**Constraint:** `_options_for` inspects a constructor's type hints to route options, over a
map (`_OPTION_BUILDERS`) already one-to-one with the emitter registry — a Middle Man a
deletion test shows is not load-bearing.

**Acceptance:** `_options_for` is replaced by the direct one-to-one lookup, the deletion
test passes, and every existing emitter still receives its options unchanged.

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

## Delete `region.build_region`'s always-true `if adder.IsDone()`

**Status:** Resolved by ticket 50 (wave 6). Found in
the 2026-08 architecture review's wave 2 (its own finding F3-M2); re-verified and refuted
in wave 5's confirm phase (C7). Its own title has changed: the entry used to ask for a
refusal, and there is nothing to refuse.

**What was claimed.** `stompdrill.cad.region.build_region` rebuilds the outer wire first
and raises `StompdrillError` when that rebuild does not complete (`if not builder.IsDone():
raise ...`). A few lines later, subtracting each structure wire (a boss boundary) uses
`if adder.IsDone(): region = adder.Face()` with no `else`, so -- the claim ran -- a
subtraction that does not complete is silently skipped and that boss's boundary never
narrows the drillable region. `CheckCaseClearance` explicitly refuses to guess in the
direction that would hide a real obstruction; this looked like a fail-open path biasing the
other way. **This entry was ranked as the item that reaches aluminium** -- the most
dangerous on wave 5's frozen list.

**Why the premise is false.** Both halves were proved independently and only one held.
The *consequence* is real: forcing `IsDone()` false does flip a hole centred on a 3.0 mm
proud boss from not-clear to **clear**, silently, so had the branch been reachable it would
have passed a hole through structure. But the branch is not reachable.
`BRepBuilderAPI_MakeFace::Add` sets `FaceDone` **unconditionally** -- demonstrated against
the installed OCP kernel with nine hostile wires (non-planar, open, self-intersecting,
off-surface), every one of which returned `FaceDone`. The `if` is dead, not fail-open, and
no clearance verdict is at risk. The ranking was wrong and is recorded as wrong here so a
later wave cites this rather than re-promoting the item.

**Acceptance (narrowed to the residue).** One always-true `if` is deleted --
`if adder.IsDone(): region = adder.Face()` becomes the unconditional
`region = adder.Face()`, at `packages/stompdrill/src/stompdrill/cad/region.py` (line 100 at
the time of writing; locate it by its text) -- the change is byte-identical on every
artefact, and no test asserts the dead branch. Cosmetic, so **list A**, and it must be
taken **after ticket 44 has merged**, because ticket 44 owned `cad/region.py`. That
condition is now satisfied: ticket 44 merged at `07d7f66`.

**Resolved by ticket 50 (wave 6).** The `if` is gone and `region = adder.Face()` is now
unconditional. Two corrections this entry's own wording invites, both established by ticket
50's own probe rather than inherited. First, wave 5's demonstration ran against a *different*
construction -- a `BRepBuilderAPI_MakeFace` built from a wire -- so the re-probe against the
constructor this call site actually uses, one built from an existing face, was necessary
rather than ceremony; every hostile wire still reported done. Second, "the `if` is dead" is
the imprecise form. `IsDone()` is *false* on a builder freshly constructed from a face, and
only `Add` forces it true, so the flag is genuine and observable: what is unconditional is
`Add`'s setting of it. A restatement that keeps the loose wording leaves a reader concluding
`IsDone()` is a stub. A default-constructed null `TopoDS_Wire` passed to `Add` segfaults the
kernel rather than reporting not-done; that is unreachable from `classify_bounds`, so it is
not a defect, but it is the sharpest available statement of why no guard at this point could
have helped.

## Give the model-side geometry helpers a real tie-break instead of kernel traversal order

**Status:** Resolved by ticket 44 (2026-08). Found in the 2026-08 architecture review's
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

**Sharper evidence (wave 4, M3-02):** two of the four do not even agree on what "by area"
means, and one's docstring claims otherwise. `region._floor_face` picks the single largest
**face** by its own area inside a compound; `case._inner_level` picks by the **aggregate**
area of every face grouped into a level (`_Level.area = sum(item[0] for item in members)`,
and `_plates`'s own comment states the choice is deliberate: "on the level's aggregate
areas, not per face"). `_floor_face`'s docstring nonetheless says it picks "exactly as
`case._inner_level`/`_drilled_level` pick by area too" — false: the two use different
metrics, not the same rule stated twice. Confirmed by reading both functions; unreachable
on the four cached Hammond models, so it has not yet produced a wrong artefact. This
sharpens rather than replaces the tie-break gap above: two candidates could tie under one
metric and not the other, so a fix to this entry's own tie-break defect should settle
*which* metric each helper is meant to use before adding the tie-break clause, and correct
the docstring's false claim of agreement in the same change.

**Acceptance:** Each of the four helpers breaks a tie on a stated geometric property,
never on enumeration order, and a test constructs two candidates with equal area/position
and asserts the same winner regardless of which one the kernel enumerates first. The fix
also states, for `_floor_face` and `_inner_level`, which metric each uses and why they
differ, and corrects `_floor_face`'s docstring to stop claiming agreement it does not
have.

**Resolution (ticket 44, `6e66bc1` then `2eaacb2` and `660a94f`):** Closed in full,
including the wave-4 area-metric clause and `_floor_face`'s false docstring. Each of the
four helpers now names its winner from the candidates' own geometry, and the secondary key
is consulted only where the primary compares exactly equal: `case._inner_level` ranks
aggregate area and breaks a tie by nearness to `drilled`; `case._nearest_companion_level`
ranks distance from `inner` and breaks a tie towards the **proud** side (`+inner.outward`);
`region._floor_face` ranks one face's own area and breaks a tie on the whole-nanometre
bounding box, lexicographically greatest, in `bounding_box_mm`'s own order (minima before
maxima); `region._proud_mm` ranks the in-plane footprint gap and breaks a tie towards the
most proud. `_floor_face`'s docstring no longer claims agreement with `case._inner_level`
that it does not have -- the two metrics are stated, and stated as different. Every
tie-break ships a guilty probe whose fixture asserts its own exact tie in the body, and
an innocent probe proving the new key is a tie-break and not a co-primary; both
owned test modules are `--hammond`-marked at module scope. No primary comparison, threshold
or cited constant moved and the behaviour lock held unmoved. The tie direction was
corrected once mid-ticket: round 1 transcribed `region.py`'s then-inverted prose and pointed
the companion tie at the receding side, which would have let a receding face be bundled into
`Faces.inner` beside a real boss and passed a hole straight through it; measured against the
real cached 1590BB, the proud side is `+inner.outward`, away from the drilled face. That
prose inversion was itself fixed in `660a94f` at all four of its sites, so nothing is left
outstanding from it. Closed; nothing further to do.

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

**Resolution:** Closed. `stompgeom.shapes.compound(shapes)` is that helper, and the second
consumer arrived: `stompcollider`'s clash stage builds a board's solids into one compound
through it, and the assembly emitter reaches it through `build_document`. The three
`stompdrill` sites call it rather than repeating the `BRep_Builder()` pair; the remaining
`MakeCompound` calls in the tree are fixtures building geometry, which is not the
duplication this named (`grep -rn "MakeCompound" packages --include="*.py"`). Closed;
nothing further to do.

## `CheckCaseClearance` is stateful, and nothing states the `apply`-before-`describe` order it relies on

**Status:** Confirmed gap, not scheduled. Found independently by three lenses in the 2026-08
architecture review's wave 3 (F2-05, M3-02, F1-06); recorded once because all three name the
same mutable field.

**Constraint:** `pipeline/clearance.py`'s `CheckCaseClearance` assigns `self._checked_frame`
in `apply()` and reads it back in `describe()` — the only self-mutating stage in the
workspace — so that two statements of one fact keep agreeing: the reconciled frame, typed on
`DrillData.case.frame`, and the play area, string-keyed in `StageRun.parameters`. Nothing
pays today: `Pipeline.run` always calls `apply` then `describe` on one instance, and
`_checked_frame` defaults to the model's own frame, so an out-of-order `describe()` degrades
to the unreconciled play area rather than crashing. Two observations travel with it.
`stompmodel.protocols.Stage`'s own docstring — "A deterministic preprocessing step
independent of pipeline position" — states nothing about an ordering obligation between its
two methods, so a second implementer (`stompcollider`'s `Match`/`Seat` stages,
`docs/specs/stompcollider-technical.md`'s "Internal architecture") meets no warning before
writing the same shape.
`apply`/`_play_area_in` used to decide whether to reframe by testing
`frame is self.model.frame` — object identity, which the concrete `OcpCaseModel` dataclass
happens to preserve but which the `CaseModel` protocol never promises. Ticket 51 replaced
both with `==`, the equality the protocol's read-only-property declaration actually
supports: a computed-property implementation of `.frame`, which under identity would have
taken the reframe branch on every access, is exactly the case the equality now serves. The
`TwinFrameCase` fixture in `packages/stompdrill/tests/test_pipeline_clearance.py` is a live
example of that implementation shape.

**Acceptance:** Either `Stage.describe()`'s docstring states the ordering obligation a stage
may rely on (or forbids one) and `CheckCaseClearance` keeps or loses its mutable field to
match; or the field is removed by moving `play_area_nm` onto `CaseRegistration` (the fix
wave 2's ticket 12 ruled out of scope as "not yet true of the play area" — a ground this
wave's reconciliation changed, since a play area now needs the reconciled frame to be stated
at all). Either way, the identity comparisons are replaced by an equality the `CaseModel`
protocol actually promises, or the protocol is amended to promise identity.

**Wave 5 confirm (C9), and the wave-6 outcome:** re-verified against HEAD in wave 5, where
both identity comparisons were still present. **Ticket 51 (wave 6) discharged the final
clause of the Acceptance above** -- *replacing those identity comparisons with an equality
the `CaseModel` protocol actually promises*. Both sites now compare by value. It was Minor,
because the shipped `OcpCaseModel` is a frozen dataclass whose `.frame` really is one object,
so the change was byte-identical on every artefact the behaviour lock hashes and on every
model this repository can fetch; the lock confirmed that at the merge. The widened `==`
admits no false positive either: `_reconciled_frame`'s quarter-turned frame (u <- v,
v <- -u) can never compare equal to its source for an orthonormal basis. The rest of this entry
is left standing exactly as written: the confirm evidence addresses only the identity
clause and says nothing about the mutable field, the `Stage` docstring, or moving
`play_area_nm` onto `CaseRegistration`, so none of those is narrowed here.

## The checked registration does not record whether it was reconciled

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(M3-01). The fix considered for it — a boolean field — was weighed and declined; see "Wave
3's declined and rejected design proposals" below for the reasoning.

**Constraint:** `CaseRegistration` carries `frame` with no record of whether it is the
model's own frame or a quarter turn from it (ticket 28's reconciliation), and
`EnclosureMatch.rotated` cannot recover that either — it states only that the drawn pair
matched the catalogue's printed row transposed, which ADR-0007's T15 amendment establishes is
a different fact from whether the registration itself turned. A consumer restoring a `v6`
document from bytes alone — `stompcollider` reading a drilled model's registration, per
`docs/specs/stompcollider-technical.md` — cannot tell the two apart, and the turn direction is
a stated convention rather than a derivable one, so inspection cannot recover it either. Harm
today is nil: no consumer reads the registration's provenance.

**Acceptance:** Not scheduled. Reopen only against a real second consumer that needs to
distinguish a reconciled registration from an unreconciled one — a forecast consumer alone
does not license adding the field, per the ruling below.

## `_walk_page` reads the crop box unnormalised and unclamped

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(M3-03).

**Constraint:** `sources/ai_pdf._walk_page` builds `crop = [float(v) for v in page.cropbox]`
and reads it in stored array order. ISO 32000-1 §7.9.5 does not guarantee `[llx lly urx ury]`
ordering, and pikepdf's `cropbox` property returns the raw `Array` rather than a normalised
rectangle, so a reversed box yields `x0 > x1`; `_centre_outside` and `_entirely_outside` both
treat that as degenerate-and-cull-everything, discarding every path in the document and
failing the run as `EmptyLayerError` — loud, but for the wrong reason. Separately, the crop
box is never intersected with the media box, so a crop box larger than the media box would
let pasteboard artwork back past ticket 21's fix. The same function also mixes
`page.cropbox` (inheritance-aware) with `page.MediaBox` (raw dictionary access) two lines
apart.

**Acceptance:** `_walk_page` normalises the crop box to `x0 <= x1, y0 <= y1` before using it
and intersects it with the media box, and a test drives a reversed-order crop box (and a crop
box larger than the media box) to prove neither degrades culling nor lets pasteboard artwork
through.

## The write mechanism replaces a symlink instead of writing through it

**Status:** Resolved by ticket 33 (2026-08). Found in the 2026-08 architecture review's
wave 3 (M3-04) against the pre-ticket-26 code; the call site moved once more under this
wave before the decision landed.

**Constraint:** `os.replace(tmp, path)` where `path` is a symlink replaces the link itself
with a regular file, rather than writing through it to its target. Before this review's write-
mechanism consolidation, the predecessor `path.write_bytes` followed the link and updated its
target; the rename-based mechanism does not. After ticket 26 the call site is
`stompmodel.protocols.StagedWrite.commit`'s single `os.replace(self._tmp, self.path)`, so
there is exactly one production site to fix rather than two. An operator keeping
`latest.svg -> builds/2026-08-24.svg` loses the link on the next run, silently — worth
deciding alongside ticket 29's `/dev/null` narrowing, since both are "what may a target be".

**Resolution (ticket 33):** Declared deliberate, on this entry's own second branch.
ADR-0005's target-domain paragraph now states plainly that committing replaces the
target's *name*, not the file its name used to resolve to: a symlink standing where the
target should be is afterwards a regular file holding the new payload, and whatever file
the link pointed at is left alone. Pinned by
`test_committing_a_staged_write_replaces_a_symlink_target_with_a_regular_file` in
`stompmodel`'s own suite (verified passing, independently, while preparing ticket 38 —
`.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_protocols.py -k
symlink -q`). Closed; nothing further to do.

## `OcpCaseModel.frame` and `OcpCaseModel.own_frame` are the same value

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(F2-06).

**Constraint:** `cad/loader.py` builds one frame and passes it to both `OcpCaseModel.frame`
and `OcpCaseModel.own_frame`. `classify()` reads `own_frame`; `CheckCaseClearance` reads
`frame`. Two public names for one value on one frozen dataclass — a reader must discover by
inspection that they cannot differ.

**Acceptance:** `own_frame` is deleted and every reader uses `frame`; the loader builds the
value once, and the full stompdrill suite passes unchanged.

## An unidentified enclosure is reported under two diagnostic codes at two severities

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(F2-07).

**Constraint:** `pipeline/clearance.py`'s `_cross_check` emits `case-model-unverified` (INFO)
and `_orientation_notice` emits `case-orientation-unverifiable` (WARNING) for the identical
condition, `data.enclosure is None`. A run with no identified enclosure and a supplied case
model therefore carries two findings for one absence, and the run's exit code moves from 0 to
1 on the strength of the second alone. `enclosure.quantise`'s own comment states the opposite
rule — that a second finding would report one absence twice.

**Acceptance:** One of the two diagnostics is deleted (or downgraded to a comment) so a
missing enclosure is reported once, at one severity, and a test proves that a run supplying a
case model but no identifiable enclosure produces exactly one diagnostic for the absence.

## Two rules decide "which solid is the drilled one"

**Status:** Deliberate deferral, not scheduled. Found in the 2026-08 architecture review's
wave 3 (F2-08). Explicitly not proposed as a fold: one inline site each, so a shared helper
would be a hypothetical seam.

**Constraint:** `cad/case.select_solid` refuses unless exactly one product name contains the
keyword; `emitters/step.cut_shape` cuts the *first* name-matching leaf that carries a shape.
They cannot disagree today only because `load_case_model` always runs `select_solid` first.
This is the half of wave 1's `leaf_labels` fold that did not close: `cut_shape` still walks
labels itself because `StepSolid` drops its label, so the selection rule could not be shared
with it.

**Acceptance:** Not scheduled as a fold until `cut_shape` gains a second call site, or
`StepSolid` carries its label and can call `select_solid` directly; until then this entry
stands as the reason the two must be changed together if either is.

**Annotated, not satisfied (ticket 34, 2026-08):** `stompgeom.step.StepLabel` now exists
and makes the "`StepSolid` carries its label" trigger cheap — `leaf_labels` already hands
back a `StepLabel` per solid, so wiring one onto `StepSolid` is no longer new plumbing.
This ticket deliberately does not take it: adding a label field to `StepSolid` was refused
by name as manufacturing this entry's own trigger rather than being asked for it. The
condition above still governs when this is taken.

## The `last_run → get → isinstance` provenance read is stated four times, deliberately not folded

**Status:** Confirmed gap, recorded as a relocation rather than a fold. Found in the 2026-08
architecture review's wave 3 (F2-09).

**Constraint:** `pipeline/snap.ReviewGridTies._pitch`, `cli._tool_label`, and
`cli.format_case` (twice) each read a stage's prior provenance as
`last_run(name) → get(key) → isinstance`. A shared accessor was considered and rejected: the
three readers want three different result types, so a shared accessor would need a type
parameter and would add more machinery than it removes — the deletion test does not
concentrate. The real answer is fewer string-keyed facts (see the `CheckCaseClearance` entry
above), not a nicer way to read them.

**Acceptance:** Not scheduled as a fold; this entry records the ruling so a later wave does
not manufacture a shared accessor and meet the same rejection again. Reopen only if a fourth
reader wants the same result *type* as an existing one.

## `cli.py` imports `SheetText` from the wrong drawing module

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(F2-10). Drawing-subsystem locality only; Minor by the review's own charter regardless of
severity elsewhere.

**Constraint:** `SheetText` is `emitters.drawing.content`'s type, re-exported by
`emitters.drawing.build`; `cli.py` imports it from `build`, reaching two levels into the
drawing subsystem for a name that belongs one level in.

**Acceptance:** `cli.py` imports `SheetText` from `emitters.drawing.content` directly, and the
full stompdrill suite passes unchanged.

## `fit_circle` runs up to three times per painted path

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 3
(F2-11). Locality only; no behaviour depends on it.

**Constraint:** `fit_circle` runs once in `_walk`'s cull, once in `AiPdfSource.read`'s drill
fit, and once in `_largest_non_circular`'s skip test. Correct but not shared: the `Circle`
the cull already computed is discarded rather than threaded through to the later two call
sites.

**Acceptance:** The cull's own `Circle` is threaded through (or memoised) so a painted path
is fit at most once per read, and the full stompdrill suite passes unchanged.

## `stompcollider-technical.md` misdescribes `wrong-case-model` as a product-name check

**Status:** Resolved by ticket 46 (2026-08). Found in the 2026-08 architecture review's
wave 3 (F1-04). Spec-axis; harm was entirely forecast.

**Constraint:** `docs/specs/stompcollider-technical.md`'s "Command line" said `stompcollider`'s
`wrong-case-model` "compares the drill document's declared enclosure part against the
model's own product name — the same check `stompdrill` already makes." `stompdrill` makes no
such check: `pipeline/clearance.py`'s `_cross_check` reduces both the model's measured
`footprint_nm` and the matched catalogue pair to descending order and compares them for exact
nanometre equality; the model's product name never enters the comparison (`OcpCaseModel.part`
is read only into message strings — see "`wrong-case-model` names the operator's `--case`
designator as the model's own" above, a related finding from a different direction). Left as
written, two tools would emit one diagnostic code meaning two different things — a
dimensional mismatch in one, a designator-string mismatch in the other — which `stompcad`
cannot reduce over, since it matches diagnostics by code.

**Acceptance:** `stompcollider-technical.md`'s sentence is corrected to describe a footprint
comparison (or `stompcollider`'s own check is designed to match `stompdrill`'s dimensional
one), before `stompcollider`'s clearance stage is implemented against the current wording.

**Resolution (ticket 46):** The first branch of the Acceptance was taken -- the document is
corrected, `stompdrill`'s dimensional check is left exactly as it is -- because the shipped
comparison is the behaviour that ought to ship and `stompcollider` has no code yet. The
misdescription occupied **two** sites, not the one this entry quoted: the diagnostics-table
row as well as the prose. The row now reads "The model's footprint is not the enclosure the
drill document identifies", and the prose names `length_nm` and `width_nm`, the descending-
order reduction, the exact nanometre comparison, that product names never enter it, that
`CheckCaseClearance._cross_check` is the tool already making it, and the
unidentified-enclosure skip. Every clause is implementable against the shipped document:
`stompmodel.codec` writes and restores `enclosure.length_nm` and `enclosure.width_nm`, and
the skip matches `_cross_check`'s own `case-model-unverified` INFO branch. Re-verified
before the edit with a probe driving `CheckCaseClearance` over two cases -- identical
product names with different footprints, and totally different product names with identical
footprints -- which returned `['wrong-case-model']` and `[]` respectively: the name is
provably not consulted. The related finding one direction over, "`wrong-case-model` names
the operator's `--case` designator as the model's own", is untouched and stays open. Closed;
nothing further to do.

## `stompdrill` has no library entry point below `main`

**Status:** Recorded, not proposed as work. Found in the 2026-08 architecture review's wave 3
(F1-05); the review's own wave-3 asymmetry rule governs it — a forecast consumer licenses not
narrowing an interface, never adding one — and wave 1 already ruled the neighbouring CLI-half
question DEFERRED.

**Constraint:** The composition that turns a panel path plus options into `DrillData` lives
in `cli._run`, private, keyed to an `argparse.Namespace`, printing to a `TextIO` and returning
an exit code. Every helper it calls takes the same `Namespace` (`build_quantisers(args)`,
`build_pipeline(args)`, `build_case_model(args)`), and `read_source`, `run_pipeline`,
`settings_from`, `make_emitter` and `format_report` are not in `cli.__all__`. The package
root exports the parts (`Source`, `quantise`, the stages, `load_case_model`) but nothing that
composes them, so `stompcad` — which must import `stompdrill` as a library and never shell
out (`docs/specs/stompcad.md:112`) — would either synthesise a fake `Namespace` or
re-implement `_run`.

**Acceptance:** Not scheduled as work by this entry. Its value is directional: the next thing
added below `cli.main` should be a value-returning composition rather than another
`build_*(args)` helper keyed to `Namespace`, so the eventual seam does not get more expensive
to cut. A wave that finds this again cites this entry rather than re-deriving it, unless it is
ready to design the facade against a real caller.

## The 1590LB reconciliation turns on a difference finer than the matcher's own tolerance, silently

**Status:** Confirmed gap, not scheduled. Found by the T15 design verdict during the 2026-08
architecture review's wave 3 (`design/wave3-t15-registration-stated-at-value-VERDICT.md §6`);
the diagnostic that would close it is deliberately not built.

**Constraint:** `CheckCaseClearance`'s panel-to-model reconciliation (ticket 28) decides
whether a quarter turn is needed by comparing `ReferenceOutline.raw`'s two drawn extents. For
`1590LB`, the catalogue's own two dimensions differ by 0.05 mm — thirty times finer than
`IdentifyHammondFootprint`'s 1.5 mm per-axis matching slack — so the turn decision rests on a
difference the identification itself never had to resolve, and no diagnostic marks it. A
catalogue sweep
(`packages/stompdrill/tests/test_clearance.py::test_the_near_square_band_is_computed_and_is_exactly_1590lb`)
is the reproduction: it computes, rather than hard-codes, every catalogue row whose two
dimensions fall inside the matcher's own tolerance band, and today that is `1590LB` alone.
The near-square warning that would close it — extending `case-orientation-unverifiable` to
any footprint inside that band — was considered and deliberately not built in the same
ticket, because `CheckCaseClearance` cannot see `IdentifyHammondFootprint.tolerance_nm`, and
inventing a threshold to stand in for it would be exactly the ungrounded machinery this
repository's design rules refuse.

**Acceptance:** Either `IdentifyHammondFootprint`'s matching tolerance becomes visible to
`CheckCaseClearance` (as a value on `EnclosureMatch`, or otherwise) and the near-square
warning is built against it; or the risk is accepted as recorded here for as long as the
shipped catalogue's only near-square row is `1590LB`, and the acceptance test above is what
notices if a future catalogue addition joins the band.

## Harvest candidate: a document must not claim a class closed in the same change that ships the fix

**Status:** Recorded for the coordinator to route (harvest candidate) — not a repository rule
adopted by this entry, and not implementation work. Raised by the 2026-08 architecture
review's wave-3 synthesis (`reviews/wave3-themes.md`, forecast P5) while scoring wave 2's own
forecast.

**Constraint:** Wave 2's ticket 22 fixed the CLI's partial-write hazard well past its own red
test — staging every artefact before committing any, unwinding the whole set on failure — and
then its ADR-0001 amendment, written in the same change, asserted the transaction claim
closed. The implementer's own `_commit` docstring honestly conceded the residue the mechanism
did not anticipate (`os.replace` can fail after an earlier target already replaced), but nothing
checked that concession against the ADR sentence it sat beside. Wave 3 reproduced the gap
directly — three independent findings (F3-03, F6-01, and F2-02's first half) all reduce to
the same false ADR-0001 sentence, closed only now, by ticket 29 of this later wave. The
proposed workflow rule: **a document may not claim a class of failure closed in the same
change that ships its fix, unless the acceptance evidence names the mechanism's actual
preconditions and shows each one held** — a docstring conceding a residual precondition and an
ADR sentence asserting the class closed, side by side in one diff, is the shape to catch.

**Acceptance:** Not scheduled as repository tooling by this entry. The coordinator decides
where this rule lives — a `CLAUDE.md` testing or documentation rule, a step in the review
workflow's own Implement or Review phase, or left recorded here only — and this entry is
superseded once that decision is made, rather than acted on directly.

## Extract the "a bound is whole nanometres and not negative" validation rule

**Status:** Confirmed duplication, not scheduled. Named by ticket 36 (T21, "the tool says
how far it moved the diameter") while adding `SnapDiametersToDrillTable.warn_over_nm`.

**Constraint:** `SnapPositions.__init__`/`_threshold` in `pipeline/snap.py` and
`SnapDiametersToDrillTable.__init__` in `pipeline/diameters.py` each check, inline and
independently, that a bound is a plain non-negative whole number of nanometres —
`tolerance_nm`, `warn_over_nm` on both stages, and `grid_nm`. Ticket 36 makes this the
third independent copy of the same two-clause rule rather than folding it, deliberately:
taking the fold would put a lock-covered stage into that ticket's diff for no behavioural
gain — see its "Out of scope". The shape both stages now share (validate in `__init__`,
raise `ValueError` naming the parameter and the negative value) makes a later extraction
mechanical.

**Acceptance:** A single published helper (in `stompdrill.tolerance` or a new module)
replaces all three inline checks, every existing bound-validation test still passes
unchanged (the error messages it asserts against are preserved or the tests are updated
in the same change), and the full suite, lint, and both mypy configurations stay green.

## The staged write's commit-or-discard obligation is unenforced

**Status:** Resolved by ticket 41 (2026-08). Found in the 2026-08 architecture review's
wave 4 (its own finding F2-05); see ticket 33's report, "Scope discipline".

**Constraint:** `stompmodel.protocols.stage_payload` returns a `StagedWrite` whose `_tmp`
field two module-level functions, `commit_staged` and `discard_staged`, read directly
rather than through a method on the dataclass — a private field crossing the module's own
boundary twice. Nothing enforces that a caller who stages a payload goes on to call one of
the two: a `StagedWrite` a caller drops leaks its temporary silently, with no warning and
no finalizer. Expressing the pair as `StagedWrite.commit()` and `StagedWrite.discard()`
would stop the field crossing the boundary and would narrow the mechanism's four published
names to two.

**Acceptance:** Either `commit_staged`/`discard_staged` become methods on `StagedWrite`
(closing the private-field crossing) and something — a `__del__` warning, a context-manager
requirement, or a documented convention with a gate — makes an abandoned `StagedWrite`
detectable rather than silent; or the trade-off is recorded as accepted, since ADR-0005's
own reason for the two-call split (a caller composing a whole set must be able to pause
between staging and committing) is settled and correct and does not by itself require the
enforcement half.

**Title correction (ticket 41):** this entry was filed as "... and a private field crosses
a package boundary". That clause was false and is not carried forward: `_tmp` appeared in
exactly one production module, so what it crossed was the class's own encapsulation inside
that module, not a package boundary. The Constraint above is left as written so the
rediscovery is still findable; read it with this correction.

**Resolution (ticket 41, `6a016b3`):** Both limbs of the Acceptance are satisfied, the
first by construction and the second as the recorded-and-accepted trade-off. `commit_staged`
and `discard_staged` are deleted outright -- no deprecating wrapper -- and their bodies
move verbatim onto the value they already operated on, as `StagedWrite.commit()` and
`StagedWrite.discard()`; `_tmp` is now read only by `self`, inside its own class, in its
own module, and `stompmodel.protocols.__all__` loses both names and gains none. The
enforcement half is refused rather than shipped: ADR-0005 gains a Decision subsection
carrying the four candidate detectors and why each was refused, and naming the caller-side
residue assertion that does catch an abandoned temporary. Three independent design seats
each proposed an enforcement mechanism and the judge refused all three -- `__del__` works
on a frozen slotted dataclass and is refused on merit, not on impossibility. What would
make enforcement correct later: a second production caller that stages without discharging
in the same expression, which is the shape a detector could actually find. Closed; nothing
further to do.

## `codec._read_frame` reads a face frame's origin without the length guard `_read_diagnostic` already carries

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 4
(its own finding F2-06).

**Constraint:** `stompmodel.codec._read_diagnostic` checks `len(location) != _LOCATION_VALUES`
explicitly before indexing a diagnostic's `location_nm`, with a docstring stating why: a
short one would raise past the reader, and a long one would be silently truncated into a
position the writer never stated. `_read_frame` indexes `origin[0]`, `origin[1]`,
`origin[2]` directly with no equivalent check (confirmed by reading
`packages/stompmodel/src/stompmodel/codec.py`). A four-element `origin_nm` in a supplied
document is silently truncated to three rather than rejected; a two-element one still
raises, but only through the codec's broad `except (IndexError, TypeError, ValueError,
AttributeError)` wrapper rather than a named guard stating why.

**Acceptance:** `_read_frame` gains the same length check `_read_diagnostic` already
carries, symmetric in shape and reason, and a test supplies a four-element `origin_nm` and
asserts `DocumentError` rather than silent truncation.

## `tools/workspace_membership.py` cites a `CLAUDE.md` section by a word `CLAUDE.md` never uses

**Status:** Confirmed gap, not scheduled. Found in the 2026-08 architecture review's wave 4
(its own finding F6-02).

**Constraint:** `tools/workspace_membership.py`'s module docstring says "See ADR-0008, and
`CLAUDE.md`'s Testing rules on ownership gates." `CLAUDE.md` never uses the word
"ownership" anywhere in the file (`grep -n ownership CLAUDE.md` returns nothing). The five
gate modules the docstring is pointing a reader toward are real, and `CLAUDE.md`'s Testing
rules section does discuss the ownership-gate family under other language — the citation
names the wrong word, not a section that does not exist.

**Acceptance:** Either the docstring's citation is corrected to the wording `CLAUDE.md`
actually carries, or `CLAUDE.md` gains the word its own tooling already expects to find
there. A one-line fix either way.

## Both `stompcollider` specs still place the length newtypes and the frame values in `stompgeom`

**Status:** Resolved by ticket 46 (2026-08), having been explicitly deferred rather than
fixed by wave 4's own documents ticket — see ticket 38's "Out of scope". Found in the 2026-08
architecture review's wave 4 (its own finding F1-03).

**Constraint:** ADR-0008's own preamble states plainly that the length newtypes and the
frame values "have since settled in `stompmodel`", not `stompgeom` — confirmed in the
shipped source: `Nanometre`, `Millimetre`, `Micron`, `CoordinateFrame` and `FaceFrame` are
all defined under `packages/stompmodel/src/stompmodel/`, and `stompgeom` names none of the
four. Two spec sentences have not caught up: `docs/specs/stompcad.md` states "`stompcad`
depends on `stompgeom` only for lengths it reports", and
`docs/specs/stompcollider-technical.md`'s plan table (line ~560) credits plan 2
(`stompgeom`) with "the `CoordinateFrame` / `FaceFrame` split". Both name the wrong package
for values that now live in `stompmodel`. A plan-3 implementer reading either sentence
looks in the wrong package for both.

**Acceptance:** Both sentences are corrected to name `stompmodel` for the newtypes and the
frame values, and to state what `stompgeom` actually contributes at that seam (the kernel
reader and writer, and the STEP-specific `StepLabel`/`StepSolid`/`StepDocument` types).
Should land **before plan 3 starts**, per this wave's own synthesis — a spec-axis,
doc-only fix, same category as the `wrong-case-model` misdescription entry above.

**Correction to this entry's own title (ticket 46):** neither file carried both halves.
`docs/specs/stompcad.md` misattributed only the lengths; `docs/specs/stompcollider-technical.md`'s
plan table misattributed only the frame values, and the row above it already credited plan 1
(`stompmodel`) with lengths correctly. The Constraint's own body states this accurately; the
title compounds it. Read the title as "two specification sentences", not "both specs, both
halves".

**Resolution (ticket 46):** `docs/specs/stompcad.md` now names `stompmodel`, and says what
`stompgeom` really does contribute at that seam rather than leaving a hole: `stompcad` takes
no direct dependency on it, and the kernel reaches it only transitively -- through
`stompdrill`, whose distribution declares `stompgeom` today, and through `stompcollider`,
which its own technical specification has writing its assembly through `stompgeom`'s writer.
The same sentence was widened, not merely retargeted: "only for lengths" was an underclaim,
since the orchestration section immediately above it already has the drill document and the
structured diagnostics -- both `stompmodel` values -- passing through `stompcad`.
`docs/specs/stompcollider-technical.md`'s plan-2 row now names the reader, the writer and
the kernel guard, and records that the `CoordinateFrame` / `FaceFrame` split moved *down*
into `stompmodel` rather than into `stompgeom`, citing ADR-0009 as amended. The row
deliberately preserves the history instead of deleting the clause, because
`docs/plans/2026-08-22-stompgeom-extraction.md` states the extraction's goal as moving the
frame *values* down into `stompmodel`, and a row that erased the clause would make the plan
table disagree with the plan it records. Closed; nothing further to do.

## `StepSolid.unit_mm` is a published field with one possible value and no reader

**Status:** Resolved by ticket 45 (2026-08). Found in the 2026-08 architecture review's
wave 4 (its own finding F1-04).

**Constraint:** `stompgeom.step.read_step` forces `xstep.cascade.unit = "MM"` before
reading, so every `StepSolid.unit_mm` it constructs is `1.0` — the field can hold no other
value on the path that sets it, and nothing in `stompgeom` or `stompdrill` reads it (a
`stompcollider` board reader is the invited future reader, per the field's own apparent
purpose, but plan 3 has not been written yet).

**Acceptance:** Either the field's docstring states plainly that it is always `1.0` because
`read_step` fixes the cascade unit, and why it is published anyway (for the reader plan 3
is expected to add), or the field is deleted until that reader exists and re-added with it.
Deleting it is the interface-moving half and belongs with `stompgeom` work, not with a
documentation-only pass — matching ticket 34's own refusal to add a field speculatively.

**Resolution (ticket 45, `03a19bd`):** The deletion branch of the Acceptance was taken --
the field is gone, and it returns with its first real reader. Narrowing the claim to what
the code delivers *is* removing the member here, because a `float` cannot express the domain
{1.0}: the reader forces `xstep.cascade.unit` to MM and hard-coded the field to `1.0` at its
sole construction site, and no attribute read of it exists anywhere in the workspace. The
millimetre guarantee itself is unaffected -- it is already prose in three places and
behaviour in `test_step_reader.py`. No docstring changed, because the absence of a field is
not documented. Closed; the entry stands so that whoever adds the `stompcollider` board
reader can see what was removed and why.

## The `--emit` duplicate-target check is defeated by a case-insensitive filesystem

**Status:** Resolved by ticket 40 (2026-08), having been explicitly deferred by ticket 35,
wave 4's own fix to the surrounding pre-flight. Found in the 2026-08 architecture review's
wave 4 (its own finding M3-01).

**Constraint:** `stompdrill.cli._preflight_targets` detects a duplicate `--emit` target by
`path.resolve()` equality. On this repository's own filesystem (macOS, case-insensitive by
default) two targets differing only in case — `out.json` and `OUT.json` — resolve to
different `Path` values, both pass the duplicate check, and both are staged; the second to
commit silently overwrites the first, and only one of the two "wrote ..." lines the
operator sees is honest about what is on disk afterwards. Ticket 35's own "Out of scope"
names this and declines it: "every available fix either over-fires on case-sensitive
filesystems or needs a probe that writes."

**Acceptance:** Not scheduled by this entry — ticket 35's stated reason stands. Reopen only
with a fix that does not over-fire on a case-sensitive filesystem and does not need a probe
that writes to decide.

**Resolution (ticket 40, `3d5b7c2`):** Reopened with a fix that meets both of this entry's
own conditions -- it needs no probe that writes, and it does not decide differently on a
case-sensitive filesystem. The pre-flight keeps its place and its phase; only the key it
compares changes. `_target_key` reduces a resolved target to UAX #15 D145's canonical
caseless match (NFD, casefold, NFD), applied unconditionally, so the refusal is
deterministic and needs no filesystem access. It is a comparison key only: the bytes still
go to the spelling the caller typed.

**What the fix deliberately gives up.** It over-fires rather than under-fires: on a
case-preserving, case-sensitive volume a caller who genuinely wanted
`--emit json=out.json --emit drawing-svg=OUT.json` as two files is now refused, with exit 3
and a message saying why. That was chosen knowingly -- the cost is one rename, against a run
reporting a byte count for an artefact it destroyed, on a machine whose output drills
aluminium. The fold is conservative rather than exact: Windows's trailing-dot stripping and
8.3 aliases and locale-specific folds are not closed, and are not to be added pre-emptively
for a filesystem nobody here runs on; the failure direction there is silent
under-detection, which is today's behaviour, never a false refusal. Guilty probes cover
the case-only and the NFC/NFD-only collision, the second carrying its own fixture control
that its two paths really are two distinct strings; innocent probes keep the narrowing
scoped to case and normalisation form alone. `CLAUDE.md`'s `--emit` paragraph was amended by ticket 46 to state the
folded key. Closed; nothing further to do.

## `clearance_reason` breaks a distance tie on a source-literal dict order

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Named by ticket 44 while
closing the tie-break entry above, and recorded rather than fixed because it is outside
that ticket's four owned helpers.

**Constraint:** `stompdrill.cad.region.clearance_reason`'s `min(groups, ...)` (around
`region.py:245`; locate it by its text) picks the nearest group and, where two groups sit at
exactly the same distance, returns whichever the source literal happens to list first. That
is the same class of defect the tie-break entry above closed on four other helpers -- a
winner decided by a spelling rather than by geometry -- but it decides a diagnostic's stated
*reason*, not a clearance verdict, so nothing a bit meets changes.

**Acceptance:** The tie is broken on a stated property of the groups themselves, and a test
constructs two groups at exactly equal distance and asserts the same reason whichever order
they are supplied in.

## `drill_axis` breaks a footprint tie on a source-literal axis index

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Named by ticket 44 while
closing the tie-break entry above, and recorded rather than fixed for the same reason.

**Constraint:** `stompdrill.cad.case.drill_axis` loops over `range(3)` and returns the first
axis matching the footprint, so two axes with equal footprints are separated by the literal
order of the loop rather than by anything about the enclosure. Latent on every model this
repository can fetch, because a 1590 enclosure has no two equal footprints; it is recorded
so a later cubic or square part does not discover it as an artefact difference.

**Acceptance:** The choice among equal-footprint axes is stated as a geometric rule, and a
test drives two equal footprints and asserts the same axis whichever order they appear in.

## `_inner_level`'s primary key is a float sum over kernel-ordered members

**Status:** Recorded, not proposed as work. Named by ticket 44, which found it while giving
the same helper a secondary key and deliberately did not touch the primary.

**Constraint:** `stompdrill.cad.case._inner_level` ranks levels by `_Level.area`, a plain
float `sum()` over members held in kernel traversal order (`case.py:199`). Float addition is
not associative, so in principle the aggregate -- and therefore the winner -- is a function
of the order `TopExp_Explorer` walked. Latent rather than live: 40 random permutations of
the plane list through `_levels` differ in zero aggregates on 1590BB and 1590Y. Ticket 44's
own rules forbade quantising a primary key, so it recorded this rather than acting.

**Acceptance:** None proposed. Reopen only with a case where two permutations of one model
really do produce different aggregates; the fix then has to settle whether the primary key
is quantised or the summation is ordered, and that is a decision about ADR-0006's reach,
not a local repair.

## Select `_floor_face` from `_inner_level`'s own level

**Status:** Recorded, not argued for. Named by ticket 44 as the structural alternative it
did not take.

**Constraint:** `region._floor_face` ranks a single face by its own area; `case._inner_level`
ranks a level by the aggregate area of its members. Ticket 44 stated both metrics and stopped
claiming they agree, which was that entry's acceptance. Choosing `_floor_face` from
`_inner_level`'s own level would make the two consistent by construction rather than by
statement -- but it needs level information plumbed from `case.py` into `region.py` and it
changes what `_floor_face` returns, so it is a design question rather than a cleanup.

**Acceptance:** None proposed. Recorded so a later reader sees that the consistency was
stated deliberately rather than left unexamined.

## `tools/verify-lock.sh` certifies a truncated reference

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Found while ticket 46
re-read what ticket 39 shipped.

**Constraint:** The compare loop counts rows and refuses a reference naming **no** artefact
(`if [ "$rows" -eq 0 ]`), which is the guard ticket 39 added. It does not check the count
against what the run was asked to hash, so a `SHA256SUMS` truncated to one row still
compares one row, finds it unchanged, and prints `BEHAVIOUR LOCK HELD`. The lock's whole
value is that a green run means every hashed artefact was compared, and a partial reference
makes that untrue while looking identical.

**Acceptance:** The compare path refuses a reference whose row count is not the number of
artefacts the panels were asked for, with the count in the message, and ships both probes: a
guilty one truncating a real reference and an innocent one adding a legitimate artefact.

## ADR-0011 says the script echoes the reference path it used, and the compare path does not

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Found while ticket 46
re-read what ticket 39 shipped.

**Constraint:** ADR-0011 states "The script echoes the reference path it used, and keeps the
artefacts beside it, so a break can be diffed rather than guessed at." Only the *capture*
path prints it (`echo "reference captured: $REFERENCE"`); the compare path prints per-row
`ok`/`CHANGED` lines and the verdict, and never names the reference. A reader following the
ADR to diff a break has to reconstruct the path from the invocation. The keeps-the-artefacts
half is true.

**Acceptance:** Either the compare path echoes `$REFERENCE` before the rows, or ADR-0011's
sentence is narrowed to the capture path. This entry does not choose; note that ADR-0011 is
an ADR, so whichever is taken, the ADR is amended in the same change.

## ADR-0001 and `CLAUDE.md` now differ by one clause about the `--emit` pre-flight

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Deferred by ticket 40 under
the coordinator's ruling, and landed here as an entry because ticket 46 amended the
`CLAUDE.md` half.

**Constraint:** ADR-0001's transaction paragraph says "no two targets may name one path".
`CLAUDE.md`'s `--emit` paragraph now says the same thing "compared under a case- and
normalisation-folded key, because a filesystem may hold two such spellings as one file",
which is what ticket 40 shipped. Neither statement is false; the ADR is simply the less
specific of the two, and this repository treats `docs/adr/` as the authority, so the
authority is the vaguer document.

**Acceptance:** ADR-0001's clause carries the folded key, or states plainly that the key is
`CLAUDE.md`'s to specify. One line either way, and it is an ADR amendment.

## ADR-0006's enforcement list underclaims by four sites

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Handed over by ticket 44,
which addressed it to ticket 43; ticket 43 had already merged when the hand-off was written,
so no wave-5 branch carried it.

**Constraint:** ADR-0006's list of the sites that enforce its ordering rule does not include
the four model-side helpers ticket 44 brought under it -- `cad/case.py`'s `_inner_level` and
`_nearest_companion_level`, and `cad/region.py`'s `_floor_face` and `_proud_mm`. This is an
underclaim rather than an overclaim, which is the direction nobody looks for by habit: the
ADR states a narrower reach than the code delivers, so a reader deciding whether a new
selection rule is bound by it can reasonably conclude it is not.

**Acceptance:** ADR-0006's enforcement list names the four helpers, and says that its
amendment binds every selection rule over kernel-derived candidates rather than routing's
alone. An ADR amendment, so it is accepted before it is written.

## `stompgeom`'s leaf-walk ownership probe passes on a harness that never ran

**Status:** Confirmed gap, not scheduled -- **wave 6, list A.** Found while ticket 46
re-read wave 5's instruments.

**Constraint:** `packages/stompdrill/tests/test_ownership_gate_convention.py`'s
`test_stompgeoms_own_suite_catches_a_second_leaf_walk_in_its_own_source` splices a duplicate
XCAF leaf descent into `stompgeom`'s `writer.py`, runs `stompgeom`'s own suite in a
subprocess, and asserts only `result.returncode != 0`. Every way of failing to run pytest at
all -- `uv` absent, the working directory wrong, a resolver error, the `uv run --no-sync`
form that the review's own worktree brief records as not working outside the main checkout --
also returns non-zero, so the probe passes without the gate it names ever having been
consulted. It is the same instrument class ticket 42 repaired elsewhere: a verification that
can pass by finding nothing.

**Acceptance:** The assertion binds to the gate's own failure -- the spliced-in breach named
in the subprocess's output, or a distinguishable exit code -- and a control shows the test
failing when the subprocess dies before collection.

## `Match` pairs a protrusion to a hole by absolute proximity, so a real export pairs nothing

**Status:** Confirmed defect, not scheduled. It is a specification change as well as a code
change, so it is recorded rather than patched. Found while the dock report and the assembly
model were first read back and compared.

**Constraint:** `stompcollider.match._pair_face` measures the distance from a protrusion's
`axis_xy_nm` — a coordinate in the board model's own frame — to a hole's `(x_nm, y_nm)` in
the case's face frame, and pairs them when it is within the recognition tolerance. That
presupposes the board model's origin already coincides with the face frame's origin, which
is precisely the quantity the Candidates step exists to compute from the pairs this step
produces. On the synthetic fixtures the two origins do coincide, so the suite is green; a
real KiCad export, whose origin sits at a board corner or a sheet origin, is displaced far
past any tolerance and pairs nothing, earning `no-correspondence` on every board.

A visible consequence, worth stating because it looks like a separate fact: every placement
this implementation can produce has `x_nm`, `y_nm` and `theta_deg` at or near zero, because
a correspondence only exists where a part already lies on its hole.

**Acceptance:** Pairing is seeded from *relative* geometry — the invariant the Candidates
section already half-describes, `| p₁p₂ | = | h₁h₂ |` within twice the tolerance — so that a
board displaced by an arbitrary rigid motion still pairs, and `docs/specs/stompcollider-technical.md`'s
Match section is amended to specify that seed rather than absolute proximity. A test seats a
board whose model origin is displaced by more than the tolerance and finds the same
correspondences as the undisplaced one, and the agreement test then has a placement with a
non-zero translation and turn to compare.

## An under-constrained board reaches no artefact, which the pre-spec requires it to reach

**Status:** Confirmed gap between the two `stompcollider` specifications, not scheduled.

**Constraint:** `docs/specs/stompcollider.md` states that a board with no panel-reference
parts, or exactly one, "is explicitly placed rather than solved, and treated as a fixed
body others must avoid". Nothing implements that. `Match` records
`under-constrained-board` and gives such a board no placement; the assembly emitter then
leaves it out entirely, so it is neither drawn nor checked for interference, and the
boards around it are checked against a space it really occupies as though it were empty.
`--place` is the flag that would supply the missing placement, and it is refused, because
no stage consumes one. Refusing it is right — an accepted flag that changed nothing would
be worse — but the requirement behind it is still unmet, and the pre-spec is the authority
where the two documents disagree.

**Acceptance:** A stage places an explicitly placed board, `--place N=X,Y,THETA` feeds it,
such a board appears in the assembly model and participates in the clash check as a fixed
body that others must avoid, and `docs/specs/stompcollider-technical.md`'s command line
section drops the shortfall it currently records. A test covers a run with one
under-constrained board and one solved board that clashes with it.

## The `-v` stage trace is a near-copy between the two command lines

**Status:** Confirmed duplication, not scheduled. The commit-loop half of this entry is
closed: `stompmodel.protocols` publishes the set-level transaction as `stage_all` and
`commit_all`, both command lines call it, and ADR-0001 records the promotion as it
recorded the target-set precondition's.

**Constraint:** What is left of the duplication is the per-stage trace. `stompdrill.cli`'s
`run_pipeline` takes an optional `trace` callback; `stompcollider.cli`'s `_traced` takes an
optional stream and prints to it. Both fold one stage at a time through a single-stage
`Pipeline` so that the value before and after each stage is available, and both build a
line from the same three facts — the stage's name, the count of the thing it might drop,
and the diagnostic codes it added. Two spellings of one fold is a second chance to disagree
about what a stage did.

**Acceptance:** One fold, published where `Pipeline` is, taking the value before and after
each stage to a caller-supplied observer; each command line keeps only the sentence it
formats, which is genuinely tool-specific (holes against boards). Both `-v` outputs are
unchanged byte for byte.

## Two tools raise `wrong-case-model` from two implementations of one rule

**Status:** Confirmed duplication, not scheduled. Recorded rather than patched: the
promotion this needs was not part of the work that created the second copy.

**Constraint:** `stompcollider/sources/step.py`'s `_cross_check`/`_footprint_nm`/
`_descending` and `stompdrill/pipeline/clearance.py`'s `CheckCaseClearance._cross_check`
(reading the footprint `stompdrill/cad/loader.py`'s `_footprint_and_axis` measured) each
implement one rule: take the case model's three bounding spans, drop the shallowest as the
depth, reduce the remaining two to descending order, and compare them with the identified
enclosure's own pair at exact nanometre equality. `stompgeom.assembly_spans` — the
measurement — was promoted; the *interpretation* of those spans was not, and the
interpretation is what carries the diagnostic's meaning. `stompcollider`'s docstring says
so honestly, naming `stompdrill`'s `CheckCaseClearance._cross_check` as the rule it
repeats; `stompdrill`'s own docstring names only `case.py` and `enclosure.py` and never
`stompcollider`, correctly, since `stompdrill` sits below `stompcollider` in the
workspace's dependency order and must not know about it. The duplication is visible from
one direction only, which is the right arrangement given that order, not a gap in it.

**Why it matters:** one diagnostic code, `wrong-case-model`, is now raised by two
implementations, and nothing compares them. A change to either — which axis counts as the
depth, whether the comparison stays exact, what a shape with two equal spans does — makes
that one code mean two different things depending on which tool reported it, with no test
anywhere that would notice. Matching by `code` is this workspace's rule for reading a
diagnostic, so a consumer cannot tell the two apart.

**Acceptance:** The interpretation lives once, beside `assembly_spans` in `stompgeom` or as
a footprint rule in `stompmodel`, and both call sites read it; or, if the two are shown to
be genuinely different questions, one of them stops using the code the other owns. Either
way a test compares the two tools' answers over one model rather than each tool's answer
against itself.

## `stompgeom`'s subprocess determinism probes run unmutated code, so the writer's survey is not what it looks like

**Status:** Confirmed gap, not scheduled.

**Constraint:** Several of `stompgeom`'s determinism tests run their probe in a subprocess
(`sys.executable -c …` in `tests/test_writer.py`), and that interpreter resolves
`import stompgeom` through the installed distribution rather than through the tree the
test is running against. Under `cd packages/stompgeom && mutmut run` the mutant lives in
mutmut's own copy of the source, so those subprocesses execute the unmutated code and pass
whatever the mutant did: they can kill nothing in `writer._reslot_colours` or
`writer._canonicalise_ownership`. Every kill the survey credits for those two functions is
an in-process test's, and the determinism claim the subprocess probes exist to make is not
surveyed at all — which a survey read by module gives no sign of.

**Acceptance:** The subprocess resolves `stompgeom` from the tree under test (a
`PYTHONPATH` it inherits, or a probe run in-process), a control shows a deliberate breach
of the determinism rule failing that subprocess, and the survey is re-read for those two
functions with the coupling gone.

## `RigidTransform`'s basis tolerance has no headroom against `CoordinateFrame`'s own edge

**Status:** Confirmed gap, not scheduled.

**Constraint:** `stompmodel.frames._BASIS_TOLERANCE` is the same `1e-9` for
`RigidTransform` as it is for `CoordinateFrame`, so a frame legally admitted at its own
orthogonality edge (`u·v = 9.9e-10`, just inside `CoordinateFrame`'s own check) makes
`placement_onto` raise where an otherwise-legal frame previously returned; the break-even
sits near `5e-10`. Unreachable from any production builder today — the measured deviation
`build_frame` actually produces is exactly `0.0` — but it is a real domain narrowing on a
published type, since a hand-built `CoordinateFrame` could meet the admitted edge that
`RigidTransform` then refuses.

**Acceptance:** Either `RigidTransform` is shown to need no headroom beyond
`CoordinateFrame`'s own edge and this is recorded as the reason, or its tolerance widens
enough to admit every frame `CoordinateFrame` itself admits, and a test constructs the
`9.9e-10` edge case and asserts the chosen behaviour.

## A bare `ValueError` escapes `stompcollider`'s CLI on an oversized range bound

**Status:** Confirmed gap, not scheduled. Pre-existing; found beside the refusal policy a
recent wave rewrote.

**Constraint:** `packages/stompcollider/src/stompcollider/designators.py:64` calls
`int(lo_text)` on a range term's bound before checking its width. A bound long enough to
overflow Python's integer-to-string conversion threshold (thousands of digits) raises a
bare `ValueError` there, and `stompcollider.cli.main` catches only `StompError` and
`OSError`, so the failure escapes as a traceback rather than the `UsageError` the same
function raises for an ordinary oversized range.

**Acceptance:** The oversized-bound case raises the same `UsageError` an oversized range
raises today, a test drives it with a bound wide enough to trigger the conversion limit,
and `stompcollider.cli.main`'s existing catch clauses need no widening to reach it.

## Rulings, for citation

Entries below are decisions, not open work: each states an alternative that was considered
and the reason it was not taken (or, for the first, a wording question that measurement
settled), with no residual "not yet done" left standing. Separated from the sections above
so the count of open backlog entries means what it says. Nothing here is deleted — a later
wave that rediscovers one of these questions cites the entry rather than re-deriving the
argument, per this repo's own rule that a decision record is Settled while a record naming
a gap is open work wearing a citation.

### Clarify what ADR-0001 means by the pipeline's "fixed composition"

**Status:** Ruled — closed, no change needed. Noted 2026-08-21 after measurement; the
status line is flipped here on the entry's own first branch rather than left open
indefinitely for a wording question the measurement already answered.

**Constraint:** ADR-0001's Rationale says the stages' "fixed composition" is "read at the
invocation boundary". A review of every live restatement of the stage order — ADR-0001's
prose and Figure 1, ADR-0007, CLAUDE.md, the `cli` module and `build_pipeline` docstrings —
found all of them current and in agreement, including the conditional `CheckCaseClearance`
edge. Nothing here is stale, so this was a wording question and not a correction: "fixed"
could be read as denying that the fifth stage is conditional, when what the sentence means
is that the composition is settled *at* the boundary rather than negotiated between stages.

**Resolution:** Left alone. Spot-checked again while preparing ticket 38 (2026-08):
ADR-0001's Rationale sentence is unchanged and Figure 1 still shows
`contain -.->|DrillData, if --case-model| clearance` as the conditional edge it always
was. This entry's own acceptance criterion is satisfied by its first branch — "measured,
no change needed" — and is recorded here for citation rather than deleted, since a later
reader who meets the same wording question should cite this measurement rather than
re-derive it.

### `falsify/tests/`'s wave-1 fixtures going stale against a later refactor is not a defect

**Status:** Deliberate ruling, not a gap. Made during the 2026-08 architecture review's
wave 2: ticket 14's implementer found the staleness and correctly left the file alone
rather than editing outside its own ticket's scope; the coordinator ruled on what it means.

**Constraint:** `.scratch/architecture-review/falsify/tests/` holds one-shot
falsification fixtures, each built to reproduce a specific wave's finding before it was
fixed. Several of wave 1's still pass a bare `"box"` string where the code has since moved
to a `CaseFace` enum (`stompmodel.model.CaseFace`, introduced closing this review's ticket
13) — for example `test_f2_04_face_keyword_totality.py` and
`test_wave2_f1_02_case_frame_codec_unvalidated.py`. Falsify tests are scratch evidence of
the wave that wrote them, not a maintained suite: they are **not** updated to track later
refactors, and the directory is git-ignored and outside every suite the gate runs.

**Acceptance:** Not a scheduled fix. This entry only prevents a future reader from
mistaking a stale `falsify/tests/` fixture for a live defect: a wave that meets one of
these fixtures failing or looking wrong against current types cites this entry and marks
the question Settled, rather than re-deriving the ruling or filing the staleness itself as
a finding. Only promoting `falsify/tests/` to a maintained, tracked suite would reopen it.

### Wave 3's declined and rejected design proposals, recorded for citation

**Status:** Ruled — recorded so a later wave can mark a rediscovery Settled by citing this
entry rather than re-deriving the argument. From the 2026-08 architecture review's wave 3
design verdicts (T13, `design/wave3-t13-one-write-rule-VERDICT.md`; T15,
`design/wave3-t15-registration-stated-at-value-VERDICT.md`) and T17's own theme text
(`reviews/wave3-themes.md`). All five below are **decisions**: each states a considered
alternative and the reason it was not built, with no residual "not yet done" — the review's
own rule is that an ADR or design record stating a decision ("we chose X over Y") is Settled,
while one recording a gap ("not yet owned", "a debt") is open work wearing a citation. None of
these five is the latter; the residual limitations two of them leave behind are filed as
their own Minor entries above ("The checked registration does not record whether it was
reconciled"; "The 1590LB reconciliation turns on a difference finer than the matcher's own
tolerance, silently") rather than folded into this entry.

**Constraint:**

- **A `reconciled: bool` flag on `CaseRegistration`.** Declined: no consumer today reads it —
  `stompcollider-technical.md`'s "What a placement is", "The report" and "Command line"
  read `case.frame` as a complete
  registration and never asks after its provenance — and a forecast consumer licenses not
  narrowing an interface, never adding one.
- **A public `axis_correspondence` primitive in `stompmodel`.** Rejected: one call site after
  the fix, so publishing it would be a hypothetical seam.
- **The predicted fold across `CoordinateFrame` / `FaceFrame` / `basis` /
  `EnclosureMatch.rotated`.** Declined, and scored *further away* after ticket 28 than
  before it: post-fix, `rotated` states the catalogue's printed row order (read by two
  display sites) and the registration states the panel's own measurement — two concepts that
  no longer even read the same input. Collapsing them would leave both concepts standing and
  add a translation between them — Speculative Generality by name. This is wave 3's scored
  answer to wave 2's forecast (prediction P1 in the wave-3 synthesis), not an omission.
- **A shared ordered view both the Excellon and STEP emitters read, instead of each sorting
  `numbered()` itself.** Rejected: two call sites, and the shared thing would be one
  `sorted()` call — a helper that relocates rather than concentrates, failing the folding
  guard's second clause.
- **A batch-write helper or shared-CLI write layer for the write mechanism (T13).** Barred by
  wave 1's ruling and wave 2's ticket 22 adjudication, both already recorded at "Defer moving
  the CLI's usage/IO policy below `stompdrill`" above; none of T13's three design lanes
  proposed one. Rediscovery is noted on that entry, not repeated here.

**Acceptance:** Not implementation work. A later wave that reconsiders any item above cites
this entry and marks its own finding Settled without repeating the argument, unless it has a
real second consumer the argument above did not have.

### Wave 4's declined and rejected design proposals, recorded for citation

**Status:** Ruled — recorded so a later wave can mark a rediscovery Settled by citing this
entry rather than re-deriving the argument. From the 2026-08 architecture review's wave 4
design verdicts (`design/wave4-t18-stompgeom-owns-its-handles-VERDICT-v2.md`,
`design/wave4-t19-the-mechanism-states-its-contract-VERDICT.md`) and tickets 32, 33, 34, 35
and 36's own "Out of scope" sections. Each item below states what was refused, why, and
what would make it correct later — the third clause is what a "decision" record owes that
a bare rejection does not, and its absence is how a ruling is mistaken for a "not yet".

**Constraint:**

- **A mutation, edit or undo session owning `stompgeom`'s cut-and-restore protocol
  (ticket 34).** Rejected by name as Speculative Generality: the protocol has exactly one
  call site (`stompdrill.emitters.step.cut_shape`), its undo closure never crosses a
  package boundary, and three independently designed lanes refused it unprompted before
  any probe was run. **Correct later if:** a second call site appears whose undo crosses a
  package boundary — the shape chosen (a document, an `undo` closure, and an entry-string
  set) is a strict subset of the session, so nothing already built forecloses it.
- **A shared AST-scan helper across the five ownership gates (ticket 32; the same fold T20
  names and declines).** Declined: the gates' differing reaches — source plus `tools/` for
  three of them, source only for one, source plus `tests/` for the fifth — are three
  argued policies, not one rule restated three times, and flattening them would destroy a
  real distinction. **Correct later if:** two or more gates' reach areas collapse onto the
  same policy through an unrelated change, so the "three argued policies" premise no
  longer holds; not correct merely because the five gates look similar today.
- **A movement-reporting protocol or base class shared by the position and diameter
  quantisers (ticket 36).** Rejected: one side compares a two-dimensional distance over a
  uniform, operator-declared pitch without taking a square root; the other compares a
  one-dimensional signed scalar over a non-uniform published table. The only shared text is
  the comparison operator itself — a helper here would relocate one line, not concentrate a
  rule. **Correct later if:** a third quantiser needs the identical comparison shape *and*
  the identical inputs (a uniform pitch, or a non-uniform table — not merely "some
  threshold"), giving the fold a real third data point rather than a second name for the
  same coincidence.
- **A published target-domain predicate, or a set-level writer, in `stompmodel` (tickets
  33 and 35, settled by the coordinator's own Q6 ruling).** Forbidden: a forecast consumer
  licenses not narrowing an interface, never adding one, and no second caller of a
  target-domain check exists yet. The narrow way to satisfy the theme without adding a name
  — making `stage_payload` enforce its own domain — was taken instead. **Correct later
  if:** `stompcollider` (or another real caller) needs to validate a target's domain ahead
  of a write it does not itself perform, at which point the predicate has a genuine second
  consumer and the forecast-consumer rule licenses publishing it.
- **A pre-flight readability probe in `stompdrill`'s command line (tickets 33 and 35).**
  Refused: this wave's own reproduced defect is that the *existing* probes are less
  accurate than the operation they anticipate — they consult the real uid/gid and ignore
  ACLs where the write itself reports the filesystem's true answer at the moment it
  matters — and a readability probe repeats exactly that mistake for reading instead of
  writing. **Correct later if:** never, on the reasoning given — this is closer to a
  standing rule than a "not yet" deferral. The only way this becomes correct is if the
  filesystem stopped being able to answer authoritatively at the moment of the real
  operation, which is not a forecast that has a trigger.
- **A "dry-run" staged write used as a pre-flight probe (ticket 33).** Rejected: it invents
  the concept of a staged write that is not a write, which makes ADR-0001's "nothing has
  yet been staged" before the pre-flight false. **Correct later if:** operators complain
  about the cost of a wasted render on a target that turns out to be out of domain — ticket
  33 names this explicitly as the trigger, not a hypothetical one.

**Acceptance:** Not implementation work. A later wave that reconsiders any item above cites
this entry and marks its own finding Settled without repeating the argument, unless it has
the real second consumer or trigger named above.

### `Pipeline` has no per-stage observation point, and the DRY consequence claimed for it is false

Raised in the 2026-08 architecture review's wave 1 (F2-06) as an open gap; refuted in
wave 5's confirm phase (C8) and closed here as a decision.

**The true clause.** `Pipeline` exposes no per-stage hook a caller can observe a
`StageRun` through as it runs. That much is correct and unchanged.

**The false consequence.** The entry claimed `cli.run_pipeline` "iterates it a second
time to produce `-v` output". It does not. `run_pipeline`'s first statement is
`if trace is None: return pipeline.run(data)`, so the traced and untraced paths are
mutually exclusive, not one on top of the other. Instrumented `apply()` call counts are
1 per stage on **both** paths, and artefacts are byte-identical between a `-v` run and a
non-`-v` run. There is no duplicated iteration to remove, so the DRY argument that
motivated the work is not available.

**The refusal, and why.** A hook on `stompmodel.protocols`' published `Stage` /
`Pipeline` contract, added for a consumer that does not exist, is exactly what this
review's forecast-consumer rule declines to license: a forecast consumer licenses *not
narrowing* an interface, never *adding* one. `stompcollider` is a certain future
consumer, but a certain future consumer whose `-v` has not been designed cannot say what
shape the seam should be, and today's single caller does not need it at all.

**What would make it correct later.** A second real consumer that needs per-stage
observation -- concretely, plan 3 shipping a `stompcollider -v` of its own that wants the
same five lines. At that point there are two callers in the room, the seam is designable
from both, and this entry is cited rather than re-derived. Nothing is owed before then.

### Wave 5's declined and rejected design proposals, recorded for citation

**Status:** Ruled — recorded so a later wave can mark a rediscovery Settled by citing this
entry rather than re-deriving the argument. Transcribed from the wave-5 branches' own commit
messages and "Out of scope" sections (tickets 39–45), not from memory. As with wave 3's and
wave 4's entries above, each item states what was refused, why, and what would make it
correct later; the third clause is what a decision record owes that a bare rejection does
not.

**Constraint:**

- **Committing a `SHA256SUMS` reference for the behaviour lock (ticket 39).** Refused: the
  digests carry the OpenCASCADE processor's version string and descend from a Hammond model
  fetched at run time, so a committed reference would go red on a different kernel wheel for
  no change in this repository at all. The decision is stated once in ADR-0011 — tracked, the
  procedure; untracked, the reference. **Correct later if:** the artefacts stop carrying
  kernel-version-dependent bytes, which would take the STEP panel out of the lock or the
  version string out of the writer's output.
- **Pinning the behaviour lock's blind-spot classes with a test (ticket 39).** Refused with
  its reason recorded in ADR-0011: the only way to falsify a blind-spot class is to improve
  the lock, so the guilty probe and the innocent probe would be the same event, and a gate
  whose two probes cannot be distinguished is not an instrument. **Correct later if:** the
  lock grows a second panel that exercises an error path, at which point the "any error
  withholds every requested artefact" class becomes testable rather than assumed.
- **`os.path.samefile`, `os.pathconf`, a write-probe, and fold-then-fall-back-to-samefile,
  for the `--emit` duplicate-target key (ticket 40).** All four refused, and the reasons
  differ: `samefile` raises when neither target exists, which is the reported reproduction's
  own case; `PC_CASE_SENSITIVE` is not exposed by CPython here and answers about a volume
  rather than about two names; a write-probe re-imports into the pre-flight the target-domain
  preconditions ticket 35 deliberately moved out of it, and creates files for a run that may
  never write one; and the hybrid would refuse a command line on Monday and accept it on
  Tuesday, making the usage contract a function of what is already on disk. A
  non-deterministic refusal is a worse instrument than a deterministic over-fire.
  **Correct later if:** a platform appears whose folding rules the unconditional key gets
  wrong in the *refusing* direction — today's residual error is silent under-detection only.
- **A shared path-folding helper module (ticket 40).** Refused as ceremony: `cli.py`'s
  duplicate key is the only site in the workspace asking whether two paths are the same file,
  verified by grep over `packages/*/src` and `tools`. **Correct later if:** `stompcollider`'s
  own command line needs the same key — and that case is already carried, with two earlier
  rediscoveries, by "Defer moving the CLI's usage/IO policy below `stompdrill`" above.
- **Every mechanism for enforcing the staged write's commit-or-discard obligation
  (ticket 41).** Three independent design seats each proposed one and the judge refused all
  three; the refusal, its four candidate detectors and the caller-side residue assertion that
  does catch an abandoned temporary are recorded in ADR-0005's own Decision subsection.
  `__del__` is refused on merit, not on impossibility — it works on a frozen slotted
  dataclass. **Correct later if:** a second production caller stages a payload without
  discharging it in the same expression, which is the shape a detector could actually find;
  both of today's call shapes are followed trivially or reach their value only by iterating
  the collection that holds it.
- **A shared AST-scan helper across the ownership gates, rediscovered (ticket 42).** The
  wave-4 ruling above was read and its correction condition tested rather than assumed: the
  gates' reaches are still three argued policies, not one, so the condition has not fired and
  the decline stands. Four copies of `_outside` are the accepted price. Function-level
  pairing of the guilty and innocent probes was separately considered and refused.
  **Correct later if:** two or more gates' reach areas collapse onto one policy — unchanged
  from wave 4's statement of it.
- **Enforcing the hole-index permutation at `DrillData.numbered()`, at `Hole`, at a
  `DrillData.__post_init__` or at `to_document` (ticket 43).** All four refused; the reader
  is where the rule lands. Two reasons, both recorded in ADR-0006's fifth amendment: a
  fixture that numbers a lone hole out of range is this workspace's own "read the number, not
  the position" instrument and a constructor refusal would delete it, and a legal
  `Deduplicate`-after-`RouteHoles` composition owes a diagnostic rather than a crash.
  **Correct later if:** the pipeline's stage order is fixed such that no legal composition
  can produce a gapped set, at which point a constructor refusal costs nothing.
- **Breaking `_nearest_companion_level`'s distance tie towards the drilled face
  (ticket 44).** The ticket's own acceptance criterion 4 asked for it and was **waived as a
  ticket defect** under the coordinator's ruling: the drilled-face side is the *receding*
  one, so electing it would classify a real boss as relief and report an obstructed hole
  clear. The shipped rule breaks the tie towards the proud side, `+inner.outward`.
  **Correct later if:** nothing — this is a safety direction, and a later proposal to flip it
  should cite the measurement on the real 1590BB that settled it rather than the criterion
  that asked for it.
- **Narrowing `stompdrill`'s published root return type to the `CaseModel` protocol
  (ticket 45).** Refused twice over: it would replace an `ImportError` with the one value
  `StepEmitter.__init__` refuses, and it contradicts ADR-0007:279-282's root-export mandate.
  Removing `load_case_model` from the root was refused on the same ADR grounds.
  **Correct later if:** ADR-0007's root-export mandate is itself revisited, which is an ADR
  decision and not a code one.
- **Adding a `stompcollider` duplicate-target rule, a `stompgeom` cut-and-restore session,
  and any other seam with one caller.** Refused across several tickets under one rule, which
  is worth stating once: a forecast consumer licenses **not narrowing** an interface; it never
  licenses **adding** one. **Correct later if:** the forecast consumer becomes a real second
  caller in the room while the seam is being designed — which is precisely what plan 3 is
  expected to supply.

