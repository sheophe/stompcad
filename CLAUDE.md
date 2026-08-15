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

`pikepdf>=9` is the only runtime dependency. `pdfplumber` is a **development** dependency and must stay one: `tools/extract_1590.py` reads `docs/1590.pdf` with it to generate `src/aidrill/enclosures.py`, and the shipped catalogue is a literal table. Nothing under `src/aidrill` may import it — the runtime never opens the PDF, and `tests/test_enclosures.py` asserts as much.

Python floor is 3.10 (`X | Y` annotations, `slots=True` dataclasses; no `match` statements).

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

Flags: `--drill-layer`, `--reference-layer`, `--grid`, `--grid-warn`, `--drill-standard` (`metric` | `fractional`), `--drill-sizes` / `--no-drill-sizes` (narrow the standard to what is in the drawer), `--dedupe-tolerance`, `--case` (the Hammond base designator the panel is drawn for), `--emit`, `--title`, `-v`. All of them are resolved before the input file is opened, so a bad standard, an unstocked size or a part number in no catalogue is a usage error rather than a diagnostic.

`--diameters`, `--diameter-tolerance` and `--true-size` are gone. `--drill-sizes` kept its name and changed its meaning — it used to be the whole table and was ignored unless `--diameters table` was passed, so an old invocation that carried it as a no-op now takes bits out of the drawer.

Exit codes are a contract: `0` clean, `1` warnings present, `2` errors, `3` usage/IO failure. Exit 2 is reachable from `unknown-diameter`, `ambiguous-enclosure` and `wrong-enclosure`.

## Architecture

Three roles, three protocols, one direction of flow:

```
Source ──▶ Pipeline of Stages ──▶ Emitter ──▶ artifact
 .ai/PDF    snap · snap-diameters ·  excellon
            dedupe ·                 drawing-svg
            identify-enclosure ·     json
            sort
```

**The pipeline is universal, and this is the load-bearing rule.** Snapping, diameter quantisation, deduplication and enclosure identification happen once, before any emitter sees the data. An earlier version clustered diameters inside the Excellon writer, so the drill file and the drawing could legitimately disagree about how many hole sizes a panel had — it emitted the same 7 mm bit as two tools. `docs/adr/0001-pipeline-and-emitter-adapters.md` records that incident and is worth reading before changing anything structural.

**Each quantity snaps onto the domain's own answer set, not onto a number we chose.** Positions go to a declared grid, diameters to a declared drill standard (`DRILL_STANDARDS`, metric by default), and the reference outline to a Hammond 1590 catalogue footprint. We can no more make a custom bit than a custom case, which is why diameters do *not* snap to the grid: at `--grid 0.25` a measured 12.7 mm (1/2″) would become 12.75, a bit that exists in neither drawer. `docs/adr/0003-domain-quantisers.md` has the whole argument.

A hole whose diameter matches no size in the declared standard is an **ERROR** and is **dropped**, and a run with any ERROR writes **no artifacts at all** — the Excellon format renders no diagnostics, so a drill file missing a hole looks perfectly well-formed.

Consequences you must respect:

- **Emitters may translate frames and convert units. They may never round positions, cluster diameters, drop duplicates, sort, or renumber.** An emitter that re-derives a pipeline fact is a bug, not a style preference.
- **`DrillData.tools()` lives on the model**, not in the Excellon emitter, so the drill file's tool table and the drawing's hole schedule cannot disagree. Same for `tool_counts()`.
- **No stage may assert which stage ran before it** (LSP). Stage order is chosen by `cli.py`, never by a stage. A stage that only works after snapping is a design error.
- **`Pipeline` depends only on the `Stage` protocol** and contains no domain knowledge. Only `cli.py` names concrete classes.

### Canonical frame

Millimetres, Y-up, origin at the centre of the reference outline. Always. Emitters wanting another frame convert on output via `DrillData.with_origin()`; nobody hand-rolls the arithmetic. Inch conversion happens inside an emitter, at the last moment — no stage ever sees inches.

The reference frame comes from the reference layer's largest non-circular path bounding box, **never** from the PDF MediaBox: the artboard is not guaranteed to match the enclosure. `IdentifyHammondFootprint` then snaps that measured outline to the catalogue footprint it matches — the fixture measures 113.000 × 60.000 and comes out 112 × 61 — keeping the measurement in `ReferenceOutline.raw`.

### The backplate convention

**The Background layer must be drawn to the enclosure's BACKPLATE dimensions.** The catalogue stores backplate sizes, and a Hammond 1590 is die-cast with tapered walls ("low side wall draft angle (2° or less)", per the datasheet), so the face that actually gets drilled is smaller by `2 · d · tan θ` per axis — 1.9 mm on a 1590B, 6.3 mm on a 1590V.

No tolerance can accept a face-drawn outline: matching one needs at least 2.4 mm on the shallowest common part, while two footprints tie at 2.0 mm because the closest pair in the catalogue is 4 mm apart. Required ≥ 2.4, permitted < 2.0. So the operator who carefully measures the face they are about to drill is the one who gets `unknown-enclosure` — which is why that message names the convention, and why this paragraph exists. Do not "fix" it by widening `IdentifyHammondFootprint`'s tolerance; that trades a refusal for a guess between two real enclosures. `docs/adr/0003-domain-quantisers.md` has the arithmetic.

### Identity and provenance

