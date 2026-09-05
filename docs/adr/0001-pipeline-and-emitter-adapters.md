# ADR-0001: Processing architecture and artefact consistency

**Status:** Accepted, amended by
[ADR-0009](0009-shared-model-package-and-dependency-order.md), which moves
`Stage`, `Pipeline` and `Emitter` into `stompmodel` and makes them generic in
the value they process. Shared facts still have one owner and are computed once.
An amendment in place moves target validation (`target_key`/`check_target_set`)
and write transactions (`stage_all`/`commit_all`) into `stompmodel.protocols`.
`stompdrill.cli` and the `stompcollider` command line now use these published functions.

## Context

`stompdrill` reads measured drill geometry and can emit several representations of the
same panel. Every artefact from one invocation must describe the same accepted holes,
tool set, ordering, diagnostics and processing provenance. Computing these facts
independently in each emitter would allow the outputs to disagree.

The architecture needs clear boundaries between measured source data, canonical drill
data, processing that changes shared facts, and presentation that represents those facts.

## Decision

### Processing and emission

`AiPdfSource` produces unquantised `RawDrillData`. `quantise()` turns those
measurements into canonical `DrillData`. A `Pipeline` then applies `Deduplicate`,
`ReviewGridTies`, `RouteHoles` and `CheckOutlineContainment` as independent stages,
each accepting and returning `DrillData`. A supplied case model also enables
`CheckCaseClearance`.

All facts shared by more than one artefact are computed once before emission and
carried on `DrillData`, including diagnostics and processing provenance. Emitters
serialise that document. They may convert units and coordinate frames or format
text, but must not quantise, deduplicate, classify, sort or re-derive shared facts.
Presenting an already assigned drill sequence is covered by
[ADR-0006](0006-toolpath-ordering-and-hole-numbering.md).

Repeatable `--emit FORMAT=PATH` arguments select any number of outputs, including
none. A format may be requested more than once, so the number of artefacts is not
limited by the number of registered formats. Payloads may be text or bytes; see
[ADR-0005](0005-binary-emitter-payloads.md).

Emitter registration maps formats to emitters without changing the processing
contract. The CLI explicitly composes the ordered post-quantisation stages;
`Pipeline` applies them in that order, and each stage remains independent.
ADR-0001, Figure 1 shows the processing blocks and transferred document types.

```mermaid
flowchart LR
    source["AiPdfSource"]

    subgraph quantise["quantise()"]
        direction TB
        footprint["IdentifyHammondFootprint"]
        snap_drill["SnapDiametersToDrillTable"]
        snap_position["SnapPositions"]
        footprint -.-> snap_drill
        snap_drill -.-> snap_position
    end

    subgraph pipeline["Pipeline"]
        direction LR
        dedupe["Deduplicate"]
        ties["ReviewGridTies"]
        route["RouteHoles"]
        contain["CheckOutlineContainment"]
        clearance["CheckCaseClearance<br/>(conditional)"]
        dedupe -->|DrillData| ties
        ties -->|DrillData| route
        route -->|DrillData| contain
        contain -.->|DrillData, if --case-model| clearance
    end

    excellon["ExcellonEmitter"]
    drawing["DrawingSvgEmitter"]
    drawing_pdf["DrawingPdfEmitter"]
    json["JsonEmitter"]
    step["StepEmitter"]
    selected{"--emit FORMAT=PATH<br/>argument (repeatable)"}

    source -->|RawDrillData| quantise
    quantise -->|DrillData| dedupe
    contain -->|DrillData| selected
    clearance -.->|DrillData| selected
    selected -->|DrillData| excellon
    selected -->|DrillData| drawing
    selected -->|DrillData| drawing_pdf
    selected -->|DrillData| json
    selected -->|DrillData| step
```

Figure 1 — Processing blocks, aggregate boundaries, and transferred document types.

### Validating output targets

One invocation's artefacts form one transaction: all requested artefacts are written,
or every target is left as it was, subject to the restoration exclusion below.
An ERROR diagnostic withholds all artefacts before rendering begins.

Before rendering, `check_target_set` validates the requested paths together:

