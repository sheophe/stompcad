# ADR-0001: Preprocessing pipeline with adapter-based emitters

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Pavlo Vakhnivskyi (Artifact Instruments)
**Supersedes:** the `read_drill.py` / `emit.py` script pair

---

## Context

`aidrill` extracts drill data from Adobe Illustrator panel artwork and emits it in
fabrication formats. The `.ai` file's `Drill` layer is authoritative: every circle on it
is a hole.

The first version was a single script with an `emit.py` helper. It worked, and then the
Excellon output exposed a defect that had been latent from the start.

**The driving incident.** Circle diameters recovered from the PDF stream come back as
`6.9998` and `7.0000` for what the designer drew as one 7 mm hole — the difference is
Bézier-fitting noise, not design intent. Position snapping was applied as a preprocessing
pass; diameters were not, because nothing had forced the question. Then the Excellon
writer needed to build a tool table, so it grouped diameters *itself*, inside the writer.
The emitted file was:

```
T1C5.000
T2C7.000
T3C7.000      ← the same physical drill bit, loaded twice
```

A shop would have run two separate passes with one bit. The fix applied at the time —
clustering inside the writer — was worse than the bug, because the SVG drawing did its
own grouping separately. Two artifacts describing the same panel could legitimately
disagree about how many hole sizes existed, and nothing would catch it.

**Forces at play.**

- Output formats will keep multiplying. Excellon and a drill drawing exist today; DXF is
  wanted next (an enclosure shop is more likely to want DXF than Excellon), and a
  `.ai`-writeback emitter is plausible later.
- Input formats may multiply too — SVG and DXF sources are conceivable.
- Every artifact from one run is consumed by a *different human*: the machinist reads the
  drawing, the CNC reads the drill file, the wider toolchain reads JSON. They must agree.
- Preprocessing parameters are user-facing (`--grid`, `--diameter-tolerance`,
  `--dedupe-tolerance`) and must apply uniformly, not per-format.
- Single-operator project. Maintenance burden matters more than throughput; there is no
  team to absorb accidental complexity.

**Constraint.** `aidrill` is one component of a larger pedal-design toolchain. It must
stay narrow — parse artwork, emit drill data — and be importable as a library by the
enclosure/PCB fit-checking work that will consume it.

---

## Decision

Adopt a three-role architecture with one direction of flow:

```
Source ──RawGeometry──▶ Pipeline of Stages ──DrillData──▶ Emitter ──▶ artifact
```

**All normalisation happens exactly once, in the pipeline, before any emitter sees the
data.** Snapping, diameter normalisation, deduplication and validation are `Stage`
implementations composed by the CLI in a fixed order. Emitters serialise and may translate
frames or units, but may not round, cluster, dedupe or renumber anything.

Three supporting decisions follow from that core rule:

1. **`DrillData.tools()` lives on the model, not in the Excellon emitter.** Tool numbering
   is shared truth between the drill file's tool table and the drawing's hole schedule, so
   it cannot live in either.
2. **Emitters self-register** via `@register_emitter` into a registry the CLI resolves
   `--emit FORMAT=PATH` against. Adding a format touches the new module plus one
   `__init__` line; `cli.py` never names a format.
3. **Diagnostics are data, produced once and rendered many times.** A stage that finds
   something appends a `Diagnostic` with a stable machine `code` and a small payload;
   the CLI report, the drawing's NOTES block and the JSON output are three renderings of
   the same finding, never three computations.

---

## Options Considered

### Option A: Keep the script, fix the diameter bug in place

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | ~1 hour |
| Extensibility | Poor — each new format re-opens the same file |
| Team familiarity | Highest (it already existed and worked) |
| Testability | Poor — no seam between parsing, processing and output |

**Pros:** Fastest path to a correct drill file. No new concepts. The script was ~400 lines
and legible.

**Cons:** Fixes the symptom, not the class. The same defect recurs the moment a third
format needs a derived value — and it did recur: the review found the drawing emitter had
independently grown its own duplicate-detection with a hardcoded 0.05 tolerance and *no
diameter check*, disagreeing with the pipeline's verdict on the same panel. That is the
identical bug, relocated. No place to put `--grid` such that all formats honour it.

### Option B: Extract a shared `normalise()` helper each emitter calls

| Dimension | Assessment |
|---|---|
| Complexity | Low–Medium |
| Cost | ~half a day |
| Extensibility | Medium |
| Team familiarity | High |
| Testability | Medium — helper is testable; call sites are not enforced |

**Pros:** Removes the duplicated arithmetic with minimal restructuring. Keeps a single
implementation of clustering. Much cheaper than Option C.

**Cons:** Correctness depends on every emitter *remembering* to call it, with the same
arguments, in the same order. Nothing enforces it, and nothing detects an emitter that
forgets. It also leaves normalisation conceptually inside the output stage, so a new
emitter author reasonably assumes normalising is their job — which is exactly the belief
that produced the incident. Preprocessing parameters would have to be threaded through
every emitter's options, growing each format's API for reasons that have nothing to do
with that format.

