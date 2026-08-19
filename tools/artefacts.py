"""Emit every format from one fixture, so a refactor can be proved inert.

Not a test: a migration instrument. Run it on the pre-migration tree and on
the working tree, then diff the two directories. Any difference is a
behaviour change, which this plan forbids. Give both runs the same panel
path: it is recorded verbatim as provenance, so a fixture that sits at two
spellings must be copied to one. The STEP artefact needs a cached case model
and is skipped when one is not supplied.
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
