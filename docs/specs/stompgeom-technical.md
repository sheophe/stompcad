# `stompgeom`: the workspace's kernel layer

**Status:** executed. Plan 2 landed as `stompgeom`. Amended since, where later
decisions overtook what this plan set out to do; each amendment says so in place. Where
this document and an ADR disagree the ADR governs, by `CLAUDE.md`'s documentation rules.

**Spec:** `docs/specs/stompcollider-technical.md` — this is **plan 2 of 3** from its
"Order of work". Plan 1 extracted `stompmodel`; plan 3 builds `stompcollider`.

**Governed by:** [ADR-0008](../adr/0008-workspace-and-shared-geometry-core.md) and
[ADR-0009](../adr/0009-shared-model-package-and-dependency-order.md). This design
amends both, and [ADR-0007](../adr/0007-case-model-and-clearance.md).

## Scope

ADR-0008 decided that a shared geometry core is extracted *before* either new tool is
written, so the seam is verifiable against a suite that already exists rather than
guessed. ADR-0009 fixed the workspace's dependency order and moved the length newtypes
down into `stompmodel`. Between them they settle that `stompgeom` exists and roughly
what it holds.

Four seams were left open: where the frame types live, how they divide, where
`emitters/step.py` splits, and what survives the kernel becoming unconditional. This
document closes all four — the first as decisions 1 to 3, since it turned out to carry
a contradiction — and settles the package layout that follows.

**`levels()` is not in this plan.** ADR-0009 places it in `stompgeom` and that is where
it ends up, but the spec's "Order of work" defers it to plan 3 deliberately:
`find_faces` returns an inner compound, a plate thickness, an outward normal, a
drilled and an inner position, and a footprint span. Two of those are case-shaped — the
footprint span, and the thickness measured against a catalogue — where carrier-plane
detection wants levels and holedness. The outward normal is not case-shaped, and is the
same quantity the collider calls a carrier normal, so the overlap is larger than a
plate-and-thickness reading of this sentence suggests. Cutting that seam
now would mean designing an interface with no second consumer in the room — the exact
failure ADR-0008 exists to avoid. So plan 2 lands `stompgeom` as a *format* layer that
plan 3 thickens into an *operations* layer.

**Plan 2 succeeds when nothing observable changes.** Every artefact `stompdrill` emits
must be byte-identical across the move. `stompdrill`'s suite is the instrument.

## Decisions

### 1. The frame values live in `stompmodel`, not `stompgeom`

ADR-0009 as accepted contains a contradiction. Four of its statements cannot all hold:

- `stompgeom` holds `CoordinateFrame` and `FaceFrame`.
- `stompdrill` publishes the `FaceFrame` it cut in **as a member of the drill document**.
- `stompmodel` holds `DrillData` and its members, and the `DrillData` codec both ways.
- Figure 1 fixes the order `stompmodel ──► stompgeom`, and `stompmodel`'s distribution
  declares no dependencies at all.

A `stompmodel` dataclass cannot carry a typed member defined in `stompgeom` without
`stompmodel` importing it, which is a cycle in a graph the ADR calls linear and acyclic.

**Decision: `CoordinateFrame` and `FaceFrame` are defined in `stompmodel`,** in a new
`frames.py`. `stompgeom` keeps the kernel-side reading and writing; frame
*construction* stays in `stompdrill`.

**Amended.** This sentence first read that `stompgeom` keeps the operations that build
one. That was wrong when written: `build_frame` picks its `u` axis from footprint spans,
which is enclosure reasoning, and ADR-0009 rules on it pre-emptively — "Frame
*construction* is not here and is not coming ... A reader looking here for a frame
builder will not find one". This document's own inventory under "What does not move"
always agreed with the ADR; only this line did not.

**Why.** The frame value needs no kernel: it is a frozen, slotted dataclass of
`Nanometre` and float triples. What needs the kernel is `build_frame`, which reads OCC
faces to produce one. That is precisely the division ADR-0009 already made for lengths,
and its rationale transfers verbatim — a length is a unit rather than an operation, and
putting it in the leaf "keeps the graph linear and lets a consumer take `Nanometre`
without taking a CAD kernel". A frame is a registration rather than an operation, and
the same sentence is true of it.

It also satisfies `stompmodel`'s first admission rule without strain: `stompdrill`
produces the face frame, `stompcollider` consumes it, and neither is its home. That is
interchange, which is the rule's own definition.

**Consequence.** ADR-0009's `stompgeom` inventory is amended, and plan 3 is unblocked:
once `FaceFrame` is a leaf type, `DrillData` can carry it and the codec can serialise
it without `stompmodel` growing a dependency on OpenCASCADE.

A new `frames.py` rather than an addition to `model.py`: `model.py` holds drill-data
values, and a registration is not one.

