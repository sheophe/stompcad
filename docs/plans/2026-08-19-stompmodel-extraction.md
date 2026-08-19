# stompmodel Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `stompmodel` out of `stompdrill` as a standalone, kernel-free
distribution holding the values every package in the workspace exchanges.

**Architecture:** The repository becomes a uv workspace of packages under
`packages/`. `stompmodel` takes the branded lengths, `DrillData` and its
members, diagnostics, the JSON codec in both directions, and the generic
pipeline contracts. `stompdrill` keeps everything else and gains a dependency
on `stompmodel`. Nothing observable changes: the same 1342 tests pass and every
emitted artefact is byte-for-byte what it was.

**Tech Stack:** Python ≥3.10, uv workspaces, setuptools, pytest, ruff, mypy.

**Spec:** `docs/specs/stompcollider-technical.md` — this is **plan 1 of 3** from
its "Order of work". Governed by
`docs/adr/0009-shared-model-package-and-dependency-order.md` and
`docs/adr/0008-workspace-and-shared-geometry-core.md`.

## Global Constraints

- **Nothing observable changes.** Every emitted artefact must be byte-identical
  to its pre-migration bytes. Task 1 builds the instrument that proves it; every
  later task runs it.
- **No re-exports for compatibility.** One name, one home. A moved symbol is
  imported from `stompmodel`; `stompdrill` does not alias it back. (ADR-0009)
- **Two admission rules for `stompmodel`, and nothing else gets in.** A type
  crosses a package boundary and neither package owns it; or it is a contract
  both tools must implement identically for `stompcad` to treat them uniformly.
  (ADR-0009)
- **`stompmodel` is pure Python.** No kernel, no parser, no I/O beyond
  serialisation. Its only third-party dependency is none.
- **`stompmodel` installs and tests alone.** `cd packages/stompmodel && uv sync
  && pytest` must pass in a clean environment, and nothing under its `tests/`
  may import `stompdrill`. (ADR-0008)
- **Keep SOLID and DRY in mind, as guidance rather than ceremony.** Use them to
  remove duplication and sharpen a boundary; never to add an interface nobody
  needs or a layer with one implementation. (CLAUDE.md, Design rules)
- **British spelling in prose, established American spelling in identifiers.**
- **`from __future__ import annotations` and an explicit, logically ordered
  `__all__` in every module.** Value objects are frozen, slotted dataclasses
  whose transforms return replacements.
- **Docstrings are at most ten physical lines** and explain why the code is
  shaped this way, never how it got that way.
- Exact test count before this plan: **1342 passing** under
  `pytest --hammond`, **1249 passing / 93 skipped** without it.

---

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` (rewritten) | virtual uv workspace root; shared ruff and mypy config |
| `packages/stompmodel/pyproject.toml` | the distribution; no runtime dependencies |
| `packages/stompmodel/src/stompmodel/units.py` | `Nanometre`, `Millimetre`, conversions |
| `packages/stompmodel/src/stompmodel/errors.py` | `StompError`, `EmitterError` |
| `packages/stompmodel/src/stompmodel/diagnostics.py` | `Severity`, `Diagnostic` |
| `packages/stompmodel/src/stompmodel/model.py` | `DrillData` and its members |
| `packages/stompmodel/src/stompmodel/codec.py` | `to_document`, `from_document` |
| `packages/stompmodel/src/stompmodel/protocols.py` | `Stage`, `Pipeline`, `Emitter`, `Payload`, `Processable` |
| `packages/stompmodel/tests/` | its own suite, importing no `stompdrill` |
| `packages/stompdrill/pyproject.toml` | the distribution; depends on `stompmodel` |
| `tools/artefacts.py` | emit every format from one fixture, for byte comparison |

**Moved wholesale:** `src/stompdrill/` → `packages/stompdrill/src/stompdrill/`;
`tests/` → `packages/stompdrill/tests/`.

**Deleted:** `src/stompdrill/model.py` (Task 6). `RawDrillData` moves to
`quantise.py`, which is the only module that consumes it.

---

### Task 1: The workspace, and the instrument that proves nothing changed

Relocates the existing tree and builds the byte-comparison harness every later
task depends on. No symbol moves yet.

**Files:**
- Create: `tools/artefacts.py`
- Create: `packages/stompdrill/pyproject.toml`
- Rewrite: `pyproject.toml`
- Move: `src/stompdrill/` → `packages/stompdrill/src/stompdrill/`
- Move: `tests/` → `packages/stompdrill/tests/`

**Interfaces:**
- Consumes: nothing.
- Produces: `tools/artefacts.py` with
  `write_all(out_dir: Path, case_model: Path | None = None) -> list[Path]`,
  invoked as `python tools/artefacts.py OUT_DIR [CASE_MODEL]`. Later tasks run
  it against a baseline worktree and against `HEAD` and diff the directories.

- [ ] **Step 1: Record the baseline commit**

```bash
git rev-parse HEAD > /tmp/stompmodel-baseline
cat /tmp/stompmodel-baseline    # expect f8740eb… or later; this is the "before"
```

- [ ] **Step 2: Write the artefact harness**

Create `tools/artefacts.py`:

```python
"""Emit every format from one fixture, so a refactor can be proved inert.

Not a test: a migration instrument. Run it on the pre-migration tree and on
the working tree, then diff the two directories. Any difference is a
behaviour change, which this plan forbids. The STEP artefact needs a cached
case model and is skipped when one is not supplied.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["write_all"]

#: Formats that need only the artwork.
_PLAIN = ("json", "excellon", "drawing-svg", "drawing-pdf")


def write_all(out_dir: Path, panel: Path, case_model: Path | None = None) -> list[Path]:
    """Emit every format into ``out_dir`` and return the files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    emits = [f"--emit={name}={out_dir / name}.out" for name in _PLAIN]
    argv = [sys.executable, "-m", "stompdrill.cli", str(panel), "--case", "1590B", *emits]
    if case_model is not None:
        argv += ["--case-model", str(case_model), f"--emit=step={out_dir / 'step'}.out"]
    # Exit 1 is expected: the fixture carries a duplicate-hole warning.
    result = subprocess.run(argv, capture_output=True)
    if result.returncode not in (0, 1):
        raise SystemExit(f"emit failed ({result.returncode}): {result.stderr.decode()}")
    return sorted(out_dir.glob("*.out"))


if __name__ == "__main__":
    out = Path(sys.argv[1])
    panel = Path(sys.argv[2])
    model = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    for written in write_all(out, panel, model):
        print(written)
```

- [ ] **Step 3: Capture the baseline artefacts, before moving anything**

```bash
PYTHONPATH=src .venv/bin/python tools/artefacts.py /tmp/baseline-artefacts \
  tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
ls -la /tmp/baseline-artefacts     # expect 5 files: json, excellon,
                                   # drawing-svg, drawing-pdf, step
```

Expected: five `.out` files. If `~/.cache/stompcad/cases/1590B.stp` is absent,
run `python tools/fetch_case_model.py 1590B` first.

- [ ] **Step 4: Move the tree**

```bash
mkdir -p packages/stompdrill
git mv src packages/stompdrill/src
git mv tests packages/stompdrill/tests
```

- [ ] **Step 5: Write the member pyproject**

Create `packages/stompdrill/pyproject.toml`:

```toml
[project]
name = "stompdrill"
version = "0.1.0"
description = "Extract drill data from Adobe Illustrator artwork and emit it in fabrication formats"
requires-python = ">=3.10"
dependencies = ["pikepdf>=9"]

