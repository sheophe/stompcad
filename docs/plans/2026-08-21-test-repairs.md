# Test-Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four recorded test-quality defects carried forward from the verification
programme, and the wider classes that recon proved each of them belongs to.

**Architecture:** Six independent tasks over the two packages' test suites. Five repair
tests; the sixth records what was measured. Only two production files are touched, both
docstring-only. No behaviour changes.

**Tech Stack:** Python 3.10+, pytest, mutmut 3.x, ruff, mypy, a two-member uv workspace.

**Authority:** This plan has **no spec**. In its place stand three recon reports and a
rulings file, all under `.scratch/test-repairs/`:

- `recon-a-excellon.md` — the hollow test and the compound-assertion class
- `recon-b-kappa.md` — the `_kappa_consistent` mutation survivors
- `recon-c-invariant.md` — the pipeline-composition class
- `rulings.md` — twenty-four rulings, R-1 to R-24, that settle every open question the
  three reports raised
- `baselines.md` — the measured starting counts

**Where the plan cites a recon section for exact code, that section is the requirement and
is to be followed verbatim.** The reports are the authority a spec would normally be; they
are long because they carry the evidence, and copying their code blocks into this file
twice would create precisely the second-copy drift this plan exists to remove.

---

## Global Constraints

Every task's requirements implicitly include this section.

**Environment**

- Repository root `/Users/thelyx/repo/stompcad`. Branch `stompcad-test-repairs`.
- **Anchor every `find` / `grep` / `rg` to an explicit path inside the repository.** Never
  search `~`, `/`, `$HOME`, or issue a bare recursive walk. Hard user requirement.
- **Never run plain `uv sync` or plain `uv run` inside a workspace member** (`packages/*`).
  Both re-resolve the shared root `.venv` and strip `pikepdf` and `OCP`. Use the root venv's
  binaries by absolute path. The single sanctioned exception is `uv run --no-sync mypy`
  inside `packages/stompmodel`.
- Recovery if the environment is broken: `uv sync --all-packages --all-extras` from the root.

**Measured baselines** (`.scratch/test-repairs/baselines.md`, taken on this branch at base
`f6af5a8`, before any commit):

