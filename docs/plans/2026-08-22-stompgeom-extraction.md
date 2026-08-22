# `stompgeom` Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the workspace's kernel layer into a third package, `stompgeom`, moving the frame *values* down into `stompmodel` and the STEP reader and deterministic writer out of `stompdrill`, without changing a single emitted byte.

**Architecture:** `stompmodel` (pure-Python leaf) gains `frames.py`. A new `stompgeom` package sits above it holding the OpenCASCADE-facing format layer: the STEP reader, the deterministic writer with its byte normalisation, and the kernel guard. `stompdrill` keeps everything enclosure-shaped — `CaseModel`, `Rejection`, the play-area reasoning, and the hole cutter — and depends on both. The kernel stops being optional.

**Tech Stack:** Python 3.10+, uv workspace, `cadquery-ocp==7.9.3.1.1` (OpenCASCADE via OCP), pytest, mypy, ruff, mutmut.

**Spec:** `docs/specs/stompgeom-technical.md` — this is **plan 2 of 3** from `docs/specs/stompcollider-technical.md`'s "Order of work". Read both.

## Global Constraints

- **Byte identity is the success criterion.** Every artefact `stompdrill` emits must be unchanged. Do not reorder arithmetic, rename an emitted string, or alter a header value. Where a move tempts you to tidy, don't.
- **Dependency order is linear and acyclic:** `stompmodel` → `stompgeom` → `stompdrill`. `stompmodel`'s distribution declares **no dependencies at all**. `stompgeom` may import `stompmodel` and `OCP`, nothing else.
- **Each package installs and passes its own tests alone.** ADR-0008's governing test.
- **One name, one home.** Nothing is re-exported for backwards compatibility. Update every import site.
- **Every module keeps `from __future__ import annotations` and an explicit, logically ordered `__all__`.** Value objects are frozen, slotted dataclasses.
- **Docstrings are at most ten physical lines.** Rationale belongs in an ADR.
- **British spelling in prose, established American spelling in identifiers.**
- **Record no measurements** in any document this plan touches — no test counts, no mutation tallies. Name the command instead.
- Run everything from the repository root unless a step says otherwise.

---

### Task 1: `CoordinateFrame` in `stompmodel`

The frame value is pure Python: only the kernel code that *builds* one needs OCP. It lands in the leaf so `DrillData` can carry it in plan 3 without `stompmodel` growing a kernel dependency.

**Files:**
- Create: `packages/stompmodel/src/stompmodel/frames.py`
- Test: `packages/stompmodel/tests/test_frames.py`

**Interfaces:**
- Consumes: `stompmodel.units.Nanometre`, `Millimetre`, `mm_from_nm`, `nm_from_mm`; `stompmodel.diagnostics.ParameterValue`
- Produces: `CoordinateFrame(origin_nm, u, v, w)` with `to_model(x_nm, y_nm) -> tuple[Millimetre, Millimetre, Millimetre]`, `to_canonical(point_mm) -> tuple[Millimetre, Millimetre]`, `reframe(x_nm, y_nm, target) -> tuple[Nanometre, Nanometre]`, `as_parameters() -> tuple[tuple[str, ParameterValue], ...]`

- [ ] **Step 1: Write the failing tests**

Create `packages/stompmodel/tests/test_frames.py`:

```python
"""The frame value's arithmetic, which the kernel layer above only builds."""

from __future__ import annotations

from stompmodel.frames import CoordinateFrame
from stompmodel.units import Millimetre, Nanometre

#: A frame whose axes are deliberately not the kernel's own: ``u`` runs along
#: -Y and ``v`` along +Z, so a test cannot pass by ignoring the basis.
ROTATED = CoordinateFrame(
    origin_nm=(Nanometre(1_000_000), Nanometre(2_000_000), Nanometre(3_000_000)),
    u=(0.0, -1.0, 0.0),
    v=(0.0, 0.0, 1.0),
    w=(1.0, 0.0, 0.0),
)


def test_to_model_returns_the_origin_for_the_frame_origin() -> None:
    """Canonical (0, 0) is the frame's own origin, in millimetres."""
    assert ROTATED.to_model(Nanometre(0), Nanometre(0)) == (1.0, 2.0, 3.0)


def test_to_model_walks_u_for_x() -> None:
    """A canonical x displaces along ``u``, not along the kernel's own X."""
    assert ROTATED.to_model(Nanometre(5_000_000), Nanometre(0)) == (1.0, -3.0, 3.0)


def test_to_model_walks_v_for_y() -> None:
    """A canonical y displaces along ``v``. Checked apart from x so that a
    formula using one axis for both still fails one of these two."""
    assert ROTATED.to_model(Nanometre(0), Nanometre(5_000_000)) == (1.0, 2.0, 8.0)


def test_to_canonical_inverts_to_model() -> None:
    """The round trip returns the coordinates it started from."""
    point = ROTATED.to_model(Nanometre(7_000_000), Nanometre(-4_000_000))

    assert ROTATED.to_canonical(point) == (7.0, -4.0)


def test_to_canonical_returns_millimetres_not_nanometres() -> None:
    """The unit is load-bearing: ``region_bbox_nm`` rounds after its own
    minimum and maximum, so this must not round here."""
    assert ROTATED.to_canonical((1.0, 2.0, 3.5)) == (0.0, 0.5)


def test_reframe_restates_a_point_on_another_frame() -> None:
    """A point measured against one face means something else on another.

    The target is the same origin viewed from the opposite side, so a
    canonical x of +5 mm on the source reads as -5 mm on the target.
    """
    target = CoordinateFrame(
        origin_nm=ROTATED.origin_nm, u=(0.0, 1.0, 0.0), v=(0.0, 0.0, 1.0), w=(-1.0, 0.0, 0.0)
    )

    assert ROTATED.reframe(Nanometre(5_000_000), Nanometre(0), target) == (
        Nanometre(-5_000_000),
        Nanometre(0),
    )


def test_reframe_onto_the_same_frame_is_the_identity() -> None:
    """The degenerate case, so the conversion cannot silently drop a term."""
    assert ROTATED.reframe(Nanometre(3_000_000), Nanometre(9_000_000), ROTATED) == (
        Nanometre(3_000_000),
        Nanometre(9_000_000),
    )


def test_as_parameters_flattens_every_member() -> None:
    """``StageRun`` provenance names all four, so none may be dropped."""
    assert ROTATED.as_parameters() == (
        ("frame_origin_nm", (1_000_000, 2_000_000, 3_000_000)),
        ("frame_u", (0.0, -1.0, 0.0)),
        ("frame_v", (0.0, 0.0, 1.0)),
        ("frame_w", (1.0, 0.0, 0.0)),
    )


def test_the_frame_is_frozen() -> None:
    """A registration is a value; a transform returns a replacement."""
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        ROTATED.u = (1.0, 0.0, 0.0)  # type: ignore[misc]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd packages/stompmodel && uv run --no-sync pytest -o addopts= tests/test_frames.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'stompmodel.frames'`.

