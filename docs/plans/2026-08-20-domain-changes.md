# Domain Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make two silent failures speak — a hole that leaves the panel outline,
and artwork nested below the reader's recursion limit — each as a warning that
reaches exit 1 with every artefact still written.

**Architecture:** Both are *observation* changes, not decision changes. Nothing
new is refused and no artefact's content moves; two conditions that the program
already encounters and says nothing about become diagnostics. Containment
arrives as a fourth unconditional pipeline stage, `CheckOutlineContainment`,
beside the conditional `CheckCaseClearance` it is the weaker sibling of. Form
nesting stops being a hard maximum: `_MAX_FORM_DEPTH` becomes
`DEFAULT_FORM_DEPTH`, `--form-depth` overrides it, and the reader reports
truncation only when it actually refused a form that was there. The two are
diagnosed differently for a reason the spec records and this plan preserves: an
off-outline hole is observed and judged, while a form below the limit is never
observed at all, so silence there is indistinguishable from correctness.

**Tech Stack:** Python ≥3.10 (running 3.12), pytest, pikepdf, mypy, ruff.

**Spec:** `docs/specs/verification-technical.md` — this is **plan 2 of 3** from
its "Order of work" (§7), implementing §4's "Domain changes" in full.

## Global Constraints

- **The routing repair is NOT in this plan.** `docs/specs/verification-technical.md`
  §6 places `_two_opt` in Phase C, and §7 puts Phase C in plan 3, because its one
  risk — a float-summation tie changing a route — is only catchable by instruments
  plan 3 builds. Do not touch `pipeline/route.py` except for the docstring in
  Task 5.
- **No emitted artefact's geometry changes.** Both fixtures were measured before
  this plan was written: `tar.ai`'s tightest hole clears its outline by 8.750 mm
  and `pax.ai`'s by 11.000 mm, so no existing test's exit code moves. If any
  artefact byte outside a diagnostics block changes, stop and report it.
- **A test must fail when the behaviour it names is removed.** Check each clause
  of a compound condition independently, and ensure a mutation changes only the
  behaviour under test. (CLAUDE.md, Testing rules)
- **A stage must not depend on or assert that another stage ran first.**
  `CheckOutlineContainment` must never read `Hole.index` or call
  `DrillData.numbered()`; there is a test for this.
- **British spelling in prose, established American spelling in identifiers.**
- **Docstrings are at most ten physical lines** and explain why the code is
  shaped this way, never how it got that way. An in-suite audit warns on breach.
- **`from __future__ import annotations` and an explicit, logically ordered
  `__all__` in every Python module.**
- **`docs/adr/` is the authority.** Update and accept an ADR before changing the
  architecture in code. A sentence that narrates what an ADR's own decision
  changed is history and must not be retrofitted; a sentence asserting a current
  fact must be true.
- Suites at the start of this plan: `stompdrill` **1161** under `--hammond`,
  **1067** passed / 94 skipped without it; `stompmodel` **240**. Counts may only
  rise.
- Never run plain `uv sync` or plain `uv run` inside a workspace member — both
  re-resolve the shared root `.venv` and strip `pikepdf` and `OCP`. Use the
  `.venv/bin/` binaries directly, or `uv run --no-sync`. Recover with
  `uv sync --all-packages --all-extras` from the repository root.
- Keep every filesystem search anchored inside the repository, and to the
  narrowest directory that answers the question.
- Line length is 110 (`[tool.ruff] line-length`). E501 is not selected, so ruff
  will not tell you; keep to it anyway.

---

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `packages/stompdrill/tests/test_containment.py` | the containment stage, driven by hand-built `DrillData` |

**Modified:**

| Path | Change |
| --- | --- |
| `packages/stompdrill/src/stompdrill/pipeline/validate.py` | add `CheckOutlineContainment`; amend the module docstring |
| `packages/stompdrill/src/stompdrill/pipeline/__init__.py` | export it |
| `packages/stompdrill/src/stompdrill/__init__.py` | export it, and `DEFAULT_FORM_DEPTH` |
| `packages/stompdrill/src/stompdrill/cli.py` | compose the stage; add `--form-depth`; pass it to the source |
| `packages/stompdrill/src/stompdrill/sources/ai_pdf.py` | `DEFAULT_FORM_DEPTH`, the truncation report, `form_depth` |
| `packages/stompdrill/src/stompdrill/sources/__init__.py` | export `DEFAULT_FORM_DEPTH` |
| `packages/stompdrill/src/stompdrill/pipeline/route.py` | document `_path_length`'s precondition |
| `packages/stompmodel/src/stompmodel/units.py` | document `nm_from_mm`'s precondition |
| `packages/stompdrill/tests/conftest.py` | teach the PDF builder to nest forms |
| `packages/stompdrill/tests/test_cli.py` | stage order, the flag, the pass-through, the exit codes |
| `packages/stompdrill/tests/test_ai_pdf.py` | the depth limit and its report |
| `packages/stompdrill/tests/test_pipeline.py` | the root-export test |
| `packages/stompdrill/tests/test_route.py` | `_path_length`'s documented boundary |
| `packages/stompmodel/tests/test_units.py` | `nm_from_mm`'s documented boundary |
| `CLAUDE.md` | flags, exit codes, the stage list, one invariant, one parsing rule, counts |
| `docs/adr/0001-pipeline-and-emitter-adapters.md` | the fourth unconditional stage, in prose and in Figure 1 |
| `docs/adr/0002-domain-quantisers.md` | the containment policy and its reason |
| `docs/adr/0007-case-model-and-clearance.md` | the stage list, and what a model buys over the outline |
| `docs/GLOSSARY.md` | **Containment** |

## Recorded deviation from the spec

The spec (§4, "Form nesting") writes the renamed constant `_DEFAULT_FORM_DEPTH`,
with the leading underscore the old `_MAX_FORM_DEPTH` carried. This plan makes it
public: **`DEFAULT_FORM_DEPTH`**.

The spec's sentence decides that the number stops being a hard maximum; it does
not decide the constant's visibility, and it was written before `--form-depth`
had a help string. The CLI must state the default it will apply, and a private
constant the CLI cannot import forces a second literal `12` into `cli.py` — a
second authority for one number, which is what this repository spells once on
principle (`pipeline/snap.py:25`, `enclosures.py`'s generated catalogue,
`CATALOGUE_PARTS`). `DEFAULT_STANDARD` is already public and exported at the
package root for exactly this reason. Nothing else about the spec's decision
changes.

---

## Task 1: The containment stage

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/pipeline/validate.py`
- Modify: `packages/stompdrill/src/stompdrill/pipeline/__init__.py`
- Modify: `packages/stompdrill/src/stompdrill/__init__.py`
- Modify: `packages/stompdrill/tests/test_pipeline.py:855-877` (the root-export test)
- Test: `packages/stompdrill/tests/test_containment.py` (new)

**Interfaces:**
- Consumes: `stompmodel.model.DrillData`, `Hole`, `ReferenceOutline`, `StageRun`;
  `stompmodel.diagnostics.Diagnostic`; `stompmodel.units.Nanometre`, `format_nm`;
  the test helpers `at`, `codes`, `make_data` from `tests.conftest`.
- Produces: `stompdrill.pipeline.CheckOutlineContainment`, a parameter-free stage
  with `name = "check-outline-containment"`, `describe() -> StageRun`, and
  `apply(DrillData) -> DrillData`. It raises `hole-outside-outline` WARNING
  diagnostics and changes no hole. Task 2 composes it into the CLI pipeline.

**Context you need that the code does not state:**

The canonical frame is Y-up with its origin at the reference-outline centre
(CLAUDE.md, Domain invariants), so the outline occupies
`x ∈ [-width/2, +width/2]` and `y ∈ [-height/2, +height/2]`.
`ReferenceOutline.centre_x_nm` / `centre_y_nm` are the outline's centre *in
source space* (the page's lower-left origin) and are **not** what this stage
compares against. Do not use them.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompdrill/tests/test_containment.py` with exactly this content:

```python
"""The outline containment stage, driven by hand-built drill data."""

from __future__ import annotations

from stompdrill.pipeline import CheckOutlineContainment
from stompmodel.diagnostics import Severity
from stompmodel.model import ReferenceOutline, StageRun
from stompmodel.protocols import Stage
from stompmodel.units import Nanometre
from tests.conftest import at, codes, make_data

__all__: list[str] = []

MM = 1_000_000

#: 100 x 60 mm. Half-extents of 50 and 30 mm, so every boundary case below is a
#: whole number of millimetres and no assertion rests on an odd nanometre.
PANEL = ReferenceOutline(Nanometre(100 * MM), Nanometre(60 * MM))

#: The widest hole that fits centred on the +x edge: 50 - 7/2 = 46.5 mm.
ON_THE_EDGE = 46_500_000


def run(*holes, reference=PANEL):
    """Apply the stage to hand-built holes in the canonical, outline-centred frame."""
    return CheckOutlineContainment().apply(make_data(*holes, reference=reference))


def only(data):
    """The single diagnostic the stage raised, or fail saying how many there were."""
    assert len(data.diagnostics) == 1, codes(data)
    return data.diagnostics[0]


def test_it_satisfies_the_stage_protocol():
    assert isinstance(CheckOutlineContainment(), Stage)


def test_describe_names_the_stage_and_takes_no_parameters():
    assert CheckOutlineContainment().describe() == StageRun("check-outline-containment", ())


def test_a_hole_well_inside_the_outline_raises_nothing():
    assert codes(run(at(0, 0, 7 * MM, index=1))) == []


def test_a_hole_whose_edge_lands_exactly_on_the_boundary_is_contained():
    """Touching is inside. The inclusive boundary is the decision, not an accident."""
    assert codes(run(at(ON_THE_EDGE, 0, 7 * MM, index=1))) == []


def test_a_hole_one_nanometre_past_the_boundary_is_reported():
    """One nanometre, so the pair with the test above pins the comparison exactly."""
    assert codes(run(at(ON_THE_EDGE + 1, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_whose_centre_is_inside_but_whose_edge_is_not_is_reported():
    """The extent is the test, not the centre: 48 mm is inside, 48 + 3.5 is not."""
    assert codes(run(at(48 * MM, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_past_the_negative_edge_is_reported_too():
    """Absolute value, not a one-sided comparison."""
    assert codes(run(at(-48 * MM, 0, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_the_short_axis_is_checked_as_well_as_the_long_one():
    """Inside on x, outside on y. A stage that checked only x would pass everything."""
    assert codes(run(at(0, 28 * MM, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_a_hole_past_the_negative_short_edge_is_reported_too():
    assert codes(run(at(0, -28 * MM, 7 * MM, index=1))) == ["hole-outside-outline"]


def test_it_is_a_warning_so_the_artefacts_are_still_written():
    assert only(run(at(48 * MM, 0, 7 * MM, index=1))).severity is Severity.WARNING


def test_each_axis_reports_its_own_overshoot():
    """Unequal on purpose: equal figures would not catch the two swapped."""
    finding = only(run(at(48 * MM, 29 * MM, 7 * MM, index=1)))

    assert finding.get("overshoot_x_nm") == 1_500_000
    assert finding.get("overshoot_y_nm") == 2_500_000


def test_an_axis_that_is_inside_reports_no_overshoot():
    """Nought, not the negative slack: a contained axis lost no metal."""
    finding = only(run(at(0, 29 * MM, 7 * MM, index=1)))

    assert finding.get("overshoot_x_nm") == 0
    assert finding.get("overshoot_y_nm") == 2_500_000


def test_the_reported_overshoot_rounds_up():
    """One odd nanometre over. Flooring would report nought and read as contained."""
    finding = only(run(at(ON_THE_EDGE, 0, 7_000_001, index=1)))

    assert finding.get("overshoot_x_nm") == 1


def test_the_finding_carries_the_hole_and_the_outline_it_left():
    finding = only(run(at(48 * MM, 0, 7 * MM, index=1)))

    assert finding.location_nm == (48 * MM, 0)
    assert finding.get("diameter_nm") == 7 * MM
    assert finding.get("width_nm") == 100 * MM
    assert finding.get("height_nm") == 60 * MM


def test_the_message_states_the_hole_the_breakout_and_the_outline():
    message = only(run(at(48 * MM, 0, 7 * MM, index=1))).message

    assert "7" in message and "48" in message
    assert "1.5" in message
    assert "100" in message and "60" in message


def test_a_panel_with_no_outline_is_not_checked():
    """No outline, no boundary. Page-relative coordinates have nothing to leave."""
    assert codes(run(at(10_000 * MM, 0, 7 * MM, index=1), reference=None)) == []


def test_every_hole_outside_is_reported_not_only_the_first():
    result = run(at(48 * MM, 0, 7 * MM, index=1), at(-48 * MM, 0, 7 * MM, index=2))

    assert codes(result) == ["hole-outside-outline", "hole-outside-outline"]
    assert [d.location_nm for d in result.diagnostics] == [(48 * MM, 0), (-48 * MM, 0)]


def test_it_reports_an_unrouted_hole_as_readily_as_a_routed_one():
    """No stage may require another to have run first; this one must not read an index."""
    assert codes(run(at(48 * MM, 0, 7 * MM))) == ["hole-outside-outline"]


def test_the_stage_changes_no_hole():
    given = (at(48 * MM, 0, 7 * MM, index=1), at(0, 0, 7 * MM, index=2))

    assert run(*given).holes == given
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_containment.py -q
```

Expected: collection error — `ImportError: cannot import name 'CheckOutlineContainment'
from 'stompdrill.pipeline'`.

- [ ] **Step 3: Add the stage**

In `packages/stompdrill/src/stompdrill/pipeline/validate.py`, replace the module
docstring:

```python
"""Validation stages that report findings without changing any data.

``CheckOutlineContainment`` is in the CLI pipeline. ``CheckReferenceSize`` is
not: ``--case`` owns catalogue identity there, and a library caller may compose
that independent size assertion.
"""
```

Extend the imports and `__all__`:

```python
from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData, Hole, ReferenceOutline, StageRun
from stompmodel.units import Nanometre, format_nm

from ..tolerance import within

__all__ = ["CheckOutlineContainment", "CheckReferenceSize"]
```

Add the stage after `CheckReferenceSize`, before the private helpers:

```python
class CheckOutlineContainment:
    """Warn about a hole whose extent leaves the reference outline.

    The extent, not the centre, so an edge breakout is caught. A warning rather
    than an error because the outline is a published top view and not the
    drilled face: see ADR-0002. A panel with no outline has no boundary to
    leave and is skipped.
    """

    name: ClassVar[str] = "check-outline-containment"

    def describe(self) -> StageRun:
        """Record that parameter-free containment ran."""
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        outline = data.reference
        if outline is None:
            return data
        findings = []
        for hole in data.holes:
            # Doubled, so the decision needs no halving. A hole centred at ``x``
            # spans ``2|x| + d`` across that axis, and comparing that with the
            # full dimension keeps the boundary exact -- rounding a half-nanometre
            # radius here would settle a boundary case by arithmetic nobody wrote.
            over_x = 2 * abs(hole.x_nm) + hole.diameter_nm - outline.width_nm
            over_y = 2 * abs(hole.y_nm) + hole.diameter_nm - outline.height_nm
            if over_x > 0 or over_y > 0:
                findings.append(_outside(hole, outline, over_x, over_y))
        return data.with_diagnostics(*findings)
```

And the two helpers, beside `_whole_nanometres` and `_signed_mm`:

```python
def _outside(
    hole: Hole, outline: ReferenceOutline, over_x: int, over_y: int
) -> Diagnostic:
    """Report a breakout, with each axis's own overshoot on the finding.

    The sentence states the worst axis and the payload states both, so a
    consumer never has to subtract the two sizes back out of the prose.
    """
    x_nm = _overshoot(over_x)
    y_nm = _overshoot(over_y)
    return Diagnostic.warning(
        "hole-outside-outline",
        f"⌀{format_nm(hole.diameter_nm)} mm hole at "
        f"({format_nm(hole.x_nm)}, {format_nm(hole.y_nm)}) reaches "
        f"{format_nm(Nanometre(max(x_nm, y_nm)))} mm past the "
        f"{format_nm(outline.width_nm)} × {format_nm(outline.height_nm)} mm outline",
        location_nm=(hole.x_nm, hole.y_nm),
        data=(
            ("diameter_nm", hole.diameter_nm),
            ("overshoot_x_nm", x_nm),
            ("overshoot_y_nm", y_nm),
            ("width_nm", outline.width_nm),
            ("height_nm", outline.height_nm),
        ),
    )


def _overshoot(doubled_nm: int) -> Nanometre:
    """Halve a doubled overshoot, rounding up; a contained axis reports nought.

    Ceiling for the reason ``CheckCaseClearance`` ceilings its radius: the
    breakout reported must never read smaller than the metal actually lost.
    """
    return Nanometre(0 if doubled_nm <= 0 else -(-doubled_nm // 2))
```

- [ ] **Step 4: Export the stage**

In `packages/stompdrill/src/stompdrill/pipeline/__init__.py`, change the
`validate` import and add the name to `__all__` beside `CheckReferenceSize`:

```python
from .validate import CheckOutlineContainment, CheckReferenceSize
```

```python
    "CheckReferenceSize",
    "CheckOutlineContainment",
    "CheckCaseClearance",
```

In `packages/stompdrill/src/stompdrill/__init__.py`, add it to both the
`from .pipeline import (...)` block and `__all__`, keeping the existing line
shape:

```python
    CheckReferenceSize, ReviewGridTies, RouteHoles, DrillStandard, DRILL_STANDARDS,
    DEFAULT_STANDARD, CheckCaseClearance, CheckOutlineContainment,
```

```python
    "CheckReferenceSize", "ReviewGridTies", "RouteHoles", "DrillStandard", "DRILL_STANDARDS",
    "DEFAULT_STANDARD", "CheckCaseClearance", "CheckOutlineContainment",
```

- [ ] **Step 5: Extend the root-export test**

In `packages/stompdrill/tests/test_pipeline.py`, the test at line 855 loops over
the stages the root must name. Add the new stage to that tuple and to the
imports at the top of the file:

```python
    for name in (
        SnapPositions,
        SnapDiametersToDrillTable,
        IdentifyHammondFootprint,
        Deduplicate,
        ReviewGridTies,
        RouteHoles,
        CheckReferenceSize,
        CheckOutlineContainment,
    ):
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_containment.py packages/stompdrill/tests/test_pipeline.py -q
```

Expected: all pass, 19 new items in `test_containment.py`.

- [ ] **Step 7: Prove each repair with its mutant**

Apply each mutation, watch the named test fail, revert. A repair that is not
proved this way is not done. Record the killing test for each in your report.

| Mutation in `validate.py` | Must fail |
| --- | --- |
| `if over_x > 0 or over_y > 0:` → `>= 0` | `test_a_hole_whose_edge_lands_exactly_on_the_boundary_is_contained` |
| `if over_x > 0 or over_y > 0:` → `over_x > 0` only | `test_the_short_axis_is_checked_as_well_as_the_long_one` |
| `if over_x > 0 or over_y > 0:` → `over_y > 0` only | `test_a_hole_whose_centre_is_inside_but_whose_edge_is_not_is_reported` |
| `abs(hole.x_nm)` → `hole.x_nm` | `test_a_hole_past_the_negative_edge_is_reported_too` |
| `abs(hole.y_nm)` → `hole.y_nm` | `test_a_hole_past_the_negative_short_edge_is_reported_too` |
| `2 * abs(hole.x_nm)` → `abs(hole.x_nm)` | `test_a_hole_one_nanometre_past_the_boundary_is_reported` |
| `-(-doubled_nm // 2)` → `doubled_nm // 2` | `test_the_reported_overshoot_rounds_up` |
| `0 if doubled_nm <= 0 else` → return the halved value unconditionally | `test_an_axis_that_is_inside_reports_no_overshoot` |
| `if outline is None: return data` deleted | `test_a_panel_with_no_outline_is_not_checked` (with `AttributeError`) |
| `Diagnostic.warning` → `Diagnostic.error` | `test_it_is_a_warning_so_the_artefacts_are_still_written` |
| `findings.append(...)` → `return data.with_diagnostics(_outside(...))`, reporting only the first | `test_every_hole_outside_is_reported_not_only_the_first` |

- [ ] **Step 8: Lint and type-check**

```bash
ruff check packages tools
mypy packages
```

Expected: clean. If mypy objects to `over_x`/`over_y` being `int` where a
`Nanometre` is expected, that is the point — they are doubled quantities and not
lengths, so leave them `int` and brand only in `_overshoot`'s return, which is
where the value becomes a length again (CLAUDE.md, Domain invariants).

- [ ] **Step 9: Commit**

```bash
git add packages/stompdrill/src/stompdrill/pipeline/validate.py \
        packages/stompdrill/src/stompdrill/pipeline/__init__.py \
        packages/stompdrill/src/stompdrill/__init__.py \
        packages/stompdrill/tests/test_containment.py \
        packages/stompdrill/tests/test_pipeline.py
git commit -m "Report a hole that leaves the panel outline"
```

---

## Task 2: Containment in the command-line pipeline

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/cli.py:1-6` (module docstring),
  `:44-57` (the `.pipeline` import), `:343-354` (`build_pipeline`)
- Test: `packages/stompdrill/tests/test_cli.py:285-292`, `:1609-1618`, plus new tests

**Interfaces:**
- Consumes: `CheckOutlineContainment` from Task 1.
- Produces: `cli.build_pipeline` returns four stages by default and five with a
  case model, in the order `deduplicate, review-grid-ties, route,
  check-outline-containment[, check-case-clearance]`.

**Why it goes there:** after `Deduplicate`, so a duplicated outside hole is
reported once rather than twice. After `RouteHoles`, beside the clearance check
it is the weak sibling of, so the report reads outline-check then face-check.
The stage itself does not care — it reads no index — and Task 1's
`test_it_reports_an_unrouted_hole_as_readily_as_a_routed_one` keeps that true.

- [ ] **Step 1: Write the failing tests**

In `packages/stompdrill/tests/test_cli.py`, update the two existing stage-order
assertions. At line 285:

```python
def test_the_cli_fixes_the_stage_order():
    """The cli fixes the stage order."""
    assert [stage.name for stage in pipeline_for()] == [
        "deduplicate",
        "review-grid-ties",
        "route",
        "check-outline-containment",
    ]
```

At line 1609:

```python
def test_no_case_model_leaves_the_pipeline_unchanged():
    from stompdrill.cli import build_parser, build_pipeline

    args = build_parser().parse_args(["panel.ai"])

    assert [stage.name for stage in build_pipeline(args)] == [
        "deduplicate", "review-grid-ties", "route", "check-outline-containment"
    ]
```

Then append these two, after `test_a_case_model_appends_the_clearance_stage_last`:

```python
def test_containment_runs_after_deduplication_so_a_repeat_is_reported_once():
    """Ordering is the one thing a stage cannot self-declare; assert it here."""
    names = [stage.name for stage in pipeline_for()]

    assert names.index("deduplicate") < names.index("check-outline-containment")


def test_a_panel_whose_holes_are_all_inside_still_exits_clean(fake_source, capsys):
    """The other half of the pair: the stage must not warn about every panel."""
    fake_source(read())

    assert cli.main(["panel.ai"]) == 0

    assert "hole-outside-outline" not in capsys.readouterr().out


