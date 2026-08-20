# Instruments and Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mutation survey executable for both packages, and repair the
tests it showed to be hollow, so that later quality claims are falsifiable.

**Architecture:** Mutation testing cannot run from a uv workspace root —
mutmut's `setup_source_paths()` only ever puts `mutants/.`, `mutants/src` and
`mutants/source` on `sys.path`, and this workspace's sources land at
`mutants/packages/<member>/src/<member>`, which is none of those. The survey
therefore becomes per-member, run from inside each package, exactly as `pytest`
and `mypy` already are. With the instrument working, seven tests that pass
regardless of what the code does are repaired, each proved by killing the mutant
it currently misses.

**Tech Stack:** Python ≥3.10 (running 3.12), pytest, mutmut 3.7, mypy, ruff.

**Spec:** `docs/specs/verification-technical.md` — this is **plan 1 of 3** from
its "Order of work". The audit reports it argues from are in
`.scratch/test-audit/`, principally `mutation.md`.

## Global Constraints

- **Nothing observable changes.** No emitted artefact may differ. This plan
  touches one production file (`pipeline/dedupe.py` is **read** but not
  modified); everything else is tests, configuration and documentation.
- **A test must fail when the behaviour it names is removed.** Every repair in
  this plan is proved by applying the mutant it currently survives, watching the
  test fail, and reverting. A repair that is not proved that way is not done.
- **Check each clause of a compound condition independently**, and ensure a
  mutation changes only the behaviour under test. (CLAUDE.md, Testing rules)
- **Break accidental equality in fixtures: number routed holes out of tuple
  order**, so a test only passes an emitter that reads the number through
  `DrillData.numbered()`. (CLAUDE.md, Testing rules)
- **British spelling in prose, established American spelling in identifiers.**
- **Docstrings are at most ten physical lines** and explain why the code is
  shaped this way, never how it got that way. An in-suite audit enforces this.
- **`docs/adr/` is the authority.** A sentence that narrates what an ADR's own
  decision changed is history and must not be retrofitted; a sentence asserting
  a current fact must be true.
- Suites at the start of this plan: `stompdrill` **1154** under `--hammond`,
  **1060** without it; `stompmodel` **238**. Counts may only rise.
- Never run plain `uv sync` or plain `uv run` inside a workspace member — both
  re-resolve the shared root `.venv` and strip `pikepdf` and `OCP`. Use
  `uv run --no-sync`. Recover with `uv sync --all-packages --all-extras` from the
  repository root.
- Keep every filesystem search anchored inside the repository, and to the
  narrowest directory that answers the question.

---

## File Structure

**Modified:**

| Path | Change |
| --- | --- |
| `pyproject.toml` | delete `[tool.mutmut]`; add `mutants/` to `[tool.mypy] exclude` |
| `packages/stompdrill/pyproject.toml` | add `[tool.mutmut]` |
| `packages/stompmodel/pyproject.toml` | add a deselect to `[tool.mutmut]` |
| `CLAUDE.md` | the mutation commands; the survivor-worth-chasing list |
| `packages/stompmodel/tests/test_diagnostics.py` | one parametrised case |
| `packages/stompmodel/tests/test_codec.py` | two widened `match=` patterns |
| `packages/stompdrill/tests/test_quantise.py` | three assertions |
| `packages/stompdrill/tests/test_geometry.py` | parametrise one test over five angles |
| `packages/stompdrill/tests/test_pipeline.py` | two new message tests |
| `packages/stompdrill/tests/test_drawing_svg.py` | split one compound assertion |
| `packages/stompdrill/tests/test_excellon.py` | rebuild the shared fixture |
| `packages/stompdrill/tests/test_drawing_iso.py` | split two compound assertions |
| `packages/stompdrill/tests/test_snap.py` | split one compound assertion |
| `packages/stompdrill/tests/test_diameters.py` | split one compound assertion |
| `docs/adr/0001-pipeline-and-emitter-adapters.md` | emitter count, pipeline diagram |
| `docs/adr/0007-case-model-and-clearance.md` | status |