| Gate | Result |
|---|---|
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q` | **1213 passed** |
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q` | **241 passed** |
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q` | **1119 passed, 94 skipped** |

**R-24 binds every task: no task predicts a test count.** Three streams move the totals in
opposite directions. State the baseline you measured at the start of your own task, run the
suite, and report what you actually got. If your number differs from what you expected, say
so plainly and investigate — **do not construct an explanation for it.** A previous run's
implementer met a stale predicted count and invented "some previously skipped tests may now
run" rather than reporting the discrepancy. Report the discrepancy.

**Project law** (`CLAUDE.md`, binding)

- A test must fail when the behaviour it names is removed.
- Check each clause of a compound condition independently.
- Ensure a mutation changes only the behaviour under test.
- Keep new or edited docstrings to at most **ten physical lines**.
- Keep `from __future__ import annotations` and an explicit, logically ordered `__all__` in
  each Python module.
- British spelling in prose, established American spelling in identifiers.
- Mutation testing is a survey, not a numeric gate. Read it by module.
- Verification reports name the exact commands run; a tool invocation that suppresses the
  claimed rule is not evidence.

**Gates every task must leave green**

```bash
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
```

**No TDD in this plan, and what replaces it.** This plan repairs and updates tests; it does
not build features, so there is no red-green cycle. The discipline that replaces it is
**adversarial verification**, and it is not optional:

- A test added to kill a mutant must be shown to **fail against that mutant and pass against
  real code**. Hand-mutate a scratch copy or load a monkeypatching pytest plugin from outside
  the repository — never edit tracked source to test a test.
- A test deleted must be shown to **cost nothing**: the mutation it caught must still be
  caught after the deletion.
- A split assertion must be shown to have **independently reachable clauses**, or the task
  must say plainly that it does not.

Throwaway harnesses go under `/Users/thelyx/.claude/jobs/`, never in the repository.

**Commits.** One commit per task, British spelling in the message body, and the trailer:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

## File Structure

| File | Task | Change |
|---|---|---|
| `packages/stompdrill/tests/test_excellon.py` | 1 | delete a test, amend a fixture docstring, split two assertions |
| ~10 test modules, both packages | 5 | split ~45 compound assertions |
| `packages/stompdrill/tests/test_invariant.py` | 2 | run the shipped pipeline; add clearance and breakout coverage |
| `packages/stompdrill/tests/test_pipeline.py` | 3 | complete `ALL_STAGES` |
| `packages/stompdrill/tests/test_cli.py` | 3 | delete a duplicate test, correct an import |
| `packages/stompdrill/tests/test_geometry.py` | 4 | six new tests |
| `packages/stompdrill/src/stompdrill/geometry.py` | 4 | one docstring clause (no behaviour change) |
| `CLAUDE.md` | 6 | correct a stale count, record the equivalent-mutant floor |
| `.scratch/test-audit/*.md` | 6 | refresh stale citations |

**Order matters here, and it is not the order the items were recorded in.** Tasks 1–4 touch
disjoint files and could run in any sequence. Task 5's sweep, however, reaches into
`test_geometry.py`, `test_pipeline.py`, `test_cli.py` and `test_containment.py` — the same
files Tasks 3 and 4 rewrite — so it runs *after* them. That is not merely conflict avoidance:
the sweep re-derives its own list with a grep, so running it last means it also catches any
compound assertion the new tests introduce. Task 6 runs last of all, because it records what
Tasks 1–5 measured.

---

### Task 1: The excellon file's three defects

**Files:**
- Modify: `packages/stompdrill/tests/test_excellon.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks consume. `test_excellon.py` has no entry in Task 5's sweep
  list, so the line numbers you shift here do not invalidate that task.

**Requirement:** `.scratch/test-repairs/recon-a-excellon.md`, sections "Defect 1",
"Defect 2a" and "Defect 2b". Rulings R-1, R-2, R-3, R-9.

- [ ] **Step 1: Read the requirement**

Read `recon-a-excellon.md` in full and `rulings.md` R-1 to R-3 and R-9. The exact
replacement code for all three defects is in the report.

- [ ] **Step 2: Measure your starting point**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_excellon.py -q
```

Record the number. Expect 41 passed; if it is not 41, stop and report rather than proceeding.

- [ ] **Step 3: Prove the deletion costs nothing — before deleting**

```bash
PYTHONPATH=/Users/thelyx/.claude/jobs/excellon-recon .venv/bin/python -m pytest \
  -p no:cacheprovider -o addopts= -p mutate_numbered \
  packages/stompdrill/tests/test_excellon.py -q
```

Expect **2 failed**: the guard test, and
`test_a_hole_outside_the_reference_outline_is_refused_in_lower_left`. The second is the one
that matters — it is the kill that survives the deletion. If the harness directory is
missing, recreate `mutate_numbered.py` from the report's quoted source.

- [ ] **Step 4: Delete the guard test and its orphaned banner**

Delete `test_the_fixtures_numbers_are_a_permutation_out_of_tuple_order` entirely, together
with the `# --- the fixture itself ---` banner comment above it, which then heads nothing.
Exact line range and banner text are in the report.

- [ ] **Step 5: Move the rationale onto the fixture**

Replace `fixture_data()`'s docstring with the seven-line version in the report. **Do not
change the holes' numbers** — they stay scrambled; that is the whole point. The new
docstring is the only place a future editor of this fixture will meet the reason.

- [ ] **Step 6: Re-run the mutation harness to prove the deletion cost nothing**

```bash
PYTHONPATH=/Users/thelyx/.claude/jobs/excellon-recon .venv/bin/python -m pytest \
  -p no:cacheprovider -o addopts= -p mutate_numbered \
  packages/stompdrill/tests/test_excellon.py -q
```

Expect **1 failed** — `test_a_hole_outside_the_reference_outline_is_refused_in_lower_left`.
This command is the task's central evidence. Quote its output in your report.

- [ ] **Step 7: Split the non-negative-coordinate assertion (defect 2a)**

Replace the compound assertion in `test_lower_left_keeps_every_coordinate_non_negative` with
the two-assertion form in the report. **Carry `, line` onto both halves** so the failing
coordinate line is still named.

Add the one-line docstring R-2 requires, recording that this test checks the emitted bytes
*behind* `_reject_negative_coordinates` rather than being the discriminating test of that
rule. Recon proved neither clause is reachable by any single production fault; the docstring
stops the next reader mistaking it for a front-line check.

- [ ] **Step 8: Split the header assertion (defect 2b)**

Replace line 461's compound with the two-assertion form in the report, keeping the
`# half the outline's width` / `# half its height` comments.

**Take the plain split, not the axis-anchored form** (R-3). Anchoring to `"X56.500"` /
`"Y30.000"` would also catch a swapped header, but recon proved
`test_the_stated_shift_is_the_shift_the_coordinates_were_moved_by` at line 475 already
catches that, and copying the rule is what this plan is removing.

- [ ] **Step 9: Run the gates**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_excellon.py -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Report the counts you measured. One test was deleted and none added, so the file's count
falls by one — but state the number you saw, not the number you expected.

- [ ] **Step 10: Commit**

```bash
git add packages/stompdrill/tests/test_excellon.py
git commit -F- <<'EOF'
Retire a fixture guard and split two compound assertions

The guard test named a property of a fixture, not of the product, so no
production behaviour could be removed to make it fail on its own terms.
Its docstring additionally claimed no production change could falsify it,
which is untrue: rewriting numbered() to yield list position does. That
mutation is killed eleven times over, once in this very file, so the
deletion costs no coverage -- proved by re-running the mutation with the
test gone. The reason the fixture's numbers are scrambled now sits on the
fixture, where an editor will meet it.

The two compound assertions become four. The header pair takes the plain
split: anchoring it to the axes would catch a swapped header, but the
neighbouring test already does, and a second copy of a rule is what this
work removes. The coordinate pair keeps its message on both halves and
gains a line saying it checks the bytes behind the emitter's own guard,
which is the only way either clause can be reached.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Make the invariance harness run the shipped pipeline

**Files:**
- Modify: `packages/stompdrill/tests/test_invariant.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks consume. Task 3 also completes the composition class, but in
  different files, so the two do not collide.

**Requirement:** `recon-c-invariant.md` §7 carries the **exact replacement code, already
verified**. Sections §3, §4 and §6 carry the reasoning. Rulings R-10 to R-14, R-17.

- [ ] **Step 1: Read the requirement**

Read `recon-c-invariant.md` §§3–7 and rulings R-10 to R-14. §7's code has been run: 7 passed
in 0.56s, ruff clean, mypy clean under the root gate's flags.

- [ ] **Step 2: Measure your starting point**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_invariant.py -q
```

Expect 5 passed.

- [ ] **Step 3: See the defect for yourself**

Before changing anything, reproduce the provenance divergence §3 measured — that the
harness's JSON differs from the shipped JSON by the `processing` key. §4 has the script. This
is the evidence that the harness certifies a document the CLI never emits, and it is what
the repair fixes for free.

- [ ] **Step 4: Replace `artifacts()` with the shipped pipeline**

Apply §7's replacement. The essentials:

- `artifacts()` calls `build_pipeline(...)` and runs the `Pipeline` it returns, rather than
  folding a hand-written tuple of stages.
- Fold through **`Pipeline.run`, not `stage.apply`** (R-10), so provenance is certified too.
- Obtain the namespace with **`build_parser().parse_args(["panel.ai"])`**, not a bare
  `argparse.Namespace()` (R-13). The bare form is far cheaper but silently depends on
  `build_pipeline` continuing to read nothing but `case_model_object`; the parsed form
  survives it growing a dependency on another flag, and matches `test_cli.pipeline_for`.

Option (b) — keeping the tuple and asserting it matches — is **rejected** (R-11): it keeps
the copy, adds a fourth restatement of the stage names, and leaves the provenance divergence
untouched.

- [ ] **Step 5: Certify the five-stage composition too**

Add §7's clearance test (R-12). The CLI ships **two** compositions, and ADR-0007 puts
clearance in the `Pipeline` precisely because its diagnostics are shared facts — a shared
fact that varied with element order would break ADR-0006 exactly as a coordinate would. Use
`conftest.FakeCase()`; it runs against `pax.ai`.

- [ ] **Step 6: Add the breakout panel**

Add §7's `_breakout_raw()` (R-14). Neither `tar.ai` nor `pax.ai` raises
`hole-outside-outline`, so without this the fourth stage is certified on its silent path
only — and recon measured that the drawings *do* change once the finding appears.

Derive it from `_synthetic_raw()` with `dataclasses.replace`. **Do not add a sixth hole to
`_synthetic_raw()` itself**: its docstring makes precise claims about which of its five holes
make which sort clause load-bearing, and a sixth would quietly falsify them.

- [ ] **Step 7: Verify**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_invariant.py -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Recon measured 7 passed for this file. Report what you got.

- [ ] **Step 8: Prove the harness now certifies the shipped artefacts**

Re-run Step 3's comparison. The harness's JSON must now match the CLI's, `processing`
included. Quote the output — this is the task's central evidence.

- [ ] **Step 9: Commit**

```bash
git add packages/stompdrill/tests/test_invariant.py
git commit -F- <<'EOF'
Certify the pipeline the CLI ships, not a hand-copied third of it

ADR-0006's binding invariance test composed its own pipeline from a
hard-coded tuple of three stages, where build_pipeline ships four and a
conditional fifth. It also folded with stage.apply rather than
Pipeline.run, so it recorded no provenance at all: its JSON differed from
the shipped JSON by the whole processing key. The test certifying that
geometry alone determines output was certifying a document the CLI never
emits.

It now runs the Pipeline that build_pipeline returns. That removes the
copy instead of guarding it, and is what ADR-0001 already asks for -- the
composition is meant to be read at the invocation boundary, and
build_pipeline is that boundary. Order is the one thing a stage cannot
self-declare, so a test that certifies the fold must read the fold from
where it is decided.

Both shipped compositions are now covered, the four-stage and the
five-stage with a case model, since clearance diagnostics are shared facts
that would break the invariant just as a coordinate would. A breakout
panel joins the two clean fixtures so the containment stage is certified
on the path where it actually says something.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: Complete `ALL_STAGES`, and remove the CLI's duplicate

**Files:**
- Modify: `packages/stompdrill/tests/test_pipeline.py`
- Modify: `packages/stompdrill/tests/test_cli.py`

**Interfaces:**
- Consumes: nothing. Independent of Task 2 despite sharing its subject.
- Produces: nothing.

**Requirement:** `recon-c-invariant.md` §1 rows 11, 14, 15 and §8. Ruling R-10.

This is the **larger instance** of the class Task 2 fixes. `ALL_STAGES` is commented "Every
class that satisfies `Stage`" and omits two of them, so those two are subject to none of the
five cross-cutting contracts it drives.

- [ ] **Step 1: Read the requirement**

Read §1's rows 11, 14 and 15, the subsection "The one that matters most, #14", and §8.

- [ ] **Step 2: Confirm the coverage hole is real**

`ALL_STAGES` drives `test_stages_are_pure_functions`, `test_stages_survive_empty_input`,
`test_stages_preserve_existing_diagnostics`,
`TestDescribe::test_a_stage_describes_itself_under_its_own_name` and
`test_a_pipeline_records_its_stages_in_order`. Confirm that neither
`CheckOutlineContainment` nor `CheckCaseClearance` is covered for input non-mutation,
the wholly-empty `DrillData()` case, or preservation of a prior diagnostic — recon checked
`test_containment.py` and `test_clearance.py` and found none of the three. Verify rather
than assume; this is what justifies the change.

- [ ] **Step 3: Add both stages to `ALL_STAGES`**

Add `CheckOutlineContainment()` and `CheckCaseClearance(FakeCase())`, making the comment
true. Recon ran both against all four contracts:

```
CheckOutlineContainment empty ok, holes= () codes= []
  preserves prior: True
  describe name == check-outline-containment check-outline-containment
CheckCaseClearance empty ok, holes= () codes= ['case-model-unverified']
  preserves prior: True
  describe name == check-case-clearance check-case-clearance
```

Both should pass as-is. `CheckCaseClearance` adds an INFO diagnostic on empty input, from the
no-enclosure branch; `test_stages_survive_empty_input` asserts holes, reference, source and
the prior finding, not the absence of new ones — so this is expected, not a failure to
suppress. **If any contract does fail, report it rather than adjusting the contract**: a
genuine failure here is a finding about the stage, not about the test.

- [ ] **Step 4: Delete the duplicate CLI test**

`test_cli.py:1719-1726` (`test_no_case_model_leaves_the_pipeline_unchanged`) asserts the same
four stage names as `test_the_cli_fixes_the_stage_order` at `:294`. Delete it, or keep it and
reduce it to only what it uniquely adds. Prefer deletion — `:294` is the specification, and
one specification is enough.

Leave `:1729-1736` alone; it asserts the conditional fifth stage and is not a duplicate.

- [ ] **Step 5: Correct the misdirected import**

`test_cli.py:1731` reads `from tests.test_clearance import FakeCase`. `FakeCase` is defined
at `conftest.py:198` and merely re-imported by `test_clearance.py:9`. Import it from
`tests.conftest`, where it lives.

- [ ] **Step 6: Verify**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_pipeline.py packages/stompdrill/tests/test_cli.py -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Two stages joining five parametrised contracts adds collected tests; one deletion removes
one. Report the number you measured.

- [ ] **Step 7: Commit**

```bash
git add packages/stompdrill/tests/test_pipeline.py packages/stompdrill/tests/test_cli.py
git commit -F- <<'EOF'
Subject every stage to the contracts ALL_STAGES claims to cover

ALL_STAGES is commented "Every class that satisfies Stage" and listed four
of them, omitting CheckOutlineContainment and CheckCaseClearance. It
drives five cross-cutting contracts -- purity, empty input, diagnostic
preservation, self-naming and pipeline ordering -- so both omitted stages
were subject to none of them, and their own test modules cover none of the
three that matter. An untrue comment was hiding a real coverage hole
rather than merely a stale list.

Both stages join the list and pass all five. The CLI's duplicate assertion
of the stage order goes, since the test above it is already the
specification, and FakeCase is imported from the conftest that defines it
rather than from a module that only re-imports it.

With this and the invariance harness, the stage order is stated in exactly
two places: build_pipeline, and the one test that specifies it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Kill the six killable kappa mutants

**Files:**
- Modify: `packages/stompdrill/tests/test_geometry.py`
- Modify: `packages/stompdrill/src/stompdrill/geometry.py` (docstring only, no behaviour)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

**Requirement:** `recon-b-kappa.md` §4 carries the **six tests, complete and gated**. §3
carries the classification and the distinguishing inputs. Rulings R-19 to R-23.

- [ ] **Step 1: Read the requirement**

Read `recon-b-kappa.md` §§3–5 and rulings R-19 to R-23. Recon measured: 70 mutants in
`_kappa_consistent`, 56 killed, **14 survive** — six killable, eight provably equivalent.

- [ ] **Step 2: Understand what you are *not* doing**

**Eight survivors stay alive deliberately** (R-19). `mutmut_20/27/28/30` double `travel` or
`sense`, which reach exactly one sign test, so a positive scale factor cannot change the
outcome. `mutmut_59/60/62/63` turn `* ±1.0` into `/ ±1.0`, bit-identical for every IEEE-754
double. Killing any of them would mean asserting an unobservable.

**Do not attempt them, and do not report a clean sweep.** The honest floor for this function
is 8 survivors out of 70, and the residual is part of the deliverable.

- [ ] **Step 3: Add the six tests**

Apply §4's tests verbatim. They are already gated: ruff clean, mypy clean, longest line 99,
docstrings within ten lines. They kill:

| Mutant | What it breaks |
|---|---|
| 9 | winding read without subtracting the centre |
| 24 | the exactly-zero cross-product tie-break |
| 44 | the length band closed on the wrong side |
| 52 | `/radius` → `*radius`, inverting the radial guard with scale |
| 56 | the radial band closed on the wrong side |
| 67 | `<=` → `<`, admitting a cusp whose tangential dot is exactly zero |

Recon measured these one-to-one: each mutant fails exactly its own test and no other.

- [ ] **Step 4: Keep the colinear test, and say the case is unreachable**

`mutmut_24`'s test pins a tie-break `fit_circle` cannot reach — it needs `tolerance >= 1`.
Keep it (R-20), with the docstring stating the unreachability outright.

This does not collide with Task 1's deletion. That test named a property of a *fixture*; this
names a real tie-break in real code and fails when that behaviour is removed, which is
CLAUDE.md's actual rule. `test_geometry.py` already imports the private predicates on
purpose, for exactly this reason.

- [ ] **Step 5: Record the closed-band convention**

Add one clause to `fit_circle`'s existing docstring stating that the tolerance band is
**closed** — `> slack` rejects, so a value exactly one slack out is accepted (R-22). Three
guards in `fit_circle` and both bands in `_kappa_consistent` rely on this, and nothing said
so, which is why `mutmut_44` and `mutmut_56` survived.

Docstring only. **No behaviour change** — recon confirmed all six kills need none. The
docstring is currently four lines and the cap is ten. Not an ADR: a float-comparison
convention inside a geometry helper is not an architectural decision.

- [ ] **Step 6: Take `_quarter_turns` mutmut_12 as well**

It is the *same* `/ radius` → `* radius` scale inversion as kappa's `mutmut_52` (R-23), and
recon has done half its analysis. Recon measured that the six new tests do **not** kill it:
on a true quarter turn `p·q` is exactly zero, so no scaling of zero crosses any threshold.
Killing it needs a **near**-quarter turn at a small radius.

Write that test. Verify it fails against a hand-mutated `_quarter_turns` and passes against
real code. **If it resists, record it as residual with the reason rather than forcing it** —
an honest residual beats a test that passes for the wrong reason.

- [ ] **Step 7: Prove each test kills its mutant**

For each of the seven, hand-mutate a scratch copy under `/Users/thelyx/.claude/jobs/` and
show the test failing against the mutant and passing against real code. Recon's harness and
method are in §3.2. **Quote the results.** A test added to kill a mutant, without evidence it
does, is not evidence.

- [ ] **Step 8: Re-run the scoped survey**

```bash
(cd packages/stompdrill && PYTHONDONTWRITEBYTECODE=1 \
  ../../.venv/bin/mutmut run 'stompdrill.geometry.x__kappa_consistent*' \
  && ../../.venv/bin/mutmut results)
```

Recon's scoped run took 9s on a warm stats cache. Expect **8 survivors, all equivalent**.
Report the actual figure. If more than eight survive, name which and why.

- [ ] **Step 9: Run the gates**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_geometry.py -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Recon predicted +8 collected from its six tests, plus yours from Step 6. Report measured.

- [ ] **Step 10: Commit**

```bash
git add packages/stompdrill/tests/test_geometry.py packages/stompdrill/src/stompdrill/geometry.py
git commit -F- <<'EOF'
Kill the six reachable kappa survivors and prove the other eight equivalent

Fourteen mutants survived in _kappa_consistent, the predicate that makes
circle recognition rotation-invariant. CLAUDE.md names geometry as a
module where a survivor is worth chasing, because it holds cited constants
rather than placement, and nobody had enumerated these.

Six were reachable and now have tests: a winding read that never
subtracted the centre, the exactly-zero cross-product tie-break, both
tolerance bands closed on the wrong side, a radial guard whose threshold
inverted with scale, and a cusp admitted where the tangential dot is
exactly zero. Each test was measured against its own mutant and no other.
The same scale inversion in _quarter_turns is taken too, since it is the
same defect and the six new tests provably do not reach it.

The remaining eight stay alive on purpose and the count is recorded rather
than rounded away: travel and sense reach exactly one sign test, so
doubling them changes nothing, and dividing by a unit is bit-identical to
multiplying by it. Killing those would mean asserting an unobservable. The
honest floor for this function is eight of seventy.

fit_circle's docstring now states that the tolerance band is closed, which
is what two of the six survivors were exploiting in the silence.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: The compound-assertion sweep

**Files:**
- Modify: ~10 test modules across both packages. The authoritative list is in
  `recon-a-excellon.md`, "Additional compound assertions found by sweep", Groups 1, 2 and 3.

**Interfaces:**
- Consumes: the finished state of Tasks 1–4. This task runs **after** them because its list
  reaches into `test_geometry.py`, `test_pipeline.py`, `test_cli.py` and `test_containment.py`,
  which Tasks 3 and 4 rewrite.
- Produces: nothing.

**Requirement:** `recon-a-excellon.md`'s sweep section. Rulings R-4, R-5, R-6.

This is a large but mechanical batch: one shape of edit, ~45 times. It is one task and one
commit because a reviewer judges it as one unit.

- [ ] **Step 1: Re-derive the list rather than trusting it**

```bash
grep -rnE "^[[:space:]]*assert .* (and|or) " \
  packages/stompdrill/tests packages/stompmodel/tests --exclude-dir=mutants
```

65 raw hits at the time of writing. Recon classified ~45 as genuine top-level compounds and
the rest as false positives — an `and`/`or` inside an expression, a comprehension filter, or
a trailing prose comment. **Re-derive, do not trust the tabled line numbers**, which shift as
you edit.

- [ ] **Step 2: Work file by file, bottom to top**

Within each file, edit from the highest line number downwards so earlier edits do not
invalidate later line numbers.

For each genuine compound `assert A and B`:

```python
# before
assert A and B, "message"

# after
assert A, "message"
assert B, "message"
```

Rules that bind every split:

- **Carry the message onto both halves.** Where the message names only one side (for example
  `f"hole {row.number}: only one Y shown"` at `test_drawing_agreement.py:312`), reword each
  half so it describes the clause it guards.
- **Three clauses become three asserts** (R-6): `test_cli.py:981` and `test_cli.py:1506`.
  The point of splitting `:1506` is to name *which* artefact is missing.
- **Group 3's guard-plus-claim pairs still split** (`assert X is not None and <claim>`).
  The split turns "something was wrong" into "there were no pairs" versus "there were the
  wrong number of pairs".
- `test_model.py:683`'s `and` sits inside a generator expression, so splitting it means two
  `all(...)` calls rather than two asserts on one expression.
- **Do not touch the false positives.** They are listed under "Not compound" in the report.

- [ ] **Step 3: Do both packages**

`stompmodel`'s entries (`test_codec.py:601`, `test_model.py:683`,
`test_diagnostics.py:33`) are in scope (R-4). The rule is workspace-wide; leaving them
because a recon brief happened to say "stompdrill" would be scoping by accident of dispatch.

- [ ] **Step 4: Leave chained equality alone**

Do **not** change `assert A == B == literal` (R-5). Fourteen sites, listed in the report.
pytest's assertion rewriting already prints both operands on failure, so which half broke is
visible, and the idiom is this repo's deliberate way of writing cross-artefact agreement.
This is a ruling, not an oversight — if you disagree, say so in your report and still leave
them alone.

- [ ] **Step 5: Verify the count did not move**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q
```

Splitting an assertion adds no test, so **both counts must be unchanged by your own work**.
Do not compare against this plan's opening baselines: Tasks 1–4 have already moved them.
Measure the counts *before* your first edit, measure them again after, and require the two to
match. A count that moves across your own diff means a split altered behaviour — investigate
before committing.

- [ ] **Step 6: Confirm the sweep is complete**

Re-run Step 1's grep. Every remaining hit must be a documented false positive. List them in
your report with the reason each is not a compound.

- [ ] **Step 7: Run the gates**

```bash
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
```

Watch for lines pushed past ruff's `line-length = 110` by the duplicated message.

- [ ] **Step 8: Commit**

```bash
git add packages/stompdrill/tests packages/stompmodel/tests
git commit -F- <<'EOF'
Split every compound assertion into independently failing clauses

CLAUDE.md asks that each clause of a compound condition be checked
independently. Roughly forty-five assertions did not, across both
packages: under `and`, the second clause is invisible whenever the first
has already failed, so a bounded interval reports only its lower bound and
a two-axis claim reports only its first axis.

The carried-forward item named one of these. An anchored sweep found the
rest, which is why the whole class goes rather than the recorded instance
-- fixing only what was written down would leave the same law broken in
forty places and recreate the mistake of reading a recorded list as a
complete one.

Messages are carried onto both halves and reworded where they named only
one side. Chained equality is deliberately left alone: pytest prints both
operands, so which half broke is already visible. No test is added or
removed and no count moves.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: Record what was measured

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.scratch/test-audit/contracts.md`, `.scratch/test-audit/kinds.md`

**Interfaces:**
- Consumes: the measured suite counts from Tasks 1–5. **This task runs last.**
- Produces: the branch's final recorded state.

**Requirement:** Rulings R-8, R-16, R-19.

- [ ] **Step 1: Measure the branch's true totals**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q
```

These two numbers are the only counts this task may write. **Do not carry forward any
number predicted by an earlier task.**

- [ ] **Step 2: Correct CLAUDE.md's stale counts**

`CLAUDE.md:298` and `:301` document `# 241 passed` and `# 1209 passed`. The stompdrill figure
was already stale before this branch — measured 1213 at base `f6af5a8` (R-8), having drifted
during the previous plan's fix wave. Replace both with what Step 1 measured.

- [ ] **Step 3: Record the equivalent-mutant floor**

CLAUDE.md's mutation-survey guidance says a survivor in `geometry` is the kind worth chasing.
That stays true, but a reader now needs to know that eight of `_kappa_consistent`'s are
proved equivalent and are not worth re-chasing (R-19). Add one sentence naming the floor —
eight of seventy — and pointing at this plan for the proof.

Keep it to a sentence. The proof lives in the recon report and this plan; CLAUDE.md carries
the rule and the pointer.

- [ ] **Step 4: Refresh the stale audit citations**

`.scratch/test-audit/contracts.md:86, 131, 223, 229` and `.scratch/test-audit/kinds.md:55`
cite `test_invariant.py` by line number and say "5 tests". Tasks 3 and 4 moved all of it.

The directory is git-ignored scratch and gates nothing, so this is housekeeping (R-16) —
but leaving it is the same drift in miniature, and it is the only inventory of which test
covers which contract. **Fix the citations only. Do not audit the rest of the directory.**

- [ ] **Step 5: Verify the docs match the code**

Re-read every count and line-number you wrote and confirm it against the file it names. A
verification report that names a command it did not run is worse than no report.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -F- <<'EOF'
Record the counts and the residual this branch actually measured

CLAUDE.md's documented suite count had drifted during the previous plan's
fix wave: it said 1209 where the branch point measured 1213. Both counts
now say what was measured after this branch's work, which is the discipline
the file itself asks for -- a verification report names the exact commands
run.

The mutation guidance gains a sentence naming a floor. A survivor in
geometry is still worth chasing, but eight of _kappa_consistent's seventy
are proved equivalent, and a reader who chases them will find nothing and
conclude the module is under-tested. Recording the number is the only way
the next survey reads the same result the same way.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Residuals this plan deliberately leaves

Named here so the branch does not imply a sweep it did not perform.

| Residual | Why |
|---|---|
| Eight equivalent `_kappa_consistent` mutants | Provably unkillable without asserting an unobservable (R-19). |
| Four other `geometry` survivors — `fit_circle` 44, 52; `_quarter_turns` 11, 17 | Need their own analysis; backlogged (R-23). |
| Fourteen chained-equality assertions | Not a defect; pytest prints both operands (R-5). |
| `numbered()` does not validate its index set | A `stompmodel` contract change needing ADR-0006 amended first; backlogged (R-7). |
| `build_pipeline` reads `case_model_object` off the namespace | A `cli.py` signature change; backlogged (R-15). |
| ADR-0001's "fixed composition" wording | Measured as current and in agreement; downgraded to a wording question (R-18). |
| The unscoped `stompdrill` mutation survey | Never run; backlogged, and out of scope here. |

## Corrections this plan makes to the record

Three of the four carried-forward items were recorded inaccurately. The plan states the
measured facts; the landed plans that carry the original claims are history and are **not**
back-edited (R-9).

- **Item 1** was "the one test no production change can falsify". False — mutating
  `numbered()` to yield list position falsifies it. It is deleted for redundancy instead.
- **Item 3** said "5 of 19" killed. The 14 survivors are right; 19 was the pre-repair
  survivor count, not the mutant total, which is 70.
- **Item 4** implied ADR drift. Every live restatement was measured as current and in
  agreement.
- **M-3** was understated: the harness also skipped `Pipeline.run`, so it recorded no
  provenance, and a larger instance sat in `ALL_STAGES`.
