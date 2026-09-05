# Agent guidance

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development commands, testing rules,
extension recipes, code conventions and writing style. The rules below add
domain constraints and guidance
for automated work in this repository.

## Purpose and scope

`stompdrill` reads Adobe Illustrator artwork and creates drill files, drawings,
a JSON drill document and, when given an enclosure model, a drilled STEP model.
`DrillData` is its library integration contract. KiCad data and component
semantics are outside this package's scope.

`stompcollider` reads the drill document, a drilled case model and board models.
It seats boards using the holes matched to their panel-reference components,
then reports clashes. It does not drill the case or modify geometry to eliminate
clashes.

Enclosure geometry comes from a supplied model. `stompdrill` uses it to verify
clearance and cut the selected holes. Model acquisition is handled separately
by `tools/fetch_case_model.py`.

All outputs from one invocation must agree on the geometry they describe.

## Development commands

Create the environment with Python 3.10 or later:

```bash
uv venv
uv sync --all-packages
source .venv/bin/activate
```

`cadquery-ocp` is required by `stompgeom` and installed with both tools. It also
pulls in vtk and matplotlib. The optional extra described in the original
ADR-0007 decision has been replaced by this required dependency.

`pdfminer.six` belongs to `stompdrill`'s dev group because its PDF read-back tests
import it. `hypothesis` belongs to the root, `stompmodel`, `stompdrill` and
`stompcollider` dev groups so each package can run its own tests. These are
installed by `uv sync --all-packages`.