No production code is modified by this plan.

---

### Task 1: Make the mutation survey run

The root configuration produces nothing — not a poor survey, no survey. Until
this task lands, no claim about test quality in this repository is checkable.

**Files:**
- Modify: `pyproject.toml`
- Modify: `packages/stompdrill/pyproject.toml`
- Modify: `packages/stompmodel/pyproject.toml`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: two working commands — `cd packages/stompmodel && mutmut run` and
  `cd packages/stompdrill && mutmut run` — which every later task uses to prove
  a repair kills its mutant.

- [ ] **Step 1: Confirm the root survey is broken, so the fix is measured**

```bash
cd /Users/thelyx/repo/stompcad
PYTHONDONTWRITEBYTECODE=1 .venv/bin/mutmut run --max-children 4 2>&1 | tail -5
.venv/bin/mutmut results 2>&1 | tail -3
```

Expected: the run reports `Stopping early, because we could not find any test
case for any mutant`, or `mutmut results` shows every mutant as `not checked`.
Record which. This is the baseline the task removes.

The cause is in mutmut itself, at
`.venv/lib/python3.12/site-packages/mutmut/__main__.py:264`:

```python
def setup_source_paths() -> None:
    source_code_paths = [Path("."), Path("src"), Path("source")]
```

Only `mutants/.`, `mutants/src` and `mutants/source` are put on `sys.path`. From
the repository root the mutated sources land at
`mutants/packages/stompdrill/src/stompdrill`, which is none of those, so the
tests import the real unmutated package. From **inside** a member,
`src/<member>` maps to `mutants/src`, which is covered.

- [ ] **Step 2: Delete the root `[tool.mutmut]` table**

Remove the whole `[tool.mutmut]` block from `pyproject.toml` — the table and the
comments above `source_paths`, `also_copy` and `do_not_mutate`. Replace it with
a comment explaining why there is no root table, so the next reader does not add
one back:

```toml
# No [tool.mutmut] here. mutmut puts only mutants/., mutants/src and
# mutants/source on sys.path (setup_source_paths in its __main__), so from a
# workspace root the mutated sources at mutants/packages/<member>/src are never
# imported and the run scores nothing. The survey is per-member, run from inside
# the package, the same shape as pytest and mypy for the same kind of reason.
```

- [ ] **Step 3: Give `stompdrill` its own `[tool.mutmut]`**

Add to `packages/stompdrill/pyproject.toml`, after the existing
`[tool.pytest.ini_options]` table:

```toml
# Run from this directory: `cd packages/stompdrill && mutmut run`. src/stompdrill
# then maps to mutants/src, which is one of the three paths mutmut imports from.
[tool.mutmut]
source_paths = ["src/stompdrill"]
also_copy = ["tests/fixtures/"]
# enclosures.py is generated, and test_enclosures.py asserts that its *text on
# disk* is what tools/build_catalogue.py renders. Instrumenting it fails that
# test for every mutant, which aborts the whole run before any result is
# collected. Excluding it costs nothing: it is a literal catalogue table, so a
# mutant of it is either caught by the first assertion or meaningless.
do_not_mutate = ["src/stompdrill/enclosures.py"]
# Two tests read source text rather than behaviour, so mutmut's rewritten files
# fail them for every mutant and abort the survey. test_enclosures.py re-reads
# docs/parts/dimensions.tsv, which is outside the copied tree; the CLI test
# ast.parses cli.py, whose mutated form contains every mutant literal.
pytest_add_cli_args_test_selection = [
    "--deselect=tests/test_enclosures.py",
    "--deselect=tests/test_cli.py::test_cli_source_never_names_a_registered_format",
]
```

- [ ] **Step 4: Deselect the boundary gate in `stompmodel`**

`packages/stompmodel/tests/test_package_boundary.py` asserts every module
imports only the standard library or `stompmodel`. mutmut injects `import
mutmut` into every module it instruments, so the gate fails on all seven and the
stats phase — which runs with `-x` — kills the survey.

