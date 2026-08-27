# `stompcollider` Implementation Plan — plan 3 of 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `stompcollider`, the tool that seats PCB models inside a drilled case and reports where they clash, together with the foundation prerequisites the 2026-08 docket identified as blocking it.

**Architecture:** `BoardSource → RawBoards → canonicalise() → Pipeline(Match, Seat, Clash) → {ReportEmitter, AssemblyEmitter}` — ADR-0001's shape instantiated for docking. Everything above `sources/` and `emitters/` is pure and hand-testable; the kernel is confined to `sources/`, `clash.py` and `emitters/assembly.py`. Phase 0 first moves four helpers to their ruled homes, gives `CoordinateFrame` composition, and turns `stompdrill`'s private level grouping into `stompgeom.levels()`.

**Tech Stack:** Python 3.10+, `cadquery-ocp` (OpenCASCADE via OCP), `pytest`, `hypothesis`, `mypy`, `ruff`, `uv` workspaces.

**Spec:** [`docs/specs/stompcollider-technical.md`](../specs/stompcollider-technical.md) is what is built. [`docs/specs/foundation-docket-rulings.md`](../specs/foundation-docket-rulings.md) supplies the seven answers it left open, and **its Consolidated work list is Phase 0's contents**. Executors read both.

## Global Constraints

Copied from `CLAUDE.md` and the two specs. Every task's requirements implicitly include this section.

- **Python 3.10 or later.** Environment: `uv venv && uv sync --all-packages && source .venv/bin/activate`.
- **Every module** carries `from __future__ import annotations` and an explicit, logically ordered `__all__`.
- **Value objects are frozen, slotted dataclasses** whose transforms return replacements.
- **British spelling in prose, established American spelling in identifiers.**
- **Docstrings are at most ten physical lines.** Architectural rationale goes in an ADR, not a docstring. No incident history — a docstring says why the code is shaped this way, never how it got that way.
- **Canonical lengths are integer nanometres**, selected by exact decimal scaling before representation rounding (ADR-0003). Raw source lengths are finite float millimetres.
- **No dict or set key holds a float**, nor a composite key containing one. Quantise to an integer first.
- **No rule may consult input order** (ADR-0006). Two inputs representing the same geometry produce byte-identical artefacts.
- **Any error withholds every requested artefact.**
- **Exit codes:** `0` clean, `1` findings, `2` error, `3` usage or IO — via `stompmodel.diagnostics.exit_for_severity`.
- **TDD throughout.** A test must fail when the behaviour it names is removed. Check each clause of a compound condition independently.
- **A gate that can pass by finding nothing is not evidence.** Every structural gate, ordering guard or property test ships with a *guilty* probe (a deliberate breach that must fail it) and an *innocent* probe (a legitimate change that must not), in the same suite, run by the same command.
- **Record no drifting numbers in tracked documents** — not test totals, not call-site counts. Name the command that produces the figure instead.
- **`docs/adr/` is the authority.** Amend and accept an ADR before changing the architecture it governs.
- **Diagnostics are matched by `code`, never by message.**

### Commands

```bash
# stompdrill's suite (root testpaths cover only this package)
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --tb=short
# with the kernel tests
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
# the other members, each in its own interpreter
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q      # new in this plan
# lint and types
ruff check packages tools
mypy packages
cd packages/stompmodel && uv run --no-sync mypy
cd packages/stompgeom && uv run --no-sync mypy
cd packages/stompcollider && uv run --no-sync mypy                      # new in this plan
# byte lock: capture before a change that must move nothing, compare after
bash tools/verify-lock.sh
```

---

# Phase 0 — Foundation prerequisites

Rows 1–10 of the ruling's Consolidated work list. **Every task in this phase must move no artefact byte.** Capture `bash tools/verify-lock.sh` before starting the phase and compare after each task that touches `stompdrill`.

---

### Task 1: Publish `stompgeom.compound()` and collapse `stompdrill`'s copies

The `TopoDS_Compound` build idiom is duplicated in shipped source, not deferred — `grep -rn "MakeCompound" packages --include="*.py"` finds it in `stompdrill`'s `cad/region.py` (twice), `cad/case.py` and `emitters/step.py`, plus test copies. Ruling 7 promotes it.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/shapes.py`
- Create: `packages/stompgeom/tests/test_shapes.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/region.py` (both `MakeCompound` sites)
- Modify: `packages/stompdrill/src/stompdrill/cad/case.py` (`_compound`, delete it)
- Modify: `packages/stompdrill/src/stompdrill/emitters/step.py` (its `MakeCompound` site)

**Interfaces:**
- Consumes: `stompgeom.kernel.require_kernel`
- Produces: `stompgeom.shapes.compound(shapes: Iterable[Any]) -> Any` — returns a `TopoDS_Compound` holding every shape given, in the order given. An empty iterable returns an empty compound rather than raising: a level with no faces is a legitimate value, and refusing it here would push the check to four call sites.

- [ ] **Step 1: Write the failing test**

Create `packages/stompgeom/tests/test_shapes.py`:

```python
"""The compound builder: one idiom, one home."""

from __future__ import annotations

from typing import Any

from stompgeom.shapes import compound


def _box(dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def _members(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def test_compound_holds_every_shape_given() -> None:
    """The whole set arrives, not the first or the last."""
    assert len(_members(compound([_box(1, 1, 1), _box(2, 2, 2), _box(3, 3, 3)]))) == 3


def test_compound_of_nothing_is_an_empty_compound() -> None:
    """A level with no faces is a value, not an error; see this task's Interfaces."""
    from OCP.TopAbs import TopAbs_ShapeEnum

    empty = compound([])
    assert empty.ShapeType() == TopAbs_ShapeEnum.TopAbs_COMPOUND
    assert _members(empty) == []


def test_compound_accepts_a_generator() -> None:
    """Callers pass generator expressions; a one-pass consumer must not break."""
    assert len(_members(compound(_box(n, n, n) for n in (1, 2)))) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_shapes.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stompgeom.shapes'`

- [ ] **Step 3: Write the implementation**

Create `packages/stompgeom/src/stompgeom/shapes.py`:

```python
"""Assembling kernel shapes into one shape.

The topological side of geometry, as distinct from the format side that
reads and writes STEP. See ADR-0008.
"""

from __future__ import annotations

from typing import Any, Iterable

from .kernel import require_kernel

__all__ = ["compound"]


def compound(shapes: Iterable[Any]) -> Any:
    """Bundle ``shapes`` into one ``TopoDS_Compound``, in the order given.

    An empty iterable yields an empty compound rather than raising: a level
    with no faces is a legitimate value, and refusing it here would push the
    same check into every caller.
    """
    require_kernel()
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    built = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(built)
    for shape in shapes:
        builder.Add(built, shape)
    return built
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_shapes.py -q`
Expected: PASS, 3 tests

- [ ] **Step 5: Collapse `stompdrill`'s four copies**

In `packages/stompdrill/src/stompdrill/cad/case.py`, delete the whole `_compound` function and its `__all__` entry if present, then replace its call in `find_faces`:

```python
from stompgeom.shapes import compound
...
        inner=compound(inner.faces + (companion.faces if companion else ())),
```

In `packages/stompdrill/src/stompdrill/cad/region.py` and
`packages/stompdrill/src/stompdrill/emitters/step.py`, replace each local
`TopoDS_Compound()` / `BRep_Builder()` / `MakeCompound` / `Add` sequence with a
single `compound(...)` call over the same shapes in the same order, and delete
the now-unused imports. **Order matters** — the compound's member order reaches
the STEP writer, so preserve each site's existing sequence exactly.

- [ ] **Step 6: Prove nothing moved**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
bash tools/verify-lock.sh
```
Expected: stompdrill's suite green; `BEHAVIOUR LOCK HELD`.

- [ ] **Step 7: Commit**

```bash
git add packages/stompgeom/src/stompgeom/shapes.py packages/stompgeom/tests/test_shapes.py \
        packages/stompdrill/src/stompdrill/cad/region.py \
        packages/stompdrill/src/stompdrill/cad/case.py \
        packages/stompdrill/src/stompdrill/emitters/step.py
git commit -m "Give the compound idiom one home in stompgeom"
```

---

### Task 2: Move `assembly_spans` to `stompgeom`

`stompgeom-technical.md:296-303` lists it under "What does not move" and states the governing test in the next sentence — "whether it can be described without naming a panel" — which "the bounding-box span of every solid together, per axis, in millimetres" plainly passes. `docs/BACKLOG.md:678-689`'s deferral condition has arrived with `wrong-case-model`.

**Files:**
- Modify: `packages/stompgeom/src/stompgeom/step.py` (add `assembly_spans`, extend `__all__`)
- Create: `packages/stompgeom/tests/test_assembly_spans.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/case.py` (delete the function, import it, drop it from `__all__`)
- Modify: `packages/stompdrill/tests/test_cad_case.py` (import from the new home)

**Interfaces:**
- Consumes: `stompgeom.step.StepDocument`, `stompgeom.step.bounding_box_mm`
- Produces: `stompgeom.step.assembly_spans(document: StepDocument) -> tuple[float, float, float]` — unchanged in behaviour and signature.

- [ ] **Step 1: Write the failing test**

Create `packages/stompgeom/tests/test_assembly_spans.py`:

```python
"""The assembly's own extent, per axis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stompgeom.step import assembly_spans


@dataclass(frozen=True)
class _Solid:
    name: str
    shape: Any


def _box(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


@dataclass(frozen=True)
class _Document:
    solids: tuple[_Solid, ...]


def test_spans_cover_every_solid_not_the_first() -> None:
    """Two disjoint solids span their union, so neither alone can satisfy it."""
    document = _Document((
        _Solid("a", _box(10.0, 1.0, 1.0, (0.0, 0.0, 0.0))),
        _Solid("b", _box(1.0, 20.0, 1.0, (0.0, 0.0, 0.0))),
    ))
    x, y, z = assembly_spans(document)  # type: ignore[arg-type]
    assert round(x, 6) == 10.0
    assert round(y, 6) == 20.0


def test_spans_measure_extent_not_distance_from_the_origin() -> None:
    """A solid placed away from the origin spans its own size, not its reach."""
    document = _Document((_Solid("a", _box(3.0, 4.0, 5.0, (100.0, 0.0, 0.0))),))
    x, _y, _z = assembly_spans(document)  # type: ignore[arg-type]
    assert round(x, 6) == 3.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_assembly_spans.py -q`
Expected: FAIL — `ImportError: cannot import name 'assembly_spans'`

- [ ] **Step 3: Move the function**

Cut `assembly_spans` from `packages/stompdrill/src/stompdrill/cad/case.py` verbatim and paste it into `packages/stompgeom/src/stompgeom/step.py` below `bounding_box_mm`, dropping the now-redundant import. Add `"assembly_spans"` to `step.py`'s `__all__`, after `"bounding_box_mm"`.

- [ ] **Step 4: Rewire `stompdrill`**

In `cad/case.py`, remove `"assembly_spans"` from `__all__` and extend the existing import:

```python
from stompgeom.step import StepDocument, StepSolid, assembly_spans, bounding_box_mm
```

Update `packages/stompdrill/tests/test_cad_case.py` to import `assembly_spans` from `stompgeom.step`. Do **not** add a re-export in `stompdrill` — one name, one home.

- [ ] **Step 5: Run everything**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages && bash tools/verify-lock.sh
```
Expected: all green; `BEHAVIOUR LOCK HELD`.

- [ ] **Step 6: Commit**

```bash
git add packages/stompgeom packages/stompdrill
git commit -m "Move assembly_spans to the package both tools depend on"
```

---

### Task 3: Move `scaled_nm` home to `stompdrill`

Ruling 6: it returns a `Decimal` rather than a length, its docstring cites ADR-0003 — `stompdrill`'s quantisation-boundary ADR — and its only callers are `stompdrill`'s three quantisers (`grep -rn "scaled_nm" packages/*/src/`). ADR-0009's own `Micron` test sends it home.

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/units.py` (delete `scaled_nm`, drop from `__all__`)
- Modify: `packages/stompmodel/tests/test_units.py` (delete its tests, move them)
- Modify: `packages/stompdrill/src/stompdrill/units.py` (add `scaled_nm`)
- Modify: `packages/stompdrill/src/stompdrill/pipeline/snap.py`, `pipeline/enclosure.py`, `pipeline/diameters.py` (re-import)
- Modify: `packages/stompdrill/tests/test_units.py` (receive the moved tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `stompdrill.units.scaled_nm(mm: float) -> Decimal` — behaviour unchanged. `stompmodel.units` no longer exports it.

- [ ] **Step 1: Write the failing test**

Add to `packages/stompdrill/tests/test_units.py`:

```python
def test_scaled_nm_lives_in_stompdrill_not_the_leaf() -> None:
    """ADR-0009's Micron test: a statement of this package's quantisation
    policy stays here, however unit-adjacent it looks."""
    import stompmodel.units

    from stompdrill.units import scaled_nm

    assert scaled_nm(1.5) == Decimal("1500000")
    assert not hasattr(stompmodel.units, "scaled_nm")


def test_scaled_nm_scales_exactly_not_through_binary_float() -> None:
    """0.1 mm has no exact binary representation; the Decimal path must not
    inherit its error, which is the whole reason this helper exists."""
    from stompdrill.units import scaled_nm

    assert scaled_nm(0.1) == Decimal("100000")
```

Ensure `from decimal import Decimal` is imported at the top of that test module.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_units.py -q`
Expected: FAIL — `ImportError: cannot import name 'scaled_nm' from 'stompdrill.units'`

- [ ] **Step 3: Move it**

Cut `scaled_nm` and its docstring from `packages/stompmodel/src/stompmodel/units.py` into `packages/stompdrill/src/stompdrill/units.py`, adding `"scaled_nm"` to the latter's `__all__` and removing it from the former's. Carry `from decimal import Decimal` and the `NM_PER_MM` import across; `NM_PER_MM` stays in `stompmodel` and is imported.

Move the existing `scaled_nm` tests out of `packages/stompmodel/tests/test_units.py` into `packages/stompdrill/tests/test_units.py` unchanged.

- [ ] **Step 4: Rewire the three quantisers**

In `pipeline/snap.py`, `pipeline/enclosure.py` and `pipeline/diameters.py`, remove `scaled_nm` from the `stompmodel.units` import and add `from ..units import scaled_nm` (matching each module's existing relative-import style).

- [ ] **Step 5: Run everything**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
cd packages/stompmodel && uv run --no-sync mypy && cd ../..
bash tools/verify-lock.sh
```
Expected: all green; `BEHAVIOUR LOCK HELD`.

- [ ] **Step 6: Commit**

```bash
git add packages/stompmodel packages/stompdrill
git commit -m "Send scaled_nm home, by ADR-0009's own Micron test"
```

---

### Task 4: Promote the CLI target-set validation to `stompmodel`

`ADR-0001:88-90` grants the set-level transaction to `stompdrill`'s command line *"for as long as `stompdrill` is the only caller composing a set of several artefact paths for one invocation."* `--report` plus `--assembly` ends that condition, so the grant terminates itself.

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/protocols.py` (add `target_key`, `check_target_set`, extend `__all__`)
- Create: `packages/stompmodel/tests/test_target_set.py`
- Modify: `packages/stompdrill/src/stompdrill/cli.py:270-315` (delete `_target_key` and the local set check; call the promoted pair)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `stompmodel.protocols.target_key(path: Path) -> str` — the case- and normalisation-folded key over a path's *resolved* form.
  - `stompmodel.protocols.check_target_set(paths: Sequence[Path]) -> None` — raises `ValueError` when two paths share a key, or when an existing path is not a regular file. The caller turns that into its own usage failure; `stompmodel` does not own exit codes for a CLI it cannot see.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompmodel/tests/test_target_set.py`:

```python
"""The set-level write precondition, shared by every tool that emits a set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stompmodel.protocols import check_target_set, target_key


