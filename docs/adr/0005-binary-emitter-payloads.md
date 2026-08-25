# ADR-0005: Binary emitter payloads

**Status:** Accepted

## Context

`Emitter.emit` returned `str`, and the command line ended every artifact in
`path.write_text(text, encoding="utf-8")`. Excellon, JSON and the SVG drawing are all
text, so the contract and its single writing site agreed.

A PDF drawing does not. PDF is a byte format whose cross-reference table holds byte
offsets, so it cannot travel a contract that promises text without the encoding step
becoming part of the format's correctness.

## Decision

The emitter payload is `Payload = str | bytes`. An emitter returns whichever its format
is; a text emitter continues to return `str` and is unchanged.

The dispatch on the value is `stompmodel.protocols.stage_payload`, which encodes the
payload and writes it in full to a temporary beside its target. `StagedWrite.commit` is the
only function in the emit path that puts bytes at a **caller-visible** path, and
`StagedWrite.discard` the only one that abandons them; the command line owns the report it
prints around the count `StagedWrite.commit` returns. The qualifier is load-bearing:
`stompgeom.writer.render_step` writes its own STEP bytes through a scratch file first,
because the kernel's writer exposes no in-memory target, only a path — but that write is
forced by the kernel's path-only API, is invisible to callers, and is why the claim
needed the qualifier at all. `render_step` returns finished bytes and leaves nothing on
disk a caller can observe; `StagedWrite.commit` remains the only function whose file a caller
asked for. As first taken, that dispatch was the command line's own:

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

Every artifact is still rendered before any path is written, so a failure in one emitter
withholds all of them.

`stage_payload` writes to a temporary file beside the target; `StagedWrite.commit` renames it
into place. Afterwards the target holds either the complete payload or exactly what it
held before, and the temporary survives neither outcome — `StagedWrite.discard` removes it
explicitly when a caller abandons the write instead of committing it. A caller never
observes a truncated artefact and never needs to know the mechanism that prevents it.
The write is split across two calls, rather than made in one as it first was, because
today's only caller must stage a whole set of artefacts before committing any of them —
see ADR-0001 — and a single write-and-rename call cannot be paused between the two
halves.

### The obligation is one verb on one value, and it is deliberately not enforced

`stage_payload` hands back a `StagedWrite`, and exactly one of `StagedWrite.commit`
and `StagedWrite.discard` is owed on every value it hands out. The verbs are the
value's own methods because the temporary is the value's own state: a caller can no
longer reach a verb without the value it applies to, and cannot name the temporary at
all. That narrows what the module publishes — `stage_payload` and the value it returns
are the whole surface — without narrowing what it can do, because the split across two
calls the paragraph above requires is unchanged.

Nothing detects a `StagedWrite` a caller stages and then drops. That is a weighed
decision rather than an omission, and these are the candidates it weighed:

- A `__del__` raising `ResourceWarning` does not see the breach that raised this
  question, because a value dropped on a path no test exercises has no destructor run
  to report it. `ResourceWarning` is default-ignored, so making it bite would mean
  promoting it to an error across every member's pytest configuration, which
  immediately grades unrelated unclosed handles in `pikepdf` and the geometry kernel.
  It also puts a filesystem probe inside a frozen value's finalisation, whose own
  failure mode at interpreter shutdown is silence. It is refused on merit, not on
  impossibility.
- `weakref.finalize`, the deterministic form of the same idea, needs a `__weakref__`
  slot that a slotted dataclass gains only above this workspace's declared Python
  floor.
- A required context manager cannot express a pause that spans two functions, so it is
  reachable only through an exit stack threaded through every caller — restructuring
  the set-level transaction ADR-0001 owns, for no change in behaviour.
- A static gate over workspace source can only judge the shape a caller writes in the
  frame that staged the write. Every production call here composes a set, staging into
  a collection rather than binding a name a gate could follow to its discharge, so such
  a gate has no subject to judge and could pass only by finding nothing.

What does catch an abandoned temporary is the caller-side residue assertion a caller
composing a set already makes: `stompdrill`'s command line asserts, at every failure
position its suite injects, that no temporary survives. ADR-0001 owns the set-level
rule that assertion checks, and a second tool inherits the convention together with the
mechanism.