Add to the existing `[tool.mutmut]` table in
`packages/stompmodel/pyproject.toml`:

```toml
# mutmut injects `import mutmut` into every module it instruments, which the
# boundary gate rejects by design. Deselecting keeps the gate's assertion exact
# -- stdlib or this package, no third name -- and puts the exception where the
# anomaly is, next to do_not_mutate, rather than weakening the rule itself.
pytest_add_cli_args_test_selection = [
    "--deselect=tests/test_package_boundary.py::test_every_module_imports_only_the_standard_library_and_itself",
]
```

- [ ] **Step 5: Run the `stompmodel` survey**

```bash
cd /Users/thelyx/repo/stompcad/packages/stompmodel
PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run --max-children 4 2>&1 | tail -6
../../.venv/bin/mutmut results 2>&1 | tail -20
```

Expected: a real survey. The reference figure from the audit is **418 mutants,
407 killed, 10 survived, 1 uncovered**. Exact numbers may differ; what must be
true is that mutants are *scored* rather than reported `not checked`.

If it still aborts, read the failure before changing anything — a second
self-referential test may exist that the audit did not hit.

- [ ] **Step 6: Run the `stompdrill` survey**

```bash
cd /Users/thelyx/repo/stompcad/packages/stompdrill
PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run --max-children 4 \
  'stompdrill.geometry.*' 'stompdrill.pipeline.dedupe.*' \
  'stompdrill.quantise.*' 'stompdrill.units.*' 2>&1 | tail -6
../../.venv/bin/mutmut results 2>&1 | tail -30
```

Expected: a scored survey over those four modules. The audit's reference is
**328 mutants, 289 killed, 39 survived**. Record the surviving mutant names for
`quantise`, `geometry` and `dedupe` — Task 3 kills specific ones and needs their
identifiers.

- [ ] **Step 7: Stop a survey from breaking the type gate**

`mutmut run` leaves a `mutants/` directory. It is git-ignored but not
mypy-excluded, and it contains a second `tests` package, so `mypy packages`
then fails with `Duplicate module named "tests"`.

In the root `pyproject.toml`, extend `[tool.mypy] exclude`:

```toml
exclude = [
    "^packages/[^/]+/build/",
    "^packages/[^/]+/mutants/",
    "^packages/stompmodel/tests/",
]
```

Keep the existing comment above it and add one sentence naming the new entry's
reason — a survey must not break an unrelated gate.

- [ ] **Step 8: Prove the exclusion works**

```bash
cd /Users/thelyx/repo/stompcad
ls -d packages/stompmodel/mutants   # must exist from Step 5
.venv/bin/mypy packages
```

Expected: `Success`. Before Step 7 this same command fails. If `mutants/` was
cleaned up, re-run Step 5 first — the point is to prove the exclusion with the
directory present.

- [ ] **Step 9: Correct CLAUDE.md**

In `## Development commands`, replace the mutation block with the two per-member
commands:

```bash
# Mutation survey, per package -- there is no workspace-wide run
cd packages/stompmodel && PYTHONDONTWRITEBYTECODE=1 mutmut run && mutmut results
cd packages/stompdrill && PYTHONDONTWRITEBYTECODE=1 mutmut run && mutmut results
```

In `## Testing rules`, the survivor-worth-chasing list currently reaches
`stompmodel.units` only through the member run. Check what it says and make it
true: name which command reaches which modules, in one sentence.

- [ ] **Step 10: Run the full gates**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Expected: `1154 passed`, `238 passed`, clean, clean.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "Make the mutation survey runnable, per package

mutmut puts only mutants/., mutants/src and mutants/source on sys.path, so from
a workspace root the mutated sources at mutants/packages/<member>/src are never
imported and the run scores nothing at all. The root table is deleted rather
than repaired -- there is no value it could hold that would work -- and each
member carries its own, the same shape as pytest and mypy for the same reason.