def test_a_hole_outside_the_outline_exits_one_and_still_writes_the_artefact(
    fake_source, tmp_path, capsys
):
    """A warning, so the drill file is written.

    ``read()``'s default 99.6 x 50.4 outline quantises to the catalogue's
    100 x 50 mm and raises nothing at all, so the containment finding is the
    only thing between this run and exit 0. The hole overshoots x by 1.5 mm.
    """
    fake_source(read(holes=(RawHole(Millimetre(48.0), Millimetre(0.0), Millimetre(7.0)),)))
    target = tmp_path / "out.drl"

    assert cli.main(["panel.ai", "--emit", f"excellon={target}"]) == 1

    assert "hole-outside-outline" in capsys.readouterr().out
    assert target.exists()
```

`read`, `RawHole` and `Millimetre` are all already imported in `test_cli.py`;
confirm before adding an import. Both facts the docstring states were measured
against the current tree before this plan was written: `read()`'s defaults
quantise clean, and that hole overshoots by exactly 1.5 mm.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_cli.py -q -k "stage_order or pipeline_unchanged or containment or outline"
```

Expected: the two updated assertions fail on a three-name list; the two new
tests fail — one on the missing stage name, one on exit `0`.

- [ ] **Step 3: Compose the stage**

In `packages/stompdrill/src/stompdrill/cli.py`, add `CheckOutlineContainment` to
the `from .pipeline import (...)` block in its alphabetical position (after
`CheckCaseClearance`), and rewrite `build_pipeline`:

```python
def build_pipeline(args: argparse.Namespace) -> Pipeline[DrillData]:
    """Build deduplicate → review-grid-ties → route → containment, then clearance.

    Review follows deduplication so it describes surviving holes; ordering is
    last among the geometry stages. The two checks only diagnose, so they run
    after numbering and every stage remains independently valid. Containment
    precedes clearance: the outline is the weaker boundary and the model's face
    is the stronger one.
    """
    stages: list[Stage[DrillData]] = [
        Deduplicate(),
        ReviewGridTies(),
        RouteHoles(),
        CheckOutlineContainment(),
    ]
    model = getattr(args, "case_model_object", None)
    if model is not None:
        stages.append(CheckCaseClearance(model))
    return Pipeline(stages)
```

Update the module docstring's second line:

```python
"""Command-line composition and reporting.

Quantiser order belongs to :func:`stompdrill.quantise`; post-quantisation stages
run deduplicate → review-grid-ties → route → check-outline-containment, with
clearance appended when a case model is supplied. Emitters are registry-resolved.
Exit codes are 0 clean, 1 warnings, 2 errors and 3 usage or I/O failure.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
```

Expected: **1067 + the new items** passed, 94 skipped. No test that previously
passed may now fail. If any CLI test's expected exit code moved, stop: it means
a fixture hole is outside its outline, which was measured not to be the case.

- [ ] **Step 5: Prove the composition with its mutant**

Remove `CheckOutlineContainment()` from the `stages` list and confirm
`test_the_cli_fixes_the_stage_order`, `test_no_case_model_leaves_the_pipeline_unchanged`
and `test_a_hole_outside_the_outline_exits_one_and_still_writes_the_artefact`
all fail. Revert. Then move `CheckOutlineContainment()` to the front of the list
and confirm `test_containment_runs_after_deduplication_so_a_repeat_is_reported_once`
fails. Revert.

- [ ] **Step 6: Lint, type-check and commit**

```bash
ruff check packages tools
mypy packages
git add packages/stompdrill/src/stompdrill/cli.py packages/stompdrill/tests/test_cli.py
git commit -m "Check containment on every run, not only a modelled one"
```

---

## Task 3: A form-nesting limit that reports being reached

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/sources/ai_pdf.py:44-45` (the
  constant), `:63-70` (`__init__`), `:91-113` (`read`), `:167-177` (`_extract`),
  `:83-89` (`layer_subpaths`), `:234-315` (`_walk_page` and `_walk`)
- Modify: `packages/stompdrill/src/stompdrill/sources/__init__.py`
- Modify: `packages/stompdrill/tests/conftest.py:111-153` (`build_pdf`)
- Test: `packages/stompdrill/tests/test_ai_pdf.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `stompdrill.sources.DEFAULT_FORM_DEPTH` (`int`, value `12`);
  `AiPdfSource(path, drill_layer=…, reference_layer=…, form_depth=DEFAULT_FORM_DEPTH)`
  raising `ValueError` for a depth below 1 or a non-`int`; a
  `nesting-truncated` WARNING on `read()` when — and only when — a Form XObject
  went unread because the limit was reached. Task 4 wires the flag to it.

**The mechanism, verified before this plan was written:** `build_pdf` puts the
form under the page's `/XObject` as `/Fm0`, and `_walk` passes the *inherited*
resources to a form that declares none. A form whose own content stream contains
`/Fm0 Do` therefore re-enters itself, and recursion stops only at the depth
limit. Measured against the current code: a self-referential form yields 12
drill subpaths at the default limit, 1 at `form_depth=1`, 2 at `form_depth=2`; a
form whose body ends in `/Im0 Do` yields 1 and refuses nothing, because
`_form_xobject` rejects an image `/Subtype`. Those four facts are what the tests
below assert.

- [ ] **Step 1: Teach the PDF builder to nest**

`build_pdf` already accepts `form=(matrix, content)`. Nothing needs to change in
it — a self-referential body is just a string. Add the two bodies as helpers in
`packages/stompdrill/tests/conftest.py`, immediately after `circle_ops`, and add
their names to that file's `__all__`:

```python
def self_nesting_form(cx: float = 20.0, cy: float = 20.0, r: float = 5.0) -> str:
    """A form body that draws a circle and then invokes itself.

    ``build_pdf`` gives the form no ``/Resources``, so ``/Fm0`` resolves against
    the page's and the form re-enters itself. Recursion ends only at the reader's
    depth limit, which is what makes this the vehicle for testing that limit.
    """
    return f"{circle_ops(cx, cy, r)} /Fm0 Do"


def image_ending_form(cx: float = 20.0, cy: float = 20.0, r: float = 5.0) -> str:
    """A form body ending in a ``Do`` that names an image, not another form."""
    return f"{circle_ops(cx, cy, r)} /Im0 Do"
```

- [ ] **Step 2: Write the failing tests**

Append to `packages/stompdrill/tests/test_ai_pdf.py`, and extend its
`from tests.conftest import ...` line with `image_ending_form, self_nesting_form`:

```python
# ---------------------------------------------------------------------------
# nested Form XObjects
# ---------------------------------------------------------------------------

#: A rectangle big enough to be the reference outline in the synthetic files below.
FRAME_OPS = "0 0 m 300 0 l 300 200 l 0 200 l h S"


def nested(tmp_path, name, body, *, depth=None, image=False):
    """Read a one-page file whose Drill layer invokes a form, at ``depth``."""
    path = build_pdf(
        tmp_path / name,
        {"Background": FRAME_OPS, "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], body),
        image=image,
    )
    source = AiPdfSource(path) if depth is None else AiPdfSource(path, form_depth=depth)
    return source.read()


def test_the_default_nesting_depth_is_twelve_levels():
    """A named constant, because the CLI states it in a help string too."""
    from stompdrill.sources import DEFAULT_FORM_DEPTH

    assert DEFAULT_FORM_DEPTH == 12
    assert AiPdfSource(FIXTURE).form_depth == DEFAULT_FORM_DEPTH


def test_nesting_stops_at_the_default_depth(tmp_path):
    data = nested(tmp_path, "deep.pdf", self_nesting_form())

    assert len(data.holes) == 12


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_the_requested_depth_is_how_many_levels_are_read(tmp_path, depth):
    data = nested(tmp_path, f"d{depth}.pdf", self_nesting_form(), depth=depth)

    assert len(data.holes) == depth


def test_reaching_the_limit_with_more_below_it_is_reported(tmp_path):
    data = nested(tmp_path, "cut.pdf", self_nesting_form(), depth=1)

    assert [d.code for d in warnings(data)] == ["nesting-truncated"]


def test_the_report_names_the_depth_that_was_reached(tmp_path):
    data = nested(tmp_path, "cut2.pdf", self_nesting_form(), depth=2)
    (finding,) = warnings(data)

    assert finding.get("form_depth") == 2
    assert "2" in finding.message


def test_stopping_short_of_the_limit_reports_nothing(tmp_path):
    """A limit nobody reached is not news. This is the whole point of the code."""
    data = nested(tmp_path, "shallow.pdf", circle_ops(20, 20, 5), depth=1)

    assert warnings(data) == []
    assert len(data.holes) == 1


def test_a_do_naming_an_image_at_the_limit_reports_nothing(tmp_path):
    """Nothing was refused: an image is not a deeper layer of artwork."""
    data = nested(tmp_path, "img.pdf", image_ending_form(), depth=1, image=True)

    assert warnings(data) == []
    assert len(data.holes) == 1


def test_truncation_below_the_top_level_still_reports(tmp_path):
    """The flag comes back up the recursion; it is not only the outermost frame."""
    data = nested(tmp_path, "deep3.pdf", self_nesting_form(), depth=3)

    assert [d.code for d in warnings(data)] == ["nesting-truncated"]


def test_the_fixture_reads_without_a_truncation_report(data):
    """Real artwork nests nowhere near twelve. A report on it would be a false alarm."""
    assert "nesting-truncated" not in [d.code for d in data.diagnostics]


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_a_depth_below_one_level_is_refused(bad):
    """``True`` is an ``int`` to Python and is not a depth anybody typed."""
    with pytest.raises(ValueError, match="form depth"):
        AiPdfSource(FIXTURE, form_depth=bad)


def test_listing_layers_still_works_when_nesting_is_truncated(tmp_path):
    """``layers()`` reads the same walk; the extra return value must not reach it."""
    path = build_pdf(
        tmp_path / "layers.pdf",
        {"Background": FRAME_OPS, "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], self_nesting_form()),
    )

    assert AiPdfSource(path, form_depth=1).layers() == ("Background", "Drill")


def test_layer_subpaths_still_works_when_nesting_is_truncated(tmp_path):
    path = build_pdf(
        tmp_path / "subpaths.pdf",
        {"Background": FRAME_OPS, "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], self_nesting_form()),
    )

    assert len(AiPdfSource(path, form_depth=2).layer_subpaths("Drill")) == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_ai_pdf.py -q -k "nest or depth or truncat"
```

Expected: `ImportError` on `DEFAULT_FORM_DEPTH`, and `TypeError: __init__() got
an unexpected keyword argument 'form_depth'`.

- [ ] **Step 4: Rename the constant and make it public**

In `packages/stompdrill/src/stompdrill/sources/ai_pdf.py`, replace lines 44-45:

```python
#: How deep Form XObjects are followed before the reader stops recursing.
#: Overridable with ``--form-depth``; reaching it is reported, never fatal.
DEFAULT_FORM_DEPTH = 12
```

Add it to that module's `__all__`:

```python
__all__ = ["AiPdfSource", "DEFAULT_FORM_DEPTH"]
```

And to `packages/stompdrill/src/stompdrill/sources/__init__.py`:

```python
"""Artwork sources that return unquantised ``RawDrillData``."""

from .ai_pdf import DEFAULT_FORM_DEPTH, AiPdfSource

__all__ = ["AiPdfSource", "DEFAULT_FORM_DEPTH"]
```

- [ ] **Step 5: Take the depth on the source**

Replace `AiPdfSource.__init__`:

```python
    def __init__(
        self,
        path: str | Path,
        drill_layer: str = "Drill",
        reference_layer: str = "Background",
        form_depth: int = DEFAULT_FORM_DEPTH,
    ) -> None:
        # ``type(...) is not int`` rather than ``isinstance``: a bool is an int
        # to Python, and ``form_depth=True`` is not a depth anybody typed.
        if type(form_depth) is not int or form_depth < 1:
            raise ValueError(f"form depth must be a whole number of levels from 1, not {form_depth!r}")
        self.path = Path(path)
        self.drill_layer = drill_layer
        self.reference_layer = reference_layer
        self.form_depth = form_depth
```

Leave `__repr__` alone: it is documented as naming the layer choices, and a
non-default depth reaches the operator through the diagnostic instead.

- [ ] **Step 6: Carry truncation back out of the walk**

Replace `_walk_page`:

```python
def _walk_page(page: pikepdf.Page, max_depth: int) -> tuple[list[_LayerPath], bool]:
    """Painted, non-clipping subpaths in page space, and whether nesting was cut.

    Page space is PDF points from the ``/MediaBox`` lower-left corner; the base
    CTM removes a non-zero box offset.
    """
    box = [float(v) for v in page.MediaBox]
    base: Matrix = (1.0, 0.0, 0.0, 1.0, -box[0], -box[1])
    out: list[_LayerPath] = []
    truncated = _walk(page, page.get("/Resources"), base, (), out, 0, max_depth)
    return out, truncated
```

Give `_walk` the limit and a return value. Its signature and docstring:

```python
def _walk(
    source,
    resources,
    ctm: Matrix,
    marks: tuple[frozenset[str], ...],
    out: list[_LayerPath],
    depth: int,
    max_depth: int,
) -> bool:
    """Interpret one content stream, appending to ``out``.

    ``marks`` is inherited by nested forms, but each stream may close only the
    marked-content entries it opened. Returns whether a form went unread for
    want of depth, here or anywhere below.
    """
    truncated = False
    stack: list[Matrix] = []
```

and replace the `-- forms` branch, which is the last branch of the loop:

```python
        # -- forms
        elif op == "Do":
            form = _form_xobject(operands, resources)
            if form is None:
                continue
            if depth >= max_depth:
                # Resolve first, then refuse: the condition worth reporting is
                # that a form went unread, not that a limit exists. A ``Do``
                # naming an image has lost nothing and must stay silent.
                truncated = True
                continue
            matrix = _numbers(form.get("/Matrix"), 6)
            inner = builder.ctm
            if matrix is not None:
                inner = multiply(_as_matrix(matrix), inner)
            truncated |= _walk(
                form,
                form.get("/Resources", resources),
                inner,
                marks,
                out,
                depth + 1,
                max_depth,
            )

    return truncated
```

Note the `return truncated` sits after the `for` loop, at function level.

- [ ] **Step 7: Report it from the read**

Replace `_extract` and its two other callers.

```python
    def layer_subpaths(self, layer: str) -> tuple[SubPath, ...]:
        """Return painted page-space subpaths on ``layer``, excluding clips."""
        names, paths, _ = self._extract()
        self._require_layer(layer, names)
        return tuple(p.path for p in paths if layer in p.layers)
```

```python
    def _extract(self) -> tuple[tuple[str, ...], list[_LayerPath], bool]:
        """Open the file once: layer names, painted subpaths, and truncation."""
        try:
            with pikepdf.open(self.path) as pdf:
                names = _layer_names(pdf)
                if len(pdf.pages) == 0:
                    raise SourceError(f"{self.path} has no pages")
                page = pdf.pages[0]
                paths, truncated = _walk_page(page, self.form_depth)
                return names, paths, truncated
        except (OSError, pikepdf.PdfError) as exc:
            raise SourceError(f"cannot read {self.path}: {exc}") from exc
```

`layers()` keeps `return self._extract()[0]` unchanged.

In `read()`, change the unpack and raise the warning before any other
diagnostic — it says what the rest of the read was working from:

```python
        names, paths, truncated = self._extract()
        self._require_layer(self.drill_layer, names)
        self._require_layer(self.reference_layer, names)

        diagnostics: list[Diagnostic] = []
        if truncated:
            diagnostics.append(
                Diagnostic.warning(
                    "nesting-truncated",
                    f"stopped {self.form_depth} Form XObjects deep; artwork nested "
                    f"below that was not read and is in no artefact. Raise "
                    f"--form-depth to reach it",
                    data=(("form_depth", self.form_depth),),
                )
            )
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
```

