"""The set-level write transaction: ``stage_all`` and ``commit_all``.

``stage_payload``/``StagedWrite.commit`` guarantee one path in isolation;
these two make a whole set of paths one transaction, which is the rule
ADR-0001 states and both command lines consume rather than restate. The
sweep below is the criterion, not a reproduction: every position crossed
with every failure kind, asserting both halves -- no temporary survives,
and every target still holds the bytes it held before the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from stompmodel import protocols
from stompmodel.protocols import Payload, StagedWrite, commit_all, stage_all


class _SimulatedFailure(Exception):
    """Marks a failure a test injects, distinct from a real ``OSError``."""


@dataclass
class _RefusingWrite:
    """A staged write that stages for real but will not commit."""

    path: Path

    def commit(self) -> int:
        raise _SimulatedFailure("no room on device")

    def discard(self) -> None:
        return None


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_staging_writes_no_target_and_commit_writes_all_of_them(tmp_path: Path) -> None:
    """Nothing reaches a target until ``commit_all``, and then all of it does."""
    targets: list[tuple[Path, Payload]] = [
        (tmp_path / "a.json", "⌀7.000"),
        (tmp_path / "b.bin", b"\x00\xff"),
    ]

    staged = stage_all(targets)

    assert not (tmp_path / "a.json").exists()
    assert not (tmp_path / "b.bin").exists()

    sizes = commit_all(staged)

    assert sizes == [8, 2], "the counts are the encoded byte counts, in order"
    assert (tmp_path / "a.json").read_text(encoding="utf-8") == "⌀7.000"
    assert (tmp_path / "b.bin").read_bytes() == b"\x00\xff"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.bin"]


def test_the_staged_writes_come_back_in_the_order_they_were_given(
    tmp_path: Path,
) -> None:
    """Positional, because a caller pairs them back up with its own labels."""
    names = ["c.txt", "a.txt", "b.txt"]

    staged = stage_all([(tmp_path / name, name) for name in names])

    assert [written.path.name for written in staged] == names


# --------------------------------------------------------------------------
# the sweep: every position x every failure kind
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "kind"),
    [
        (position, kind)
        for position in ("first", "middle", "last")
        for kind in ("staging", "the pre-commit read", "the commit")
    ],
)
def test_every_position_and_failure_kind_leaves_no_temporary_behind(
    position: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three real targets, seeded with distinct prior bytes so "restored" is
    distinguishable from "never written", swept across {first, middle,
    last} x {staging fails, the pre-commit read fails, the commit fails}.
    After the raise the directory holds exactly the three target names --
    no temporary of any shape -- and every target holds its seeded bytes.
    """
    index = {"first": 0, "middle": 1, "last": 2}[position]
    names = ["a.json", "b.drl", "c.svg"]
    prior = [b"OLD-A", b"OLD-B", b"OLD-C"]
    new_text = ["NEW-A", "NEW-B", "NEW-C"]
    targets = [tmp_path / name for name in names]
    for target, data in zip(targets, prior):
        target.write_bytes(data)
    rendered: list[tuple[Path, Payload]] = list(zip(targets, new_text))
    failing = targets[index]

    if kind == "staging":
        real_stage = protocols.stage_payload

        def fake_stage(path: Path, payload: Payload) -> StagedWrite:
            if path == failing:
                raise _SimulatedFailure("staging")
            return real_stage(path, payload)

        monkeypatch.setattr(protocols, "stage_payload", fake_stage)
        with pytest.raises(_SimulatedFailure):
            stage_all(rendered)
    else:
        staged = stage_all(rendered)
        if kind == "the pre-commit read":
            real_read_bytes = Path.read_bytes

            def fake_read_bytes(self: Path, *args: object, **kwargs: object) -> bytes:
                if self == failing:
                    raise _SimulatedFailure("read")
                return real_read_bytes(self, *args, **kwargs)

            monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
        else:
            real_commit = StagedWrite.commit

            def fake_commit(self: StagedWrite) -> int:
                if self.path == failing:
                    raise _SimulatedFailure("commit")
                return real_commit(self)

            monkeypatch.setattr(StagedWrite, "commit", fake_commit)

        with pytest.raises(_SimulatedFailure):
            commit_all(staged)

    # Undo the patches before inspecting the result: the assertions below
    # read the same targets and must see the real filesystem, not the
    # injected failure.
    monkeypatch.undo()

    assert sorted(p.name for p in tmp_path.iterdir()) == names, (
        f"a temporary survived the {kind!r} failure at the {position} position"
    )
    for target, data in zip(targets, prior):
        assert target.read_bytes() == data, (
            f"{target} was not restored to its seeded prior bytes after the "
            f"{kind!r} failure at the {position} position"
        )


# --------------------------------------------------------------------------
# the two rollback shapes, and the residual ADR-0001 excludes
# --------------------------------------------------------------------------


