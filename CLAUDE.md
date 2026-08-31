# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in
this repository.

## Purpose and scope

`stompdrill` reads drill geometry from Adobe Illustrator artwork and emits fabrication
artefacts. `DrillData` is the library integration contract and the JSON emitter is its
serialised form. KiCad data and component semantics are outside `stompdrill`'s scope.

`stompcollider` is the second tool. It takes that drill document, a **drilled** case
model and one or more board models, seats each board on the holes its panel-reference
parts pair with, and reports where anything clashes. It drills nothing and resolves no
collision away: seeing the interference is the point.

Enclosure geometry enters only as a supplied model: `stompdrill` never synthesises an
enclosure, and reads one only to verify clearance and to cut the holes it has already
decided on. Acquiring that model is not the package's job — see
`tools/fetch_case_model.py`.

The output is used to drill aluminium, so every artefact from one invocation must agree.

## Development commands

Python 3.10 or later is required. Create the development environment with:

```bash
uv venv
uv sync --all-packages
source .venv/bin/activate
```

That is the whole install: there is no optional extra to opt into. The `cadquery-ocp`
geometry kernel is `stompgeom`'s unconditional dependency, so the STEP features
(`--case-model`, `--emit step=…`) arrive with the command above. The kernel is large —
it pulls in vtk and matplotlib transitively — and every install now pays for it.
[ADR-0007](docs/adr/0007-case-model-and-clearance.md) records the optional extra this
replaced.

`pdfminer.six` is declared only in `packages/stompdrill/pyproject.toml`'s dev group,
because `tests/recovery/pdf.py` imports it and ADR-0008's governing test is that each
member passes its own tests alone. `hypothesis` is declared there too, and in the root's
dev group, `stompmodel`'s and `stompcollider`'s, for the same reason. Both arrive with a
plain `uv sync --all-packages`.

Run the project checks and tools from the repository root:

```bash
# stompdrill's suite (root testpaths cover only this package; see
# "Testing rules" below for every member's own command)
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --tb=short

# One test
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_pipeline.py::test_name -v

# Coverage, per package. The root testpaths cover only stompdrill, so measuring
# another member through it reports a package no test in scope imports end to
# end and grades its codec far below the 100% target below.
.venv/bin/python -m pytest -o addopts= --cov=stompdrill --cov-report=term-missing
cd packages/stompmodel && uv run --no-sync pytest -o addopts= \
  --cov=stompmodel --cov-report=term-missing
cd packages/stompgeom && uv run --no-sync pytest -o addopts= \
  --cov=stompgeom --cov-report=term-missing
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards \
  --cov=stompcollider --cov-report=term-missing

# Lint and types. `mypy packages` excludes every member's own tests but
# stompdrill's -- four `tests` packages cannot share one scan -- so each
# member's own config is a second gate.
ruff check packages tools
mypy packages
cd packages/stompmodel && uv run --no-sync mypy
cd packages/stompgeom && uv run --no-sync mypy
cd packages/stompcollider && uv run --no-sync mypy

# Kernel tests against real Hammond models (downloads and caches them)
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond --tb=short

# stompcollider's kernel-backed tests, which read its committed board fixture
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q

# Behaviour lock: whole artefacts from two panels, hashed. Capture before a change
# that must move no artefact byte, then run again after. It is not a gate on HEAD
# and no reference is committed; panel A needs the 1590B model cached. See ADR-0011
# for what a green run does not reach.
bash tools/verify-lock.sh

# Mutation survey, per package -- there is no workspace-wide run
(cd packages/stompmodel && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompgeom && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompdrill && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)
(cd packages/stompcollider && PYTHONDONTWRITEBYTECODE=1 ../../.venv/bin/mutmut run \
  && ../../.venv/bin/mutmut results)

# Regenerate the enclosure catalogue after editing docs/parts/dimensions.tsv.
# stompdrill/enclosures.py is generated; edit the TSV, never the module.
.venv/bin/python tools/build_catalogue.py

# Run the tool (installed as the `stompdrill` console script too)
python -m stompdrill.cli PANEL.ai --emit excellon=out.drl --emit drawing-svg=out.svg

# Cut a supplied Hammond enclosure and check clearance
python tools/fetch_case_model.py 1590BB   # downloads and prints the cached .stp path
python -m stompdrill.cli PANEL.ai --case 1590BB \
  --case-model ~/.cache/stompcad/cases/1590BB.stp \
  --emit step=out.stp
```

