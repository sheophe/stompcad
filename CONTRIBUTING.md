# Contributing

See the [README](README.md#install) for environment setup and
[architecture overview](docs/ARCHITECTURE.md) for the package structure.

## Run the checks

Run these commands from the repository root. The parentheses keep each package
command in its own working directory, so you can run the block as written.

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
(cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q)
(cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q)
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
```

The root pytest configuration covers only `stompdrill`. Each package has a
`tests` package, so run their suites in separate Python processes to avoid
module-name conflicts.

Two suites use real geometry fixtures:

- `--hammond` enables tests using published Hammond models downloaded and
  cached at run time. Omit it for a quicker `stompdrill` run without those tests.
- `--boards` enables `stompcollider` tests using the committed board STEP
  fixture. Omit it to skip those tests.

The kernel is required by both tools. A failed kernel import is a test failure;
it is not a reason to skip a test. The flags above control fixture-based tests.

Run lint and type checks:

```bash
ruff check packages tools
mypy packages
(cd packages/stompmodel && uv run --no-sync mypy)
(cd packages/stompgeom && uv run --no-sync mypy)
(cd packages/stompcollider && uv run --no-sync mypy)
```

The root mypy run includes `stompdrill`'s tests. Each other package's mypy
configuration checks its own tests in a separate run.

To run one test:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_pipeline.py::test_a_collapsed_pair_reports_one_hole_dropped -v
```

### Coverage

Measure each package with its own tests:

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond \
  --cov=stompdrill --cov-report=term-missing
(cd packages/stompmodel && uv run --no-sync pytest -o addopts= \
  --cov=stompmodel --cov-report=term-missing)
(cd packages/stompgeom && uv run --no-sync pytest -o addopts= \
  --cov=stompgeom --cov-report=term-missing)
(cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards \
  --cov=stompcollider --cov-report=term-missing)
```

Targets are 90% for each package and 100% for quantisers, stages, emitters and
`stompmodel`'s codec. `stompcollider.match` and `seat` count as stages. Include the
kernel suites when measuring the STEP reader, writer, cutter, board sources and
assembly emitter. `stompdrill` needs `--hammond` to reach its overall target.

## Write tests that detect the change

Use TDD for code changes. Keep stages pure where possible and test emitters with
hand-built `DrillData`.

Check cross-format claims by parsing the emitted bytes. The read-back helpers
must be independent of the code that wrote the output:

- `packages/stompdrill/tests/recovery/` contains Excellon, SVG and PDF readers
  and their shared facts. It must not import `stompdrill`.
- `packages/stompcollider/tests/recovery/` reads the JSON report and STEP
  assembly. It must not import `stompcollider` or `stompgeom`.

AST tests enforce these import restrictions. Inverting an emitter's own
transform would only test its internal consistency.

A test must fail when the behaviour it describes is removed. For compound
conditions, check each clause separately and keep each deliberate mutation
limited to the behaviour being tested. Use fixtures that distinguish correct
behaviour from plausible mistakes. For example, store routed holes out of tuple
order to check that an emitter reads `DrillData.numbered()`.

A check that could pass without examining anything needs a control in the same
suite. Introduce a deliberate breach and show that the check fails. This
applies to structural scans, ordering checks and properties that may never
reach the relevant branch. A record of a manual check is insufficient.

Preserve property tests for snapping onto the grid, staying within half a pitch,
idempotence and tool stability under hole reordering. Deduplication idempotence
is already implied by exact integer equality; it does not need a property test
that cannot fail under that model.

Test clearance rules with a fake `CaseModel`, alongside kernel tests using
real models. Catalogue tests must reread `docs/parts/dimensions.tsv` and verify
that the generated module is current. Type-check tests as well as source:
helpers can accept plain literals and brand them internally, while direct model
construction wraps lengths explicitly.

When reporting verification, include the commands you ran and their results.
Ensure their options actually enable the checks you claim. Avoid recording test
counts or mutation-survivor totals in standing documentation; use the commands
to obtain current results.

## Check output preservation

`tools/verify-lock.sh` compares complete output bytes across a change. Capture
a reference before the change, then verify afterwards:

```bash
bash tools/verify-lock.sh
```

The script selects capture or verification according to whether the reference
exists. Panel A requires the `1590B` model in the cache; the script prints the
fetch command if it is missing. See [ADR-0011](docs/adr/0011-behaviour-lock-and-its-blind-spots.md)
for the procedure, environment constraints and coverage limits.

The reference stays ignored, normally under `.scratch/lock/`. Do not commit a
`SHA256SUMS` file. This check supplements the tests; it exercises two successful
CLI runs and does not cover failure paths or every option.

## Mutation testing

Run each package's survey with bytecode generation disabled:

```bash
(cd packages/stompmodel && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompgeom && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompdrill && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompcollider && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
```

There is no workspace-wide mutation run. Read the results by module and inspect
which test killed each relevant mutation. Treat the survey as evidence to
investigate, rather than a numeric gate.

Many survivors in drawing layout, CLI help and formatting change labels,
offsets or font sizes. Prioritise survivors in geometry, quantisation,
validation, units, sheet calculations and drawing layout decisions that affect
shared facts. For `stompcollider`, inspect `match`, `seat`, `clash`,
`canonicalise` and `designators`; for `stompgeom`, inspect the kernel guard,
STEP reader and deterministic writer.

The `_kappa_consistent` survivors have already been investigated: tests killed
some and the remainder were shown equivalent. Other survivors in `geometry`
still need individual analysis.

## Extend the tools

### Add an emitter

Implement `stompmodel`'s `Emitter` protocol, decorate it with
`@register_emitter`, and import it in `stompdrill/emitters/__init__.py`. The CLI
looks up `--emit` formats through the registry. An emitter needing new CLI
options also requires a `cli.py` change.

Return a `str` or `bytes` payload; let the CLI stage and commit it through
`stompmodel.protocols`. Unsupported constructor requirements produce a usage
error (exit 3, no output). Exceptions from the emitter's later `emit` call keep
their traceback. Drawing backends expose `render(scene, title)`.

### Add a stage

Implement `stompmodel`'s `Stage` protocol, including `describe()`, and insert the
stage in `cli.build_pipeline`. The caller chooses stage order. Export a new
`stompdrill` stage from `packages/stompdrill/src/stompdrill/__init__.py`.

### Add a source

Implement `stompdrill`'s `Source` protocol and return `RawDrillData`. Export the
source from `packages/stompdrill/src/stompdrill/__init__.py`.

Sources are a library extension point. The CLI always uses `AiPdfSource`; there
is no source-selection flag or registry. Add CLI selection when a real second
source needs it.

The package root exports stages and sources because they have no registry.
Emitters are retrieved through `stompdrill.emitters.get_emitter` and don't need
root exports. `METRIC_BANDS` and `FRACTIONAL_SIXTY_FOURTHS` remain in
`stompdrill.pipeline`, where they generate the drill standards.

## Update the enclosure catalogue

Edit `docs/parts/dimensions.tsv`, then regenerate the module:

```bash
.venv/bin/python tools/build_catalogue.py
```

Do not edit `packages/stompdrill/src/stompdrill/enclosures.py` directly. See the
[catalogue notes](docs/parts/README.md) for dimension conventions and sources.

## Code and documentation conventions

Use SOLID and DRY to reduce duplication and keep responsibilities clear. Add an
interface or layer when there is a concrete need for it. Duplicate rules and
modules that change for unrelated reasons are useful review signals.

Keep `from __future__ import annotations` and an explicit, logically ordered
`__all__` in every Python module. Value objects are frozen, slotted dataclasses;
transforms return replacements.

Use British spelling in prose and established American spelling in identifiers.
Keep new or edited docstrings to ten physical lines or fewer. The documentation
test audits source, tests and tools and reports longer docstrings as warnings.
Keep docstrings local to their code and put architectural reasons in ADRs.

Update and accept an ADR before changing architecture in code. Other documents
should link to the decision. Number diagrams within each ADR as `Figure 1`,
`Figure 2`, and so on, and cite them as `ADR-000N, Figure N`.

[docs/FOUNDATION.md](docs/FOUNDATION.md) is the one exception, and deliberately.
It states an abstract model, so it cites nothing: no ADR, no module, no test, and
nothing observed while building the software. Citation runs inward only — an ADR
may appeal to the model, never the reverse — because a model carrying references
to the thing it models cannot be read on its own terms. Where the software shows
the model inaccurate, amend the model as mathematics rather than annotating it
with the evidence.

Working plans, specs and issues live in ignored directories. Keep durable
architectural decisions in [docs/adr/](docs/adr/) and definitions in the
[glossary](docs/GLOSSARY.md). [CLAUDE.md](CLAUDE.md) collects the agent-specific
instructions and domain constraints.

### Writing style

Give each paragraph one main job. Keep instructions, examples and practical
limits in user guides; put implementation details and design arguments in
architecture notes. Use the glossary to explain technical distinctions.

State requirements directly. Avoid repeated rebuttals, dramatic absolutes and
claims about how rigorous the design is. Reserve bold text for instructions or
details readers need to notice. Check that edits preserve defaults, flags,
units, guarantees and their exceptions.