Two kinds of test abort a survey by reading source text rather than behaviour:
the boundary gate rejects the import mutmut that instrumentation injects, and
two stompdrill tests parse files whose mutated form contains every mutant
literal. All three are deselected in the mutation config rather than weakened,
so each gate's assertion stays exact.

mypy gains a mutants/ exclusion: running the survey must not break the type
gate afterwards."
```

---

### Task 2: The two hollow tests in `stompmodel`

**Files:**
- Modify: `packages/stompmodel/tests/test_diagnostics.py`
- Modify: `packages/stompmodel/tests/test_codec.py:630,639`

**Interfaces:**
- Consumes: Task 1's `cd packages/stompmodel && mutmut run`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Prove the payload test is blind, by mutating**

`test_a_payload_key_ending_nm_must_hold_whole_nanometres` names "a payload key",
but every fixture payload has exactly one key, so the loop never reaches a
second and the `continue` that skips non-length keys is unpinned.

In `packages/stompmodel/src/stompmodel/diagnostics.py`, find
`_check_payload_lengths` and change its `continue` to `break`:

```python
    for key, value in items:
        if not key.endswith("_nm"):
            break        # was: continue
```

Then run:

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
```

Expected: **238 passed**. The mutation is invisible. **Revert it now** before
going on:

```bash
git checkout packages/stompmodel/src/stompmodel/diagnostics.py
```

- [ ] **Step 2: Add the case that sees the second key**

In `packages/stompmodel/tests/test_diagnostics.py`, add one case to the
`parametrize` list feeding
`test_a_payload_key_ending_nm_must_hold_whole_nanometres`, placing the length
key **second** so the loop must survive a non-length key to reach it:

```python
        pytest.param(
            lambda v: Diagnostic.warning(
                "off-grid",
                "hole 4 moved",
                # The length key is second on purpose: with only one key the
                # loop cannot distinguish skipping a non-length key from
                # stopping at it, and `continue -> break` goes unnoticed.
                data=(("stage", "ReviewGridTies"), ("moved_nm", v)),
            ),
            id="Diagnostic.data-with-a-non-length-key-first",
        ),
```

Match the surrounding cases' style — check whether they pass `build` as a lambda
of one argument and follow that exactly.

- [ ] **Step 3: Prove the new case kills the mutant**

Re-apply the `continue → break` mutation from Step 1, then:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_diagnostics.py -q
```

Expected: **FAIL** on the new case — `DID NOT RAISE TypeError`. Revert the
mutation and re-run; expected **239 passed** for the file's suite total to have
risen by one.

- [ ] **Step 4: Widen the two refusal patterns**

`packages/stompmodel/tests/test_codec.py` matches only the constant half of each
refusal message, so the half echoing the offending value is unpinned. Change:

```python
    with pytest.raises(DocumentError, match="not a stompcad-drill-data document"):
```

to:

```python
    with pytest.raises(DocumentError, match="not a stompcad-drill-data document: 'some-other-tool'"):
```

and:

```python
    with pytest.raises(DocumentError, match=f"expected {VERSION}"):
```

to:

```python
    with pytest.raises(DocumentError, match=f"version {VERSION + 1}, expected {VERSION}"):
```

Read `codec.py`'s actual message text first and match what it emits — if the
wording differs from the above, the message is right and the pattern follows it.
`pytest.raises(match=)` treats its argument as a regular expression, so escape
any `(`, `)` or `.` that appears literally.

- [ ] **Step 5: Prove both patterns bite**

In `codec.py`, drop the offending value from the first message — change the
f-string so it reports only the constant half — and run:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_codec.py -q
```

Expected: **FAIL**. Revert, repeat for the version message, revert again.