## Command-line contract

Flags: `--drill-layer`, `--reference-layer`, `--grid` and `--grid-warn` (both in
**millimetres**; the pitch must be a whole number of microns, and one finer than a micron
is clamped to one with `grid-too-fine`), `--drill-standard` (`metric` | `fractional`),
`--drill-sizes` / `--no-drill-sizes` (narrow the standard to the sizes in the drawer),
`--case` (the Hammond 1590 base designator the panel is drawn for), `--case-model`,
`--case-face` (`box` | `lid`) and `--case-margin` (a supplied enclosure model, which face
it is drilled against, and the clearance margin), `--form-depth` (how many levels of
nested Form XObject the reader follows), `--emit FORMAT=PATH` (repeatable), `--title`,
`-v`. All are resolved before the input file is opened, so a bad standard, an unstocked
size, or a part number in no catalogue is a usage error rather than a diagnostic.

`--emit` formats come from the registry: `drawing-pdf`, `drawing-svg`, `excellon`,
`json`, `step`.

The requested `--emit` targets are validated once, as a set, before anything is
rendered: two targets may not reach one file, compared as a case- and
normalisation-folded key over each target's *resolved* path, because a filesystem may
hold two such spellings, or two paths joined by a symlink, as one file; and every
target that already exists must be a regular file. The write
mechanism's own preconditions are not restated there — it enforces and reports them
itself; see
[ADR-0005](docs/adr/0005-binary-emitter-payloads.md) and
[ADR-0001](docs/adr/0001-pipeline-and-emitter-adapters.md). A run that fails this
check, or fails while writing, writes none of its requested artefacts and leaves
every existing target exactly as it was, modulo the one named exclusion.

`drawing-pdf` writes an ISO 5457 sheet at 1:1, choosing the smallest of A4 portrait, A3,
A2, A1 and A0 landscape that holds the panel. ISO 5457 §4.1 fixes the orientation of each
size, so there is no orientation to choose.

Exit codes are a contract: `0` clean, `1` warnings present, `2` errors, `3` usage or IO
failure. Exit 2 is reachable from `unknown-diameter`, `ambiguous-enclosure`,
`unverifiable-enclosure`, `unmatched-enclosure`, `wrong-enclosure`, `hole-off-face`,
`hole-through-boss`, `hole-obstructed` and `wrong-case-model`. `grid-too-fine`,
`grid-ambiguous`, `hole-outside-outline`, `nesting-truncated`,
`case-orientation-unverifiable` and `off-size` are warnings and reach exit 1.

`stompcollider`'s own command line is `DRILL.json BOARD.stp …` with `--case-model`,
`--panel-reference`, `--match-tolerance`, `--fit-clearance`, `--report`, `--assembly`
and `-v`; there is
no `--case-face`, because the drill document carries the face frame `stompdrill` cut
in. `--fit-clearance` is how much wider than a part its hole must be, stated **on
diameter** and so contributing half its value to a radius; it defaults to 0.1 mm and
zero is a legal value, being the strict fit the comparison already is. It is the one
number the board reader needs before it can measure anything, because a component's
profile is measured by cutting the solid at the radii this panel's holes admit. `--match-tolerance` is **optional**: it defaults to half the grid pitch the drill
document records under its `snap` run, which is the derivation the flag's own help
used to ask the operator to perform by hand. A supplied value overrides it; a document
recording no usable pitch is a usage failure naming the flag, never a guessed
tolerance. Do not restore the requirement, and do not invent a default pitch — the
tolerance decides which hole pairs with which part. The value a run actually matched
with is printed in the report's `CASE` block.
`--place` and `--pin` are accepted and parsed, so a bad ordinal is still a usage
error naming that ordinal — and then **refused with a stated reason**, because nothing
downstream honours either: no stage places a board explicitly, and `Clashes` re-ranks
after a pinned rank could have been held. Do not make either silently do nothing.

