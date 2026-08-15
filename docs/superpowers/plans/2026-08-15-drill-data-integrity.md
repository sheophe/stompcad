# aidrill Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 22 findings from the four-lens review of 2026-08-14, restoring the invariant that no emitter output can contain two tools of equal diameter and that diagnostics keep a stable referent to the holes they describe.

**Architecture:** Two contract changes land first and sequentially, because most other work consumes them: `Hole` gains a required deterministic identity, and `DrillData` gains stage provenance via a new `Stage.describe()`. Everything after that is partitioned by file ownership so tasks can run in parallel without edit conflicts.

**Tech Stack:** Python 3.10+, pikepdf 9, pytest, stdlib `xml.etree.ElementTree`. No new runtime dependencies.

**Spec:** `docs/SPEC.md` (v1.0), `docs/adr/0001-pipeline-and-emitter-adapters.md`. Both are stale in six places identified in Task 14 — read the divergence table there before trusting the spec on clustering, circle fitting, or the `Emitter` protocol.

## Global Constraints

- Python floor is `>=3.10`. `X | Y` annotations, `slots=True` dataclasses. No `match` statements.
- Millimetres internally, always. Inch conversion happens inside an emitter only.
- Emitters may translate frames and convert units. They may **never** round positions, cluster diameters, drop duplicates, sort, or renumber. This is the founding rule of ADR-0001.
- No stage may assert which stage ran before it (LSP). Stage order is chosen by `cli.py`.
- Diagnostics are matched on `code`, never on `message` — in source and in tests.
- House style: module docstrings explain *why* and name the bug that motivated the design. British spelling in prose (`centre`, `millimetre`, `normalisation`, `colour`), American in identifiers. `from __future__ import annotations` and an explicit `__all__` in every module.
- Test command: `PYTHONPATH=src /private/tmp/claude-501/-Users-thelyx-repo-aidrill/8f58794d-c2a3-4c5c-bc2f-57252cb8eac7/scratchpad/aidrill-env/bin/python -m pytest -p no:cacheprovider -q`
- Baseline before any change: **359 tests passing, 98% coverage**. No task may reduce the passing count except by deliberately replacing a test, which must be stated in the commit message.
- TDD throughout. Write the failing test, run it, watch it fail for the right reason, then implement. If a test cannot go green until a later task lands, **leave it failing** and mark it `@pytest.mark.xfail(strict=True, reason="awaits Task N")`. Do not write a dummy assertion or hack the implementation to fake green.

---

## Design decisions settled before planning

These were put to a second reviewer (Codex, `gpt-5.6-sol`) and settled. Do not relitigate them mid-task.