[project.optional-dependencies]
step = ["cadquery-ocp==7.9.3.1.1"]

[project.scripts]
stompdrill = "stompdrill.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

# Its own testpaths, so `cd packages/stompdrill && pytest` is correct and does
# not inherit a root testpaths pointing at a sibling package.
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
markers = ["hammond: needs a real Hammond STEP model; run with --hammond"]
```

- [ ] **Step 6: Rewrite the root pyproject as a virtual workspace**

Replace the `[project]`, `[project.optional-dependencies]`, `[project.scripts]`,
`[build-system]` and `[tool.setuptools.packages.find]` tables with the workspace
declaration below. **Keep every existing `[tool.ruff]`, `[tool.ruff.lint]`,
`[tool.mypy]` and `[tool.uv]` table exactly as it is** — they are shared, and
their comments record decisions this plan must not undo.

```toml
# A virtual workspace root: it declares no distribution of its own, so
# `uv sync` here installs every member and `pip install` of any one member
# still works in a clean environment. That second property is ADR-0008's
# governing test, which is why the packages are distributions and not
# directories.
[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["pytest", "pytest-cov", "hypothesis", "ruff", "mypy", "mutmut"]

# Whole-workspace run. Each member also declares its own testpaths, so the
# per-package run stays honest; these two are separate processes on purpose,
# because two `tests` packages cannot share one interpreter.
[tool.pytest.ini_options]
testpaths = ["packages/stompdrill/tests"]
addopts = "-q"
markers = ["hammond: needs a real Hammond STEP model; run with --hammond"]
```

- [ ] **Step 7: Reinstall and run the suite**

```bash
rm -rf .venv && uv venv && uv sync --all-packages --all-extras
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond --tb=short -q
```

Expected: `1342 passed`. No `PYTHONPATH=src` — the workspace install puts
`stompdrill` on the path.

- [ ] **Step 8: Prove the artefacts did not move**

```bash
.venv/bin/python tools/artefacts.py /tmp/after-move \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-move && echo "IDENTICAL"
```

Expected: `IDENTICAL`. A difference here means the move changed behaviour, which
must be fixed before proceeding — do not continue with a known difference.

- [ ] **Step 9: Prove the member installs alone**

```bash
uv venv /tmp/alone-drill
VIRTUAL_ENV=/tmp/alone-drill uv pip install ./packages/stompdrill
/tmp/alone-drill/bin/python -c "import stompdrill; print(stompdrill.__file__)"
```

Expected: a path under `/tmp/alone-drill`. This is ADR-0008's governing test and
every later task keeps it passing.

- [ ] **Step 10: Update CLAUDE.md's development commands**

In the `## Development commands` section, replace each `PYTHONPATH=src pytest …`
invocation with the workspace form. The full-suite line becomes:

```bash
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --tb=short
```

and the environment setup becomes:

```bash
uv venv
uv sync --all-packages --all-extras
source .venv/bin/activate
```

Also change `--cov=stompdrill` to `--cov=stompdrill --cov=stompmodel`, and
`mypy src/stompdrill tests` to `mypy packages`.

- [ ] **Step 11: Run lint and types**

```bash
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
```

Expected: both clean.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Make the repository a workspace of packages

Relocates stompdrill under packages/ and makes the root a virtual uv
workspace, so a member installs alone in a clean environment -- ADR-0008's
governing test, which a boundary asserted in prose cannot pass.

Adds tools/artefacts.py, the instrument the extraction is measured by: emit
every format before and after, diff the directories, and any difference is a
behaviour change this migration forbids."
```

---

### Task 2: `stompmodel` with the branded lengths

**Files:**
- Create: `packages/stompmodel/pyproject.toml`
- Create: `packages/stompmodel/src/stompmodel/__init__.py`
- Create: `packages/stompmodel/src/stompmodel/units.py`
- Create: `packages/stompmodel/tests/__init__.py`
- Move: `packages/stompdrill/tests/test_units.py` → `packages/stompmodel/tests/test_units.py`
- Create: `packages/stompdrill/tests/test_units_drill.py`
- Modify: `packages/stompdrill/src/stompdrill/units.py`
- Modify: `packages/stompdrill/pyproject.toml`

**Interfaces:**
- Consumes: the workspace layout from Task 1.
- Produces: `stompmodel.units` exporting `Nanometre`, `Millimetre`, `NM_PER_MM`,
  `nm_from_mm(mm: float) -> Nanometre`, `mm_from_nm(nm: Nanometre) -> Millimetre`,
  `scaled_nm(mm: float) -> Decimal`, `format_nm(nm: Nanometre, decimals: int = 3) -> str`.
  `stompdrill.units` keeps `Micron`, `NM_PER_MICRON`,
  `nm_from_micron(microns: Micron) -> Nanometre`, `mm_from_pt(points: float) -> Millimetre`.

- [ ] **Step 1: Write the distribution**

Create `packages/stompmodel/pyproject.toml`:

```toml
[project]
name = "stompmodel"
version = "0.1.0"
description = "The values every stomp package exchanges: lengths, drill data, diagnostics, contracts"
requires-python = ">=3.10"
# Deliberately none. This package is the workspace's pure-Python leaf; a
# dependency here would be inherited by everything.
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write the failing test**

Create `packages/stompmodel/tests/__init__.py` (empty), then move the existing
units tests and repoint their import:

```bash
git mv packages/stompdrill/tests/test_units.py packages/stompmodel/tests/test_units.py
```

In `packages/stompmodel/tests/test_units.py`, change the import line

```python
from stompdrill.units import NM_PER_MM, Nanometre, format_nm, mm_from_nm, mm_from_pt, nm_from_mm, scaled_nm
```

to

```python
from stompmodel.units import NM_PER_MM, Nanometre, format_nm, mm_from_nm, nm_from_mm, scaled_nm
```

`mm_from_pt` is gone from that import because it stays in `stompdrill` — PDF
user space is a parser concern, not a unit. Delete the three assertions that
use it (they are in one test method) and recreate them in Step 3.

- [ ] **Step 3: Give the PDF conversion a home in stompdrill's own suite**

Create `packages/stompdrill/tests/test_units_drill.py`:

```python
"""The unit conversions that stay in stompdrill: the grid pitch and PDF points."""

from __future__ import annotations

from stompdrill.units import NM_PER_MICRON, Micron, mm_from_pt, nm_from_micron


def test_one_inch_of_pdf_user_space_is_25_4_millimetres():
    assert mm_from_pt(72.0) == 25.4


def test_a_single_point_keeps_full_float_precision():
    assert mm_from_pt(1.0) == 25.4 / 72.0
    assert type(mm_from_pt(1.0)) is float


def test_a_grid_pitch_widens_to_the_canonical_unit():
    assert nm_from_micron(Micron(250)) == 250 * NM_PER_MICRON
    assert nm_from_micron(Micron(250)) == 250_000
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_units.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'stompmodel'`.

- [ ] **Step 5: Write `stompmodel.units`**

Create `packages/stompmodel/src/stompmodel/units.py` with everything below,
copied from `packages/stompdrill/src/stompdrill/units.py` — the bodies are
unchanged, only the module docstring and `__all__` narrow:

```python
"""Branded length units and the conversions between them.

``Millimetre`` is what a measurement is; ``Nanometre`` is what a model holds.
Arithmetic drops the brand, so a scaled value is re-wrapped at the point it
becomes a length again. Millimetre conversions use ``Decimal(str(value))``
and half-up rounding. See ADR-0004.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NewType

__all__ = [
    "Nanometre",
    "Millimetre",
    "NM_PER_MM",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]

#: The canonical model unit. Every nominal length is one of these.
Nanometre = NewType("Nanometre", int)

#: An unquantised measurement, as a source reports it.
Millimetre = NewType("Millimetre", float)

#: Whole nanometres in one millimetre.
NM_PER_MM: int = 1_000_000

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, with ties away from zero."""
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def nm_from_mm(mm: float) -> Nanometre:
    """Convert millimetres to whole nanometres, with ties away from zero."""
    return Nanometre(int(_round_half_up(Decimal(str(mm)) * NM_PER_MM)))


def scaled_nm(mm: float) -> Decimal:
    """Scale a measurement exactly without selecting a nanometre.

    Quantisers compare this value directly with their answer sets so a
    preliminary rounding cannot manufacture a midpoint tie. See ADR-0003.
    """
    return Decimal(str(mm)) * NM_PER_MM


def mm_from_nm(nm: Nanometre) -> Millimetre:
    """Convert whole nanometres to a millimetre value."""
    return Millimetre(nm / NM_PER_MM)


def format_nm(nm: Nanometre, decimals: int = 3) -> str:
    """Format whole nanometres as millimetres, normalising negative zero."""
    value = _round_half_up(Decimal(nm) / NM_PER_MM, Decimal(1).scaleb(-decimals))
    if value == 0:
        value = abs(value)
    return str(value)
```

Create `packages/stompmodel/src/stompmodel/__init__.py`:

```python
"""The values every stomp package exchanges.

Pure Python by construction: no kernel, no parser, no I/O beyond
serialisation. What lives here either crosses a package boundary with no
owner, or is a contract both tools implement identically. See ADR-0009.
"""

from __future__ import annotations

from .units import (
    NM_PER_MM,
    Millimetre,
    Nanometre,
    format_nm,
    mm_from_nm,
    nm_from_mm,
    scaled_nm,
)

__all__ = [
    "Nanometre",
    "Millimetre",
    "NM_PER_MM",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]
```

- [ ] **Step 6: Narrow stompdrill's units to what stays**

Replace `packages/stompdrill/src/stompdrill/units.py` entirely with:

```python
"""The unit concerns that are stompdrill's own.

``Micron`` is the grid pitch and nothing else — a statement about this
package's quantisation policy, not about length, which is why it did not
travel to ``stompmodel`` with the lengths. ``mm_from_pt`` converts PDF user
space and belongs beside the parser that reads it. See ADR-0009.
"""

from __future__ import annotations

from typing import NewType

from stompmodel.units import Millimetre, Nanometre

__all__ = [
    "Micron",
    "NM_PER_MICRON",
    "nm_from_micron",
    "mm_from_pt",
]

#: The grid pitch, which is a whole number of microns and never finer.
Micron = NewType("Micron", int)

#: Whole nanometres in one micron.
NM_PER_MICRON: int = 1_000

#: PDF user space is 1/72 inch; one inch is exactly 25.4 millimetres.
_MM_PER_INCH: float = 25.4
_PT_PER_INCH: int = 72


def mm_from_pt(points: float) -> Millimetre:
    """Convert PDF user-space points to an unquantised millimetre measurement."""
    return Millimetre(points * _MM_PER_INCH / _PT_PER_INCH)


def nm_from_micron(microns: Micron) -> Nanometre:
    """Widen a grid pitch to the canonical unit."""
    return Nanometre(microns * NM_PER_MICRON)
```

- [ ] **Step 7: Declare the dependency**

In `packages/stompdrill/pyproject.toml`, change the dependencies line and add
the workspace source:

```toml
dependencies = ["stompmodel", "pikepdf>=9"]

[tool.uv.sources]
stompmodel = { workspace = true }
```

- [ ] **Step 8: Repoint every import of a moved symbol**

Across `packages/stompdrill/src` and `packages/stompdrill/tests`, any import of
`Nanometre`, `Millimetre`, `NM_PER_MM`, `nm_from_mm`, `mm_from_nm`, `scaled_nm`
or `format_nm` now comes from `stompmodel.units`. Imports of `Micron`,
`NM_PER_MICRON`, `nm_from_micron` or `mm_from_pt` stay on `stompdrill.units`. A
module needing both keeps two import statements — that is the dependency being
visible, not clutter.

Find every site:

```bash
grep -rn "from \.\.\?units import\|from stompdrill\.units import\|stompdrill\.units\." \
  packages/stompdrill/src packages/stompdrill/tests
```

- [ ] **Step 9: Reinstall and run both suites**

```bash
uv sync --all-packages --all-extras
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
```

Expected: `stompmodel` green; `stompdrill` `1342 passed` minus the units tests
that moved, plus the three new ones in `test_units_drill.py`. The two counts
must sum to at least 1342 — a test lost in the move is a regression.

- [ ] **Step 10: Prove stompmodel imports nothing from stompdrill**

```bash
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
```

Expected: `clean`. This grep is repeated at the end of every remaining task.

- [ ] **Step 11: Prove the artefacts still match**

```bash
.venv/bin/python tools/artefacts.py /tmp/after-units \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-units && echo "IDENTICAL"
```

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Move the branded lengths into stompmodel

Nanometre and Millimetre are units, not geometry, and are the most widely
shared definition in the workspace, so they sit in the pure-Python leaf.

Micron stays: its definition is 'the grid pitch, a whole number of microns
and never finer', which is a statement about stompdrill's quantisation
policy rather than about length. mm_from_pt stays for the same reason --
PDF user space is a parser's concern."
```

---

### Task 3: The shared error base

**Files:**
- Create: `packages/stompmodel/src/stompmodel/errors.py`
- Create: `packages/stompmodel/tests/test_errors.py`
- Modify: `packages/stompdrill/src/stompdrill/errors.py`
- Modify: `packages/stompdrill/src/stompdrill/cli.py`

**Interfaces:**
- Consumes: `stompmodel.units` from Task 2.
- Produces: `stompmodel.errors` exporting `StompError` (base for every error any
  package raises) and `EmitterError(StompError)`. `stompdrill.errors` keeps
  `StompdrillError(StompError)`, `SourceError`, `LayerNotFoundError`,
  `EmptyLayerError` and no longer defines `EmitterError`.

Why the base moves: `DrillData.numbered()` raises `EmitterError` and `DrillData`
is about to live in `stompmodel`, so the exception must too. `stompcollider`
will raise emitter failures of its own, and one base means `stompcad` catches
one type rather than one per tool — the second admission rule, met squarely.

- [ ] **Step 1: Write the failing test**

Create `packages/stompmodel/tests/test_errors.py`:

```python
"""The workspace's error base, and what must remain true of it."""

from __future__ import annotations

import pytest

from stompmodel.errors import EmitterError, StompError


def test_an_emitter_error_is_a_stomp_error():
    assert issubclass(EmitterError, StompError)


def test_a_stomp_error_is_an_ordinary_exception():
    assert issubclass(StompError, Exception)


def test_the_base_carries_its_message():
    with pytest.raises(StompError, match="no drill number"):
        raise StompError("no drill number")
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_errors.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'stompmodel.errors'`.

- [ ] **Step 3: Write the module**

Create `packages/stompmodel/src/stompmodel/errors.py`:

```python
"""The error base every stomp package raises through.

One base, so a caller composing two tools catches one type rather than one
per tool. ``EmitterError`` lives here because ``DrillData.numbered()``
raises it and every package that emits an artefact can fail the same way.
See ADR-0009.
"""

from __future__ import annotations

__all__ = ["StompError", "EmitterError"]


class StompError(Exception):
    """Base for every error raised by a stomp package."""


class EmitterError(StompError):
    """An emitter could not produce output from the data it was given."""
```

- [ ] **Step 4: Run it to verify it passes**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_errors.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Rebase stompdrill's hierarchy**

In `packages/stompdrill/src/stompdrill/errors.py`, remove the `EmitterError`
class, import `StompError`, and make `StompdrillError` derive from it:

```python
from stompmodel.errors import StompError

__all__ = [
    "StompdrillError",
    "SourceError",
    "LayerNotFoundError",
    "EmptyLayerError",
]


class StompdrillError(StompError):
    """Base for every error raised by stompdrill alone."""
```

Leave `SourceError`, `LayerNotFoundError`, `EmptyLayerError` and
`_empty_layer_message` exactly as they are.

- [ ] **Step 6: Widen the CLI's top-level handler**

`packages/stompdrill/src/stompdrill/cli.py` catches `StompdrillError` in two
places (around lines 312 and 769). `EmitterError` is no longer one of those, so
the outer handler at line 769 must catch `StompError` instead — otherwise an
emitter failure escapes as a traceback rather than exit 3.

Change the import at line 30 to bring in both, and the outer handler:

```python
from stompmodel.errors import StompError

    except (UsageError, StompError, OSError) as failure:
```

Leave the inner handler at line 312 catching `StompdrillError`: it guards
source reading, where an emitter error cannot arise.

- [ ] **Step 7: Repoint every `EmitterError` import**

```bash
grep -rln "EmitterError" packages/stompdrill/src packages/stompdrill/tests
```

Each becomes `from stompmodel.errors import EmitterError`.

- [ ] **Step 8: Run both suites, the leak check, and the artefact diff**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
.venv/bin/python tools/artefacts.py /tmp/after-errors \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-errors && echo "IDENTICAL"
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Give the workspace one error base

DrillData.numbered() raises EmitterError and DrillData is about to live in
stompmodel, so the exception goes with it. StompError is the base every
package raises through, which is what lets stompcad catch one type rather
than one per tool.

The CLI's outer handler widens to StompError: EmitterError is no longer a
StompdrillError, and without the widening an emitter failure would escape
as a traceback instead of exit 3."
```

---

### Task 4: Diagnostics

**Files:**
- Create: `packages/stompmodel/src/stompmodel/diagnostics.py`
- Move: the `Severity`, `Diagnostic` and payload-check tests out of
  `packages/stompdrill/tests/test_model.py` into
  `packages/stompmodel/tests/test_diagnostics.py`
- Modify: `packages/stompdrill/src/stompdrill/model.py`
- Modify: `packages/stompdrill/src/stompdrill/cli.py:66-78`

**Interfaces:**
- Consumes: `stompmodel.units` (Task 2).
- Produces: `stompmodel.diagnostics` exporting `Severity` (an `Enum` ordered
  `INFO < WARNING < ERROR`, total-ordered), `Diagnostic` (frozen slotted
  dataclass with `severity`, `code`, `message`, `location_nm`, `data`),
  `ParameterValue = float | int | str | bool | tuple[float, ...]`, the exit
  codes `EXIT_CLEAN = 0`, `EXIT_WARNINGS = 1`, `EXIT_ERRORS = 2`,
  `EXIT_USAGE = 3`, the reduction
  `exit_for_severity(worst: Severity | None) -> int`, and the module-private
  `_check_payload_lengths` helper it shares with `StageRun`.

Diagnostics move ahead of `DrillData` so that `stompcollider` can raise findings
without importing drill data at all — the two are independent, and keeping them
in one module would couple a docking diagnostic to a hole.

- [ ] **Step 1: Write the failing test**

Create `packages/stompmodel/tests/test_diagnostics.py`. Copy every test from
`packages/stompdrill/tests/test_model.py` whose subject is `Severity` or
`Diagnostic`, repointing their imports to `stompmodel.diagnostics`. Find them
with:

```bash
grep -n "Severity\|Diagnostic" packages/stompdrill/tests/test_model.py
```

Add these, which are new. The first two pin the ordering the reduction relies
on; the rest pin the reduction itself, which has never had a test of its own
because it lived inside the CLI:

```python
def test_severity_orders_info_below_warning_below_error():
    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert max((Severity.INFO, Severity.ERROR, Severity.WARNING)) is Severity.ERROR


def test_comparing_a_severity_with_a_non_severity_is_not_implemented():
    assert Severity.INFO.__lt__(1) is NotImplemented


def test_no_finding_and_an_informational_finding_both_exit_clean():
    assert exit_for_severity(None) == EXIT_CLEAN == 0
    assert exit_for_severity(Severity.INFO) == EXIT_CLEAN


def test_a_warning_exits_one_and_an_error_exits_two():
    assert exit_for_severity(Severity.WARNING) == EXIT_WARNINGS == 1
    assert exit_for_severity(Severity.ERROR) == EXIT_ERRORS == 2


def test_every_severity_has_an_exit_code():
    for severity in Severity:
        assert exit_for_severity(severity) in (EXIT_CLEAN, EXIT_WARNINGS, EXIT_ERRORS)
```

Import them at the top of the module:

```python
from stompmodel.diagnostics import (
    EXIT_CLEAN,
    EXIT_ERRORS,
    EXIT_WARNINGS,
    Diagnostic,
    Severity,
    exit_for_severity,
)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_diagnostics.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'stompmodel.diagnostics'`.

- [ ] **Step 3: Write the module**

Create `packages/stompmodel/src/stompmodel/diagnostics.py`, moving `Severity`,
`ParameterValue`, `Diagnostic`, `_tupled` and `_check_payload_lengths` from
`packages/stompdrill/src/stompdrill/model.py` **unchanged in body**. The module
docstring:

```python
"""Findings, and how much they should worry the operator.

Separate from the drill data on purpose: a docking finding and a drilling
finding are the same kind of thing, and stompcollider must be able to raise
one without importing a hole. See ADR-0009.
"""
```

`_check_payload_lengths` moves with them because `Diagnostic.data` is its first
caller. `StageRun` (Task 5) is its second and will import it from here — one
copy, one home.

Then add the exit-code reduction, moved from `cli.py:66-78`, keeping its
comment:

```python
#: The workspace's exit-code contract. Shared, because stompcad reduces
#: findings from more than one tool to a single status and a second copy of
#: this table is a second chance to disagree about what a warning is.
EXIT_CLEAN = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_USAGE = 3

_EXIT_FOR_SEVERITY: dict[Severity | None, int] = {
    None: EXIT_CLEAN,
    Severity.INFO: EXIT_CLEAN,
    Severity.WARNING: EXIT_WARNINGS,
    Severity.ERROR: EXIT_ERRORS,
}


def exit_for_severity(worst: Severity | None) -> int:
    """The exit status a run reporting ``worst`` should end with.

    Derived from the worst finding rather than recounted, so the report and
    the status cannot disagree. ``None`` means no finding at all.
    """
    return _EXIT_FOR_SEVERITY[worst]
```

`EXIT_USAGE` moves with the others even though no severity maps to it: it is
one contract, and splitting three constants from a fourth would invite a second
definition of the one left behind.

- [ ] **Step 4: Run it to verify it passes**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_diagnostics.py -q
```

- [ ] **Step 5: Delete the moved code and repoint stompdrill**

Remove `Severity`, `ParameterValue`, `Diagnostic`, `_tupled` and
`_check_payload_lengths` from `packages/stompdrill/src/stompdrill/model.py`,
add `from stompmodel.diagnostics import Diagnostic, ParameterValue, Severity,
_check_payload_lengths`, and drop those four names from its `__all__`.

Then repoint every consumer:

```bash
grep -rln "Severity\|Diagnostic\|ParameterValue" packages/stompdrill/src packages/stompdrill/tests
```

In `packages/stompdrill/src/stompdrill/cli.py`, delete the four `EXIT_*`
constants and `_EXIT_FOR_SEVERITY` (lines 66-78), import them from
`stompmodel.diagnostics`, and replace the lookup at line 754:

```python
    return exit_for_severity(data.worst_severity)
```

Keep re-exporting the `EXIT_*` names from `cli.__all__` if they are listed
there — the CLI's own callers and `test_cli.py` read them from it, and that is
a module exposing the contract it obeys, not a compatibility alias.

- [ ] **Step 6: Run both suites, the leak check, and the artefact diff**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
.venv/bin/python tools/artefacts.py /tmp/after-diag \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-diag && echo "IDENTICAL"
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Move diagnostics into stompmodel

Two packages will raise findings independently and stompcad reduces both to
one report and one exit code, which is the second admission rule met
squarely: one Severity, one ordering, one place the exit mapping reads.

Their own module rather than travelling with DrillData, so stompcollider can
raise a docking finding without importing a hole."
```

---

### Task 5: `DrillData` and its members

The largest task. `stompdrill/model.py` is deleted at the end of it.

**Files:**
- Create: `packages/stompmodel/src/stompmodel/model.py`
- Move: `packages/stompdrill/tests/test_model.py` → `packages/stompmodel/tests/test_model.py`
- Create: `packages/stompdrill/tests/test_raw_drill_data.py`
- Modify: `packages/stompdrill/src/stompdrill/quantise.py`
- Delete: `packages/stompdrill/src/stompdrill/model.py`

**Interfaces:**
- Consumes: `stompmodel.units` (Task 2), `stompmodel.errors.EmitterError`
  (Task 3), `stompmodel.diagnostics` (Task 4).
- Produces: `stompmodel.model` exporting `Origin`, `RawHole`, `Hole`,
  `RawOutline`, `ReferenceOutline`, `EnclosureMatch`, `SourceInfo`, `StageRun`,
  `DrillData`. `stompdrill.quantise` gains `RawDrillData`, whose fields are
  `source: SourceInfo`, `reference: RawOutline | None`,
  `centre: tuple[Millimetre, Millimetre]`, `holes: tuple[RawHole, ...]`,
  `diagnostics: tuple[Diagnostic, ...] = ()`.

`RawHole` and `RawOutline` move even though they hold measurements, because
`Hole.raw` and `ReferenceOutline.raw` are their fields — provenance any producer
of a hole pattern carries. `RawDrillData` does not move: it is the
pre-canonical container that only `stompdrill`'s source and quantiser touch, and
`quantise.py` is its sole consumer.

- [ ] **Step 1: Move the test module and repoint it**

```bash
git mv packages/stompdrill/tests/test_model.py packages/stompmodel/tests/test_model.py
```

In it, change `from stompdrill.model import …` to `from stompmodel.model import
…`, and `from stompdrill.units import …` to `from stompmodel.units import …`.
Move the five tests that mention `RawDrillData` out to Step 2.

- [ ] **Step 2: Give `RawDrillData` a test module in stompdrill**

Create `packages/stompdrill/tests/test_raw_drill_data.py` holding the tests just
removed, importing `from stompdrill.quantise import RawDrillData` and
`from stompmodel.model import RawHole, RawOutline, SourceInfo`. Add this one,
which pins why it did not move:

```python
def test_raw_drill_data_rejects_a_non_finite_centre():
    with pytest.raises(ValueError, match="RawDrillData"):
        RawDrillData(
            source=SourceInfo(path="panel.ai", drill_layer="Drill"),
            reference=None,
            centre=(float("inf"), 0.0),
            holes=(),
        )
```

- [ ] **Step 3: Run both to verify they fail**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_model.py -q
.venv/bin/python -m pytest -o addopts= packages/stompdrill/tests/test_raw_drill_data.py -q
```

Expected: the first fails with `No module named 'stompmodel.model'`; the second
with `cannot import name 'RawDrillData' from 'stompdrill.quantise'`.

- [ ] **Step 4: Write `stompmodel.model`**

Create `packages/stompmodel/src/stompmodel/model.py` containing, **with bodies
unchanged**, everything currently in `packages/stompdrill/src/stompdrill/model.py`
except `RawDrillData`: `Origin`, `_check_nanometres`, `_check_millimetres`,
`RawHole`, `Hole`, `RawOutline`, `ReferenceOutline`, `EnclosureMatch`,
`SourceInfo`, `StageRun`, `DrillData`.

Its imports become:

```python
from stompmodel.diagnostics import Diagnostic, ParameterValue, _check_payload_lengths
from stompmodel.errors import EmitterError
from stompmodel.units import Millimetre, Nanometre, mm_from_nm, nm_from_mm
```

Module docstring:

```python
"""Immutable drill-data values with unit and frame invariants.

Nominal lengths are whole nanometres in a Y-up, outline-centred frame; raw
measurements are finite float millimetres. ``_nm`` payloads contain
integers. Here rather than in stompdrill because stompdrill produces this
and stompcollider consumes it, and neither owns it. See ADR-0009.
"""
```

`__all__`, in the order the values are defined:

```python
__all__ = [
    "Origin",
    "RawHole",
    "Hole",
    "RawOutline",
    "ReferenceOutline",
    "EnclosureMatch",
    "SourceInfo",
    "StageRun",
    "DrillData",
    "check_millimetres",
]
```

`check_millimetres` is public because Step 5 gives it a second caller in another
package. `_check_nanometres` stays private: one caller, one package.

- [ ] **Step 5: Move `RawDrillData` into the quantiser**

Add to `packages/stompdrill/src/stompdrill/quantise.py`, above the existing
`quantise` function:

```python
@dataclass(frozen=True, slots=True)
class RawDrillData:
    """A source result in unquantised millimetres.

    ``centre`` is the outline's page-space centre. Without one, coordinates
    stay page-relative, ``centre`` is ``(0.0, 0.0)``, and the frame is
    diagnosed. It lives beside the quantiser because the quantiser is its
    only consumer — it never crosses a package boundary.
    """

    source: SourceInfo
    reference: RawOutline | None
    centre: tuple[Millimetre, Millimetre]
    holes: tuple[RawHole, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Require both centre coordinates to be finite float millimetres."""
        x, y = self.centre
        _check_millimetres("RawDrillData", centre_x=x, centre_y=y)
```

`_check_millimetres` is currently module-private in `model.py`. Two callers now
live in different packages, so promote it: export it from
`stompmodel.model` as `check_millimetres` (no leading underscore, added to
`__all__`) and import it here. Do the same for `_check_nanometres` only if a
second caller exists — otherwise leave it private.

- [ ] **Step 6: Delete `stompdrill/model.py` and repoint every import**

```bash
git rm packages/stompdrill/src/stompdrill/model.py
grep -rn "from \.model import\|from \.\.model import\|stompdrill\.model" \
  packages/stompdrill/src packages/stompdrill/tests
```

Every one becomes `stompmodel.model`, except `RawDrillData`, which becomes
`from .quantise import RawDrillData` (or `from stompdrill.quantise import
RawDrillData` in tests). Update `packages/stompdrill/src/stompdrill/__init__.py`
so its `__all__` no longer re-exports moved names — ADR-0009 forbids
compatibility aliases.

- [ ] **Step 7: Run both suites, the leak check, and the artefact diff**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
.venv/bin/python tools/artefacts.py /tmp/after-model \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-model && echo "IDENTICAL"
```

Expected: both green, `clean`, `IDENTICAL`. The two suite counts must still sum
to 1342 or more.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Move DrillData and its members into stompmodel

stompdrill produces this and stompcollider consumes it, and neither owns it
-- the first admission rule. A narrower HolePattern was considered and
rejected in ADR-0009: it would have to carry the frame, the tool table, the
numbering and the enclosure identity anyway, and what it would add is a
second schema describing holes already described.

RawDrillData stays, and moves to quantise.py, which is its only consumer.
stompdrill/model.py is gone; one model in the workspace, and it is the
package."
```

---

### Task 6: The JSON codec, both directions

**Files:**
- Create: `packages/stompmodel/src/stompmodel/codec.py`
- Create: `packages/stompmodel/tests/test_codec.py`
- Modify: `packages/stompdrill/src/stompdrill/emitters/json_out.py`
- Modify: `packages/stompdrill/tests/test_json_emitter.py`

**Interfaces:**
- Consumes: `stompmodel.model` (Task 5), `stompmodel.diagnostics` (Task 4).
- Produces: `stompmodel.codec` exporting `FORMAT = "stompcad-drill-data"`,
  `VERSION = 5`, `to_document(data: DrillData) -> dict[str, Any]` and
  `from_document(document: Mapping[str, Any]) -> DrillData`.
  `stompdrill.emitters.json_out.JsonEmitter` keeps its registry entry, its
  `name`/`media_type`/`extension` and its `indent` option, and delegates.

The reader is new: `document()` was write-only, which is why `stompcollider`
would otherwise have had to write a second parser. One document, one codec, and
a round-trip property test — that is what "one JSON, and vice versa" buys.

- [ ] **Step 1: Write the failing test**

Create `packages/stompmodel/tests/test_codec.py`:

```python
"""The drill document, both directions."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from stompmodel.codec import FORMAT, VERSION, from_document, to_document
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.model import DrillData, Hole, RawOutline, ReferenceOutline, SourceInfo
from stompmodel.units import Millimetre, Nanometre

MM = 1_000_000


def _data() -> DrillData:
    """One fully-populated value. Holes are numbered out of tuple order, so a
    codec that recomputes a number from list position fails."""
    holes = (
        Hole.from_measurement(Nanometre(19 * MM), Nanometre(-18 * MM), Nanometre(5 * MM)).with_number(2),
        Hole.from_measurement(Nanometre(-19 * MM), Nanometre(-18 * MM), Nanometre(5 * MM)).with_number(1),
    )
    return DrillData(
        holes=holes,
        reference=ReferenceOutline(
            width_nm=Nanometre(112_400_000),
            height_nm=Nanometre(60_500_000),
            raw=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        ),
        diagnostics=(Diagnostic(Severity.WARNING, "duplicate-hole", "1 hole dropped"),),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )


def test_the_document_names_its_format_and_version():
    document = to_document(_data())

    assert document["format"] == FORMAT == "stompcad-drill-data"
    assert document["version"] == VERSION


def test_a_document_round_trips_back_to_an_equal_value():
    original = _data()

    assert from_document(to_document(original)) == original


def test_the_round_trip_preserves_a_number_that_is_not_the_list_position():
    restored = from_document(to_document(_data()))

    assert [hole.index for hole in restored.holes] == [2, 1]


@given(st.integers(min_value=-500_000_000, max_value=500_000_000))
def test_any_hole_position_survives_the_round_trip(x_nm):
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(x_nm), Nanometre(0), Nanometre(5 * MM)).with_number(1),),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )

    assert from_document(to_document(data)).holes[0].x_nm == x_nm