`packages/stompdrill/tests/fixtures/tar.ai` is within tolerance of both `1590B`/`1590B2`
(112.40 × 60.50) and `1590BS` (112.00 × 60.50), so it needs `--case 1590B`. Undeclared it
is `ambiguous-enclosure`, an error. This is the correct answer, not a regression: do not
widen the tolerance, special-case the fixture, or round the footprint key back to whole
millimetres.

## Architecture

The workspace is `packages/stompmodel`, `packages/stompgeom`, `packages/stompdrill`
and `packages/stompcollider`, in that dependency order; each installs and passes its
own tests alone, which is ADR-0008's governing test. `stompcollider` depends on
`stompmodel` and `stompgeom` and on neither `stompdrill` nor a kernel binding of its
own: it reads a drill document through `stompmodel`'s codec and reaches OCP only
through `stompgeom`, which `packages/stompcollider/tests/test_package_boundary.py`
enforces.

The accepted architecture is defined by:

- [ADR-0001](docs/adr/0001-pipeline-and-emitter-adapters.md): processing boundaries and
  artefact consistency.
- [ADR-0002](docs/adr/0002-domain-quantisers.md): domain answer sets and validation
  policy.
- [ADR-0003](docs/adr/0003-quantisation-boundary-and-ordering.md): the quantisation
  boundary, ordering, and termination rules.
- [ADR-0004](docs/adr/0004-unit-newtypes.md): the branded length units.
- [ADR-0005](docs/adr/0005-binary-emitter-payloads.md): the binary emitter payload.
- [ADR-0006](docs/adr/0006-toolpath-ordering-and-hole-numbering.md): toolpath ordering and
  hole numbering.
- [ADR-0007](docs/adr/0007-case-model-and-clearance.md): supplied case models,
  clearance, and the kernel dependency.
- [ADR-0008](docs/adr/0008-workspace-and-shared-geometry-core.md): the workspace and
  the shared geometry core.
- [ADR-0009](docs/adr/0009-shared-model-package-and-dependency-order.md): the shared
  model package and the workspace's dependency order.
- [ADR-0010](docs/adr/0010-the-stomp-prefix.md): the `stomp` prefix every package
  carries.
- [ADR-0011](docs/adr/0011-behaviour-lock-and-its-blind-spots.md): the behaviour
  lock, its uncommitted reference, and what a green run does not prove.

`stompmodel` publishes the guards a measurement's unit must satisfy — `check_millimetres`
and `check_nanometres` — beside the newtypes they check, and the diagnostics vocabulary a
second tool's value type interoperates through: `Diagnosable`, and the plain-tuple
`of_severity`/`worst_severity` reductions beside `Diagnostic`, and the `latest_run`
reduction beside `StageRun` for the same reason. It also owns what a *document* means
where two tools must agree on it: `SNAP_STAGE` and `SNAP_GRID_PARAMETER` are the
snapping stage's name and pitch key spelled once for the whole workspace, and
`DrillData.grid_nm` is the one read of them — `stompdrill` records the pitch and
reviews grid ties through it, `stompcollider` derives its recognition tolerance from
it, and neither spells either literal. The `DrillData` JSON codec is
versioned; the document is at version 6, whose `CaseRegistration` member carries the
resolved part, drilled face, supplied model's file name and cutting frame as one typed fact
rather than four — see [ADR-0009](docs/adr/0009-shared-model-package-and-dependency-order.md).
`stompgeom` owns the kernel layer across every side it touches: reading, where
`stompgeom.step` publishes the one rule for what XCAF recorded as a label's name,
distinguishing an unnamed label from OCC's own synthesised placeholder; writing, where
`stompgeom.writer.render_step` is the one serialising entry point and returns the finished
STEP payload rather than a path; partitioning, where `stompgeom.levels()` groups a
solid's planar faces into the planes they lie in; and building, where
`stompgeom.build.build_document` assembles a document from placed, named, coloured solids
— see [ADR-0008](docs/adr/0008-workspace-and-shared-geometry-core.md).