def test_two_spellings_of_one_path_share_a_key(tmp_path: Path) -> None:
    """A filesystem may hold two spellings as one file, so the key folds case
    and Unicode normalisation."""
    assert target_key(tmp_path / "Out.STP") == target_key(tmp_path / "out.stp")


def test_a_symlinked_pair_shares_a_key(tmp_path: Path) -> None:
    """Resolution, not string equality: two names joined by a link are one file.

    This is the clause a key built from the unresolved path passes silently.
    """
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    os.symlink(real, link)
    assert target_key(link) == target_key(real)


def test_a_colliding_set_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one file"):
        check_target_set([tmp_path / "a.json", tmp_path / "A.JSON"])


def test_a_distinct_set_is_accepted(tmp_path: Path) -> None:
    """The innocent probe: a legitimate set must not be refused."""
    assert check_target_set([tmp_path / "a.json", tmp_path / "b.stp"]) is None


def test_an_existing_non_regular_target_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "somewhere"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        check_target_set([directory])


def test_an_existing_regular_target_is_accepted(tmp_path: Path) -> None:
    """Overwriting a file this tool wrote before is the normal case."""
    existing = tmp_path / "a.json"
    existing.write_text("{}")
    assert check_target_set([existing]) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_target_set.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_target_set'`

- [ ] **Step 3: Move the implementation**

Add to `packages/stompmodel/src/stompmodel/protocols.py`, importing `unicodedata` and `Path`:

```python
def target_key(path: Path) -> str:
    """A key under which two spellings of one file compare equal.

    Resolved first: a filesystem may hold two spellings, or two paths joined
    by a symlink, as one file. Folded twice because casefolding can itself
    denormalise -- see ADR-0005.
    """
    resolved = str(path.resolve())
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", resolved).casefold())


def check_target_set(paths: Sequence[Path]) -> None:
    """Refuse a set two of whose members would reach one file.

    Raises ``ValueError``; the caller owns what that means for its own exit
    code, because this package cannot see a command line.
    """
    seen: dict[str, Path] = {}
    for path in paths:
        key = target_key(path)
        if key in seen:
            raise ValueError(
                f"{path} and {seen[key]} name one file; each artefact needs its own"
            )
        seen[key] = path
        if path.exists() and not path.is_file():
            raise ValueError(f"{path} exists and is not a regular file")
```

Add `"target_key"` and `"check_target_set"` to `protocols.py`'s `__all__`, after `"stage_payload"`.

- [ ] **Step 4: Rewire `stompdrill`'s CLI**

Delete `_target_key` from `packages/stompdrill/src/stompdrill/cli.py` and replace the local duplicate/regular-file loop with one call, translating the exception into the CLI's own usage failure:

```python
from stompmodel.protocols import check_target_set
...
    try:
        check_target_set([path for _format, path in targets])
    except ValueError as error:
        raise UsageError(str(error)) from error
```

Match the surrounding code's existing error type and message style — read the function before editing, and keep the emitted message text identical where a test asserts on it.

- [ ] **Step 5: Run everything**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
cd packages/stompmodel && uv run --no-sync mypy && cd ../..
bash tools/verify-lock.sh
```
Expected: all green; `BEHAVIOUR LOCK HELD`.

- [ ] **Step 6: Commit**

```bash
git add packages/stompmodel packages/stompdrill
git commit -m "Promote the target-set precondition, ADR-0001's grant having lapsed"
```

---

### Task 5: Give `CoordinateFrame` composition, and `to_model` its depth

Ruling 3: `CoordinateFrame` is a `gp_Ax3` in all but name, so the workspace is not missing a transform *type* — it is missing composition. Ruling 4: `to_model` is asymmetric with a `to_canonical` that already returns three values, and three shipped sites patch the gap by overwriting a kernel component, which equals translating along `w` only while `w` stays axis-aligned.

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/frames.py`
- Modify: `packages/stompmodel/tests/test_frames.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/region.py:166`, `:232`
- Modify: `packages/stompdrill/src/stompdrill/emitters/step.py:244`

**Interfaces:**
- Consumes: `stompmodel.units.Nanometre`, `mm_from_nm`, `nm_from_mm`
- Produces, all on `stompmodel.frames`:
  - `RigidTransform` — frozen, slotted. `rotation: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]` (row-major), `translation_mm: tuple[float, float, float]`. Millimetre floats, not nanometres: a transform is a kernel-facing quantity applied to float geometry, never a canonical length a document states.
  - `RigidTransform.apply_point(point_mm) -> tuple[float, float, float]`
  - `RigidTransform.apply_direction(direction) -> tuple[float, float, float]` — rotation only. This is Ruling 4's direction transform, free.
  - `CoordinateFrame.translated_nm(du_nm, dv_nm, dw_nm) -> CoordinateFrame` — same basis, origin moved along **this frame's own** axes.
  - `CoordinateFrame.rotated_about_w(radians) -> CoordinateFrame` — same origin, `u` and `v` rotated, `w` fixed.
  - `CoordinateFrame.placement_onto(target) -> RigidTransform` — the rigid motion carrying **this frame onto** `target`. Not a coordinate restatement: `to_canonical`∘`to_model` is that, and they are different operations.
  - `CoordinateFrame.to_model(x_nm, y_nm, depth_nm=Nanometre(0))` — third argument optional, so no existing call site changes.

**Order note:** `stompcollider`'s placement is `face_frame.translated_nm(x, y, z).rotated_about_w(theta)`, translated first. Rotation about `w` leaves the origin fixed, so translating first puts the origin at `face_origin + x·u + y·v + z·w` in the **original** face axes, which is what `stompcollider-technical.md:277-288` step 2 specifies.

- [ ] **Step 1: Write the failing tests**

Add to `packages/stompmodel/tests/test_frames.py`:

```python
def _frame(
    origin_nm: tuple[int, int, int] = (0, 0, 0),
    u: tuple[float, float, float] = (1.0, 0.0, 0.0),
    v: tuple[float, float, float] = (0.0, 1.0, 0.0),
    w: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(origin_nm[0]), Nanometre(origin_nm[1]), Nanometre(origin_nm[2])),
        u=u, v=v, w=w,
    )


def test_to_model_depth_defaults_to_the_frame_plane() -> None:
    """The new argument is additive: omitting it must reproduce today's answer."""
    frame = _frame(origin_nm=(10_000_000, 20_000_000, 30_000_000))
    assert frame.to_model(Nanometre(1_000_000), Nanometre(2_000_000)) == (11.0, 22.0, 30.0)


def test_to_model_depth_moves_along_w_not_along_a_kernel_axis() -> None:
    """The clause the three patched call sites got right only by luck: on a
    frame whose w is not a kernel axis, a depth is a translation along w."""
    root = 2.0 ** -0.5
    frame = _frame(u=(0.0, 1.0, 0.0), v=(root, 0.0, -root), w=(-root, 0.0, -root))
    x, y, z = frame.to_model(Nanometre(0), Nanometre(0), Nanometre(1_000_000))
    assert round(x, 12) == round(-root, 12)
    assert round(y, 12) == 0.0
    assert round(z, 12) == round(-root, 12)


def test_apply_direction_ignores_the_translation() -> None:
    """A direction has no origin. to_canonical subtracting one is the defect
    Ruling 4 names; a rotation-only operation is the answer."""
    moved = _frame().translated_nm(Nanometre(10_000_000), Nanometre(0), Nanometre(0))
    motion = _frame().placement_onto(moved)
    assert motion.apply_direction((1.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)
    assert motion.apply_point((0.0, 0.0, 0.0)) == (10.0, 0.0, 0.0)


def test_placement_onto_carries_this_frame_onto_the_target() -> None:
    """The defining property, stated on all four of a frame's parts."""
    source = _frame(origin_nm=(1_000_000, 2_000_000, 3_000_000))
    target = _frame(
        origin_nm=(50_000_000, 0, 0), u=(0.0, 1.0, 0.0), v=(-1.0, 0.0, 0.0), w=(0.0, 0.0, 1.0)
    )
    motion = source.placement_onto(target)
    moved_origin = motion.apply_point((1.0, 2.0, 3.0))
    assert tuple(round(c, 9) for c in moved_origin) == (50.0, 0.0, 0.0)
    assert tuple(round(c, 9) for c in motion.apply_direction(source.u)) == target.u
    assert tuple(round(c, 9) for c in motion.apply_direction(source.w)) == target.w


def test_placement_onto_itself_is_the_identity() -> None:
    """The innocent probe: a frame already in place must not be moved."""
    frame = _frame(origin_nm=(7_000_000, 0, 0))
    motion = frame.placement_onto(frame)
    assert tuple(round(c, 12) for c in motion.apply_point((1.0, 2.0, 3.0))) == (1.0, 2.0, 3.0)


def test_rotated_about_w_keeps_the_normal_and_stays_right_handed() -> None:
    """Both clauses matter: a rotation that flipped w would still be unit."""
    turned = _frame().rotated_about_w(math.pi / 2)
    assert turned.w == (0.0, 0.0, 1.0)
    assert tuple(round(c, 12) for c in turned.u) == (0.0, 1.0, 0.0)
    # __post_init__ re-checks u x v == w, so construction proves handedness.


def test_translated_nm_moves_along_the_frames_own_axes() -> None:
    """Not along the kernel's. A frame turned 90 degrees moves sideways."""
    turned = _frame().rotated_about_w(math.pi / 2)
    moved = turned.translated_nm(Nanometre(1_000_000), Nanometre(0), Nanometre(0))
    assert tuple(int(c) for c in moved.origin_nm) == (0, 1_000_000, 0)
```