```

`hypothesis` is a dev dependency of the workspace; add it to
`packages/stompmodel/pyproject.toml` under a `[dependency-groups] dev` table if
the per-package run cannot see it.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_codec.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'stompmodel.codec'`.

- [ ] **Step 3: Write the codec**

Create `packages/stompmodel/src/stompmodel/codec.py`. Move `FORMAT`, `VERSION`
and every `_`-prefixed helper from
`packages/stompdrill/src/stompdrill/emitters/json_out.py` — `_source`,
`_reference`, `_hole`, `_listed`, `_diagnostic`, `_stage_run`, `_enclosure` —
**with bodies unchanged**, and rename `JsonEmitter.document` to a module-level
`to_document(data)`. Its imports:

```python
from collections.abc import Mapping
from typing import Any

from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.errors import EmitterError
from stompmodel.model import (
    DrillData,
    EnclosureMatch,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from stompmodel.units import Millimetre, Nanometre
```

Then add the inverse. Each reader mirrors exactly one
writer, in the same order, so the pair can be read side by side:

```python
def from_document(document: Mapping[str, Any]) -> DrillData:
    """Rebuild ``DrillData`` from a document ``to_document`` produced.

    Mirrors the writers above one for one. A document whose ``format`` is not
    this one, or whose ``version`` is unknown, is refused rather than parsed
    on a guess: a reader that silently accepts a shape it does not know is
    how two packages come to disagree about the same file.
    """
    if document.get("format") != FORMAT:
        raise EmitterError(f"not a {FORMAT} document: {document.get('format')!r}")
    if document.get("version") != VERSION:
        raise EmitterError(f"{FORMAT} version {document.get('version')!r}, expected {VERSION}")
    return DrillData(
        holes=tuple(_read_hole(h) for h in document["holes"]),
        reference=_read_reference(document["reference"]),
        diagnostics=tuple(_read_diagnostic(d) for d in document["diagnostics"]),
        source=_read_source(document["source"]),
        processing=tuple(_read_stage_run(r) for r in document["processing"]),
        enclosure=_read_enclosure(document["enclosure"]),
    )
```