The flow is `AiPdfSource -> RawDrillData -> quantise() -> DrillData -> Pipeline ->
Emitter`. The source reports measured floats in millimetres. Quantisation compares those
measurements with the enclosure, drill-size, and grid answer sets, then produces canonical
integer-nanometre data. The pipeline applies `Deduplicate`, `ReviewGridTies`, `RouteHoles`
and `CheckOutlineContainment`, and `CheckCaseClearance` too when a case model is supplied.
Emitters only translate frames, convert units, format, and serialise; shared facts are
computed once before the emitter fan-out.

`quantise()` owns enclosure, diameter, then position ordering. The CLI explicitly composes
the post-quantisation stage order in `cli.build_pipeline`. A stage must not depend on or
assert that another stage ran first; `Pipeline` depends only on the `Stage` protocol.

Both drawing emitters share `emitters/drawing/`: `content` holds the facts a sheet states,
`layout` resolves a sheet's geometry, and `build` turns the two into a `Scene` of
primitives. `drawing_svg` and `drawing_pdf` only serialise that scene, each through its
own public `render(scene, title)` method — the seam between building a `Scene` and
serialising it. They differ in which unknown they solve for: SVG fixes the sheet and fits
the scale, PDF fixes the scale at 1:1 and walks the ISO 5457 candidates.
`packages/stompdrill/tests/test_drawing_agreement.py` parses both artefacts and compares
what they say about one panel; the sheets may list different numbers of rows, but never
differ about a row they both show. A `DrawingOptions(scale=…)` that overflows the chosen
sheet draws the shared `CONTENT EXCEEDS` marker rather than clipping silently; there is no
`--scale` flag, so only a library caller supplying an explicit scale reaches it, never the
CLI.

## Domain invariants

- Canonical coordinates use a Y-up frame with the origin at the reference-outline centre.
  Emitters convert from it through model operations.
- Raw source lengths are finite float millimetres. Canonical lengths are integer
  nanometres, selected by exact decimal scaling before representation rounding.
- Lengths carry their unit in the type: `Millimetre` for a measurement, `Nanometre` for
  every canonical length, `Micron` for the effective grid pitch. Arithmetic drops the
  brand, so a scaled result is re-wrapped where it becomes a length again. Brand at a real
  conversion, never everywhere — see [ADR-0004](docs/adr/0004-unit-newtypes.md).
- Positions snap to the declared grid, diameters to the selected drill standard, and the
  `Background` outline to the distributed enclosure catalogue. These answer sets are not
  interchangeable.
- Quantisation identifies the enclosure first, selects diameters second, and selects
  positions last. An enclosure error terminates quantisation; a rejected diameter records
  its diagnostic and omits only that hole — see
  [ADR-0003](docs/adr/0003-quantisation-boundary-and-ordering.md).
- Any error withholds every requested artefact.
- Enclosure artwork uses published top-view/backplate dimensions, not the smaller drilled
  face. A two-dimensional outline identifies a footprint, not necessarily one part;
  ambiguous footprints require `--case`, and a declared case is always verified.
- A hole whose extent leaves the reference outline is a warning, not an error: the outline
  bounds the panel as identified — the catalogue footprint once an enclosure matched, the
  drawn outline otherwise — not the drilled face the bit meets. The face check needs a
  supplied model and errors — see [ADR-0002](docs/adr/0002-domain-quantisers.md).
- Geometry alone determines output: two inputs representing the same geometry produce
  byte-identical artefacts, whatever their element order. No rule may consult input order
  — see [ADR-0006](docs/adr/0006-toolpath-ordering-and-hole-numbering.md).
- `Hole.index` is the drill sequence, `1…n`, assigned only by `RouteHoles` and `None`
  before it. Each tool occupies one contiguous block; holes route within a block. Emitters
  read numbers through `DrillData.numbered()`, which refuses unrouted data.
- `ReferenceOutline.raw` preserves the measured outline. Transform these values through
  the model rather than reconstructing them.