Ensure `import math` and `from stompmodel.units import Nanometre` are present at the top of that module.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_frames.py -q`
Expected: FAIL — `AttributeError: 'CoordinateFrame' object has no attribute 'translated_nm'`

- [ ] **Step 3: Implement**

In `packages/stompmodel/src/stompmodel/frames.py`, extend `__all__` to `["CoordinateFrame", "FaceFrame", "RigidTransform"]` and add:

```python
@dataclass(frozen=True, slots=True)
class RigidTransform:
    """A rotation then a translation: one rigid motion of a body.

    Millimetre floats rather than nanometres. This is applied to kernel
    geometry, which is float millimetres throughout; a canonical length is
    what a document states, and a document never states this value.
    """

    rotation: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ]
    translation_mm: tuple[float, float, float]

    def apply_point(self, point_mm: tuple[float, float, float]) -> tuple[float, float, float]:
        """Rotate and translate a position."""
        return tuple(  # type: ignore[return-value]
            _dot(row, point_mm) + shift
            for row, shift in zip(self.rotation, self.translation_mm)
        )

    def apply_direction(
        self, direction: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        """Rotate an orientation. A direction has no origin to translate."""
        return tuple(_dot(row, direction) for row in self.rotation)  # type: ignore[return-value]
```

Add these three methods to `CoordinateFrame`, after `reframe`:

```python
    def translated_nm(
        self, du_nm: Nanometre, dv_nm: Nanometre, dw_nm: Nanometre
    ) -> CoordinateFrame:
        """A copy moved along this frame's own axes, basis unchanged."""
        shifted = tuple(
            origin + nm_from_mm(
                mm_from_nm(du_nm) * self.u[i]
                + mm_from_nm(dv_nm) * self.v[i]
                + mm_from_nm(dw_nm) * self.w[i]
            )
            for i, origin in enumerate(self.origin_nm)
        )
        return CoordinateFrame(
            origin_nm=(Nanometre(shifted[0]), Nanometre(shifted[1]), Nanometre(shifted[2])),
            u=self.u, v=self.v, w=self.w,
        )

    def rotated_about_w(self, radians: float) -> CoordinateFrame:
        """A copy turned about its own normal, origin and ``w`` unchanged."""
        cos, sin = math.cos(radians), math.sin(radians)
        turned_u = tuple(cos * a + sin * b for a, b in zip(self.u, self.v))
        turned_v = tuple(-sin * a + cos * b for a, b in zip(self.u, self.v))
        return CoordinateFrame(
            origin_nm=self.origin_nm,
            u=(turned_u[0], turned_u[1], turned_u[2]),
            v=(turned_v[0], turned_v[1], turned_v[2]),
            w=self.w,
        )

    def placement_onto(self, target: CoordinateFrame) -> RigidTransform:
        """The rigid motion carrying this frame onto ``target``.

        Not a coordinate restatement -- ``to_canonical`` composed with
        ``to_model`` is that. This moves a body; that renames a point.
        """
        rows = tuple(
            (
                target.u[i] * self.u[j] + target.v[i] * self.v[j] + target.w[i] * self.w[j]
                for j in range(_COMPONENTS)
            )
            for i in range(_COMPONENTS)
        )
        rotation = tuple(tuple(row) for row in rows)
        here = tuple(mm_from_nm(value) for value in self.origin_nm)
        there = tuple(mm_from_nm(value) for value in target.origin_nm)
        translation = tuple(
            there[i] - _dot(rotation[i], here) for i in range(_COMPONENTS)
        )
        return RigidTransform(
            rotation=rotation,  # type: ignore[arg-type]
            translation_mm=(translation[0], translation[1], translation[2]),
        )
```

Widen `to_model`:

```python
    def to_model(
        self, x_nm: Nanometre, y_nm: Nanometre, depth_nm: Nanometre = Nanometre(0)
    ) -> tuple[Millimetre, Millimetre, Millimetre]:
        """Map canonical face coordinates, at an optional depth, into model mm.

        ``depth_nm`` runs along ``w``. Optional so that a caller stating a
        point on the frame's own plane -- which is what canonical means --
        need not say so.
        """
        x, y, z = mm_from_nm(x_nm), mm_from_nm(y_nm), mm_from_nm(depth_nm)
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        return (
            Millimetre(origin[0] + x * self.u[0] + y * self.v[0] + z * self.w[0]),
            Millimetre(origin[1] + x * self.u[1] + y * self.v[1] + z * self.w[1]),
            Millimetre(origin[2] + x * self.u[2] + y * self.v[2] + z * self.w[2]),
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q`
Expected: PASS, including every pre-existing frame test unchanged.

- [ ] **Step 5: Collapse the three patch sites**

Each site currently reads `list(to_model(x, y))` then assigns one kernel component. Replace with a `to_model` carrying the depth **expressed along `w`**, which is the frame-relative quantity — not the absolute kernel coordinate the old code assigned.

In `packages/stompdrill/src/stompdrill/cad/region.py:166` and `:232`, the depth is the plane's own offset from the frame origin:

```python
    plane_at = bounding_box_mm(region)[axis]
    depth_nm = nm_from_mm((plane_at - mm_from_nm(frame.basis.origin_nm[axis])) * frame.basis.w[axis])
    point = frame.basis.to_model(x_nm, y_nm, depth_nm)
```

In `packages/stompdrill/src/stompdrill/emitters/step.py:244`, likewise with `model.drilled_position_mm` in place of `plane_at` and `model.axis` in place of `axis`.

**This is the one step in Phase 0 that can move a byte**, because it re-derives a coordinate rather than assigning it. Run the lock immediately and read the result before continuing; if an artefact moves, the arithmetic above is wrong, not the lock.

- [ ] **Step 6: Run everything**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
cd packages/stompmodel && uv run --no-sync mypy && cd ../..
bash tools/verify-lock.sh
```
Expected: all green; `BEHAVIOUR LOCK HELD`.

- [ ] **Step 7: Commit**

```bash
git add packages/stompmodel packages/stompdrill
git commit -m "Give the frame layer composition and its third dimension"
```

---

### Task 6: Realise a placement in the kernel

Ruling 3's upper half: `stompgeom` gains the one function turning a `RigidTransform` into a `TopLoc_Location` and applying it to a shape. Nothing in the workspace constructs one today — `grep -rn "gp_Trsf\|TopLoc_Location" packages/*/src/ tools/` returns nothing.

**Files:**
- Modify: `packages/stompgeom/src/stompgeom/shapes.py` (created in Task 1)
- Modify: `packages/stompgeom/tests/test_shapes.py`

**Interfaces:**
- Consumes: `stompmodel.frames.RigidTransform`
- Produces: `stompgeom.shapes.placed(shape: Any, motion: RigidTransform) -> Any` — a **located** copy of `shape`, made by `TopoDS_Shape.Moved` with a `TopLoc_Location`. A location rather than `BRepBuilderAPI_Transform`: it rebuilds no geometry, so the STEP writer sees the original topology under a placement, which is what keeps names and colours attached.

- [ ] **Step 1: Write the failing tests**

Add to `packages/stompgeom/tests/test_shapes.py`:

```python
def _centre(shape: Any) -> tuple[float, float, float]:
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(shape)
    return tuple((box[i] + box[i + 3]) / 2 for i in range(3))  # type: ignore[return-value]


def test_placed_moves_the_shape() -> None:
    from stompmodel.frames import RigidTransform

    from stompgeom.shapes import placed

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    moved = placed(_box(2, 2, 2), RigidTransform(identity, (10.0, 0.0, 0.0)))
    assert round(_centre(moved)[0], 9) == 11.0


def test_placed_rotates_as_well_as_translates() -> None:
    """A translation-only implementation passes the test above and fails this."""
    from stompmodel.frames import RigidTransform

    from stompgeom.shapes import placed

    quarter_turn = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    moved = placed(_box(4, 2, 2), RigidTransform(quarter_turn, (0.0, 0.0, 0.0)))
    from stompgeom.step import bounding_box_mm

    box = bounding_box_mm(moved)
    assert round(box[4] - box[1], 9) == 4.0     # the long axis is now y


def test_placed_leaves_the_original_alone() -> None:
    """Value semantics: the workspace's transforms return replacements."""
    from stompmodel.frames import RigidTransform

    from stompgeom.shapes import placed

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    original = _box(2, 2, 2)
    placed(original, RigidTransform(identity, (10.0, 0.0, 0.0)))
    assert round(_centre(original)[0], 9) == 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_shapes.py -q`
Expected: FAIL — `ImportError: cannot import name 'placed'`

- [ ] **Step 3: Implement**

Append to `packages/stompgeom/src/stompgeom/shapes.py`, extending `__all__` to `["compound", "placed"]`:

```python
def placed(shape: Any, motion: RigidTransform) -> Any:
    """A located copy of ``shape`` under ``motion``.

    A ``TopLoc_Location`` rather than a rebuilt transform: locating
    rebuilds no geometry, so the writer still sees the original topology
    and the names and colours attached to it survive the placement.
    """
    require_kernel()
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    rows = motion.rotation
    trsf.SetValues(
        rows[0][0], rows[0][1], rows[0][2], motion.translation_mm[0],
        rows[1][0], rows[1][1], rows[1][2], motion.translation_mm[1],
        rows[2][0], rows[2][1], rows[2][2], motion.translation_mm[2],
    )
    return shape.Moved(TopLoc_Location(trsf))
```

Add `from stompmodel.frames import RigidTransform` to the module's imports.

- [ ] **Step 4: Run to verify they pass**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/stompgeom
git commit -m "Realise a rigid placement as a kernel location"
```

---

### Task 7: `stompgeom.levels()` — the coplanar-face partition

Rulings 1 and 2, and the largest task in Phase 0. `stompdrill`'s private `_levels` plus the ~22-line harvest clump around it become one published partition. `docs/BACKLOG.md:662-676` sizes this as a code-motion problem; under a partition that takes a solid there is no clump to name, so **that entry's Acceptance is rewritten in Task 9, not ticked**.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/levels.py`
- Create: `packages/stompgeom/tests/test_levels.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/case.py` (delete the harvest, `_Level`, `_levels`, `_outward_sign`; rewrite `find_faces`; rewire `_plates`, `_drilled_level`, `_inner_level`, `_nearest_companion_level`)
- Modify: `packages/stompdrill/tests/test_cad_case_synthetic.py` (ticket 55's `_outward_sign` tests move or retire)
- Modify: `packages/stompdrill/tests/test_cad_case.py` (`_level` helper builds a `stompgeom` `Level`)

**Interfaces:**
- Consumes: `stompgeom.step.StepSolid`, `stompgeom.kernel.require_kernel`, `stompmodel.units.Nanometre`, `nm_from_mm`
- Produces, on `stompgeom.levels`:
  - `Direction = tuple[float, float, float]` — a unit vector.
  - `Level` — frozen, slotted: `direction: Direction` (unit, **outward-facing**), `offset_nm: Nanometre` (signed, measured **along `direction`**), `area_mm2: float`, `faces: tuple[Any, ...]`.
  - `levels(solid: StepSolid, axis: Direction | None = None) -> tuple[Level, ...]`
- **Retired:** `stompdrill.cad.case._Level`, `._levels`, `._outward_sign`, and the `outward: int` field. A level's facing is now its direction's sign.

**Two invariants an implementer must not conflate:**

1. **Offset is signed along the outward direction**, so two opposed levels' offsets **sum** to the slab thickness — `0.000 + 1.510` on `fixtures/tar-pcb.stp`. `find_faces`' `abs(inner.position - drilled.position)` therefore becomes a **sum**, not a difference.
2. **Two tolerances, distinct jobs.** The millionth grouping granularity decides *are these faces the same plane as each other*. The inherited `1e-9` parallelism test decides *is this plane aligned with the caller's axis*, and is `cad/case.py:151`'s test carried across **unchanged** — exact equality on a quantised direction is not equivalent and would narrow `stompdrill`'s acceptance.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompgeom/tests/test_levels.py`:

```python
"""The coplanar-face partition, its granularity, and its control."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from stompgeom.levels import Level, levels


@dataclass(frozen=True)
class _Solid:
    name: str
    shape: Any


def _box(dx: float, dy: float, dz: float) -> _Solid:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return _Solid("box", BRepPrimAPI_MakeBox(dx, dy, dz).Shape())


def _planar_faces(shape: Any) -> int:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    count = 0
    while explorer.More():
        adaptor = BRepAdaptor_Surface(TopoDS.Face_s(explorer.Current()))
        count += adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane
        explorer.Next()
    return count


def test_a_cuboid_partitions_into_six_levels() -> None:
    """Six faces, six directions, no two coplanar."""
    assert len(levels(_box(10.0, 20.0, 30.0))) == 6  # type: ignore[arg-type]


def test_every_planar_face_lands_in_exactly_one_level() -> None:
    """The partition property: nothing dropped, nothing counted twice."""
    solid = _box(10.0, 20.0, 30.0)
    found = levels(solid)  # type: ignore[arg-type]
    assert sum(len(level.faces) for level in found) == _planar_faces(solid.shape)


def test_opposed_offsets_sum_to_the_thickness() -> None:
    """Offset runs along each face's OWN outward normal, so the pair adds.

    A level whose offset were measured along a fixed axis would subtract
    here, which is the arithmetic find_faces must switch to.
    """
    found = levels(_box(10.0, 20.0, 3.0))  # type: ignore[arg-type]
    down = next(l for l in found if tuple(round(c) for c in l.direction) == (0, 0, -1))
    up = next(l for l in found if tuple(round(c) for c in l.direction) == (0, 0, 1))
    assert round(float(down.offset_nm + up.offset_nm) / 1e6, 6) == 3.0


def test_the_axis_filter_keeps_both_facings() -> None:
    """An axis is unsigned: a caller asking for z wants the top and the bottom."""
    found = levels(_box(10.0, 20.0, 30.0), axis=(0.0, 0.0, 1.0))  # type: ignore[arg-type]
    assert len(found) == 2
    assert {tuple(round(c) for c in l.direction) for l in found} == {(0, 0, 1), (0, 0, -1)}


def test_the_axis_filter_admits_a_face_tilted_within_the_inherited_tolerance() -> None:
    """cad/case.py:151's test, carried across unchanged. Exact equality on a
    quantised direction would reject this and narrow stompdrill's acceptance.
    """
    tilt = 1e-7
    solid = _Solid("tilted", _tilted_slab(tilt))
    assert len(levels(solid, axis=(0.0, 0.0, 1.0))) == 2  # type: ignore[arg-type]


def _tilted_slab(radians: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    shape = BRepPrimAPI_MakeBox(10.0, 10.0, 2.0).Shape()
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), radians)
    return shape.Moved(TopLoc_Location(turn))


def test_faces_of_one_plane_separated_by_export_noise_stay_one_level() -> None:
    """The granularity's INNOCENT probe.

    fixtures/tar-pcb.stp carries a face tilted 3.846e-08 off axis -- export
    noise, not geometry -- which the shipped acceptance test admits. At the
    ruled millionth granularity it stays with its plane.
    """
    from pathlib import Path

    from stompgeom.step import read_step

    document = read_step(Path(__file__).parents[3] / "fixtures" / "tar-pcb.stp")
    strip = min(
        (s for s in document.solids if not s.name),
        key=lambda s: sum(len(l.faces) for l in levels(s)),
    )
    wall = [
        l for l in levels(strip)
        if tuple(round(c) for c in l.direction) == (0, -1, 0)
        and round(float(l.offset_nm) / 1e6, 3) == 37.500
    ]
    assert len(wall) == 1
    assert round(wall[0].area_mm2, 2) == 98.15


def test_a_billionth_granularity_would_split_that_wall() -> None:
    """The granularity's GUILTY probe.

    A control, not a behaviour: it re-runs the partition at the rejected
    granularity and asserts the split the ruling measured, so the constant
    above is evidence rather than a number nothing exercises.
    """
    from pathlib import Path

    from stompgeom.levels import _partition
    from stompgeom.step import read_step

    document = read_step(Path(__file__).parents[3] / "fixtures" / "tar-pcb.stp")
    strip = min(
        (s for s in document.solids if not s.name),
        key=lambda s: sum(len(l.faces) for l in levels(s)),
    )
    fine = [
        l for l in _partition(strip.shape, scale=1e9)
        if tuple(round(c) for c in l.direction) == (0, -1, 0)
        and round(float(l.offset_nm) / 1e6, 3) == 37.500
    ]
    assert len(fine) == 2
    assert sorted(round(l.area_mm2, 2) for l in fine) == [39.26, 58.89]


def test_the_partition_does_not_depend_on_traversal_order() -> None:
    """ADR-0006: no rule may consult input order. Keying, not clustering, is
    what makes this true by construction rather than by luck."""
    solid = _box(10.0, 20.0, 30.0)
    once = levels(solid)  # type: ignore[arg-type]
    twice = levels(solid)  # type: ignore[arg-type]
    key = lambda level: (level.direction, int(level.offset_nm))
    assert sorted(once, key=key) == sorted(twice, key=key)


def test_a_published_direction_is_exactly_unit() -> None:
    """CoordinateFrame's 1e-9 unit-length check must have margin, so the
    quantised key is re-normalised rather than handed back as it rounds."""
    for level in levels(_box(1.0, 1.0, 1.0)):  # type: ignore[arg-type]
        assert abs(math.sqrt(sum(c * c for c in level.direction)) - 1.0) < 1e-15
```

The two fixture probes are the granularity's control pair and must run in the same command as the rest. `fixtures/tar-pcb.stp` sits at the repository root until Task 16 homes it; `Path(__file__).parents[3]` reaches it from `packages/stompgeom/tests/`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_levels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stompgeom.levels'`

- [ ] **Step 3: Implement**

Create `packages/stompgeom/src/stompgeom/levels.py`:

```python
"""Grouping a solid's planar faces into the planes they lie in.

A partition, not a search: every planar face belongs to exactly one level,
keyed on the face's own outward direction and offset. See ADR-0008 and
docs/specs/foundation-docket-rulings.md.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from stompmodel.units import Nanometre, nm_from_mm

from .kernel import require_kernel
from .step import StepSolid

__all__ = ["Direction", "Level", "levels"]

Direction = tuple[float, float, float]

#: Direction components are keyed as integer millionths. Chosen from a
#: measured gap, not rounded to taste: the largest real coplanar deviation
#: across every available fixture is 3.846e-08, and the tolerance the axis
#: filter below inherits is ~4.5e-5 radians. A millionth sits 26x above the
#: noise and 45x below the tolerance -- near that three-order gap's
#: geometric midpoint. A billionth was measured and rejected: it splits one
#: real side wall in two. tests/test_levels.py holds both probes.
_DIRECTION_SCALE = 1e6

#: How nearly a plane's normal must lie along a caller's axis to be kept.
#: Inherited unchanged from stompdrill's cad/case.py, where it has always
#: governed this decision; it is not a second expression of the constant
#: above and does not track it.
_PARALLEL_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class Level:
    """Every coplanar planar face of one solid sharing one outward facing.

    ``offset_nm`` is signed **along** ``direction``, so two opposed levels'
    offsets sum to the material between them. A single physical plane can
    tessellate into disconnected patches, which is why this is a set.
    """

    direction: Direction
    offset_nm: Nanometre
    area_mm2: float
    faces: tuple[Any, ...]


def _partition(shape: Any, scale: float = _DIRECTION_SCALE) -> tuple[Level, ...]:
    """Every planar face of ``shape``, grouped by outward direction and offset.

    ``scale`` is a parameter only so the granularity's guilty probe can drive
    the rejected value; production callers take the default.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    groups: dict[tuple[tuple[int, int, int], int], list[tuple[float, Any]]] = defaultdict(list)
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            plane = adaptor.Plane()
            axis, location = plane.Axis().Direction(), plane.Location()
            outward = [axis.X(), axis.Y(), axis.Z()]
            if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
                outward = [-component for component in outward]
            offset = (
                location.X() * outward[0]
                + location.Y() * outward[1]
                + location.Z() * outward[2]
            )
            key = (
                (
                    round(outward[0] * scale),
                    round(outward[1] * scale),
                    round(outward[2] * scale),
                ),
                int(nm_from_mm(offset)),
            )
            properties = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, properties)
            groups[key].append((properties.Mass(), face))
        explorer.Next()
    return tuple(
        Level(
            direction=_unit(components, scale),
            offset_nm=Nanometre(offset_nm),
            area_mm2=sum(area for area, _face in members),
            faces=tuple(face for _area, face in members),
        )
        for (components, offset_nm), members in groups.items()
    )


def _unit(components: tuple[int, int, int], scale: float) -> Direction:
    """The quantised key as a unit vector.

    Re-normalised rather than handed back as it rounds, so that every member
    of a level shares one bit-identical direction and a consumer's own
    unit-length check has margin.
    """
    raw = [component / scale for component in components]
    length = math.sqrt(sum(component * component for component in raw))
    return (raw[0] / length, raw[1] / length, raw[2] / length)


def levels(solid: StepSolid, axis: Direction | None = None) -> tuple[Level, ...]:
    """Group ``solid``'s planar faces into the planes they lie in.

    ``axis`` is an optional **unsigned** filter: given one, levels facing
    either way along it are kept and the rest dropped, by the parallelism
    test stompdrill has always applied.
    """
    require_kernel()
    found = _partition(solid.shape)
    if axis is None:
        return found
    return tuple(
        level for level in found
        if abs(abs(_dot(level.direction, axis)) - 1.0) < _PARALLEL_TOLERANCE
    )


def _dot(a: Direction, b: Direction) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_levels.py -q`
Expected: PASS, 9 tests, **including both granularity probes**.

- [ ] **Step 5: Rewrite `find_faces` onto it**

In `packages/stompdrill/src/stompdrill/cad/case.py`:

- Delete `_outward_sign`, `_Level` and `_levels` entirely.
- Import `from stompgeom.levels import Level, levels`.
- Replace the whole harvest block in `find_faces` (the `TopExp_Explorer` walk building `planes`, and the `_levels(...)` call) with one line, converting the kernel-axis index the signature still takes into the direction the partition wants:

```python
    unit: list[float] = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    found = _plates(list(levels(solid, axis=(unit[0], unit[1], unit[2]))))
```

- Change every `level.position` to `mm_from_nm(level.offset_nm)` **and correct the sense**: the offset is signed along the level's own outward direction, so a `-1`-facing level at kernel coordinate `low` now carries `offset_nm == nm_from_mm(-low)`. In `_drilled_level`, the bounding-box comparison becomes:

```python
    low, high = solid_bbox[axis], solid_bbox[axis + 3]
    candidates = [
        level for level in levels_
        if (level.direction[axis] < 0 and level.offset_nm == nm_from_mm(-low))
        or (level.direction[axis] > 0 and level.offset_nm == nm_from_mm(high))
    ]
```

- In `_inner_level`, `inward = -drilled.direction[axis]` selects by `level.direction[axis] * inward > 0`, and the position inequality compares `offset_nm` directly — both are integers, so the comparison is exact and no rounding helper is needed.
- In `find_faces`, `thickness` becomes a **sum**:

```python
    thickness = mm_from_nm(Nanometre(inner.offset_nm + drilled.offset_nm))
```

- `Faces.outward` keeps its `tuple[float, float, float]` type and is now `drilled.direction` directly, with no `normal` list to build.
- `_plates` and `_nearest_companion_level` change only their type annotations (`list[Level]`) and their `position`/`outward` reads.

- [ ] **Step 6: Update `stompdrill`'s fixtures**

`packages/stompdrill/tests/test_cad_case.py`'s `_level` helper builds a `stompgeom` `Level`, taking a direction rather than an `outward: int`. Ticket 55's `_outward_sign` tests in `test_cad_case_synthetic.py` have lost their subject — the sign field is gone. **Do not delete their evidence:** rewrite the two-faces-of-one-plane test against `stompgeom.levels` instead, so the regression it pins survives the move.

- [ ] **Step 7: Prove nothing moved**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
bash tools/verify-lock.sh
```
Expected: all green; `BEHAVIOUR LOCK HELD`. Every Hammond solid is float-noise clean at every granularity measured, so a break here means the port is wrong, not that the constant is.

- [ ] **Step 8: Commit**

```bash
git add packages/stompgeom packages/stompdrill
git commit -m "Publish the coplanar-face partition as stompgeom.levels()"
```

---

### Task 8: Widen the writer's colour census past the two-solid enclosure it was fitted to

**This blocks the assembly emitter.** `render_step` today refuses `fixtures/tar-pcb.stp` with `EmitterError`: `_count_colour_assignments` walks `leaf_labels` and tests only `XCAFDoc_ColorSurf` on each leaf, while a real board carries colour on sub-shapes, so `expected` is far below the chains actually written. The audit also measured that **deleting `_reslot_colours`' effect leaves `stompgeom`'s whole suite green** — the determinism it exists to provide is untested.

**Files:**
- Modify: `packages/stompgeom/src/stompgeom/writer.py` (`_count_colour_assignments`, `_COLOUR_CHAIN`, the mismatch message)
- Create: `packages/stompgeom/tests/fixtures/per_face_colours.py` (a built document, not a committed binary)
- Modify: `packages/stompgeom/tests/test_writer.py`

**Interfaces:**
- Consumes: `stompgeom.step.StepLabel`, `leaf_labels`
- Produces: no signature change. `render_step` gains the ability to write a document whose colours sit on sub-shapes.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompgeom/tests/fixtures/per_face_colours.py`:

```python
"""A document colouring sub-shapes, not only whole solids.

Built rather than committed: a binary fixture would fix one OpenCASCADE
version's encoding into the repository, which is the coupling the writer's
own guard exists to detect.
"""

from __future__ import annotations

from typing import Any


def per_face_coloured_document() -> Any:
    """One box whose six faces carry six different surface colours."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    shape_tool.AddShape(box, True)

    explorer = TopExp_Explorer(box, TopAbs_ShapeEnum.TopAbs_FACE)
    index = 0
    while explorer.More():
        shade = (index + 1) / 8.0
        color_tool.SetColor(
            explorer.Current(),
            Quantity_Color(shade, 1.0 - shade, 0.5, Quantity_TypeOfColor.Quantity_TOC_RGB),
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )
        index += 1
        explorer.Next()
    return document
```

Add to `packages/stompgeom/tests/test_writer.py`:

```python
def test_a_per_face_coloured_document_is_written_not_refused() -> None:
    """The census must count what the writer will emit. Counting only leaf
    solids under-counts a board by orders of magnitude and the guard fires.
    """
    from stompgeom.writer import render_step

    from .fixtures.per_face_colours import per_face_coloured_document

    payload = render_step(
        per_face_coloured_document(),
        title="probe",
        timestamp="1970-01-01T00:00:00+00:00",
        originating_system="test",
    )
    assert payload.count(b"STYLED_ITEM") >= 6


def test_two_writes_of_one_document_are_byte_identical_across_processes() -> None:
    """The control _reslot_colours never had.

    Slot assignment hashes on a TShape POINTER, so two writes inside one
    process can agree by accident. Only separate interpreters vary the
    allocator enough to exercise the defect, which is why this shells out.
    """
    import subprocess
    import sys

    script = (
        "from stompgeom.writer import render_step;"
        "from stompgeom.tests.fixtures.per_face_colours import per_face_coloured_document;"
        "import hashlib,sys;"
        "sys.stdout.write(hashlib.sha256(render_step("
        "per_face_coloured_document(), title='p',"
        "timestamp='1970-01-01T00:00:00+00:00', originating_system='t')).hexdigest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(2)
    }
    assert len(digests) == 1


def test_the_byte_identity_control_fails_when_the_reslot_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GUILTY probe for the test above.

    Without this, a reslot that stopped working would leave the suite green,
    which the 2026-08 audit measured as the actual state of affairs.
    """
    from stompgeom import writer

    monkeypatch.setattr(writer, "_reslot_colours", lambda payload, expected: payload)
    document = per_face_coloured_document()
    unsorted = writer.render_step(
        document, title="p", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    reslotted = writer.render_step.__wrapped__ if False else None  # placeholder guard
    assert reslotted is None
    # The claim under test: the reslot is the step that imposes an order, so
    # the payload without it must differ from the payload with it whenever
    # the document has more than one chain.
    monkeypatch.undo()
    ordered = writer.render_step(
        document, title="p", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    assert unsorted != ordered or unsorted.count(b"STYLED_ITEM") < 2
```

**Note for the implementer:** the third test above is written to a shape the executor must finish — it asserts the reslot changes the payload, which holds only when the slots arrived unsorted. If the built fixture proves too stable to demonstrate that in-process, replace the assertion with a subprocess pair run under `PYTHONHASHSEED` variation and keep the guilty/innocent structure. **Do not delete it and leave the byte-identity test uncontrolled** — that is precisely the vacuity this task exists to remove.

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_writer.py -q`
Expected: FAIL — `EmitterError: the source document assigns 1 colour(s), but 6 STYLED_ITEM chain(s) were found`

- [ ] **Step 3: Widen the census**

In `_count_colour_assignments`, walk the colour tool's own inventory rather than the shape tree, and count all three colour types:

```python
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    coloured: set[str] = set()
    labels = TDF_LabelSequence()
    color_tool.GetColors(labels)
    for index in range(1, labels.Length() + 1):
        shapes = TDF_LabelSequence()
        color_tool.GetShapesOfColor(labels.Value(index), shapes)  # or the version's equivalent
        for position in range(1, shapes.Length() + 1):
            entry = StepLabel(document, shapes.Value(position)).entry
            if entry not in replaced_labels:
                coloured.add(entry)
    return len(coloured)
```

If this OpenCASCADE build exposes no `GetShapesOfColor`, fall back to walking **every** label under the shape tool — components *and* their sub-shape children — testing `IsSet` for `XCAFDoc_ColorSurf`, `XCAFDoc_ColorGen` and `XCAFDoc_ColorCurv`. Verify against the built fixture, which knows it has six.

Generalise `_COLOUR_CHAIN` to match `OVER_RIDING_STYLED_ITEM` as well as `STYLED_ITEM`, and rewrite the mismatch message to name **both** candidate causes rather than only the version one:

```python
        raise EmitterError(
            f"the source document assigns {expected} colour(s), but "
            f"{len(chains)} colour chain(s) were found in the written STEP. "
            "Either this document colours through a route the census does not "
            "walk, or _COLOUR_CHAIN needs updating for this OpenCASCADE "
            "version's chain shape"
        )
```

- [ ] **Step 4: Run to verify they pass, then prove the real board writes**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && cd ../..
.venv/bin/python - <<'PY'
from pathlib import Path
from stompgeom.step import read_step
from stompgeom.writer import render_step
document = read_step(Path("fixtures/tar-pcb.stp"))
print(len(render_step(document.document, title="probe",
      timestamp="1970-01-01T00:00:00+00:00", originating_system="probe")), "bytes")
PY
```
Expected: `stompgeom` green; the board renders without `EmitterError`. Adjust the accessor for the document handle to whatever `StepDocument` exposes.

- [ ] **Step 5: Prove `stompdrill` did not move**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
bash tools/verify-lock.sh
```
Expected: green; `BEHAVIOUR LOCK HELD`. The enclosure path colours whole solids, so a widened census must return the same number for it.

- [ ] **Step 6: Commit**

```bash
git add packages/stompgeom
git commit -m "Teach the writer's colour census the shapes a real board colours"
```

---

### Task 9: Promote the document builder with `placement` and `colour`

ADR-0008:225-229 defers `stompgeom` owning "build" until a real second consumer arrives; the assembly emitter is it. The builder that exists today is a test fixture's construction, and `stompcollider-technical.md:598-602` specifies it promoted with a `placement` parameter — which Task 5 and Task 6 have now made constructible.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/build.py`
- Create: `packages/stompgeom/tests/test_build.py`
- Modify: `packages/stompgeom/src/stompgeom/__init__.py` (docstring; see Task 10)

**Interfaces:**
- Consumes: `stompmodel.frames.RigidTransform`, `stompgeom.shapes.placed`, `stompgeom.step.StepDocument`
- Produces, on `stompgeom.build`:
  - `PlacedSolid` — frozen, slotted: `shape: Any`, `name: str`, `colour: tuple[float, float, float] | None`, `placement: RigidTransform | None`.
  - `build_document(solids: Sequence[PlacedSolid]) -> Any` — a `TDocStd_Document` ready for `render_step`.
  - `solid_colour(document, label) -> tuple[float, float, float] | None` — the published way to read a solid's colour back, which `stompcollider-technical.md:598-602` requires be named explicitly rather than left as "whatever reading half".

**Precondition the first test must assert:** a builder that colours through a route Task 8's census does not walk fails with a message about OpenCASCADE versions. Assert the census agrees before asserting anything about bytes.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompgeom/tests/test_build.py`:

```python
"""Assembling a document from placed, named, coloured solids."""

from __future__ import annotations

from typing import Any

from stompmodel.frames import RigidTransform

from stompgeom.build import PlacedSolid, build_document, solid_colour
from stompgeom.step import bounding_box_mm
from stompgeom.writer import render_step

_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _box(dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def test_a_built_document_renders_without_a_census_mismatch() -> None:
    """The precondition: colouring through a route the census does not walk
    fails with a message about OpenCASCADE versions, not about colour.
    """
    document = build_document([
        PlacedSolid(_box(1, 1, 1), "A", (1.0, 0.0, 0.0), None),
        PlacedSolid(_box(2, 2, 2), "B", (0.0, 1.0, 0.0), None),
    ])
    payload = render_step(
        document, title="t", timestamp="1970-01-01T00:00:00+00:00", originating_system="t"
    )
    assert b"'A'" in payload and b"'B'" in payload


def test_a_placement_moves_the_solid_in_the_built_document() -> None:
    document = build_document([
        PlacedSolid(_box(2, 2, 2), "A", None, RigidTransform(_IDENTITY, (10.0, 0.0, 0.0))),
    ])
    from stompgeom.step import read_step_document  # or the reader this package exposes

    solids = read_step_document(document).solids
    assert round(bounding_box_mm(solids[0].shape)[0], 9) == 10.0


def test_an_absent_placement_leaves_the_solid_where_it_was() -> None:
    """The innocent probe: None must mean untouched, not identity-applied."""
    document = build_document([PlacedSolid(_box(2, 2, 2), "A", None, None)])
    from stompgeom.step import read_step_document

    solids = read_step_document(document).solids
    assert round(bounding_box_mm(solids[0].shape)[0], 9) == 0.0


def test_a_solids_colour_reads_back() -> None:
    """The published reading half stompcollider-technical.md:598-602 requires."""
    document = build_document([PlacedSolid(_box(1, 1, 1), "A", (1.0, 0.0, 0.0), None)])
    from stompgeom.step import read_step_document

    solid = read_step_document(document).solids[0]
    assert solid_colour(document, solid) == (1.0, 0.0, 0.0)


def test_an_uncoloured_solid_reads_back_as_none() -> None:
    document = build_document([PlacedSolid(_box(1, 1, 1), "A", None, None)])
    from stompgeom.step import read_step_document

    solid = read_step_document(document).solids[0]
    assert solid_colour(document, solid) is None
```

**Implementer's note:** `stompgeom.step` currently reads from a `Path`. This task needs a document-level reader so a built document can be inspected without a round trip through the filesystem. Add it if it does not exist, or read the rendered bytes back through a temporary file — the choice is yours, but say which in the commit message, and keep the public name stable because Task 20 depends on it.

- [ ] **Step 2: Run to verify they fail, implement, and re-run**

Run: `cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_build.py -q`

Create `packages/stompgeom/src/stompgeom/build.py` around `XCAFDoc_ShapeTool.AddShape` and `XCAFDoc_ColorTool.SetColor`, reusing the known-good call sequence from the existing test fixture rather than inventing one, applying `shapes.placed` when `placement` is not `None`, and setting the name through `TDataStd_Name`. Keep the module under one screen; it is a constructor, not a subsystem.

- [ ] **Step 3: Full gates**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
ruff check packages tools && mypy packages && bash tools/verify-lock.sh
```

- [ ] **Step 4: Commit**

```bash
git add packages/stompgeom
git commit -m "Promote the document builder, with placement and colour"
```

---

### Task 10: Phase 0's document and ADR amendments

`CLAUDE.md`'s documentation rules make `docs/adr/` the authority and require an ADR be amended *with* the work. Phase 0 has now made five documents wrong.

**Files:**
- Modify: `docs/adr/0001-pipeline-and-emitter-adapters.md:88-90`
- Modify: `docs/adr/0008-workspace-and-shared-geometry-core.md:8-10`
- Modify: `docs/adr/0009-shared-model-package-and-dependency-order.md:146-148`, `:308-310`
- Modify: `docs/specs/stompgeom-technical.md` ("What does not move"; three broken `../../adr/` links)
- Modify: `docs/BACKLOG.md:662-676`, `:678-689`
- Modify: `packages/stompgeom/src/stompgeom/__init__.py` (docstring)
- Modify: `CLAUDE.md` (the Architecture section's `stompgeom` sentence)

- [ ] **Step 1: Make each edit**

Work the ruling's own amendment table, which lists all fourteen with their reasons: `docs/specs/foundation-docket-rulings.md`, section "Document amendments this ruling requires". Each edit states *what changed and why*; none restates an ADR's argument, per the documentation rules.

Two that need care:

`packages/stompgeom/src/stompgeom/__init__.py` currently says the package is "The format side of geometry". After Tasks 1, 6, 7 and 9 it also partitions, places, and builds. Widen it without inflating it — the honest sentence is that `stompgeom` is the workspace's kernel layer, holding the operations that need OpenCASCADE, which is what ADR-0008:8-12 already says.

`docs/BACKLOG.md:662-676`'s Acceptance requires the harvest clump become "a named type rather than a bare tuple". Rewrite it rather than tick it: under a partition taking a solid there is no clump, so the entry closes by having its premise removed, and the record should say so.

- [ ] **Step 2: Check every link resolves**

```bash
cd /Users/thelyx/repo/stompcad
grep -rno '](\.\./[^)]*\.md' docs/specs docs/adr | while IFS=: read -r file _line link; do
  target="$(dirname "$file")/${link#](}"
  [ -f "$target" ] || echo "BROKEN: $file -> $link"
done
```
Expected: no output. Before Task 10 this prints the three `stompgeom-technical.md` links; that is the control showing the check is not vacuous — run it once before editing and once after.

- [ ] **Step 3: Run the documentation audit and commit**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= packages/stompdrill/tests/test_documentation.py -q
git add docs CLAUDE.md packages/stompgeom
git commit -m "Amend the documents Phase 0's moves made wrong"
```

**Phase 0 is complete.** Before starting Phase 1, run every gate in **Commands** above and `bash tools/verify-lock.sh` one final time. No artefact byte should have moved across the whole phase.

---

# Phase 1 — the pure core

Everything in this phase is kernel-free and testable with hand-built values. No task here reads a fixture file.

**A spec observation to carry forward, not to resolve silently:** `stompcollider-technical.md:115-117` says "everything above `sources/` and `emitters/` is pure", but the module layout lists `boards.py` and `protrude.py` above `sources/` and both need the kernel. The sentence's own justification names only `Match` and `Seat`, which Ruling 5 keeps true. Task 23 corrects the sentence to say what it means; **do not** move `boards.py` or `protrude.py` to make the looser reading true.

---

### Task 11: The `stompcollider` package and its pure model

**Files:**
- Create: `packages/stompcollider/pyproject.toml`, `src/stompcollider/__init__.py`, `src/stompcollider/py.typed`, `src/stompcollider/errors.py`, `src/stompcollider/model.py`
- Create: `packages/stompcollider/tests/__init__.py`, `tests/test_model.py`, `tests/test_package_boundary.py`
- Modify: root `pyproject.toml` (workspace members)

**Interfaces:**
- Consumes: `stompmodel.errors.StompError`, `stompmodel.units.Nanometre`, `check_nanometres`, `stompmodel.diagnostics.Diagnostic`, `stompmodel.model.CaseRegistration`, `stompmodel.frames.CoordinateFrame`
- Produces, on `stompcollider.model`, every one a frozen slotted dataclass validated at construction:
  - `Profile(steps: tuple[tuple[Nanometre, Nanometre, Nanometre], ...])` — `(radius_nm, depth_from_tip_min_nm, depth_from_tip_max_nm)` per cylinder in the stack. `Profile.radius_at(depth_nm) -> Nanometre` is the greatest radius of any step covering that depth; `Profile.insertion_through(radius_nm) -> Nanometre | None` is the least depth at which the profile exceeds `radius_nm`, or `None` if it never does.
  - `Protrusion(designator: str, axis_xy_nm: tuple[Nanometre, Nanometre], profile: Profile)`
  - `Component(designator: str, protrusion: Protrusion | None)`
  - `Board(ordinal: int, designators: tuple[str, ...], extent_nm: tuple[Nanometre, Nanometre, Nanometre], carrier: CoordinateFrame, components: tuple[Component, ...])`
  - `Correspondence(designator: str, hole_index: int, hole_xy_nm: tuple[Nanometre, Nanometre], insertion_nm: Nanometre, offset_nm: Nanometre)`
  - `Clash(with_: str, kind: str, bbox_nm: tuple[Nanometre, ...], depth_nm: Nanometre, axis: str, volume_nm3: int)`
  - `Placement(rank: int, x_nm, y_nm, z_nm, theta_deg: float, correspondence: tuple[Correspondence, ...], clashes: tuple[Clash, ...])`
  - `DockData(case: CaseRegistration, boards: tuple[Board, ...], placements: dict[int, tuple[Placement, ...]], unmatched_holes: tuple[int, ...], diagnostics: tuple[Diagnostic, ...], processing: tuple[StageRun, ...])` with `with_processing`, satisfying `stompmodel.protocols.Processable` and `Diagnosable`.
- `stompcollider.errors.StompcolliderError(StompError)`, and `UsageError` beneath it.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompcollider/tests/test_model.py`:

```python
"""The pure values, and the two rules that are arithmetic rather than shape."""

from __future__ import annotations

import pytest

from stompcollider.model import Profile
from stompmodel.units import Nanometre


def _profile(*steps: tuple[int, int, int]) -> Profile:
    return Profile(tuple(
        (Nanometre(r), Nanometre(lo), Nanometre(hi)) for r, lo, hi in steps
    ))


#: A 5 mm LED: 4.9 to the flange at 3 mm, then 5.8 beyond it.
_LED = _profile((2_450_000, 0, 3_000_000), (2_900_000, 3_000_000, 8_000_000))


def test_radius_at_takes_the_greatest_step_covering_that_depth() -> None:
    """Greatest, not last and not first: steps may overlap in depth."""
    assert _LED.radius_at(Nanometre(1_000_000)) == Nanometre(2_450_000)
    assert _LED.radius_at(Nanometre(5_000_000)) == Nanometre(2_900_000)


def test_insertion_is_the_least_depth_at_which_the_profile_exceeds_the_hole() -> None:
    """The LED's flange is the feature that must NOT pass: a 5 mm hole seats
    on it at 3 mm, while a 6 mm hole admits the whole part."""
    assert _LED.insertion_through(Nanometre(2_500_000)) == Nanometre(3_000_000)
    assert _LED.insertion_through(Nanometre(3_000_000)) is None


def test_a_largest_radius_rule_would_name_the_flange() -> None:
    """The clause that distinguishes this from the rule the spec rejects: the
    greatest radius in the stack is 5.8, which no 5 mm hole admits at all."""
    assert max(step[0] for step in _LED.steps) == Nanometre(2_900_000)
    assert _LED.insertion_through(Nanometre(2_500_000)) is not None


def test_insertion_never_increases_as_the_hole_narrows() -> None:
    """A property the spec names. Monotone by construction, so a regression
    here means radius_at stopped taking the greatest step."""
    depths = [
        _LED.insertion_through(Nanometre(radius))
        for radius in range(2_400_000, 3_000_000, 50_000)
    ]
    finite = [d for d in depths if d is not None]
    assert finite == sorted(finite)


def test_a_profile_with_no_steps_is_refused() -> None:
    """A component with no admissible cylinder has no profile; it must not be
    representable as an empty one that silently inserts to zero depth."""
    with pytest.raises(ValueError, match="at least one step"):
        Profile(())
```

Create `packages/stompcollider/tests/test_package_boundary.py`, modelled on `packages/stompgeom/tests/test_package_boundary.py`: assert that no module under `src/stompcollider/` imports `stompdrill`, and — the guilty probe — that the gate fails when handed a synthetic module that does.

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q`
Expected: FAIL — the package does not exist yet. Create `pyproject.toml` modelled on `packages/stompgeom/pyproject.toml`, declaring `stompmodel` and `stompgeom` as dependencies, then add `packages/stompcollider` to the root workspace members and run `uv sync --all-packages`.

- [ ] **Step 3: Implement `model.py`**

Every class is `@dataclass(frozen=True, slots=True)` with a `__post_init__` running `check_nanometres` over its length fields, following `stompmodel/model.py`'s existing shape exactly. The two behaviours with logic:

```python
    def radius_at(self, depth_nm: Nanometre) -> Nanometre:
        """The greatest radius of any step covering ``depth_nm``.

        Greatest rather than last: a stack's steps may overlap in depth, and
        the widest feature at a depth is what a hole must admit there.
        """
        covering = [
            radius for radius, low, high in self.steps if low <= depth_nm <= high
        ]
        return Nanometre(max(covering)) if covering else Nanometre(0)

    def insertion_through(self, radius_nm: Nanometre) -> Nanometre | None:
        """The least depth at which this profile exceeds ``radius_nm``.

        ``None`` when it never does: the part passes fully. Evaluated on the
        step boundaries alone, because the profile is piecewise constant.
        """
        beyond = sorted(
            low for radius, low, _high in self.steps if radius > radius_nm
        )
        return Nanometre(beyond[0]) if beyond else None
```

- [ ] **Step 4: Run, then commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
ruff check packages tools
git add packages/stompcollider pyproject.toml uv.lock
git commit -m "Create stompcollider and its kernel-free model"
```

---

### Task 12: `designators.py` — the panel-reference filter

`stompcollider-technical.md:158-188`. A comma-separated list of terms **evaluated left to right over the set of designators present, so that a later term overrides an earlier one.**

**Files:**
- Create: `packages/stompcollider/src/stompcollider/designators.py`
- Create: `packages/stompcollider/tests/test_designators.py`

**Interfaces:**
- Produces: `parse_filter(expression: str) -> Filter`, raising `UsageError` on a malformed expression (the CLI resolves it before opening any file); `Filter.admit(designators: Iterable[str]) -> frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

```python
"""The panel-reference filter: grammar, override order, and its refusals."""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from stompcollider.designators import parse_filter
from stompcollider.errors import UsageError

_PRESENT = ("D1", "D2", "D3", "D4", "RV1", "RV2", "SW1", "SW10", "C1")


def _admit(expression: str) -> set[str]:
    return set(parse_filter(expression).admit(_PRESENT))


def test_a_literal_admits_exactly_itself() -> None:
    assert _admit("D3") == {"D3"}


def test_a_glob_star_admits_a_run() -> None:
    assert _admit("RV*") == {"RV1", "RV2"}


def test_a_glob_question_matches_one_character_not_many() -> None:
    """Both clauses: SW1 is admitted and SW10 is not."""
    assert _admit("SW?") == {"SW1"}


def test_a_range_admits_its_endpoints_inclusively() -> None:
    assert _admit("D(2..4)") == {"D2", "D3", "D4"}


def test_a_later_term_overrides_an_earlier_one() -> None:
    """Left-to-right, not set arithmetic: the negation must remove what the
    glob added, and the order of the two terms must matter."""
    assert _admit("RV*,!RV1") == {"RV2"}
    assert _admit("!RV1,RV*") == {"RV1", "RV2"}


def test_a_negation_alone_admits_nothing() -> None:
    """No implicit 'everything' to subtract from; the spec gives no default."""
    assert _admit("!RV1") == set()


def test_a_malformed_expression_is_a_usage_error() -> None:
    for expression in ("D(", "D(4..2)", "", ",", "D(a..b)"):
        with pytest.raises(UsageError):
            parse_filter(expression)


@given(st.lists(st.sampled_from(_PRESENT), min_size=1, max_size=4))
def test_parse_and_apply_is_idempotent(chosen: list[str]) -> None:
    """The property the spec names: applying an expression to its own result
    admits the same set."""
    expression = ",".join(chosen)
    once = parse_filter(expression).admit(_PRESENT)
    assert parse_filter(expression).admit(once) == once
```

- [ ] **Step 2: Run to verify they fail, implement, re-run**

Implement `parse_filter` as a left-to-right fold: each term produces a predicate and a polarity, and `admit` walks the terms in order, adding or removing from a running set that starts **empty**. Compile globs with `fnmatch.translate` and ranges by splitting on `..`; refuse a descending range, a non-integer bound, an empty term and an empty expression with `UsageError`.

- [ ] **Step 3: Commit**

```bash
git add packages/stompcollider
git commit -m "Parse and apply the panel-reference filter"
```

---

### Task 13: `canonicalise()` — the boundary

`stompcollider-technical.md:88-96`: **the boundary is `canonicalise()`, not `quantise()`.** It converts measured millimetre floats to integer nanometres by exact decimal scaling before representation rounding, per ADR-0003, and it **selects nothing** — a board's geometry has no answer set to snap to. Naming it `quantise` would assert a catalogue that does not exist.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/canonicalise.py`
- Create: `packages/stompcollider/tests/test_canonicalise.py`
- Create: `packages/stompcollider/src/stompcollider/raw.py` (`RawBoards`, `RawComponent`, `RawCylinder` — float millimetres)

**Interfaces:**
- Consumes: `stompcollider.raw.RawBoards`, `stompmodel.units.nm_from_mm`, `stompmodel.model.CaseRegistration`
- Produces: `canonicalise(raw: RawBoards, case: CaseRegistration) -> DockData`

- [ ] **Step 1: Write the failing tests**

```python
"""The canonicalisation boundary: representation only, never selection."""

from __future__ import annotations

from stompcollider.canonicalise import canonicalise
from stompmodel.units import Nanometre


def test_a_measurement_scales_exactly_not_through_binary_float() -> None:
    """ADR-0003's rule. 0.1 mm has no exact binary form; the canonical value
    must be 100000 nm and not 99999 or 100001."""
    raw = _raw_with_axis(0.1, 0.3)
    data = canonicalise(raw, _case())
    assert data.boards[0].components[0].protrusion.axis_xy_nm == (
        Nanometre(100_000), Nanometre(300_000),
    )


def test_canonicalise_selects_nothing() -> None:
    """The distinction from quantise(): an odd measurement stays odd. If this
    starts passing with a snapped value, a catalogue has crept in."""
    raw = _raw_with_axis(3.141593, 2.718282)
    data = canonicalise(raw, _case())
    assert data.boards[0].components[0].protrusion.axis_xy_nm == (
        Nanometre(3_141_593), Nanometre(2_718_282),
    )


def test_boards_are_ordinalled_by_geometry_not_by_input_order() -> None:
    """ADR-0006. Two raw inputs listing the same boards in opposite orders
    must produce the same ordinals."""
    forward = canonicalise(_two_boards(swapped=False), _case())
    backward = canonicalise(_two_boards(swapped=True), _case())
    assert [b.ordinal for b in forward.boards] == [b.ordinal for b in backward.boards]
    assert [b.designators for b in forward.boards] == [b.designators for b in backward.boards]
```

Write `_raw_with_axis`, `_case` and `_two_boards` as module-level helpers building `RawBoards` by hand. **Number the boards out of tuple order** in `_two_boards`, per the repository's fixture rule, so a test cannot pass by reading list position.

- [ ] **Step 2: Implement**

Ordinals sort on `(min x_nm, min y_nm, min z_nm, −footprint area)` in the case's face frame, per `stompcollider-technical.md:142-150`. Every traversal is over an explicitly sorted sequence.

- [ ] **Step 3: Commit**

```bash
git add packages/stompcollider
git commit -m "Convert measured boards to canonical nanometres, selecting nothing"
```

---

### Task 14: `match.py` — pairing, face selection, and candidates

`stompcollider-technical.md:228-273`. A pure stage over `DockData`, tested with hand-built values and no fixture.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/match.py`
- Create: `packages/stompcollider/tests/test_match.py`

**Interfaces:**
- Consumes: `DockData`, `Board`, `Correspondence`, `stompmodel.protocols.Stage`
- Produces: `Match(tolerance_nm: Nanometre)` satisfying `Stage[DockData]`, with `describe() -> str`. Adds `Placement` entries carrying `correspondence` and the transform's `x_nm`, `y_nm`, `theta_deg`; `z_nm` stays `0` until `Seat`.

**Four rules an implementer must not soften:**

1. **Pairing is a predicate, not a score.** The face with *strictly* more pairings points at the panel. Equal non-zero counts on both faces is `both-faced-group`, ERROR. Zero on both is `no-correspondence`, ERROR. Neither is broken by a majority or a fallback.
2. **Recognition is more permissive than fit.** Whether a shaft physically passes is `Seat`'s question; a 3PDT bush measures 12.000 mm into a 12.000 mm hole, so asking it here makes the test unsatisfiable.
3. **A candidate is identified by the set of correspondences it validates.** Two seed pairs validating the same set are the same candidate. The deduplication is exact and discrete — **no rounding of x, y or θ**, and therefore no angular resolution to choose.
4. **The reported transform for a distinct candidate is computed from its two most widely separated corresponded protrusions**, ties broken by designator order — the best-conditioned choice available, and order-free.

- [ ] **Step 1: Write the failing tests**

```python
"""Match: which face points at the panel, and which placements survive."""

from __future__ import annotations

import math

from stompcollider.match import Match
from stompcollider.model import Correspondence
from stompmodel.units import Nanometre

_TOLERANCE = Nanometre(1_270_000)      # half a 2.54 mm grid pitch


def test_the_face_with_strictly_more_pairings_is_chosen() -> None:
    data = Match(_TOLERANCE).apply(_board_pairing(front=3, back=1))
    assert data.boards[0].panel_face == "-w"


def test_equal_non_zero_pairings_on_both_faces_is_an_error() -> None:
    """Not broken by a majority, a fallback, or a preference for the front."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=2, back=2))
    assert [d.code for d in data.diagnostics] == ["both-faced-group"]


def test_zero_pairings_on_both_faces_is_a_different_error() -> None:
    """Distinct code: a wrong board and an undeclared side are different faults."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=0, back=0))
    assert [d.code for d in data.diagnostics] == ["no-correspondence"]


def test_two_protrusions_within_tolerance_of_one_hole_is_ambiguous() -> None:
    """Two parts cannot occupy one hole, and choosing between them would be
    the weighting the pre-spec refuses."""
    data = Match(_TOLERANCE).apply(_two_parts_one_hole())
    assert [d.code for d in data.diagnostics] == ["ambiguous-pairing"]


def test_a_pair_whose_separations_disagree_seeds_no_candidate() -> None:
    """|p1p2| must equal |h1h2| within TWICE the tolerance -- two independent
    recognition errors, not one."""
    assert _candidates(part_gap_mm=20.0, hole_gap_mm=20.0 + 3.0) == 0
    assert _candidates(part_gap_mm=20.0, hole_gap_mm=20.0 + 2.4) == 1


def test_a_transform_fitting_only_under_reflection_is_rejected() -> None:
    """A board cannot be mirrored in its own plane."""
    assert _candidates_from(_mirrored_layout()) == 0


def test_two_seed_pairs_validating_one_set_are_one_candidate() -> None:
    """The deduplication is on the SET, exactly and discretely. Three
    corresponded parts give three seed pairs and must give one placement."""
    data = Match(_TOLERANCE).apply(_three_collinear_parts())
    assert len(data.placements[1]) == 1


def test_a_symmetric_pattern_returns_both_placements() -> None:
    """Every distinct placement is returned. Handing back one silently is how
    a pedal gets assembled mirror-imaged."""
    data = Match(_TOLERANCE).apply(_two_fold_symmetric_board())
    assert len(data.placements[1]) == 2
    assert {round(p.theta_deg, 6) for p in data.placements[1]} == {0.0, 180.0}


def test_fewer_than_two_correspondences_is_under_constrained() -> None:
    """One leaves the board free to turn about that point. Two is the rank of
    a rigid planar transform, not a threshold."""
    data = Match(_TOLERANCE).apply(_board_pairing(front=1, back=0))
    assert "under-constrained-board" in {d.code for d in data.diagnostics}
```

Write each `_…` helper as a module-level builder of hand-built `DockData`. **Store correspondences unsorted and number boards out of tuple order**, per the repository's fixture rule.

- [ ] **Step 2: Implement**

The rigid planar transform from two correspondences, which is the one piece of real arithmetic:

```python
def _transform(
    first: tuple[Correspondence, tuple[Nanometre, Nanometre]],
    second: tuple[Correspondence, tuple[Nanometre, Nanometre]],
) -> tuple[float, float, float] | None:
    """``(x_mm, y_mm, theta_rad)`` taking both parts onto both holes.

    ``None`` when the fit needs a reflection, which a rigid board in its own
    plane cannot supply. Closed form: the angle between the two separation
    vectors, then the translation that lands the first part.
    """
    (part_a, hole_a), (part_b, hole_b) = first, second
    px, py = _mm(part_b[0] - part_a[0]), _mm(part_b[1] - part_a[1])
    hx, hy = _mm(hole_b[0] - hole_a[0]), _mm(hole_b[1] - hole_a[1])
    if math.hypot(px, py) == 0.0:
        return None
    theta = math.atan2(hy, hx) - math.atan2(py, px)
    cos, sin = math.cos(theta), math.sin(theta)
    ax, ay = _mm(part_a[0]), _mm(part_a[1])
    x = _mm(hole_a[0]) - (cos * ax - sin * ay)
    y = _mm(hole_a[1]) - (sin * ax + cos * ay)
    return (x, y, theta)
```

Reflection is rejected by construction here — a rotation is solved for, never a general affine fit — so the test above passes only if the *validation* step then rejects the mirrored layout by finding the other correspondences out of tolerance. **Write the validation before assuming that**; if a mirrored layout validates, add the explicit determinant check and say so in the commit.

Candidate identity is `frozenset` of `(designator, hole_index)`. Deduplicate on that set alone.

- [ ] **Step 3: Run, then commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
git add packages/stompcollider
git commit -m "Pair protrusions with holes and enumerate the placements they imply"
```

---

### Task 15: `seat.py` — seating depth and ranking

`stompcollider-technical.md:291-368`. Pure, closed-form, **no kernel query and no descent**.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/seat.py`
- Create: `packages/stompcollider/tests/test_seat.py`

**Interfaces:**
- Consumes: `DockData`, `Profile.insertion_through`, `stompmodel.protocols.Stage`
- Produces: `Seat()` satisfying `Stage[DockData]`. Fills each `Placement.z_nm` and assigns `rank`.

**Two rules:**

1. **Seating depth is fixed by the panel-reference correspondences alone.** Anything else that would foul at that depth is a clash to report, not a constraint to yield to. A standoff is not a seating constraint; it is a solid that clashes.
2. **Ranking is lexicographically ascending on `(clash count, total clash volume, greatest clash depth, θ, x_nm, y_nm)`.** Rank is a reported field, not a verdict: **every** distinct placement is returned.

At this task's point in the plan no clash has been computed, so the first three key elements are zero for every placement and the ranking falls through to `(θ, x_nm, y_nm)`. Task 19 re-ranks once clashes exist. **Write the comparator to take the whole six-tuple now** — a comparator that only sorts three fields is a comparator Task 19 has to replace rather than feed.

- [ ] **Step 1: Write the failing tests**

```python
"""Seat: how deep a board goes, and in what order placements are reported."""

from __future__ import annotations

from stompcollider.seat import Seat, rank_key
from stompmodel.units import Nanometre


def test_travel_is_the_least_insertion_over_the_correspondences() -> None:
    """The shallowest part is what stops the board, not the average or the
    deepest -- so a fixture with a distinct minimum proves the reduction."""
    data = Seat().apply(_placement_with_insertions([9_000_000, 3_000_000, 7_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-3_000_000)


def test_a_part_that_passes_fully_does_not_constrain_seating() -> None:
    """insertion_through returns None for a part the hole admits entirely; a
    None treated as zero would seat the board on nothing."""
    data = Seat().apply(_placement_with_insertions([None, 4_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-4_000_000)


def test_a_standoff_does_not_raise_the_board() -> None:
    """Rule 1 stated as a test: a non-panel-reference solid that would foul is
    a clash to report, never a seating constraint."""
    data = Seat().apply(_placement_with_a_tall_non_reference_part())
    assert data.placements[1][0].z_nm == Nanometre(-3_000_000)


def test_ranking_is_a_total_order_over_the_whole_key() -> None:
    """Property the spec names. Equal on the first five elements must still
    order, which is what x_nm and y_nm are in the key for."""
    keys = [rank_key(p) for p in _placements_differing_only_in_x()]
    assert len(set(keys)) == len(keys)
    assert keys == sorted(keys)


def test_clean_placements_sort_before_clashing_ones() -> None:
    ranked = sorted(_one_clean_one_clashing(), key=rank_key)
    assert ranked[0].clashes == ()


def test_ties_fall_through_to_the_transform_not_to_a_measured_quantity() -> None:
    """A genuinely symmetric pair must order on theta, which is exact, so the
    order never depends on kernel round-off."""
    ranked = sorted(_symmetric_pair(), key=rank_key)
    assert [round(p.theta_deg, 6) for p in ranked] == [0.0, 180.0]


def test_every_distinct_placement_survives_ranking() -> None:
    """Rank is a reported field, not a filter."""
    data = Seat().apply(_two_placements())
    assert len(data.placements[1]) == 2
    assert sorted(p.rank for p in data.placements[1]) == [1, 2]
```

- [ ] **Step 2: Implement**

```python
def rank_key(placement: Placement) -> tuple[int, int, int, float, int, int]:
    """The spec's lexicographic key, whole, from the first version.

    Written six-wide before clashes exist so that Task 19 supplies data to a
    comparator rather than replacing one.
    """
    return (
        len(placement.clashes),
        sum(clash.volume_nm3 for clash in placement.clashes),
        max((int(clash.depth_nm) for clash in placement.clashes), default=0),
        placement.theta_deg,
        int(placement.x_nm),
        int(placement.y_nm),
    )
```

Travel is `min` over the correspondences of `profile.insertion_through(hole_radius_nm)`, skipping `None`. A placement whose every correspondence returns `None` seats at the panel surface: `z_nm = 0`.

- [ ] **Step 3: Run, then commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q && uv run --no-sync mypy && cd ../..
git add packages/stompcollider
git commit -m "Seat each placement and rank every one that survives"
```

---

# Phase 2 — the kernel side

Kernel-backed tests are **opt-in behind `--boards`**, mirroring `--hammond`, and run against `fixtures/tar-pcb.stp`. Add the flag to `packages/stompcollider/tests/conftest.py` in Task 16, modelled on `stompdrill`'s `--hammond`. Coverage for `sources/` and `emitters/assembly.py` is measured under that command, not the default one.

---

### Task 16: `boards.py` — substrate identification, grouping, ordinals

**The direct consumer of Ruling 1**, and the first thing plan 3 could not write before the docket was settled. Read `docs/specs/foundation-docket-rulings.md` Ruling 1 in full before starting.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/boards.py`
- Create: `packages/stompcollider/tests/conftest.py` (the `--boards` flag)
- Create: `packages/stompcollider/tests/test_boards.py`
- Move: `fixtures/tar-pcb.stp` → `packages/stompcollider/tests/fixtures/tar-pcb.stp` (`stompcollider-technical.md:605-609`: "the root is where a fixture with no member waits, not where one lives")
- Modify: Task 7's two fixture probes in `packages/stompgeom/tests/test_levels.py` — their path changes with the move

**Interfaces:**
- Consumes: `stompgeom.levels.levels`, `stompgeom.step.StepDocument`, `bounding_box_mm`
- Produces:
  - `substrates(document) -> tuple[StepSolid, ...]` — the unnamed solids, each verified to be a slab.
  - `carrier_frame(solid) -> CoordinateFrame` — built from the slab's two carrier levels.
  - `group(document, substrates) -> tuple[tuple[StepSolid, tuple[StepSolid, ...]], ...]` — each substrate with the components contacting it.
  - `ordinals(...)` — boards numbered per `stompcollider-technical.md:142-150`.

**Ruling 1 in one sentence:** an unnamed solid is a substrate **candidate**; a candidate is a board only if its two largest levels are **exactly opposed** (component-wise negation of one direction key by the other), of comparable area, and their offsets sum to a thickness small against the carrier's own extent. **Holedness plays no part.** The two proportions are this task's to calibrate — from a measured gap across the fixture's two substrates and any Hammond solid used as a negative, stated with what lies on each side, with both probes. **Do not** copy a ratio from anywhere; the ruling deliberately declines to supply one.

- [ ] **Step 1: Write the failing tests**

```python
"""Finding the boards in an assembly, and proving each one is a board."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcollider.boards import carrier_frame, group, ordinals, substrates
from stompgeom.step import read_step

_FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"


@pytest.fixture(scope="module")
def document():
    return read_step(_FIXTURE)


@pytest.mark.boards
def test_the_fixture_holds_two_substrates(document) -> None:
    """41 named solids carry reference designators; 2 are unnamed. Both
    unnamed solids are real boards, not one board in two pieces -- they are
    disjoint in y by 4.25 mm at the same z."""
    assert len(substrates(document)) == 2


@pytest.mark.boards
def test_each_substrate_measures_a_slab(document) -> None:
    """Ruling 1's verification, on real geometry: opposed, equal-area, thin."""
    for solid in substrates(document):
        frame = carrier_frame(solid)
        assert frame is not None


@pytest.mark.boards
def test_a_component_is_not_a_substrate(document) -> None:
    """The slab test's GUILTY probe on real geometry: a switch body is a
    named solid, but feeding it to the verification directly must refuse it."""
    from stompcollider.boards import is_slab

    switch = next(s for s in document.solids if s.name == "SW1")
    assert is_slab(switch) is False


@pytest.mark.boards
def test_a_real_board_passes_the_same_test(document) -> None:
    """The INNOCENT probe beside it. Without this pair the threshold could
    reject everything and the test above would still be green."""
    from stompcollider.boards import is_slab

    assert all(is_slab(solid) for solid in substrates(document))


@pytest.mark.boards
def test_the_carrier_normal_is_the_levels_own_direction(document) -> None:
    """Not searched for and not swept: it falls out of the partition's key."""
    for solid in substrates(document):
        assert tuple(round(c) for c in carrier_frame(solid).w) in {(0, 0, 1), (0, 0, -1)}


@pytest.mark.boards
def test_every_named_solid_is_grouped_onto_exactly_one_board(document) -> None:
    """41 designators across two boards, none dropped and none doubled."""
    grouped = group(document, substrates(document))
    assigned = [c.name for _substrate, components in grouped for c in components]
    assert len(assigned) == len(set(assigned)) == 41


def test_ordinals_do_not_depend_on_input_order() -> None:
    """ADR-0006, on hand-built inputs so it runs without --boards."""
    forward = ordinals(_two_hand_built_boards())
    backward = ordinals(list(reversed(_two_hand_built_boards())))
    assert [b.ordinal for b in forward] == [b.ordinal for b in backward]


def test_a_document_with_no_unnamed_solid_is_refused() -> None:
    """`no-substrate` stays live under Ruling 1: an exporter that names
    everything gets a refusal rather than a guess."""
    from stompcollider.errors import StompcolliderError

    with pytest.raises(StompcolliderError, match="no-substrate"):
        substrates(_all_solids_named())
```

Register the marker in `conftest.py` and make `--boards` the flag that enables it, exactly as `stompdrill`'s `conftest.py` does for `--hammond`. **Kernel-backed tests do not skip on a missing kernel** — it is an unconditional dependency, so failing to import it is a failure rather than a silent pass.

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q`

- [ ] **Step 3: Implement, calibrating the two proportions**

Before writing `is_slab`'s constants, measure. Harvest `levels()` over every solid in the fixture and over a Hammond box, and record for each: the ratio of the two largest levels' areas, and the thickness-to-extent ratio. Take each constant from the gap between what must pass and what must fail, and write the measurement into the constant's docstring the way `_HOLED_FRACTION_LIMIT` and `stompgeom.levels._DIRECTION_SCALE` do. **A constant with no stated gap is a tuned value and will not survive review.**

- [ ] **Step 4: Move the fixture and fix Task 7's paths**

```bash
git mv fixtures/tar-pcb.stp packages/stompcollider/tests/fixtures/tar-pcb.stp
```
Then update the two granularity probes in `packages/stompgeom/tests/test_levels.py`. They are a **control pair** and must keep running; if the path cannot be reached across packages, copy the two measurements into `stompgeom`'s own built fixture rather than deleting the probes.

- [ ] **Step 5: Run everything, then commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && uv run --no-sync mypy && cd ../..
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && cd ../..
git add packages/stompcollider packages/stompgeom
git commit -m "Identify a board by name and verify it by slab-ness"
```

---

### Task 17: `protrude.py` — the cylinder stack and its profile

`stompcollider-technical.md:190-226`, and Ruling 7's cylinder enumerator, which is written here rather than earlier so it is designed against the consumer that needs its missing half.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/cylinders.py` and `packages/stompgeom/tests/test_cylinders.py`
- Create: `packages/stompcollider/src/stompcollider/protrude.py` and `packages/stompcollider/tests/test_protrude.py`
- Modify: `packages/stompdrill/tests/hammond.py:179` (collapse onto the published version)

**Interfaces:**
- Produces, on `stompgeom.cylinders`:
  - `Cylinder` — frozen, slotted: `axis_location_mm: tuple[float, float, float]`, `axis_direction: Direction`, `radius_mm: float`, `extent_mm: tuple[float, float]` (along the axis).
  - `cylindrical_faces(shape) -> tuple[Cylinder, ...]`
- Produces, on `stompcollider.protrude`: `protrusion_of(solid, carrier_normal) -> Protrusion | None`

**The existing test helper returns axis location and radius but neither direction nor axial extent**, which is exactly what a profile needs — hence Ruling 7's instruction that a promoted version must return both.

**Three rules:**

1. **Only cylinders whose axis is parallel to the carrier normal are admitted.** A cylinder at another angle cannot pass through a hole in a flat panel, so admitting one risks an axis that means nothing. This is correctness, not optimisation — on the fixture it takes a footswitch from 534 faces to 124.
2. **Parallelism is `gp_Dir.IsParallel` at `Precision::Angular()`; coaxiality is `Precision::Confusion()` on the axis position.** The kernel's own declarations, not tolerances chosen here.
3. **The admitted cylinder reaching furthest along the outward direction fixes the axis; every cylinder coaxial with it forms the stack.** A profile is radius-versus-depth, never a diameter.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.boards
def test_an_ordinary_diode_reduces_to_two_admitted_faces(document) -> None:
    """Rule 1's measured consequence; the numbers are the spec's own."""
    diode = next(s for s in document.solids if s.name == "D2")
    admitted = admissible(diode, carrier_normal=(0.0, 0.0, 1.0))
    assert len(admitted) == 2


@pytest.mark.boards
def test_a_footswitch_reduces_from_534_faces_to_124(document) -> None:
    switch = next(s for s in document.solids if s.name == "SW1")
    assert len(cylindrical_faces(switch.shape)) == 534
    assert len(admissible(switch, carrier_normal=(0.0, 0.0, 1.0))) == 124


@pytest.mark.boards
def test_the_footswitch_profile_admits_a_twelve_millimetre_hole_fully(document) -> None:
    """The spec's validation table, as a test: 10 tip, 8 shaft, 12 bush;
    a 12 mm hole passes it to full depth."""
    switch = next(s for s in document.solids if s.name == "SW1")
    profile = protrusion_of(switch, (0.0, 0.0, 1.0)).profile
    assert profile.insertion_through(Nanometre(6_000_000)) is None


@pytest.mark.boards
def test_a_five_millimetre_led_seats_on_its_flange(document) -> None:
    """The case a largest-radius rule gets wrong: the flange is precisely the
    feature that must not pass through."""
    led = next(s for s in document.solids if s.name.startswith("D3"))
    profile = protrusion_of(led, (0.0, 0.0, 1.0)).profile
    assert profile.insertion_through(Nanometre(2_500_000)) is not None
    assert profile.insertion_through(Nanometre(3_000_000)) is None


def test_a_component_with_no_admissible_cylinder_has_no_axis() -> None:
    """Reported as unmatched-part, the same finding as an axis that pairs with
    no hole -- not as a crash and not as a zero-radius profile."""
    assert protrusion_of(_a_plain_cuboid_solid(), (0.0, 0.0, 1.0)) is None


def test_a_cylinder_at_an_angle_is_not_admitted() -> None:
    """Rule 1's guilty probe on synthetic geometry, so it runs without --boards."""
    assert admissible(_tilted_cylinder_solid(), (0.0, 0.0, 1.0)) == ()


def test_an_axial_cylinder_is_admitted() -> None:
    """The innocent probe beside it."""
    assert len(admissible(_axial_cylinder_solid(), (0.0, 0.0, 1.0))) == 1
```

The three face counts above (534, 124, 2) are properties of a committed fixture and are the spec's own figures; assert them rather than trusting the prose. If a count disagrees, **stop and report it** — the spec is either wrong or the admission rule is, and guessing which would put a wrong number into the code.

- [ ] **Step 2: Implement, run, and collapse the test helper**

Replace `packages/stompdrill/tests/hammond.py:179`'s local walk with `stompgeom.cylinders.cylindrical_faces`, keeping `stompdrill`'s suite green.

- [ ] **Step 3: Commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && cd ../..
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
git add packages/stompgeom packages/stompcollider packages/stompdrill
git commit -m "Publish the cylinder enumerator and build a protrusion's profile"
```

---

### Task 18: `sources/step.py` — `BoardSource`

**Files:**
- Create: `packages/stompcollider/src/stompcollider/sources/__init__.py`, `sources/step.py`
- Create: `packages/stompcollider/tests/test_source.py`

**Interfaces:**
- Consumes: `stompgeom.step.read_step`, `stompcollider.boards`, `stompcollider.protrude`, `stompmodel.model.DrillData` (read through `stompmodel`'s codec)
- Produces: `BoardSource(drill: Path, boards: Sequence[Path], case_model: Path).read() -> RawBoards`

**Three required behaviours:**

1. **`wrong-case-model`** compares the footprint the drill document's `enclosure` records (`length_nm`, `width_nm`) with the footprint measured from the supplied case model via `stompgeom.step.assembly_spans` — **both pairs reduced to descending order before an exact nanometre comparison**. Product names never enter it. A drill document that identified no enclosure carries none to check, and the comparison is **skipped rather than guessed at**.
2. **`unreadable-board`** for a file that is not readable STEP, or holds no solids.
3. **`multiple-boards`** is a WARNING, not INFO, on purpose: a caller expecting one board must learn it passed two, and exit 0 would not tell them.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_case_model_of_the_wrong_footprint_is_refused() -> None:
    """Descending-order comparison, so a 112x60 enclosure and a 60x112 model
    are the same footprint and a 112x50 model is not."""
    assert _codes(_read_with(enclosure=(112_400_000, 60_500_000),
                            model_spans=(60.50, 112.40, 31.00))) == []
    assert _codes(_read_with(enclosure=(112_400_000, 60_500_000),
                             model_spans=(112.40, 50.00, 31.00))) == ["wrong-case-model"]


def test_a_drill_document_naming_no_enclosure_skips_the_check() -> None:
    """Skipped, not guessed at: no footprint to compare is not a mismatch."""
    assert _codes(_read_with(enclosure=None, model_spans=(1.0, 2.0, 3.0))) == []


def test_two_boards_in_one_file_is_a_warning_not_an_info() -> None:
    from stompmodel.diagnostics import Severity

    found = [d for d in _read_two_boards().diagnostics if d.code == "multiple-boards"]
    assert [d.severity for d in found] == [Severity.WARNING]


def test_a_file_with_no_solids_is_unreadable_board() -> None:
    assert _codes(_read_with_empty_file()) == ["unreadable-board"]


@pytest.mark.boards
def test_the_fixture_reads_end_to_end() -> None:
    raw = BoardSource(_DRILL, [_FIXTURE], _CASE).read()
    assert len(raw.boards) == 2
```

- [ ] **Step 2: Implement, run, commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && uv run --no-sync mypy && cd ../..
git add packages/stompcollider
git commit -m "Read boards, the case model and the drill document into RawBoards"
```

---

# Phase 3 — clash, outputs, and the command line

---

### Task 19: `clash.py` — the impure stage

**Ruling 5.** `stompdrill` performs no boolean, so `BRepAlgoAPI_Common` has exactly one consumer and ADR-0008 says leave it here rather than promote it. The stage sits **between `Seat` and the emitters**, taking placements in and clash records out, which is what keeps `stompcollider-technical.md:115-117`'s purity claim true as written.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/clash.py`
- Create: `packages/stompcollider/tests/test_clash.py`

**Interfaces:**
- Consumes: `stompgeom.shapes.placed`, `stompgeom.step.bounding_box_mm`, `DockData`
- Produces: `Clashes(case_solids, board_solids)` satisfying `Stage[DockData]`. Fills `Placement.clashes` and re-ranks through `seat.rank_key`, which Task 15 already wrote six-wide for this.

**Four rules:**

1. **Each board is checked against the whole of the rest of the assembly** — every case solid and every other board. No part is privileged or exempt. The rule is stated this way deliberately: an enumerated list of things worth checking would eventually omit one, and the omission would look like a passing result.
2. **Bounding boxes filter pairs; a surviving pair gets an exact `BRepAlgoAPI_Common`.** A clash is that common region's axis-aligned bounding box **in the case's face frame**, its depth the least extent and its axis that axis.
3. **Contact is not a clash and needs no threshold.** A 12.000 mm bush in a 12.000 mm hole yields extents at the kernel's modelling tolerance, which round to **0 nm** under ADR-0003. Zero-nanometre depth is contact. Anything the canonical representation cannot express is not a fact, so the resolution is the test and no threshold is introduced.
4. **Each board is ranked against the case alone.** The assembly is then formed from each board's rank-1 placement, and inter-board clashes are computed once on that assembly. The Cartesian product of every board's candidates never appears.

- [ ] **Step 1: Write the failing tests**

```python
"""Clashes: what overlaps, by how much, and what merely touches."""

from __future__ import annotations

import pytest

from stompcollider.clash import Clashes
from stompmodel.units import Nanometre


def test_two_overlapping_boxes_report_the_overlap() -> None:
    found = _clashes_between(_box_at(0, 0, 0, 10, 10, 10), _box_at(8, 0, 0, 10, 10, 10))
    assert found[0].depth_nm == Nanometre(2_000_000)
    assert found[0].axis == "u"


def test_depth_is_the_LEAST_extent_not_the_greatest() -> None:
    """The clause a max() implementation passes the test above and fails here:
    an overlap 2 mm deep and 10 mm wide is 2 mm of interference."""
    found = _clashes_between(_box_at(0, 0, 0, 10, 10, 10), _box_at(8, 0, 0, 10, 40, 40))
    assert found[0].depth_nm == Nanometre(2_000_000)


def test_touching_faces_are_contact_not_a_clash() -> None:
    """The named test the spec requires, not an assumption: a 12.000 bush in
    a 12.000 hole rounds to zero nanometres, and zero depth is contact."""
    found = _clashes_between(_box_at(0, 0, 0, 10, 10, 10), _box_at(10, 0, 0, 10, 10, 10))
    assert found == ()


def test_a_one_nanometre_overlap_IS_a_clash() -> None:
    """The innocent probe beside it. Without this, a contact rule that
    discarded everything would still pass the test above."""
    found = _clashes_between(_box_at(0, 0, 0, 10, 10, 10), _box_at(9.999999, 0, 0, 10, 10, 10))
    assert found[0].depth_nm == Nanometre(1_000)


def test_the_lid_is_checked_like_any_other_solid() -> None:
    """No part of the enclosure is privileged or exempt; the lid is named in
    the report for emphasis, which is not a narrowing of the check."""
    found = _clashes_against_case_named("LID")
    assert found[0].with_ == "LID" and found[0].kind == "case"


def test_a_clash_with_another_board_is_kinded_board() -> None:
    """So a consumer never parses the `with` string to learn what it is."""
    found = _inter_board_clashes()
    assert found[0].kind == "board" and found[0].with_ == "board:2"


def test_clashes_sort_by_kind_then_with_then_depth() -> None:
    """Determinism: every traversal is over an explicitly sorted sequence."""
    found = _several_clashes()
    assert found == tuple(sorted(found, key=lambda c: (c.kind, c.with_, int(c.depth_nm))))


def test_a_clashing_board_is_still_reported_and_still_drawn() -> None:
    """Matching and fitting fail differently. A matched board whose every
    candidate clashes is the RIGHT board with a misaligned design: exit 1,
    every candidate reported. Withholding it would defeat the tool."""
    data = Clashes(_case(), _boards()).apply(_all_candidates_clash())
    assert data.placements[1] != ()
    assert max(d.severity for d in data.diagnostics).name == "WARNING"
```

- [ ] **Step 2: Implement, run, commit**

Use `stompgeom.shapes.placed` to move each board's solids, never a second kernel transform written here. Convert the common region's corners into the case's face frame with `CoordinateFrame.to_canonical`, which Task 5 made three-dimensional for exactly this.

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && cd ../..
git add packages/stompcollider
git commit -m "Compute clashes as a stage, leaving Seat pure"
```

---

### Task 20: `emitters/report.py`

`stompcollider-dock-report` v1 — `stompcollider-technical.md:393-440`. Integer nanometres, a `format`/`version` header, diagnostics matched by `code`.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/emitters/__init__.py`, `emitters/report.py`
- Create: `packages/stompcollider/tests/test_report.py`

**Interfaces:**
- Produces: `ReportEmitter()` satisfying `stompmodel.protocols.Emitter[DockData]`, returning `bytes`. **No registry** — two fixed outputs; `stompdrill`'s registry earns its keep across six formats, and here it would be ceremony around a two-element set.

**Four details that are easy to get wrong:**

1. **`case.face` is echoed from the drill document, never chosen here.**
2. **Angles are serialised at six decimal places** — the only float in the document and the only place byte-identity depends on formatting.
3. **`offset_nm` is a field, not a message.** It is what turns "no valid placement" into "RV3 is 0.15 mm off and will bind", which is the answer the tool exists to give when a board nearly fits.
4. **`unmatched_holes` is reported once across the assembly**, not per board — each board covers a subset by construction, so a leftover hole means panel-mounted hardware on no PCB, or a board missing from the run.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_header_names_the_format_and_version() -> None:
    document = json.loads(ReportEmitter().emit(_data()))
    assert document["format"] == "stompcollider-dock-report"
    assert document["version"] == 1
    assert document["units"] == "nm"


def test_the_case_face_is_echoed_not_chosen() -> None:
    """Given a drill document cut in the lid, the report must say lid."""
    document = json.loads(ReportEmitter().emit(_data(face="lid")))
    assert document["case"]["face"] == "lid"


def test_angles_carry_exactly_six_decimal_places() -> None:
    """The only float in the document; byte identity depends on this format."""
    payload = ReportEmitter().emit(_data(theta=180.0))
    assert b'"theta_deg": 180.000000' in payload


def test_the_recognition_miss_is_a_field() -> None:
    document = json.loads(ReportEmitter().emit(_data(offset_nm=150_000)))
    assert document["boards"][0]["placements"][0]["correspondence"][0]["offset_nm"] == 150_000


def test_unmatched_holes_are_reported_once_across_the_assembly() -> None:
    """Not per board: a hole no board covers is an assembly-level fact."""
    document = json.loads(ReportEmitter().emit(_two_boards_sharing_leftovers()))
    assert document["unmatched_holes"] == [7, 9]
    assert all("unmatched_holes" not in board for board in document["boards"])


def test_the_emitter_reads_the_ordinals_the_model_states() -> None:
    """Fixture rule: boards are numbered out of tuple order, so an emitter
    recomputing an ordinal from list position fails here."""
    document = json.loads(ReportEmitter().emit(_boards_numbered_out_of_order()))
    assert [b["ordinal"] for b in document["boards"]] == [2, 1]


def test_two_inputs_of_one_assembly_emit_identical_bytes() -> None:
    """ADR-0006 over the report: no rule may consult input order."""
    assert ReportEmitter().emit(_data()) == ReportEmitter().emit(_data(shuffled=True))
```

- [ ] **Step 2: Implement, run, commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= -q && cd ../..
git add packages/stompcollider
git commit -m "Emit the dock report"
```

---

### Task 21: `emitters/assembly.py`

The case model's solids plus each board's solids under its chosen placement, through `stompgeom`'s deterministic writer. **Collisions are left in place** — docking rules are respected, interference is not resolved away, and seeing the clash is the point.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/emitters/assembly.py`
- Create: `packages/stompcollider/tests/test_assembly.py`

**Interfaces:**
- Consumes: `stompgeom.build.PlacedSolid`, `build_document`, `stompgeom.writer.render_step`
- Produces: `AssemblyEmitter()` satisfying `Emitter[DockData]`, returning `bytes`.

**The emitter must not construct kernel documents itself** — ADR-0008:225-229 and `stompcollider-technical.md:598-602`; it calls the builder Task 9 promoted.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.boards
def test_the_assembly_holds_the_case_solids_and_the_board_solids() -> None:
    solids = _read_back(AssemblyEmitter().emit(_seated()))
    assert len(solids) == _case_solid_count() + _board_solid_count()


@pytest.mark.boards
def test_a_board_is_written_at_its_placement_not_at_its_export_position() -> None:
    """The whole point of the artefact. A builder ignoring `placement` passes
    the test above and fails this one."""
    solids = _read_back(AssemblyEmitter().emit(_seated(z_nm=-28_085_000)))
    assert round(_board_bbox(solids)[2], 3) == -28.085


@pytest.mark.boards
def test_a_clashing_placement_is_still_written() -> None:
    """Collisions are left in place; resolving them away would hide the fault
    the tool exists to show."""
    assert AssemblyEmitter().emit(_clashing()) != b""


@pytest.mark.boards
def test_two_writes_of_one_assembly_are_byte_identical() -> None:
    assert AssemblyEmitter().emit(_seated()) == AssemblyEmitter().emit(_seated())


@pytest.mark.boards
def test_names_and_colours_survive_the_placement() -> None:
    """Which is why Task 6 locates rather than rebuilds, and why Task 8 had to
    widen the census before this task could exist."""
    solids = _read_back(AssemblyEmitter().emit(_seated()))
    assert "RV1" in {s.name for s in solids}
```

- [ ] **Step 2: Implement, run, commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && cd ../..
git add packages/stompcollider
git commit -m "Emit the assembly model, collisions left in place"
```

---

### Task 22: `cli.py`

`stompcollider-technical.md:484-513`. **Every flag resolves before any file is opened**, so an unparseable filter expression, a malformed `--place`, or a `--pin` naming a board ordinal that cannot exist is exit 3 rather than a diagnostic.

**Files:**
- Create: `packages/stompcollider/src/stompcollider/cli.py`
- Create: `packages/stompcollider/tests/test_cli.py`
- Modify: `packages/stompcollider/pyproject.toml` (console script)

**Interfaces:**
- Consumes: `stompmodel.protocols.stage_payload`, `check_target_set` (Task 4), `stompmodel.diagnostics.exit_for_severity`
- Produces: `main(argv: Sequence[str] | None = None) -> int`

**Three rules:**

1. **There is no `--case-face`.** The drill document carries the face frame `stompdrill` cut in, so `stompcollider` reads the registration instead of choosing a face, and checks against every solid of the case model.
2. **Any error withholds every requested artefact**, as `stompdrill` does — and the target set is validated as a set, through Task 4's promoted `check_target_set`, before anything is rendered.
3. **Exit codes:** `0` clean, `1` findings, `2` error, `3` usage or IO, through `stompmodel`'s shared reduction.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_malformed_filter_is_usage_not_a_diagnostic(tmp_path, capsys) -> None:
    """Resolved before any file is opened: the exit code proves the ordering,
    because a nonexistent input would otherwise be reported first."""
    code = main(["nowhere.json", "nowhere.stp", "--case-model", "nowhere.stp",
                 "--panel-reference", "D(", "--match-tolerance", "1.27"])
    assert code == 3


def test_a_pin_naming_an_impossible_ordinal_is_usage(tmp_path) -> None:
    assert main([*_valid_args(tmp_path), "--pin", "0=1"]) == 3


def test_two_targets_reaching_one_file_are_refused(tmp_path) -> None:
    """Task 4's promoted set check, from its second caller."""
    target = tmp_path / "out"
    assert main([*_valid_args(tmp_path), "--report", str(target),
                 "--assembly", str(target)]) == 3


def test_an_error_withholds_every_artefact(tmp_path) -> None:
    report, assembly = tmp_path / "r.json", tmp_path / "a.stp"
    assert main([*_args_causing_no_correspondence(tmp_path),
                 "--report", str(report), "--assembly", str(assembly)]) == 2
    assert not report.exists() and not assembly.exists()


def test_warnings_exit_one_and_still_write(tmp_path) -> None:
    """Matching and fitting fail differently, and only one is an error."""
    report = tmp_path / "r.json"
    assert main([*_args_with_a_clash(tmp_path), "--report", str(report)]) == 1
    assert report.stat().st_size > 0


def test_there_is_no_case_face_flag() -> None:
    """A regression guard on a deliberate omission: the registration is read,
    never chosen. A future contributor adding the flag fails here."""
    assert main([*_valid_args_list(), "--case-face", "lid"]) == 3
```

- [ ] **Step 2: Implement, run, commit**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && uv run --no-sync mypy && cd ../..
git add packages/stompcollider
git commit -m "Drive the docking flow from a command line"
```

---

### Task 23: Cross-artefact agreement, coverage, and the documents

**Files:**
- Create: `packages/stompcollider/tests/recovery/__init__.py`, `recovery/report.py`, `recovery/assembly.py`
- Create: `packages/stompcollider/tests/test_dock_agreement.py`
- Modify: `docs/specs/stompcollider-technical.md`, `docs/adr/0009-…`, `CLAUDE.md`, `docs/BACKLOG.md`

- [ ] **Step 1: Write the agreement test**

Parse **both** emitted artefacts and compare what they say about one assembly, as `packages/stompdrill/tests/test_drawing_agreement.py` does today: the report's `x_nm`/`y_nm`/`z_nm` for each board against the board's measured position in the written STEP, and the report's designator list against the names the model carries.

Add the AST gate `stompdrill` has: nothing under `recovery/` may import `stompcollider`. **A recovery that inverts its own emitter's transform proves that emitter self-consistent and nothing more.** Ship the gate's guilty probe beside it.

- [ ] **Step 2: Meet the coverage targets**

```bash
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards --cov=stompcollider --cov-report=term-missing
```
Targets: **90% for the package, 100% for `match`, `seat` and the emitters.** Coverage for `sources/` and `emitters/assembly.py` is measured under `--boards`, not the default command.

- [ ] **Step 3: Correct the documents**

- `stompcollider-technical.md:115-117` — say what it means: `Match` and `Seat` are pure; `boards.py`, `protrude.py` and `clash.py` are kernel-backed. Add `clash.py` to the module layout and move `### Clashes` out from under `## Seat`.
- `stompcollider-technical.md` **Status** — `accepted, unimplemented` becomes implemented, naming the commit.
- `stompcollider-technical.md:556-566` — plan 3's row gains its own "Done when" evidence.
- `docs/specs/foundation-docket-rulings.md` — Status becomes executed.
- `CLAUDE.md` — the workspace is now four packages, in dependency order. Add `stompcollider`'s own test, mypy and mutmut commands to the per-member lists. **Record no counts**, only commands.
- `docs/BACKLOG.md` — close the entries Rulings 2 and 7 discharged.
- ADR-0009's dependency-order section gains `stompcollider`.

- [ ] **Step 4: Final gates**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q && cd ../..
cd packages/stompcollider && uv run --no-sync pytest -o addopts= --boards -q && cd ../..
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
ruff check packages tools && mypy packages
cd packages/stompmodel && uv run --no-sync mypy && cd ../..
cd packages/stompgeom && uv run --no-sync mypy && cd ../..
cd packages/stompcollider && uv run --no-sync mypy && cd ../..
bash tools/verify-lock.sh
```

- [ ] **Step 5: Commit**

```bash
git add packages docs CLAUDE.md
git commit -m "Prove the two artefacts agree, and correct what plan 3 changed"
```

---

## Self-Review

**Spec coverage.** Walked `stompcollider-technical.md` section by section: Inputs and outputs → Task 18; Internal architecture and module layout → Tasks 11–22; Reading boards → Task 16; the panel-reference filter → Task 12; Protrusions → Task 17; Match and Candidates → Task 14; Seat, seating depth, contact, ranking, several boards → Tasks 15 and 19; Clashes → Task 19; Emitters, the report, the assembly model → Tasks 20 and 21; Diagnostics and exit codes → Tasks 18, 19, 22; Command line → Task 22; Determinism → asserted in Tasks 13, 16, 19, 20; Testing → Tasks 16 and 23. `foundation-docket-rulings.md`'s twelve work-list rows map to Tasks 1–10 and 16–19. **One gap found and closed:** the ruling's row 10 (cylinder enumerator) had no task until Task 17 absorbed it.

**Placeholder scan.** One deliberate exception, flagged in place: Task 8's third test carries an implementer's note because the guilty probe's exact shape depends on whether the built fixture demonstrates slot permutation in-process. The note states what must not happen — deleting it and leaving the byte-identity test uncontrolled. Task 16's two slab proportions are also deliberately unset, per the ruling, with the calibration method specified.

**Type consistency.** `Level.offset_nm` is `Nanometre` throughout Tasks 7, 16 and 17. `RigidTransform` is constructed only in Task 5 and consumed in Tasks 6, 9, 19, 21. `Profile.insertion_through` returns `Nanometre | None` in Tasks 11, 15 and 17 — the `None` case is asserted in each. `rank_key` is six-wide in Task 15 and fed, not replaced, in Task 19.

**Known ordering risk.** Task 16 moves `fixtures/tar-pcb.stp`, which Task 7's granularity probes read. Task 16 Step 4 fixes them explicitly; an executor running tasks out of order will see `stompgeom`'s suite fail on a missing fixture, which is the intended loud failure rather than a silent skip.