1. **The Excellon tool collision is an emitter representability failure, not a normalisation failure.** It depends on `units` and `decimals`, which are emitter-specific, so no universal stage can diagnose it truthfully. The emitter checks injectivity of its own rendered tokens and refuses. **No upstream warning** — it would be false when emitting only JSON/SVG and insufficient when emitting Excellon.
2. **Hole identity is a required field with no default.** A shared default (`0`/`None`) reintroduces exactly the ambiguity it is meant to remove. `RawHole` cannot serve as the key because equal raw geometry is valid and especially likely for duplicates — which is the case the feature exists for.
3. **Stage provenance is a generic typed record**, not per-stage record classes (which would create a closed registry and undermine stage extensibility) and not `(name, repr)` strings (the drawing needs the grid numerically).
4. **Provenance does not fix `_OPTION_BUILDERS`.** Processing parameters belong in `DrillData`; presentation/encoding parameters belong to the emitter. The ADR's "one module plus one import" claim is true only for emitters that take no options. Task 15 amends the ADR honestly rather than pretending otherwise.
5. **Out of scope, deliberately:** deleting `Pipeline.then()` or `Emitter.extension` (tiny, harmless, reasonable registry metadata); splitting `drawing_svg.py` into a package (a refactoring candidate, not a defect — do it when a concrete boundary reduces real change friction); deleting the ERROR severity tier or manufacturing an ERROR to make exit code 2 reachable (a third-party stage can already produce one; the model contract is broader than today's CLI path).

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/aidrill/model.py` | Adds `Hole.index`, `StageRun`, `DrillData.processing`; fixes `Severity` ordering and `rows()` determinism | 1, 2, 10 |
| `src/aidrill/protocols.py` | Adds `Stage.describe()`; `Pipeline.run` collects provenance | 2 |
| `src/aidrill/pipeline/*.py` | Each stage implements `describe()`; dedupe carries hole ids; diameters mean fix; validate code split | 2, 3, 8 |
| `src/aidrill/sources/ai_pdf.py` | Assigns hole ids; clip-and-paint fix; EMC balance | 1, 6 |
| `src/aidrill/geometry.py` | κ tangential-direction check | 6 |
| `src/aidrill/emitters/excellon.py` | Token injectivity guard; lower-left positivity check | 5 |
| `src/aidrill/emitters/json_out.py` | Serialises `index`, `Diagnostic.data`, `processing`; version bump | 3 |
| `src/aidrill/emitters/drawing_svg.py` | Matches duplicates by id; reads grid from provenance; dimension clamp; XML control chars | 4, 7 |
| `src/aidrill/cli.py` | Drops `grid` from `OutputSettings`; finite validation; merged except blocks | 2, 9 |
| `src/aidrill/errors.py` | House-style docstring, `__all__`, annotations; `EmptyLayerError` reason arg | 9 |
| `tests/conftest.py` | **Create** — shared `clean_registry`, `at()`, `make_data()`, hole-id helpers | 1, 12 |
| `pyproject.toml` | ruff/mypy config, dev dependency group | 13 |
| `docs/SPEC.md`, `docs/adr/0002-*.md` | Spec sync; follow-up ADR for the model change | 14, 15 |

---

## Execution order and parallelism

```
Task 1 (hole identity)  ──►  Task 2 (provenance)  ──►  Task 3 (json)  ──►  Task 4 (drawing consumes both)
        │                            │
        └────────────────────────────┴──►  Tasks 5,6,7,8,9,10 run in PARALLEL after Task 2
                                                        │
                                                        └──►  Tasks 11,12,13 (verification, tests, tooling)
                                                                        │
                                                                        └──►  Tasks 14,15 (docs)
```

Tasks 5–10 own disjoint file sets and must be dispatched together. Tasks 1–4 are strictly sequential.

---

### Task 1: Give `Hole` a required, deterministic identity

Fixes finding 02 (duplicate highlighting lost on stage reorder). This is the root-cause fix: a diagnostic currently points at a hole using coordinates a later stage may change.

**Files:**
- Modify: `src/aidrill/model.py:82-108` (`Hole`)
- Modify: `src/aidrill/sources/ai_pdf.py:185`
- Modify: `src/aidrill/pipeline/dedupe.py:55-77` (`_report`)
- Create: `tests/conftest.py`
- Modify: `tests/test_pipeline.py:41-51`, `tests/test_excellon.py:40-50`, `tests/test_cli.py:45`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Hole.index: int` — required field, no default, positioned **after** `raw` so positional construction of the existing four fields still reads naturally.
  - `Hole.from_measurement(cls, x: float, y: float, diameter: float, index: int) -> Hole` — `index` required.
  - `Diagnostic` payload key `"hole_index"` on `duplicate-hole`, carrying the survivor's `index`.
  - `tests/conftest.py::at(x, y, diameter=7.0, *, index)` and `tests/conftest.py::holes(*specs)` which enumerates indices from 0.

- [ ] **Step 1: Write the failing test**

In `tests/test_pipeline.py`:

```python
def test_duplicate_diagnostic_identifies_the_survivor_by_index_not_position():
    """The referent must survive a later coordinate change.

    protocols.py forbids a stage assuming its predecessor, so Deduplicate may
    legitimately run before SnapPositions. When it does, the survivor moves
    after the diagnostic is written and a position-keyed referent goes stale.
    """
    data = make_data(
        Hole.from_measurement(10.03, 5.02, 7.0, index=0),
        Hole.from_measurement(10.04, 5.02, 7.0, index=1),
    )
    after = Pipeline([Deduplicate(tolerance=0.05), SnapPositions(grid=0.25)]).run(data)

    duplicates = [d for d in after.diagnostics if d.code == "duplicate-hole"]
    assert len(duplicates) == 1
    survivor_index = duplicates[0].get("hole_index")
    assert survivor_index is not None
    assert [h.index for h in after.holes] == [survivor_index]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src <env>/bin/python -m pytest tests/test_pipeline.py::test_duplicate_diagnostic_identifies_the_survivor_by_index_not_position -v`
Expected: FAIL — `TypeError: from_measurement() got an unexpected keyword argument 'index'`

- [ ] **Step 3: Add the field**

In `src/aidrill/model.py`, add to `Hole` after `raw`:

```python
    index: int
```

and update the constructor and docstring:

```python
    @classmethod
    def from_measurement(cls, x: float, y: float, diameter: float, index: int) -> "Hole":
        """Build a hole whose nominal values are still its measured values.

        ``index`` is the hole's stable identity, assigned once by the source in
        traversal order and preserved by every transform. It exists because a
        diagnostic needs a referent that survives later stages: keying on
        position went stale the moment a stage moved the hole, and keying on
        ``raw`` cannot work because two coincident circles — precisely the
        duplicate case — share identical raw geometry.
        """
        return cls(x=x, y=y, diameter=diameter, raw=RawHole(x, y, diameter), index=index)
```

`moved_to`, `with_diameter` and `translated` already use `replace()`, so they preserve `index` with no change.

- [ ] **Step 4: Assign ids at the source**

In `src/aidrill/sources/ai_pdf.py:185`, enumerate the fitted circles in traversal order and pass `index=i`. Traversal order is deterministic for a given file, which is what makes the id reproducible across runs.

- [ ] **Step 5: Carry the id in the dedupe payload**

In `src/aidrill/pipeline/dedupe.py`, add `("hole_index", survivor.index)` to the `data` tuple in `_report`. Keep `location` — it remains useful human context in the CLI report and the drawing's NOTES, it is simply no longer the foreign key.

- [ ] **Step 6: Create `tests/conftest.py` and migrate the helpers**

```python
"""Shared test helpers.

``clean_registry`` and the hole builders were defined identically in two and
three files respectively, and the ``at()`` copies had already drifted apart.
"""

from __future__ import annotations

import pytest

from aidrill.emitters import base
from aidrill.model import DrillData, Hole, ReferenceOutline


@pytest.fixture
def clean_registry():
    saved = dict(base.REGISTRY)
    try:
        yield base.REGISTRY
    finally:
        base.REGISTRY.clear()
        base.REGISTRY.update(saved)


def at(x: float, y: float, diameter: float = 7.0, *, index: int) -> Hole:
    """One hole with an explicit identity. ``index`` is keyword-only so a test
    can never pass it by accident where ``diameter`` was meant."""
    return Hole.from_measurement(x, y, diameter, index=index)


def holes(*specs: tuple[float, ...]) -> tuple[Hole, ...]:
    """Build holes from ``(x, y[, diameter])`` triples, numbering them 0..n-1.

    Sequential numbering here is deterministic per call — no module-level
    counter, so a test's hole ids do not depend on which tests ran before it.
    """
    return tuple(
        Hole.from_measurement(s[0], s[1], s[2] if len(s) > 2 else 7.0, index=i)
        for i, s in enumerate(specs)
    )
```

Delete the duplicate `clean_registry` from `tests/test_emitter_registry.py` and `tests/test_cli.py`, and the local `at`/`make_data` from `tests/test_pipeline.py` and `tests/test_excellon.py`, importing from `conftest` instead. Update all 38 construction sites.

- [ ] **Step 7: Run the full suite**

Run the full test command.
Expected: all tests pass, count ≥ 359. The new test passes.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: give Hole a required stable identity

Diagnostics referred to holes by their current coordinates, which went
stale whenever a stage moved the hole afterwards. Proven: under
Pipeline([Deduplicate, SnapPositions]) the drawing highlighted zero
duplicate holes while the pipeline had correctly found one.

Adds Hole.index, assigned in source traversal order and preserved by
every transform, and carries it in the duplicate-hole payload."
```

---

### Task 2: Record stage provenance on `DrillData`

Fixes finding 08 (the drawing stamps a grid the data was never snapped to). Depends on Task 1 only for merge order, not semantically.

**Files:**
- Modify: `src/aidrill/model.py` (add `StageRun`, `DrillData.processing`)
- Modify: `src/aidrill/protocols.py:24-35` (`Stage`), `:78-81` (`Pipeline.run`)
- Modify: all five of `src/aidrill/pipeline/*.py`
- Modify: `src/aidrill/cli.py:301-315` (`run_pipeline`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1's `Hole.index` (only via the shared test helpers).
- Produces:
  - `StageRun(name: str, parameters: tuple[tuple[str, float | int | str | bool], ...])`, frozen+slots, with `get(key, default=None)` mirroring `Diagnostic.get`.
  - `DrillData.processing: tuple[StageRun, ...]`, default `()`.
  - `DrillData.with_processing(*runs: StageRun) -> DrillData`.
  - `DrillData.last_run(stage_name: str) -> StageRun | None`.
  - `Stage.describe(self) -> StageRun` on the protocol; implemented by all five stages.
  - `Pipeline.run` appends each stage's `describe()` after that stage applies successfully.

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_records_what_each_stage_actually_did():
    data = make_data(*holes((10.03, 5.02), (-20.0, 5.0, 5.0)))
    after = Pipeline([SnapPositions(grid=0.5), Deduplicate(tolerance=0.05)]).run(data)

    assert [r.name for r in after.processing] == ["snap-positions", "deduplicate"]
    snap = after.last_run("snap-positions")
    assert snap.get("grid_mm") == 0.5
    assert snap.get("warn_over_mm") == 0.125   # the *resolved* default, not None


def test_describe_reports_resolved_defaults_not_raw_arguments():
    """warn_over defaults to grid/4; provenance must record the effective value."""
    assert SnapPositions(grid=0.25).describe().get("warn_over_mm") == 0.0625
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `AttributeError: 'DrillData' object has no attribute 'processing'`

- [ ] **Step 3: Add `StageRun` and the `DrillData` field**

In `model.py`, mirroring `Diagnostic`'s payload shape so there is one idiom for typed key/value provenance in this codebase, not two.

- [ ] **Step 4: Widen the `Stage` protocol**

```python
    def describe(self) -> "StageRun":
        """Report what this stage was configured to do, with *effective* values.

        The drawing's title block must state the grid the holes were actually
        snapped to. Threading that through the emitter's options instead meant a
        library consumer could emit a sheet stamped 0.25 for data snapped at 0.5.
        """
```

- [ ] **Step 5: Implement `describe()` on all five stages**

Each returns effective values, with units in the parameter names:
- `SnapPositions` → `grid_mm`, `warn_over_mm` (resolved), `enabled` (False when `grid <= 0`)
- `NormalizeDiameters` → `strategy`, plus the strategy's `tolerance` and, for `TableDiameters`, its `sizes` as a tuple
- `Deduplicate` → `tolerance_mm`
- `CheckReferenceSize` → `expected_width_mm`, `expected_height_mm`, `tolerance_mm`
- `SortHoles` → `key` (the key function's name, or `"default"`)

- [ ] **Step 6: Collect in `Pipeline.run`**

```python
    def run(self, data: DrillData) -> DrillData:
        for stage in self._stages:
            data = stage.apply(data).with_processing(stage.describe())
        return data
```

Then make `cli.run_pipeline`'s verbose path fold through the same `Pipeline.run` rather than maintaining its own duplicate loop — one fold, so the traced path and the normal path cannot diverge.

- [ ] **Step 7: Run full suite; Step 8: Commit**

```bash
git commit -m "feat: record stage provenance on DrillData

Adds StageRun and Stage.describe(), collected by Pipeline.run. The
drawing can now state the grid the holes were actually snapped to
rather than being told a second copy through its own options."
```

---

### Task 3: Serialise identity, payloads and provenance in JSON

Fixes finding 07. The JSON emitter is the declared integration contract and currently drops `Diagnostic.data` — precisely the payload ADR-0001 describes as the fix for the original sin.

**Files:**
- Modify: `src/aidrill/emitters/json_out.py:110-130`
- Test: `tests/test_json_emitter.py`

**Interfaces:**
- Consumes: `Hole.index` (Task 1), `StageRun` / `DrillData.processing` (Task 2).
- Produces: JSON document `version` bumped `1 → 2`; hole objects gain `"index"`; diagnostic objects gain `"data"` as an object; document gains a top-level `"processing"` array of `{"name":…, "parameters":{…}}`.

- [ ] **Step 1: Write the failing test**

```python
def test_diagnostic_payloads_survive_serialisation():
    """The duplicate's payload is the whole point of Diagnostic.data.

    Without it a JSON consumer must re-derive which holes were duplicates from
    positions alone — the exact defect ADR-0001 exists to eliminate, displaced
    one layer out into the toolchain.
    """
    data = make_data(*holes((0.0, 0.0), (0.01, 0.0)))
    after = Pipeline([Deduplicate(tolerance=0.05)]).run(data)
    doc = json.loads(JsonEmitter().emit(after))

    assert doc["version"] == 2
    duplicate = next(d for d in doc["diagnostics"] if d["code"] == "duplicate-hole")
    assert duplicate["data"]["dropped"] == 1
    assert duplicate["data"]["hole_index"] == doc["holes"][0]["index"]
```

- [ ] **Step 2: Run to verify it fails.** Expected: `KeyError: 'data'`.
- [ ] **Step 3: Implement** `_diagnostic` to emit `data` as an object, `_hole` to include `index`, and add `processing` to the document. Bump `VERSION` to 2.
- [ ] **Step 4: Update the round-trip test** at `tests/test_json_emitter.py:218-253` so its fixture diagnostics carry a non-empty payload — it currently passes only because they are empty.
- [ ] **Step 5: Run full suite; Step 6: Commit.**

---

### Task 4: Make the drawing consume identity and provenance

Fixes findings 02 (consumer half) and 08 (consumer half).

**Files:**
- Modify: `src/aidrill/emitters/drawing_svg.py:1060-1088` (`_flagged_holes`, `_is_flagged`), `:104-114` (`DrawingOptions`), `:890` (title block)
- Modify: `src/aidrill/cli.py:245-267` (`OutputSettings`, `_OPTION_BUILDERS`)
- Test: `tests/test_drawing_svg.py`

**Interfaces:**
- Consumes: `Diagnostic.get("hole_index")` (Task 1), `DrillData.last_run("snap-positions")` (Task 2).
- Produces: `DrawingOptions` **loses** its `grid` field. `OutputSettings` loses `grid`. `_OPTION_BUILDERS`'s `DrawingOptions` entry drops `grid=...`.

- [ ] **Step 1: Write the failing tests**

```python
def test_duplicates_are_highlighted_whatever_order_the_pipeline_ran_in():
    data = make_data(*holes((10.03, 5.02), (10.04, 5.02)))
    for pipeline in (
        Pipeline([SnapPositions(grid=0.25), Deduplicate(tolerance=0.05)]),
        Pipeline([Deduplicate(tolerance=0.05), SnapPositions(grid=0.25)]),
    ):
        after = pipeline.run(data)
        root = ET.fromstring(DrawingSvgEmitter().emit(after))
        flagged = [e for e in root.iter() if RED in (e.get("stroke") or "")]
        assert flagged, f"no duplicate ring for {pipeline!r}"


def test_the_title_block_states_the_grid_the_holes_were_actually_snapped_to():
    data = make_data(*holes((10.03, 5.02)))
    after = Pipeline([SnapPositions(grid=0.5)]).run(data)
    assert "0.5" in _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(after)))


def test_the_title_block_does_not_invent_a_grid_when_none_was_recorded():
    """A hand-built DrillData never went through a pipeline. Saying 0.25 would be a lie."""
    text = _title_block_text(ET.fromstring(DrawingSvgEmitter().emit(make_data(*holes((0.0, 0.0))))))
    assert "0.25" not in text
    assert "NOT RECORDED" in text or "GRID" not in text
```

- [ ] **Step 2: Run to verify all three fail.** The first fails only for the second ordering — confirm that, since a test that fails for both orderings means the helper is wrong, not the code.
- [ ] **Step 3: Rewrite `_flagged_holes`/`_is_flagged`** to collect `d.get("hole_index")` into a `frozenset[int]` and match `hole.index in flagged`. Update the docstring: identity is now explicit, so the essay about exact float matching should be replaced with one sentence about why the id exists.
- [ ] **Step 4: Read the grid from provenance.** `grid > 0` → print the recorded value; `grid == 0` → `GRID OFF`; no provenance → `GRID NOT RECORDED`. Never fall back to a literal.
- [ ] **Step 5: Delete `DrawingOptions.grid` and `OutputSettings.grid`.**
- [ ] **Step 6: Run full suite; Step 7: Commit.**

---

### Task 5: Refuse to emit an Excellon file with a non-injective tool table

Fixes findings 01 (High) and 14. **Owns `src/aidrill/emitters/excellon.py` and `tests/test_excellon.py` exclusively.**

**Files:**
- Modify: `src/aidrill/emitters/excellon.py:83-135`
- Test: `tests/test_excellon.py`

**Interfaces:**
- Consumes: `DrillData.tools()`.
- Produces: no new public API. `emit` raises `EmitterError` on token collision and on a negative reframed coordinate.

- [ ] **Step 1: Write the failing tests**

```python
def test_two_nominals_that_render_to_the_same_token_are_refused():
    """SPEC 7: one tool per nominal diameter -- this is an invariant.

    tools() is keyed on the float nominal but the table is printed through
    format_mm(d, decimals). Nominals closer than the print resolution collapse
    to one token and the file loads the same bit twice -- byte for byte the
    T2C7.000 / T3C7.000 defect this module's docstring exists to describe.
    """
    data = make_data(at(0, 0, 7.0, index=0), at(10, 0, 7.0004, index=1),
                     reference=ReferenceOutline(50, 50))
    with pytest.raises(EmitterError, match="7.000"):
        ExcellonEmitter().emit(data)


def test_inch_output_refuses_diameters_it_cannot_separate():
    """decimals=3 in inches is only 0.0254 mm of resolution."""
    data = make_data(at(0, 0, 3.02, index=0), at(10, 0, 3.03, index=1),
                     reference=ReferenceOutline(50, 50))
    with pytest.raises(EmitterError):
        ExcellonEmitter(ExcellonOptions(units=Units.INCHES)).emit(data)


def test_a_hole_outside_the_reference_outline_is_refused_in_lower_left():
    """SPEC 7 promises LOWER_LEFT keeps every coordinate positive."""
    data = make_data(at(-60, 0, 7.0, index=0), reference=ReferenceOutline(50, 50))
    with pytest.raises(EmitterError, match="negative"):
        ExcellonEmitter().emit(data)
```

- [ ] **Step 2: Run to verify they fail** — the first two currently *emit happily*, so assert the failure mode is `DID NOT RAISE`, not an unrelated error.
- [ ] **Step 3: Implement.** Build the rendered token for each nominal **after** unit conversion, check the nominal→token mapping is injective, and raise naming both nominals, the shared token, the units and the precision. Then check reframed coordinates are non-negative and raise naming the offending hole's index.
- [ ] **Step 4: Add the regression test that the old one could not catch** — the existing invariant test at `tests/test_excellon.py:161` is fed already-collapsed nominals. Add one driven end-to-end from `--diameter-tolerance 0.0001` in `tests/test_cli.py`… **no**: that file belongs to Task 9. Instead assert it here at emitter level and note the CLI-level case in Task 11.
- [ ] **Step 5: Run full suite; Step 6: Commit.**

---

### Task 6: Fix the PDF parser's clip handling, mark balance and circle validation

Fixes findings 03 (High), 15, 16. **Owns `src/aidrill/sources/ai_pdf.py`, `src/aidrill/geometry.py`, `tests/test_ai_pdf.py`, `tests/test_geometry.py` exclusively.**

**Files:**
- Modify: `src/aidrill/sources/ai_pdf.py:432-447` (`flush`), `:333` (`EMC`)
- Modify: `src/aidrill/geometry.py:287-312` (`_kappa_consistent`)

**Interfaces:** no public API change.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_path_that_clips_and_paints_is_kept():
    """SPEC 6.3 discards W/W* *followed by n*. W is not what makes it
    invisible -- n is. A background outline drawn `re W f` marks real ink."""
    pdf = build_pdf(background="10 10 200 100 re W f")
    data = AiPdfSource(pdf).read()
    assert data.reference is not None
    assert data.reference.width == pytest.approx(70.556, abs=1e-3)


def test_a_stroked_circle_that_also_clips_is_still_a_hole():
    pdf = build_pdf(drill=circle_ops(50, 50, 10) + " h W S")
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_an_unbalanced_emc_inside_a_form_does_not_unwind_the_caller():
    pdf = build_pdf(drill_form="EMC " + circle_ops(50, 50, 10) + " S")
    assert len(AiPdfSource(pdf).read().holes) == 1


def test_a_cusped_star_is_not_a_circle():
    """Four cubics on a circle's anchors with both control offsets negated:
    lengths and radial components are identical to a real circle, so a check
    that ignores tangential direction accepts inward cusps."""
    assert fit_circle(star_path(3.5)) is None
```

- [ ] **Step 2: Run to verify they fail.** Expected: outline `None`; `EmptyLayerError`; `EmptyLayerError`; a `Circle` where `None` was wanted.
- [ ] **Step 3: Fix `flush`** — discard only when the terminating operator is in `_NO_PAINT_OPS`. Remove the `clipping` test from `flush` entirely; the flag stays only to suppress the path when `n` follows.
- [ ] **Step 4: Fix the mark stack** — record `len(marks)` on entry to `_walk` and refuse to pop below it.
- [ ] **Step 5: Fix `_kappa_consistent`** — additionally require the control offset's tangential component to point along the direction of travel: `ox*tx + oy*ty > 0`.
- [ ] **Step 6: Run full suite; Step 7: Commit.**

---

### Task 7: Stop the drawing running off the sheet, and make its text XML-safe

Fixes findings 06, 17, 22. **Owns `src/aidrill/emitters/drawing_svg.py` and `tests/test_drawing_svg.py` after Task 4 lands.** Must be sequenced after Task 4, not parallel with it.

**Files:**
- Modify: `src/aidrill/emitters/drawing_svg.py:287` (reservation), `:575` (`dim_y`), `:243` (`_text`), `:1053` (`_dedupe_sorted`)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("n_rows", [13, 14, 15, 25])
def test_chain_dimensions_stay_on_the_sheet(n_rows):
    """The reserved space is capped at half the drawing area but dim_y kept
    stepping per row, so past ~14 rows the stack walked off the page --
    losing the numbers the machinist works from, with no note saying so."""
    data = make_data(*holes(*[(0.0, float(i) * 3.0) for i in range(n_rows)]),
                     reference=ReferenceOutline(113.0, 60.0))
    root = ET.fromstring(DrawingSvgEmitter().emit(data))
    sheet_h = DrawingOptions().sheet.height
    for line in root.iter("{http://www.w3.org/2000/svg}line"):
        if "dim-line" in (line.get("class") or ""):
            assert float(line.get("y1")) <= sheet_h


def test_control_characters_in_the_title_do_not_break_the_document():
    svg = DrawingSvgEmitter(DrawingOptions(title="A\x0cB")).emit(make_data(*holes((0.0, 0.0))))
    ET.fromstring(svg)   # must not raise
```

- [ ] **Step 2: Run to verify they fail** — 13 passes, 14/15/25 fail; the second raises `ParseError: not well-formed`.
- [ ] **Step 3: Clamp the dimension stack** to the rows that fit in the reserved space and emit an "N further dimension rows not shown" note, using the same honest-overflow pattern already at `:805` and `:950`.
- [ ] **Step 4: Strip characters outside the XML 1.0 `Char` production** in `_text` and `_sheet_title`.
- [ ] **Step 5: Import `ROW_SLACK`** in `_dedupe_sorted` instead of re-declaring `1e-6` — the precise duplication `tolerance.py` was created to end.
- [ ] **Step 6: Run full suite; Step 7: Commit.**

---

### Task 8: Fix the cluster mean and split the overloaded diagnostic code

Fixes findings 05, 09. **Owns `src/aidrill/pipeline/diameters.py` and `src/aidrill/pipeline/validate.py` exclusively.**

- [ ] **Step 1: Write the failing tests**

```python
def test_one_stray_circle_does_not_move_every_holes_nominal():
    """The mean was taken over the de-duplicated *set* of measured values, so a
    single outlier counted as much as a whole row of holes."""
    got = ClusterDiameters(0.05).nominal([6.9998] * 5 + [7.0400])
    assert got[6.9998] == pytest.approx(7.01, abs=0.005)   # hole-weighted, not 7.02


def test_the_two_no_reference_outline_conditions_have_distinct_codes():
    """SPEC 3 calls `code` a stable machine key. One key meaning two things at
    two severities defeats the purpose -- and changes the exit code."""
    from_stage = CheckReferenceSize((113.0, 60.0)).apply(DrillData()).diagnostics
    assert [d.code for d in from_stage] == ["no-reference-outline"]
    assert from_stage[0].severity is Severity.INFO
```

- [ ] **Step 2: Run to verify the first fails** (`7.02 != 7.01`). The second documents current stage behaviour and should pass — its partner assertion lives in Task 6's file, so here assert only the stage half and rename the **source's** code in Task 6… **no.** `ai_pdf.py` belongs to Task 6. To keep ownership clean: this task renames only the source-side code by coordinating through the plan — the source's diagnostic becomes `reference-outline-not-found` (WARNING) and is edited **in Task 6, Step 6a**. Add that step there.
- [ ] **Step 3: Compute the representative as the count-weighted mean** over `measured`, keeping the grouping value-based.
- [ ] **Step 4: Run full suite; Step 5: Commit.**

---

### Task 9: CLI validation, error hierarchy and house style

Fixes findings 13, and the `errors.py` outlier and merged-except cleanups. **Owns `src/aidrill/cli.py`, `src/aidrill/errors.py`, `tests/test_cli.py` exclusively.**

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("bad", ["infx60", "nanxnan", "0x60"])
def test_non_finite_or_zero_true_size_is_a_usage_error(bad):
    """`width <= 0` never rejects nan (all comparisons false) or inf, so
    --true-size infx60 exited 1 and wrote an SVG full of x="-inf"."""
    with pytest.raises(UsageError):
        cli.parse_true_size(bad)


def test_negative_true_size_is_rejected_by_our_validation_not_by_argparse():
    """The old test asserted '--true-size' appeared in stderr, which argparse's
    usage banner satisfies -- so it passed without ever reaching the check."""
    with pytest.raises(UsageError, match="positive"):
        cli.parse_true_size("-5x60")


@pytest.mark.parametrize("bad", ["", "3.2,-5", "3,nan"])
def test_malformed_drill_sizes_are_rejected(bad):
    with pytest.raises(UsageError):
        cli.parse_drill_sizes(bad)
```

- [ ] **Step 2: Run to verify they fail** for `infx60`, `nanxnan`, `""`, `3.2,-5`, `3,nan`.
- [ ] **Step 3: Add `math.isfinite` guards** to `parse_true_size` and `parse_drill_sizes`.
- [ ] **Step 4: Replace the broken CLI-level test** at `tests/test_cli.py:277-281` — assert on `"aidrill: error:"`, the program's own prefix, so argparse's banner can never satisfy it again.
- [ ] **Step 5: Merge the two byte-identical `except` blocks** at `cli.py:493-498` into one. Narrow `except Exception` at `:274` to `(NameError, TypeError, AttributeError)`.
- [ ] **Step 6: Bring `errors.py` up to house style** — `from __future__ import annotations`, `__all__`, a two-paragraph *why* docstring, `available: Iterable[str]` annotated. Give `EmptyLayerError` a `path_count: int = 0` constructor argument so `ai_pdf.py` stops mutating `.args` after construction.
- [ ] **Step 7: Run full suite; Step 8: Commit.**

---

### Task 10: Model hygiene — `Severity` ordering and deterministic rows

Fixes findings 11, 18. **Owns the `Severity` and `rows()` regions of `src/aidrill/model.py`.** Must be sequenced after Tasks 1–2, which also touch this file.

- [ ] **Step 1: Write the failing tests**

```python
def test_severity_supports_the_whole_comparison_protocol():
    assert Severity.INFO < Severity.ERROR
    assert Severity.INFO <= Severity.ERROR      # only __lt__ existed: TypeError
    assert Severity.ERROR >= Severity.WARNING


def test_comparing_severity_to_a_foreign_type_raises_TypeError():
    """list.index() raised ValueError; the protocol wants NotImplemented so
    Python can raise its standard TypeError."""
    with pytest.raises(TypeError):
        Severity.INFO < "x"


def test_rows_bucket_the_same_way_whatever_order_the_holes_arrive_in():
    spec = [(0.0, 0.0), (1.0, 5e-7), (2.0, 1e-6)]
    forward = DrillData(holes=holes(*spec)).rows()
    reverse = DrillData(holes=tuple(reversed(holes(*spec)))).rows()
    assert [y for y, _ in forward] == [y for y, _ in reverse]
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Reimplement `Severity` ordering** with `functools.total_ordering` and a module-level `_RANKS` mapping; `__lt__` returns `NotImplemented` for non-`Severity`. Keep `.value` as the lowercase word — `json_out.py:126` and `cli.py:380` depend on it.
- [ ] **Step 4: Sort by `y` before bucketing in `rows()`.**
- [ ] **Step 5: Run full suite; Step 6: Commit.**

---

### Task 11: Close the untested gaps the review found

Fixes TQ-2, TQ-3, TQ-4, TQ-5 and the missing SPEC §9 fixture assertions.

- [ ] **Step 1:** Replace the vacuous QTY assertion at `tests/test_drawing_svg.py:597` — `"2" in summary[0] and "5" in summary[1]` passes even if the quantities are swapped, because each string contains both digits. Regex `QTY (\d+)` as `tests/test_cli.py:535` already does correctly.
- [ ] **Step 2:** Replace both `pytest.raises(Exception)` catch-alls at `tests/test_geometry.py:258,278` with `pytest.raises(dataclasses.FrozenInstanceError)`.
- [ ] **Step 3:** Add a test for `ReferenceOutline.__post_init__` rejecting non-positive dimensions — currently zero coverage.
- [ ] **Step 4:** Add the missing SPEC §9 fixture assertions **post-pipeline** on `tar.ai`: the ⌀7.00 row at y=+18.00 and x ∈ {−40,−20,0,+20,+40}, the ⌀5.00 pair at y=−18.75 and x=∓19.00, and the duplicate group's location at (−40.00,+18.00). These hold today; only the assertions are missing.
- [ ] **Step 5:** Add the end-to-end CLI case for Task 5 — `--diameter-tolerance 0.0001` must now exit non-zero with a clear message rather than writing a broken tool table.
- [ ] **Step 6:** Import `RED`/`INK` from `drawing_svg` in the five tests that hardcode `c00000`, so changing a presentation colour stops breaking tests.
- [ ] **Step 7: Run full suite; Step 8: Commit.**

---

### Task 12: Convert the seeded loops into real property tests

- [ ] **Step 1:** Add `hypothesis` to the dev dependency group (Task 13 creates it; if that has not landed, install it in the test env and note the dependency).
- [ ] **Step 2:** Convert the four hand-rolled seeded loops (snap idempotence, dedupe idempotence, `tools()` reorder stability, cluster spread) to `@given`. They already have the right shape; this buys shrinking, so a failure reports a minimal counterexample instead of a random 12-element list.
- [ ] **Step 3:** Add failure messages to any assertion left as a bare `assert` inside a loop — `tests/test_pipeline.py:310` currently prints neither the tolerance nor the offending group.
- [ ] **Step 4: Run full suite; Step 5: Commit.**

---

### Task 13: Configure the tooling that would have caught the drift

Fixes finding 12.

- [ ] **Step 1:** Add to `pyproject.toml`:
  - `[project.optional-dependencies] dev = ["pytest", "pytest-cov", "hypothesis", "ruff", "mypy"]`
  - `[tool.ruff]` with an explicit `line-length` and `select = ["E","F","B","BLE","ISC","UP"]`, `ignore = ["RUF022"]` — the `__all__` ordering in this codebase is deliberately logical, not alphabetical.
  - `[tool.mypy]` with `warn_unused_ignores = true`.
- [ ] **Step 2:** Fix the two real mypy errors: the `sorted(key=...)` type at `pipeline/sort.py:31`, and the unsound `emitter_cls.__init__` access at `cli.py:273`.

- [ ] **Step 2a:** Configure `basedpyright`, which is what the maintainer's editor runs. Out of the box it reports 356 diagnostics against `src/aidrill`, ~190 of which are strict-mode unknown/Any noise from the untyped `pikepdf` boundary. Configure it so the signal survives:

```toml
[tool.basedpyright]
typeCheckingMode = "standard"
venvPath = "."
venv = ".venv"
reportUnusedImport = "none"   # see the trap below
```

`venvPath`/`venv` matter: without them basedpyright cannot resolve `pikepdf` and reports a spurious missing-import error.

**A trap that must not be "fixed":** basedpyright flags the three imports in `emitters/__init__.py:10` as unused. They are side-effect imports that run the `@register_emitter` decorators — deleting them empties `REGISTRY` and every `--emit` invocation fails with "unknown output format". They already carry `# noqa: F401` for ruff, which basedpyright does not honour. Suppress the rule or re-export the modules; never delete the imports.

- [ ] **Step 2b:** Fix the two genuine type errors basedpyright finds that mypy misses:

1. `pipeline/diameters.py:169` — `tuple(float(s) for s in sizes)` where `sizes` was narrowed only to bare `Sequence`, so its elements are `object` and `float(s)` is unsound. This is the duck-typing hazard already noted against `describe()`: a strategy exposing a non-numeric `sizes` raises at runtime. Narrow the elements, not just the container.
2. `emitters/drawing_svg.py:1110` — `_flagged_holes` is annotated `frozenset[int]` but builds from `d.get("hole_index")`, whose type is `ParameterValue | None` (`float | int | str | None`). The annotation is *wrong*, not merely loose. Narrow the payload value to `int` explicitly before adding it to the set.

**Do not** chase `reportUnknownMemberType`/`reportAny`/`reportUnknownArgumentType` at the `pikepdf` boundary — that library is untyped, the boundary is deliberately duck-typed, and `typeCheckingMode = "standard"` already silences most of it. `reportUnusedCallResult` (53 hits) is pure opinion; leave it off.

- [ ] **Step 2c:** `reportDeprecated` correctly flags `typing.Iterable`/`Sequence`/`Mapping`/`Iterator`/`Union` imports that should now come from `collections.abc` (and `X | Y` for `Union`). This overlaps ruff's `UP035`/`UP007`. Fix them together in Step 3 rather than twice.
- [ ] **Step 3:** Fix the genuine ruff findings only — the two dead imports at `emitters/base.py:12`, `BLE001`, the two `ISC004` implicit concatenations, `UP037`, `UP007`. Leave the stylistic defaults alone.
- [ ] **Step 4:** Type `REGISTRY: dict[str, type[Emitter]]` and `get_emitter() -> type[Emitter]`; annotate `Diagnostic.warning/info/error` and `get()`.
- [ ] **Step 5: Run ruff, mypy and the full suite; Step 6: Commit.**

---

### Task 14: Sync the spec with the code where the code is right

Six divergences where `docs/SPEC.md` is the stale side. The spec is explicitly load-bearing documentation here, so a stale spec is a defect.

- [ ] **Step 1:** §5.1 — replace "greedy single-linkage" with a description of leader clustering (each value compared to the group's smallest member, bounding group spread at `tolerance`), and note that PLAN.md requires the non-chaining behaviour.
- [ ] **Step 2:** §5.1 — replace "rounded to 2 dp" with the tolerance-derived precision rule, noting it is identical at the default and that a fixed 2 dp inverts the stage below 0.01.
- [ ] **Step 3:** §4 — add `extension: ClassVar[str]` to the `Emitter` protocol.
- [ ] **Step 4:** §7 — `Units.METRIC` → `Units.MILLIMETRES`.
- [ ] **Step 5:** §6.4 — replace the bbox aspect test with the centroid/equal-radius description, noting rotation invariance as the reason.
- [ ] **Step 6:** §3 — document `Diagnostic.data`, `DrillData.tool_counts()`, `rows()`, and the new `Hole.index` and `DrillData.processing`.
- [ ] **Step 7:** §7 — correct the Excellon header ordering to what the emitter actually writes.
- [ ] **Step 8: Commit.**

---

### Task 15: Record the contract change in an ADR

- [ ] **Step 1:** Write `docs/adr/0002-hole-identity-and-stage-provenance.md` covering: why `RawHole` could not serve as the key (equal raw geometry is valid and especially likely for duplicates); why identity is required rather than defaulted; why provenance is a generic record rather than per-stage classes; and the JSON version bump.
- [ ] **Step 2:** Amend ADR-0001's OCP claim honestly. The "one module plus one import line" promise holds only for emitters that take no options; an emitter needing CLI flags still forces a `cli.py` edit. Either state that limit or record letting registry entries contribute their own option factory as future work. Do not leave the stronger claim standing unqualified when `_OPTION_BUILDERS` contradicts it.
- [ ] **Step 3: Commit.**

---

### Task 16: Vacuity audit — prove every load-bearing test can actually fail

**This runs last, after every other task, as its own review phase.** A test that stays green when the behaviour it names is removed or inverted is not a test; it is documentation that costs CI time. Task 1 produced two such tests *from this plan's own text* — the identity regression test and the payload test both passed unchanged under the positional-survivor design the plan explicitly rejected, and both were caught only by hand-mutating the source. That is a 2-for-2 hit rate on the tests that mattered most, which is the argument for doing this systematically rather than trusting review-by-reading.

**Files:**
- Create: `.superpowers/sdd/2026-08-15-drill-data-integrity/vacuity-report.md` (outside the repo tree's tracked content)
- Modify: whichever test files the audit proves vacuous
- Test: the whole suite

**Interfaces:**
- Consumes: every test written or amended by Tasks 1–15.
- Produces: no source API change. Only test strengthening.

**Method — mutation, not reading, in two lanes.** Lane A automates breadth with a mutation-testing tool. Lane B hand-applies the semantic substitutions no tool can express. Both are required, and neither substitutes for the other — see the note below on why.

**Why both lanes.** `mutmut` mutates *syntax*: it flips operators, perturbs constants, negates conditionals, swaps boundaries. That catches an enormous class of weak assertions cheaply. But the two vacuous tests this plan actually produced were neither — "carry the survivor's **position** instead of its **index**" and "report the **constructor argument** instead of the **resolved default**" are *design* substitutions between two equally well-formed programs. No syntactic mutation operator generates them. Lane A finds the many shallow gaps; Lane B finds the few that matter most, which are exactly the ones guarding this plan's invariants.

**Viability, measured:** the suite runs in 0.5 s over 1439 statements, so a full mutmut run is minutes, not hours. There is no excuse for sampling.

- [ ] **Step 0 (Lane A): Configure and run mutmut**

Add to `pyproject.toml` (mutmut 3.7 reads `[tool.mutmut]`; confirm the key names against the installed version's docs before the full run, since the config API changed between 2.x and 3.x):

```toml
[tool.mutmut]
paths_to_mutate = ["src/aidrill/"]
tests_dir = ["tests/"]
```

Add `mutmut` to the dev dependency group created in Task 13. Then:

```bash
mutmut run                       # full run; use --max-children to parallelise
mutmut results                   # survivors
mutmut show <mutant>             # the exact surviving diff
```

Validate the harness on one module first (`mutmut run src/aidrill/pipeline/snap.py`) and confirm it reports *some* killed mutants — a run that kills nothing means the tool is not actually running the suite, not that the tests are perfect.

Triage every survivor into exactly one bucket, and record the bucket in the report:
- **Vacuous test** — the mutant changes real behaviour and no test noticed. Strengthen the test.
- **Equivalent mutant** — the mutant cannot change observable behaviour (e.g. perturbing a constant inside an unreachable defensive guard). Record it with one sentence of justification; do not chase it.
- **Genuinely untested behaviour** — no test claims to cover this at all. Write one, or record it as accepted risk with a reason.

A survivor left untriaged is the same failure this task exists to prevent, one level up.

- [ ] **Step 1 (Lane B): Hand-mutate each finding's fix and confirm its regression test dies**

**MANDATORY: every mutation run must disable the bytecode cache.** Use `python -B` or export `PYTHONDONTWRITEBYTECODE=1`. This is not hygiene — without it the results are fiction.

CPython validates a `.pyc` against the source's `(mtime, size)`, and **the `.pyc` header stores mtime as a 4-byte value in whole seconds**. A mutation applied and reverted inside one wall-clock second, at unchanged file size — which is every same-length mutation, run at machine speed — is invisible to the validator, so the interpreter silently executes the *previous* bytecode. Reproduced in this repo: a file mutated from `"ORIGINAL"` to `"MUTATEDX"` still printed `ORIGINAL`. Under `-B` the same sequence correctly prints `ORIGINAL → MUTATEDX → ORIGINAL`.

Both failure directions are possible and both are silent:
- the mutant never runs, the original passes, and the mutation is recorded as a **false survivor** — you strengthen a test that was already fine;
- the run executes the *preceding* mutant, and its kill list is attributed to the current one — a **false kill**, which is worse, because a genuine survivor is recorded as caught.

This defect was found in a hand-written harness during Task 4, where one mutation reported an identical kill list to the mutation before it. Any mutation evidence gathered without `-B` is not evidence.

- [ ] **Step 1a: Re-run Tasks 1–3's hand mutations under `-B`**

Tasks 1, 2 and 3 ran hand mutations before this was known (8, 8 and 9 respectively, all reported killed). Their conclusions are probably right — most were applied deliberately and slowly — but they were not gathered under a sound harness, so they are not evidence. Re-run them from the tables in each task's report and record the results in `vacuity-report.md` alongside the new ones. A mutation that now survives is a finding against that task, not against this one.

For each mutation below: apply it to `src/`, run only the tests that claim to cover it **with `-B`**, record whether any test fails, then **restore the source and confirm `git diff --stat src/` is empty** before the next mutation. A surviving mutation is a vacuous test and must be strengthened until it fails. Work one at a time; never leave a mutation in the tree.

One mutation per fix, targeting the exact behaviour the task claimed to restore:

| Task | Mutation to apply to `src/` | A test MUST fail |
|---|---|---|
| 1 | Make `Deduplicate._report` carry the survivor's *position* in the holes tuple instead of `survivor.index` | identity regression + payload test |
| 1 | Drop `index=` from `replace()` in one of `moved_to`/`translated`/`with_diameter` — i.e. renumber on transform | some identity test |
| 2 | Make `SnapPositions.describe()` report the *constructor argument* `warn_over` rather than the resolved default | the resolved-defaults test |
| 2 | Make `Pipeline.run` record `describe()` *before* applying instead of after | a provenance ordering test |
| 3 | Delete `"data"` from `_diagnostic`; separately delete `"index"` from `_hole` | round-trip / payload tests |
| 4 | Revert `_is_flagged` to matching on `(x, y, diameter)` | the both-orderings highlight test |
| 4 | Hardcode the title block's grid to `0.25` again | the two title-block tests |
| 5 | Remove the injectivity check | both collision tests |
| 5 | Compare tokens *before* unit conversion rather than after | the inch-units test |
| 6 | Restore `paths = [] if self.clipping else self._done` | clip-and-paint tests |
| 6 | Remove the tangential-direction term from the κ check | the cusped-star test |
| 8 | Revert the cluster mean to the de-duplicated set | the outlier test |
| 10 | Remove `total_ordering`; separately make `__lt__` raise instead of returning `NotImplemented` | the comparison-protocol tests |

- [ ] **Step 2: Hunt the two vacuity patterns this codebase has already produced**

Both were real here, so grep for them specifically rather than reading everything:

1. **Coincidence between an identity and a position.** Any test where a hole's `index` equals its position in the tuple proves nothing about identity. Grep every test constructing holes with `index=0, index=1, …` in input order and ask whether the assertion would survive a positional implementation. Renumber out of order where it would not.
2. **A substring assertion satisfied by the wrong string.** The review already found `assert "2" in summary[0] and "5" in summary[1]`, where each string contained both digits, and a `--true-size` test whose stderr assertion was satisfied by argparse's usage banner rather than the program's own error. Grep for `in stderr`, `in out`, `in text`, `in svg` and check each for a narrower assertion.

- [ ] **Step 3: Verify the strict-xfail markers self-destruct**

Every `xfail(strict=True)` added by this plan must turn XPASS into a failure once its blocking task lands. Confirm none survives at the end of the plan: `grep -rn "xfail" tests/` should return nothing. A leftover strict xfail means a task shipped without removing its marker, and the suite would be failing — if it is not failing, the marker is on a test that never started passing, which is its own finding.

- [ ] **Step 4: Write the report**

`vacuity-report.md` lists every mutation applied, whether it was caught, and by which test. Surviving mutations get a named fix. This table is the evidence that the suite is load-bearing; a green suite alone is not.

- [ ] **Step 5: Strengthen every vacuous test found, then re-run the full suite**

- [ ] **Step 6: Confirm the tree is clean of mutations**

Run `git diff --stat src/` — it must be empty. Then run the full suite one final time.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test: strengthen tests that survived mutation

Mutation-audited every fix from this plan. Tests that stayed green when
the behaviour they name was removed or inverted are not tests; each is
listed in the vacuity report with what now makes it fail."
```

---

## Self-Review

**Spec coverage.** All 22 review findings map to a task: 01→5, 02→1+4, 03→6, 04→15 (documented, not code-fixed, per decision 4), 05→8, 06→7, 07→3, 08→2+4, 09→8+6, 10→ deliberately out of scope (decision 5) except the merged except blocks in 9, 11→10, 12→13, 13→9, 14→5, 15→6, 16→6, 17→7, 18→10, 19→ out of scope (decision 5), 20→ out of scope (decision 5), 21→ out of scope (decision 5), 22→7. Test findings TQ-1→9, TQ-2/3/4/5→11, TQ-6→11, TQ-8→1 (conftest), TQ-9→11.

**Placeholder scan.** Tasks 8 and 5 each contained a mid-task ownership collision, resolved inline: the `no-reference-outline` source-side rename moves to Task 6 Step 6a, and Task 5's CLI-level regression test moves to Task 11 Step 5. Add Step 6a to Task 6 when executing: *rename the source's diagnostic at `ai_pdf.py:168` to `reference-outline-not-found` at WARNING severity.*

**Type consistency.** `Hole.index` (int) is used as `hole_index` in diagnostic payloads and `"index"` in JSON — three names for one concept, deliberately: the field, the payload key, and the wire key. `StageRun.parameters` keys carry unit suffixes (`grid_mm`, `tolerance_mm`) consistently across all five stages.
