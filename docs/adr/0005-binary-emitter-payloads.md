# ADR-0005: Binary emitter payloads

**Status:** Accepted

## Context

`Emitter.emit` originally returned `str`, and the command line wrote every artefact with
`path.write_text(text, encoding="utf-8")`. Excellon, JSON and SVG all use text, so they
fit this contract.

PDF needs a byte payload. Its cross-reference table contains byte offsets, so converting
it through a text contract would make encoding part of the format's correctness.

## Decision

### Payloads and writes

The emitter payload is `Payload = str | bytes`. Text emitters continue to return `str`;
binary emitters return `bytes`.

`stompmodel.protocols.stage_payload` handles both. It encodes text as UTF-8 and writes
the complete payload to a temporary file beside the target. `StagedWrite.commit` is the
only function in the emission path that writes to a caller-visible output path;
`StagedWrite.discard` abandons a staged write. The command line builds its report from
the byte count returned by `commit`.

The restriction concerns requested output paths. `stompgeom.writer.render_step` also
uses a scratch file because the kernel writer accepts only a path. `render_step` returns finished
STEP bytes and leaves no file for the caller. Publishing those bytes to the requested
path still goes through `StagedWrite.commit`.

The original decision implemented payload dispatch directly in the command line:

```python
def _write(emitter: Emitter, path: Path, payload: Payload) -> str:
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        size = len(payload)
    else:
        path.write_text(payload, encoding="utf-8")
        size = len(payload.encode("utf-8"))
    return f"wrote {path}  ({emitter.name}, {size} bytes)"
```

All artefacts are rendered before any output path is written. An emitter failure
therefore withholds every output.

`stage_payload` writes the temporary, then `StagedWrite.commit` renames it into place.
Afterwards the target holds either the complete payload or exactly its previous
contents, and no temporary remains. When abandoning a staged write, the caller removes
the temporary with `StagedWrite.discard`. Callers never receive a truncated artefact.

Staging and committing were split from the original single operation so that callers
can stage an entire set before replacing any target. Both command lines now use this
set-level transaction through the functions described in
[ADR-0001](0001-pipeline-and-emitter-adapters.md).

### Completing a staged write

A caller must invoke exactly one of `StagedWrite.commit` and `StagedWrite.discard` on
every value returned by `stage_payload`. These are methods because the temporary belongs
to the value. Callers need the value to complete the write and never name its temporary.
The per-path API consists of `stage_payload` and the value it returns.

The API does not detect a caller dropping an unfinished `StagedWrite`. The following
options were considered and rejected:

- A `__del__` method raising `ResourceWarning` cannot detect a path that no test runs.
  The warning is ignored by default; promoting it to an error in every member's pytest
  configuration would also report unrelated unclosed handles in `pikepdf` and the
  geometry kernel. It would put a filesystem probe in finalisation of a frozen value,
  where failures at interpreter shutdown can go unreported.
- `weakref.finalize` needs a `__weakref__` slot. Support for adding that slot to a
  slotted dataclass requires a Python version above the workspace's declared minimum.
- A required context manager cannot directly span the two functions. An exit stack
  passed through callers could do so, but would restructure ADR-0001's transaction
  without changing its behaviour.
- A static source check cannot usefully follow the call patterns in this workspace.
  Some calls stage and complete a write in one expression; others stage values into a
  collection and complete them by iterating it elsewhere. The first pattern trivially
  satisfies the check, while the second gives it no local binding to follow. A check
  that finds no obligation to inspect would not provide evidence of cleanup.

Caller-side tests check for abandoned temporaries. `stompdrill`'s command-line suite
asserts that none remain at every injected failure position. This checks ADR-0001's
set-level rule; a second tool inherits the testing convention with the mechanism.

### Target requirements

The target's parent directory must already exist and accept a new file. The target
itself must not be a directory. These requirements allow `stage_payload` to create a
sibling temporary and `StagedWrite.commit` to rename it onto the target. The mechanism
enforces both requirements; callers need no separate probes.

`stage_payload` rejects an existing directory target before creating a temporary.
Deferring that check until rename would discover an invalid target only after the caller
had begun committing the set. The test is
`test_staging_at_a_directory_target_raises_before_any_temporary_exists` in
`stompmodel`'s suite.

The filesystem detects other failures when the write is attempted: a missing parent,
a parent that is not a directory, or a parent that refuses new files. These are checked
by `test_a_target_whose_directory_is_missing_still_raises_an_os_error`,
`test_a_target_whose_parent_is_not_a_directory_names_the_target` and
`test_a_parent_that_refuses_a_new_file_names_the_target`. Every raised exception retains
its standard errno-mapped subclass and names the target in its filename, rather than
the private temporary.

The per-path mechanism accepts any non-directory target, including a named pipe, if its
parent accepts the temporary. Committing replaces that node with a regular file; see
`test_committing_a_staged_write_can_replace_a_named_pipe_with_a_regular_file`.
An unprivileged caller's `/dev` target usually fails because the parent refuses new
files, independently of the target node's type.

A symlink target also becomes a regular file containing the new payload. The file it
previously pointed to is left unchanged, as checked by
`test_committing_a_staged_write_replaces_a_symlink_target_with_a_regular_file`.
The rename replaces the target's name.

A caller that reads the target before replacement has additional requirements, including
readability. Such a caller might compare a target with a supplied model or save previous
bytes for rollback. These requirements belong to that caller's pre-flight policy;
ADR-0001 records the command lines' stricter target checks.

## Rationale

Adding `binary: ClassVar[bool]` beside `media_type` and `extension` would duplicate a fact
already expressed by the payload's type. The flag could disagree with the payload;
`isinstance` uses the value itself.

Requiring every emitter to return `bytes` was also rejected. The three existing emitters
and their tests use text, and a text artefact can legitimately be represented as `str`.

## Consequences

Binary formats use the same write mechanism as text formats. Consumers of `Emitter` must
accept the union; `mypy` detects callers that still assume every payload is `str`.

The report counts encoded bytes for both payload types. Text is encoded as UTF-8 and
written as bytes, without platform newline translation. The returned count is therefore
the untranslated encoded length on every platform.

This per-path guarantee supports the requirement that every artefact from an invocation
must agree. Whether the whole set is written or withheld belongs to ADR-0001's
transaction, outside this ADR's scope.

`stompcollider` uses the byte count from
`stompmodel.protocols.stage_payload`/`StagedWrite.commit`, so both tools report it by the
same convention. This satisfies ADR-0009's admission rule 2 (contract): `stompcad`
depends on consistent reporting and byte counts across the tools it orchestrates.
