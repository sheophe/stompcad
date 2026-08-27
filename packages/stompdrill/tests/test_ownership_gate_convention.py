"""Integration checks over the ownership-gate convention itself (tickets 25, 32, 48).

No test below polices one of the five singularity rules; each rule's own
gate lives in the suite of the member that owns it. These check the
*convention*: a breach in a member's own source fails that member's own
command as that gate, a package no gate names literally is still caught,
and an innocent new package trips no gate. Every check that drives a suite
spawns a subprocess, so none is collected by the suite it drives. The gate
family is discovered by the marker every gate defines (``_REACH_TEST``).
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tools.workspace_membership import REPO, member_package_dirs

STOMPGEOM = REPO / "packages" / "stompgeom"
WRITER = STOMPGEOM / "src" / "stompgeom" / "writer.py"

#: The gate that owns the leaf-walk rule, in the suite that owns the walk.
#: Its rule-checking test is read off by the family's own convention below,
#: never spelled out here, so renaming it cannot leave this probe watching
#: for a failure that can no longer be reported.
_LEAF_WALK_GATE = STOMPGEOM / "tests" / "test_the_leaf_walk_is_stated_once.py"

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

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: The words pytest's own summary line counts an executed test with.
#: ``deselected`` and ``warnings`` are absent on purpose: neither is a test
#: that ran, and counting them would let a run that examined nothing clear
#: the floor below.
_OUTCOME = re.compile(r"(\d+) (?:passed|failed|skipped|xfailed|xpassed|errors?)\b")


def _plain(text: str) -> str:
    """Captured output with terminal colour escapes removed."""
    return _ANSI.sub("", text)


def _test_names(path: Path) -> list[str]:
    """Every top-level ``test_`` function a test module defines, in file order."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _rule_test_of(gate_file: Path) -> str:
    """The rule-checking test of a gate, by this family's own convention.

    It is the *last* top-level ``test_`` function defined, following the
    reach control and every proof-the-scanner-fires positive control.
    """
    names = _test_names(gate_file)
    assert _REACH_TEST in names, f"{gate_file} carries no reach control -- not a gate in this family"
    return names[-1]


def _tests_defined_by(package: Path) -> int:
    """A floor on what a whole run of ``package``'s own suite must report.

    Read from the source rather than written down, so no count in this file
    drifts. It is a lower bound in both directions that matter: a skip is
    still a reported outcome, and parametrised or class-bound tests only add
    to what a run reports beyond the module-level functions counted here.
    """
    return sum(len(_test_names(path)) for path in sorted((package / "tests").rglob("test_*.py")))


