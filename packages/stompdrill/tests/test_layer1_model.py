"""Layer 1: the model itself -- reproducible, order-blind, and pinned.

Two emissions in fresh processes rather than two calls in one: within a
process an insertion-ordered dict looks deterministic whether or not the
code depends on it, and a differing hash seed is what tells the two apart.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from stompdrill.cli import build_parser, build_pipeline, build_quantisers, read_source
from stompdrill.quantise import quantise
from stompmodel.model import DrillData

__all__: list[str] = []

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden" / "tar-1590b.json"

#: Two seeds that differ, so set and dict iteration differ between the runs.
SEEDS = ("0", "12345")

FORMATS = ("excellon", "json", "drawing-svg", "drawing-pdf")


def emit_in_a_fresh_process(destination: Path, seed: str, panel: str, case: str) -> dict[str, bytes]:
    """Run the CLI in a subprocess under ``seed`` and return what it wrote."""
    destination.mkdir(parents=True, exist_ok=True)
    targets = {name: destination / f"{name}.out" for name in FORMATS}
    environment = dict(os.environ, PYTHONHASHSEED=seed)
    arguments = [sys.executable, "-m", "stompdrill.cli", str(FIXTURES / panel), "--case", case]
    for name, path in targets.items():
        arguments += ["--emit", f"{name}={path}"]

    completed = subprocess.run(arguments, env=environment, capture_output=True, check=False)
    assert completed.returncode in (0, 1), completed.stderr.decode()
    return {name: path.read_bytes() for name, path in targets.items()}


@pytest.mark.parametrize("panel,case", [("tar.ai", "1590B"), ("pax.ai", "1590BB")])
def test_two_fresh_processes_emit_identical_bytes(tmp_path, panel, case):
    """T1. A hash seed reaching an artefact is the failure this catches, and
    no single-process comparison can see it."""
    first = emit_in_a_fresh_process(tmp_path / "a", SEEDS[0], panel, case)
    second = emit_in_a_fresh_process(tmp_path / "b", SEEDS[1], panel, case)

    assert first == second


#: Read by the subprocess script below, appended to its own generated
#: ``sys.path`` entry so it can import the tools this repository ships.
_PERMUTE_SCRIPT = textwrap.dedent(
    """
    import json
    import random
    import sys
    from dataclasses import replace
    from pathlib import Path

    from stompdrill.cli import build_parser, build_pipeline, build_quantisers
    from stompdrill.emitters.json_out import JsonEmitter
    from stompdrill.quantise import quantise
    from stompdrill.sources import AiPdfSource

    seed = int(sys.argv[1])
    fixtures = Path(sys.argv[2])

    args = build_parser().parse_args([str(fixtures / "tar.ai"), "--case", "1590B"])
    raw = AiPdfSource(
        args.panel, drill_layer=args.drill_layer, reference_layer=args.reference_layer,
    ).read()

    shuffled_holes = list(raw.holes)
    random.Random(seed).shuffle(shuffled_holes)
    raw = replace(raw, holes=tuple(shuffled_holes))

    quantisers = build_quantisers(args)
    data = quantise(
        raw,
        enclosure=quantisers.enclosure,
        diameters=quantisers.diameters,
        positions=quantisers.positions,
    )
    data = build_pipeline(args).run(data)
    sys.stdout.write(JsonEmitter().emit(data))
    """
)


def emit_permuted_in_a_fresh_process(script: Path, seed: int, hash_seed: str) -> bytes:
    """Run ``script`` in a subprocess under ``hash_seed`` and return its stdout."""
    environment = dict(os.environ, PYTHONHASHSEED=hash_seed)
    completed = subprocess.run(
        [sys.executable, str(script), str(seed), str(FIXTURES)],
        env=environment,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return completed.stdout


def test_a_permuted_panel_emits_identical_bytes_from_a_fresh_process(tmp_path):
    """T1'. ``test_invariant.py`` shuffles within one process; this crosses a
    process boundary as well, so an order dependency that only surfaces under
    a different hash seed cannot hide behind the in-process check."""
    script = tmp_path / "permute_and_emit.py"
    script.write_text(_PERMUTE_SCRIPT, encoding="utf-8")

    first = emit_permuted_in_a_fresh_process(script, seed=1, hash_seed=SEEDS[0])
    second = emit_permuted_in_a_fresh_process(script, seed=2, hash_seed=SEEDS[1])

    assert first == second


def shipped_model(panel: str, case: str) -> DrillData:
    """The model the CLI builds for ``panel``, read from it rather than
    hand-copied. Follows ``test_invariant.shipped_pipeline``'s precedent: a
    copied stage list, or a copied quantiser set, drifts the moment either
    grows a new default.
    """
    args = build_parser().parse_args([str(FIXTURES / panel), "--case", case])
    quantisers = build_quantisers(args)
    raw = read_source(args)
    data = quantise(
        raw,
        enclosure=quantisers.enclosure,
        diameters=quantisers.diameters,
        positions=quantisers.positions,
    )
    return build_pipeline(args).run(data)


def fact_set(data: DrillData) -> dict[str, object]:
    """Everything about a model a change should have to justify.

    Geometry, findings and provenance of process -- but not ``source.path``,
    which is the working directory rather than a fact about the panel, and
    the one value that would make this file fail on a legitimate change.
    """
    return {
        "outline_nm": None if data.reference is None
        else [data.reference.width_nm, data.reference.height_nm],
        "enclosure": None if data.enclosure is None
        else {
            "family": data.enclosure.family,
            "candidates": list(data.enclosure.candidates),
            "rotated": data.enclosure.rotated,
            "selected_part": data.enclosure.selected_part,
        },
        "layers": {
            "drill": data.source.drill_layer,
            "reference": data.source.reference_layer,
            "found": list(data.source.layers_found),
        },
        "tools": [[diameter_nm, number] for diameter_nm, number in data.tools().items()],
        "holes": [
            {"index": index, "x_nm": hole.x_nm, "y_nm": hole.y_nm,
             "diameter_nm": hole.diameter_nm}
            for index, hole in data.numbered()
        ],
        "diagnostics": [
            {"code": d.code, "severity": d.severity.name,
             "location_nm": None if d.location_nm is None else list(d.location_nm)}
            for d in data.diagnostics
        ],
        "processing": [
            {"name": run.name, "parameters": [list(p) for p in run.parameters]}
            for run in data.processing
        ],
    }


def test_the_model_still_states_the_facts_the_golden_records():
    """One golden, of the model. With T2 holding per format a golden per
    artefact is redundant, and a byte-golden would fail on a legitimate
    change: the panel path is provenance in four of five artefacts and the
    STEP writer appends a volatile counter.
    """
    current = fact_set(shipped_model("tar.ai", "1590B"))

    if os.environ.get("STOMPDRILL_UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    assert current == json.loads(GOLDEN.read_text(encoding="utf-8")), (
        "the model's facts changed. If the change is intended, regenerate with:\n"
        "  STOMPDRILL_UPDATE_GOLDEN=1 .venv/bin/python -m pytest -o addopts= "
        "packages/stompdrill/tests/test_layer1_model.py -k golden\n"
        "and review the diff -- a change that moves one number is a bug, a "
        "change that moves the whole file is the intended edit."
    )
