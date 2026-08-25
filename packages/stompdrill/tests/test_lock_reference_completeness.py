"""The behaviour lock's compare path, probed over a synthetic directory.

`tools/verify-lock.sh` is the instrument every preservation programme in this
repository cites, so the one failure it cannot afford is a verdict delivered
over part of its panels. The script is sourced with `LOCK_FUNCTIONS_ONLY` set,
which stops it before it renders anything, and its comparison is driven over
files this module writes. See ADR-0011.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
SCRIPT = REPO / "tools" / "verify-lock.sh"
# The two panels' whole output, as the script's own --emit flags name it.
ARTEFACTS = ("a.drl", "a.json", "a.pdf", "a.stp", "a.svg", "b.drl", "b.json", "b.pdf", "b.svg")

__all__: list[str] = []


def synthesise(directory: Path) -> str:
    """Write a stand-in for every artefact, and return a reference over them.

    The digests come from `hashlib`, not from the script, so the reference is
    an independent statement of the `shasum -a 256` line format rather than
    whatever the script would have produced. The two panel logs are written
    too: they sit beside the artefacts and must stay outside the set.
    """
    directory.mkdir(exist_ok=True)
    rows = []
    for name in ARTEFACTS:
        payload = f"{name} stands in for an artefact\n".encode()
        (directory / name).write_bytes(payload)
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {name}")
    for log in ("a.log", "b.log"):
        (directory / log).write_text("a panel's console output\n", encoding="utf-8")
    return "".join(f"{row}\n" for row in rows)


def compare(reference: Path, directory: Path) -> subprocess.CompletedProcess[str]:
    """Run the script's compare path alone, over one reference and directory."""
    program = f'LOCK_FUNCTIONS_ONLY=1 . "{SCRIPT}"\ncompare_to_reference "$1" "$2"\n'
    return subprocess.run(
        ["bash", "-c", program, "verify-lock", str(reference), str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )


def capture(reference: Path, directory: Path) -> subprocess.CompletedProcess[str]:
    """Run the script's capture path alone, over one directory."""
    program = f'LOCK_FUNCTIONS_ONLY=1 . "{SCRIPT}"\ncapture_reference "$1" "$2"\n'
    return subprocess.run(
        ["bash", "-c", program, "verify-lock", str(reference), str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )


def prepared(tmp_path: Path, reference_text: str) -> subprocess.CompletedProcess[str]:
    """Compare a directory of stand-in artefacts against the given reference."""
    reference = tmp_path / "SHA256SUMS"
    reference.write_text(reference_text, encoding="utf-8")
    return compare(reference, tmp_path / "artefacts")


def test_a_complete_reference_holds_and_states_how_many_it_compared(tmp_path: Path):
    """Innocent probe: the whole set, unaltered, still passes and says its size.

    The reference path is asserted here too: ADR-0011 promises the script
    echoes it, and until this change only the capture path did.
    """
    result = prepared(tmp_path, synthesise(tmp_path / "artefacts"))

    assert result.returncode == 0, result.stdout
    assert "BEHAVIOUR LOCK HELD" in result.stdout
    assert f"reference: {tmp_path / 'SHA256SUMS'}" in result.stdout
    assert len(re.findall(r"(?m)^  ok  ", result.stdout)) == len(ARTEFACTS)
    assert f"compared {len(ARTEFACTS)} artefacts" in result.stdout


def test_a_reference_truncated_to_a_subset_is_refused(tmp_path: Path):
    """Guilty probe: rows that went missing must not be certified by silence.

    Three of the nine rows compare clean, which is exactly the shape that used
    to print a green verdict over six unexamined artefacts.
    """
    whole = synthesise(tmp_path / "artefacts").splitlines(keepends=True)

    result = prepared(tmp_path, "".join(whole[:3]))

    assert result.returncode == 2, result.stdout
    assert "BEHAVIOUR LOCK HELD" not in result.stdout
    for name in ARTEFACTS[3:]:
        assert name in result.stdout


def test_a_reference_naming_an_artefact_no_panel_produced_is_refused(tmp_path: Path):
    """Guilty probe: a reference from another harness is stale, not a break.

    The set disagrees, so the run cannot tell a moved byte from an artefact
    this script no longer writes; it says which, and declines to judge.
    """
    stale = synthesise(tmp_path / "artefacts") + f"{'0' * 64}  a.dxf\n"

    result = prepared(tmp_path, stale)

    assert result.returncode == 2, result.stdout
    assert "BEHAVIOUR LOCK BROKEN" not in result.stdout
    assert "a.dxf" in result.stdout


def test_a_reference_over_no_artefact_is_refused_in_its_own_words(tmp_path: Path):
    """Guilty probe: the zero-row case keeps a message that explains itself."""
    synthesise(tmp_path / "artefacts")

    result = prepared(tmp_path, "")

    assert result.returncode == 2, result.stdout
    assert "names no artefact" in result.stdout


def test_a_final_row_without_a_newline_is_refused(tmp_path: Path):
    """Guilty probe: `read` drops an unterminated last row, so the count must catch it."""
    result = prepared(tmp_path, synthesise(tmp_path / "artefacts").rstrip("\n"))

    assert result.returncode == 2, result.stdout
    assert "BEHAVIOUR LOCK HELD" not in result.stdout
    assert f"names {len(ARTEFACTS)} artefacts but yielded {len(ARTEFACTS) - 1}" in result.stdout


def test_a_moved_byte_is_still_reported_as_a_break(tmp_path: Path):
    """Control: refusing an incomplete reference has not displaced the digests.

    A complete reference over an artefact whose bytes moved is the lock doing
    its own job, and must still reach the break verdict rather than a refusal.
    """
    whole = synthesise(tmp_path / "artefacts")
    (tmp_path / "artefacts" / "a.json").write_bytes(b"different bytes, same name\n")

    result = prepared(tmp_path, whole)

    assert result.returncode == 1, result.stdout
    assert "BEHAVIOUR LOCK BROKEN" in result.stdout
    assert "CHANGED  a.json" in result.stdout


def test_the_panel_logs_are_not_part_of_the_artefact_set(tmp_path: Path):
    """The set rule reads the artefacts a run leaves, and the logs are not among them."""
    directory = tmp_path / "artefacts"
    synthesise(directory)

    listed = subprocess.run(
        ["bash", "-c", f'LOCK_FUNCTIONS_ONLY=1 . "{SCRIPT}"\nproduced_artefacts "$1"\n', "x", str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert tuple(listed.stdout.split()) == ARTEFACTS


def test_a_captured_reference_is_one_a_verify_accepts(tmp_path: Path):
    """Round trip: what capture writes is what compare demands back.

    The two paths would drift apart silently — a capture whose digest lines
    took another tool's format still looks like a reference — so the control
    is that the pair agrees, not that either half matches a literal.
    """
    directory = tmp_path / "artefacts"
    synthesise(directory)
    reference = tmp_path / "SHA256SUMS"

    captured = capture(reference, directory)
    verified = compare(reference, directory)

    assert captured.returncode == 0, captured.stdout
    assert len(reference.read_text(encoding="utf-8").splitlines()) == len(ARTEFACTS)
    assert verified.returncode == 0, verified.stdout
    assert "BEHAVIOUR LOCK HELD" in verified.stdout


def test_a_capture_over_an_empty_directory_records_nothing(tmp_path: Path):
    """Guilty probe: a reference over no artefact is refused where it is made."""
    directory = tmp_path / "artefacts"
    directory.mkdir()
    reference = tmp_path / "SHA256SUMS"

    result = capture(reference, directory)

    assert result.returncode == 2, result.stdout
    assert not reference.exists()


def test_the_script_runs_through_the_functions_these_probes_drive():
    """Non-vacuity: the probed comparison must be the one a real verify runs.

    Every probe above drives the seam's functions directly, so they would go
    on passing if the script's own paths stopped calling them.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    commands = re.sub(r"(?m)(?:^|(?<=\s))#.*$", "", script)

    assert re.search(r'(?m)^compare_to_reference "\$REFERENCE" "\$OUT"$', commands)
    assert re.search(r'(?m)^    capture_reference "\$REFERENCE" "\$OUT"$', commands)
