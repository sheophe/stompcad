# CLAUDE.md

## Purpose and scope

`aidrill` reads drill geometry from Adobe Illustrator artwork and emits fabrication
artefacts. `DrillData` is the library integration contract and the JSON emitter is its
serialised form. Enclosure modelling, KiCad data, clearance checking, and component
semantics are outside the package's scope.

The output is used to drill aluminium, so every artefact from one invocation must agree.

## Development commands

Python 3.10 or later is required. Create the development environment with:

```bash
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
```

Run the project checks and tools from the repository root:

```bash
# Full suite
PYTHONPATH=src pytest -p no:cacheprovider -o addopts= --tb=short

# One test
PYTHONPATH=src pytest -o addopts= tests/test_pipeline.py::test_name -v

# Coverage
PYTHONPATH=src pytest -o addopts= --cov=aidrill --cov-report=term-missing

# Lint and types
ruff check src tests tools
mypy src/aidrill

# Mutation survey
PYTHONDONTWRITEBYTECODE=1 mutmut run
mutmut results

# Run the tool
PYTHONPATH=src python -m aidrill.cli PANEL.ai --emit excellon=out.drl --emit drawing-svg=out.svg
```

## Architecture

The accepted architecture is defined by:

- [ADR-0001](docs/adr/0001-pipeline-and-emitter-adapters.md): processing boundaries and
  artefact consistency.
- [ADR-0002](docs/adr/0002-domain-quantisers.md): domain answer sets and validation
  policy.
- [ADR-0003](docs/adr/0003-quantisation-boundary-and-ordering.md): the quantisation
  boundary, ordering, and termination rules.

The flow is `AiPdfSource -> RawDrillData -> quantise() -> DrillData -> Pipeline ->
Emitter`. The source reports measured floats in millimetres. Quantisation compares those
measurements with the enclosure, drill-size, and grid answer sets, then produces canonical
integer-nanometre data. The pipeline applies `Deduplicate`, `ReviewGridTies`, and
`SortHoles`. Emitters only translate frames, convert units, format, and serialise; shared
facts are computed once before the emitter fan-out.

`cli.py` owns quantiser and stage order. A stage must not depend on or assert that another
stage ran first. `Pipeline` depends only on the `Stage` protocol.

## Domain invariants

- The canonical frame is millimetres, Y-up, with the origin at the reference-outline
  centre. Emitters convert from it through model operations.
- Raw source lengths are finite float millimetres. Canonical lengths are integer
  nanometres, selected by exact decimal scaling before representation rounding.
- Positions snap to the declared grid, diameters to the selected drill standard, and the
  `Background` outline to the distributed enclosure catalogue. These answer sets are not
  interchangeable.
- Quantisation identifies the enclosure first, selects diameters second, and selects
  positions last. An enclosure error terminates quantisation; a rejected diameter records
  its diagnostic and omits only that hole.
- Any error withholds every requested artefact.
- Enclosure artwork uses published top-view/backplate dimensions, not the smaller drilled
  face. A two-dimensional outline identifies a footprint, not necessarily one part;
  ambiguous footprints require `--case`, and a declared case is always verified.
- `Hole.index` is stable source-order identity. `ReferenceOutline.raw` preserves the
  measured outline. Transform these values through the model rather than reconstructing
  them.
- Diagnostics, processing provenance, tool assignments, and ordering live on
  `DrillData`; emitters do not re-derive them. Match diagnostics by `code`, not message.

## Parsing constraints

- Illustrator's native save embeds the PDF-compatible stream read by `pikepdf`; Illustrator
  need not be running.
- Layers come from `/OCProperties` -> `/OCGs` and content mappings in
  `/Resources/Properties` -> `/MCn`. Only top-level layers are recoverable.
- Paths with neither fill nor stroke are absent from the stream.
- `W` and `W*` establish clipping boundaries; `n`, not `W`, makes a path invisible.
- Circle recognition validates four cubic Beziers by equal anchor radii and kappa
  consistency around their centroid, so it remains rotation-invariant.
- Apply every `cm` current transformation matrix, including a Form XObject's `/Matrix`.
- Object names are not recoverable because Illustrator files provide no structure tree.
- The reference outline is the largest non-circular path on the reference layer, not the
  document MediaBox.

## Documentation rules

- `docs/adr/` is the authority for architectural decisions. Update and accept an ADR
  before changing the architecture in code; other documentation links to ADRs instead of
  restating their arguments.
- Number diagrams within each ADR as `Figure 1`, `Figure 2`, and so on. Refer to them as
  `ADR-000N, Figure N` in the surrounding prose.
- Keep new or edited docstrings to at most ten physical lines. Put architectural rationale
  in an ADR and keep docstrings local to the code they document.
- Use British spelling in prose and established American spelling in identifiers.
- Keep `from __future__ import annotations` and an explicit, logically ordered `__all__`
  in each Python module. Value objects are frozen, slotted dataclasses whose transforms
  return replacements.

## Testing rules

- Use TDD. Keep stages pure where possible and test emitters with hand-built `DrillData`.
- Assert cross-artefact claims against emitted bytes by parsing each output format.
- A test must fail when the behaviour it names is removed. Check each clause of a compound
  condition independently, and ensure a mutation changes only the behaviour under test.
- Break accidental equality in fixtures: use out-of-order hole identities when testing
  identity rather than sequence position.
- Run mutation tests with bytecode generation disabled and inspect which test killed each
  relevant mutation. Mutation testing is a survey, not a numeric gate.
- Preserve property tests for snapping idempotence, deduplication idempotence, and tool
  stability under hole reordering.
- Coverage targets are 90% for `src/aidrill` and 100% for quantisers, stages, and emitters.
- Catalogue tests must re-read `docs/parts/dimensions.tsv` and prove that the generated
  module is current.
- Verification reports name the exact commands run; a tool invocation that suppresses the
  claimed rule is not evidence.