The document carries a `tools` table, which `to_document` derives from the holes
and `from_document` must **not** read back: `DrillData.tools()` recomputes it,
and storing a second copy is the duplication this package exists to prevent. The
round-trip test above is what proves the derived table is genuinely derived.

Each `_read_*` helper takes the mapping its writer produced and returns the value
type; `_read_hole` reads `index` and calls `with_number`, never enumerating.

- [ ] **Step 4: Run it to verify it passes**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_codec.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Reduce the emitter to a wrapper**

Replace `packages/stompdrill/src/stompdrill/emitters/json_out.py` with:

```python
"""Register stompmodel's drill document as an emitter format.

The document and its codec live in stompmodel, because stompcollider reads
the same file and cannot import stompdrill. What is left here is the
registry entry and the one option that is genuinely presentation:
``indent``. See ADR-0009.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

from stompmodel.codec import to_document
from stompmodel.model import DrillData

from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter"]


@dataclass(frozen=True, slots=True)
class JsonOptions:
    """``indent`` is passed straight to :func:`json.dumps`; ``None`` is compact."""

    indent: int | None = 2


@register_emitter
class JsonEmitter:
    """Emit the whole of ``DrillData`` as JSON."""

    name: ClassVar[str] = "json"
    media_type: ClassVar[str] = "application/json"
    extension: ClassVar[str] = ".json"

    def __init__(self, options: JsonOptions | None = None) -> None:
        self.options = options if options is not None else JsonOptions()

    def emit(self, data: DrillData) -> str:
        return json.dumps(to_document(data), indent=self.options.indent) + "\n"
```

