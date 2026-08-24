"""Integration checks over the ownership-gate convention itself (tickets 25, 32).

Neither test below polices one of the five singularity rules; each rule's
own gate lives in the suite of the member that owns it. These check the
*convention*: a breach in a member's own source fails that member's own
command, a package no gate names literally is still caught, and an
innocent new package trips no gate. Each spawns a subprocess pytest run,
so none is collected by the suite it drives. The gate family is discovered
by the marker every gate defines (``_REACH_TEST``), not listed.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

from tools.workspace_membership import REPO, member_package_dirs

WRITER = REPO / "packages" / "stompgeom" / "src" / "stompgeom" / "writer.py"

#: The name every gate file in the family gives its reach-control test.
#: Carrying this function is what makes a module part of the family --
#: not appearing in a literal list of paths.
_REACH_TEST = "test_the_scan_reaches_every_workspace_member"

#: The probe package's name is deliberately outside the ``stomp`` prefix
#: ADR-0010 gives every real workspace member (``stompmodel``, ``stompgeom``,
#: ``stompdrill``, ``stompcollider``, ``stompcad``), so it can never collide
#: with a member the workspace legitimately gains later -- ``stompcollider``
#: itself is named in ADR-0008 as a real future package, which the old probe
#: name did not account for.
_PROBE_NAME = "_ownership_gate_probe"

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


def _discover_gates() -> tuple[tuple[Path, str], ...]:
    """Every gate file in the family, paired with its own rule-checking test.

    A module belongs to the family by carrying ``_REACH_TEST``, not by
    appearing in a literal list -- found by walking every workspace
    member's own ``tests/``, so a new gate built the same way is exercised
    here the moment it exists. Its rule-checking test is read off
    structurally too: by this family's own convention (every gate file
    above), it is the *last* top-level ``test_`` function defined, following
    the reach control and every proof-the-scanner-fires positive control.
    """
    found: list[tuple[Path, str]] = []
    for pkg in member_package_dirs():
        tests_dir = pkg / "tests"
        if not tests_dir.is_dir():
            continue
        for path in sorted(tests_dir.rglob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            test_names = [
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            ]
            if _REACH_TEST in test_names:
                found.append((path, test_names[-1]))
    return tuple(found)


def _run_gate(gate_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", "-v", str(gate_file)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _status_of(stdout: str, test_name: str) -> str | None:
    for line in stdout.splitlines():
        if test_name in line and ("PASSED" in line or "FAILED" in line):
            return "PASSED" if "PASSED" in line else "FAILED"
    return None


def _make_probe(source: str) -> Path:
    probe_pkg = REPO / "packages" / _PROBE_NAME
    probe_src = probe_pkg / "src" / _PROBE_NAME
    assert not probe_pkg.exists(), f"{_PROBE_NAME} already exists; refusing to overwrite it"
    probe_src.mkdir(parents=True)
    (probe_src / "probe.py").write_text(source, encoding="utf-8")
    return probe_pkg


_GUILTY_PROBE_SOURCE = (
    "from OCP.XCAFDoc import XCAFDoc_ShapeTool\n"
    '_FACES = {"box": "BOX", "lid": "LID"}\n'
    "def guard(name, value):\n"
    "    if type(value) is not int:\n"
    '        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")\n'
    "def order(hole):\n"
    "    return (hole.raw.x, hole.raw.y, hole.raw.diameter)\n"
    "def walk(label):\n"
    "    return XCAFDoc_ShapeTool.IsAssembly_s(label)\n"
    "def replace(tmp, path):\n"
    "    import os\n"
    "    os.replace(tmp, path)\n"
    "def temp_name(target):\n"
    '    return f".{target.name}.{id(target)}.tmp"\n'
)

_INNOCENT_PROBE_SOURCE = "INNOCENT = 1\n"


def test_a_fourth_package_breaching_every_rule_is_caught_by_every_gate_on_its_own_rule() -> None:
    """A new workspace member is covered by every ownership gate unedited.

    A probe package breaching every "stated once" rule the family polices
    is caught by every gate individually, each in its own subprocess, so a
    change silently weakening one gate cannot hide behind another's pass.
    The failure must land on the gate's own rule-checking assertion, not
    its reach control -- a gate failing only because a member exists has
    not been fixed (ticket 32).
    """
    probe_pkg = _make_probe(_GUILTY_PROBE_SOURCE)
    try:
        gates = _discover_gates()
        assert gates, "no gate files were discovered -- the family marker moved"
        results = {gate_file: _run_gate(gate_file) for gate_file, _rule_test in gates}
    finally:
        shutil.rmtree(probe_pkg, ignore_errors=True)

    problems = []
    for gate_file, rule_test in gates:
        result = results[gate_file]
        reach_status = _status_of(result.stdout, _REACH_TEST)
        rule_status = _status_of(result.stdout, rule_test)
        if result.returncode == 0:
            problems.append(f"{gate_file}: exited 0 -- did not catch the breach at all")
        elif reach_status == "FAILED":
            problems.append(
                f"{gate_file}: failed on its reach control ({_REACH_TEST}) rather "
                "than its rule-checking assertion -- the gate has not been fixed"
            )
        elif rule_status != "FAILED":
            problems.append(
                f"{gate_file}: exited non-zero but its rule-checking test "
                f"({rule_test}) did not fail (status={rule_status})"
            )
    assert problems == [], (
        "a fourth package breaching every rule the gate family polices was not "
        "caught cleanly by every gate's own rule-checking assertion:\n"
        + "\n".join(problems)
    )


def test_a_fourth_package_breaching_nothing_passes_every_gate() -> None:
    """The matched pair (ticket 32): an innocent new member trips no gate.

    A probe package that breaches none of the family's rules must pass
    every gate -- otherwise a gate's exit code cannot distinguish "a rule
    was breached" from "the workspace merely grew a member", which is
    exactly the vacuous-reach-control defect this ticket exists to close.
    """
    probe_pkg = _make_probe(_INNOCENT_PROBE_SOURCE)
    try:
        gates = _discover_gates()
        assert gates, "no gate files were discovered -- the family marker moved"
        results = {gate_file: _run_gate(gate_file) for gate_file, _rule_test in gates}
    finally:
        shutil.rmtree(probe_pkg, ignore_errors=True)

    wrongly_tripped = [
        f"{gate_file}: exit {results[gate_file].returncode} "
        f"({_REACH_TEST}={_status_of(results[gate_file].stdout, _REACH_TEST)})"
        for gate_file, _rule_test in gates
        if results[gate_file].returncode != 0
    ]
    assert wrongly_tripped == [], (
        "an innocent fourth member (breaching none of the family's rules) "
        "tripped these gates, proving a reach control still fires on mere "
        "membership growth rather than on a real breach:\n"
        + "\n".join(wrongly_tripped)
    )