### 2. `FaceFrame` composes `CoordinateFrame`

```python
@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    """An origin and a right-handed basis. Carries no meaning about what it registers."""
    origin_nm: tuple[Nanometre, Nanometre, Nanometre]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    w: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FaceFrame:
    """A face's registration: a frame whose third axis is that face's outward normal."""
    basis: CoordinateFrame
```

`FaceFrame` adds a guarantee and no fields. It cannot carry a face designator:
ADR-0009 keeps `select_solid`'s box and lid keywords in `stompdrill`, and no enclosure
vocabulary crosses this boundary.

**Composition rather than inheritance**, and **no delegation** — callers reach through
`.basis`. ADR-0008 says primitives of this shape are "split, not moved wholesale". A
subclass would let a `FaceFrame` pass silently wherever a bare `CoordinateFrame` is
wanted, which is the "universal wrapped in a meaning" leak the ADR names as the risk
this package carries; delegating every method would rebuild that substitutability by
hand. The wrapping is meant to be visible at the call site.

The churn this costs is small, because of decision 3: most call sites stop touching the
basis at all.

**No `__post_init__` validation** *as extracted*: right-handedness and unit length
were not checked, because adding a check is new behaviour in a plan whose test is that
nothing observable changes. `build_frame`'s existing degenerate-frame guard stayed where
it is.

**Amended.** `CoordinateFrame.__post_init__` now validates, under its own measurement:
component count, whole-nanometre origins through `check_nanometres`, finiteness, unit
length to a stated tolerance, pairwise orthogonality, and that `w` equals `u × v`. Each
raises `ValueError` at construction. The consequence for a caller building a frame from
measured geometry — a carrier plane read off a board, say — is that a basis which misses
orthonormality by more than the tolerance raises rather than propagating: normalise
before constructing. ADR-0004 records the rule and `frames.py` records where the
tolerance was measured.

### 3. The transform arithmetic belongs to the value

`cad/region.py`'s `_to_model` and `emitters/step.py`'s `_face_point` both compute
`origin + x·u + y·v`, differing only in that `_face_point` adds an overshoot along `w`.
Two copies of one rule in two modules is the signal `CLAUDE.md`'s design rules say to
act on. Both are pure arithmetic on floats and `Nanometre`, so they follow the value
into the leaf:

```python
def to_model(self, x_nm, y_nm) -> tuple[Millimetre, Millimetre, Millimetre]
def to_canonical(self, point_mm) -> tuple[Millimetre, Millimetre, Millimetre]
def reframe(self, x_nm, y_nm, target: CoordinateFrame) -> tuple[Nanometre, Nanometre]
```

**The names keep the existing function names.** `to_model` and `to_canonical` are
today's `_to_model` and `_to_canonical` without the underscore, and `reframe` is
today's `region.reframe`. No `_mm` or `_nm` suffix: `Millimetre` *is* the model-space
representation and `Nanometre` *is* the canonical one, so the return types already say
what a suffix would repeat.

**Returns are branded.** `to_model` returns `Millimetre`, not bare `float`. Today
`_to_model` returns raw floats while `_face_point` already writes
`float(mm_from_nm(...))` — the same conversion, branded in one place and not the other.
ADR-0004 says brand at a real conversion, and nanometres to millimetres is one. Callers
unwrap with `float()` at the OCC boundary, as `_face_point` already does.

**The third value is the depth along `w`, and it arrived after this plan.** As
extracted, `to_canonical` projected onto `u` and `v` only while `to_model` was already
three-dimensional, so the pair was asymmetric in arity as well as in unit. The depth is
signed and is zero for a point on the frame's plane. `reframe` was deliberately left
two-valued: a canonical point is two-dimensional by definition, and both of its callers
feed the result straight back into canonical data. The unit question below is a separate
one and is still open.

**`to_canonical` returns millimetres, and that asymmetry is deliberate here.** In this
code "canonical" names the frame's own axes, not the unit: `_to_model` takes canonical
coordinates in nanometres and returns model millimetres, while `_to_canonical` returns
canonical coordinates in *millimetres*. `region_bbox_nm` depends on it — it projects
four corners, takes the minimum and maximum across them, and rounds once at the end.
Returning nanometres would round each corner first instead. The results provably agree,
since half-up rounding is monotonic, but a plan whose success criterion is byte identity
does not reorder arithmetic on the strength of a proof. `reframe` keeps today's
`nm_from_mm` wrap. The asymmetry is a wart to fix under its own measurement, not here.

`region.py` loses `_to_model`, `_to_canonical` and `reframe`; the box-and-lid motivation
that `reframe`'s docstring carries survives as a comment at the call site, because the
operation is frame algebra and the motivation is enclosure reasoning. ADR-0009 keeps the
latter in `stompdrill`.