- [ ] **Step 6: Run the gates and the survey**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
cd packages/stompmodel && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run --max-children 4 2>&1 | tail -3
```

Expected: 239 passed; clean; and the survey's survivor count **lower than Task
1's baseline** by at least the mutants these repairs target. Record both numbers.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Make three stompmodel assertions capable of failing

The payload guard's test named 'a payload key' while every fixture carried
exactly one, so the loop never reached a second and continue -> break was
invisible. One case with the length key second closes it.

The two refusal tests matched only the constant half of their message, leaving
the half that echoes the offending value unpinned -- so a reader that refused a
document without saying which one passed both."
```

---

### Task 3: The four hollow tests in `stompdrill`

**Files:**
- Modify: `packages/stompdrill/tests/test_quantise.py:186`
- Modify: `packages/stompdrill/tests/test_geometry.py:340`
- Modify: `packages/stompdrill/tests/test_pipeline.py`
- Modify: `packages/stompdrill/tests/test_drawing_svg.py:1096`

**Interfaces:**
- Consumes: Task 1's `cd packages/stompdrill && mutmut run`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Inspect what the enclosure-error test ignores**

`test_every_enclosure_error_stops_the_run` is the only test of the
enclosure-error return, and it never looks at the returned data. Six mutants
live in the keyword arguments it ignores.

Read the function around `packages/stompdrill/tests/test_quantise.py:186` and
find what `phase(...)` returns and what the assertions after the call check.
Then read `quantise.py`'s enclosure-error return to see which fields it sets.

- [ ] **Step 2: Assert what the returned data carries**

`phase(...)` returns the `DrillData` directly — the existing assertions read
`out.holes` and `out.worst_severity`. Bind the raw value first so provenance can
be compared against its own source rather than a literal:

```python
    raw = read(
        RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0)),
        RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0)),
        reference=reference,
    )

    out = phase(
        raw,
        enclosure=watched.enclosure(declared, tolerance_nm),
        diameters=watched.diameters(),
        positions=watched.positions(),
    )
```

Then add three assertions after the existing four:

```python
    # The name promises the run stops; these say what it stops *with*. Without
    # them the keyword arguments on the error return are unpinned, and a run
    # that halted while discarding its provenance would pass.
    assert out.source == raw.source
    assert out.enclosure is None
    assert (out.reference is None) == (reference is None)
```

The third is written as a round trip rather than a literal because one of the
four parameter sets supplies `reference=None`, and an assertion that hard-coded
an outline would be wrong for it. If `enclosure` turns out to be populated on
some paths, make that one per-parameter too rather than weakening it.

- [ ] **Step 3: Prove the assertions kill a mutant**

In `quantise.py`'s enclosure-error return, drop one keyword argument — set
`reference=None` where it passed the real outline — and run:

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_quantise.py -q
```

Expected: **FAIL**. Revert. Repeat for a second argument to confirm more than one
is now covered.

- [ ] **Step 4: Parametrise the rotation test over angles that change sign**

`test_recovers_a_circle_under_rotation` uses one angle, 37°, chosen where every
sign in the anchor arithmetic stays positive. Six mutations of the travel
derivation survive it, one raising `ZeroDivisionError` at 90°.

Replace the test at `packages/stompdrill/tests/test_geometry.py:340` with:

```python
    @pytest.mark.parametrize("degrees", [37.0, 60.0, 90.0, 105.0, 300.0])
    def test_recovers_a_circle_under_rotation(self, degrees: float) -> None:
        """A rotated circle is still a circle, at every angle.

        Fitting from the *axis-aligned* bounding box would report a diameter of
        2r*cos(45 deg) here. Anchor radii are rotation invariant, so they don't.
        One angle is not a test of rotation: 37 deg keeps every sign in the
        anchor arithmetic positive, and 90 deg is where a sign-dependent
        derivation divides by zero.
        """
        ctm = rotation(degrees)
        found = fit_circle(mapped(circle_path(10.0, -5.0, 2.5), ctm))
        assert found is not None
        assert (found.cx, found.cy) == pytest.approx(transform(ctm, 10.0, -5.0), abs=PT_SLACK)
        assert found.diameter == pytest.approx(5.0, abs=PT_SLACK)
