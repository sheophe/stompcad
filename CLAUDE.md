# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`aidrill` extracts drill data from an Adobe Illustrator `.ai` file and emits it in a chosen fabrication format. That is the whole responsibility.

It deliberately does **not** model enclosures in 3D, read KiCad, check clearances, or know what a potentiometer is. Those belong to the wider pedal-design toolchain, which consumes `aidrill` as a library — `DrillData` is the integration contract and the `json` emitter is its serialised form. The SRP test for any proposed change is one sentence: *"aidrill turns panel artwork into drill data."* Anything that doesn't serve it goes elsewhere.

The output gets drilled into aluminium. The expensive failure is not a crash — it is two artifacts that describe the same panel and silently disagree.

## Development environment

The system Python has neither `pytest` nor `pikepdf`. You must work inside a virtual environment:

```bash
uv venv && uv pip install -e ".[dev]"
```

`pikepdf>=9` is the only runtime dependency. Python floor is 3.10 (`X | Y` annotations, `slots=True` dataclasses; no `match` statements).

## Commands

```bash
# Full suite. Pass -o addopts= because pyproject already sets -q, and a second
# -q suppresses the summary line entirely.
PYTHONPATH=src pytest -p no:cacheprovider -o addopts= --tb=short

# One test / one file
PYTHONPATH=src pytest -o addopts= tests/test_pipeline.py::test_name -v

# Coverage. SPEC 9 targets 90% of src/aidrill and 100% of the stages and emitters.
PYTHONPATH=src pytest -o addopts= --cov=aidrill --cov-report=term-missing

# Lint, format check, types
ruff check src tests
mypy src/aidrill

# Mutation testing — the suite is sub-second, so run it fully rather than sampling
mutmut run && mutmut results

# Run the tool
PYTHONPATH=src python -m aidrill.cli PANEL.ai --emit excellon=out.drl --emit drawing-svg=out.svg
```

Exit codes are a contract: `0` clean, `1` warnings present, `2` errors, `3` usage/IO failure.

## Architecture

Three roles, three protocols, one direction of flow:

```
Source ──▶ Pipeline of Stages ──▶ Emitter ──▶ artifact
 .ai/PDF    snap · normalize ·      excellon
            dedupe · validate ·     drawing-svg
            sort                    json
```

**The pipeline is universal, and this is the load-bearing rule.** Snapping, diameter normalisation and deduplication happen once, before any emitter sees the data. An earlier version clustered diameters inside the Excellon writer, so the drill file and the drawing could legitimately disagree about how many hole sizes a panel had — it emitted the same 7 mm bit as two tools. `docs/adr/0001-pipeline-and-emitter-adapters.md` records that incident and is worth reading before changing anything structural.

Consequences you must respect:

- **Emitters may translate frames and convert units. They may never round positions, cluster diameters, drop duplicates, sort, or renumber.** An emitter that re-derives a pipeline fact is a bug, not a style preference.
- **`DrillData.tools()` lives on the model**, not in the Excellon emitter, so the drill file's tool table and the drawing's hole schedule cannot disagree. Same for `tool_counts()`.
- **No stage may assert which stage ran before it** (LSP). Stage order is chosen by `cli.py`, never by a stage. A stage that only works after snapping is a design error.
- **`Pipeline` depends only on the `Stage` protocol** and contains no domain knowledge. Only `cli.py` names concrete classes.

### Canonical frame

Millimetres, Y-up, origin at the centre of the reference outline. Always. Emitters wanting another frame convert on output via `DrillData.with_origin()`; nobody hand-rolls the arithmetic. Inch conversion happens inside an emitter, at the last moment — no stage ever sees inches.

The reference frame comes from the reference layer's largest non-circular path bounding box, **never** from the PDF MediaBox: the artboard is not guaranteed to match the enclosure.

### Identity and provenance

Two fields exist specifically to stop information going stale, and both are easy to break:

- **`Hole.index`** is a required, deterministic identity assigned in source traversal order and preserved by every transform. Diagnostics refer to holes by it. Do not key on coordinates (a later stage moves them) and do not key on `RawHole` (two coincident circles share identical raw geometry — precisely the duplicate case).
- **`DrillData.processing`** is a tuple of `StageRun` records collected by `Pipeline.run` from each stage's `describe()`. `describe()` reports *effective* values, not raw constructor arguments. The drawing's title block reads the grid from here; it must never be handed a second copy through emitter options, or a library consumer gets a sheet stamping a grid the holes were never snapped to.