- [ ] **Step 3: Write the implementation**

Create `packages/stompmodel/src/stompmodel/frames.py`:

```python
"""A coordinate frame, and the face registration that wraps one.

A frame is a registration rather than an operation, so the value lives in the
leaf and the kernel code that builds one lives above it. That keeps the graph
linear and lets a consumer take a frame without taking a CAD kernel. See
ADR-0009.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import ParameterValue
from .units import Millimetre, Nanometre, mm_from_nm, nm_from_mm

__all__ = ["CoordinateFrame", "FaceFrame"]


@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    """An origin and a right-handed basis.

    Carries no meaning about what it registers -- that is the point. The
    meaning is added by wrapping, not by a field here.
    """

    origin_nm: tuple[Nanometre, Nanometre, Nanometre]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    w: tuple[float, float, float]

    def to_model(
        self, x_nm: Nanometre, y_nm: Nanometre
    ) -> tuple[Millimetre, Millimetre, Millimetre]:
        """Map canonical face coordinates into model millimetres."""
        x, y = mm_from_nm(x_nm), mm_from_nm(y_nm)
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        return (
            Millimetre(origin[0] + x * self.u[0] + y * self.v[0]),
            Millimetre(origin[1] + x * self.u[1] + y * self.v[1]),
            Millimetre(origin[2] + x * self.u[2] + y * self.v[2]),
        )

    def to_canonical(
        self, point_mm: tuple[float, float, float]
    ) -> tuple[Millimetre, Millimetre]:
        """Project a model point onto this frame's own axes, in millimetres.

        Millimetres, not nanometres: ``region_bbox_nm`` projects four corners
        and rounds once after its own minimum and maximum, and rounding here
        would round each corner first instead.
        """
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        relative = tuple(p - o for p, o in zip(point_mm, origin))
        x = sum(r * c for r, c in zip(relative, self.u))
        y = sum(r * c for r, c in zip(relative, self.v))
        return (Millimetre(x), Millimetre(y))

    def reframe(
        self, x_nm: Nanometre, y_nm: Nanometre, target: CoordinateFrame
    ) -> tuple[Nanometre, Nanometre]:
        """Restate a canonical point registered here in ``target``'s frame."""
        x_mm, y_mm = target.to_canonical(self.to_model(x_nm, y_nm))
        return nm_from_mm(x_mm), nm_from_mm(y_mm)

    def as_parameters(self) -> tuple[tuple[str, ParameterValue], ...]:
        """Flatten to ``StageRun``-safe scalars and float tuples."""
        return (
            ("frame_origin_nm", tuple(self.origin_nm)),
            ("frame_u", self.u),
            ("frame_v", self.v),
            ("frame_w", self.w),
        )
```

Leave `FaceFrame` out of `__all__`'s implementation for now — Task 2 adds the class; the name is listed here so the two tasks do not fight over the line.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd packages/stompmodel && uv run --no-sync pytest -o addopts= tests/test_frames.py -v
```

Expected: all pass. (`__all__` naming a not-yet-defined `FaceFrame` does not break imports; Task 2 closes it. If ruff's F822 objects, add `FaceFrame` in Task 2 before running ruff.)

- [ ] **Step 5: Commit**

```bash
git add packages/stompmodel/src/stompmodel/frames.py packages/stompmodel/tests/test_frames.py
git commit -m "Give the frame value a home in the leaf, with its own arithmetic

The value needs no kernel; only the code that builds one does. Putting it in
stompmodel is the division ADR-0009 already made for lengths, and it is what
lets the drill document carry a face frame without the leaf importing a CAD
kernel."
```

---

### Task 2: `FaceFrame`, and the leaf's boundary gate corrected

`FaceFrame` adds a guarantee and no fields. It composes rather than subclasses, so it cannot pass silently where a bare `CoordinateFrame` is wanted. The boundary gate's `TYPE_CHECKING` example currently names `stompgeom.frames`, a module this design means will never exist.

**Files:**
- Modify: `packages/stompmodel/src/stompmodel/frames.py`
- Modify: `packages/stompmodel/tests/test_package_boundary.py`
- Modify: `packages/stompmodel/tests/test_frames.py`

**Interfaces:**
- Consumes: `CoordinateFrame` from Task 1
- Produces: `FaceFrame(basis: CoordinateFrame)` — one field, named `basis`. Callers reach through it: `face_frame.basis.to_model(...)`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/stompmodel/tests/test_frames.py`:

```python
def test_a_face_frame_wraps_a_basis() -> None:
    """The wrapping is visible at the call site, which is the point of it."""
    from stompmodel.frames import FaceFrame

    assert FaceFrame(basis=ROTATED).basis is ROTATED


def test_a_face_frame_is_not_a_coordinate_frame() -> None:
    """Composition, not inheritance: a face frame carries a meaning that a
    bare transform does not, so it must not substitute for one silently."""
    from stompmodel.frames import FaceFrame

    assert not isinstance(FaceFrame(basis=ROTATED), CoordinateFrame)
```

In `packages/stompmodel/tests/test_package_boundary.py`, change the guarded import inside `test_the_scanner_finds_a_sibling_hidden_behind_type_checking` from

```python
        "    from stompgeom.frames import FaceFrame\n"
```

to

```python
        "    from stompgeom.step import read_step\n"
```