- Diagnostics, processing provenance, tool assignments, and ordering live on `DrillData`;
  emitters do not re-derive them. Match diagnostics by `code`, not message.

## Parsing constraints

- Illustrator's native save embeds the PDF-compatible stream read by `pikepdf`;
  Illustrator need not be running.
- Layers come from `/OCProperties` -> `/OCGs` and content mappings in
  `/Resources/Properties` -> `/MCn`. Only top-level layers are recoverable.
- Paths with neither fill nor stroke are absent from the stream, which is why
  `EmptyLayerError` names the remedy: give the drill circles a stroke.
- `W` and `W*` mark a clipping path but are not tracked as a clip region; `n`, not `W`,
  makes a path invisible.
- The page's own crop box — its media box when none is declared (ISO 32000-1 §14.11.2) —
  and every Form XObject's declared `/BBox` (ISO 32000-1 §8.10.2) are each an
  unconditional clip, carried through the walk as **one** inherited region rather than
  two policies: entering a form intersects its box, mapped through the form's own
  `/Matrix` and the current matrix, into the region inherited from the page and every
  enclosing form. Nested forms intersect cumulatively; no unconditional box is exempt
  because no test named it.
- The culling decision is taken on the quantity the recovered feature actually is. A
  recognised circle is judged by its **centre** — a hole is point-like, so a circle
  painting only a thin crescent inside the clip is not a hole, however far its bounding
  box reaches into it. Any other feature, an outline candidate among them, is judged by
  its **extent**, so a path merely straddling the region's edge is kept.
- Circle recognition validates four cubic Beziers by equal anchor radii and kappa
  consistency around their centroid, so it remains rotation-invariant.
- Apply every `cm` current transformation matrix, including a Form XObject's `/Matrix`.
- Form XObjects nest. The reader follows `--form-depth` levels and reports
  `nesting-truncated` only when it refused a form that was really there — a limit nobody
  reached is not news. Artwork below a refused level reaches no artefact and no report, so
  silence about it is not evidence of correctness.
- Object names are not recoverable because Illustrator files provide no structure tree.
- The reference outline is the largest non-circular path on the reference layer, not the
  document MediaBox.

## Extending

- **New emitter:** implement `stompmodel`'s `Emitter` protocol, decorate with
  `@register_emitter`, add one import in `emitters/__init__.py`. The CLI resolves
  `--emit FORMAT=PATH` through the registry and never names a format. An emitter needing
  its own CLI flags still requires a `cli.py` edit. A registered emitter whose constructor
  needs something this CLI cannot supply is refused as a usage failure (exit 3, no
  artefact written) rather than crashing; only construction is guarded, so a fault raised
  later from the emitter's own `emit` step keeps its traceback. An emitter returns its
  payload and never writes it. The command line stages every requested artefact through
  `stompmodel.protocols.stage_payload`, then commits each through the `StagedWrite.commit`
  that staging handed back, which is where the bytes reach a path and are counted; the CLI
  keeps only the sentence it prints from that count — see
  [ADR-0005](docs/adr/0005-binary-emitter-payloads.md). A drawing backend exposes
  `render(scene, title)`, the same seam `drawing_svg` and `drawing_pdf` serialise a
  `Scene` through.
- **New stage:** implement `stompmodel`'s `Stage` protocol including `describe()`, then
  insert it in `cli.build_pipeline`. Order is the one thing a stage cannot self-declare,
  so `build_pipeline` is the integration point by design.
- **New source:** implement `stompdrill`'s own `Source` protocol, returning
  `RawDrillData`. This is a library caller's extension point, not the CLI's: `stompdrill`'s
  command line always reads Illustrator artwork through `AiPdfSource`, and no flag selects
  another one. That is deliberate, not an omission — wiring a selection flag ahead of a real
  second source would be speculative generality, so a reader who finds this recipe
  unreachable from the CLI should treat this sentence as the answer, not as a gap to close.
  There is no source registry.