- No two targets may reach the same file.
- Every existing target must be a regular file. The transaction reads its previous
  bytes before replacement; reading a named pipe or character device could block.

`target_key` compares each target's resolved path using canonical caseless matching
in the sense of UAX #15 D145. Resolution catches aliases through symlinks or relative
prefixes. Folding case and normalisation catches spellings that a filesystem could
hold as one file. This folding applies on every host: the filesystem's behaviour
cannot be established before a target exists, and `samefile` requires both targets
to exist. The key is used only for collision checks; output goes to the caller's
original path.

The per-path write requirements belong to `stage_payload`, as described in
ADR-0005. It checks them during staging, before any target is replaced. A target
outside that function's domain therefore withholds the whole set, though the
payloads have already been rendered. Passing target validation does not guarantee
that a later commit will succeed.

### Rendering, staging and committing

Every payload is rendered before any target path is touched. `stage_all` then
stages each payload to a temporary file beside its target. Only after every staging
write succeeds does `commit_all` replace the targets, in request order.

Before each commit, `commit_all` reads that target's previous bytes if it exists.
If rendering, staging, a read or a commit fails, the transaction discards pending
writes and restores targets already replaced. This covers emitter faults, refused
writes and a later replacement failing after an earlier one succeeded.

Restoration uses `stage_payload` and `StagedWrite.commit`, the same mechanism as
the original write. A target absent before the run is restored by deleting it;
that deletion is the only filesystem operation the rollback performs directly.
Neither command line implements a separate write mechanism or transaction loop.
Each keeps only the report sentence built from the byte count returned by a commit.

The pending set includes the write currently being attempted. A write leaves that
set only after its commit returns successfully. On failure, `StagedWrite.discard`
removes all remaining staged writes, including the one whose read or commit failed.
Tickets 29 and 35 enforce this cleanup invariant.

### Restoration exclusion and durability limits

Restoring an already replaced target relies on its saved bytes still being the
correct contents to restore. This guarantee excludes another process changing that
target between the read and rollback, and a restoring write failing for a reason
that pre-flight validation could not detect. In those cases, restoration of that
target is not guaranteed; it may retain this run's bytes. The original failure
that triggered rollback propagates, rather than a second restoration failure.

Closing the race would require a lock that these command lines do not take.
Atomicity against other processes, fsync and durability against power loss are
outside this decision's guarantee.

ADR-0005 defines the matching guarantee for one path. `stompmodel.protocols`
publishes the set-level functions here because both `stompdrill` and
`stompcollider` compose several artefact paths in one invocation.

## Rationale

The transition from `RawDrillData` to `DrillData` makes the quantisation boundary
visible in the types. Computing shared facts before selecting emitters gives all
outputs the same answers. Independent stages keep their own responsibilities,
while the invocation's composition shows their order.

Diagnostics and provenance describe the same decisions as the accepted geometry.
Carrying them together lets console, drawing and machine-readable output present
the same findings without repeating the calculations.

## Consequences

Every emitter receives the same fully processed `DrillData`. Differences between
artefacts are limited to presentation. A new emitter consumes this contract and
must not introduce a parallel processing path. Changes to shared facts belong
before emission and must update the canonical document.

The separation between quantisation, stages and emitters requires callers and
maintainers to preserve the typed flow. Domain decisions must stay out of
format-specific code.

Staging costs one temporary file per target, present briefly beside it until the
set commits or is abandoned. `stage_all` uses `stage_payload`; `commit_all` uses
`StagedWrite.commit`; both use `StagedWrite.discard` for abandoned writes. Saving
and restoring prior bytes adds bookkeeping around that shared mechanism.

Subject to the restoration exclusion, each target ends with either this run's
complete artefact or exactly its previous bytes. No temporary created by the
invocation survives a commit, rollback or failure.

This is a guarantee about paths. `StagedWrite.commit` replaces a name: at the
per-path level, a symlink or named pipe becomes a regular file, as ADR-0005
explains. The command lines apply the stricter regular-file pre-flight above.
The transaction does not add concurrency or durability guarantees beyond those
stated here.