Four fields exist specifically to stop information going stale, and every one of them is easy to break:

- **`Hole.index`** is a required, deterministic identity assigned in source traversal order and preserved by every transform. Diagnostics refer to holes by it. Do not key on coordinates (a later stage moves them) and do not key on `RawHole` (two coincident circles share identical raw geometry — precisely the duplicate case).
- **`ReferenceOutline.raw`** is the outline as the artwork actually measured. `IdentifyHammondFootprint` rewrites the nominal size, so without `raw` nothing downstream can tell a 113 that was *measured* from a 113 that was *snapped to* — its absence once sent a nominal size out as though it were what the artwork said. Constructing a fresh `ReferenceOutline(112.0, 61.0)` is legal code whose `raw` defaults to its own dimensions, which is exactly that lie written by hand; go through `resized()`.
- **`DrillData.enclosure`** is a *conclusion*, which is why it is neither `SourceInfo` (where the bytes came from) nor a `StageRun` (what a stage was configured to do). It is replaced, never appended: "which enclosure is this panel?" gets one answer or `None`, never a list to pick from. A 2-D outline identifies a **footprint, never a part** — 37 catalogue parts collapse into 22 footprints — so the match names `candidates` and `selected_part` is only ever what the operator declared with `--case`.
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
- British spelling in prose (`centre`, `millimetre`, `normalisation`, `colour`), American in identifiers (`SnapDiametersToDrillTable`, `normalize_part_name`).
- `from __future__ import annotations` and an explicit `__all__` in every module, ordered logically rather than alphabetically.
- Value objects are `@dataclass(frozen=True, slots=True)`; every transform returns a new instance via `replace()`.
- Float comparison goes through `tolerance.within()`; millimetre values print through `formatting.format_mm()`, which normalises negative zero away.

## Testing

TDD throughout — test first, then implementation. Stages are pure functions, so most of the suite needs no I/O; emitter tests take hand-built `DrillData`.

Two conventions matter more than coverage:

- **Assert on emitted bytes for cross-artifact claims.** The test that the drill file and the drawing agree re-parses the `.drl` as text and the `.svg` as XML. Asserting against the in-memory objects would pass even under the bug the architecture exists to prevent, because both emitters read the same `DrillData`.
- **A test that stays green when the behaviour it names is removed is not a test.** Before claiming a test covers something, mutate the implementation and confirm the test dies. The recurring trap here is a fixture where two quantities coincide numerically — holes numbered `0, 1, 2` in order make `index` indistinguishable from array position, so an assertion about identity silently also passes for position. Number fixtures out of order to break the coincidence.

Three mechanics that have each produced a wrong answer in this repo:

- **Run mutations with `python -B`.** A `.pyc` is validated against the source's `(mtime, size)`, and the header stores mtime in **whole seconds** — so a same-size mutation applied and reverted inside one second executes stale bytecode. That silently yields either a false survivor or, worse, the *previous* mutation's kill list attributed to the current one.
- **Mutate each clause of a condition, not the condition as a unit.** Removing or misgating a check tests it as a whole; `if x or y` needs `if y` and `if x` mutated separately. A guard covering two axes lost half its coverage here, invisibly, because folding two tests kept one fixture and dropped the other — and the surviving test's name and docstring still described the full behaviour, so nothing *looked* missing.
- **A mutation must change only the thing it names.** An impure mutation produces a falsely *strong* result: editing a value where it is both compared and emitted gets "killed" by tests that merely noticed the changed output, proving nothing about the comparison. If a mutation dies, check *which* test died and whether it had any business dying.

Applies to verification tooling too: a linter invoked with a flag that suppresses the rule you are claiming to pass is not evidence. Report the command, not just the result.

Property tests cover snapping idempotence, dedupe idempotence and `tools()` stability under hole reordering. `tests/test_enclosures.py` additionally re-extracts `docs/1590.pdf` on every run, so a datasheet revision is a red test rather than a quiet disagreement.

## Documentation map

- `docs/SPEC.md` — the specification, currently v2.0. **Load-bearing, not a nicety**: three protocols must be understood before any concrete module makes sense. Keep it in sync; a stale spec here is a defect.
- `docs/adr/` — architecture decisions with the incidents that drove them. 0001 is the pipeline and the emitter adapters; 0003 is the drill standards, the enclosure catalogue and the backplate convention. There is no 0002 — it was planned and never written, and the gap is left rather than renumbered.
- `docs/1590.pdf` — the Hammond datasheet `src/aidrill/enclosures.py` is generated from. It is the authority for every catalogue number; `tools/extract_1590.py` is the audit trail, and `tests/test_enclosures.py` re-extracts on every suite run.
- `docs/parts/` — Hammond's 37 per-part drawings, plus `dimensions.tsv`, which carries the same 37 parts at 0.05 mm where `docs/1590.pdf` gives whole millimetres. **Not the shipped catalogue** — `enclosures.py` is still generated from `docs/1590.pdf`, and nothing at runtime reads this directory. `docs/parts/README.md` says what the TSV holds and where the two disagree; the adoption plan is in `docs/BACKLOG.md`.
- `docs/PLAN.md` — **historical.** The task breakdown for the original v1.0 build, kept as a record. Its interfaces are superseded; read SPEC and the ADRs for what is true now.
- `docs/BACKLOG.md` — agreed work that is deliberately not scheduled.