```

The centre `(10.0, -5.0)` already has a negative Y, so no further offset is
needed; confirm that by reading `circle_path` and `rotation` before deciding.

- [ ] **Step 5: Prove the new angles kill what 37° missed**

Run the test as it now stands:

```bash
.venv/bin/python -m pytest -o addopts= "packages/stompdrill/tests/test_geometry.py::TestFitCircle::test_recovers_a_circle_under_rotation" -v
```

Expected: five cases, all passing. Then apply a sign mutation in `geometry.py`'s
travel derivation — flip one subtraction to an addition — and re-run. Expected:
the 37° case may pass while at least one other **fails**. That asymmetry is the
whole point of the change; record which angles caught it. Revert.

- [ ] **Step 6: Test the duplicate-hole message, which has no test at all**

`pipeline/dedupe.py:47` builds the singular and plural forms of the
`duplicate-hole` message, and nothing asserts either. Six mutants survive,
including a straight inversion of the plural condition.

Add to `packages/stompdrill/tests/test_pipeline.py`, beside the other
`Deduplicate` tests:

```python
def test_a_collapsed_pair_reports_one_hole_dropped() -> None:
    """Singular and plural are separate assertions because one mutation of the
    plural condition satisfies whichever form the other case does not."""
    data = make_data(at(0, 0, 5_000_000), at(0, 0, 5_000_000))

    finding = Deduplicate().apply(data).diagnostics[0]

    assert finding.code == "duplicate-hole"
    assert "1 hole dropped" in finding.message


def test_a_collapsed_triple_reports_two_holes_dropped() -> None:
    """The plural side of the same message."""
    data = make_data(at(0, 0, 5_000_000), at(0, 0, 5_000_000), at(0, 0, 5_000_000))

    finding = Deduplicate().apply(data).diagnostics[0]

    assert finding.code == "duplicate-hole"
    assert "2 holes dropped" in finding.message
```

`at(x_nm, y_nm, diameter_nm=7_000_000, *, index=None)` and
`make_data(*holes, reference=None)` both come from `tests.conftest`; check the
file's existing imports and add whichever it lacks. Nanometres are written as
integer literals throughout this suite, which is why no unit constant appears.

- [ ] **Step 7: Prove both message tests bite**

In `dedupe.py`, invert the plural condition:

```python
        plural = "s" if len(dropped) == 1 else ""    # was: "" if ... else "s"
```

Run:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_pipeline.py -q
```

Expected: **both new tests fail**. Revert and re-run; expected clean.

- [ ] **Step 8: Split the compound quantity assertion**

`packages/stompdrill/tests/test_drawing_svg.py:1096` reads:

```python
    assert "2" in summary[0] and "5" in summary[1]  # quantities, ascending by size
```

Both clauses are already satisfied by the diameter text asserted one line above
(`"5.00" in joined`), so neither can fail while the row renders. The next test
pins the quantities properly. Replace the line with two assertions that name
what they check:

```python
    assert "QTY 2" in summary[0], "first tool's quantity, ascending by size"
    assert "QTY 5" in summary[1], "second tool's quantity"
```

Read the emitted summary text first — if the rendered form is not `QTY 2`, use
whatever it is, and if the quantities are genuinely indistinguishable from the
diameters in that string, delete the line instead and say so in the commit.

- [ ] **Step 9: Run the gates and the survey**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
cd packages/stompdrill && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run --max-children 4 \
  'stompdrill.geometry.*' 'stompdrill.pipeline.dedupe.*' 'stompdrill.quantise.*' 2>&1 | tail -3
```

Expected: the suite green with its count risen by seven (five parametrised
rotation cases replacing one, plus two message tests); clean; and the survivor
count **lower** than Task 1's baseline. Record both.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Make four stompdrill tests capable of failing

The enclosure-error test named the run stopping and never looked at what it
stopped with, leaving six mutants alive in the four keyword arguments it
ignored. The rotation test used one angle chosen where every sign stays
positive, so six travel-derivation mutants survived it -- one of which divides
by zero at ninety degrees, an angle the test never tried. The duplicate-hole
message had no test at all. And the schedule's quantity assertion compounded two
clauses that were both already satisfied by the diameter text asserted above it."
```

