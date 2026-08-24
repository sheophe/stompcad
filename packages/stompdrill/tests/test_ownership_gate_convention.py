"""Integration checks over the ownership-gate convention itself (ticket 25).

Neither test below polices one of the four singularity rules -- each rule's
own gate now lives in the suite of the member that owns it (three in
``stompmodel``'s, one in ``stompgeom``'s). These check the *convention*: a
member's own command catches a breach in its own source, and a package no
gate names literally is still caught. They live here, not inside a gate's
own suite, because each spawns a subprocess pytest run that must not be
collected by the very suite it drives.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WRITER = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "writer.py"

_DUPLICATE_WALK = '''

def _second_leaf_walk(document):  # deliberate duplicate, for this test only
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    out = []
    for i in range(1, free.Length() + 1):
        label = free.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            kids = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, kids)
    return out
'''


def test_stompgeoms_own_suite_catches_a_second_leaf_walk_in_its_own_source() -> None:
    """A regression entirely inside ``stompgeom`` is caught by ``stompgeom`` alone.

    Appending a second XCAF leaf descent to ``stompgeom``'s own ``writer.py``
    and running exactly the command CLAUDE.md documents for ``stompgeom``
    ("cd packages/stompgeom && uv run --no-sync pytest") must fail: the fold
    this rule protects belongs to ``stompgeom``, and ticket 25 moved the gate
    that notices its violation into ``stompgeom``'s own suite.
    """
    original = WRITER.read_text(encoding="utf-8")
    try:
        WRITER.write_text(original + _DUPLICATE_WALK, encoding="utf-8")
        result = subprocess.run(
            ["uv", "run", "--no-sync", "pytest", "-o", "addopts=", "-q"],
            cwd=REPO / "packages" / "stompgeom",
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        WRITER.write_text(original, encoding="utf-8")

    assert result.returncode != 0, (
        "stompgeom's own suite passed (exit 0) with a second XCAF leaf walk "
        "sitting in its own writer.py -- the ownership gate is supposed to "
        "catch this from stompgeom's own suite alone.\n"
        f"stdout tail:\n{result.stdout[-800:]}"
    )


def test_a_fourth_package_breaching_all_four_rules_is_caught_by_every_gate() -> None:
    """A new workspace member is covered by every ownership gate unedited.

    ``stompcollider`` is plan 3's named fourth member. A file inside it that
    breaches all four "stated once" rules at once is caught by at least one
    of the four gates -- each derives the packages it scans from
    ``member_package_dirs``, which discovers this probe the moment its
    ``src`` directory exists, with no edit to any gate.
    """
    probe_pkg = REPO / "packages" / "stompcollider"
    probe_src = probe_pkg / "src" / "stompcollider"
    probe_file = probe_src / "probe.py"
    assert not probe_pkg.exists(), "stompcollider already exists; refusing to overwrite it"

    probe_src.mkdir(parents=True)
    probe_file.write_text(
        "from OCP.XCAFDoc import XCAFDoc_ShapeTool\n"
        '_FACES = {"box": "BOX", "lid": "LID"}\n'
        "def guard(name, value):\n"
        "    if type(value) is not int:\n"
        '        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")\n'
        "def order(hole):\n"
        "    return (hole.raw.x, hole.raw.y, hole.raw.diameter)\n"
        "def walk(label):\n"
        "    return XCAFDoc_ShapeTool.IsAssembly_s(label)\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
                "-q",
                "packages/stompmodel/tests/test_nanometre_guard_is_singular.py",
                "packages/stompmodel/tests/test_case_face_vocabulary_is_singular.py",
                "packages/stompgeom/tests/test_the_leaf_walk_is_stated_once.py",
                "packages/stompmodel/tests/test_tie_break_owner.py",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(probe_pkg, ignore_errors=True)

    assert result.returncode != 0, (
        "all four ownership gates passed with a file in a fourth package "
        "(stompcollider) breaching every one of their published-once rules "
        "at once -- member_package_dirs() should have discovered it.\n"
        f"stdout tail:\n{result.stdout[-800:]}"
    )