### 4. `stompgeom`'s contents

| Module | Contents | Source |
| --- | --- | --- |
| `kernel.py` | `KernelUnavailable`, `require_kernel()` | `cad/step.py`, `cad/base.py` |
| `errors.py` | `StompgeomError(StompError)` | new |
| `step.py` | `StepSolid`, `StepDocument`, `StepLabel`, `read_step`, `leaf_labels`, `bounding_box_mm`, `source_timestamp`, and the XCAF label helpers | `cad/step.py` entire |
| `writer.py` | `render_step()` and its normalisation | `emitters/step.py`, lower half |

`StepLabel` and `leaf_labels` are the workspace's one XCAF leaf descent and the wrapper
that carries the document a label was drawn from. ADR-0008 argues both, and states the
wrapper's guarantee in its narrow form: the published surface offers no route that hands
out an already-dangling label, not that a consumer cannot construct one — keeping the raw
handle and dropping the `StepLabel` still can. A consumer that must walk a STEP document
calls these rather than writing a second walk.

`require_kernel` is defined twice today — once in `cad/step.py` and again in
`emitters/step.py` as a test indirection. The extraction leaves one.

**`read_step`'s refusals become `DocumentError`.** A `stompgeom` reader cannot raise a
`stompdrill` error, and ADR-0009 put `DocumentError` in `stompmodel` for exactly this:
"refusing a foreign document" is a failure any member can have.

**`KernelUnavailable` changes base** from `StompdrillError` to `StompgeomError`. A test
asserts the old relationship and must change; that is an intended behaviour change, not
incidental churn.

### 5. The STEP writer seam

`emitters/step.py` does two jobs. The format layer moves; the cutter stays.