### Diagnostics

Stages append `Diagnostic`s; emitters render them. The CLI report, the drawing's NOTES block and the JSON output are three renderings of one finding, never three computations.

`code` is the stable machine key — **match on `code`, never on `message`**, in source and in tests. `Diagnostic.data` carries a small payload so a consumer can act on a finding without recomputing the predicate that produced it.

## Extending

- **New emitter:** implement the `Emitter` protocol, decorate with `@register_emitter`, add one import in `emitters/__init__.py`. The CLI resolves `--emit FORMAT=PATH` through the registry and never names a format. Note the honest limit recorded in ADR-0001: an emitter that needs its own CLI flags still requires a `cli.py` edit.
- **New stage:** implement `Stage` (including `describe()`), then insert it in `cli.build_pipeline`. Every output format inherits it. `build_pipeline` is the integration point by design, because order is the one thing a stage cannot self-declare.
- **New source:** implement `Source`. There is no source registry — `AiPdfSource` is currently the only one, and the abstraction is acknowledged as speculative.

## Parsing `.ai` files

Illustrator's native save embeds a PDF-compatible stream, read with `pikepdf`; Illustrator need not be running. Constraints verified against real files:

- Layers come from `/OCProperties` → `/OCGs`, mapped to content via `/Resources/Properties` → `/MCn`. **Top-level layers only** — sublayers fold into the parent OCG.
- Paths with neither fill nor stroke are absent from the PDF stream entirely. That is why `EmptyLayerError` tells the operator to give the drill circles a stroke.
- `W`/`W*` marks a clipping boundary, but **`n` is what makes a path invisible, not `W`** — a path that clips *and* paints is real geometry.
- Circles are 4 cubic Béziers with κ ≈ 0.5522847498; fitting validates via centroid with equal anchor radii plus a κ-consistency check, which is rotation-invariant where a bounding-box aspect test is not.
- The CTM from `cm` must be applied, including a Form XObject's own `/Matrix`.
- Object names are **not** recoverable — `.ai` files carry no structure tree. Do not design around them.

## Conventions

**House style is consistent and deliberate — match it rather than imposing an outside one.**

- Module docstrings explain *why*, naming the specific bug that motivated the design. This is the codebase's most distinctive trait and its highest-value documentation. `tolerance.py` and `formatting.py` exist purely because a decision made in six places is six decisions.
- British spelling in prose (`centre`, `millimetre`, `normalisation`, `colour`), American in identifiers (`NormalizeDiameters`).
- `from __future__ import annotations` and an explicit `__all__` in every module, ordered logically rather than alphabetically.
- Value objects are `@dataclass(frozen=True, slots=True)`; every transform returns a new instance via `replace()`.
- Float comparison goes through `tolerance.within()`; millimetre values print through `formatting.format_mm()`, which normalises negative zero away.

## Testing

TDD throughout — test first, then implementation. Stages are pure functions, so most of the suite needs no I/O; emitter tests take hand-built `DrillData`.

Two conventions matter more than coverage:

- **Assert on emitted bytes for cross-artifact claims.** The test that the drill file and the drawing agree re-parses the `.drl` as text and the `.svg` as XML. Asserting against the in-memory objects would pass even under the bug the architecture exists to prevent, because both emitters read the same `DrillData`.
- **A test that stays green when the behaviour it names is removed is not a test.** Before claiming a test covers something, mutate the implementation and confirm the test dies. The recurring trap here is a fixture where two quantities coincide numerically — holes numbered `0, 1, 2` in order make `index` indistinguishable from array position, so an assertion about identity silently also passes for position. Number fixtures out of order to break the coincidence.

Property tests cover snapping idempotence, dedupe idempotence, `tools()` stability under reordering, and cluster group spread.

## Documentation map

- `docs/SPEC.md` — the specification. **Load-bearing, not a nicety**: three protocols must be understood before any concrete module makes sense. Keep it in sync; a stale spec here is a defect.
- `docs/adr/` — architecture decisions with the incidents that drove them.
- `docs/PLAN.md` — the original implementation plan and agreed interfaces.
