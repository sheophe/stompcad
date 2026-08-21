# Verification Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish that every artefact of one invocation says the same thing about the same
geometry, by checking each emitter's last owned representation against the model and each
codec's bytes against that representation — then repair the one algorithm the new instruments
make it safe to touch.

**Architecture:** Three verification layers, split on one distinction: **the project owns
everything up to the codec, and codecs it did not write are trusted by design.** Layer 1
checks `P` itself (determinism, denotational invariance, one committed golden of the model).
Layer 2 checks each emitter's owned representation against the model — Python values, so
comparison is exact and needs no parser, and **cross-artefact agreement is established here**,
between owned representations, not by parsing artefacts back. Layer 3 checks the bytes, at the
depth each format warrants, through a recovery derived independently of the emitter that wrote
them. Work is spent unevenly on purpose: the more of a codec was outsourced, the less it costs
to verify.

**Tech Stack:** Python 3.10+ (running 3.12), pytest, hypothesis, `pdfminer.six` (new dev
dependency), pikepdf, stdlib `ElementTree` and `Decimal`, ruff, mypy, mutmut, a two-member uv
workspace.

**Spec:** `docs/specs/verification-technical.md` — this is **plan 3 of 3** from its "Order of
work", and the last. Plans 1 and 2 are landed (`docs/plans/2026-08-20-instruments-and-repairs.md`,
`docs/plans/2026-08-20-domain-changes.md`); a fourth run repaired what the first two exposed
(`docs/plans/2026-08-21-test-repairs.md`).

**Audit reports**, at `.scratch/test-audit/`, are the evidence the spec argues from and are
cited by task where they carry code or measurements a task must reproduce:

| Report | Carries |
| --- | --- |
| `parsers.md` | the Excellon grammar, the library survey, the SVG and PDF recovery probes |
| `route-performance.md` | the measured growth curve, the O(1) delta, the 96-route equivalence run |
| `interfaces.md` | G1 (`render`), G2 (`write_payload`), G5 (`SheetText`), D2, N1–N7 |
| `kinds.md` | Gap 3 (e2e), Gap 4 (golden), §4 (the generative conversions) |
| `contracts.md` | the nine contract-coverage gaps |
| `spike-symbolic.md` | the symbolic tier — **backlogged by this plan, not built** |

**Where the spec and an audit report disagree, the spec wins.** The reports were written
before it and two of them are superseded in part; §"Corrections this plan makes to the record"
at the foot of this file names every place, and each affected task repeats the correction.

---

## Global Constraints

Every task's requirements implicitly include this section.

### Environment

- Repository root `/Users/thelyx/repo/stompcad`. Work on branch **`stompcad-verification`**,
  cut from `main` at `e0852e7`. Never commit to `main`; merging is the user's call.
- **Anchor every `find` / `grep` / `rg` to an explicit path inside the repository.** Never
  search `~`, `/`, `$HOME`, or issue a bare recursive walk. Hard user requirement, and it
  binds any subagent a task dispatches.
- **Never run plain `uv sync` or plain `uv run` inside a workspace member** (`packages/*`).
  Both re-resolve the shared root `.venv` and strip `pikepdf` and `OCP`. Use the root venv's
  binaries by absolute path. The single sanctioned exception is `uv run --no-sync mypy`
  inside `packages/stompmodel`.
- Recovery if the environment is broken: `uv sync --all-packages --all-extras` from the root.
- Task 3 adds one dependency. Add it to the **root** `[dependency-groups] dev` and resync with
  `uv sync --all-packages --all-extras` from the root — never with `uv add` inside a member.

### Measured baselines

Taken on `main` at `e0852e7`, immediately before this plan was written:

| Gate | Result |
|---|---|
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q` | **1234 passed** |
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q` | **1140 passed, 94 skipped** |
| `.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q` | **241 passed** |

**No task in this plan predicts a test count.** Measure your own starting point, run the
suite, report what you got. If your number differs from what you expected, say so plainly and
investigate — **do not construct an explanation for it.** A previous run's implementer met a
stale predicted count and invented "some previously skipped tests may now run" rather than
reporting the discrepancy. Report the discrepancy.

### Gates every task must leave green

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
```

`mypy packages` covers `packages/stompdrill/tests` as well as its sources, so every helper
this plan adds under `tests/` is type-checked. It excludes `packages/stompmodel/tests`, which
is why the member's own config is a second gate.

### Project law (`CLAUDE.md`, binding)

- A test must fail when the behaviour it names is removed.
- Check each clause of a compound condition independently, and ensure a mutation changes only
  the behaviour under test.
- **Geometry alone determines output.** Two inputs representing the same geometry produce
  byte-identical artefacts, whatever their element order. No rule may consult input order.
- Any error withholds every requested artefact.
- Canonical coordinates are integer nanometres in a Y-up frame centred on the reference
  outline. Lengths carry their unit in the type; re-wrap at a real conversion, never everywhere.
- Keep new or edited docstrings to at most **ten physical lines**, explaining why the code is
  shaped this way and never how it got that way. An in-suite audit enforces this.
- Keep `from __future__ import annotations` and an explicit, logically ordered `__all__` in
  each Python module. Value objects are frozen, slotted dataclasses whose transforms return
  replacements.
- British spelling in prose, established American spelling in identifiers.
- `docs/adr/` is the authority. Update and accept an ADR **before** changing the architecture
  in code. A sentence narrating what an ADR's own decision changed is history and must not be
  retrofitted; a sentence asserting a current fact must be true.
- Mutation testing is a survey, not a numeric gate. Read it by module.
- Verification reports name the exact commands run; a tool invocation that suppresses the
  claimed rule is not evidence.
- Coverage targets: 90% per package, 100% for quantisers, stages, emitters and `stompmodel`'s
  codec.

### TDD, and the two places this plan departs from it

Tasks that add production code (**1, 10, 11**) and tasks that add new test-support modules
with behaviour of their own (**2, 3**) follow ordinary TDD: failing test, minimal
implementation, passing test, commit.

Two departures, each narrow:

- **Task 1 is a pure split and has no red step.** Its deliverable is that nothing changed.
  The proof is a byte comparison against a throwaway instrument, described in the task.
- **Tasks 4–9 and 12–13 add tests to code that already works.** There is no failing-first
  cycle available. The discipline that replaces it is **adversarial verification**: a new
  test must be shown to **fail when the behaviour it names is removed** — hand-mutate a
  scratch copy outside the repository, or load a monkeypatching pytest plugin from a
  directory on `PYTHONPATH`. **Never edit tracked source to test a test.** A task that cannot
  demonstrate this for one of its tests says so plainly in its report rather than claiming it.

### Precision, declared once

**Each recovery reports what its format states, and comparison is exact.** The comparison
rounds the canonical nanometre the way that format rounds, then demands equality. No epsilon
anywhere except STEP, which uses the kernel's `Precision::Confusion()`. This extends ADR-0003's
discipline to the readback.

| Format | Stated precision | Quantum | How a recovery parses it |
| --- | --- | --- | --- |
| Excellon | `ExcellonOptions.decimals`, default 3 | 1 µm = 1 000 nm | `Decimal(token) * 10**6`, exact |
| SVG | `_fmt`, six decimals of mm | 1 nm | `Decimal(attr) * 10**6`, exact |
| PDF | `_num`, four decimals of mm | 100 nm | float via pdfminer, then round to the quantum |
| JSON | integer nanometres | 1 nm | exact, no rounding |
| STEP | kernel | `Precision::Confusion()` | the one epsilon |

**Parse decimal text with `Decimal`, never `float`.** `parsers.md` used `float` and had to
reach for `pytest.approx` after `16.200000000000003` appeared; the noise was in its own
reframing arithmetic, not in any reader. `Decimal` removes both the noise and the epsilon.

### Independence is a gate, not a convention

A recovery that inverts its emitter's own transform proves the emitter self-consistent and
nothing more. The failure it must catch is a transform wrong in both directions. Task 2 builds
an AST gate — the same shape as `packages/stompmodel/tests/test_package_boundary.py` — asserting
that nothing under `packages/stompdrill/tests/recovery/` imports from `stompdrill.emitters`.
Every later task that touches a recovery keeps that gate green without weakening it.

---

## File Structure

### Created

| Path | Responsibility |
| --- | --- |
| `packages/stompdrill/tests/recovery/__init__.py` | the subpackage marker and its `__all__` |
| `packages/stompdrill/tests/recovery/facts.py` | `RecoveredCircle`, `RecoveredPanel` — the comparison vocabulary |
| `packages/stompdrill/tests/recovery/excellon.py` | the hand-rolled Excellon reader |
| `packages/stompdrill/tests/recovery/svg.py` | `ElementTree` over `<circle>` and `<rect>` |
| `packages/stompdrill/tests/recovery/pdf.py` | `pdfminer.six`, applying the CTM, recognising Bézier circles |
| `packages/stompdrill/tests/test_recovery.py` | the readers' own tests, and the independence gate |
| `packages/stompdrill/tests/test_layer3_codecs.py` | bytes against the representation each codec was handed |
| `packages/stompdrill/tests/test_layer2_owned.py` | each owned representation against the model; T4 |
| `packages/stompdrill/tests/test_layer1_model.py` | determinism, denotational invariance, the golden |
| `packages/stompdrill/tests/golden/tar-1590b.json` | the committed fact-set of the model |
| `packages/stompdrill/tests/test_packaging.py` | the console script, the entry point, both `py.typed` |
| `packages/stompdrill/tests/test_acceptance.py` | the nine contract-coverage gaps |

### Modified

| Path | Change |
| --- | --- |
| `packages/stompdrill/src/stompdrill/emitters/drawing_svg.py` | Task 1 `render`; Task 11 `SheetText` field |
| `packages/stompdrill/src/stompdrill/emitters/drawing_pdf.py` | Task 1 `render`; Task 11 `SheetText` field |
| `packages/stompdrill/src/stompdrill/emitters/drawing/build.py` | Task 11: `_plain_title_block` reads `content` |
| `packages/stompdrill/src/stompdrill/emitters/drawing/content.py` | Task 11: the plain title block's lines |
| `packages/stompmodel/src/stompmodel/protocols.py` | Task 10: `write_payload` |
| `packages/stompdrill/src/stompdrill/cli.py` | Task 10: `_write` delegates |
| `packages/stompdrill/src/stompdrill/pipeline/route.py` | Task 12: the O(1) delta, and the stale comment |
| `packages/stompdrill/tests/test_drawing_agreement.py` | Task 1: three private imports become two public |
| `packages/stompdrill/tests/test_emitter_registry.py` | Task 10: `cli._write` call sites |
| `packages/stompdrill/tests/test_snap.py` | Task 9: snapping as three properties |
| `packages/stompdrill/tests/test_pipeline.py` | Task 9: dedupe idempotence deleted for named examples |
| `packages/stompdrill/tests/test_invariant.py` | Task 9: the permutation invariant made generative |
| `packages/stompdrill/tests/test_route.py` | Task 12: a block at a realistic panel size |
| `packages/stompmodel/tests/test_codec.py` | Task 9: the round trip widened over shape |
| `packages/stompmodel/tests/test_protocols.py` | Task 10: `write_payload` |
| `packages/stompdrill/pyproject.toml` | Task 3: `pdfminer.six`; Task 9: `hypothesis` |
| `uv.lock` | Tasks 3 and 9, as a consequence |
| `CLAUDE.md` | Task 9 (the preserved-properties sentence), Task 12 (if it states a cost), Task 13 |
| `docs/specs/verification-technical.md` | Task 13: §5 and §7, the two gaps this plan rules on |
| `docs/adr/0005-binary-emitter-payloads.md` | Task 10 |
| `docs/BACKLOG.md` | Task 13 |

No production file is modified by Tasks 2–9 or 13.

---

## Phase A — before any new test

The spec puts one extraction ahead of everything else, and gives the reason: the test that
would protect it cannot be written until it happens. `emit()` fuses layout, build and
serialise, and only the fused whole is public, which is why `test_drawing_agreement.py`
reaches for `_serialise`, `_num` and `_render_item`. `layout()` is already public on both
emitters, so this finishes a split that is half done.

Phase A carries an obligation the other phases do not. It changes shipped code **before** the
semantic checks exist, and the migration's byte-comparison instrument was deliberately
deleted. So byte-identity across the split is proved by the same throwaway method the
migration used — emit before, emit after, diff — and the instrument is discarded again
afterwards.

---

### Task 1: `render(scene, title)` on both drawing emitters

A **pure split**. Byte-identical output, no redesign, no behaviour change, no new field. If
any artefact byte moves, the task has failed and the change is reverted rather than explained.

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing_svg.py`
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing_pdf.py`
- Modify: `packages/stompdrill/tests/test_drawing_agreement.py:29-31, 360-377, 395`

**Interfaces:**
- Consumes: nothing.
- Produces, and every later task uses these instead of a private import:

```python
class DrawingSvgEmitter:
    def render(self, scene: Scene, title: str) -> str: ...

class DrawingPdfEmitter:
    def render(self, scene: Scene, title: str) -> bytes: ...
```

`_num` on the PDF side stays private and stays imported by the agreement test. `interfaces.md`
G1 rules on this explicitly: predicting the exact string a stream will contain is legitimate
coupling to a *formatter*, which is a different thing from reaching past a missing seam. Three
private imports become one.

- [ ] **Step 1: Record the before-bytes with a throwaway instrument**

The instrument lives outside the repository and is deleted in Step 7. Nothing tracked is
touched by it.

```bash
cd /Users/thelyx/repo/stompcad
mkdir -p "${TMPDIR:-/tmp}/phase-a/before" "${TMPDIR:-/tmp}/phase-a/after"
emit_all () {   # $1 = output directory
  for panel_case in "tar.ai:1590B" "pax.ai:1590BB"; do
    panel="${panel_case%%:*}"; case="${panel_case##*:}"
    .venv/bin/python -m stompdrill.cli \
      "packages/stompdrill/tests/fixtures/${panel}" --case "${case}" \
      --emit "drawing-svg=$1/${panel}.svg" \
      --emit "drawing-pdf=$1/${panel}.pdf" \
      --emit "excellon=$1/${panel}.drl" \
      --emit "json=$1/${panel}.json" >/dev/null 2>&1
  done
}
emit_all "${TMPDIR:-/tmp}/phase-a/before"
ls -l "${TMPDIR:-/tmp}/phase-a/before"
```

Expected: eight files. Both panels exit non-zero (`tar.ai` raises one `duplicate-hole`
warning); the artefacts are still written, which is what matters here. If a file is missing,
stop — a comparison against a partial set proves nothing.

- [ ] **Step 2: Split the SVG emitter**

In `packages/stompdrill/src/stompdrill/emitters/drawing_svg.py`, add `Scene` to the existing
`.drawing.scene` import, then replace `emit` with these two methods. Every line of the body
below is moved verbatim from the current `emit`; only the two lines that resolve the layout and
the title move out of it.

```python
    def emit(self, data: DrillData) -> str:
        scene = build_scene(self.layout(data), data, self._sheet_text())
        return self.render(scene, self._sheet_title(data))

    def render(self, scene: Scene, title: str) -> str:
        """Serialise a resolved scene. The seam a two-backend comparison needs.

        ``emit`` fuses layout, build and serialise; only here is one scene
        drawn by one backend, which is the only way a divergence localises to
        a serialiser rather than to a layout.
        """
        # The namespace is declared as a plain attribute rather than through
        # ElementTree's ``default_namespace``: that option rejects unqualified
        # attribute names, and every SVG attribute here is unqualified.
        root = ET.Element(
            "svg",
            {
                "xmlns": SVG_NS,
                "width": f"{_fmt(scene.sheet.width)}mm",
                "height": f"{_fmt(scene.sheet.height)}mm",
                "viewBox": f"0 0 {_fmt(scene.sheet.width)} {_fmt(scene.sheet.height)}",
                "version": "1.1",
            },
        )
        _sub(root, "title").text = title
        _sub(root, "style", type="text/css").text = _STYLESHEET

        for item in scene.items:
            _render_item(root, item)

        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
```

- [ ] **Step 3: Split the PDF emitter**

In `packages/stompdrill/src/stompdrill/emitters/drawing_pdf.py`, add `Scene` to the existing
`.drawing.scene` import (it is already imported there) and replace `emit`:

```python
    def emit(self, data: DrillData) -> bytes:
        scene = build_scene(self.layout(data), data, self._sheet_text())
        return self.render(scene, self._title(data))

    def render(self, scene: Scene, title: str) -> bytes:
        """Serialise a resolved scene. The seam a two-backend comparison needs.

        The SVG side carries the same method for the same reason; keeping the
        pair symmetrical is what lets one test drive both over one scene.
        """
        return _serialise(scene, title)
```

- [ ] **Step 4: Run the suites and confirm nothing failed**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -3
```

Expected: the same count as your measured baseline, all passing. A split that changes a count
is not a split.

- [ ] **Step 5: Prove byte-identity**

```bash
cd /Users/thelyx/repo/stompcad
emit_all "${TMPDIR:-/tmp}/phase-a/after"     # the function from Step 1
diff -r "${TMPDIR:-/tmp}/phase-a/before" "${TMPDIR:-/tmp}/phase-a/after" && echo "IDENTICAL"
```

Expected: `IDENTICAL`, with no output from `diff`. **This is the task's deliverable.** If
`diff` reports anything at all — including the PDFs, which are deterministic by construction
(`deterministic_id=True`, no XMP) — revert Steps 2 and 3 and report what moved. Do not adjust
the comparison to accommodate a difference.

Record the exact `diff` invocation and its empty output in your report. A `diff` that
suppressed a file class is not evidence.

- [ ] **Step 6: Move the agreement test onto the public seam**

In `packages/stompdrill/tests/test_drawing_agreement.py`, delete the `_serialise` and
`_render_item` imports at lines 29–31, keeping `_num`:

```python
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from stompdrill.emitters.drawing_pdf import _num as pdf_num
from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
```