`FORMAT` and `VERSION` are no longer exported from here. Repoint their importers:

```bash
grep -rn "json_out import\|json_out\.FORMAT\|json_out\.VERSION" \
  packages/stompdrill/src packages/stompdrill/tests
```

- [ ] **Step 6: Split the emitter's tests**

`packages/stompdrill/tests/test_json_emitter.py` tests both the document's shape
and the emitter's wrapping. Move every test whose subject is the document's
content into `packages/stompmodel/tests/test_codec.py`, repointing imports to
`stompmodel.codec`. Keep in `stompdrill` only what tests the emitter as an
emitter: its registry name, media type, extension, the `indent` option, the
trailing newline, and that `--emit json=PATH` writes it.

- [ ] **Step 7: Run both suites, the leak check, and the artefact diff**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
.venv/bin/python tools/artefacts.py /tmp/after-codec \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-codec && echo "IDENTICAL"
```

`IDENTICAL` matters most here: the emitted JSON must be byte-for-byte what it
was, including key order, which `to_document` preserves by building the mapping
in the same sequence.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Move the drill document's codec into stompmodel, with a reader

document() was write-only, so stompcollider reading the same file would have
had to write a second parser -- the duplication stompmodel exists to
prevent, arriving through the back door. from_document is that reader, and
a round-trip property test is what makes 'one JSON, and vice versa' a fact
rather than a claim.

The tools table is written and not read back: DrillData.tools() derives it,
and a stored second copy would be the same duplication one level down. The
round trip proves it is genuinely derived.

JsonEmitter keeps its registry entry and the one thing that is really
presentation, indent."
```

