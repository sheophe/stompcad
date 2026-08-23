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

The dispatch on the value is `stompmodel.protocols.write_payload`, the only function in
the emit path that writes a **caller-visible** file; the command line owns the report it
prints around the count that function returns. The qualifier is load-bearing:
`stompgeom.writer.render_step` writes its own STEP bytes through a scratch file first,
because the kernel's writer exposes no in-memory target, only a path — but that write is
forced by the kernel's path-only API, is invisible to callers, and is why the claim
needed the qualifier at all. `render_step` returns finished bytes and leaves nothing on
disk a caller can observe; `write_payload` remains the only function whose file a caller
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

`write_payload` writes to a temporary file beside the target and renames it into place,
so the same declaration this ADR already makes — the one function where an artefact's
bytes reach a path and are counted — now also covers what a failure at that path leaves
behind: the write is all-or-nothing for one path. Afterwards the target holds either the
complete payload or exactly what it held before, and the temporary does not survive
either outcome. A caller never observes a truncated artefact and never needs to know the
mechanism that prevents it.

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

`stompcollider` inherits this counting convention from `stompmodel.protocols.write_payload`
rather than re-deriving it, which is what makes "means the same thing for both kinds of
payload" hold across two tools rather than within one — the move satisfies ADR-0009's
admission rule 2 (contract), naming `stompcad`'s dependence on one report and one
byte-counting convention across both tools it orchestrates.