Expected: every test in the suite passes, including all of `test_ai_pdf.py`'s
existing form tests (`:543`, `:625`, `:693`).

- [ ] **Step 9: Prove each repair with its mutant**

| Mutation in `ai_pdf.py` | Must fail |
| --- | --- |
| `if depth >= max_depth` → `>` | `test_the_requested_depth_is_how_many_levels_are_read[1]` |
| `truncated = True` in the refusal → `truncated = False` | `test_reaching_the_limit_with_more_below_it_is_reported` |
| `if form is None: continue` moved *after* the depth check | `test_a_do_naming_an_image_at_the_limit_reports_nothing` |
| `truncated |= _walk(...)` → `_walk(...)` discarded | `test_truncation_below_the_top_level_still_reports` |
| `truncated = False` at the top of `_walk` → `True` | `test_stopping_short_of_the_limit_reports_nothing` and `test_the_fixture_reads_without_a_truncation_report` |
| `DEFAULT_FORM_DEPTH = 12` → `13` | `test_the_default_nesting_depth_is_twelve_levels` and `test_nesting_stops_at_the_default_depth` |
| `form_depth < 1` → `< 0` | `test_a_depth_below_one_level_is_refused[0]` |
| `type(form_depth) is not int` → `not isinstance(form_depth, int)` | `test_a_depth_below_one_level_is_refused[True]` |

- [ ] **Step 10: Lint, type-check and commit**

```bash
ruff check packages tools
mypy packages
git add packages/stompdrill/src/stompdrill/sources/ai_pdf.py \
        packages/stompdrill/src/stompdrill/sources/__init__.py \
        packages/stompdrill/tests/conftest.py \
        packages/stompdrill/tests/test_ai_pdf.py
git commit -m "Say when artwork was nested below what the reader read"
```

---

## Task 4: `--form-depth`

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/cli.py:59` (import), `:175-177`
  (the last flags), `:357-362` (`read_source`)
- Modify: `packages/stompdrill/src/stompdrill/__init__.py`
- Test: `packages/stompdrill/tests/test_cli.py:155-174` (`fake_source`), plus new tests

**Interfaces:**
- Consumes: `DEFAULT_FORM_DEPTH` and `AiPdfSource(form_depth=…)` from Task 3.
- Produces: `--form-depth N`, defaulting to `DEFAULT_FORM_DEPTH`, translated into
  a usage error (exit 3) below 1, and passed to the source.

**Where validation lives:** `AiPdfSource.__init__` raises `ValueError` and
`read_source` translates it into `UsageError`, exactly as `_snap_positions`
does for `SnapPositions`. The source is constructed before `pikepdf.open`, so a
bad depth is still a usage error rather than a diagnostic, which is the contract
CLAUDE.md states.

- [ ] **Step 1: Write the failing tests**

First, `fake_source` must accept the new keyword or every CLI test using it will
`TypeError`. Replace its inner class in `packages/stompdrill/tests/test_cli.py`:

```python
@pytest.fixture
def fake_source(monkeypatch):
    """Install a stand-in for ``AiPdfSource``. Returns an ``install`` callable."""

    def install(result):
        from stompdrill.sources import DEFAULT_FORM_DEPTH

        class FakeSource:
            def __init__(
                self,
                path,
                drill_layer="Drill",
                reference_layer="Background",
                form_depth=DEFAULT_FORM_DEPTH,
            ):
                self.path = path
                self.drill_layer = drill_layer
                self.reference_layer = reference_layer
                self.form_depth = form_depth

            def read(self):
                if isinstance(result, Exception):
                    raise result
                return result

        monkeypatch.setattr(cli, "AiPdfSource", FakeSource)
        return FakeSource

    return install
```

Then append these tests beside the other flag tests:

```python
def test_form_depth_defaults_to_the_sources_own_default():
    from stompdrill.sources import DEFAULT_FORM_DEPTH

    args = cli.build_parser().parse_args(["panel.ai"])

    assert args.form_depth == DEFAULT_FORM_DEPTH


def test_the_help_states_the_default_depth_it_will_apply():
    """One number, one authority: the help must not carry a second literal."""
    from stompdrill.sources import DEFAULT_FORM_DEPTH

    assert str(DEFAULT_FORM_DEPTH) in cli.build_parser().format_help()


def test_form_depth_reaches_the_source(monkeypatch):
    """Its own spy rather than ``fake_source``: the shared fixture stays a stub.

    A class attribute recording the last instance would be an ``attr-defined``
    error the moment anyone annotated that fixture's ``__init__``.
    """
    seen: dict[str, int] = {}

    class Spy:
        def __init__(self, path, drill_layer="Drill", reference_layer="Background", form_depth=0):
            seen["form_depth"] = form_depth

        def read(self):
            return read()

    monkeypatch.setattr(cli, "AiPdfSource", Spy)

    cli.main(["panel.ai", "--form-depth", "3"])

    assert seen["form_depth"] == 3


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_a_depth_below_one_level_is_a_usage_error(bad, capsys):
    assert cli.main([str(FIXTURE), "--form-depth", bad]) == 3

    assert "--form-depth" in capsys.readouterr().err


def test_a_depth_that_is_not_a_whole_number_is_a_usage_error():
    """argparse's own ``type=int`` rejects it; the exit code is still the contract."""
    assert cli.main([str(FIXTURE), "--form-depth", "1.5"]) == 3


def test_a_bad_depth_is_refused_before_the_panel_is_opened(tmp_path, capsys):
    """A file that would fail to parse must not be reached; the flag loses first."""
    unreadable = tmp_path / "not-a-pdf.ai"
    unreadable.write_text("this is not a PDF", encoding="utf-8")

    assert cli.main([str(unreadable), "--form-depth", "0"]) == 3

    assert "--form-depth" in capsys.readouterr().err