**Moves to `stompgeom.writer`:** `render_step` (today's `_write`), `_normalise`,
`_reslot_colours`, `_count_colour_assignments`, `_silence_stdout`, and the
volatile-entity and colour-chain patterns. The XCAF label helpers land in `step.py`
beside the reader that uses them, not here.

**Stays in `stompdrill`:** `StepOptions`, `StepEmitter`, `cut_shape`, `_cut_leaf`,
`_drill_compound`, `_face_point`. These read `DrillData` and decide what to
cut, which is drilling.

```python
def render_step(document, *, title: str, timestamp: str,
                originating_system: str,
                replaced_labels: frozenset[str] = frozenset()) -> bytes
```

**Amended: it returns bytes and takes no path.** As planned this was
`write_step(document, path, ...) -> None`. ADR-0005 makes an emitter return its payload
and never write it, so the shipped entry point renders and returns; the command line
stages and commits. Read as first written, this block inverted that contract.

**All identity is injected, never defaulted.** Were `render_step` to keep today's
hardcoded header strings, a `stompcollider` assembly written through it would stamp
`ORIGINATING_SYSTEM` with `stompdrill`'s name — provenance from a tool that never
touched it. ADR-0009 already ruled on this pattern when it stopped
`SourceInfo.producer` defaulting to `"stompdrill"`, and the argument is unchanged here.
`stompdrill` therefore supplies both the header name and the originating system at the
call site, and keeps its own version constant, which is what reproduces today's bytes
exactly.

**The translator's wrapper product name stays inside the writer.** It is already the
workspace's name rather than any package's, and it is load-bearing rather than
cosmetic: `_normalise` strips the volatile counter appended to it, so the setter, the
pattern and the replacement must all read one constant.

**`touched` is renamed `replaced_labels`.** The parameter states a fact about the
kernel's writer — a shape whose colour was not serialised because `SetShape` replaced
it — without naming drilling. `stompcollider` does not cut, and takes the default.

The colour-chain guard keeps raising `EmitterError`; its message names the new module.
This is an error path and reaches no emitted artefact, so byte identity is unaffected.

### 6. The kernel becomes unconditional

ADR-0009 retires ADR-0007's optional `stompdrill[step]` extra when `stompgeom` lands,
and says removing it is plan 2's change. `stompgeom` takes the kernel unconditionally,
so `stompdrill` does too. This is coherent with the wider design rather than a loose
end: `docs/specs/stompcad.md` gives the unconditional kernel as the reason
`stompcad doctor` exists at all.

**`require_kernel` and `KernelUnavailable` both survive**, with the install hint
rewritten to name the missing package rather than any tool. A broken environment is an
anticipated state in this design — it is what `doctor` repairs — so an error naming its
remedy earns its place. The hint names no consumer, preserving ADR-0009's rule that a
shared component never bakes in the identity of a package above it.

**The emitter must import the module, not the name.** A test simulates an absent kernel
by patching `require_kernel` on the emitter's module, which is the indirection this
extraction deletes as a duplicate. So the cutter calls `kernel.require_kernel()` through
the imported module. A `from ... import require_kernel` would bind the function at
import time, the patch would stop reaching it, and the test would pass vacuously —
which `CLAUDE.md`'s testing rules forbid: a test must fail when the behaviour it names
is removed.

**Every `importorskip("OCP")` is deleted.** Once the kernel is a hard dependency these
can never fire, and worse: if OCP ever did fail to import they would skip silently
rather than fail. A gate that suppresses the rule it claims to check is not evidence.
The `--hammond` opt-in is untouched; it governs downloading real models, which is a
separate concern.

### 7. Documentation

`CLAUDE.md` states the facts this plan changes, and nothing more: the `stompdrill[step]`
extra and the `--all-extras` guidance are retired, `stompgeom`'s own test, type and
mutation commands are added, and the clause about kernel-backed tests skipping when the
extra is absent is removed. Documentation that plan 2 makes wrong is documentation plan
2 repairs.

**A wider `CLAUDE.md` audit is not part of this plan**, and is being done separately.
Trimming restated ADR argument, removing recorded measurements and repairing ADR links
are all worth doing, but they answer to what orients a fresh session rather than to what
this extraction changes. Carrying them here would put two rubrics in one diff — the same
reason the parent spec split three plans instead of writing one.

## What does not move

ADR-0009 is explicit and this design adds nothing to the list: `CaseModel`, `Rejection`,
`select_solid`'s box and lid keywords, and `region.py`'s play-area reasoning stay in
`stompdrill`, as do `Faces`, `find_faces`, `build_frame` and `drill_axis`. The test for a
`stompgeom` type is whether it can be described without naming a panel; the test for a
`stompmodel` type is interchange or contract. Nothing here passes either.

**Amended:** `assembly_spans` moves. The bounding-box span of every solid together, per
axis, in millimetres, passes this section's own test; it is now
`stompgeom.step.assembly_spans`, and `stompdrill` imports it rather than defining it. See
ADR-0009's `stompgeom` inventory.

`stompdrill`'s `Micron` also stays: ADR-0009 keeps it because it states that package's
grid policy rather than anything about length.

## Verification

1. **Byte identity.** Every artefact `stompdrill` emits is unchanged across the move,
   asserted under the kernel-backed run. This is the governing test, and `stompdrill`'s
   existing suite is the instrument — which is the whole reason ADR-0008 extracts before
   the new tools rather than after.
2. **Each package installs and passes its own tests alone.** ADR-0008's governing test,
   now for three packages.
3. **A new boundary gate for `stompgeom`**, modelled on the leaf's import-AST scanner,
   permitting `stompmodel` and the kernel and no sibling above it.
4. **The leaf's boundary gate is corrected.** Its `TYPE_CHECKING` example imports from a
   `stompgeom.frames` that decision 1 means will never exist; it must name a module that
   genuinely sits above the leaf. Its explicit module list gains `frames.py`, or the
   scan would pass by not reaching the new file.
5. **Coverage targets are unchanged in kind**: the workspace target for each package,
   and full coverage for the frame values, which are small, pure and shared.
6. No expected counts are recorded, here or in `CLAUDE.md`. The commands are named; the
   numbers are read from a run.

## ADR amendments

Each lands with the work, because a stale ADR is misinformation.

- **ADR-0009** — `CoordinateFrame` and `FaceFrame` move from the `stompgeom` inventory to
  `stompmodel`'s, with decision 1's reasoning: the value is kernel-free, the operation
  that builds it is not, and the drill document could not otherwise carry the frame.
- **ADR-0007** — the optional `stompdrill[step]` extra is retired. Its argument assumed
  `stompdrill` stood alone, which stops being true here.
- **ADR-0008** — a note that lengths and frames both settled in `stompmodel`, so its
  "shared geometry core" reads as the kernel layer it became.

## Order of work within plan 2

Written as an implementation plan next; the phases are:

1. `frames.py` in `stompmodel`, with the transform methods, and the leaf's boundary gate
   corrected. Nothing consumes it yet.
2. The `stompgeom` package: reader, kernel guard, errors, boundary gate.
3. The writer split, with identity injected.
4. `stompdrill` rewired onto both; `cad/step.py` deleted, `Frame` deleted.
5. The kernel made unconditional; the extra and the skips removed.
6. `CLAUDE.md`'s factual updates and the ADR amendments.

Phases 1 to 5 are judged by byte identity. Phase 6 is judged by reading.

## Not decided here

- **`levels()` and holedness.** Plan 3, immediately after the carrier-plane code that
  consumes it, so the interface is discovered rather than invented.
- **The drill document's face-frame member and its version bump.** Plan 3. Decision 1
  makes it possible; it does not perform it.
- **Whether `stompcollider` needs anything else from `stompgeom`.** It grows as real
  second consumers appear, which is ADR-0008's method.