def _run_stompgeoms_own_command() -> subprocess.CompletedProcess[str]:
    """Exactly the command CLAUDE.md documents for ``stompgeom``, captured."""
    return subprocess.run(
        ["uv", "run", "--no-sync", "pytest", "-o", "addopts=", "-q"],
        cwd=STOMPGEOM,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _outcomes_reported(result: subprocess.CompletedProcess[str]) -> int | None:
    """How many executed tests pytest's own summary line reports, if any.

    ``None`` means no summary line was printed, which is exactly what an
    exit code on its own cannot tell apart from a suite that ran and failed.
    """
    for line in reversed(_plain(result.stdout).splitlines()):
        counts = _OUTCOME.findall(line)
        if counts and " in " in line:
            return sum(int(count) for count in counts)
    return None


def _did_not_examine_stompgeoms_suite(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Every reason this run is no evidence that stompgeom's suite ran at all.

    The size of what was examined, never the exit status: a summary line
    reporting at least as many outcomes as stompgeom's tests define. A
    resolver failure, an import or collection error, a timeout or an
    interpreter that never started prints no such line and is refused here.
    """
    floor = _tests_defined_by(STOMPGEOM)
    if floor == 0:
        return ["stompgeom's tests/ defines no test function -- this floor would pass on nothing"]
    reported = _outcomes_reported(result)
    if reported is None:
        return ["pytest printed no summary line at all -- the suite never ran"]
    if reported < floor:
        return [
            (
                f"pytest's own summary covers {reported} of the {floor} tests "
                "stompgeom's own tests/ defines -- part of the suite never ran"
            )
        ]
    return []


def _is_not_the_leaf_walk_gate_failing(result: subprocess.CompletedProcess[str]) -> list[str]:
    """Every reason this run is not the leaf-walk gate catching this breach.

    Identity, not exit status: the failure pytest reports must be the node
    id of that gate's own rule-checking test, and its output must name the
    file the probe mutated. A non-zero exit is necessary and is checked
    last, because on its own it is what ticket 48 found proves nothing.
    """
    problems = _did_not_examine_stompgeoms_suite(result)
    node_id = f"{_LEAF_WALK_GATE.relative_to(STOMPGEOM).as_posix()}::{_rule_test_of(_LEAF_WALK_GATE)}"
    breached = WRITER.relative_to(STOMPGEOM).as_posix()
    text = _plain(result.stdout + result.stderr)
    if f"FAILED {node_id}" not in text:
        problems.append(f"pytest reported no failure of {node_id}")
    if breached not in text:
        problems.append(f"the reported failure never names {breached}, the file this probe mutated")
    if result.returncode == 0:
        problems.append("the command exited 0")
    return problems


def _fabricated(returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    """A run that never happened, for the sabotage control below."""
    return subprocess.CompletedProcess(args=["uv", "run"], returncode=returncode, stdout=stdout, stderr="")


def test_stompgeoms_own_suite_catches_a_second_leaf_walk_in_its_own_source() -> None:
    """A regression entirely inside ``stompgeom`` is caught by ``stompgeom`` alone.

    Appending a second XCAF leaf descent to ``stompgeom``'s own ``writer.py``
    and running exactly the command CLAUDE.md documents for that member must
    fail *as the leaf-walk gate*: over a summary covering the whole suite,
    naming that gate's own rule test and the mutated file. Ticket 25 moved
    the gate here; ticket 48 replaced this probe's exit-code-only assertion,
    which a resolver or collection failure satisfied just as well.
    """
    original = WRITER.read_text(encoding="utf-8")
    try:
        WRITER.write_text(original + _DUPLICATE_WALK, encoding="utf-8")
        result = _run_stompgeoms_own_command()
    finally:
        WRITER.write_text(original, encoding="utf-8")

    problems = _is_not_the_leaf_walk_gate_failing(result)
    assert problems == [], (
        "stompgeom's own suite did not fail as its own leaf-walk gate with a "
        "second XCAF leaf walk sitting in its own writer.py:\n"
        + "\n".join(problems)
        + f"\nstdout tail:\n{result.stdout[-800:]}"
    )


def test_stompgeoms_own_suite_is_green_with_that_breach_absent() -> None:
    """The innocent probe matched to the guilty one above (ticket 48).

    Unmutated, the same command examines the same suite and exits 0. Without
    this, a stompgeom suite left permanently red -- by an unrelated
    regression, or by a restore that silently failed -- would let the guilty
    probe pass while proving nothing about the gate.
    """
    result = _run_stompgeoms_own_command()

    assert _did_not_examine_stompgeoms_suite(result) == [], (
        "stompgeom's own suite did not run at all, unmutated:\n"
        f"{result.stdout[-800:]}\n{result.stderr[-800:]}"
    )
    assert result.returncode == 0, (
        "stompgeom's own suite is red before this module mutates anything, so the "
        f"guilty probe beside it proves nothing:\n{result.stdout[-800:]}"
    )


def test_a_non_zero_run_that_is_not_the_gate_firing_is_refused() -> None:
    """The sabotage control: the strengthening is what rejects these (ticket 48).

    Each fabricated run is non-zero, so the exit-code-only assertion this
    module carried until ticket 48 accepts all three -- a resolver failure
    before pytest started, a command that collected nothing, and an
    unrelated test failing over a full suite. Asserting on identity and on
    the size examined refuses all three, which is the whole difference.
    """
    unrelated = (
        "F" + "." * 69 + "\n"
        "=================================== FAILURES ===================================\n"
        "tests/test_writer.py:42: AssertionError\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_writer.py::test_a_wholly_unrelated_claim - AssertionError\n"
        "1 failed, 69 passed in 1.66s\n"
    )
    fabricated = {
        "uv failed before pytest started": _fabricated(1, ""),
        "the command collected nothing": _fabricated(5, "no tests ran in 0.01s\n"),
        "an unrelated test failed": _fabricated(1, unrelated),
    }
    for label, result in fabricated.items():
        assert result.returncode != 0, f"{label}: this control must satisfy the old assertion"
        assert _is_not_the_leaf_walk_gate_failing(result), (
            f"{label}: accepted by the strengthened verdict, which is the hole ticket 48 closes"
        )


def _discover_gates() -> tuple[tuple[Path, str], ...]:
    """Every gate file in the family, paired with its own rule-checking test.

    A module belongs to the family by carrying ``_REACH_TEST``, not by
    appearing in a literal list -- found by walking every workspace
    member's own ``tests/``, so a new gate built the same way is exercised
    here the moment it exists. Its rule-checking test is read off
    structurally too, by ``_rule_test_of`` above.
    """
    found: list[tuple[Path, str]] = []
    for pkg in member_package_dirs():
        tests_dir = pkg / "tests"
        if not tests_dir.is_dir():
            continue
        for path in sorted(tests_dir.rglob("test_*.py")):
            if _REACH_TEST in _test_names(path):
                found.append((path, _rule_test_of(path)))
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
    "from OCP.TDF import TDF_Label\n"
    '_FACES = {"box": "BOX", "lid": "LID"}\n'
    "def guard(name, value):\n"
    "    if type(value) is not int:\n"
    # Deliberately paraphrased: this probe shares no wording with any
    # owner's implementation, so a gate deciding on prose rather than on
    # the rule's own mechanism fails here rather than passing by luck.
    '        raise TypeError(f"{name} must be an integral count of nanometres, not {value!r}")\n'
    "def order(hole):\n"
    "    return (hole.raw.x, hole.raw.y, hole.raw.diameter)\n"
    "def walk(label):\n"
    "    return XCAFDoc_ShapeTool.IsAssembly_s(label)\n"
    "def replace(tmp, path):\n"
    "    import os\n"
    "    os.replace(tmp, path)\n"
    "def temp_name(target):\n"
    '    return f".{target.name}.{id(target)}.tmp"\n'
    # Ticket 34's gate (stompgeom: no published name returns a bare
    # label): a re-exported, bare-label-returning free function under one
    # of the two deleted names is exactly the shape that gate polices.
    "__all__ = ['label_name']\n"
    "def label_name(label: TDF_Label) -> TDF_Label:\n"
    "    return label\n"
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