def test_truncated_nesting_exits_one_from_the_command_line(tmp_path, capsys):
    from tests.conftest import build_pdf, self_nesting_form

    panel = build_pdf(
        tmp_path / "deep.ai",
        {"Background": "0 0 m 300 0 l 300 200 l 0 200 l h S", "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], self_nesting_form()),
    )

    assert cli.main([str(panel), "--form-depth", "1"]) == 1

    assert "nesting-truncated" in capsys.readouterr().out
```

`FIXTURE` and `read` are already defined in `test_cli.py`; confirm before adding
imports.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_cli.py -q -k "form_depth or depth_below or nesting"
```

Expected: `AttributeError: 'Namespace' object has no attribute 'form_depth'`.

- [ ] **Step 3: Add the flag**

In `packages/stompdrill/src/stompdrill/cli.py`, import the constant beside the
source:

```python
from .sources import DEFAULT_FORM_DEPTH, AiPdfSource
```

Insert the argument after `--case-margin` and before `--emit`:

```python
    parser.add_argument(
        "--form-depth",
        metavar="N",
        type=int,
        default=DEFAULT_FORM_DEPTH,
        help="how many levels of nested Form XObject to follow in the artwork; "
        f"stopping with more below reports nesting-truncated (default: {DEFAULT_FORM_DEPTH})",
    )
```

- [ ] **Step 4: Pass it to the source**

```python
def read_source(args: argparse.Namespace) -> RawDrillData:
    try:
        source = AiPdfSource(
            args.panel,
            drill_layer=args.drill_layer,
            reference_layer=args.reference_layer,
            form_depth=args.form_depth,
        )
    except ValueError as failure:
        raise UsageError(f"--form-depth: {failure}") from failure
    return source.read()
```

- [ ] **Step 5: Export the constant from the package root**

In `packages/stompdrill/src/stompdrill/__init__.py`, alongside `AiPdfSource`,
for the same reason `DEFAULT_STANDARD` is there — a caller building a source
needs the number the tool would have used:

```python
from .sources import DEFAULT_FORM_DEPTH, AiPdfSource
```

```python
    "Source",
    "AiPdfSource", "DEFAULT_FORM_DEPTH",
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
```

Expected: everything passes. `fake_source` is used by many tests; if any of them
now fail, the fixture change is wrong, not the flag.

- [ ] **Step 7: Prove each repair with its mutant**

| Mutation in `cli.py` | Must fail |
| --- | --- |
| `default=DEFAULT_FORM_DEPTH` → `default=12` | nothing — and that is the point; instead delete `DEFAULT_FORM_DEPTH` from the help f-string and confirm `test_the_help_states_the_default_depth_it_will_apply` fails |
| `form_depth=args.form_depth` dropped from the `AiPdfSource(...)` call | `test_form_depth_reaches_the_source` (the spy sees `0`) and `test_truncated_nesting_exits_one_from_the_command_line` |
| the `try/except ValueError` removed from `read_source` | `test_a_depth_below_one_level_is_a_usage_error[0]` (the run raises rather than exiting 3) |
| `read_source` moved above `build_case_model` in `_run` | nothing should change; if a test fails, say which in your report |

- [ ] **Step 8: Lint, type-check and commit**

```bash
ruff check packages tools
mypy packages
git add packages/stompdrill/src/stompdrill/cli.py \
        packages/stompdrill/src/stompdrill/__init__.py \
        packages/stompdrill/tests/test_cli.py
git commit -m "Let the operator choose how deep the reader follows"
```

---

## Task 5: The two documented preconditions

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/units.py:45-47` (`nm_from_mm`)
- Modify: `packages/stompdrill/src/stompdrill/pipeline/route.py:55-58` (`_path_length`)
- Test: `packages/stompmodel/tests/test_units.py`,
  `packages/stompdrill/tests/test_route.py`

**Interfaces:**
- Consumes: nothing. Produces: nothing importable. Two docstrings and two tests.

**What this task is and is not.** The spec (§4) decides these two domain edges
are **documented as preconditions rather than guarded**: "a panel is physically
bounded and inventing a limit invites arguing about its value." So do not add a
check, a clamp, a custom exception or a `raise` of any kind. Write the
precondition down, and pin the boundary behaviour with a test — the test is not
hollow, because it fails the day someone adds the guard the spec declined.

Both boundaries were measured before this plan was written:
`nm_from_mm(1e21)` succeeds and `nm_from_mm(1e22)` raises
`decimal.InvalidOperation`; `_path_length` over a 10**150 nm separation returns
`1e+150` and over 10**160 nm raises `OverflowError`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/stompmodel/tests/test_units.py` (add
`import decimal` and `import pytest` if either is absent):

```python
def test_a_length_no_panel_could_have_raises_rather_than_rounding():
    """The documented precondition, made falsifiable.

    Guarding this is declined on purpose: a panel is physically bounded, and a
    limit invented here would be a number to argue about. The test fails if
    someone adds one, or turns the refusal into a silent answer.
    """
    assert nm_from_mm(1e21) == 10**27

    with pytest.raises(decimal.InvalidOperation):
        nm_from_mm(1e22)
```

Append to `packages/stompdrill/tests/test_route.py`:

```python
def test_a_separation_no_panel_could_have_raises_rather_than_saturating():
    """The documented precondition, made falsifiable. See ``nm_from_mm``'s twin.

    Constructed directly rather than through ``from_measurement``, whose
    millimetre provenance would overflow first and prove the wrong thing.
    """
    from stompdrill.pipeline.route import _path_length
    from stompmodel.model import Hole, RawHole
    from stompmodel.units import Millimetre

    raw = RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(7.0))
    origin = Hole(Nanometre(0), Nanometre(0), Nanometre(7_000_000), raw)

    def far(exponent: int) -> Hole:
        return Hole(Nanometre(10**exponent), Nanometre(0), Nanometre(7_000_000), raw)

    assert _path_length([origin, far(150)]) == 1e150

    with pytest.raises(OverflowError):
        _path_length([origin, far(160)])
```

Confirm `Nanometre` and `pytest` are already imported in `test_route.py`; add
what is missing.

- [ ] **Step 2: Run the tests to verify they pass already**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompdrill/tests/test_route.py -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= \
  packages/stompmodel/tests/test_units.py -q
```

Expected: **PASS**, both. This is the one place in this plan where a new test
passes before the change, because the change is documentation. Prove they are
not hollow at Step 4 instead.

- [ ] **Step 3: Write the preconditions down**

In `packages/stompmodel/src/stompmodel/units.py`:

```python
def nm_from_mm(mm: float) -> Nanometre:
    """Convert millimetres to whole nanometres, with ties away from zero.

    Precondition: a physically bounded panel length. Around 1e22 mm the exact
    decimal scaling exceeds the context's precision and raises
    ``decimal.InvalidOperation``. Unguarded on purpose: a bound invented here
    would be one more number to argue about than the physics already fixes.
    """
    return Nanometre(int(_round_half_up(Decimal(str(mm)) * NM_PER_MM)))
```

In `packages/stompdrill/src/stompdrill/pipeline/route.py`:

```python
def _path_length(route: list[Hole]) -> float:
    """Sum of leg lengths. Real distance, because a reversal changes legs
    unequally and squared lengths would not compare correctly.

    Precondition: panel-sized nanometres. A squared separation past ``float``'s
    range raises ``OverflowError``; unguarded for the same reason
    ``nm_from_mm`` is.
    """
    return sum(_distance_sq(a, b) ** 0.5 for a, b in pairwise(route))
```

- [ ] **Step 4: Prove the tests are not hollow**

Add the guard the spec declined, temporarily, and watch each test fail:

- In `nm_from_mm`, wrap the body in `try: ... except decimal.InvalidOperation:
  return Nanometre(0)`. `test_a_length_no_panel_could_have_raises_rather_than_rounding`
  must fail on `DID NOT RAISE`. Revert.
- In `_path_length`, wrap the body in `try: ... except OverflowError: return
  float("inf")`. `test_a_separation_no_panel_could_have_raises_rather_than_saturating`
  must fail on `DID NOT RAISE`. Revert.

Also confirm the first assertion of each carries its weight: change `1e21` to
`1e22` and `far(150)` to `far(160)` in turn and watch each test fail. Revert.

- [ ] **Step 5: Run both suites, lint, type-check and commit**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
ruff check packages tools
mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
git add packages/stompmodel/src/stompmodel/units.py \
        packages/stompmodel/tests/test_units.py \
        packages/stompdrill/src/stompdrill/pipeline/route.py \
        packages/stompdrill/tests/test_route.py
git commit -m "Write down the two limits nothing guards"
```

---

## Task 6: The contract and the ADRs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/adr/0001-pipeline-and-emitter-adapters.md`
- Modify: `docs/adr/0002-domain-quantisers.md`
- Modify: `docs/adr/0007-case-model-and-clearance.md`
- Modify: `docs/GLOSSARY.md`

**Interfaces:** consumes every earlier task; produces nothing importable.

**The rule that governs every edit here.** A sentence that narrates what an
ADR's own decision changed is history and must not be retrofitted. A sentence
asserting a current fact must be true. ADR-0001 saying the pipeline groups three
stages is the second kind, and it is now false. ADR-0007's account of *why* the
clearance check is a stage is the first kind and stays exactly as written.

- [ ] **Step 1: ADR-0002 — the containment policy**

This is the ADR the spec's "with an ADR amendment" names: ADR-0002 is the
validation-policy ADR, and it already owns the fact that makes containment a
warning ("The `Background` outline is drawn to enclosure backplate dimensions").

In **Decision**, after the paragraph beginning "The `Background` outline is drawn
to enclosure backplate dimensions" and before "`docs/parts/dimensions.tsv` is the
distributed catalogue authority":

```markdown
A hole whose **extent** leaves that outline is a warning, `hole-outside-outline`,
checked whenever an outline exists. The extent and not the centre, so a hole
that straddles the boundary is caught. Face containment is the stronger check,
against the real drilled face rather than the published top view; it needs a
supplied model and it is an error. See
[ADR-0007](0007-case-model-and-clearance.md).
```

In **Rationale**, after the paragraph beginning "The enclosure outcomes reflect
what the evidence can support":

```markdown
Containment warns because its evidence is weak in a known direction. The outline
is the backplate footprint and a die-cast face is smaller than it, so a hole
inside the outline may still miss the face and a hole a fraction outside it may
still be drillable. Withholding every artifact on that evidence would stop a
legitimate panel; saying nothing would let an edge breakout through unremarked.
A warning reports what was observed without claiming more than the outline can
support.
```

In **Consequences**, as a new final paragraph:

```markdown
A panel whose holes reach past its own outline still produces every requested
artifact and exits 1. An operator who wants that refused rather than reported
supplies a case model, whose face check is an error.
```

- [ ] **Step 2: ADR-0001 — the fourth unconditional stage**

Line 24 of `docs/adr/0001-pipeline-and-emitter-adapters.md` currently reads
"A `Pipeline` then groups `Deduplicate`, `ReviewGridTies`, and `RouteHoles` as
independent stages, each accepting and returning `DrillData`." Replace that
sentence with:

```markdown
A `Pipeline` then groups `Deduplicate`, `ReviewGridTies`, `RouteHoles` and
`CheckOutlineContainment` as independent stages, each accepting and returning
`DrillData`.
```

In Figure 1, add the node inside the `pipeline` subgraph and re-aim the two
edges that currently leave `route`:

```
        route["RouteHoles"]
        contain["CheckOutlineContainment"]
        clearance["CheckCaseClearance<br/>(conditional)"]
        dedupe -->|DrillData| ties
        ties -->|DrillData| route
        route -->|DrillData| contain
        contain -.->|DrillData, if --case-model| clearance
```

and below the subgraph:

```
    source -->|RawDrillData| quantise
    quantise -->|DrillData| dedupe
    contain -->|DrillData| selected
    clearance -.->|DrillData| selected
```

`route -->|DrillData| selected` is deleted; `route` now reaches the emitters
through `contain`. Check the rendered diagram has no node without an outgoing
edge before committing — a box with no way out is what the last plan's review
called "internally contradictory, which is worse" than an incomplete diagram.

- [ ] **Step 3: ADR-0007 — the stage list, and what a model buys**

Line 46 currently reads "`CheckCaseClearance` runs in the `Pipeline` alongside
`Deduplicate`, `ReviewGridTies`, and `RouteHoles`, because its diagnostics are
shared facts under ADR-0001". Change only the list:

```markdown
**Clearance is a stage, not emitter-local.** `CheckCaseClearance` runs in the
`Pipeline` alongside `Deduplicate`, `ReviewGridTies`, `RouteHoles` and
`CheckOutlineContainment`, because its diagnostics are shared facts under
ADR-0001:
```

Leave every word of the reasoning that follows it untouched.

In **Consequences**, as a new final paragraph:

```markdown
Without a case model a panel is still checked against its own reference outline:
`hole-outside-outline`, a warning under
[ADR-0002](0002-domain-quantisers.md). The face check is what a model buys — an
error, against the real drilled face rather than the published top view.
```

- [ ] **Step 4: `docs/GLOSSARY.md` — Containment**

Two boundaries now answer one question, which is exactly the ambiguity the
glossary exists to remove. Insert in the **Panel and drilling** section,
alphabetically between **Answer set** and **Drill document**:

```markdown
**Containment**:
Whether a hole's whole extent lies inside a boundary. Two boundaries answer it:
the reference outline, which warns, and the drilled face, which errors.
_Avoid_: bounds check, inside test
_See also_: Play area, Reference outline — the two boundaries.
```

- [ ] **Step 5: `CLAUDE.md` — the command-line contract**

In the **Flags** paragraph, insert between `--case-margin`'s parenthetical and
`--emit FORMAT=PATH`:

```
`--form-depth` (how many levels of nested Form XObject the reader follows),
```

In the **Exit codes** paragraph, replace the final sentence:

```markdown
`grid-too-fine`, `grid-ambiguous`, `hole-outside-outline` and `nesting-truncated`
are warnings and reach exit 1.
```

- [ ] **Step 6: `CLAUDE.md` — architecture, invariants and parsing**

In **Architecture**, replace "The pipeline applies `Deduplicate`, `ReviewGridTies`
and `RouteHoles`, and `CheckCaseClearance` too when a case model is supplied.":

```markdown
integer-nanometre data. The pipeline applies `Deduplicate`, `ReviewGridTies`,
`RouteHoles` and `CheckOutlineContainment`, and `CheckCaseClearance` too when a
case model is supplied.
```

In **Domain invariants**, after the bullet beginning "Enclosure artwork uses
published top-view/backplate dimensions":

```markdown
- A hole whose extent leaves the reference outline is a warning, not an error:
  the outline bounds the panel as drawn, not the drilled face the bit meets. The
  face check needs a supplied model and errors — see
  [ADR-0002](docs/adr/0002-domain-quantisers.md).
```

In **Parsing constraints**, after "Apply every `cm` current transformation
matrix, including a Form XObject's `/Matrix`.":

```markdown
- Form XObjects nest. The reader follows `--form-depth` levels and reports
  `nesting-truncated` only when it refused a form that was really there: a limit
  nobody reached is not news, and artwork below one is in no artefact and no
  report, so silence there is indistinguishable from correctness.
```

- [ ] **Step 7: `CLAUDE.md` — the suite counts**

Measure them; do not carry this plan's estimate into the file. Run both:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
```

and write the two numbers into the **Testing rules** block that currently reads
`# 240 passed` and `# 1161 passed`. This plan estimates 241 and about 1200; an
estimate is not evidence, and the last plan's estimate was wrong by one.

- [ ] **Step 8: Verify every documentation claim against the code**

Do not skip this. For each claim below, run the command and read the answer:

```bash
# the stage list and its order
.venv/bin/python -c "from stompdrill.cli import build_parser, build_pipeline; \
print([s.name for s in build_pipeline(build_parser().parse_args(['p.ai']))])"

# every flag CLAUDE.md names, and no flag it does not
.venv/bin/python -m stompdrill.cli --help

# the two new codes exist and are warnings
grep -rn "hole-outside-outline\|nesting-truncated" packages/stompdrill/src
```

- [ ] **Step 9: Run every gate and commit**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
ruff check packages tools
mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
git add CLAUDE.md docs/adr/0001-pipeline-and-emitter-adapters.md \
        docs/adr/0002-domain-quantisers.md \
        docs/adr/0007-case-model-and-clearance.md docs/GLOSSARY.md
git commit -m "Make the contract and the ADRs state the two new warnings"
```

---

## Done when

- `hole-outside-outline` and `nesting-truncated` each reach exit 1 from the
  command line, with every requested artefact still written, and each has a test
  that fails when the behaviour it names is removed.
- The mutant table in Tasks 1, 3 and 5 has been walked: every mutation applied,
  the named test seen to fail, and the mutation reverted.
- Both fixtures still produce the artefacts they produced before this plan, with
  the same exit codes.
- Both suites pass, `ruff check packages tools` is clean, and both mypy gates
  are clean.
- CLAUDE.md, ADR-0001, ADR-0002, ADR-0007 and the glossary say what the code
  does.

## Deliberately not in this plan

- **The `_two_opt` repair.** Plan 3, Phase C. See Global Constraints.
- **A tolerance on containment.** The comparison is exact and the boundary is
  inclusive. The spec asks for no tolerance, and `--case-margin` already exists
  for the operator who wants slack against a real face.
- **Reporting containment per panel rather than per hole.** One finding per hole
  with its location, matching `CheckCaseClearance`.
- **`AiPdfSource.__repr__` naming the depth.** It is documented as naming the
  layer choices; a non-default depth reaches the operator in the diagnostic.
- **Anything in `docs/BACKLOG.md`.** The five items carried out of plan 1 are
  their own commit, awaiting the user's go-ahead.
