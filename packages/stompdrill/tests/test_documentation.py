"""Repository documentation policy checks."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from stompdrill.emitters import available
from stompmodel.codec import FORMAT
from tools.check_docstrings import find_long_docstrings
from tools.workspace_membership import member_area_roots, member_package_dirs

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
# The scripts stayed at the repository root when the package moved beneath it,
# and a root that does not exist scans as empty rather than failing, so `tools`
# is named apart. Every member's own areas come from the one statement of
# workspace membership rather than a list restated here: a member missing from
# a hand-written list is a member whose prose nothing audits at all, and the
# list gives no sign of it. `test_the_docstring_audit_reaches_every_member`
# below is the control that this really reaches them.
PYTHON_ROOTS = (REPO / "tools",) + tuple(
    directory / area
    for directory in member_package_dirs()
    for area in ("src", "tests")
    if (directory / area).is_dir()
)


def missing_emit_formats(script: str, formats: tuple[str, ...]) -> frozenset[str]:
    """Registry formats the lock script never asks the CLI to emit.

    Comments are removed before the scan, by the shell's own rule that a
    ``#`` opening a word begins one, so header prose cannot stand in for a
    command a panel really runs.
    """
    commands = re.sub(r"(?m)(?:^|(?<=\s))#.*$", "", script)
    asked = frozenset(re.findall(r"--emit\s+([a-z0-9-]+)=", commands))
    return frozenset(formats) - asked


def test_the_scanner_reports_the_owner_and_physical_line_count(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text('def example():\n    """one\n    two\n    three"""\n', encoding="utf-8")

    (violation,) = find_long_docstrings((sample,), max_lines=2)

    assert violation.path == sample
    assert violation.line == 2
    assert violation.owner == "example"
    assert violation.lines == 3


def test_the_docstring_audit_reaches_every_member():
    """The reach control: a root list that named one package short would let
    that package's prose go unaudited and report nothing while doing it.

    Ground truth comes from a second walk of ``packages/`` that never calls
    the function ``PYTHON_ROOTS`` is built from, so a narrowed return there
    fails here. Non-emptiness is asserted first, because a walk finding no
    member would otherwise satisfy every containment below for free.
    """
    scanned = frozenset(PYTHON_ROOTS)
    sources, suites = member_area_roots("src"), member_area_roots("tests")

    assert sources and suites

    assert sources <= scanned
    assert suites <= scanned
    assert (REPO / "tools") in scanned


def test_the_repository_docstring_audit_reports_every_over_length_docstring():
    """The ceiling guides new prose; it does not gate the suite, so this only warns."""
    violations = find_long_docstrings(PYTHON_ROOTS)
    if not violations:
        return
    details = "\n".join(
        f"{item.path.relative_to(REPO)}:{item.line}: "
        f"{item.owner} spans {item.lines} lines"
        for item in violations
    )
    warnings.warn(f"docstrings over 10 lines:\n{details}", stacklevel=1)


def test_the_collider_spec_names_the_format_string_the_codec_actually_writes():
    """A plan-3 reader built to this spec must recognise stompdrill's document.

    Compared mechanically against ``stompmodel.codec.FORMAT`` rather than by
    eye, so the two cannot drift apart again the way they once did.
    """
    spec = REPO / "docs" / "specs" / "stompcollider-technical.md"
    text = spec.read_text(encoding="utf-8")

    found = re.search(r"Drill document \(`([^`]+)` v\d+\)", text)

    assert found, f"{spec}: the drill-document row was not found as expected"
    assert found.group(1) == FORMAT


def test_the_lock_script_emits_every_registered_format():
    """ADR-0011's coverage claim, against the registry rather than by eye.

    A sixth emitter registered without a line in the lock would leave the
    ADR and the script's own header overclaiming, silently. Non-vacuity is
    asserted first: an empty registry or an unreadable script would
    otherwise pass for free.
    """
    formats = available()
    script = (REPO / "tools" / "verify-lock.sh").read_text(encoding="utf-8")
    assert formats and script

    missing = missing_emit_formats(script, formats)

    assert missing == frozenset(), (
        f"tools/verify-lock.sh passes no --emit for {sorted(missing)}, so "
        "ADR-0011's claim that the lock covers every registered emitter is false"
    )


def test_a_format_absent_from_the_script_is_reported():
    """Guilty probe: a registered format the script never emits must be named."""
    assert missing_emit_formats(
        "--emit excellon=$OUT/a.drl\n", ("excellon", "step")
    ) == frozenset({"step"})


def test_a_script_naming_every_format_reports_nothing():
    """Innocent probe: unrelated edits to the script must not trip the check.

    Comment prose, interleaved flags and a reordered emit list are all
    legitimate changes to the lock; none of them is a coverage breach.
    """
    assert missing_emit_formats(
        "# two panels, reordered\n--emit step=$OUT/a.stp --case 1590B\n"
        "--emit excellon=$OUT/a.drl --title ''\n",
        ("excellon", "step"),
    ) == frozenset()


def test_a_format_named_only_in_a_comment_is_reported():
    """Guilty probe: prose may not stand in for a command a panel runs.

    A shell comment is not an invocation, so a format mentioned only in
    the script's header — or after a `#` on an otherwise real line — is
    still a format no panel emits.
    """
    assert missing_emit_formats(
        "# the lock also passes --emit step=$OUT/a.stp\n"
        "--emit excellon=$OUT/a.drl  # --emit step=$OUT/a.stp\n",
        ("excellon", "step"),
    ) == frozenset({"step"})