Replace `_svg_circles` with the public form. Its docstring loses the sentence describing the
gap, because the gap is gone:

```python
def _svg_circles(scene: Scene, cls_token: str) -> list[tuple[float, float, float]]:
    """Render ``scene`` through the SVG backend and read its circles back.

    ``render`` is the seam ``emit`` fuses: it takes the scene the test built
    rather than resolving one of its own, so the PDF and SVG halves of the
    comparison are reading a single scene.
    """
    root = ET.fromstring(DrawingSvgEmitter(DrawingOptions(title=TITLE)).render(scene, TITLE))
    return [
        (float(e.attrib["cx"]), float(e.attrib["cy"]), float(e.attrib["r"]))
        for e in root.iter(f"{{{SVG_NS}}}circle")
        if cls_token in (e.get("class") or "").split()
    ]
```

The `ET.fromstring(ET.tostring(...))` round trip and its comment go with it: `render` returns
text, so namespace inheritance already resolves on parsing.

In `test_a_holes_mark_lands_at_the_same_sheet_point_on_both_backends`, replace the one
`pdf_serialise` call:

```python
    pdf_stream = stream_of(DrawingPdfEmitter(PdfDrawingOptions(title=TITLE)).render(scene, TITLE))
```

- [ ] **Step 7: Discard the instrument, run every gate, and commit**

```bash
cd /Users/thelyx/repo/stompcad
rm -rf "${TMPDIR:-/tmp}/phase-a"
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Finish the split emit left half done"
```

`git status --porcelain -uall` before committing, not `git status --short`: the short form has
already, in this programme, been read as a clean tree while two modified files were sitting in it.

---

## Phase B — the layers and the recoveries

---

### Task 2: The comparison vocabulary, the Excellon recovery, and the independence gate

Excellon carries the whole weight. There is no `Scene` between `DrillData` and these bytes:
`ExcellonEmitter.emit` reframes, formats and joins strings in one method, so the writer and
the codec are the same code and there is no owned intermediate to check instead. A reader here
is the only thing standing between a wrong `_value` or `_reframe` and aluminium.

`parsers.md` establishes why this is hand-rolled rather than a dependency. `gerbonara` parses
our file correctly and was very nearly the answer; it is disqualified by three things, of which
the first is decisive: **it discards the tool number** (`original_number` is set only in its
*Gerber* parser), and the T-number is contract — `DrillData.tools()` assigns it and CLAUDE.md
makes the contiguous-block-per-tool an invariant. It also declares `requires-python >= 3.12`
against this project's `>=3.10`, and brings 17 transitive packages including Flask and Quart.
`pcb-tools` is dead on Python 3.11+ (`open(..., 'rU')`); `pygerber` is Gerber X3 only. No other
Excellon parser is published.

The reader is short because the format's difficulty is difficulty this emitter is
**structurally incapable of emitting**: implied decimals, zero suppression, `FMAT,1`, `INCH`,
slots, routing, incremental mode and repeats are all unreachable from `_coordinates`, which
writes one `X…Y…` per hole and nothing else. Hardening a test helper against inputs its only
supplier cannot generate is how a test becomes complex enough to need its own tests.

**Files:**
- Create: `packages/stompdrill/tests/recovery/__init__.py`
- Create: `packages/stompdrill/tests/recovery/facts.py`
- Create: `packages/stompdrill/tests/recovery/excellon.py`
- Create: `packages/stompdrill/tests/test_recovery.py`

**Interfaces:**
- Consumes: nothing.
- Produces, used by Tasks 3, 4 and 5:

```python
# tests/recovery/facts.py
@dataclass(frozen=True, slots=True)
class RecoveredCircle:
    x_nm: Nanometre
    y_nm: Nanometre
    diameter_nm: Nanometre
    number: int | None = None
    tool: int | None = None
    cls: str = ""

@dataclass(frozen=True, slots=True)
class RecoveredPanel:
    circles: tuple[RecoveredCircle, ...] = ()
    outline_nm: tuple[Nanometre, Nanometre] | None = None
    comments: tuple[str, ...] = ()

def nm_from_decimal(token: str | Decimal) -> Nanometre: ...

# tests/recovery/excellon.py
def read_excellon(text: str) -> RecoveredPanel: ...
```

**Why `RecoveredCircle` and not `RecoveredHole`.** Every item any of these formats states is
literally a circle; only Excellon's are all holes. A drawing sheet also states balloons, an
origin mark and a duplicate ring, and a recovery cannot tell them apart without the emitter's
own class vocabulary — which is exactly what it may not import. Reporting every circle is both
honest and the stronger check: the comparison then verifies the codec wrote every circle the
scene asked for and no extra one. The spec calls this shape "recovered holes and outline"; that
is a description of the shape, not a name, and the name follows what the field holds.

- [ ] **Step 1: Write the vocabulary**

`packages/stompdrill/tests/recovery/facts.py`. Named fields, not positions — transposing x and
y is the characteristic bug in a test helper, and a positional tuple makes it invisible.

```python
"""What a recovery reports, in canonical units, whatever format it read.

Named fields rather than positions: transposing x and y is the characteristic
bug in a helper like this, and a positional tuple hides it. Every field is
what the artefact *states*, never what the model holds — the comparison is
the test's job, not the vocabulary's.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stompmodel.units import Nanometre

__all__ = ["NM_PER_MM", "RecoveredCircle", "RecoveredPanel", "nm_from_decimal"]

#: Nanometres in a millimetre. Stated here so a recovery never spells 1e6.
NM_PER_MM = 1_000_000


@dataclass(frozen=True, slots=True)
class RecoveredCircle:
    """One circle an artefact states, hole or furniture.

    ``number``, ``tool`` and ``cls`` are the claims only some formats carry:
    Excellon states a tool and a sequence and no class, SVG states a class
    and neither of the others, and PDF states none of the three.
    """

    x_nm: Nanometre
    y_nm: Nanometre
    diameter_nm: Nanometre
    number: int | None = None
    tool: int | None = None
    cls: str = ""


@dataclass(frozen=True, slots=True)
class RecoveredPanel:
    """Everything one artefact states about one panel.

    ``comments`` is the header prose only Excellon carries and ``outline_nm``
    the extent only the drawings do; each is empty or ``None`` where its
    format states nothing, so a comparison cannot check a field by accident.
    """

    circles: tuple[RecoveredCircle, ...] = ()
    outline_nm: tuple[Nanometre, Nanometre] | None = None
    comments: tuple[str, ...] = ()


def nm_from_decimal(token: str | Decimal) -> Nanometre:
    """Exact nanometres from a decimal value, refusing a finer one.

    ``Decimal`` rather than ``float`` so the comparison can demand equality
    instead of an epsilon; a token past six decimals states a length the
    canonical model cannot hold, and is a defect in the writer, not a
    rounding question for the reader.
    """
    scaled = Decimal(token) * NM_PER_MM
    if scaled != scaled.to_integral_value():
        raise ValueError(f"not a whole number of nanometres: {token!r}")
    return Nanometre(int(scaled))
```

- [ ] **Step 2: Write the failing tests for the Excellon reader**

`packages/stompdrill/tests/test_recovery.py`. Every refusal below is a failure mode that would
otherwise put a hole in the wrong place at a plausible-looking number.

```python
"""The recoveries' own tests, and the gate that keeps them independent."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.recovery.excellon import read_excellon
from tests.recovery.facts import nm_from_decimal

__all__: list[str] = []

RECOVERY = Path(__file__).resolve().parent / "recovery"

#: A minimal file with every statement kind the emitter can write.
SAMPLE = """\
M48
;DRILL file for panel.ai
;ORIGIN=lower-left corner of the reference outline, X56.200 Y30.250 from its centre
FMAT,2
METRIC,TZ
T1C5.000
T2C7.000
%
G90
G05
T1
X37.200Y11.500
T2
X16.200Y48.250
T0
M30
"""


def test_the_reader_recovers_positions_as_exact_nanometres():
    panel = read_excellon(SAMPLE)

    assert [(c.x_nm, c.y_nm) for c in panel.circles] == [
        (37_200_000, 11_500_000),
        (16_200_000, 48_250_000),
    ]


def test_the_reader_recovers_the_tool_number_the_library_would_have_dropped():
    """The one fact this artefact most needs checked; see ``parsers.md``."""
    panel = read_excellon(SAMPLE)

    assert [c.tool for c in panel.circles] == [1, 2]


def test_the_reader_recovers_each_tools_declared_diameter():
    panel = read_excellon(SAMPLE)

    assert [c.diameter_nm for c in panel.circles] == [5_000_000, 7_000_000]


def test_the_reader_numbers_hits_in_file_order_because_the_format_states_no_number():
    """Excellon carries the drill sequence as position and nothing else, so
    position is the file's own claim here rather than a recomputed one."""
    panel = read_excellon(SAMPLE)

    assert [c.number for c in panel.circles] == [1, 2]


def test_the_reader_recovers_the_header_comments():
    panel = read_excellon(SAMPLE)

    assert panel.comments[0] == "DRILL file for panel.ai"


def test_the_reader_reports_the_origin_comment_that_states_the_frame():
    """The half-extents live only in this comment; nothing else in the file
    says which corner the coordinates are measured from."""
    panel = read_excellon(SAMPLE)

    assert "X56.200 Y30.250 from its centre" in panel.comments[1]


def test_excellon_states_no_outline():
    """The format carries none. Reporting ``None`` keeps a comparison from
    silently checking nothing."""
    assert read_excellon(SAMPLE).outline_nm is None


def test_a_file_without_the_m48_header_is_refused():
    with pytest.raises(ValueError, match="no M48 header"):
        read_excellon("G90\nX1.0Y1.0\n")


def test_a_file_with_no_header_terminator_is_refused():
    with pytest.raises(ValueError, match="no header terminator"):
        read_excellon("M48\nFMAT,2\nMETRIC,TZ\n")


def test_an_inch_file_is_refused_rather_than_read_in_the_wrong_unit():
    """The failure mode this guards is the dangerous one: a plausible number
    at 25.4x the intended position."""
    with pytest.raises(ValueError, match="unsupported units"):
        read_excellon(SAMPLE.replace("METRIC,TZ", "INCH,LZ"))


def test_a_coordinate_before_any_tool_selection_is_refused():
    with pytest.raises(ValueError, match="no tool selected"):
        read_excellon(SAMPLE.replace("T1\nX37.200Y11.500", "X37.200Y11.500"))


def test_an_unknown_body_statement_is_refused_rather_than_skipped():
    """A reader that skipped what it does not model would pass an emitter
    change by omission."""
    with pytest.raises(ValueError, match="unhandled Excellon statement"):
        read_excellon(SAMPLE.replace("T0\nM30", "G85\nT0\nM30"))


def test_an_unknown_header_statement_is_refused_too():
    with pytest.raises(ValueError, match="unhandled Excellon header"):
        read_excellon(SAMPLE.replace("FMAT,2", "FMAT,2\nICI,ON"))


def test_a_coordinate_finer_than_a_nanometre_is_refused():
    with pytest.raises(ValueError, match="whole number of nanometres"):
        nm_from_decimal("1.0000001")


def test_a_whole_number_of_nanometres_is_exact_at_six_decimals():
    """The boundary the refusal above sits on, so the refusal is not simply
    rejecting every fractional value."""
    assert nm_from_decimal("1.000001") == 1_000_001
```

- [ ] **Step 3: Run them and watch them fail**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_recovery.py -q 2>&1 | tail -5
```

Expected: a collection error — `ModuleNotFoundError: No module named 'tests.recovery'`.

- [ ] **Step 4: Write the reader**

`packages/stompdrill/tests/recovery/__init__.py`:

```python
"""Independent read-back of what this project's emitters write.

Test support, not shipped: no caller outside a test parses an Excellon file
or a drawing. Each module here reads what our emitters write and nothing
else, and none of them may import ``stompdrill`` -- a recovery that inverts
its emitter's own transform proves the emitter self-consistent and nothing
more. ``test_recovery.py`` holds the gate that enforces it.
"""

from __future__ import annotations

__all__: list[str] = []
```

`packages/stompdrill/tests/recovery/excellon.py`:

```python
"""Read back a metric Excellon FMAT,2 file, from the format's own grammar.

Nine statement kinds and explicit decimals -- everything that makes general
Excellon parsing hard is unreachable from ``_coordinates``. It raises on any
statement it does not model, so an emitter that grew one fails loudly rather
than passing by omission, and it asserts the header rather than assuming it.
"""

from __future__ import annotations

import re

from .facts import RecoveredCircle, RecoveredPanel, nm_from_decimal

__all__ = ["read_excellon"]

_TOOL_DEF = re.compile(r"^T(\d+)C(-?\d*\.?\d+)$")
_TOOL_SEL = re.compile(r"^T(\d+)$")
_HIT = re.compile(r"^X(-?\d*\.?\d+)Y(-?\d*\.?\d+)$")

#: Body statements that carry no geometry. Absolute mode, drill mode, end.
_INERT = frozenset({"G90", "G05", "M30"})

#: Header statements that are not a comment and not a tool definition.
_HEADER = frozenset({"FMAT,2", "METRIC,TZ"})