- **A new stage or source also gets one line in
  `packages/stompdrill/src/stompdrill/__init__.py`.** A new emitter does not — it has a
  registry, and is resolved through `stompdrill.emitters.get_emitter`. The root exports
  what no registry can find, so that a consumer reproducing the
  `Source -> quantise -> Pipeline -> Emitter` flow has something satisfying each protocol.
  `METRIC_BANDS` and `FRACTIONAL_SIXTY_FOURTHS` stay in `stompdrill.pipeline`: they
  generate the standards rather than read a result.

## Documentation rules

- `docs/adr/` is the authority for architectural decisions. Update and accept an ADR
  before changing the architecture in code; other documentation links to ADRs instead of
  restating their arguments.
- Number diagrams within each ADR as `Figure 1`, `Figure 2`, and so on. Refer to them as
  `ADR-000N, Figure N` in the surrounding prose.
- Keep new or edited docstrings to at most ten physical lines.
  `packages/stompdrill/tests/test_documentation.py` audits every workspace member's own
  `src` and `tests`, discovered through `tools.workspace_membership` rather than listed,
  plus `tools/`, through `tools/check_docstrings.py`, but only warns — the ceiling
  guides new prose rather than gating the suite. Put architectural rationale in an ADR
  and keep docstrings local to the code they document.
- Use British spelling in prose and established American spelling in identifiers.
- Keep `from __future__ import annotations` and an explicit, logically ordered `__all__`
  in each Python module. Value objects are frozen, slotted dataclasses whose transforms
  return replacements.

## Design rules

- Keep SOLID and DRY in mind, as guidance rather than ceremony. Use them to remove
  duplication and to sharpen a boundary; do not use them to justify an interface nobody
  needs, a layer with one implementation, or a class where a function reads better. Review
  for both: a second copy of a rule, or a module that would have to change for two
  unrelated reasons, is the signal worth acting on.

## Testing rules

- Use TDD. Keep stages pure where possible and test emitters with hand-built `DrillData`.
- Assert cross-artefact claims against emitted bytes by parsing each output format.
- A test must fail when the behaviour it names is removed. Check each clause of a compound
  condition independently, and ensure a mutation changes only the behaviour under test.
- Break accidental equality in fixtures: number routed holes out of tuple order, so a test
  only passes an emitter that reads the number through `DrillData.numbered()` rather than
  recomputing one from list position.
- The fixture rule above is a special case of a general one: a verification instrument that
  can pass by finding nothing — a structural gate scanning for a restated rule, an ordering
  guard whose fixture never exercises the order it claims to police, a property that never
  reaches the branch it means to constrain — is not evidence until a control shows it, by a
  deliberate breach of the rule it enforces, actually failing. Write that control beside the
  instrument, in the same suite, run by the same command; a report that a control was run by
  hand is not the control.
- Preserve property tests for snapping (onto the grid, within half a pitch, and
  idempotent) and tool stability under hole reordering — not deduplication idempotence,
  which exact integer equality makes structurally unfalsifiable.
- `packages/stompdrill/tests/recovery/` holds uncollected read-back helpers
  (`excellon.py`, `svg.py`, `pdf.py`) plus a shared vocabulary in `facts.py`; a recovery
  that inverts its own emitter's transform proves that emitter self-consistent and nothing
  more. An AST gate in `test_recovery.py` forbids anything under `recovery/` from
  importing `stompdrill`.
- `packages/stompcollider/tests/recovery/` is the same arrangement for the two docking
  artefacts: `report.py` reads the JSON through the standard library and `assembly.py`
  reads the STEP through OCP, sharing a vocabulary in `__init__.py`. Its gate, in
  `test_dock_agreement.py`, forbids **both** `stompcollider`, which wrote the report,
  and `stompgeom`, whose writer produced the STEP.
- Coverage targets are 90% for each package and 100% for quantisers, stages, emitters, and
  `stompmodel`'s codec — `stompcollider`'s `match` and `seat` are stages by that rule.
  `stompdrill`'s figure only reaches its target with the kernel tests included, so
  measure it under `--hammond` — see the kernel-test rule below.