---

### Task 4: The fixture that opts out, and four compound conditions

**Files:**
- Modify: `packages/stompdrill/tests/test_excellon.py:25`
- Modify: `packages/stompdrill/tests/test_drawing_iso.py:205,421`
- Modify: `packages/stompdrill/tests/test_snap.py:72`
- Modify: `packages/stompdrill/tests/test_diameters.py:205`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Understand the rule the fixture breaks**

CLAUDE.md requires routed holes to be numbered out of tuple order, so that a
test only passes an emitter reading the number through `DrillData.numbered()`
rather than recomputing it from list position. `tests/conftest.py` encodes this:
`holes()` numbers sequentially from 1 and its docstring redirects to `at()` for
anything that reads a number.

`test_excellon.py`'s principal fixture uses `holes()`, so every assertion driven
by it is blind to that difference. The rest of the file is disciplined — 38
explicit `index=` sites — which is what makes this one load-bearing.

- [ ] **Step 2: Rebuild the fixture with scrambled numbers**

Replace the `holes(...)` call in `fixture_data()` with explicit `at()` calls
carrying out-of-order indices. Keep every coordinate and diameter exactly as it
is; only the numbering changes:

```python
        holes=(
            at(-40_000_000, 18_000_000, index=4),
            at(-20_000_000, 18_000_000, index=7),
            at(0, 18_000_000, index=1),
            at(20_000_000, 18_000_000, index=6),
            at(40_000_000, 18_000_000, index=2),
            at(-19_000_000, -18_750_000, 5_000_000, index=5),
            at(19_000_000, -18_750_000, 5_000_000, index=3),
        ),
```

`at(x_nm, y_nm, diameter_nm=7_000_000, *, index=None)` defaults the diameter to
7 mm, which is what the first five holes took implicitly from `holes()`, so only
the last two need theirs spelled. Add `at` to the file's imports from
`tests.conftest` if it is not already there.

- [ ] **Step 3: Run the Excellon suite and read the failures carefully**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_excellon.py -q
```

Some tests will now fail, and **each failure is information**. A test that
expected drill order `1..7` and now sees `1,2,3,4,5,6,7` in a different sequence
was reading position, not number — fix the expectation to the routed order. A
test that fails because the *output* changed order is telling you the emitter
sorts by number, which is correct.

Do not restore the old fixture to make failures go away. If a failure cannot be
explained, stop and report it — that is a real finding about the emitter.

- [ ] **Step 4: Prove the fixture now discriminates**

Add one test to `test_excellon.py`, modelled on the gold standard at
`test_drawing_svg.py:423`:

```python
def test_the_drill_order_is_the_routed_order_not_the_tuple_order() -> None:
    """The fixture is only worth having if these two differ.

    Without the second assertion an emitter that enumerated the tuple would pass
    every test in this file, which is what it did before the fixture carried
    explicit numbers.
    """
    data = fixture_data()
    numbers = [n for n, _ in data.numbered()]

    assert numbers == sorted(numbers)
    assert numbers != [h.index for h in data.holes]
```

- [ ] **Step 5: Split the four compound conditions**

Each is one assertion where a mutation need only spare one clause. CLAUDE.md
requires each clause checked independently. At each site, split into one
assertion per clause with a message naming it. For example, at
`test_drawing_iso.py:421`:

```python
    assert left, "left margin"
    assert right, "right margin"
    assert top, "top margin"
    assert bottom, "bottom margin"
```

Do the same at `test_drawing_iso.py:205`, `test_snap.py:72-73` (a type check and
a modulo check compounded across two lines — these are two distinct claims) and
`test_diameters.py:205`. Read each site and name each clause for what it
actually asserts; the messages above are the shape, not the text.

- [ ] **Step 6: Run the gates**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
```