def read_excellon(text: str) -> RecoveredPanel:
    """Tools by number, hits in file order, and the header's comments."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "M48":
        raise ValueError("not an Excellon file: no M48 header")
    if "%" not in lines:
        raise ValueError("no header terminator: the file states no body")
    end = lines.index("%")
    header, body = lines[1:end], lines[end + 1 :]

    if "METRIC,TZ" not in header:
        raise ValueError(f"unsupported units or zero suppression: {header}")
    tools = {int(m[1]): nm_from_decimal(m[2]) for line in header if (m := _TOOL_DEF.match(line))}
    for line in header:
        if not (line.startswith(";") or line in _HEADER or _TOOL_DEF.match(line)):
            raise ValueError(f"unhandled Excellon header statement: {line}")

    circles: list[RecoveredCircle] = []
    selected: int | None = None
    for line in body:
        if match := _TOOL_SEL.match(line):
            selected = int(match[1]) or None  # T0 unloads the tool
        elif match := _HIT.match(line):
            if selected is None:
                raise ValueError(f"coordinate with no tool selected: {line}")
            circles.append(
                RecoveredCircle(
                    x_nm=nm_from_decimal(match[1]),
                    y_nm=nm_from_decimal(match[2]),
                    diameter_nm=tools[selected],
                    number=len(circles) + 1,
                    tool=selected,
                )
            )
        elif line not in _INERT:
            raise ValueError(f"unhandled Excellon statement: {line}")

    comments = tuple(line[1:] for line in header if line.startswith(";"))
    return RecoveredPanel(circles=tuple(circles), comments=comments)
```

- [ ] **Step 5: Run them and watch them pass**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_recovery.py -q 2>&1 | tail -3
```

- [ ] **Step 6: Write the independence gate**

Append to `packages/stompdrill/tests/test_recovery.py`. This is a second, small AST scanner —
`packages/stompmodel/tests/test_package_boundary.py` has one too, and the duplication is
unavoidable rather than careless: two `tests` packages cannot share one interpreter, and the
two gates ask different questions anyway ("stdlib or self" against "not the code under test").

```python
# ---------------------------------------------------------------------------
# independence
# ---------------------------------------------------------------------------


def imported_roots(source: str) -> set[str]:
    """Every absolute import root in ``source``. Relative imports cannot leave
    the subpackage, so they need no check."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def recovery_modules() -> list[Path]:
    """Every module in the subpackage, sorted so a failure names a stable one."""
    return sorted(p for p in RECOVERY.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_scanner_finds_an_emitter_import():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert "stompdrill" in imported_roots("from stompdrill.emitters.excellon import _value")


def test_the_scanner_finds_a_plain_package_import_too():
    """``import x`` and ``from x import y`` are the same edge, differently spelt."""
    assert "stompdrill" in imported_roots("import stompdrill.emitters.drawing_pdf")


def test_no_recovery_imports_the_package_whose_output_it_reads():
    """A recovery that inverts its emitter's own transform proves the emitter
    self-consistent and nothing more. The failure this must catch is a
    transform wrong in both directions, which self-consistency cannot see.
    """
    offenders = {
        str(module.relative_to(RECOVERY)): sorted(
            root for root in imported_roots(module.read_text(encoding="utf-8"))
            if root == "stompdrill"
        )
        for module in recovery_modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_scan_reaches_every_recovery_module():
    """An empty or narrowed walk would pass the gate above by finding nothing."""
    scanned = {str(module.relative_to(RECOVERY)) for module in recovery_modules()}

    assert scanned >= {"__init__.py", "facts.py", "excellon.py"}
```

- [ ] **Step 7: Prove the gate fires against a real violation**

Adversarial verification. Do **not** edit a tracked file — copy the subpackage out, break the
copy, and point the scanner at it:

```bash
cd /Users/thelyx/repo/stompcad
WORK="${TMPDIR:-/tmp}/gate-check"
rm -rf "$WORK" && mkdir -p "$WORK"
cp -R packages/stompdrill/tests/recovery "$WORK/recovery"
printf 'from stompdrill.emitters.excellon import ExcellonEmitter\n' >> "$WORK/recovery/excellon.py"
.venv/bin/python - "$WORK/recovery" <<'PY'
import ast, sys
from pathlib import Path
root = Path(sys.argv[1])
def roots(src):
    found = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found
bad = {p.name: sorted(r for r in roots(p.read_text()) if r == "stompdrill")
       for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}
print({k: v for k, v in bad.items() if v})
PY
rm -rf "$WORK"
```

Expected: `{'excellon.py': ['stompdrill']}` — the gate's predicate finds the violation.
Quote this output in your report.

- [ ] **Step 8: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Read an Excellon file back from the format, not from the writer"
```

---

### Task 3: The SVG and PDF recoveries

Two recoveries of the same shape, batched into one task because their difference is the whole
point and is easiest to see side by side.

**The asymmetry is earned, not assumed.** `drawing_svg._render_item` copies `cx`, `cy` and `r`
from the primitive to the attribute and performs no arithmetic; verify the `Scene` and SVG
follows, so its recovery is belt-and-braces. `drawing_pdf` does not. It owns a frame flip
(`_y(sheet, value) = sheet.height - value`, applied uniformly to lines and to circles), a
`PT_PER_MM` matrix, and a kappa-Bézier circle construction. The last matters most: a PDF circle
is four curves, so recovering a radius from one cannot be done by reading a field. **This is the
only owned transform nothing else reaches, which is why PDF's independent recovery is
load-bearing rather than belt-and-braces** — and why it is worth a dependency.

`pdfminer.six` is MIT, declares `requires-python >=3.10`, ships `py.typed`, and brings four
transitive packages (`cryptography`, `cffi`, `pycparser`, `charset-normalizer`). It applies the
CTM and exposes `LTCurve.original_path` with the Bézier operators intact.

**Everything below was verified against a real emitted sheet** (`tar.ai --case 1590B`, A3
landscape) while this plan was written. Do not re-derive it; do check it still holds.

| Fact | Measured |
| --- | --- |
| Path signatures on the page | `mcccch` ×16, `mlclclclch` ×1, `mlllh` ×13, `mllh` ×28, `ml` ×79 |
| `mcccch` | a circle, and the only circle — 7 holes, 7 balloons, the origin mark, the duplicate ring |
| `mlclclclch` | the panel outline, and the only one |
| The outline's `bbox` | exact: `112.400000 × 60.500000` mm. pdfminer computes it from on-curve endpoints, not control points, so the rounded corners cost nothing |
| Endpoint radius spread within a circle | ≤ `1.14e-13` pt |
| Recovered positions against the model | exact to six decimals — `-19.000000`, `-18.750000`, `+40.000000` |

SVG's own shape, from the same run: circle classes `hole` ×6, `hole dup` ×1, `balloon` ×7,
`origin` ×1, `dup-ring` ×1; rect classes `outline`, `border`, `schedule-box`, `title-block`,
`notes-box`. The outline rect carries `width="112.4" height="60.5" rx="3"`.

**Both recoveries report the sheet frame — millimetres, Y down, the `Scene`'s own frame — not
canonical model coordinates.** Layer 3's job is that the codec faithfully wrote the scene it was
handed; layer 2 is where that scene is checked against the model. Undoing the PDF's Y flip to
reach the sheet frame *is* the independent check of that flip.

**Files:**
- Modify: `packages/stompdrill/pyproject.toml` — its `[dependency-groups] dev`
- Modify: `uv.lock`
- Create: `packages/stompdrill/tests/recovery/svg.py`
- Create: `packages/stompdrill/tests/recovery/pdf.py`
- Modify: `packages/stompdrill/tests/test_recovery.py`

**Interfaces:**
- Consumes: `RecoveredCircle`, `RecoveredPanel`, `nm_from_decimal`, `NM_PER_MM` (Task 2).
- Produces, used by Tasks 4 and 5:

```python
# tests/recovery/svg.py
def read_svg(text: str) -> RecoveredPanel: ...

# tests/recovery/pdf.py
def read_pdf(payload: bytes) -> RecoveredPanel: ...
```

- [ ] **Step 1: Add the dependency, to the member and not to the root**

It goes in **`packages/stompdrill/pyproject.toml`**, because ADR-0008's governing test is that
each member installs and passes its own tests *alone*. A recovery imported by
`packages/stompdrill/tests/` that is declared only at the root would fail
`cd packages/stompdrill && pytest` while passing from the root — the exact split ADR-0008
exists to forbid. `stompmodel` already declares its own `hypothesis` for the same reason.

**Verified while this plan was written:** declaring it in the member is also *sufficient* for
the shared root environment. `uv sync --all-packages --all-extras` from the root then installs
`pdfminer-six` and `pycparser` into `.venv`, and `pikepdf` and `OCP` keep importing. Do not add
a second declaration at the root.

```toml
[dependency-groups]
dev = ["pytest", "pdfminer.six"]
```

The comment above that line currently reads "`pytest` is the whole list: the tests import
nothing else the distribution does not already depend on". That sentence becomes false with
this edit, so rewrite it rather than leaving it — a stale statement in a config file is the
same defect as a stale statement in an ADR:

```toml
# What this package's own suite needs, so that ADR-0008's sentence -- change
# into the member, sync, test -- runs a real suite rather than an import check.
# `pdfminer.six` joins `pytest` for one reason: tests/recovery/pdf.py reads a
# drawing back independently of the writer, and the writer's own transforms
# are the thing it exists to check. Every module that reaches OCP still guards
# itself with ``importorskip``, so the heavy `step` extra stays opt-in.
```

```bash
cd /Users/thelyx/repo/stompcad
uv sync --all-packages --all-extras 2>&1 | tail -5
.venv/bin/python -c "import pdfminer, pikepdf, OCP; print(pdfminer.__version__)"
```

Expected: a version string, with `pikepdf` and `OCP` still importing. If either stopped, the
sync was run from inside a member — re-run it from the repository root. `uv.lock` changes by
two lines; commit it with the task.

- [ ] **Step 2: Write the failing tests**

Append to `packages/stompdrill/tests/test_recovery.py`. These drive the real emitters, because
a recovery that only ever reads a hand-written sample is not reading this project's output.

```python
# ---------------------------------------------------------------------------
# the drawing recoveries
# ---------------------------------------------------------------------------

from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter
from stompdrill.emitters.drawing_svg import DrawingSvgEmitter
from tests.conftest import at, make_data
from tests.recovery.pdf import read_pdf
from tests.recovery.svg import read_svg
from stompmodel.model import ReferenceOutline
from stompmodel.units import Nanometre


def sheet_panel():
    """Four holes of two diameters on a declared outline, routed out of tuple
    order so nothing can pass by recomputing a number from a list position."""
    return make_data(
        at(-20_000_000, 18_000_000, 7_000_000, index=3),
        at(20_000_000, 18_000_000, 7_000_000, index=4),
        at(-19_000_000, -18_750_000, 5_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    )


def test_the_svg_recovery_finds_every_circle_the_sheet_draws():
    svg = DrawingSvgEmitter().emit(sheet_panel())

    recovered = read_svg(svg)

    assert len(recovered.circles) == svg.count("<circle")


def test_the_svg_recovery_keeps_each_circles_class():
    """The class is what selects a hole downstream; a geometry-only recovery
    could not tell a hole from a balloon."""
    classes = {c.cls for c in read_svg(DrawingSvgEmitter().emit(sheet_panel())).circles}

    assert "hole" in classes


def test_the_svg_recovery_reports_the_outline_extent():
    recovered = read_svg(DrawingSvgEmitter().emit(sheet_panel()))

    assert recovered.outline_nm == (112_400_000, 60_500_000)


def test_the_svg_recovery_is_exact_with_no_epsilon():
    """``_fmt`` states six decimals of a millimetre, which is one nanometre,
    so a ``Decimal`` parse loses nothing and the comparison can demand
    equality."""
    holes = [c for c in read_svg(DrawingSvgEmitter().emit(sheet_panel())).circles
             if "hole" in c.cls.split()]

    assert all(c.diameter_nm in (5_000_000, 7_000_000) for c in holes)


def test_the_pdf_recovery_finds_the_same_circles_as_the_svg_one():
    """Two independent readers over two codecs of one panel. Neither can be
    right by inverting the other's transform: they share no code below
    ``RecoveredPanel``."""
    data = sheet_panel()

    from_svg = read_svg(DrawingSvgEmitter().emit(data))
    from_pdf = read_pdf(DrawingPdfEmitter().emit(data))

    assert len(from_pdf.circles) == len(from_svg.circles)


def test_the_pdf_recovery_reports_the_outline_extent():
    """The outline is drawn with rounded corners; its recovered extent must be
    the rectangle, not the rectangle plus the arcs' control points."""
    recovered = read_pdf(DrawingPdfEmitter().emit(sheet_panel()))

    assert recovered.outline_nm == (112_400_000, 60_500_000)


def test_the_pdf_recovery_undoes_the_frame_flip_the_emitter_owns():
    """``_y(sheet, value) = sheet.height - value`` is an owned transform that
    nothing else in the project reaches. A recovery reading Y-up points
    straight through would put every mark on the wrong half of the sheet."""
    data = sheet_panel()

    svg_ys = sorted(c.y_nm for c in read_svg(DrawingSvgEmitter().emit(data)).circles)
    pdf_ys = sorted(c.y_nm for c in read_pdf(DrawingPdfEmitter().emit(data)).circles)

    assert pdf_ys == svg_ys


def test_the_pdf_recovery_recovers_a_radius_from_four_beziers():
    """A PDF circle is four curves, so a radius cannot be read from a field.
    This is the reason this recovery is load-bearing rather than a smoke check.
    """
    diameters = {c.diameter_nm for c in read_pdf(DrawingPdfEmitter().emit(sheet_panel())).circles}

    assert {5_000_000, 7_000_000} <= diameters


def test_the_pdf_recovery_refuses_a_four_curve_path_that_is_not_a_circle():
    """The signature alone does not prove a circle; the endpoints must be
    equidistant from their own centroid."""
    from tests.recovery.pdf import circle_from_path

    squashed = [
        ("m", (10.0, 0.0)),
        ("c", (0.0, 0.0), (0.0, 0.0), (0.0, 5.0)),
        ("c", (0.0, 0.0), (0.0, 0.0), (-10.0, 0.0)),
        ("c", (0.0, 0.0), (0.0, 0.0), (0.0, -5.0)),
        ("c", (0.0, 0.0), (0.0, 0.0), (10.0, 0.0)),
        ("h",),
    ]

    with pytest.raises(ValueError, match="not a circle"):
        circle_from_path(squashed)
```

- [ ] **Step 3: Run them and watch them fail**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_recovery.py -q 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'tests.recovery.svg'`.

- [ ] **Step 4: Write the SVG recovery**

`packages/stompdrill/tests/recovery/svg.py`:

```python
"""Read a drawing sheet back out of its SVG, with the standard library.

Plain elements in millimetre user units at 1:1, and the only ``transform``
anywhere is ``rotate`` on text -- nothing nests a coordinate system, so no
CTM composition is needed. Values arrive at six decimals of a millimetre,
which is one nanometre, so a ``Decimal`` parse is exact.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from .facts import RecoveredCircle, RecoveredPanel, nm_from_decimal

__all__ = ["read_svg"]

_NS = "{http://www.w3.org/2000/svg}"


def read_svg(text: str) -> RecoveredPanel:
    """Every circle the sheet draws, and the panel outline's extent.

    The input is a document this suite emitted moments earlier, from a writer
    that produces no DOCTYPE and no entities: no untrusted input, so no
    ``defusedxml``.
    """
    root = ET.fromstring(text)
    circles = tuple(
        RecoveredCircle(
            x_nm=nm_from_decimal(element.attrib["cx"]),
            y_nm=nm_from_decimal(element.attrib["cy"]),
            diameter_nm=nm_from_decimal(Decimal(element.attrib["r"]) * 2),
            cls=element.get("class", ""),
        )
        for element in root.iter(f"{_NS}circle")
    )
    outline = next(
        (
            (nm_from_decimal(r.attrib["width"]), nm_from_decimal(r.attrib["height"]))
            for r in root.iter(f"{_NS}rect")
            if "outline" in (r.get("class") or "").split()
        ),
        None,
    )
    return RecoveredPanel(circles=circles, outline_nm=outline)
```

- [ ] **Step 5: Write the PDF recovery**

`packages/stompdrill/tests/recovery/pdf.py`. `_PT_PER_MM` is redefined here from the format's
own definition — PDF user space is 1/72 inch and an inch is exactly 25.4 mm — rather than
imported from the emitter that used it. That is the whole point of the module.

```python
"""Read a drawing sheet back out of its PDF, independently of the writer.

The PDF backend owns three transforms nothing else in the project reaches: a
frame flip, a points matrix, and a circle built from four cubic Beziers. A
radius therefore cannot be read from a field, which is why this recovery is
load-bearing rather than a smoke check. Constants here come from the format,
never from ``drawing_pdf``.
"""

from __future__ import annotations

import io
import math
from decimal import Decimal
from typing import Any

from pdfminer.high_level import extract_pages

from .facts import NM_PER_MM, RecoveredCircle, RecoveredPanel

__all__ = ["circle_from_path", "read_pdf"]

#: PDF user space is 1/72 inch and an inch is exactly 25.4 millimetres.
_PT_PER_MM = Decimal(72) / Decimal("25.4")

#: ``_num`` states four decimals of a millimetre, so every coordinate in the
#: stream is a whole multiple of this. Rounding to it recovers the stated
#: value exactly and leaves no epsilon in the comparison.
_QUANTUM_NM = 100

#: Four cubic segments closed by ``h``: the only circle PDF has.
_CIRCLE = "mcccch"

#: A rectangle with four corner arcs. The panel outline, and nothing else.
_ROUNDED_RECT = "mlclclclch"

#: Endpoint radii may disagree by float noise (measured: 1.14e-13 pt) and by
#: nothing else. Well under the stated quantum, well over the noise.
_ROUND_ENOUGH_PT = 1e-6


def circle_from_path(path: list[Any]) -> tuple[float, float, float]:
    """Centre and radius in points, from four cubic segments.

    The signature alone does not prove a circle: the four on-curve endpoints
    must be equidistant from their own centroid. Refusing rather than
    skipping keeps an emitter change from passing by omission.
    """
    ends = [segment[-1] for segment in path[1:5]]
    cx = sum(x for x, _ in ends) / 4.0
    cy = sum(y for _, y in ends) / 4.0
    radii = [math.hypot(x - cx, y - cy) for x, y in ends]
    if max(radii) - min(radii) > _ROUND_ENOUGH_PT:
        raise ValueError(f"not a circle: endpoint radii disagree by {max(radii) - min(radii)}")
    return cx, cy, sum(radii) / 4.0


def _nm(points: float) -> int:
    """Page points to nanometres, at the precision the stream states."""
    nanometres = float(Decimal(1) / _PT_PER_MM) * points * NM_PER_MM
    return round(nanometres / _QUANTUM_NM) * _QUANTUM_NM


def read_pdf(payload: bytes) -> RecoveredPanel:
    """Every circle the page draws, and the panel outline's extent.

    Reported in the sheet's own frame -- millimetres, Y down -- so undoing
    the emitter's Y-up flip is part of what this checks.
    """
    page = next(iter(extract_pages(io.BytesIO(payload), laparams=None)))
    height_nm = _nm(page.bbox[3])

    circles: list[RecoveredCircle] = []
    outline: tuple[int, int] | None = None
    for obj in page:
        path = getattr(obj, "original_path", None)
        if not path:
            continue
        signature = "".join(segment[0] for segment in path)
        if signature == _CIRCLE:
            cx, cy, radius = circle_from_path(path)
            circles.append(
                RecoveredCircle(
                    x_nm=_nm(cx),
                    y_nm=height_nm - _nm(cy),
                    diameter_nm=_nm(2 * radius),
                )
            )
        elif signature == _ROUNDED_RECT and outline is None:
            x0, y0, x1, y1 = obj.bbox
            outline = (_nm(x1 - x0), _nm(y1 - y0))
    return RecoveredPanel(circles=tuple(circles), outline_nm=outline)
```

`_nm` returns a plain `int` and the dataclass fields are `Nanometre`, which is a `NewType` over
`int`. If mypy objects, wrap at the construction site — `x_nm=Nanometre(_nm(cx))` — rather than
loosening the field type. Brand at a real conversion; this is one.

- [ ] **Step 6: Run them and watch them pass, and keep the gate green**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_recovery.py -q 2>&1 | tail -3
```

Both new modules are scanned by `test_no_recovery_imports_the_package_whose_output_it_reads`
without any change to it — `recovery_modules()` walks the directory. Extend
`test_the_scan_reaches_every_recovery_module`'s literal set to `{"__init__.py", "facts.py",
"excellon.py", "svg.py", "pdf.py"}` so the walk is still pinned.

The test module itself imports `stompdrill.emitters` to drive the real emitters. That is
correct and is not a gate violation: the gate scans `tests/recovery/`, not `test_recovery.py`.
A test may know both sides; a recovery may not.

- [ ] **Step 7: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Recover both drawing sheets without asking the writer"
```

---

### Task 4: Layer 3 — the bytes against the representation each codec was handed

A codec's job is to turn one representation into bytes. Layer 3 checks exactly that, and no
more; whether the representation was right is layer 2's question, and the composition of the
two is what makes the bytes right. Excellon is the exception and the reason the layer matters:
it has no owned intermediate, so its check runs all the way to the model and carries full weight.

| Format | Compared against | Codec owner | Precision |
| --- | --- | --- | --- |
| Excellon | **the model**, reframed with `with_origin` | ours | 1 µm — `ExcellonOptions.decimals` |
| SVG | the `Scene` | ours | 1 nm |
| PDF | the `Scene` | ours | 100 nm |
| JSON | the document mapping, via `from_document` | stdlib — trusted | exact |
| STEP | the cut shape, via `read_step` and face interrogation | OCC — trusted | `Precision::Confusion()` |

**Files:**
- Create: `packages/stompdrill/tests/test_layer3_codecs.py`

**Interfaces:**
- Consumes: `read_excellon`, `read_svg`, `read_pdf` (Tasks 2–3); `render` (Task 1).
- Produces: nothing later tasks import.

- [ ] **Step 1: Write the Excellon check — the one that carries full weight**

```python
"""Layer 3: what each codec wrote, against what it was handed.

Excellon has no owned intermediate -- the emitter is the codec -- so its
check runs to the model and carries full weight. The rest check a codec
alone, because layer 2 has already checked the representation it was given.
"""

from __future__ import annotations

import json

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from stompdrill.emitters.drawing_svg import DrawingOptions, DrawingSvgEmitter
from stompdrill.emitters.excellon import ExcellonEmitter, ExcellonOptions
from stompdrill.emitters.json_out import JsonEmitter
from stompmodel.codec import from_document
from stompmodel.model import DrillData, Origin, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data
from tests.recovery.excellon import read_excellon
from tests.recovery.pdf import read_pdf
from tests.recovery.svg import read_svg

__all__: list[str] = []

#: Excellon states three decimals of a millimetre by default.
EXCELLON_QUANTUM_NM = 1_000

#: ``drawing_pdf._num`` states four.
PDF_QUANTUM_NM = 100


def quantised(value: int, quantum: int) -> int:
    """Round a canonical nanometre the way one format rounds it.

    Comparison is then exact. No epsilon: an epsilon would let a real
    off-by-one hide inside a tolerance nobody chose on purpose.
    """
    return round(value / quantum) * quantum


def panel() -> DrillData:
    """Two tools, four holes, numbered out of tuple order.

    The scrambled numbering is load-bearing: an emitter that recomputed a
    drill number from a list position would agree with a fixture numbered
    ascending and disagree with this one.
    """
    return make_data(
        at(-20_000_000, 18_000_000, 7_000_000, index=3),
        at(20_000_000, 18_000_000, 7_000_000, index=4),
        at(-19_000_000, -18_750_000, 5_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    )


# ---------------------------------------------------------------------------
# Excellon: straight to the model, because there is nothing in between
# ---------------------------------------------------------------------------


def expected_hits(data: DrillData) -> list[tuple[int, int, int, int]]:
    """``(number, tool, x, y)`` in the lower-left frame, at Excellon's precision.

    ``with_origin`` is a model operation, so this expectation owes nothing to
    the emitter. Nothing here calls ``format_nm``: building the expected
    string with the writer's own formatter would let a wrong formatter cancel
    itself out.
    """
    framed = data.with_origin(Origin.LOWER_LEFT)
    tools = framed.tools()
    return [
        (
            index,
            tools[hole.diameter_nm],
            quantised(hole.x_nm, EXCELLON_QUANTUM_NM),
            quantised(hole.y_nm, EXCELLON_QUANTUM_NM),
        )
        for index, hole in framed.numbered()
    ]


def test_the_excellon_file_states_every_hole_the_model_holds():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert len(recovered.circles) == len(data.holes)


def test_the_excellon_file_states_each_hole_at_the_position_the_model_holds():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [(c.x_nm, c.y_nm) for c in recovered.circles] == [
        (x, y) for _, _, x, y in expected_hits(data)
    ]


def test_the_excellon_file_assigns_each_hole_the_tool_the_model_assigned():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [c.tool for c in recovered.circles] == [tool for _, tool, _, _ in expected_hits(data)]


def test_the_excellon_file_drills_in_the_order_the_model_numbered():
    """File position is the format's only statement of sequence, so this is
    where ``RouteHoles``' numbering reaches the machine."""
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert [c.number for c in recovered.circles] == [n for n, _, _, _ in expected_hits(data)]


def test_the_excellon_file_states_each_tools_diameter():
    data = panel()

    recovered = read_excellon(ExcellonEmitter().emit(data))

    assert {c.diameter_nm for c in recovered.circles} == {5_000_000, 7_000_000}


def test_each_tool_occupies_one_contiguous_block_in_the_file():
    """CLAUDE.md's invariant, read off the artefact rather than the model.

    ``groupby`` collapses each run of one tool to a single entry, so a tool
    appearing in two separate runs shows up twice and the comparison with the
    sorted distinct set fails.
    """
    data = panel()

    sequence = [c.tool for c in read_excellon(ExcellonEmitter().emit(data)).circles]

    assert [tool for tool, _ in groupby(sequence)] == sorted(set(sequence))


def test_a_finer_precision_reaches_the_file_rather_than_being_rounded_away():
    """The quantum above is Excellon's default, not a property of the format.
    Raising it must change what the file states, or the comparison is testing
    a constant rather than the emitter."""
    data = make_data(
        at(1_234_567, 0, 5_000_000, index=1),
        reference=ReferenceOutline(Nanometre(100_000_000), Nanometre(50_000_000)),
    )

    coarse = read_excellon(ExcellonEmitter(ExcellonOptions(decimals=3)).emit(data))
    fine = read_excellon(ExcellonEmitter(ExcellonOptions(decimals=6)).emit(data))

    assert coarse.circles[0].x_nm != fine.circles[0].x_nm
```

`from itertools import groupby` goes in the module's import block with the rest.

- [ ] **Step 2: Write the drawing checks — bytes against the scene**

```python
# ---------------------------------------------------------------------------
# the drawings: one scene, two codecs
# ---------------------------------------------------------------------------


def scene_of(data: DrillData):
    """The scene the SVG backend would build, resolved once and shared."""
    emitter = DrawingSvgEmitter(DrawingOptions(title="LAYER 3"))
    return build_scene(emitter.layout(data), data, SheetText(title="LAYER 3"))


def sheet_nm(value: float, quantum: int) -> int:
    """A scene millimetre as nanometres, at one format's stated precision.

    ``Decimal(repr(x))`` rather than ``x * 1e6``: ``repr`` gives the shortest
    decimal that round-trips to the float, which is the value ``_fmt`` and
    ``_num`` then format. Multiplying the float directly would reintroduce
    exactly the noise ``Decimal`` is here to remove.
    """
    return round(Decimal(repr(value)) * 1_000_000 / quantum) * quantum


def scene_circles(scene, quantum: int = 1) -> list[tuple[int, int, int]]:
    """Every circle the scene states, in sheet nanometres, sorted."""
    found: list[tuple[int, int, int]] = []

    def walk(item) -> None:
        if isinstance(item, Group):
            for child in item.items:
                walk(child)
        elif isinstance(item, Circle):
            found.append(
                (
                    sheet_nm(item.cx, quantum),
                    sheet_nm(item.cy, quantum),
                    sheet_nm(2 * item.r, quantum),
                )
            )

    for item in scene.items:
        walk(item)
    return sorted(found)
```

`Circle`, `Group` and `Decimal` go in the module's import block, not inside the function. The
`quantum` parameter is what makes one helper serve both backends: SVG states one nanometre and
passes the default, PDF states a hundred and passes `PDF_QUANTUM_NM`, and the recovered side is
already rounded the same way by `read_pdf`.

```python
def test_the_svg_states_every_circle_the_scene_holds():
    data = panel()
    scene = scene_of(data)

    recovered = read_svg(DrawingSvgEmitter(DrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert len(recovered.circles) == len(scene_circles(scene))


def test_the_svg_places_each_circle_where_the_scene_put_it():
    """``_render_item`` copies cx, cy and r straight through, so this is a
    check that the copy is faithful rather than that a transform is right."""
    data = panel()
    scene = scene_of(data)

    recovered = read_svg(DrawingSvgEmitter(DrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert sorted((c.x_nm, c.y_nm, c.diameter_nm) for c in recovered.circles) == scene_circles(scene)


def test_the_pdf_places_each_circle_where_the_scene_put_it():
    """The load-bearing one. Between the scene and these bytes sit a frame
    flip, a points matrix and a four-Bezier circle, and no other test reaches
    all three."""
    data = panel()
    scene = scene_of(data)

    recovered = read_pdf(DrawingPdfEmitter(PdfDrawingOptions(title="LAYER 3")).render(scene, "L3"))

    assert sorted(
        (c.x_nm, c.y_nm, c.diameter_nm) for c in recovered.circles
    ) == scene_circles(scene, PDF_QUANTUM_NM)


def test_both_codecs_state_the_same_outline_extent():
    """T4 at the byte level. The load-bearing form of this claim is at layer 2,
    between owned representations; this is the cheap confirmation that the two
    codecs did not diverge below it."""
    data = panel()
    scene = scene_of(data)

    from_svg = read_svg(DrawingSvgEmitter().render(scene, "L3")).outline_nm
    from_pdf = read_pdf(DrawingPdfEmitter().render(scene, "L3")).outline_nm

    assert from_svg is not None, "the SVG stated no outline at all"
    assert from_pdf == tuple(quantised(v, PDF_QUANTUM_NM) for v in from_svg)
```

- [ ] **Step 3: Write the JSON round trip**

The codec is `json.dumps`, which the project did not write and trusts. What is worth checking
is that our own reader recovers our own writer's output through it.

```python
def test_the_json_bytes_rebuild_the_model_they_were_written_from():
    data = panel()

    rebuilt = from_document(json.loads(JsonEmitter().emit(data)))

    assert rebuilt == data


def test_the_json_bytes_preserve_a_drill_number_that_is_not_a_list_position():
    data = panel()

    rebuilt = from_document(json.loads(JsonEmitter().emit(data)))

    assert [hole.index for hole in rebuilt.holes] == [3, 4, 1, 2]
```

- [ ] **Step 4: Write the STEP face interrogation**

The only new work on the STEP side. `read_step` returns placed solids; hole geometry needs
faces on top. Cut cylinders are found by difference — the enclosure has cylindrical faces of
its own (bosses, fillets), so the set that appears between before and after **is** the holes.
That sidesteps having to classify a cylinder as a hole, which nothing in the geometry says.

```python
@pytest.mark.hammond
def test_every_hole_appears_as_a_cylinder_the_uncut_model_did_not_have(tmp_path):
    """``read_step`` returns placed solids, so the holes are recovered by
    interrogating faces. Taking the difference against the uncut model avoids
    having to decide which of the enclosure's own cylinders is a hole."""
    pytest.importorskip("OCP", reason="needs stompdrill[step]")

    from stompdrill.cad.step import read_step
    from tests.hammond import require_model

    ...
```

Write the body against the existing patterns in `packages/stompdrill/tests/test_step_cut.py`,
which already does before-and-after comparison over `read_step(...).solids` for volume and for
bounding box; `_model_path()` and `require_model` are its helpers. The face walk is:

```python
def cylinders(shape) -> set[tuple[int, int, int, int]]:
    """Every cylindrical face's axis point and radius, in nanometres.

    Rounded to the kernel's own confusion so two runs of one geometry agree;
    this is the single epsilon the whole verification design admits.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.Precision import Precision
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    tolerance_mm = Precision.Confusion_s()
    found: set[tuple[int, int, int, int]] = set()
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        surface = BRepAdaptor_Surface(explorer.Current())
        if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis().Location()
            found.add(
                tuple(
                    round(v / tolerance_mm)
                    for v in (axis.X(), axis.Y(), axis.Z(), cylinder.Radius())
                )
            )
        explorer.Next()
    return found
```

Assert that `len(cylinders(after) - cylinders(before))` equals the number of holes drilled, and
that the recovered radii match the model's diameters halved. Two assertions, each failing
independently: a count that is right with wrong radii, and radii that are right with a wrong
count, are different defects.

If the OCP symbol names above prove wrong for the pinned `cadquery-ocp==7.9.3.1.1`, resolve
them against the installed package and record what you changed — the shape of the check is the
requirement, the exact import path is not.

- [ ] **Step 5: Prove each check fails when its codec is wrong**

Adversarial verification, one mutant per format, loaded as a pytest plugin from **outside** the
repository. Never edit tracked source.

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/layer3-mutants"; rm -rf "$W"; mkdir -p "$W"

cat > "$W/flipy.py" <<'PY'
"""Break the PDF's frame flip: return the value unflipped."""
from stompdrill.emitters import drawing_pdf
drawing_pdf._y = lambda sheet, value: value
PY

cat > "$W/shift.py" <<'PY'
"""Break Excellon's lower-left reframing by one micron in X."""
from stompdrill.emitters.excellon import ExcellonEmitter
_real = ExcellonEmitter._value
ExcellonEmitter._value = lambda self, nm: _real(self, type(nm)(int(nm) + 1_000))
PY

for mutant in flipy shift; do
  echo "--- $mutant ---"
  PYTHONPATH="$W" .venv/bin/python -m pytest -p "$mutant" -o addopts= \
    packages/stompdrill/tests/test_layer3_codecs.py -q 2>&1 | tail -3
done
rm -rf "$W"
```

Expected: `flipy` fails `test_the_pdf_places_each_circle_where_the_scene_put_it` and
`shift` fails the Excellon position and contiguity checks. **If a mutant passes, the check it
was aimed at is not checking what it claims** — say so in your report and fix the check, do not
weaken the mutant. Quote both outputs.

- [ ] **Step 6: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Check each codec against the representation it was handed"
```

---

### Task 5: Layer 2 — the owned representations against the model, and T4

The load-bearing addition, and it follows from the distinction the audits did not have: **the
project owns everything up to the codec, and codecs it did not write are trusted by design.**
These are Python values, so comparison is exact and needs no parser — and **cross-artefact
agreement is established here**, between owned representations, rather than by parsing
artefacts back and hoping two parsers were both right.

| Emitter | Owned representation | Reached by |
| --- | --- | --- |
| JSON | the document mapping | `to_document(data)` |
| SVG | the `Scene` | `build_scene(emitter.layout(data), data, text)` |
| PDF | the `Scene` | the same, over its own layout |
| STEP | the cut shape | `cut_shape(model, data)` |
| Excellon | **none** — the emitter is the codec | checked at layer 3 instead |

**On epsilons.** The no-epsilon rule governs the *readback*, where an artefact states a decimal
and a `Decimal` parse can be exact. A `Scene` coordinate is a float the layout computed, and
comparing a float to a float is a different question. `pytest.approx` is correct here, with the
tolerance stated in the test's own docstring. Do not carry an approx into layer 3.

**Files:**
- Create: `packages/stompdrill/tests/test_layer2_owned.py`

**Interfaces:**
- Consumes: `build_scene`, `to_document`, `cut_shape`, `Layout.scale`.
- Produces: nothing later tasks import.

- [ ] **Step 1: Write the scene-against-model checks**

The scene is in sheet millimetres and the model in canonical nanometres, so the comparison
needs a datum and a scale. Both come from things already public or already stated:

- the **datum** is the scene's own `origin`-class circle, which `build.py` draws at the
  canonical origin and nowhere else;
- the **scale** is `layout.scale`, a public attribute of a public method's return value.

Nothing here reaches into the build's private helpers, and nothing assumes a placement: a
uniform offset of the whole panel on the sheet is a layout decision, and the datum absorbs it
by construction.

```python
"""Layer 2: what each emitter owns, against the model it was given.

Python values, so comparison needs no parser -- and cross-artefact agreement
(T4) is established here, between representations this project wrote, not by
parsing two artefacts back and trusting both readers at once.
"""

from __future__ import annotations

import pytest

from stompdrill.emitters.drawing.build import SheetText, build_scene
from stompdrill.emitters.drawing.scene import Circle, Group, Scene
from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter
from stompdrill.emitters.drawing_svg import DrawingSvgEmitter
from stompmodel.codec import to_document
from stompmodel.model import DrillData, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data

__all__: list[str] = []

#: A hundredth of a sheet millimetre. Far finer than any plotter resolves and
#: far coarser than the layout's own float noise, which is ~1e-12.
SHEET_TOLERANCE_MM = 1e-5


def panel() -> DrillData:
    """The same four holes every layer checks, numbered out of tuple order."""
    return make_data(
        at(-20_000_000, 18_000_000, 7_000_000, index=3),
        at(20_000_000, 18_000_000, 7_000_000, index=4),
        at(-19_000_000, -18_750_000, 5_000_000, index=1),
        at(19_000_000, -18_750_000, 5_000_000, index=2),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
    )


def circles(scene: Scene, token: str) -> list[Circle]:
    """Every circle carrying ``token`` in its class, wherever a group nests it."""
    found: list[Circle] = []

    def walk(item) -> None:
        if isinstance(item, Group):
            for child in item.items:
                walk(child)
        elif isinstance(item, Circle) and token in item.cls.split():
            found.append(item)

    for item in scene.items:
        walk(item)
    return found


def datum(scene: Scene) -> tuple[float, float]:
    """The sheet point the canonical origin sits at.

    ``build`` draws exactly one ``origin``-class circle and draws it there,
    so the scene states its own datum and the comparison need not assume a
    placement.
    """
    marks = circles(scene, "origin")
    assert len(marks) == 1, f"expected one origin mark, found {len(marks)}"
    return marks[0].cx, marks[0].cy


def scenes(data: DrillData) -> dict[str, tuple[Scene, float]]:
    """Each drawing backend's owned representation, with its own scale.

    The two solve for different unknowns -- SVG fixes the sheet and fits the
    scale, PDF fixes the scale at 1:1 and walks the ISO 5457 candidates -- so
    they own two scenes, not one, and T4 has something to say.
    """
    built = {}
    for name, emitter in (("svg", DrawingSvgEmitter()), ("pdf", DrawingPdfEmitter())):
        layout = emitter.layout(data)
        built[name] = (build_scene(layout, data, SheetText(title="LAYER 2")), layout.scale)
    return built


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_draws_one_hole_mark_for_every_hole_in_the_model(backend):
    data = panel()

    scene, _ = scenes(data)[backend]

    assert len(circles(scene, "hole")) == len(data.holes)


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_places_every_hole_where_the_model_puts_it(backend):
    """One affine map, shared by every hole: the canonical Y-up frame scaled
    and flipped onto the sheet's Y-down one. A per-hole error, a transposed
    axis or a one-sided scale all break this; a uniform offset does not, and
    is a placement decision the datum absorbs."""
    data = panel()
    scene, scale = scenes(data)[backend]
    ox, oy = datum(scene)

    placed = sorted((c.cx, c.cy) for c in circles(scene, "hole"))
    expected = sorted(
        (ox + hole.x_nm / 1_000_000 * scale, oy - hole.y_nm / 1_000_000 * scale)
        for hole in data.holes
    )

    assert placed == pytest.approx(expected, abs=SHEET_TOLERANCE_MM)


@pytest.mark.parametrize("backend", ["svg", "pdf"])
def test_the_scene_draws_every_hole_at_the_models_diameter(backend):
    """Separate from position: a radius scaled by the wrong factor lands every
    mark correctly and still drills the wrong bit."""
    data = panel()
    scene, scale = scenes(data)[backend]

    drawn = sorted(2 * c.r for c in circles(scene, "hole"))
    expected = sorted(hole.diameter_nm / 1_000_000 * scale for hole in data.holes)

    assert drawn == pytest.approx(expected, abs=SHEET_TOLERANCE_MM)


def test_the_pdf_scene_is_drawn_at_one_to_one():
    """The PDF solves for the sheet, so its scale is fixed. If this ever fails
    the two backends have stopped differing in the way the design says."""
    assert scenes(panel())["pdf"][1] == 1.0
```

- [ ] **Step 2: Write the document-against-model check**

```python
def test_the_document_states_every_hole_the_model_holds_in_canonical_units():
    """The JSON emitter's owned representation is this mapping; ``json.dumps``
    below it is stdlib and trusted."""
    data = panel()

    document = to_document(data)

    assert [(h["x_nm"], h["y_nm"], h["diameter_nm"]) for h in document["holes"]] == [
        (hole.x_nm, hole.y_nm, hole.diameter_nm) for hole in data.holes
    ]


def test_the_document_states_the_tool_the_model_assigned_each_diameter():
    data = panel()

    document = to_document(data)

    assert {t["diameter_nm"]: t["number"] for t in document["tools"]} == dict(data.tools())
```

- [ ] **Step 3: Write the T4 cross-artefact check**

Project every owned representation back to canonical nanometres using only its own declared
frame, then demand the projections are equal. This is the claim ADR-0001 rests artefact
consistency on, stated once and checked between values rather than between files.

```python
def projected(scene: Scene, scale: float) -> list[tuple[int, int, int]]:
    """A scene's holes in canonical nanometres, through its own frame alone."""
    ox, oy = datum(scene)
    return sorted(
        (
            round((c.cx - ox) / scale * 1_000_000),
            round(-(c.cy - oy) / scale * 1_000_000),
            round(2 * c.r / scale * 1_000_000),
        )
        for c in circles(scene, "hole")
    )


def test_every_owned_representation_agrees_about_the_same_holes():
    """T4. Three representations, three different frames, one geometry.

    Established between values this project owns rather than by parsing two
    artefacts back: a comparison of two parsers' output is only as good as
    the weaker parser, and this one has no parser in it at all.
    """
    data = panel()
    built = scenes(data)

    from_model = sorted((h.x_nm, h.y_nm, h.diameter_nm) for h in data.holes)
    from_document = sorted(
        (h["x_nm"], h["y_nm"], h["diameter_nm"]) for h in to_document(data)["holes"]
    )

    assert from_document == from_model
    assert projected(*built["svg"]) == from_model
    assert projected(*built["pdf"]) == from_model
```

Three separate assertions, not one chained comparison: each names a different representation,
and a chained `a == b == c` reports only the first pair that fails.

- [ ] **Step 4: Add the STEP arm, behind `--hammond`**

`cut_shape(model, data)` is already public and already exercised by `test_step_cut.py` for
volume and bounding box. Add one test asserting that the cut shape's new cylinders sit at the
model's hole positions in canonical nanometres, reusing the `cylinders()` walk Task 4 wrote.
Mark it `@pytest.mark.hammond` and guard it with `pytest.importorskip("OCP")`, as every other
kernel test does. Coverage for `cad/` and `emitters/step.py` is measured under `--hammond`, not
under the default run.

If Task 4's `cylinders()` helper is wanted in two modules, move it to
`packages/stompdrill/tests/hammond.py`, which already holds the kernel test support, rather
than importing one test module from another.

- [ ] **Step 5: Prove the checks fail when the layout is wrong**

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/layer2-mutants"; rm -rf "$W"; mkdir -p "$W"

cat > "$W/swapxy.py" <<'PY'
"""Transpose the model-to-sheet mapping: the characteristic geometry bug."""
from stompdrill.emitters.drawing import build
_real = build.Circle
build.Circle = lambda cx, cy, r, stroke, fill="none", cls="": _real(
    cy, cx, r, stroke, fill=fill, cls=cls
) if "hole" in cls.split() else _real(cx, cy, r, stroke, fill=fill, cls=cls)
PY

PYTHONPATH="$W" .venv/bin/python -m pytest -p swapxy -o addopts= \
  packages/stompdrill/tests/test_layer2_owned.py -q 2>&1 | tail -4
rm -rf "$W"
```

Expected: `test_the_scene_places_every_hole_where_the_model_puts_it` fails for both backends,
and the T4 test fails. `test_the_scene_draws_every_hole_at_the_models_diameter` should still
pass — a transposition does not change a radius, and a diameter check that failed here would be
coupled to position rather than independent of it. Report both halves of that expectation.

If `build.Circle` is not the name the module binds, find the construction site and patch
whatever it is; the mutant's job is to transpose one axis of the hole marks and nothing else.

- [ ] **Step 6: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Compare what each emitter owns against the model, and to each other"
```

---

### Task 6: Layer 1 — determinism, denotational invariance, and the golden

`P` produces `DrillData`. Layer 1 is the only layer that says anything about `P` itself.

**Determinism (T1) is two emissions in fresh processes compared as bytes.** In one process a
dict or set iterating in insertion order will look deterministic whether or not the code
depends on that order; across processes with different hash seeds it will not. Nothing in the
suite currently crosses a process boundary, so this is a claim the repository has never checked.

**Denotational invariance (T1′) is the same, over inputs transformed within their equivalence
class.** `test_invariant.py` checks permutation within one process; Task 9 makes it generative.
This task adds the across-process arm.

**One committed golden guards against drift in `P`.** It is a **fact-set of the model, not
bytes of an artefact**, and that is a deliberate correction to `kinds.md` Gap 4, which proposed
three byte-goldens. The spec's reason: the panel path is provenance in four of five artefacts
and the STEP writer appends a volatile counter, so a byte-golden fails on legitimate change.
With T2 holding per format, a golden per artefact is redundant anyway — one file, and updating
it is a reviewable diff.

**Files:**
- Create: `packages/stompdrill/tests/test_layer1_model.py`
- Create: `packages/stompdrill/tests/golden/tar-1590b.json`

**Interfaces:**
- Consumes: the CLI, `AiPdfSource`, `quantise`, `build_pipeline`.
- Produces: `fact_set(data) -> dict[str, object]`, imported by no other task but named here
  because the golden file's shape is its output and the two must not drift.

- [ ] **Step 1: Write the fresh-process determinism check**

```python
"""Layer 1: the model itself -- reproducible, order-blind, and pinned.

Two emissions in fresh processes rather than two calls in one: within a
process an insertion-ordered dict looks deterministic whether or not the
code depends on it, and a differing hash seed is what tells the two apart.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

__all__: list[str] = []

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden" / "tar-1590b.json"

#: Two seeds that differ, so set and dict iteration differ between the runs.
SEEDS = ("0", "12345")

FORMATS = ("excellon", "json", "drawing-svg", "drawing-pdf")


def emit_in_a_fresh_process(destination: Path, seed: str, panel: str, case: str) -> dict[str, bytes]:
    """Run the CLI in a subprocess under ``seed`` and return what it wrote."""
    targets = {name: destination / f"{name}.out" for name in FORMATS}
    environment = dict(os.environ, PYTHONHASHSEED=seed)
    arguments = [sys.executable, "-m", "stompdrill.cli", str(FIXTURES / panel), "--case", case]
    for name, path in targets.items():
        arguments += ["--emit", f"{name}={path}"]

    completed = subprocess.run(arguments, env=environment, capture_output=True, check=False)
    assert completed.returncode in (0, 1), completed.stderr.decode()
    return {name: path.read_bytes() for name, path in targets.items()}


@pytest.mark.parametrize("panel,case", [("tar.ai", "1590B"), ("pax.ai", "1590BB")])
def test_two_fresh_processes_emit_identical_bytes(tmp_path, panel, case):
    """T1. A hash seed reaching an artefact is the failure this catches, and
    no single-process comparison can see it."""
    first = emit_in_a_fresh_process(tmp_path / "a", SEEDS[0], panel, case)
    second = emit_in_a_fresh_process(tmp_path / "b", SEEDS[1], panel, case)

    assert first == second
```

`emit_in_a_fresh_process` needs its destination directory to exist; create it before the
subprocess runs. The two `tmp_path` subdirectories keep the runs from overwriting each other,
which would make the comparison trivially true.

- [ ] **Step 2: Add the across-process invariance arm**

```python
def test_a_permuted_panel_emits_identical_bytes_from_a_fresh_process(tmp_path):
    """T1'. ``test_invariant.py`` shuffles within one process; this crosses a
    process boundary as well, so an order dependency that only surfaces under
    a different hash seed cannot hide behind the in-process check."""
```

The fixture files cannot be permuted from outside, so drive this arm through a small script the
subprocess runs, rather than through the console script: read `tar.ai` with `AiPdfSource`,
shuffle `raw.holes` with a seed passed in `argv`, quantise, run `build_pipeline`, emit `json`,
and print it. Compare two subprocesses with different shuffles **and** different
`PYTHONHASHSEED`. Write that script into `tmp_path` from the test; it is a fixture of the test,
not a tracked file.

- [ ] **Step 3: Write the fact-set projection and the golden test**

```python
def fact_set(data) -> dict[str, object]:
    """Everything about a model a change should have to justify.

    Geometry, findings and provenance of process -- but not ``source.path``,
    which is the working directory rather than a fact about the panel, and
    the one value that would make this file fail on a legitimate change.
    """
    return {
        "outline_nm": None if data.reference is None
        else [data.reference.width_nm, data.reference.height_nm],
        "enclosure": None if data.enclosure is None
        else {
            "family": data.enclosure.family,
            "candidates": list(data.enclosure.candidates),
            "rotated": data.enclosure.rotated,
            "selected_part": data.enclosure.selected_part,
        },
        "layers": {
            "drill": data.source.drill_layer,
            "reference": data.source.reference_layer,
            "found": list(data.source.layers_found),
        },
        "tools": [[diameter_nm, number] for diameter_nm, number in data.tools().items()],
        "holes": [
            {"index": index, "x_nm": hole.x_nm, "y_nm": hole.y_nm,
             "diameter_nm": hole.diameter_nm}
            for index, hole in data.numbered()
        ],
        "diagnostics": [
            {"code": d.code, "severity": d.severity.name,
             "location_nm": None if d.location_nm is None else list(d.location_nm)}
            for d in data.diagnostics
        ],
        "processing": [
            {"name": run.name, "parameters": [list(p) for p in run.parameters]}
            for run in data.processing
        ],
    }


def test_the_model_still_states_the_facts_the_golden_records():
    """One golden, of the model. With T2 holding per format a golden per
    artefact is redundant, and a byte-golden would fail on a legitimate
    change: the panel path is provenance in four of five artefacts and the
    STEP writer appends a volatile counter.
    """
    current = fact_set(shipped_model("tar.ai", "1590B"))

    if os.environ.get("STOMPDRILL_UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    assert current == json.loads(GOLDEN.read_text(encoding="utf-8")), (
        "the model's facts changed. If the change is intended, regenerate with:\n"
        "  STOMPDRILL_UPDATE_GOLDEN=1 .venv/bin/python -m pytest -o addopts= "
        "packages/stompdrill/tests/test_layer1_model.py -k golden\n"
        "and review the diff -- a change that moves one number is a bug, a "
        "change that moves the whole file is the intended edit."
    )
```

`shipped_model(panel, case)` reads the fixture with `AiPdfSource`, quantises with the same
three quantisers `test_invariant.py` uses, and folds `build_pipeline(build_parser().parse_args([...]))`
over it — read from the CLI, never hand-copied, for the reason `test_invariant.shipped_pipeline`
already records: a copied stage list drifts the moment a stage is inserted.

- [ ] **Step 4: Generate the golden and read it before committing it**

```bash
cd /Users/thelyx/repo/stompcad
mkdir -p packages/stompdrill/tests/golden
STOMPDRILL_UPDATE_GOLDEN=1 .venv/bin/python -m pytest -o addopts= \
  packages/stompdrill/tests/test_layer1_model.py -k golden -q 2>&1 | tail -3
cat packages/stompdrill/tests/golden/tar-1590b.json
```

**Read the file.** It is about to become the thing every future change is judged against, so a
wrong value committed here is a wrong value defended for as long as the file lives. Check
against what CLAUDE.md already states about this fixture: `tar.ai` is `112.40 × 60.50`, needs
`--case 1590B`, and holds seven holes over two diameters with one duplicate pair. If the golden
disagrees with any of that, stop and investigate before committing.

- [ ] **Step 5: Prove the golden fires**

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/golden-mutant"; rm -rf "$W"; mkdir -p "$W"
cat > "$W/offby.py" <<'PY'
"""Move one hole by a micron, the smallest change a golden should catch."""
from stompdrill.pipeline.snap import SnapPositions
_real = SnapPositions.quantise
def shifted(self, raw):
    (x, y), diagnostics = _real(self, raw)
    return (type(x)(int(x) + 1_000), y), diagnostics
SnapPositions.quantise = shifted
PY
PYTHONPATH="$W" .venv/bin/python -m pytest -p offby -o addopts= \
  packages/stompdrill/tests/test_layer1_model.py -k golden -q 2>&1 | tail -4
rm -rf "$W"
```

Expected: a failure naming the regeneration command. Confirm the mutant did **not** rewrite the
tracked golden — `git status --porcelain -uall` must be clean for that path, because
`STOMPDRILL_UPDATE_GOLDEN` was unset. If the golden moved, the update path is armed by default
and that is a defect: a golden that rewrites itself checks nothing.

- [ ] **Step 6: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Pin the model, and prove two fresh processes agree"
```

---

### Task 7: End to end — the console script, the entry point, and both `py.typed`

`cli.main([...])` cannot see any of it. The console script, the entry point, `py.typed` in both
distributions, the `stompdrill → stompmodel` dependency and the workspace source edge are all
untested, and this is the only assertion in the repository that would survive
`[project.scripts]` being deleted. It breaks the user rather than the part, which is a different
risk, not a smaller one.

**Files:**
- Create: `packages/stompdrill/tests/test_packaging.py`

**Interfaces:**
- Consumes: the installed distributions, not the source tree.
- Produces: nothing.

- [ ] **Step 1: Write the three checks**

```python
"""What the branch ships, exercised the way a user reaches it.

Every assertion here reads the *installed* distribution rather than the
source tree: a source-tree glob would pass with ``[project.scripts]`` or
``[tool.setuptools.package-data]`` deleted, which is the whole failure this
file exists to notice.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import subprocess
import sys
from pathlib import Path

import pytest

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

#: Resolved beside the interpreter running the suite, not through PATH, so the
#: test does not depend on an activated virtualenv.
SCRIPT = Path(sys.executable).parent / "stompdrill"


@pytest.mark.skipif(not SCRIPT.exists(), reason="stompdrill is not installed as a script")
def test_the_console_script_drills_a_panel(tmp_path):
    """The one end-to-end assertion: the name a user types, the file it writes."""
    document = tmp_path / "panel.json"

    completed = subprocess.run(
        [str(SCRIPT), str(FIXTURE), "--case", "1590B", "--emit", f"json={document}"],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1, completed.stderr.decode()
    assert len(json.loads(document.read_text(encoding="utf-8"))["holes"]) == 7


def test_the_entry_point_names_the_callable_the_script_runs():
    """A script that exists but points somewhere else is a different defect
    from a script that is missing, so it gets its own assertion."""
    scripts = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
    }

    assert scripts.get("stompdrill") == "stompdrill.cli:main"


@pytest.mark.parametrize("distribution", ["stompdrill", "stompmodel"])
def test_the_installed_package_carries_its_typing_marker(distribution):
    """PEP 561: without this marker a downstream type checker discards every
    annotation in the distribution. Read from the installed package, because
    that is where ``package-data`` either worked or did not."""
    assert importlib.resources.files(distribution).joinpath("py.typed").is_file()
```

The exit code is **1**, not 0: `tar.ai` raises one `duplicate-hole` warning, and warnings reach
exit 1 by the command-line contract. Assert the value, not merely that it is non-zero — the
contract is that each code means one thing.

- [ ] **Step 2: Run them, and confirm the script test is not silently skipping**

```bash
cd /Users/thelyx/repo/stompcad
ls -l .venv/bin/stompdrill
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_packaging.py -q -rs 2>&1 | tail -5
```

`-rs` reports skips. If `test_the_console_script_drills_a_panel` skipped, the `skipif` guard is
hiding a real absence — a skipped test proves nothing, and this one has exactly one job. Resolve
the install before continuing.

- [ ] **Step 3: Prove the entry-point test fails without the entry point**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python - <<'PY'
import importlib.metadata as m
found = {e.name: e.value for e in m.entry_points(group="console_scripts")}
print("stompdrill ->", found.get("stompdrill"))
print("would fail if absent:", found.get("stompdrill") != "stompdrill.cli:main")
PY
```

Expected: `stompdrill -> stompdrill.cli:main` and `would fail if absent: False`. That confirms
the assertion is reading the real metadata rather than a name it invented. A stronger proof
would uninstall the distribution, which is not worth breaking the environment for; say in your
report that this is the weaker demonstration and why.

- [ ] **Step 4: Record the fourth check as deliberately not built**

`kinds.md` Gap 3 names a fourth: `pip install packages/stompmodel` into a throwaway venv, the
sentence the root `pyproject.toml` calls ADR-0008's governing test. It needs the network and
tens of seconds, so it belongs behind an opt-in marker rather than in the default tier. Task 13
records it in `docs/BACKLOG.md`. Do not build it here.

- [ ] **Step 5: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Exercise what the branch ships, not only what it imports"
```

---

### Task 8: The nine contract-coverage gaps, as acceptance tests

`contracts.md` found nine claims the command-line contract makes that no test drives end to
end. All nine were re-verified as still open while this plan was written; none was closed by
plans 1 or 2. The spec's §5 default tier names an acceptance tier, so this is the task that
makes that tier exist.

**Ruling recorded here because the spec does not make it.** §4 disposes of these as
"acceptance tests" but §7's plan table assigns them to no plan. Plans 1 and 2 are landed and
carried neither. This plan takes them, on the user's decision, and Task 13 amends §7 so the
spec stops describing a tier nothing builds.

| # | Claim | Where it currently fails to be checked |
| --- | --- | --- |
| 1 | `--drill-layer` and `--reference-layer` reach the source | never passed on a command line in any test |
| 2 | `hole-obstructed` reaches exit 2 | only `hole-through-boss` is driven to exit 2 |
| 3 | `wrong-case-model` reaches exit 2 | the code exists; no test runs it through `main` |
| 4 | `unverifiable-enclosure` reaches exit 2 | the diagnostic is built; no exit code is asserted |
| 5 | an error run withholds `drawing-svg` | asserted for `drawing-pdf`, `excellon` and `step` only |
| 6 | STEP refuses unrouted data | the refusal exists; nothing calls it |
| 7 | A1 is selected when A2 will not hold the panel | `ISO_5457_CANDIDATES` names A1; nothing chooses it |
| 8 | `W*` establishes a clip, not geometry | `W` is tested at `test_ai_pdf.py:226`; `W*` is not |
| 9 | every flag resolves before the input file is opened | tested for `--grid` alone |
| 10 | the case model is parsed once, however many consumers need it | nothing counts the parses |

Ten rows for nine bullets: the spec's second bullet names two codes, and each is a separate
reachability claim with a separate failure mode.

**Files:**
- Create: `packages/stompdrill/tests/test_acceptance.py`

**Interfaces:**
- Consumes: `cli.main`, `tests.conftest.build_pdf`, `tests.conftest.FakeCase`, `circle_ops`.
- Produces: nothing.

- [ ] **Step 1: Measure what is already there, before adding**

```bash
cd /Users/thelyx/repo/stompcad
for token in -- "--drill-layer" "hole-obstructed" "wrong-case-model" \
             "unverifiable-enclosure" '"A1"' 'W\*'; do
  [ "$token" = "--" ] && continue
  printf '%-26s %s\n' "$token" "$(grep -rn -- "$token" packages/stompdrill/tests --include='*.py' | wc -l)"
done
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -1
```

Record both. If any token already has a hit that is a real end-to-end check rather than a
mention, that row is closed and you write nothing for it — say which in your report.

- [ ] **Step 2: Rows 1, 8 and 9 — the source and the flags**

```python
"""The command-line contract, driven end to end.

Every test here goes through ``cli.main`` and asserts an exit code, because
the codes are a contract: 0 clean, 1 warnings, 2 errors, 3 usage or IO.
A diagnostic that exists but reaches no exit code is a rule the operator
never meets.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stompdrill import cli
from tests.conftest import FakeCase, build_pdf, circle_ops

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"


def test_the_layer_flags_choose_which_layers_the_source_reads(tmp_path, capsys):
    """Both flags on one command line, against artwork whose layers are named
    nothing like the defaults. A default that happened to match would make a
    passing test say nothing."""
    panel = build_pdf(
        tmp_path / "panel.pdf",
        {
            "Cuts": circle_ops(50, 50, 3.5) + " " + circle_ops(80, 50, 3.5),
            "Card": "10 10 300 200 re S",
        },
    )

    code = cli.main([
        str(panel), "--drill-layer", "Cuts", "--reference-layer", "Card",
        "--emit", f"json={tmp_path / 'out.json'}",
    ])

    assert code in (0, 1), capsys.readouterr().out
    assert len(json.loads((tmp_path / "out.json").read_text())["holes"]) == 2


def test_naming_a_layer_that_is_not_there_is_a_usage_failure(tmp_path):
    """The other half: the flag is read, not ignored."""
    panel = build_pdf(tmp_path / "panel.pdf", {"Cuts": circle_ops(50, 50, 3.5)})

    assert cli.main([str(panel), "--drill-layer", "Nope"]) == 3


def test_an_even_odd_clip_is_not_geometry_either(tmp_path):
    """``W`` is covered at ``test_ai_pdf.py:226``. ``W*`` is the same rule with
    the other fill sense, and ``n`` -- not ``W`` -- is what makes a path
    invisible, so the two operators must be handled alike."""
    panel = build_pdf(
        tmp_path / "clips.pdf",
        {"Drill": "q 0 0 400 400 re W* n Q " + circle_ops(50, 50, 5)},
    )

    ...
```

Finish that last one against the pattern at `packages/stompdrill/tests/test_ai_pdf.py:237`
(`test_a_clip_only_layer_yields_nothing`), which is the `W` form of exactly this test: read the
source and assert one hole, the circle, with the clip rectangle absent.

For row 9, parametrise over every flag the contract says resolves before the file is opened,
against a path that does not exist:

```python
@pytest.mark.parametrize(
    "argv",
    [
        ["--drill-standard", "whitworth"],
        ["--drill-sizes", "3.2,3.33"],
        ["--grid", "nan"],
        ["--grid-warn", "nan"],
        ["--case", "1590ZZ"],
        ["--case-face", "sideways"],
        ["--emit", "no-such-format=/tmp/x"],
    ],
    ids=lambda a: a[0],
)
def test_every_resolvable_flag_is_judged_before_the_input_file_is_opened(argv, capsys):
    """A bad flag is a usage error whatever the panel is, so it must be
    reported without the file ever being read -- otherwise an operator with a
    typo in a flag is told about the file instead."""
    assert cli.main(["/no/such/panel.ai", *argv]) == 3

    assert "/no/such/panel.ai" not in capsys.readouterr().err
```

Check each flag's actual spelling and error text against `cli.build_parser` before committing
to the table; a parametrised case that exits 3 for the *wrong* reason passes and proves nothing.
Where the message legitimately does name the path, drop the second assertion for that case and
say so in a comment rather than deleting it for all of them.

- [ ] **Step 3: Rows 2, 3, 4 and 10 — the enclosure and clearance errors**

`FakeCase` already distinguishes the codes: `bosses=` rejects as `THROUGH_BOSS` and `behind=`
as `OBSTRUCTED`, so a test can aim at exactly one. It is a plain class, so a test may override
`footprint_nm` on an instance to provoke `wrong-case-model`.

The CLI builds its model in `build_case_model(args)` and stashes it on
`args.case_model_object`; monkeypatch `cli.build_case_model` to return the fake, which is the
same shape as the existing `monkeypatch.setattr(cli, "AiPdfSource", FakeSource)` at
`test_cli.py:180`.

```python
def test_an_obstructed_hole_reaches_exit_two_and_withholds_everything(tmp_path, monkeypatch):
    """``hole-through-boss`` is driven to exit 2 by the hammond suite;
    ``hole-obstructed`` is a different rule with a different cause and had
    never reached a code."""
    ...


def test_a_model_of_the_wrong_case_reaches_exit_two(tmp_path, monkeypatch):
    """The panel identifies one part and the supplied model is another. This
    gates an exit-2 error withholding every artefact, which is why
    ``_cross_check`` compares at exact nanometres."""
    ...


def test_a_declared_case_with_no_outline_to_check_it_against_reaches_exit_two(tmp_path):
    """``unverifiable-enclosure``. A declared case is always verified, so
    artwork with no reference outline cannot satisfy the declaration -- and
    silently proceeding would drill to an unchecked footprint."""
    panel = build_pdf(tmp_path / "panel.pdf", {"Drill": circle_ops(50, 50, 3.5)})

    assert cli.main([str(panel), "--case", "1590B"]) == 2


def test_the_case_model_is_parsed_once_however_many_consumers_want_it(tmp_path, monkeypatch):
    """The clearance stage and the STEP emitter both need it. Parsing twice
    is not only slow: two parses are two chances to disagree, and every
    artefact of one invocation must describe one geometry."""
    calls = []
    ...
    assert len(calls) == 1
```

Write each body against the existing patterns rather than inventing a new harness:
`test_cli.py:1616` is the model for an error run that withholds an artefact, and
`test_clearance.py` is the model for driving `FakeCase`. For row 10, wrap
`stompdrill.cad.load_case_model` with a counting proxy via `monkeypatch.setattr` and run a
command that requests both `--emit step=` and clearance checking.

- [ ] **Step 4: Rows 5, 6 and 7 — the emitters**

```python
def test_an_error_run_withholds_the_svg_like_every_other_artefact(tmp_path):
    """ADR-0001: any error withholds every requested artefact. Asserted for
    the PDF at ``test_cli.py:1617``; the SVG is a different emitter reached
    through a different branch, so it is a separate claim."""
    out = tmp_path / "panel.svg"

    # No --case, so tar.ai is ambiguous-enclosure, which is an error.
    code = cli.main([str(FIXTURE), "--emit", f"drawing-svg={out}"])

    assert code == 2
    assert not out.exists()


def test_the_step_emitter_refuses_data_that_was_never_routed():
    """Every other emitter's refusal is tested; this one's was not. A STEP
    file of unrouted data would cut real holes with no drill sequence behind
    them."""
    pytest.importorskip("OCP", reason="needs stompdrill[step]")
    ...
    with pytest.raises(EmitterError):
        StepEmitter(StepOptions(model=FakeCase())).emit(unrouted)


def test_a_panel_too_large_for_a2_is_drawn_on_a1(tmp_path):
    """ISO 5457 §4.1 fixes each size's orientation, so the only choice the
    emitter makes is which candidate. A1 sits between two sizes that are both
    chosen by existing tests, and was the one never reached."""
    ...
    assert emitter.layout(data).sheet.name == "A1"
```

For the A1 case, do not guess the dimensions. Derive them: A2 landscape is 594 × 420 mm and A1
is 841 × 594, so a panel wider than A2's drawable area and narrower than A1's selects A1.
Start from a 700 × 450 mm reference outline, print `emitter.layout(data).sheet.name`, and adjust
until it reads `A1`; then assert the *neighbours* too — the same panel grown must reach A0 and
shrunk must fall back to A2 — so the test pins a boundary rather than a single lucky value.

The STEP refusal is behind `pytest.importorskip("OCP")` but is **not** `@pytest.mark.hammond`:
it needs the kernel, not a downloaded model. Check which guard the neighbouring tests in
`test_step_emitter.py` use and match it.

- [ ] **Step 5: Prove each new test fails when its rule is removed**

Ten rows, ten rules. You do not need ten separate plugins — group them:

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/acceptance-mutants"; rm -rf "$W"; mkdir -p "$W"

cat > "$W/noclip.py" <<'PY'
"""Treat W* as geometry rather than as a clip."""
from stompdrill.sources import ai_pdf
# Narrow the clip operators to W alone, leaving W* to fall through as a path.
PY

cat > "$W/keepgoing.py" <<'PY'
"""Downgrade every ERROR diagnostic to a WARNING, so nothing withholds."""
from stompmodel.diagnostics import Diagnostic, Severity
_real = Diagnostic.error
Diagnostic.error = classmethod(
    lambda cls, code, message, **kw: cls(Severity.WARNING, code, message, **kw)
)
PY

for mutant in noclip keepgoing; do
  echo "--- $mutant ---"
  PYTHONPATH="$W" .venv/bin/python -m pytest -p "$mutant" -o addopts= \
    packages/stompdrill/tests/test_acceptance.py -q 2>&1 | tail -4
done
rm -rf "$W"
```

`keepgoing` must fail every exit-2 row (2, 3, 4, 5). `noclip` must fail row 8 and nothing else —
write its body to match how `ai_pdf` actually spells the clip check at `sources/ai_pdf.py:327`.
Any row you cannot demonstrate this way, say so plainly in your report and name the row. Do not
claim a demonstration you did not run.

- [ ] **Step 6: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Drive every contract claim through the command line"
```

---

### Task 9: The generative conversions

Four changes, and the rule that produced them: **generate where the answer set has a boundary
the author would not think to pick, and where the property is not a restatement of the
implementation.** Everything else stays an example. `kinds.md` §4 applies that rule in both
directions, and one of the four is a *deletion* — which is the part that needs an amendment to
`CLAUDE.md`, because CLAUDE.md currently names the test being deleted as one to preserve.

**Files:**
- Modify: `packages/stompdrill/pyproject.toml` — add `hypothesis` to the dev group
- Modify: `packages/stompdrill/tests/test_invariant.py`
- Modify: `packages/stompdrill/tests/test_snap.py`
- Modify: `packages/stompdrill/tests/test_pipeline.py`
- Modify: `packages/stompmodel/tests/test_codec.py`
- Modify: `CLAUDE.md` — the preserved-property-tests sentence

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Declare hypothesis for the member that is about to use it**

`packages/stompdrill/tests/` has never imported `hypothesis`; three of the four changes below
make it. The member's dev group is `["pytest"]` (or `["pytest", "pdfminer.six"]` after Task 3),
and ADR-0008's governing test is that the member passes its own tests alone. `stompmodel`
already declares `hypothesis` for exactly this reason. Extend the list and extend the comment
above it; re-sync from the repository root.

- [ ] **Step 2: The permutation invariant, generatively — the highest-value one**

The claim ADR-0006 rests the whole architecture on is currently checked against exactly three
hole sets: two real panels and one hand-built synthetic. The shuffling is already there; **what
is fixed is the hole set, and that is the half that matters.** The synthetic fixture's own
docstring says it exists because the real panels are too clean — that is an author noticing by
hand what a generator supplies for free.

In `packages/stompdrill/tests/test_invariant.py`, add a generative case beside the existing
example-based ones. Do not delete them: they carry named panels and a per-stage observability
assertion the generator cannot state.

```python
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

#: A coarse lattice so ties are likely rather than impossible. Two holes
#: sharing an X and a diameter, a coincident pair at a grid midpoint, and two
#: holes equal in nominal but differing in ``raw`` are the tie shapes the two
#: real fixtures cannot produce, and each one puts a different clause of
#: ``_total_order`` under load.
LATTICE_MM = [round(-40 + 80 * i / 11, 3) for i in range(12)]

CATALOGUE_MM = [3.0, 5.0, 7.0]


@st.composite
def raw_holes(draw):
    """A hole on the lattice, with occasional sub-micron jitter in ``raw``."""
    x = draw(st.sampled_from(LATTICE_MM))
    y = draw(st.sampled_from(LATTICE_MM))
    diameter = draw(st.sampled_from(CATALOGUE_MM))
    jitter = draw(st.sampled_from([0.0, 4e-4, -3e-4]))
    return RawHole(Millimetre(x + jitter), Millimetre(y), Millimetre(diameter))


@settings(deadline=None, max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(raw_holes(), min_size=1, max_size=8), st.integers(0, 2**32 - 1))
def test_no_permutation_of_any_hole_set_reaches_any_artifact(drawn, seed):
    """ADR-0006, over hole sets no author would think to write down.

    ``deadline=None`` because the emit fan-out is four formats, one of which
    builds a PDF; this is a slow property by construction, not a hanging one.
    """
    raw = replace(_synthetic_raw(), holes=tuple(drawn))

    assert_permutation_stable(raw, "1590B", shipped_pipeline(), seed=seed)
```

`assert_permutation_stable` and `_synthetic_raw` already exist in that module. Check that
`_synthetic_raw()`'s outline still holds every generated hole; if the lattice can put a hole
outside it, that is a `hole-outside-outline` warning rather than an error, so the property
still holds — confirm rather than assume, and say which you found.

**Also state the coupling that only reconciles because of an ordering.** `Deduplicate`'s
docstring says "Input order selects the survivor", which agrees with ADR-0006 only because
`quantise()` sorts on entry. Nothing tests that dependency. Add one example-based test pinning
the bare stage's order-sensitivity, so the coupling is documented rather than latent:

```python
def test_the_bare_dedupe_stage_is_order_sensitive_and_quantise_is_what_saves_it():
    """``Deduplicate`` alone keeps whichever duplicate arrived first. That is
    only compatible with ADR-0006 because ``quantise`` sorts before it runs,
    so the composed path never hands it an input order to consult. Pinning
    both halves keeps the coupling visible if either moves.
    """
```

- [ ] **Step 3: Widen the codec round trip**

`packages/stompmodel/tests/test_codec.py` has one `@given`, varying a single integer on a
one-hole document. **The round trip's real risk surface is shape, not magnitude:** hole counts,
indices permuted out of list order, diagnostics with and without `location_nm`, `data` tuples
empty and populated, `enclosure` present and absent, `reference` with and without `raw`,
`processing` with zero and many `StageRun`s, and every severity. `from_document` sits at 100%
line coverage in its own run — the gap is not lines, it is shapes, and lines cannot see that.

Build a composite `DrillData` strategy and assert `from_document(to_document(d)) == d`.
Keep the existing single-integer property: it varies magnitude, which the shape strategy holds
fixed, and the two are complementary rather than one subsuming the other.

**This is the item with the shortest window.** Once `stompcollider` exists the document is a
compatibility surface; today it is still cheap.

- [ ] **Step 4: Snapping, as three properties in nanometres**

The loop at `packages/stompdrill/tests/test_snap.py:184` asserts only idempotence, over
`rng.uniform(-60, 60)` — which will essentially never land on a half-pitch midpoint, the exact
place `grid-ambiguous` is decided and the exact place `Decimal(str(mm))` half-up rounding earns
its keep. State all three:

- `snap(x) % pitch == 0`
- `|snap(x) − x| ≤ pitch/2`
- `snap(snap(x)) == snap(x)`

**Restate them in nanometres**, which is the spec's wording and the spike's finding: expressed
over integers, an injected off-by-one in snap was found in 15.8 s; expressed over millimetres —
through `Decimal(str(mm))` — neither backend found it. The dividing line is that conversion.

Draw the pitch from `st.integers(1, 2000)` microns, which covers the sub-micron clamp boundary,
and positions from a **mixture**: a plain float strategy *and* explicitly constructed
`(k·pitch ± pitch/2)/1e6` midpoints. The midpoints are the point; a uniform float strategy
alone would be no better than the loop it replaces.

Keep the three regression examples above the loop — each cites something (the KiCad grid, the
metric step) and a citation test is the right kind there.

- [ ] **Step 5: Delete dedupe idempotence, and amend CLAUDE.md in the same commit**

`Deduplicate` compares `x_nm`, `y_nm` and `diameter_nm` by exact integer equality with no
tolerance, and its docstring says so. **Idempotence is therefore structurally guaranteed and no
generator can falsify it** — `diffbehavior` independently confirmed it survives both mutants.
Worse, the current 300-iteration loop draws positions from a 250 µm lattice, so it cannot even
generate a near-miss.

Delete the loop at `packages/stompdrill/tests/test_pipeline.py:292` and put a **distinct-keys
property** in its place, which is a claim about the stage's output rather than about running it
twice:

```python
@given(...)
def test_no_two_holes_survive_dedupe_with_the_same_key(drawn):
    """What ``Deduplicate`` is for, stated as a property of its output.

    Idempotence was the old form and could not fail: the comparison is exact
    integer equality, so a second pass has nothing left to find. This one
    can fail -- a key that drops a field, or a comparison that gained a
    tolerance, both leave two survivors that should have been one.
    """
    survivors = Deduplicate().apply(make_data(*drawn)).holes

    keys = [(h.x_nm, h.y_nm, h.diameter_nm) for h in survivors]
    assert len(keys) == len(set(keys))
```

Generate with duplicates sprinkled in *and* one-nanometre near-misses, so the property has both
things to distinguish. Add a named example for the near-miss being **retained** — that is the
boundary the old loop's lattice could not reach.

Then amend `CLAUDE.md`. It currently reads:

> Preserve property tests for snapping idempotence, deduplication idempotence, and tool
> stability under hole reordering.

`deduplication idempotence` is no longer preserved, and the instruction must stop asking for it
or the next reader restores a test this task removed on purpose. Rewrite the sentence to name
what is now preserved and why the third one went — one clause, not a paragraph. **Tool
stability under hole reordering stays**: `kinds.md` recommends folding it into the generative
permutation test, but the spec's list of four does not include it, and this plan does not
widen the spec's list on an audit's recommendation alone. Task 13 backlogs the question.

- [ ] **Step 6: Prove each converted property is stronger than what it replaced**

For each of the four, run the new property against a mutant the **old** form survived. The
spike already names one for snap; find the others by reasoning about what the old assertion
could not see.

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/generative-mutants"; rm -rf "$W"; mkdir -p "$W"
cat > "$W/halfpitch.py" <<'PY'
"""Off-by-one at the half-pitch midpoint: what a uniform float never hits."""
from stompdrill.pipeline import snap as snap_module
# Patch the rounding so a value exactly on a midpoint goes the wrong way.
PY
PYTHONPATH="$W" .venv/bin/python -m pytest -p halfpitch -o addopts= \
  packages/stompdrill/tests/test_snap.py -q 2>&1 | tail -4
rm -rf "$W"
```

Write the mutant body against how `snap.py` actually rounds; the requirement is that it changes
the answer **only at a midpoint**, so the old `rng.uniform` loop would survive it and the new
mixture strategy will not. Report, for each of the four, the mutant you used and whether the
old form survived it. If for one of them you cannot construct a mutant the old form survived,
**say so** — that is a finding about the conversion's value, not something to paper over.

- [ ] **Step 7: Run every gate and commit**

Run both suites from the root **and** the member alone, because Step 1 changed what the member
needs:

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -2
(cd packages/stompdrill && ../../.venv/bin/python -m pytest -p no:cacheprovider -o addopts= -q 2>&1 | tail -2)
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
git status --porcelain -uall
git add -A && git commit -m "Generate where a boundary hides, and delete a property that cannot fail"
```

---

## Phase C — the extractions, protected by Phase B

Each of these is a refactor under test. Phase B is what makes them safe, which is why they come
last and why the routing repair comes last of all.

---

### Task 10: `write_payload` into `stompmodel`

ADR-0005 makes this "the one site that writes a file" and prints the decision function verbatim
in the ADR. `Payload` itself already lives in `stompmodel`, but the dispatch that gives it
meaning lives privately in `stompdrill`'s CLI, and two tests already reach for `cli._write`.

ADR-0009's admission rule 2 requires naming the `stompcad` behaviour that depends on
uniformity. There is one: `stompcad` orchestrates both tools and reports once. If
`stompcollider` writes its own `isinstance(payload, bytes)` branch and its own
`"wrote {path}  ({name}, {n} bytes)"` line, the orchestrator has two report formats and two
byte-counting conventions — and ADR-0005's own consequence, "the reporting line still counts
encoded bytes, so its number means the same thing for both kinds of payload", is a promise only
one implementation can keep.

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/protocols.py`
- Modify: `packages/stompdrill/src/stompdrill/cli.py:702-710`
- Modify: `packages/stompdrill/tests/test_emitter_registry.py:180, 198`
- Modify: `packages/stompmodel/tests/test_protocols.py`
- Modify: `docs/adr/0005-binary-emitter-payloads.md`

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
# stompmodel/protocols.py
def write_payload(path: Path, payload: Payload) -> int:
    """Write one payload, letting its own type choose the mode. Returns the
    encoded byte count."""
```

The CLI keeps ownership of the sentence it prints around that number. The split is deliberate:
the byte-counting convention is shared and must not drift; the report's wording is
`stompdrill`'s and `stompcollider` will want its own.

- [ ] **Step 1: Write the failing tests in the leaf's own suite**

In `packages/stompmodel/tests/test_protocols.py`. The count is the contract, so assert it
against a payload where the two conventions differ:

```python
def test_a_text_payload_is_written_as_utf_eight(tmp_path):
    path = tmp_path / "out.txt"

    written = write_payload(path, "⌀7.000")

    assert path.read_text(encoding="utf-8") == "⌀7.000"


def test_a_text_payload_counts_encoded_bytes_not_characters(tmp_path):
    """``⌀`` is three bytes in UTF-8 and one character. The count is the whole
    reason this lives here: ``stompcad`` reduces over both tools' numbers and
    they have to mean one thing."""
    assert write_payload(tmp_path / "out.txt", "⌀7.000") == 8


def test_a_binary_payload_is_written_unchanged(tmp_path):
    path = tmp_path / "out.bin"

    written = write_payload(path, b"%PDF-1.7\n\x00\xff")

    assert path.read_bytes() == b"%PDF-1.7\n\x00\xff"


def test_a_binary_payload_counts_its_own_length(tmp_path):
    assert write_payload(tmp_path / "out.bin", b"%PDF-1.7\n\x00\xff") == 11
```

Count the bytes yourself before writing the literals: `"⌀7.000"` is 6 characters and `⌀` is
three bytes in UTF-8, so 8. Check both numbers rather than copying them from here.

- [ ] **Step 2: Run them and watch them fail, then implement**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_protocols.py -q 2>&1 | tail -3
```

Then add to `packages/stompmodel/src/stompmodel/protocols.py`, extending `__all__`. It needs
`from pathlib import Path`, which is stdlib, so the package-boundary gate stays green.

```python
def write_payload(path: Path, payload: Payload) -> int:
    """Write ``payload``, letting its own type choose the mode.

    Returns the encoded byte count, which is the number both tools report
    and ``stompcad`` reduces over. A second copy of this branch is a second
    counting convention, which is the drift ADR-0005's consequence forbids.
    """
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        return len(payload)
    encoded = payload.encode("utf-8")
    path.write_text(payload, encoding="utf-8")
    return len(encoded)
```

- [ ] **Step 3: Delegate from the CLI**

```python
def _write(emitter: Emitter[DrillData], path: Path, payload: Payload) -> str:
    """Report one artefact. The dispatch is ``stompmodel``'s; the sentence is ours."""
    size = write_payload(path, payload)
    return f"wrote {path}  ({emitter.name}, {size} bytes)"
```

`_write` stays, private and thin: `test_emitter_registry.py` reaches for it at two sites and
the report's wording is genuinely `stompdrill`'s. Leave both call sites alone unless they break.

- [ ] **Step 4: Amend ADR-0005**

The sentence "The command line owns the encoding decision at the one site that writes a file"
asserts a current fact and becomes false. The code block beneath it is the decision as
originally taken, and is history. Amend the prose and leave the block:

- Rewrite that sentence to say the dispatch is `stompmodel.protocols.write_payload` and the
  command line owns the report it prints around the count.
- Add one line under **Consequences**: `stompcollider` inherits the counting convention rather
  than re-deriving it, which is what makes ADR-0005's existing "means the same thing for both
  kinds of payload" hold across two tools rather than within one.
- Note the ADR-0009 admission rule the move satisfies, naming the `stompcad` behaviour.

Do not retrofit the Context or Rationale. They argue about a decision taken when there was one
package, and rewriting them would erase the reason the move needed an admission rule at all.

- [ ] **Step 5: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
git status --porcelain -uall
git add -A && git commit -m "Give both tools one way to write a payload and one way to count it"
```

---

### Task 11: Both options types carry a `SheetText`, and the title block stops re-deriving

Two findings with one blast radius, so one task.

**G5.** `SheetText` already *is* the extracted shared idea. Both emitters project into it —
SVG fills three fields, PDF fills six. `build_scene` is shared, so **an SVG sheet draws
`DATE OF ISSUE`, `APPROVED` and `CREATOR` and always prints `ABSENT` for all three**, because
`DrawingOptions` has no way to supply them. `PdfDrawingOptions`' docstring says "a caller that
supplies them gets a conforming sheet"; an SVG caller cannot, for no stated reason. That is the
user-visible half, and it is the reason this is worth 28 call-site edits.

**Do not merge the two options types** — `interfaces.md` N2, and CLAUDE.md and `layout.py` both
record why: `sheet`/`scale` and `candidates`/`frame` feed genuinely different solvers. Their
real overlap is the ISO 7200 text, and moving that into the type that already exists takes the
duplication to zero without pretending one solver is two.

**D2.** `_plain_title_block` re-derives what `content.title_fields` already decides, and spells
`'—'` four times against a documented `ABSENT` constant sitting in the module it should be
reading from. CLAUDE.md's own division says `content` holds the facts a sheet states and
`build` turns them into primitives.

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing_svg.py`
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing_pdf.py`
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing/content.py`
- Modify: `packages/stompdrill/src/stompdrill/emitters/drawing/build.py:934-948`
- Modify: `packages/stompdrill/src/stompdrill/cli.py` — `_OPTION_BUILDERS`
- Modify: 28 construction sites across the test suite

**Interfaces:**
- Consumes: `SheetText` (`emitters/drawing/content.py`).
- Produces:

```python
@dataclass(frozen=True, slots=True)
class DrawingOptions:
    sheet: Sheet = A4_LANDSCAPE
    scale: float | None = None
    text: SheetText = SheetText()

@dataclass(frozen=True, slots=True)
class PdfDrawingOptions:
    text: SheetText = SheetText()
    candidates: tuple[Sheet, ...] = ISO_5457_CANDIDATES
    frame: FrameStyle = FrameStyle.ISO_5457

# content.py
def plain_title_lines(data: DrillData, text: SheetText, layout: Layout, room: int) -> tuple[str, ...]:
    """The lines the non-ISO title block states, in the order it states them."""
```

`SheetText` is a frozen slotted dataclass with all-defaulted fields, so `SheetText()` as a
default is safe and needs no `field(default_factory=...)`. Add it to
`[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` in the root `pyproject.toml` if B008
fires, beside the value objects already listed there for the same reason.

- [ ] **Step 1: Record the before-bytes, exactly as Phase A did**

This task must change no artefact byte: `ABSENT` *is* `'—'`, and the field values are the same
values arriving by a different route. Reuse the Phase A instrument: the `emit_all` shell
function is written out in full in **Task 1, Step 1** — copy it from there, because a fresh
session does not inherit a shell function defined in another task. Emit into
`${TMPDIR:-/tmp}/phase-c/before`, outside the repository, and discard it at the end.

- [ ] **Step 2: Move the fields**

Replace `title`, `drawing_no` and `company` on `DrawingOptions`, and `title`, `drawing_no`,
`company`, `issue_date`, `approved_by` and `creator` on `PdfDrawingOptions`, with a single
`text: SheetText = SheetText()`. Delete `_sheet_text()` from both emitters — `emit` passes
`self.options.text` straight to `build_scene`. Point `_sheet_title` and `_title` at
`self.options.text.title`.

`PdfDrawingOptions`' docstring currently explains the three empty defaults. That explanation
belongs on `SheetText` now, which is where the three fields live; move it rather than leaving a
copy, and keep it inside ten lines.

- [ ] **Step 3: Update the CLI and every construction site**

```python
    DrawingOptions: lambda s: DrawingOptions(text=SheetText(title=s.title)),
    PdfDrawingOptions: lambda s: PdfDrawingOptions(text=SheetText(title=s.title)),
```

The comment above the PDF entry says its ISO 7200 mandatory fields "have no command-line source
yet; a caller using the library supplies them directly". That is now true of the SVG entry too
and was not before, so the two comments collapse into one above the pair.

Then the 28 test sites. This is mechanical: `DrawingOptions(title=X)` becomes
`DrawingOptions(text=SheetText(title=X))`, and the same for the PDF type. Do them in one sweep
rather than one per file; a partial sweep leaves the suite red and tells you nothing.

```bash
cd /Users/thelyx/repo/stompcad
grep -rn "DrawingOptions(" packages tools --include='*.py' | grep -v mutants | wc -l
```

Expected before the sweep: 22 for `DrawingOptions(` and 6 for `PdfDrawingOptions(`. Measure
again after, and account for any difference.

- [ ] **Step 4: Move the plain title block's facts into `content`**

Lift the nine-line list from `build.py:934-948` into `content.plain_title_lines`, replacing all
four `'—'` literals with `ABSENT`. `build.py` keeps the font fitting, the step and the `Text`
construction — that is turning facts into primitives, which is its half of the division.

`enclosure_note`, `grid_note` and `capacity` are already `content`'s own, so the moved function
calls them directly instead of `build` importing them to build a string.

- [ ] **Step 5: Prove byte-identity, then discard the instrument**

```bash
cd /Users/thelyx/repo/stompcad
emit_all "${TMPDIR:-/tmp}/phase-c/after"
diff -r "${TMPDIR:-/tmp}/phase-c/before" "${TMPDIR:-/tmp}/phase-c/after" && echo "IDENTICAL"
rm -rf "${TMPDIR:-/tmp}/phase-c"
```

Expected: `IDENTICAL`. If the SVG differs, the likely cause is a field that used to be
unreachable now arriving with a value — check `DATE OF ISSUE`, `APPROVED` and `CREATOR`, which
must still print `ABSENT` because the CLI still supplies none of them. **That the SVG can now
carry them is the fix; that it does not carry them by default is the byte-identity.**

- [ ] **Step 6: Add the one test the fix earns**

The bug G5 names has never been expressible. Now it is:

```python
def test_an_svg_caller_can_fill_the_three_iso_fields_the_sheet_already_draws():
    """The sheet drew DATE OF ISSUE, APPROVED and CREATOR and always printed
    ABSENT for them, because ``DrawingOptions`` had no way to supply them --
    for no stated reason, since ``build_scene`` is shared with the PDF."""
    options = DrawingOptions(text=SheetText(issue_date="2026-08-21", approved_by="PV"))

    shown = svg_strings(panel(), options)

    assert "2026-08-21" in shown
    assert "PV" in shown
```

Two assertions, not one: a projection that dropped one field and kept the other is a real
defect and a single `and` would report it as the same failure as dropping both.

- [ ] **Step 7: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Let both sheets carry the same words, and stop re-deriving them"
```

---

### Task 12: The routing repair — Θ(P·n³) to Θ(P·n²)

`_two_opt` scores each candidate reversal by rebuilding the route and rescoring it end to end,
when a 2-opt reversal changes exactly **two edges** and is scorable in O(1). The rescoring line
is 97% of per-candidate cost, and 99.96% of candidates are rejected after paying it. Measured
growth is Θ(n³) per improvement sweep — local slopes 3.01, 3.02, 2.94, 3.03 on a point set that
provokes exactly one sweep — with the sweep count data-dependent at 1–5 rather than scaling with
n. Cost is cubic **per tool block**, and blocks partition n.

**Not live.** A 30-hole panel routes in 0.3 ms. The repair is about ten lines and the reason it
is in this plan rather than in a performance backlog is the one in the spec: its single risk is
a float-summation tie changing a route, and **the instruments that would catch that are what
Phase B builds.** It lands here because it can now be checked, not because it is urgent.

**ADR-0006 pins the algorithm, not only the output**: first improving reversal, fixed start,
sweeping `i < j`. An O(1) edge delta preserves all three and **needs no ADR amendment**.
Best-improvement, Or-opt, or neighbour-list pruning would change the routing rule and must amend
the ADR first — even if they produced shorter paths. Do not reach for them.

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/pipeline/route.py:56-84`
- Modify: `packages/stompdrill/tests/test_route.py:165-184`

**Interfaces:**
- Consumes: nothing.
- Produces: `_leg(a: Hole, b: Hole) -> float`, replacing `_path_length`. Private, but named
  here because `test_route.py` imports the function it replaces.

- [ ] **Step 1: Record the before-bytes and the before-routes**

Reuse the Phase A instrument for the artefacts — the `emit_all` shell function is written out
in full in **Task 1, Step 1**; copy it from there, since a fresh session does not inherit it.
Add a route comparison too, because the artefacts alone would not distinguish "the route is the
same" from "the route changed and the two fixture panels are too small to show it":

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/route-repair"; rm -rf "$W"; mkdir -p "$W/before"
emit_all "$W/before"
cat > "$W/routes.py" <<'PY'
"""Print the routed order of many random blocks, as hole identities."""
import json, random, sys
from stompdrill.pipeline.route import _routed
from stompmodel.model import Hole, RawHole
from stompmodel.units import Millimetre, Nanometre

out = {}
for n in (4, 5, 8, 12, 20, 35, 60, 90):
    for seed in range(4):
        rng = random.Random(seed * 1000 + n)
        holes = []
        for i in range(n):
            x = rng.randrange(-50_000_000, 50_000_000, 10_000)
            y = rng.randrange(-25_000_000, 25_000_000, 10_000)
            holes.append(Hole.from_measurement(Nanometre(x), Nanometre(y), Nanometre(5_000_000)))
        out[f"{n}-{seed}"] = [(h.x_nm, h.y_nm) for h in _routed(tuple(holes))]
json.dump(out, open(sys.argv[1], "w"), indent=0)
PY
.venv/bin/python "$W/routes.py" "$W/before-routes.json"
wc -l "$W/before-routes.json"
```

`Hole.from_measurement` may take different arguments than shown; check its signature and adjust.
The point is 32 blocks up to n=90, which is fifteen times the largest block any existing test
routes.

- [ ] **Step 2: Make the change**

Replace `_path_length` with a single-leg helper — it is what the delta needs, and it is where
the documented precondition actually lives:

```python
def _leg(a: Hole, b: Hole) -> float:
    """One leg's real length. Squared lengths would not compare correctly,
    because a reversal changes legs unequally.

    Precondition: panel-sized nanometres. A squared separation past
    ``float``'s range raises ``OverflowError``; unguarded for the same reason
    ``nm_from_mm`` is.
    """
    return _distance_sq(a, b) ** 0.5
```

Then `_two_opt`. Reversing `route[i..j]` changes only the edges `(i−1, i)` and `(j, j+1)`:

```python
def _two_opt(route: list[Hole]) -> list[Hole]:
    """Reverse the first segment that shortens the path, keeping the start fixed.

    A reversal changes exactly two edges, so its effect is a four-term
    difference rather than a rescored route: the traversal, the
    first-improving rule, the fixed start and the tie-break are all
    unchanged, and the cost per block goes cubic to quadratic. See ADR-0006,
    which pins the algorithm and not only its output.
    """
    improved = True
    while improved:
        improved = False
        for i in range(1, len(route)):
            for j in range(i + 1, len(route)):
                delta = _leg(route[i - 1], route[j]) - _leg(route[i - 1], route[i])
                if j + 1 < len(route):
                    delta += _leg(route[i], route[j + 1]) - _leg(route[j], route[j + 1])
                if delta < -1e-9:
                    route[i : j + 1] = route[i : j + 1][::-1]
                    improved = True
    return route
```

**Also correct the comment that is no longer there to correct.** The current body carries three
lines beginning "The route's own length is loop-invariant except when an accepted candidate
replaces it". Commit `ba44744` hoisted that loop-invariant length, halved the constant, left the
exponent, and left a comment reading as though the recomputation had been dealt with — **the
artefact most likely to stop the next reader from looking.** It goes with the code it described;
do not carry a trimmed version of it forward.

`_two_opt` now mutates its argument. `_routed` passes a fresh list from `_nearest_neighbour`, so
nothing outside sees it — say so in one line rather than defensively copying.

- [ ] **Step 3: Update the precondition test**

`packages/stompdrill/tests/test_route.py:165-184` imports `_path_length` and asserts
`_path_length([origin, far(150)]) == 1e150` and that `far(160)` raises. The claim is about one
leg; move it onto `_leg` unchanged in substance. Do not delete it — it is the test that makes
the documented precondition a documented precondition rather than a hope.

- [ ] **Step 4: Prove the routes did not move**

Three pieces of evidence, in increasing strength:

```bash
cd /Users/thelyx/repo/stompcad
W="${TMPDIR:-/tmp}/route-repair"
mkdir -p "$W/after" && emit_all "$W/after"
diff -r "$W/before" "$W/after" && echo "ARTEFACTS IDENTICAL"
.venv/bin/python "$W/routes.py" "$W/after-routes.json"
diff "$W/before-routes.json" "$W/after-routes.json" && echo "32 BLOCKS IDENTICAL"
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
rm -rf "$W"
```

Expected: both `IDENTICAL` lines, the golden unmoved, and the layer-1 fresh-process comparison
green. The prototype found 96 identical routes out of 96 and four byte-identical artefacts.

**If a route moves, do not adjust the threshold to make it stop.** The spec names this exact
risk: summing four terms is not guaranteed to compare identically to summing n square roots at
a tie, so a divergence is the caveat biting, not a bug in the delta. Report the block, the two
routes and their two lengths, and stop — whether today's particular route or the faster
algorithm is the thing to keep is a decision, not a fix.

- [ ] **Step 5: Add the test at a size the cubic was visible at**

No existing test routes more than six holes. That is why nothing would have noticed a 200-LED
front panel hanging.

```python
def test_a_realistic_panel_routes_without_the_cubic_term() -> None:
    """Three hundred holes in one tool block, the size the cubic was visible at.

    Measured: the rebuild-and-rescore form took 9.6 s here and 2.08 s at
    n=200; the four-term delta takes 0.156 s. The bound sits an order of
    magnitude above the delta and well under the cubic, so it catches a
    regression rather than machine noise.
    """
    rng = random.Random(20260821)
    holes = tuple(
        at(
            rng.randrange(-50_000_000, 50_000_000, 10_000),
            rng.randrange(-25_000_000, 25_000_000, 10_000),
            5_000_000,
        )
        for _ in range(300)
    )

    started = time.perf_counter()
    routed = RouteHoles().apply(make_data(*holes))
    elapsed = time.perf_counter() - started

    assert len(routed.holes) == 300
    assert [index for index, _ in routed.numbered()] == list(range(1, 301))
    assert elapsed < 2.0, f"routing 300 holes took {elapsed:.2f}s; the cubic form took 9.6 s"
```

`random` and `time` go in the module's import block. Three assertions, not one: a hang, a
renumbering and a dropped hole are three defects and a combined condition reports them as one.
**Re-measure both figures on the machine you run on** and put your numbers in the docstring —
those above are the audit's, and a docstring citing someone else's machine is a citation to
nothing.

- [ ] **Step 6: Update CLAUDE.md if it states the old cost**

Search `CLAUDE.md` and `docs/` for any statement about routing cost or block size limits and
make it true. If there is none, say so — an absent claim needs no edit, and inventing one to
have something to update is worse than leaving it.

- [ ] **Step 7: Run every gate and commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -2
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Score a reversal by the two edges it changes"
```

---

### Task 13: The record

Every plan in this programme ends by writing down what was measured rather than what was hoped.
This one also closes two gaps between the spec and its own plan table.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/specs/verification-technical.md`
- Modify: `docs/BACKLOG.md`

- [ ] **Step 1: Measure everything, once, at the end**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q 2>&1 | tail -1
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests -q 2>&1 | tail -1
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompmodel/tests -q 2>&1 | tail -1
.venv/bin/python -m pytest -o addopts= --cov=stompdrill --cov-report=term-missing 2>&1 | tail -25
(cd packages/stompmodel && uv run --no-sync pytest -o addopts= --cov=stompmodel --cov-report=term-missing 2>&1 | tail -12)
```

Reconcile the headline count against the baselines at the top of this plan, task by task. If it
does not reconcile, **investigate rather than explain** — the difference is a real finding about
one of the twelve tasks before it.

- [ ] **Step 2: Update `CLAUDE.md`**

Only sentences that are now false, and only to what you measured:

- The two expected suite counts in **Testing rules**.
- The **Development commands** block: `pdfminer.six` and `hypothesis` arrive with
  `uv sync --all-packages`, and the recovery subpackage is worth one sentence under Testing
  rules — where it lives, that it is uncollected helper code, and that a gate forbids it
  importing `stompdrill`.
- The **Extending** section: `render(scene, title)` is now part of what a drawing emitter
  offers, and `stompmodel.protocols.write_payload` is where a payload is written.
- **Architecture**: the sentence about `emitters/drawing/` should name `render` as the seam
  between building and serialising.

Do not restate the layers' rationale in `CLAUDE.md`. The spec holds the argument; CLAUDE.md
holds the rules and points at it.

- [ ] **Step 3: Close the two gaps in the spec**

`docs/specs/verification-technical.md` §7's plan-3 row lists nine items and omits two things
§4 and §5 require. Both were ruled on before this plan was written, and the spec should stop
describing a programme its own table does not deliver:

- **Acceptance tests.** §4 disposes of the contract-coverage group as "acceptance tests" and §5
  lists an acceptance tier in the default run, but no plan row carried them. Add them to §7's
  plan-3 row, which is now true of the work that landed.
- **The symbolic tier.** §5 describes a nightly CrossHair tier and says adoption is conditional
  on the canary. No plan builds it, and this one deliberately does not. Mark it in §5 as
  **not adopted**, naming the backlog entry Step 4 writes, so the tier table stops describing a
  tier that does not exist.

This is the spec, not an ADR, but the same rule governs it: a stale statement is misinformation.
Amend the tables; leave §6's decision rationale alone, which is history.

- [ ] **Step 4: Write the backlog entries**

Each names what would close it:

1. **The symbolic tier.** CrossHair over the integer core — `dedupe.py`, `route.py`, and any
   property expressible in nanometres. Every property carries a canary, because the backend
   degrades to concrete execution with no timeout, no warning, and `metadata.backend` reporting
   `null`; if the canary stops failing, the tier is measuring nothing. `units.py` and `snap.py`
   as written are excluded: `Decimal(str(mm))` realises the symbolic float, and the spike
   measured one assertion going from 0.20 s solvable to unsolvable-but-reported-passing.
   Evidence in `.scratch/test-audit/spike-symbolic.md`. Trigger: worth taking when a bug is
   found that a property test missed at a boundary, not on a schedule.
2. **ADR-0008's governing test, executed.** `pip install packages/stompmodel` into a throwaway
   venv. `kinds.md` Gap 3's fourth check; needs the network and tens of seconds, so it belongs
   behind an opt-in marker beside `--hammond`.
3. **Tool stability under hole reordering.** `kinds.md` argues the 20-shuffle loop at
   `test_pipeline.py` is subsumed by the generative permutation test and should go. The spec's
   list of four conversions does not include it, so Task 9 left it. Decide it deliberately
   rather than by omission.
4. **Typing the emitter registry**, and with it `make_emitter`'s return annotation. Spec §8, out
   of scope: one change, when someone wants it.
5. **Moving `RawDrillData` to `stompdrill/raw.py`.** Spec §8: ADR-0009 explicitly placed it in
   `quantise.py`, there is no cycle today, and the move needs an ADR amendment when a stage
   first needs it in a signature.

Match the shape of the entries already in `docs/BACKLOG.md`. Anything the twelve tasks before
this one deferred goes here too, each with what would close it — a deferral with no closing
condition is a deletion with extra steps.

- [ ] **Step 5: Commit**

```bash
cd /Users/thelyx/repo/stompcad
.venv/bin/ruff check packages tools && .venv/bin/mypy packages
git status --porcelain -uall
git add -A && git commit -m "Record what this branch measured, and what it deliberately left"
```

---

## Residuals this plan deliberately leaves

Named so that the next reader meets a decision rather than an omission.

| Residual | Why it is left | What would close it |
| --- | --- | --- |
| The nightly symbolic tier | §5 makes adoption conditional on a canary and §7 assigns it to no plan; the spike's viable subset is narrow | a bug a property test missed at a boundary — Task 13's backlog entry names the subset and the canary rule |
| `pip install packages/stompmodel` into a clean venv | ADR-0008's governing test in its executable form; needs the network and tens of seconds | an opt-in marker beside `--hammond` |
| Tool stability under hole reordering | `kinds.md` says it is subsumed by Task 9's generative permutation test; the spec's list of four does not include it, and this plan does not widen the spec on an audit's recommendation | a deliberate decision, backlogged by Task 13 |
| Typing the emitter registry | spec §8, explicitly out of scope | one change, when someone wants it |
| Moving `RawDrillData` | spec §8; ADR-0009 placed it, there is no cycle, and the move needs an amendment | a stage needing it in a signature |
| Replacing the hand-rolled SVG and PDF serialisers | spec §8; the ISO 5457 sheet is bespoke and the change is large. §1 makes the position visible — two of five codecs are ours, which is why two of five checks are expensive | not proposed |
| A general artefact-reading capability | each recovery reads what our emitters write and nothing else; hardening a helper against inputs its only supplier cannot generate is how a test becomes complex enough to need its own tests | a second supplier |
| D1, D3, D4, D6, D7, D8, D9 from `interfaces.md` | Phase C takes the three the spec names and no more; the rest are duplication findings without a stated consequence | their own scoping pass |
| A golden per artefact | §6: with T2 holding per format it is redundant, and the panel path plus the STEP counter make a byte-golden fail on legitimate change | a format whose layer-2 check cannot be written |
| Excellon's layer 2 | there is nothing between `DrillData` and the bytes; that is a property of the emitter, not an omission | splitting `ExcellonEmitter.emit`, which nothing wants |

## Corrections this plan makes to the record

The audit reports predate the spec and two are superseded in part. Each correction is repeated
in the task it affects; they are gathered here so a reader of the reports meets them once.

1. **`parsers.md` demotes PDF to a smoke check and concludes "nothing needs adding" to the dev
   group.** The spec reverses both: PDF's independent geometry recovery is load-bearing, because
   the frame flip, the points matrix and the Bézier circle are the only owned transforms nothing
   else reaches, and `pdfminer.six` is a dev dependency bought for exactly that. Task 3. The
   report's own §"PDF geometry recovery: feasible" is the section that survives.

2. **`parsers.md` parses with `float` and compares with `pytest.approx`.** It hit
   `16.200000000000003` and correctly diagnosed the noise as its own reframing arithmetic. This
   plan parses decimal text with `Decimal`, which removes the noise and the epsilon together and
   is what lets the spec's "comparison is exact" hold. Task 2.

3. **`kinds.md` Gap 4 proposes three byte-goldens of artefacts** (`tar.drl`, `tar.json`,
   `tar.svg`), with a cwd dance to stabilise `source.path`. The spec supersedes it: **one
   golden, of the model, as a fact-set** — because the panel path is provenance in four of five
   artefacts and the STEP writer appends a volatile counter, and because with T2 holding per
   format a golden per artefact is redundant. Task 6.

4. **`kinds.md` Gap 5 estimates routing growth at "roughly n⁴".** `route-performance.md`
   measured it: Θ(n³) per improvement sweep, with the sweep count data-dependent at 1–5 rather
   than scaling with n, giving an observed whole-range exponent of 3.35. Task 12 states the
   measured figures.

5. **`kinds.md` §4 recommends replacing dedupe idempotence with three named examples.** The spec
   says "deleted for a **distinct-keys property**" — a claim about the stage's output rather
   than about running it twice, and one that can actually fail. Task 9 follows the spec and keeps
   a named example for the near-miss boundary.

6. **`interfaces.md` G1 says three private imports collapse to two.** After Task 1 only `_num`
   remains: three to one. G1's own reasoning is why — predicting a stream's exact bytes through
   a *formatter* is legitimate coupling, unlike reaching past a missing seam.

7. **A new dev dependency belongs to the member, not the root.** `parsers.md` reasons about the
   root `[dependency-groups] dev` throughout. ADR-0008's governing test is that each member
   passes its own tests *alone*, so a dependency `packages/stompdrill/tests/` imports must be
   declared there. Verified while writing this plan: declaring it in the member is also
   sufficient for the shared root `.venv` under `uv sync --all-packages --all-extras`. Tasks 3
   and 9.

8. **The spec's §7 omits two things its own §4 and §5 require.** The contract-coverage group has
   no plan row, and the symbolic tier has none either. Both were ruled before this plan was
   written: acceptance tests land here (Task 8), the symbolic tier is backlogged with its canary
   condition (Task 13). Task 13 amends §7 and §5 so the spec stops describing a programme its
   table does not deliver.

## Self-review

Run against the spec after the plan was complete.

**Spec coverage.** §1's three layers: Tasks 4, 5, 6. §2's three recoveries, the independence
gate and the precision rule: Tasks 2, 3, and the Global Constraints precision table. §3's Phase
A: Task 1; Phase B: Tasks 2–9; Phase C's three items: Tasks 10 and 11. §4's six disposition
groups: contract coverage → Task 8, hollow tests → landed in plans 1 and the test-repair run,
broken instruments → landed in plan 1, generative → Task 9, end-to-end → Task 7, documentation →
landed in plan 1. §4's domain changes: landed in plan 2. §4's routing repair and its three
constraints: Task 12. §4's domain-edge preconditions: documented already; Task 12 keeps the
`_leg` test that makes one of them real. §5's tiers: default and `--hammond` throughout, the
mutation survey unchanged, the symbolic tier ruled out and backlogged. §6's eight decisions:
each appears as the reason in the task that acts on it. §7's plan-3 row: every item, plus the
two §7 omits. §8's four out-of-scope items: in the residuals table, none built.

**Placeholders.** Four steps deliberately hand off rather than transcribe, and each says what
the requirement is and where the pattern lives: Task 4 Step 4 (OCP symbol names against the
pinned `cadquery-ocp`), Task 6 Step 2 (the subprocess script written into `tmp_path`), Task 8
Steps 3 and 4 (bodies against `test_cli.py:1616` and `test_clearance.py`), Task 9 Steps 3 and 6
(the composite strategy and the mutants). These are judgement handoffs with a named model, not
"implement later" — but they are the places a task reviewer should look hardest, and a task that
silently narrows one of them has not done it.

**Type consistency.** `RecoveredCircle` / `RecoveredPanel` / `nm_from_decimal` are defined once
in Task 2 and used unchanged in Tasks 3, 4 and 5. `read_excellon`, `read_svg`, `read_pdf` share
one return type. `render(scene, title)` has one signature per backend, fixed in Task 1 and used
in Tasks 4 and 5. `write_payload(path, payload) -> int` appears once. `_leg` replaces
`_path_length` in both the source and the one test that imports it. `SheetText` is not
redefined — Task 11 moves the existing type into two options types that stop re-declaring its
fields.

**One thing this plan cannot check about itself.** Every count it states is measured, and the
baselines at the top were taken on `main` at `e0852e7` minutes before it was written. No task
predicts a count, and any task whose measurement disagrees with its expectation is required to
report the disagreement rather than reconcile it.