### Option C (chosen): Pipeline of stages + adapter-based emitters

| Dimension | Assessment |
|---|---|
| Complexity | Medium — three protocols, ~20 small modules |
| Cost | ~1 day with parallel implementation |
| Extensibility | High — new stage or emitter touches one file plus one import |
| Team familiarity | Medium — standard pipeline/strategy/adapter patterns |
| Testability | High — every stage is a pure function; emitters take constructed data |

**Pros:** Makes the invariant structural rather than remembered. An emitter *cannot*
normalise without visibly reaching outside its responsibility, which a review catches.
Preprocessing parameters live in one place and apply to every format by construction.
Stages are pure functions of `DrillData`, so each is unit-testable with no I/O — the suite
reached 359 tests at 98% coverage. New formats and new stages are additive.

**Cons:** More files and more indirection than the problem strictly demands at two output
formats — the design is priced for the third and fourth. Requires a reader to hold three
abstractions before reading any concrete code. Immutable value objects allocate more than
mutating a list would, which is irrelevant at panel scale (tens of holes) but would matter
if this ever processed PCB drill data (thousands).

---

## Trade-off Analysis

**The real question is not "which is cleanest" but "which failure can we not afford".**
For a tool whose output gets drilled into aluminium, silent disagreement between two
artifacts is the expensive failure. Option A and Option B both leave that failure
*possible but unlikely*; Option C makes it *structurally difficult*. That asymmetry
justifies the extra indirection even though the codebase is small.

**Option B was closer than it looks.** A shared helper achieves DRY, which was the
presenting complaint. It fails on OCP and on discoverability: it doesn't change where a
future contributor believes normalisation belongs. Architecture that depends on everyone
remembering a convention is a convention, not an architecture.

**The cost is real and should be named.** At two emitters, Option C is roughly 3× the code
of Option A for the same visible behaviour. That is only a good trade if DXF and further
formats actually arrive. If `aidrill` had been a one-off, Option A was correct.

**Evidence the choice was right, from the review that followed.** An independent
architecture review of the implemented design found the drawing emitter *still* re-deriving
the duplicate predicate — parallel implementation had reproduced the original sin in a new
place. The architecture is what made that finding cheap: the rule "emitters do not
re-derive" is stated, so the violation is a review finding rather than a matter of taste,
and the fix was to read the diagnostic's payload instead of recomputing it. Under Option B
the same defect would have been indistinguishable from normal code.

---

## Consequences

**Easier**

- Adding an output format: implement `Emitter`, decorate with `@register_emitter`, add one
  import. Proven by a test that dispatches the CLI to an emitter registered only inside
  the test file.
- Adding a preprocessing rule: implement `Stage`, insert it in `build_pipeline`. Every
  format inherits it.
- Testing: stages are pure; emitters take hand-built `DrillData`; no fixture file needed
  for most of the suite.
- Consuming `aidrill` as a library from the wider toolchain — `DrillData` is the contract,
  and the JSON emitter is its serialised form.

**Harder**

- Reading the code cold. Three protocols must be understood before any concrete module
  makes sense. `docs/SPEC.md` is load-bearing documentation, not a nicety.
- Anything genuinely cross-cutting between stages. The pipeline is a left fold with no
  shared context by design; a stage needing another stage's intermediate state would not
  fit and should prompt a rethink rather than a workaround.
- Emitter-specific preprocessing, if it ever turns out to be legitimate. The architecture
  forbids it. If a real case appears, it belongs as a stage with a format-scoped
  parameter, not as an exception.

**To revisit**

- `Diagnostic.data` is an untyped key/value payload. It solved the duplicate-identification
  problem cleanly, but if more than two or three codes carry structured payloads it should
  become per-code typed classes.
- The stage order is hardcoded in `cli.py`. Correct today; if it ever needs to vary per
  invocation, it becomes configuration, and stage independence (LSP) is what makes that
  safe.
- `Units` conversion happens per emitter. Fine at two; a third emitter needing inches
  would justify a shared conversion stage at the emit boundary.
- `AiPdfSource` is the only `Source`. The abstraction is currently speculative — it costs
  little, but if no second source appears within a few months it should be collapsed.

---

## Action Items

1. [x] Freeze the contracts — `model.py`, `protocols.py`, `errors.py`, `emitters/base.py`
2. [x] Implement geometry, source, stages and emitters against them (TDD, 359 tests, 98%)
3. [x] Independent architecture review; fix the confirmed findings
4. [x] Cross-artifact invariant test — parse the `.drl` and the `.svg` from one run and
       assert their tool maps and hole ordering agree
5. [ ] Add the DXF emitter — the real test of the OCP claim; if it needs any change
       outside its own module plus one import line, this ADR was wrong
6. [ ] Add `--paper` for true 1:1 A4/A3 output, so the drawing prints as a physical
       drill template
7. [ ] Publish `DrillData` as the integration contract for the enclosure fit-check
       toolchain, and record that dependency in a follow-up ADR