**Target domain.** `stage_payload` needs to create a fresh temporary beside the target,
and `StagedWrite.commit` needs to rename onto it. Together they define the only domain a
target must satisfy: its parent directory must already exist and accept a new file, and
the target itself must not already be a directory, because a rename can never land bytes
there. The mechanism states this domain and enforces every clause of it itself; no
caller-side probe of these facts is needed or published.

Exactly one of those two clauses is checked ahead of the write: a target that is already
a directory is refused by `stage_payload` before any temporary is written, because the
alternative — waiting for `StagedWrite.commit`'s rename to fail — surfaces the violation one
target too late for a caller withholding a whole set to withhold it as a whole (test:
`test_staging_at_a_directory_target_raises_before_any_temporary_exists`, in
`stompmodel`'s own suite). Every other clause — a missing parent, a parent that is not a
directory, a parent that refuses a new file — is answered by the filesystem itself, at
the write attempt that actually needs the answer, so no caller repeats a probe of its own
(tests: `test_a_target_whose_directory_is_missing_still_raises_an_os_error`,
`test_a_target_whose_parent_is_not_a_directory_names_the_target`,
`test_a_parent_that_refuses_a_new_file_names_the_target`). In every case the raised
exception keeps its standard errno-mapped subclass, and its filename names the target —
never the mechanism's own temporary, whose name a caller never otherwise learns.

Nothing here requires the target to be a regular file: `StagedWrite.commit`'s rename replaces
whatever non-directory node currently occupies the target's name, whatever type of node
that is, rather than requiring it to already be an ordinary file — so a named pipe
qualifies for this mechanism exactly as an ordinary file does, provided its parent will
accept the sibling temporary (test:
`test_committing_a_staged_write_can_replace_a_named_pipe_with_a_regular_file`). A target
whose parent refuses new files, as an unprivileged caller usually finds `/dev` does,
falls outside the domain for that reason alone, not because of what kind of node the
target is.

Committing replaces the target's *name*, not the file its name used to resolve to: a
symlink standing where the target should be is afterwards a regular file holding the new
payload, deliberately, and whatever file the link pointed at is left completely alone
(test: `test_committing_a_staged_write_replaces_a_symlink_target_with_a_regular_file`).

A caller that needs to read a target before replacing it — to compare it against a
supplied model before deciding whether to proceed, say — needs more of that target than
this mechanism does: readability, and possibly more, neither of which staging or
committing ever asks for. That further requirement belongs to the caller, not to this
mechanism, and is stated where that caller's own pre-flight is: ADR-0001, for
`stompdrill`'s command line.

## Rationale

A `binary: ClassVar[bool]` alongside `media_type` and `extension` would match the
protocol's existing shape, but it is a second claim about the payload that can contradict
the payload itself. `isinstance` cannot disagree with the value it is given.

Requiring `bytes` from every emitter was rejected for the opposite reason: three existing
emitters and their suites produce and assert text, and an artifact a person reads is
legitimately a string.

## Consequences

A binary format is now expressible without a parallel writing path. The cost is one
branch at one site, and a union that every consumer of `Emitter` must accept: a caller
that assumes `str` is now wrong, and `mypy` says so.

The reporting line still counts encoded bytes, so its number means the same thing for
both kinds of payload. Text payloads still keep their existing newline handling — nothing
about writing through a temporary changes how a "\n" in the payload reaches disk — and
the returned count remains the untranslated encoded length on every platform.

This per-path guarantee is one half of a larger claim CLAUDE.md makes: "every artefact
from one invocation must agree." Whether a whole invocation's artefacts land or withhold
together as a set is a fact about the caller's loop over several paths, not about this
one function, and stays out of this ADR's scope; ADR-0001 owns it.

`stompcollider` inherits this counting convention from
`stompmodel.protocols.stage_payload`/`StagedWrite.commit` rather than re-deriving it, which is
what makes "means the same thing for both kinds of payload" hold across two tools rather
than within one — the move satisfies ADR-0009's admission rule 2 (contract), naming
`stompcad`'s dependence on one report and one byte-counting convention across both tools
it orchestrates.