---

### Task 7: The pipeline contracts

**Files:**
- Create: `packages/stompmodel/src/stompmodel/protocols.py`
- Create: `packages/stompmodel/tests/test_protocols.py`
- Modify: `packages/stompdrill/src/stompdrill/protocols.py`

**Interfaces:**
- Consumes: `stompmodel.model.StageRun` (Task 5).
- Produces: `stompmodel.protocols` exporting `Processable`, `Stage`, `Pipeline`,
  `Emitter`, `Payload`, each generic in the value it folds over.
  `stompdrill.protocols` keeps only `Source`, which returns `RawDrillData` and is
  stompdrill's alone.

`stompcollider` folds `Match` and `Seat` over a `DockData` exactly as
`stompdrill` folds its stages over `DrillData`, and `stompcad` reads both tools'
`StageRun` provenance. That is the second admission rule. `Source` fails it:
`RawDrillData` is artwork, and `stompcollider`'s board reader returns something
else entirely.

- [ ] **Step 1: Write the failing test**

Create `packages/stompmodel/tests/test_protocols.py`:

```python
"""The generic pipeline contracts, exercised on a value that is not DrillData."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from stompmodel.model import StageRun
from stompmodel.protocols import Pipeline


@dataclass(frozen=True, slots=True)
class Counter:
    """A minimal Processable: anything foldable, so the fold is proved generic."""

    count: int = 0
    processing: tuple[StageRun, ...] = ()

    def with_processing(self, *runs: StageRun) -> "Counter":
        return replace(self, processing=self.processing + tuple(runs))


class Add:
    name = "add"

    def __init__(self, by: int) -> None:
        self.by = by

    def apply(self, data: Counter) -> Counter:
        return replace(data, count=data.count + self.by)

    def describe(self) -> StageRun:
        return StageRun(name=self.name, parameters=(("by", self.by),))


def test_a_pipeline_folds_its_stages_in_order():
    result = Pipeline([Add(2), Add(3)]).run(Counter())

    assert result.count == 5


def test_each_stage_is_recorded_after_it_succeeds():
    result = Pipeline([Add(2), Add(3)]).run(Counter())

    assert [run.name for run in result.processing] == ["add", "add"]
    assert [dict(run.parameters)["by"] for run in result.processing] == [2, 3]


def test_a_stage_is_recorded_only_after_it_succeeds():
    """``describe()`` must run after ``apply()``, not before it.

    A fold that recorded first would report a stage that never ran. The
    counter below is the observable: ``Boom.describe`` increments it, so a
    zero proves the record was never taken.
    """
    described = []

    class Boom:
        name = "boom"

        def apply(self, data: Counter) -> Counter:
            raise RuntimeError("no")

        def describe(self) -> StageRun:
            described.append(self.name)
            return StageRun(name="boom", parameters=())

    with pytest.raises(RuntimeError, match="no"):
        Pipeline([Add(1), Boom()]).run(Counter())

    assert described == []


def test_then_returns_a_new_pipeline_and_leaves_the_original_alone():
    first = Pipeline([Add(1)])
    second = first.then(Add(1))

    assert len(first) == 1
    assert len(second) == 2
    assert second.run(Counter()).count == 2
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_protocols.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'stompmodel.protocols'`.