- `mypy` covers `tests` as well as `packages/stompdrill/src/stompdrill`, because most
  hand-built lengths are fixtures. Test helpers accept plain literals and brand them
  internally; direct model construction wraps explicitly.
- Catalogue tests must re-read `docs/parts/dimensions.tsv` and prove that the generated
  module is current.
- Clearance-rule tests use a fake `CaseModel`. Kernel-backed tests do not skip on a
  missing kernel: it is an unconditional dependency, so failing to import it is a
  failure rather than a silent pass.
- Kernel tests run against real Hammond models fetched at run time, never committed.
  They are opt-in behind `--hammond`; a standard run skips them. Coverage targets for
  `stompgeom.step`, `stompgeom.writer` and `stompdrill`'s cutter are measured under
  that command, not the default one.
- `stompcollider`'s equivalent is `--boards`, which enables the tests that read its
  committed STEP board fixture. Coverage for `stompcollider.sources` and its assembly
  emitter is measured under that flag, not the default one. Like `--hammond` it is not a
  kernel-availability switch: `stompgeom` is an unconditional dependency, so a missing
  kernel is a failure rather than a silent pass.
- Verification reports name the exact commands run; a tool invocation that suppresses the
  claimed rule is not evidence.
- Record no counts in this file — not test totals, not mutation survivors. A recorded
  number is stale on the next commit; name the command that produces it instead.
- No single command proves every suite at once: the root `testpaths` covers only
  `stompdrill`, and four `tests` packages cannot share one interpreter. Run each:

  ```bash
  .venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
  cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
  cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q
  .venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
  ```

### Mutation testing

- Run with bytecode generation disabled and inspect which test killed each relevant
  mutation. Mutation testing is a survey, not a numeric gate: run it and read the current
  result. Read it by module, not in total.
- `emitters.drawing.build`, `cli`, `emitters.drawing_pdf`, `emitters.drawing.content` and
  `emitters.drawing_svg` account for most survivors, where a mutant rewrites a help
  string, a cell offset or a font size and nothing observable changes. The drawing modules
  are layout-heavy and survive in proportion.
- A survivor in `geometry`, `pipeline.dedupe`, `pipeline.validate`, `quantise`,
  `stompdrill.units`, `emitters.drawing.sheet` or `emitters.drawing.layout` is the kind
  worth chasing: those hold cited constants and shared facts rather than placement.
- `_kappa_consistent`'s survivors are settled: some were killed by new tests, the rest are
  proved equivalent and not worth re-chasing. `docs/plans/2026-08-21-test-repairs.md` holds
  that proof, and it covers nothing else. `geometry`'s residual beyond it is still
  unclassified and each survivor needs its own analysis; they are named individually in
  their own `docs/BACKLOG.md` entry. Read those records rather than re-deriving them, and
  do not copy their figures into this file.
- `cd packages/stompdrill && mutmut run` is what reaches `geometry`, `pipeline.dedupe`,
  `pipeline.validate`, `quantise` and `stompdrill.units`; `cd packages/stompmodel &&
  mutmut run` — its own `[tool.mutmut]`, resolving against its own tests — is what reaches
  `stompmodel.units`, worth chasing for the same reason; `cd packages/stompgeom &&
  mutmut run` is that arrangement a third time, over the kernel guard, the STEP reader
  and the deterministic writer; and `cd packages/stompcollider && mutmut run` is the
  fourth, over `match`, `seat`, `clash`, `canonicalise` and `designators` — the modules
  holding this tool's cited rules rather than its placement. There is no workspace-wide
  command, the same reason the root `mypy` gate excludes the other members' tests.

## Agent skills

- **Issue tracker.** Issues and specs are local markdown under `.scratch/<feature>/`; this
  repo has no remote. See `docs/agents/issue-tracker.md`.
- **Triage labels.** The five canonical roles, unrenamed, carried on each issue's
  `Status:` line. See `docs/agents/triage-labels.md`.
- **Domain docs.** One glossary at `docs/GLOSSARY.md`, with `CLAUDE.md` and `docs/adr/`
  holding the rules and the reasons. See `docs/agents/domain.md`.