Expected: green, with the count risen by one for the new discrimination test
plus however many the splits added.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Make the Excellon fixture discriminate, and split four compounds

test_excellon.py's shared fixture numbered its seven holes 1..7 in tuple order,
so every assertion driven by it was blind to the difference between reading
DrillData.numbered() and enumerating the list -- in the one file that otherwise
holds the rule at 38 explicit sites. It now carries scrambled numbers and a test
that proves the two orders differ, so the fixture is known to be discriminating
rather than assumed to be.

Four compound assertions are split one clause per line: each was a single
statement where a mutation need only spare one half to survive."
```

---

### Task 5: Correct two ADRs

**Files:**
- Modify: `docs/adr/0001-pipeline-and-emitter-adapters.md:33,68` and its pipeline diagram
- Modify: `docs/adr/0007-case-model-and-clearance.md:3-6`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Count the emitters, then correct the count**

```bash
cd /Users/thelyx/repo/stompcad
grep -rn "@register_emitter" packages/stompdrill/src/stompdrill/emitters/
```

Expected: five. `docs/adr/0001-pipeline-and-emitter-adapters.md:33` says an
invocation selects "one to four emitters", and its Mermaid diagram at line 68
repeats it inside a node label. Correct both to the counted number.

- [ ] **Step 2: Add the fourth stage to the pipeline diagram**

The same ADR's diagram shows three stages — `Deduplicate`, `ReviewGridTies`,
`RouteHoles` (lines 57-59). `CheckCaseClearance` is a fourth, appended by
`cli.build_pipeline` when a case model is supplied.

Add it to the diagram, marked as conditional so the diagram stays true for a run
without `--case-model`. Follow the file's existing Mermaid style; do not
restructure the diagram.

- [ ] **Step 3: Make ADR-0007's status match ADR-0009**

`docs/adr/0007-case-model-and-clearance.md:3-6` states the `stompdrill[step]`
extra "is retired by ADR-0009". ADR-0009 now says it is retired **when
`stompgeom` lands**, and the extra is still declared in
`packages/stompdrill/pyproject.toml` and still documented in CLAUDE.md.

Correct ADR-0007's status to say the retirement is pending on `stompgeom`,
matching the wording ADR-0009 uses. Change the tense only — the reasoning about
why the extra existed is history and stays exactly as written.

- [ ] **Step 4: Verify no other ADR asserts something now false**

```bash
grep -rn "one to four\|is retired\|three stages" docs/adr/
```

Expected: no remaining hits that state a current fact contradicted by the code.
A sentence narrating what an ADR's own decision changed is history — leave it.

- [ ] **Step 5: Run the documentation audit and commit**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_documentation.py -q
git add -A
git commit -m "Make two ADRs state what is true

ADR-0001 counted four emitters where there are five, in prose and again inside
its diagram, and drew a three-stage pipeline when CheckCaseClearance is a fourth
whenever a case model is supplied.

ADR-0007's status said the step extra is retired. ADR-0009 makes that contingent
on stompgeom landing, and the extra is still declared and still documented, so
the status now says pending. Only the tense changes: why the extra existed is
history and stands."
```

---

## Verification Summary

Every task ends with the same gates:

| Gate | Command | Expected |
| --- | --- | --- |
| `stompdrill` suite | `pytest --hammond packages/stompdrill/tests` | green, count never falls |
| `stompmodel` suite | `pytest packages/stompmodel/tests` | green, count never falls |
| Lint and types | `ruff check packages tools`; `mypy packages` | clean |
| Survey runs | `cd packages/<member> && mutmut run` | mutants scored, not `not checked` |

And one gate specific to this plan, which is the reason it exists:

**A repair is not done until its mutant has been applied, seen to fail the
test, and reverted.** Every task above names the mutation to apply. A repair
committed without that evidence is a test that might be as hollow as the one it
replaced.