- [ ] **Step 3: Write the generic contracts**

Create `packages/stompmodel/src/stompmodel/protocols.py`:

```python
"""The contracts a stomp pipeline is built from, generic in what it folds.

stompdrill folds stages over DrillData and stompcollider folds Match and
Seat over DockData; stompcad reads both tools' StageRun provenance and
reduces it uniformly. Two hand-copied folds would drift exactly where
ADR-0001's consistency argument bites. See ADR-0009.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import ClassVar, Protocol, TypeVar, runtime_checkable

from .model import StageRun

__all__ = ["Processable", "Stage", "Emitter", "Payload", "Pipeline"]


@runtime_checkable
class Processable(Protocol):
    """A value a pipeline can fold over: it can record the stages it survived."""

    def with_processing(self, *runs: StageRun) -> "Processable": ...


T = TypeVar("T", bound=Processable)


@runtime_checkable
class Stage(Protocol[T]):
    """A deterministic preprocessing step independent of pipeline position."""

    name: ClassVar[str]

    def apply(self, data: T) -> T: ...

    def describe(self) -> StageRun:
        """Report the effective configuration applied by this stage."""
        ...


#: What an emitter hands back. Text formats return ``str``; a byte format such
#: as PDF returns ``bytes``. The writing site chooses how to put it on disk --
#: see ADR-0005.
Payload = str | bytes


@runtime_checkable
class Emitter(Protocol[T]):
    """Serialises one value into one output format.

    Emitters may translate frames and convert units, but do not quantise,
    deduplicate, sort, or renumber the model.
    """

    name: ClassVar[str]
    media_type: ClassVar[str]
    extension: ClassVar[str]

    def emit(self, data: T) -> Payload: ...


class Pipeline(Sequence[Stage[T]]):
    """An ordered, immutable sequence of stages. Contains no domain knowledge."""

    __slots__ = ("_stages",)

    def __init__(self, stages: Iterable[Stage[T]] = ()) -> None:
        self._stages: tuple[Stage[T], ...] = tuple(stages)

    def __getitem__(self, index):
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage[T]]:
        return iter(self._stages)

    def __repr__(self) -> str:
        return f"Pipeline({[s.name for s in self._stages]!r})"

    def then(self, stage: Stage[T]) -> "Pipeline[T]":
        """Return a new pipeline with ``stage`` appended."""
        return Pipeline(self._stages + (stage,))

    def run(self, data: T) -> T:
        """Fold the stages over ``data``, recording each one as it succeeds.

        A record is appended only after ``apply`` returns successfully.
        """
        for stage in self._stages:
            data = stage.apply(data).with_processing(stage.describe())
        return data
```