Run each suite in a separate process, from the repository root:

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
(cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q)
(cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q)
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
```

Run lint and types as documented in [Contributing](CONTRIBUTING.md#run-the-checks).
The root pytest configuration covers only `stompdrill`; the root mypy run also
excludes the other packages' tests. Use each package's own commands to check
those tests. Coverage and mutation surveys are per package too.

## Command-line contract

[docs/CLI.md](docs/CLI.md) documents flags, defaults, formats, diagnostics and
output handling. Keep it current when the CLI changes. Both tools use exit
codes `0` for clean, `1` for warnings, `2` for processing errors and `3` for usage
or input/output failures.

Validate options before opening the artwork or board input. Bad standards,
unstocked sizes, unknown part numbers and invalid designator filters are usage
errors. `--case-face` and `--case-margin` are validated even without a case
model.

Validate all requested targets together before rendering. Both CLIs use the
shared target checks and staged writes in `stompmodel.protocols`; do not add a
second write mechanism. Preserve the rollback behaviour and its exclusions in
[ADR-0001](docs/adr/0001-pipeline-and-emitter-adapters.md) and
[ADR-0005](docs/adr/0005-binary-emitter-payloads.md).

Keep these `stompcollider` behaviours when changing the CLI:

- `--panel-reference` is required and has no default. It identifies components
  chosen for the particular pedal.
- `--match-tolerance` defaults to half the recorded drill grid pitch. A supplied
  value overrides it. If the document has no usable pitch, report a usage error
  naming the flag. Do not invent a pitch or make the flag universally required.
  Print the effective tolerance in the terminal report's `CASE` block.
- `--seat-pitch-max` and `--seat-pitch-min` default to 2.0 and 0.05 mm. Both must
  be positive, with the coarse step at least as large as the fine one. `Seat`
  records both in `describe()`.
- The enclosure determines the first contact along the insertion path. Do not
  seat a board and then retreat until clear; the fixture disproves that method.
  Bound travel by the last possible contact, allowing a board to go deeper than
  its profile predicts. If the path has no contact, use the hole seat.
- Rank by insertion shortfall first. Exclude boards that never enter the case
  from the assembly search, so reduced mutual interference cannot make them
  preferable to boards that entered.
- Identify the lid geometrically, not by the name `LID`. Exclude it from
  insertion, ranking and the first-stage filter, but report its clashes as
  `closure`.
- Keep `--fit-clearance` removed. Profiles are measurements, not the seating
  decision. The tar footswitch profile gives 20.992 and 9.499 mm through the same
  ⌀12 hole because of tangency; this is why the enclosure search governs seating.
- Parse and validate `--place` and `--pin`, then reject them with the reason they
  are unsupported. No stage implements explicit placement, and `Clashes`
  re-ranks placements. Do not accept either as a no-op.

The `tar.ai` fixture needs `--case 1590B`. Its dimensions also match `1590B2` and
`1590BS` within tolerance, so `ambiguous-enclosure` without a declared case is
expected. Do not widen tolerances, special-case the fixture or round footprint
keys to whole millimetres to suppress the error.

## Architecture

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for package responsibilities,
processing diagrams, shared APIs and drawing output. The accepted decisions
are in [docs/adr/](docs/adr/):

| ADR | Subject |
| --- | --- |
| [0001](docs/adr/0001-pipeline-and-emitter-adapters.md) | Processing boundaries and output consistency |
| [0002](docs/adr/0002-domain-quantisers.md) | Answer sets and validation policy |
| [0003](docs/adr/0003-quantisation-boundary-and-ordering.md) | Quantisation order and termination |
| [0004](docs/adr/0004-unit-newtypes.md) | Length units in types |
| [0005](docs/adr/0005-binary-emitter-payloads.md) | Binary emitter payloads and staged writes |
| [0006](docs/adr/0006-toolpath-ordering-and-hole-numbering.md) | Toolpath ordering and hole numbering |
| [0007](docs/adr/0007-case-model-and-clearance.md) | Case models, clearance and the kernel dependency |
| [0008](docs/adr/0008-workspace-and-shared-geometry-core.md) | Workspace packages and shared geometry |
| [0009](docs/adr/0009-shared-model-package-and-dependency-order.md) | Shared model package and dependencies |
| [0010](docs/adr/0010-the-stomp-prefix.md) | Package naming |
| [0011](docs/adr/0011-behaviour-lock-and-its-blind-spots.md) | Output-preservation checks and their limits |

Keep `stompcollider` independent of `stompdrill` and direct OCP imports. Read
shared drill documents through `stompmodel` and use kernel operations through
`stompgeom`. Each package must install and pass its own tests independently.

`quantise()` selects the enclosure, diameters and positions, in that order.
`cli.build_pipeline` composes the later stages: `Deduplicate`, `ReviewGridTies`,
`RouteHoles`, `CheckOutlineContainment`, then optional `CheckCaseClearance`.
Stages must not depend on or assert that another stage ran first; `Pipeline`
depends only on the `Stage` protocol.

## Domain invariants

- Canonical coordinates use a Y-up frame with the origin at the reference
  outline's centre. Emitters transform coordinates through model operations.
- Raw lengths are finite float millimetres. Canonical lengths are integer
  nanometres, selected by exact decimal scaling before representation rounding.
- Use `Millimetre` for measurements, `Nanometre` for canonical lengths and
  `Micron` for effective grid pitch. Arithmetic drops the type brand; re-wrap a
  result when it becomes a length again. Brand values at real conversions.
- Snap positions to the declared grid, diameters to the selected drill standard,
  and the `Background` outline to the enclosure catalogue. Keep these answer
  sets separate.
- An enclosure error stops quantisation. A rejected diameter records its
  diagnostic and omits only that hole. Any error prevents every requested output.
- Artwork uses published top-view/backplate dimensions. A footprint may identify
  several parts; require `--case` when ambiguous and verify a declared part.
- A hole outside the reference outline produces a warning. Use the matched
  catalogue footprint as that boundary when available, otherwise the drawn
  outline. A hole outside the drilled face produces an error; this check needs
  a supplied model.
- Geometry determines ordering. Reordering equivalent input elements must not
  change output bytes; no ordering rule may consult input order. ADR-0006 and
  ADR-0007 describe the other inputs that affect output determinism.
- `RouteHoles` alone assigns `Hole.index`, the sequence `1…n`; it is `None`
  beforehand. Each tool has one contiguous block, with holes routed within it.
  Emitters use `DrillData.numbered()`, which rejects unrouted data.
- `ReferenceOutline.raw` preserves measured geometry. Transform it through the
  model rather than reconstructing it.
- Keep diagnostics, provenance, tool assignments and ordering on `DrillData`.
  Emitters must not recalculate them. Match diagnostics by `code`, not message.

## Parsing constraints

- The reader uses the PDF-compatible stream in an Illustrator file. Illustrator
  does not need to be running.
- Recover top-level layers through `/OCProperties` → `/OCGs` and the content
  mappings in `/Resources/Properties` → `/MCn`. Sublayers cannot be recovered.
- Paths without fill or stroke are absent from the stream. `EmptyLayerError`
  should tell users to give drill circles a stroke.
- `W` and `W*` mark clipping paths but aren't tracked as clip regions. `n` makes
  a path invisible.
- The page crop box, or media box if no crop box is declared, and every Form
  XObject `/BBox` are unconditional clips. Map each form box through its
  `/Matrix` and the current matrix, then intersect it with the inherited region.
  Accumulate intersections through nested forms. See ISO 32000-1 §14.11.2 and
  §8.10.2.
- Judge a recognised circle by its centre when clipping. A thin crescent inside
  the clip does not admit a hole whose centre lies outside. Judge other paths,
  including outline candidates, by their extent; retain paths straddling the
  boundary.
- Recognise circles by four cubic Béziers with equal anchor radii and consistent
  kappa values around their centroid. Recognition must work under rotation.
- Apply every `cm` transformation and each Form XObject's `/Matrix`.
- Follow the requested `--form-depth` levels. Report `nesting-truncated` only
  when a further form exists. Deeper artwork is absent from outputs and reports.
- Object names cannot be recovered because these Illustrator files provide no
  structure tree.
- Use the largest non-circular path on the reference layer as the reference
  outline, not the document MediaBox.

## Documentation rules

Follow the documentation conventions in
[Contributing](CONTRIBUTING.md#code-and-documentation-conventions). If a local
`docs/STYLE.md` is available, use its expanded examples too. Use the
[glossary](docs/GLOSSARY.md) for domain definitions. Ordinary explanatory wording
is welcome where it preserves the technical distinction.

ADRs define accepted architectural decisions. Update and accept the relevant
ADR before changing architecture in code. When another document disagrees with
an ADR, investigate the difference and correct the stale document. Keep reasons
in ADRs and link to them from other guidance.

## Testing rules

Follow [Contributing](CONTRIBUTING.md#write-tests-that-detect-the-change), including
TDD for code changes, independent output readers, controls for checks that can
pass without examining anything, coverage targets and per-package commands.
Keep mutation findings out of standing count summaries and report exact
verification commands.

## Agent workflows

- [Issue tracker](docs/agents/issue-tracker.md): local Markdown issues, specs and
  wayfinder maps under `.scratch/`.
- [Triage labels](docs/agents/triage-labels.md): the five status values used by
  issue-triage skills.
- [Domain documentation](docs/agents/domain.md): how to use the glossary, ADRs
  and these instructions during repository exploration.