and add `"frames.py"` to the set asserted in `test_the_scan_reaches_every_module_the_package_ships`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd packages/stompmodel && uv run --no-sync pytest -o addopts= tests/test_frames.py tests/test_package_boundary.py -v
```

Expected: `ImportError: cannot import name 'FaceFrame'`, and the module-list assertion fails on the missing `frames.py`.

- [ ] **Step 3: Write the implementation**

Append to `packages/stompmodel/src/stompmodel/frames.py`:

```python
@dataclass(frozen=True, slots=True)
class FaceFrame:
    """A face's registration: a frame whose third axis is that face's normal.

    Composes rather than extends. A subclass would pass wherever a bare
    ``CoordinateFrame`` is wanted, which is exactly the universal-wrapped-in-a-
    meaning leak ADR-0008 names as this boundary's standing risk.
    """

    basis: CoordinateFrame
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd packages/stompmodel && uv run --no-sync pytest -o addopts= -q
cd packages/stompmodel && uv run --no-sync mypy
```

Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add packages/stompmodel
git commit -m "Wrap the basis in a face frame, and stop the gate naming a fiction

The boundary gate's TYPE_CHECKING example imported from a stompgeom.frames
that this design means will never exist. The gate still fired either way --
it only exercises the scanner -- so it was a green test documenting an
architecture nobody chose."
```

---

### Task 3: The `stompgeom` package, its kernel guard, and its boundary gate

A new distribution with nothing in it yet but the kernel-availability concern, so the packaging and the gate are proved before any code depends on them.

**Files:**
- Create: `packages/stompgeom/pyproject.toml`
- Create: `packages/stompgeom/src/stompgeom/__init__.py`
- Create: `packages/stompgeom/src/stompgeom/py.typed` (empty)
- Create: `packages/stompgeom/src/stompgeom/errors.py`
- Create: `packages/stompgeom/src/stompgeom/kernel.py`
- Create: `packages/stompgeom/tests/__init__.py` (empty)
- Create: `packages/stompgeom/tests/test_kernel.py`
- Create: `packages/stompgeom/tests/test_package_boundary.py`

**Interfaces:**
- Consumes: `stompmodel.errors.StompError`
- Produces: `stompgeom.errors.StompgeomError`; `stompgeom.kernel.KernelUnavailable`, `stompgeom.kernel.require_kernel() -> None`. **Callers import the module, not the name** (`from stompgeom import kernel` then `kernel.require_kernel()`), so a test can still simulate an absent kernel by patching the attribute.

- [ ] **Step 1: Write the failing tests**

Create `packages/stompgeom/tests/test_kernel.py`:

```python
"""The kernel guard: it names the dependency, and it names no consumer."""

from __future__ import annotations

import pytest

from stompgeom import kernel
from stompgeom.errors import StompgeomError
from stompmodel.errors import StompError


def test_kernel_unavailable_is_a_stompgeom_error() -> None:
    """Each package's errors stay identifiable beneath the shared base."""
    assert issubclass(kernel.KernelUnavailable, StompgeomError)


def test_stompgeom_error_is_a_stomp_error() -> None:
    """``except StompError`` must be a complete catch across the workspace."""
    assert issubclass(StompgeomError, StompError)


def test_require_kernel_passes_when_the_kernel_imports() -> None:
    """The kernel is a hard dependency, so the guard is quiet in a real env."""
    assert kernel.require_kernel() is None


def test_require_kernel_raises_when_the_kernel_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure names the missing distribution."""
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "OCP":
            raise ImportError("no OCP here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(kernel.KernelUnavailable, match="cadquery-ocp"):
        kernel.require_kernel()


def test_the_hint_names_no_consumer() -> None:
    """A shared component never bakes in the identity of a package above it.

    ADR-0009 made this rule for ``SourceInfo.producer``; an install hint that
    told a stompcollider user to reinstall stompdrill is the same defect.
    """
    from stompgeom.kernel import _INSTALL_HINT

    assert "stompdrill" not in _INSTALL_HINT
    assert "stompcollider" not in _INSTALL_HINT
    assert "stompcad" not in _INSTALL_HINT
```

Create `packages/stompgeom/tests/test_package_boundary.py` as a copy of `packages/stompmodel/tests/test_package_boundary.py` with these differences, and no others:

- `SOURCE` points at `.../src/stompgeom`.
- `PERMITTED = frozenset(sys.stdlib_module_names) | {"stompgeom", "stompmodel", "OCP"}`.
- The docstrings say this package may take the leaf and the kernel and nothing above it.
- `test_the_scanner_finds_a_sibling_import` asserts `foreign_imports("from stompdrill.units import Micron") == {"stompdrill"}` (still a violation here — `stompdrill` is *above* this package).
- Add `test_the_scanner_accepts_the_leaf_and_the_kernel`, asserting `foreign_imports("import OCP.TDF\nfrom stompmodel.units import Nanometre\n") == set()`.
- `test_the_scan_reaches_every_module_the_package_ships` asserts the set `{"__init__.py", "errors.py", "kernel.py"}` for now; Tasks 4 and 5 add `step.py` and `writer.py`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
```

Expected: the package does not exist; the run fails to collect.

- [ ] **Step 3: Write the package**

`packages/stompgeom/pyproject.toml`:

```toml
[project]
name = "stompgeom"
version = "0.1.0"
description = "The workspace's kernel layer: the STEP reader, the deterministic writer, and the kernel guard"
requires-python = ">=3.10"
# The kernel is unconditional here. A kernel-free configuration of this
# package is one nobody runs, and ADR-0009 retired the optional extra that
# pretended otherwise.
dependencies = ["stompmodel", "cadquery-ocp==7.9.3.1.1"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

# PEP 561: without this marker a downstream type checker discards every
# annotation this distribution ships.
[tool.setuptools.package-data]
stompgeom = ["py.typed"]

# So ADR-0008's sentence -- change into the member, sync, test -- runs a real
# suite rather than an import check. `mypy` is here because the root gate
# excludes this member's tests: three `tests` packages cannot share one scan.
[dependency-groups]
dev = ["pytest", "mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.mypy]
python_version = "3.10"
mypy_path = "src"
files = ["src", "tests"]

# mutmut resolves tests through the pyproject.toml in the current working
# directory, and the root one names only stompdrill's testpaths, so a mutant of
# this member run through the root config would record a false survivor.
# `cd packages/stompgeom && mutmut run` is the real survey.
[tool.mutmut]
source_paths = ["src/stompgeom"]
# mutmut injects `import mutmut` into every module it instruments, which the
# boundary gate rejects by design. Deselecting keeps the gate's assertion
# exact rather than weakening the rule itself.
pytest_add_cli_args_test_selection = [
    "--deselect=tests/test_package_boundary.py::test_every_module_imports_only_the_standard_library_and_itself",
]
```

`packages/stompgeom/src/stompgeom/__init__.py`:

```python
"""The workspace's kernel layer.

The format side of geometry: reading a STEP assembly, writing one
deterministically, and refusing to start without the kernel. No enclosure
vocabulary crosses this boundary. See ADR-0008 and ADR-0009.
"""

from __future__ import annotations

#: Deliberately empty. Every value here is imported from the module that
#: defines it -- one name, one home, and no second import path to drift.
__all__: list[str] = []
```

`packages/stompgeom/src/stompgeom/errors.py`:

```python
"""This package's error base, beneath the workspace's own."""

from __future__ import annotations

from stompmodel.errors import StompError

__all__ = ["StompgeomError"]


class StompgeomError(StompError):
    """Base for every error raised by stompgeom alone."""
```

`packages/stompgeom/src/stompgeom/kernel.py`:

```python
"""Whether the geometry kernel is present, and how to say that it is not."""

from __future__ import annotations

from .errors import StompgeomError

__all__ = ["KernelUnavailable", "require_kernel"]

#: Names the distribution, never a consumer of this package. A hint that told
#: one tool's user to reinstall another tool's extra would be the defect
#: ADR-0009 removed from ``SourceInfo.producer``.
_INSTALL_HINT = (
    "the geometry kernel is missing: reinstall the cadquery-ocp dependency "
    "(uv sync --all-packages), or run the environment doctor"
)


class KernelUnavailable(StompgeomError):
    """The geometry kernel is a hard dependency and did not import."""


def require_kernel() -> None:
    """Raise a helpful error when OpenCASCADE is not importable."""
    try:
        import OCP  # noqa: F401
    except ImportError as failure:
        raise KernelUnavailable(_INSTALL_HINT) from failure
```

Create `packages/stompgeom/src/stompgeom/py.typed` and `packages/stompgeom/tests/__init__.py` as empty files.

- [ ] **Step 4: Sync and run the tests**

```bash
uv sync --all-packages --all-extras
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
cd packages/stompgeom && uv run --no-sync mypy
```

Expected: both clean. The root workspace picks the member up with no config change — `members = ["packages/*"]` and ruff's `src = [".", "packages/*/src", "packages/*"]` already glob it.

- [ ] **Step 5: Prove it installs alone**

```bash
cd /tmp && rm -rf stompgeom-alone && python3 -m venv stompgeom-alone
/tmp/stompgeom-alone/bin/pip install -q /Users/thelyx/repo/stompcad/packages/stompmodel /Users/thelyx/repo/stompcad/packages/stompgeom pytest
cd /Users/thelyx/repo/stompcad/packages/stompgeom && /tmp/stompgeom-alone/bin/python -m pytest -o addopts= -q
```

Expected: passes. This is ADR-0008's governing test for the new member.

- [ ] **Step 6: Commit**

```bash
git add packages/stompgeom
git commit -m "Stand up stompgeom with its kernel guard and its boundary gate

Nothing depends on it yet. The packaging, the error base and the import gate
are proved first, so the moves that follow land in a member already known to
install and pass alone."
```

---

### Task 4: Move the STEP reader into `stompgeom.step`

`cad/step.py` is already "the format layer, with nothing enclosure-specific in it" by its own docstring. It moves whole.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/step.py`
- Create: `packages/stompgeom/tests/test_step.py`
- Modify: `packages/stompgeom/tests/test_package_boundary.py` (module list gains `step.py`)
- Delete: `packages/stompdrill/src/stompdrill/cad/step.py` (in Task 6, once its callers move)

**Interfaces:**
- Consumes: `stompgeom.kernel.require_kernel`, `stompmodel.errors.DocumentError`
- Produces: `StepSolid(name, shape, unit_mm)`, `StepDocument(solids, document, timestamp)` with `.named(keyword)`, `read_step(path) -> StepDocument`, `bounding_box_mm(shape) -> tuple[float, ...]`, `source_timestamp(path) -> str`

- [ ] **Step 1: Write the failing test**

Create `packages/stompgeom/tests/test_step.py`:

```python
"""The reader's own contract, apart from any enclosure that uses it."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompgeom.step import _EPOCH, source_timestamp
from stompmodel.errors import DocumentError


def test_source_timestamp_reads_the_comment_marker(tmp_path: Path) -> None:
    """ST-Developer's comment above FILE_NAME, not the FILE_NAME field."""
    target = tmp_path / "stamped.stp"
    target.write_bytes(b"ISO-10303-21;\n/* time_stamp */ '2020-01-02T03:04:05'\n")

    assert source_timestamp(target) == "2020-01-02T03:04:05"


def test_source_timestamp_falls_back_to_the_epoch(tmp_path: Path) -> None:
    """Never a clock reading: determinism does not depend on the file
    carrying a stamp, only on every write copying the same value."""
    target = tmp_path / "bare.stp"
    target.write_bytes(b"ISO-10303-21;\n")

    assert source_timestamp(target) == _EPOCH


def test_reading_a_missing_file_is_a_document_error(tmp_path: Path) -> None:
    """A stompgeom reader cannot raise a stompdrill error; refusing a foreign
    document is a failure any member can have, so the base is shared."""
    from stompgeom.step import read_step

    with pytest.raises(DocumentError, match="no case model at"):
        read_step(tmp_path / "absent.stp")


def test_reading_a_non_step_file_is_a_document_error(tmp_path: Path) -> None:
    """Not readable is distinct from not present, and both are the file's
    fault rather than the data's."""
    from stompgeom.step import read_step

    target = tmp_path / "rubbish.stp"
    target.write_bytes(b"this is not a STEP file at all\n")

    with pytest.raises(DocumentError):
        read_step(target)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_step.py -v
```

Expected: `ModuleNotFoundError: No module named 'stompgeom.step'`.

- [ ] **Step 3: Move the module**

Copy `packages/stompdrill/src/stompdrill/cad/step.py` to `packages/stompgeom/src/stompgeom/step.py` **verbatim**, then make exactly these four changes:

1. Replace the imports `from ..errors import StompdrillError` and `from .base import KernelUnavailable` with `from stompmodel.errors import DocumentError` and `from .kernel import require_kernel as _require_kernel`.
2. Delete the module's own `require_kernel` definition and the `_INSTALL_HINT` constant — Task 3 owns both now. Re-export the name so callers keep one import path: add `require_kernel = _require_kernel` immediately below the imports, and keep `"require_kernel"` in `__all__`.
3. Replace all three `raise StompdrillError(...)` calls in `read_step` with `raise DocumentError(...)`, message text unchanged.
4. In the `source_timestamp` docstring, change "an stompdrill-written STEP file" to "a STEP file this workspace wrote" and "stompdrill's own writer" to "this workspace's own writer" — the module no longer belongs to that tool.

Everything else — `_EPOCH`, `_TIMESTAMP_PATTERN`, `StepSolid`, `StepDocument`, `bounding_box_mm`, `read_step`, `_collect`, `_name_of`, and every comment explaining `AddOptimal_s`, the millimetre normalisation and the component-label placement — is copied unchanged.

Add `"step.py"` to the module set in `packages/stompgeom/tests/test_package_boundary.py`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
cd packages/stompgeom && uv run --no-sync mypy
```

Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add packages/stompgeom
git commit -m "Move the STEP reader into the kernel layer

Its own docstring already called it the format layer with nothing
enclosure-specific in it. Its refusals become DocumentError, which ADR-0009
put in the leaf precisely so a reader in any member could raise it."
```

---

### Task 5: Move the deterministic writer into `stompgeom.writer`

The lower half of `emitters/step.py` is the format layer; the upper half decides what to cut. This task moves the former and injects every piece of identity the writer used to hardcode.

**Files:**
- Create: `packages/stompgeom/src/stompgeom/writer.py`
- Create: `packages/stompgeom/tests/test_writer.py`
- Modify: `packages/stompgeom/tests/test_package_boundary.py` (module list gains `writer.py`)

**Interfaces:**
- Consumes: `stompgeom.kernel.require_kernel`, `stompmodel.errors.EmitterError`
- Produces:
  ```python
  def write_step(document, path, *, title: str, timestamp: str,
                 originating_system: str,
                 replaced_labels: frozenset[str] = frozenset()) -> None
  def label_entry(label) -> str
  def label_name(label) -> str
  ```
  `_PRODUCT_NAME` stays private to this module and keeps the value `"stompcad"`.

- [ ] **Step 1: Write the failing test**

Create `packages/stompgeom/tests/test_writer.py`:

```python
"""The writer's identity contract and its colour-chain guard."""

from __future__ import annotations

import pytest

from stompgeom import writer
from stompmodel.errors import EmitterError


def test_the_wrapper_product_name_is_the_workspace_not_a_package() -> None:
    """It is load-bearing, not cosmetic: ``_normalise`` strips the volatile
    counter appended to exactly this prefix, so the setter, the pattern and
    the replacement must all read one constant."""
    assert writer._PRODUCT_NAME == "stompcad"


def test_normalise_erases_the_translator_version_suffix() -> None:
    """Two writes of one document must not differ by a process counter."""
    payload = b"#1 = PRODUCT('stompcad 1.2','stompcad 1.2',' ',(#2));\n"

    assert b"'stompcad'" in writer._normalise(payload)
    assert b"stompcad 1.2" not in writer._normalise(payload)


def test_normalise_renumbers_assembly_usage_occurrences_from_one() -> None:
    """The NAUO counter is process-global and has no resettable key."""
    payload = (
        b"#9 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('417','','',#1,#2,$);\n"
        b"#10 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('418','','',#1,#3,$);\n"
    )
    normalised = writer._normalise(payload)

    assert b"OCCURRENCE('1'" in normalised
    assert b"OCCURRENCE('2'" in normalised


def test_a_colour_chain_count_mismatch_is_refused() -> None:
    """Reordering nothing looks identical to reordering correctly unless the
    count is checked, which is what a kernel upgrade would silently break."""
    with pytest.raises(EmitterError, match="likely needs updating"):
        writer._reslot_colours(b"", expected=3)


def test_the_mismatch_message_names_this_module() -> None:
    """The remedy has to point at the pattern that needs the edit."""
    with pytest.raises(EmitterError, match=r"stompgeom\.writer"):
        writer._reslot_colours(b"", expected=1)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= tests/test_writer.py -v
```

Expected: `ModuleNotFoundError: No module named 'stompgeom.writer'`.

- [ ] **Step 3: Move the writer half**

Create `packages/stompgeom/src/stompgeom/writer.py` holding, copied **verbatim** from `packages/stompdrill/src/stompdrill/emitters/step.py`: the module docstring's writer half, `_PRODUCT_NAME`, `_VOLATILE_ENTITY`, `_VOLATILE_VERSION`, `_VOLATILE_NAUO_ID`, `_COLOUR_CHAIN` with all their explanatory comments, plus `_count_colour_assignments`, `_silence_stdout`, `_normalise`, `_reslot_colours`, and `_write`. Also move `_label_name` and `_label_entry`, renamed public as `label_name` and `label_entry` (the cutter in `stompdrill` needs both, and `_count_colour_assignments` needs `label_entry`).

Then make exactly these changes, and no others:

1. `_write` is renamed `write_step` and becomes the module's public entry point. Its signature becomes:

```python
def write_step(
    document: Any,
    path: Any,
    *,
    title: str,
    timestamp: str,
    originating_system: str,
    replaced_labels: frozenset[str] = frozenset(),
) -> None:
```

2. Inside it, the two hardcoded identity strings are replaced by the parameters. `header.SetName(TCollection_HAsciiString(title or "stompdrill"))` becomes `header.SetName(TCollection_HAsciiString(title))`, and `header.SetOriginatingSystem(TCollection_HAsciiString(f"stompdrill {_VERSION}"))` becomes `header.SetOriginatingSystem(TCollection_HAsciiString(originating_system))`. **`_VERSION` does not move** — it stays in `stompdrill`, which now supplies the whole string. Delete `_VERSION` from this module.

3. `touched` is renamed `replaced_labels` throughout `write_step` and `_count_colour_assignments`. Update `_count_colour_assignments`'s docstring to say "a replaced solid" rather than "a cut solid", and its comment likewise — this module knows that `SetShape` dropped the colour, not why the shape was replaced.

4. `_silence_stdout`'s docstring loses "an `stompdrill` invocation" in favour of "a caller's report".

5. `_reslot_colours`'s `EmitterError` message changes `_COLOUR_CHAIN in stompdrill.emitters.step likely needs updating` to `_COLOUR_CHAIN in stompgeom.writer likely needs updating`. This is an error path and reaches no emitted artefact.

6. `write_step` calls `require_kernel()` first, imported as `from .kernel import require_kernel`.

7. `__all__ = ["write_step", "label_entry", "label_name"]`.

Add `"writer.py"` to the module set in `packages/stompgeom/tests/test_package_boundary.py`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
cd packages/stompgeom && uv run --no-sync mypy
```

Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add packages/stompgeom
git commit -m "Move the deterministic writer, with its identity injected

Left as it was, a stompcollider assembly written through this would stamp
ORIGINATING_SYSTEM with stompdrill's name -- provenance from a tool that
never touched it. ADR-0009 ruled on that pattern for SourceInfo.producer and
the argument is unchanged here, so the caller names itself.

`touched` becomes `replaced_labels`: the writer knows SetShape dropped the
colour, not that a drill was the reason."
```

---

### Task 6: Rewire `stompdrill`'s `cad/` onto the new homes

`Frame` is deleted; `FaceFrame` replaces it. `cad/step.py` is deleted; `stompgeom.step` replaces it. `region.py` loses the three functions that became methods.

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/cad/base.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/case.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/loader.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/region.py`
- Modify: `packages/stompdrill/src/stompdrill/cad/__init__.py`
- Modify: `packages/stompdrill/src/stompdrill/__init__.py`
- Modify: `packages/stompdrill/pyproject.toml` (dependencies gain `stompgeom`)
- Delete: `packages/stompdrill/src/stompdrill/cad/step.py`
- Modify: `packages/stompdrill/tests/conftest.py`, `test_cad_base.py`, `test_cad_case.py`, `test_cad_region.py`, `test_cad_region_synthetic.py`, `test_cad_step.py`

**Interfaces:**
- Consumes: `stompmodel.frames.FaceFrame`, `CoordinateFrame`; `stompgeom.step.read_step`, `bounding_box_mm`; `stompgeom.kernel.require_kernel`
- Produces: `CaseModel.frame` is now a `FaceFrame`. `build_frame(faces, axis) -> FaceFrame`. `region.contains`, `region.clearance_reason`, `region.region_bbox_nm` all take a `FaceFrame`.

- [ ] **Step 1: Point the tests at the new names**

In `packages/stompdrill/tests/`, replace every `from stompdrill.cad import ... Frame ...` with `from stompmodel.frames import CoordinateFrame, FaceFrame`, and every construction `Frame(origin_nm=..., u=..., v=..., w=...)` with `FaceFrame(basis=CoordinateFrame(origin_nm=..., u=..., v=..., w=...))`. In `test_cad_base.py`, change the base assertion:

```python
def test_kernel_unavailable_is_a_stompgeom_error() -> None:
    """It moved packages with the guard; stompdrill no longer owns it."""
    from stompgeom.errors import StompgeomError
    from stompgeom.kernel import KernelUnavailable

    assert issubclass(KernelUnavailable, StompgeomError)
```

Delete `packages/stompdrill/tests/test_cad_step.py` — its subject now lives in `packages/stompgeom/tests/test_step.py`, and a recovery of the reader from `stompdrill` would prove nothing this workspace does not already assert.

- [ ] **Step 2: Run the suite to verify it fails**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --tb=short
```

Expected: import errors naming `Frame` and `stompgeom`.

- [ ] **Step 3: Rewire the modules**

`cad/base.py`: delete the `Frame` dataclass and the `KernelUnavailable` class entirely. Import `from stompmodel.frames import FaceFrame`, change `CaseModel.frame`'s annotation to `FaceFrame`, and set `__all__ = ["Rejection", "CaseModel"]`.

`cad/case.py`: import `from stompmodel.frames import CoordinateFrame, FaceFrame` and `from stompgeom.step import bounding_box_mm`. `build_frame` returns `FaceFrame(basis=CoordinateFrame(origin_nm=..., u=u, v=v, w=w))` — the arithmetic above the return is unchanged. Its return annotation becomes `FaceFrame`.

`cad/loader.py`: import `read_step` from `stompgeom.step` and `require_kernel` from `stompgeom.kernel` (as a module: `from stompgeom import kernel`, then `kernel.require_kernel()`). Annotate `frame`, `own_frame` and `box_frame` as `FaceFrame` / `FaceFrame | None`.

`cad/region.py`: delete `_to_model`, `_to_canonical` and `reframe`. Import `bounding_box_mm` from `stompgeom.step`. At the four former call sites, reach through the basis:

- line ~125: `corners.append(frame.basis.to_canonical((point[0], point[1], point[2])))`
- lines ~161 and ~240: `point = list(frame.basis.to_model(x_nm, y_nm))`
- the former `reframe` body moves to its caller in `loader.py`, which becomes:

```python
        box_x, box_y = self.own_frame.basis.reframe(x_nm, y_nm, self.box_frame.basis)
```

Keep `reframe`'s explanation as a comment at that call site — a box and its lid are viewed from opposite sides, so the same canonical x is a different model x on each. Remove `"reframe"` from `region.py`'s `__all__`.

`cad/__init__.py`: `__all__ = ["CaseModel", "Rejection", "load_case_model"]`.

`stompdrill/__init__.py`: drop `Frame` and `KernelUnavailable` from the imports and from `__all__`. Nothing is re-exported in their place.

`packages/stompdrill/pyproject.toml`: `dependencies = ["stompmodel", "stompgeom", "pikepdf>=9"]`.

- [ ] **Step 4: Run the suite to verify it passes**

```bash
uv sync --all-packages --all-extras
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond --tb=short
ruff check packages tools
mypy packages
```

Expected: all clean. If a hole position moves by even a nanometre, stop — the arithmetic was reordered somewhere, and that is the one thing this plan forbids.

- [ ] **Step 5: Commit**

```bash
git add packages/stompdrill
git commit -m "Rewire the enclosure code onto the frame value and the kernel layer

Frame is deleted in favour of FaceFrame wrapping a CoordinateFrame, and
region.py loses the three functions that became methods on the value --
including the origin + x*u + y*v it kept a second copy of."
```

---

### Task 7: Rewire the step emitter onto `stompgeom.writer`

The cutter stays. It now calls a writer that knows nothing about drilling, and names itself in the header.

**Files:**
- Modify: `packages/stompdrill/src/stompdrill/emitters/step.py`
- Modify: `packages/stompdrill/tests/test_step_cut.py`, `test_step_emitter.py`

**Interfaces:**
- Consumes: `stompgeom.writer.write_step`, `label_entry`, `label_name`; `stompgeom.kernel`
- Produces: `StepEmitter`, `StepOptions`, `cut_shape(model, data) -> tuple[Any, Callable[[], None], frozenset[str]]` — all unchanged in signature.

- [ ] **Step 1: Point the tests at the new module**

In `test_step_cut.py`, the colour-chain test monkeypatches `step_module._COLOUR_CHAIN`; repoint it at `stompgeom.writer`:

```python
    from stompgeom import writer as writer_module

    broken = re.compile(
        re.sub(rb"STYLED_ITEM", rb"STYLED_ITEM_ZZZ", writer_module._COLOUR_CHAIN.pattern),
        writer_module._COLOUR_CHAIN.flags,
    )
    monkeypatch.setattr(writer_module, "_COLOUR_CHAIN", broken)
```

In `test_step_emitter.py`, the kernel-absence test patches `step_module.require_kernel`; repoint it at the module the emitter now calls through:

```python
    from stompgeom import kernel as kernel_module

    monkeypatch.setattr(kernel_module, "require_kernel", absent)
```

Add a test that pins the header identity, since it is the one thing the move could silently change:

```python
def test_the_emitter_names_itself_as_the_originating_system() -> None:
    """The writer defaults nothing. A shared writer that stamped one tool's
    name would give a stompcollider assembly provenance from a tool that
    never touched it -- ADR-0009's rule for SourceInfo.producer."""
    from stompdrill.emitters import step as step_module

    assert step_module._ORIGINATING_SYSTEM == f"stompdrill {step_module._VERSION}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests/test_step_cut.py packages/stompdrill/tests/test_step_emitter.py -v
```

Expected: attribute errors for the removed names, and `_ORIGINATING_SYSTEM` undefined.

- [ ] **Step 3: Rewire the emitter**

Delete from `packages/stompdrill/src/stompdrill/emitters/step.py`: `_PRODUCT_NAME`, `_VOLATILE_ENTITY`, `_VOLATILE_VERSION`, `_VOLATILE_NAUO_ID`, `_COLOUR_CHAIN`, `require_kernel`, `_count_colour_assignments`, `_silence_stdout`, `_normalise`, `_reslot_colours`, `_write`, `_label_name`, `_label_entry`. Keep `_VERSION` and add beside it:

```python
#: Named at the call site, never defaulted inside the shared writer.
_ORIGINATING_SYSTEM = f"stompdrill {_VERSION}"
```

Replace the deleted imports with:

```python
from stompgeom import kernel
from stompgeom.writer import label_entry, label_name, write_step
```

In `StepEmitter.__init__`, the guard becomes:

```python
        try:
            kernel.require_kernel()
        except kernel.KernelUnavailable as failure:
            raise EmitterError(str(failure)) from failure
```

Import the module, not the name — a `from ... import require_kernel` binds the function at import time and the test's monkeypatch would stop reaching it, leaving a test that passes vacuously.

In `StepEmitter.emit`, the write becomes:

```python
                write_step(
                    document,
                    target,
                    title=self.options.title or "stompdrill",
                    timestamp=model.document_timestamp,
                    originating_system=_ORIGINATING_SYSTEM,
                    replaced_labels=touched,
                )
```

The `or "stompdrill"` moves here from inside the writer — same bytes, named by the tool that owns the name.

In `cut_shape`, `_cut_component` and `_label_entry`'s former callers, use the imported `label_entry` and `label_name`. Everything else in `cut_shape`, `_cut_component`, `_cut_leaf`, `_drill_compound` and `_face_point` is unchanged, except that `_drill_compound` and `_face_point` now reach through the basis:

```python
    direction = tuple(-component for component in model.frame.basis.w)
```

```python
def _face_point(model: Any, hole: Any, overshoot: float) -> tuple[float, float, float]:
    """The cylinder's start, ``overshoot`` mm outside the drilled face."""
    frame = model.frame.basis
    x, y, z = frame.to_model(hole.x_nm, hole.y_nm)
    return tuple(
        float(value) + overshoot * frame.w[i]
        for i, value in enumerate((x, y, z))
    )
```

This is the second copy of `origin + x*u + y*v` retired: the arithmetic is the value's, and only the overshoot along `w` remains here.

- [ ] **Step 4: Run the suite to verify it passes**

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond --tb=short
```

Expected: all pass, and every STEP artefact byte-identical.

- [ ] **Step 5: Prove byte identity explicitly**

Before this task's first commit, stash a reference artefact from `main`; now compare:

```bash
python tools/fetch_case_model.py 1590BB
git stash list  # the reference produced from main, if you kept one
.venv/bin/python -m stompdrill.cli packages/stompdrill/tests/fixtures/tar.ai --case 1590B \
  --case-model ~/.cache/stompcad/cases/1590BB.stp --emit step=/tmp/after.stp
cmp /tmp/before.stp /tmp/after.stp && echo "BYTE IDENTICAL"
```

Expected: `BYTE IDENTICAL`. If you did not capture `/tmp/before.stp` from `main` first, do it now with `git stash` / `git worktree`-free checkout of the base commit — this is the plan's governing test and it is not optional.

- [ ] **Step 6: Commit**

```bash
git add packages/stompdrill
git commit -m "Cut through the shared writer, and name ourselves in the header

The emitter keeps what decides where a hole goes and hands the rest to
stompgeom. _face_point loses its copy of origin + x*u + y*v -- the value owns
that arithmetic now, and only the overshoot along w is the cutter's."
```

---

### Task 8: Make the kernel unconditional

`stompgeom` takes the kernel unconditionally, so `stompdrill` does too. The extra retires, and with it thirteen skips that could no longer fire.

**Files:**
- Modify: `packages/stompdrill/pyproject.toml` (delete `[project.optional-dependencies]`)
- Modify: `packages/stompdrill/tests/test_acceptance.py`, `test_cad_case_synthetic.py`, `test_cad_region_synthetic.py`, `test_cad_case.py`, `test_cad_region.py`, `test_cli.py`, `test_layer2_owned.py`, `test_layer3_codecs.py`

- [ ] **Step 1: Delete the skips**

Remove every `pytest.importorskip("OCP", reason="needs stompdrill[step]")` line. Do not replace them with anything.

Rationale to keep in the commit message, not in the files: once the kernel is a hard dependency these can never fire, and if OCP ever *did* fail to import they would skip silently rather than fail — a gate that suppresses the rule it claims to check is not evidence.

Leave the `--hammond` opt-in exactly as it is. It governs downloading real Hammond models, which is a separate concern from whether the kernel is installed.

- [ ] **Step 2: Retire the extra**

In `packages/stompdrill/pyproject.toml`, delete:

```toml
[project.optional-dependencies]
step = ["cadquery-ocp==7.9.3.1.1"]
```

The pin now lives once, in `stompgeom`'s `dependencies`.

- [ ] **Step 3: Run both suites and the gates**

```bash
uv sync --all-packages
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
cd packages/stompgeom && uv run --no-sync pytest -o addopts= -q
ruff check packages tools
mypy packages
```

Expected: all clean. Note that `uv sync --all-packages` without `--all-extras` now installs the kernel, because it is an ordinary dependency — that is the change, and it is what makes the skips dead.

- [ ] **Step 4: Commit**

```bash
git add packages/stompdrill
git commit -m "Retire the optional kernel, and the skips that could not fire

ADR-0007 argued for the extra on the premise that stompdrill stood alone.
stompgeom takes the kernel unconditionally, so that premise is gone.

The importorskips go with it. They could never fire again, and worse: had
OCP ever failed to import they would have skipped silently rather than
failed, which is the shape of evidence that proves nothing."
```

---

### Task 9: Documentation and ADR amendments

The facts this plan changed, and nothing more. A wider `CLAUDE.md` audit is separate work and is deliberately not here.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/adr/0007-case-model-and-clearance.md`
- Modify: `docs/adr/0008-workspace-and-shared-geometry-core.md`
- Modify: `docs/adr/0009-shared-model-package-and-dependency-order.md`
- Modify: `docs/GLOSSARY.md`
- Modify: `docs/specs/stompcollider-technical.md` (tick plan 2 off)

- [ ] **Step 1: Update `CLAUDE.md`'s facts**

Change only what this plan made wrong:

- The workspace is now three packages, not two.
- Delete the `stompdrill[step]` paragraph and the `--all-extras` guidance; `uv sync --all-packages` is now the whole story and installs the kernel.
- Add `stompgeom`'s own commands beside the other members': its `pytest`, its `mypy`, its `mutmut run`.
- Delete the clause saying kernel-backed tests skip when the extra is absent.
- Note that a third `tests` package is why the root `mypy` gate still cannot cover every member.

**Record no counts.** Name commands, never their output.

- [ ] **Step 2: Amend the ADRs**

**ADR-0009** — in the `stompgeom` section, move `CoordinateFrame` and `FaceFrame` to `stompmodel`'s list, and add the reasoning: the value is kernel-free while the operation that builds one is not, and the drill document could not otherwise carry the frame without the leaf importing the package above it. Note that this is what unblocks the face-frame member in plan 3.

**ADR-0007** — mark the optional `stompdrill[step]` extra retired, naming this plan. Its argument assumed `stompdrill` stood alone.

**ADR-0008** — add a line to its status noting that lengths and frames both settled in `stompmodel`, so its "shared geometry core" is the kernel layer it became.

- [ ] **Step 3: Update the glossary**

`docs/GLOSSARY.md` says `CoordinateFrame` and `FaceFrame` are "in `stompgeom`". Both are now in `stompmodel`. The `stompgeom` entry itself stays accurate — the kernel layer, the STEP reader and writer — but drop "coordinate frames" from its list.

- [ ] **Step 4: Tick plan 2 off**

In `docs/specs/stompcollider-technical.md`'s "Order of work" table, change plan 2's "Done when" cell to `done — <commit sha>`.

- [ ] **Step 5: Verify every claim you kept**

```bash
grep -n "stompdrill\[step\]\|--all-extras" CLAUDE.md   # expect no hits
grep -c "docs/adr/" CLAUDE.md                          # every ADR mention links
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
```

Run every command CLAUDE.md now names, and confirm it works as written.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "Amend the ADRs the extraction changed, and the facts in CLAUDE.md

ADR-0009 placed the frame types in stompgeom while also having the drill
document carry one and keeping DrillData in a leaf that declares no
dependencies. Those cannot all hold; the frame value settles in the leaf.

ADR-0007's extra retires with it. A stale ADR is misinformation, so each
amendment lands with the work rather than after it."
```

---

## Self-Review

**Spec coverage.** Decision 1 → Tasks 1 and 2. Decision 2 → Task 2. Decision 3 → Task 1 (methods), Tasks 6 and 7 (call sites, both duplicates retired). Decision 4 → Tasks 3, 4, 5. Decision 5 → Tasks 5 and 7. Decision 6 → Tasks 3 and 8. Decision 7 → Task 9. "What does not move" → enforced by Task 6 leaving `CaseModel`, `Rejection`, `region.py`'s play-area reasoning and `Micron` untouched. Verification items 1–6 → Task 3 Step 5 (installs alone), Task 7 Step 5 (byte identity), Task 3 (new gate), Task 2 (leaf gate corrected), Task 9 Step 5 (no counts).

**Type consistency.** `FaceFrame.basis` is the field name in Tasks 2, 6 and 7. `write_step`'s keyword names — `title`, `timestamp`, `originating_system`, `replaced_labels` — match between Task 5's definition and Task 7's call. `label_entry` and `label_name` are public in Task 5 and imported under those names in Task 7. `to_model` returns `Millimetre` in Task 1 and is unwrapped with `float()` in Task 7.

**Known gap, deliberately left.** Task 7 Step 5 depends on a reference artefact captured from the base commit before the work starts. Capture `/tmp/before.stp` as the very first action of this plan, before Task 1.