- [ ] **Step 4: Run it to verify it passes**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests/test_protocols.py -q
```

- [ ] **Step 5: Reduce stompdrill's protocols to `Source`**

Replace `packages/stompdrill/src/stompdrill/protocols.py` with:

```python
"""The one protocol that is stompdrill's alone.

Stage, Pipeline and Emitter are generic and live in stompmodel. Source does
not: RawDrillData is artwork, and stompcollider's board reader returns
something else entirely. See ADR-0009.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .quantise import RawDrillData

__all__ = ["Source"]


@runtime_checkable
class Source(Protocol):
    """Read artwork as unquantised finite millimetres in ``RawDrillData``.

    Coordinates are Y-up and centred on the reference outline when present;
    otherwise they remain page-relative and the missing frame is diagnosed.
    """

    def read(self) -> RawDrillData: ...
```

Check for an import cycle: `quantise.py` must not import `protocols.py`. If it
does, the fix is to move the `Source` protocol's import of `RawDrillData` under
`if TYPE_CHECKING:`.

- [ ] **Step 6: Repoint every consumer**

```bash
grep -rn "from \.protocols import\|from \.\.protocols import\|stompdrill\.protocols" \
  packages/stompdrill/src packages/stompdrill/tests
```

`Stage`, `Pipeline`, `Emitter` and `Payload` come from `stompmodel.protocols`;
`Source` stays on `stompdrill.protocols`. In `stompdrill`, spell the concrete
types: `Pipeline[DrillData]`, `Stage[DrillData]`, `Emitter[DrillData]`.

- [ ] **Step 7: Run both suites, the leak check, and the artefact diff**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
grep -rn "stompdrill" packages/stompmodel/ && echo "LEAK" || echo "clean"
.venv/bin/python tools/artefacts.py /tmp/after-protocols \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/after-protocols && echo "IDENTICAL"
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Make the pipeline contracts generic and move them to stompmodel

stompcollider folds Match and Seat over DockData exactly as stompdrill folds
its stages over DrillData, and stompcad reduces both tools' StageRun
provenance uniformly -- the second admission rule. Two hand-copied twenty-line
folds would drift exactly where ADR-0001's consistency argument bites.

Source stays: RawDrillData is artwork, and stompcollider's board reader
returns something else entirely. Being similar is not the test."
```

---

### Task 8: Close the migration

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/specs/stompcollider-technical.md`
- Delete: `tools/artefacts.py`

**Interfaces:**
- Consumes: everything.
- Produces: nothing new. This task proves the plan's global constraint and
  removes the instrument.

- [ ] **Step 1: Prove both packages install and test alone**

```bash
uv venv /tmp/alone-model
VIRTUAL_ENV=/tmp/alone-model uv pip install ./packages/stompmodel pytest hypothesis
cd packages/stompmodel && /tmp/alone-model/bin/python -m pytest -o addopts= -q; cd ../..

uv venv /tmp/alone-drill
VIRTUAL_ENV=/tmp/alone-drill uv pip install ./packages/stompdrill pytest hypothesis pikepdf
cd packages/stompdrill && /tmp/alone-drill/bin/python -m pytest -o addopts= -q; cd ../..
```

Expected: both green. The `stompmodel` run must not need `pikepdf`; if it does,
something leaked and the leak must be found, not papered over with a dependency.

- [ ] **Step 2: Confirm the whole suite and the artefacts one last time**

```bash
.venv/bin/python -m pytest -o addopts= packages/stompmodel/tests -q
.venv/bin/python -m pytest -p no:cacheprovider -o addopts= --hammond packages/stompdrill/tests -q
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
.venv/bin/python tools/artefacts.py /tmp/final \
  packages/stompdrill/tests/fixtures/tar.ai ~/.cache/stompcad/cases/1590B.stp
diff -r /tmp/baseline-artefacts /tmp/final && echo "IDENTICAL"
```

Expected: green, clean, clean, `IDENTICAL`. Record the two test counts; they must
sum to at least 1342.

- [ ] **Step 3: Update the coverage targets in CLAUDE.md**

In `## Testing rules`, change the coverage line to name both packages:

```
- Coverage targets are 90% for each package and 100% for quantisers, stages,
  emitters, and `stompmodel`'s codec.
```

In `## Architecture`, add a line above the ADR list:

```
The workspace is `packages/stompmodel` and `packages/stompdrill`; each installs
and passes its own tests alone, which is ADR-0008's governing test.
```

- [ ] **Step 4: Tick plan 1 off in the spec**

In `docs/specs/stompcollider-technical.md`, in the Order of work table, change
plan 1's "Done when" cell to read `done — <commit sha>`.

- [ ] **Step 5: Remove the instrument**

```bash
git rm tools/artefacts.py
```

It was a migration instrument, not a test. Keeping it would leave a script that
nothing runs and that nothing keeps honest; the byte-identity claim it proved is
recorded in the commits and, from here on, in the suite.

- [ ] **Step 6: Run the gate once more and commit**

```bash
.venv/bin/ruff check packages tools
.venv/bin/mypy packages
git add -A
git commit -m "Finish the stompmodel extraction

Both packages install and pass their own tests in a clean environment, which
is ADR-0008's governing test and the reason these are distributions rather
than directories. Every emitted artefact is byte-identical to its
pre-migration bytes.

Removes tools/artefacts.py: a migration instrument, not a test. Nothing would
run it from here, and a script nothing runs is a script nothing keeps honest."
```

---

## Verification Summary

Every task ends with the same four gates, and none may be skipped:

| Gate | Command | Expected |
| --- | --- | --- |
| `stompmodel` suite | `pytest packages/stompmodel/tests` | green |
| `stompdrill` suite | `pytest --hammond packages/stompdrill/tests` | green; counts sum to ≥ 1342 |
| No leak | `grep -rn "stompdrill" packages/stompmodel/` | no match |
| Artefacts inert | `diff -r /tmp/baseline-artefacts /tmp/after-<task>` | identical |

A task that cannot make all four pass is not done. In particular, **a difference
in the artefact diff is never accepted as "probably fine"** — it is the one
thing this plan exists to prevent.