def test_a_commit_failure_removes_a_target_that_did_not_exist_before(
    tmp_path: Path,
) -> None:
    """The other half of putting a target back: one with no prior bytes goes."""
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    staged = [*stage_all([(first, "A")]), _RefusingWrite(second)]

    with pytest.raises(_SimulatedFailure):
        commit_all(staged)  # type: ignore[arg-type]

    assert not first.exists(), "a target created by this run was not removed again"
    assert not second.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_commit_failure_puts_back_the_target_already_replaced(
    tmp_path: Path,
) -> None:
    """Not merely "nothing new is written": the prior bytes are still there."""
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_bytes(b"previous")
    staged = [*stage_all([(first, "A")]), _RefusingWrite(second)]

    with pytest.raises(_SimulatedFailure):
        commit_all(staged)  # type: ignore[arg-type]

    assert first.read_bytes() == b"previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


def test_a_rollback_that_itself_fails_does_not_displace_the_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The residual ADR-0001 names, asserted rather than assumed.

    The second target refuses to commit and putting the first back refuses
    too. What must survive is the original failure, and the first target is
    left holding this run's bytes -- the one target ADR-0001 excludes.
    """
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_bytes(b"previous")
    staged = [*stage_all([(first, "A")]), _RefusingWrite(second)]
    seen = {"n": 0}

    def refuse_the_restore(path: Path, payload: Payload) -> StagedWrite:
        seen["n"] += 1
        raise OSError("the restore cannot be staged either")

    monkeypatch.setattr(protocols, "stage_payload", refuse_the_restore)

    with pytest.raises(_SimulatedFailure):
        commit_all(staged)  # type: ignore[arg-type]

    monkeypatch.undo()
    assert seen["n"] == 1, "the rollback did not attempt to restore the first target"
    assert first.read_bytes() == b"A", "the excluded residual is the one described"


def test_a_rollback_swallows_only_an_os_error_from_the_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the swallow above: it is narrow, not a bare ``except``.

    A restore that fails with something other than an ``OSError`` is not
    this rule's residual, so it propagates rather than being hidden --
    which a bare ``except Exception`` in ``_rollback`` would not do.
    """
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_bytes(b"previous")
    staged = [*stage_all([(first, "A")]), _RefusingWrite(second)]

    def explode(path: Path, payload: Payload) -> StagedWrite:
        raise KeyboardInterrupt("not an OSError")

    monkeypatch.setattr(protocols, "stage_payload", explode)

    with pytest.raises(KeyboardInterrupt):
        commit_all(staged)  # type: ignore[arg-type]


def test_a_staging_failure_never_touches_a_target(tmp_path: Path) -> None:
    """``stage_all`` refuses the whole set without writing any target."""
    good, bad = tmp_path / "a.txt", tmp_path / "absent" / "b.txt"
    good.write_bytes(b"previous")

    with pytest.raises(OSError):
        stage_all([(good, "A"), (bad, "B")])

    assert good.read_bytes() == b"previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


def test_the_rollback_uses_the_published_mechanism_rather_than_a_write_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named directly, not left to the structural gate: restoring prior bytes
    goes through ``stage_payload`` and the value it returns, so the one
    statement of how bytes reach a path stays the one statement."""
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_bytes(b"previous")
    staged = [*stage_all([(first, "A")]), _RefusingWrite(second)]
    real_stage = protocols.stage_payload
    restored: list[Path] = []

    def spy(path: Path, payload: Payload) -> StagedWrite:
        restored.append(path)
        return real_stage(path, payload)

    monkeypatch.setattr(protocols, "stage_payload", spy)

    with pytest.raises(_SimulatedFailure):
        commit_all(staged)  # type: ignore[arg-type]

    monkeypatch.undo()
    assert restored == [first]
    assert first.read_bytes() == b"previous"


def test_a_commit_failure_discards_every_write_still_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Including the one being attempted: it left ``pending`` only on success."""
    targets = [tmp_path / name for name in ("a.txt", "b.txt", "c.txt")]
    staged = stage_all([(target, target.name) for target in targets])
    discarded: list[Path] = []
    real_discard, real_commit = StagedWrite.discard, StagedWrite.commit

    def spy_discard(self: StagedWrite) -> None:
        discarded.append(self.path)
        real_discard(self)

    def fail_on_the_second(self: StagedWrite) -> int:
        if self.path == targets[1]:
            raise _SimulatedFailure("commit")
        return real_commit(self)

    monkeypatch.setattr(StagedWrite, "discard", spy_discard)
    monkeypatch.setattr(StagedWrite, "commit", fail_on_the_second)

    with pytest.raises(_SimulatedFailure):
        commit_all(staged)

    monkeypatch.undo()
    assert discarded == targets[1:], (
        "the write whose own commit raised must be discarded too, not only "
        "the ones after it"
    )


def test_committing_nothing_is_not_an_error(tmp_path: Path) -> None:
    """A run requesting no artefact stages and commits an empty set."""
    assert stage_all([]) == []
    assert commit_all([]) == []
    assert list(tmp_path.iterdir()) == []
