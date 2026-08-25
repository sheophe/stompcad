# ADR-0011: The behaviour lock and its blind spots

**Status:** Accepted

## Context

[ADR-0006](0006-toolpath-ordering-and-hole-numbering.md) makes an artefact's bytes
a function of the geometry alone. That guarantee creates a class of change the
test suite structurally cannot see: a refactor that keeps every assertion green
while moving a byte nobody asserted about.
`packages/stompdrill/tests/test_layer1_model.py:49`'s
`test_two_fresh_processes_emit_identical_bytes` proves two runs *of one commit*
agree with each other. Nothing in the tree compares a commit against its
predecessor, and nothing in the tree can, because a working tree only ever holds
one commit's code.

Three preservation programmes have run in this workspace with the same success
condition — the `stompmodel` extraction, the `stompgeom` extraction and the 2026-08
architecture review — and each one built the same throwaway harness: drive the
command line over fixed panels, hash whole artefacts, compare against a reference
captured before the change. Each harness lived under `.scratch/`, which
`.gitignore` excludes wholesale, so the commit messages citing the lock as their
evidence were the only surviving record of what the lock actually did. Tracking
the harness where it stood is not possible: git cannot re-include a file whose
parent directory is excluded. The choice was to move it, or to leave the procedure
undescribed for a fourth programme to rebuild.

## Decision

**The procedure is tracked; the reference is not.**

- `tools/verify-lock.sh` is a tracked repository tool, beside
  `build_catalogue.py`, `check_docstrings.py`, `fetch_case_model.py` and
  `workspace_membership.py`. The commit messages citing the lock resolve to a file
  somebody can read.
- **No `SHA256SUMS` is ever committed**, in `tools/` or anywhere else. A reference
  is captured at a change episode's base commit into a directory the caller names,
  defaulting to `.scratch/lock`, and stays ignored.
- **A green lock is not a green suite.** Five causal classes bound what a green run
  reaches. They are stated as classes rather than as an enumeration of unreached
  paths, and they are deliberately not pinned by a control.

## Rationale

**Why the reference is not committed.** Four reasons, two of which would reverse
decisions already accepted elsewhere in this repository.

*The digests are not a fact about this repository.* The STEP artefact's header
carries the OpenCASCADE processor's own version string, and the artefact descends
from a Hammond model fetched at run time and never committed. A committed
reference therefore goes red on a different `cadquery-ocp` wheel, or on a
re-fetched model, for no change in this repository at all. Noise on an innocent
change is a failure mode exactly as real as silence on a breach.

*A committed digest makes the wrong claim.* Every citation of the lock in this
history asserts "nothing moved **across this change**" — a statement about a pair
of commits. A committed digest instead asserts "HEAD's bytes are these", which
every intended change must regenerate; and a regenerated digest is unreviewable,
because a reviewer cannot tell an intended regeneration from an accidental one.

*The reviewable form is already committed, and the refusal already recorded.*
`packages/stompdrill/tests/golden/tar-1590b.json` is the fact-set golden a reviewer
can read. `docs/FOUNDATION.md`'s instrument table admits regression against a
reference only as a recorded response, never as a recorded artefact, and
`docs/specs/verification-technical.md` states plainly that golden is a fact-set and
not bytes, because the panel path is provenance in four of the five artefacts — the
STEP writer falling back to a literal is the exception — so a byte-golden fails on
legitimate change. Committing a digest would reverse both by side effect.

*`.gitignore` cannot express the exception.* Git will not re-include a file whose
parent directory is excluded, so a negation pattern is not available. The comment
beside the `.scratch/` rule records that, so nobody spends another branch
rediscovering it.

**The five classes a green lock does not enter.** The lock runs exactly two
successful command-line invocations, and everything below follows from that one
fact rather than from a list somebody wrote out.

1. **Any path reached only through a flag those invocations do not pass.** Neither
   panel passes `--grid`, `--grid-warn`, `--drill-standard`, `--drill-sizes`,
   `--case-face lid`, `--form-depth` or `--title`, so the grid family, the
   fractional standard and its labelling, the drawer narrowing and the lid frame
   are all unentered.
2. **Every failure path.** Both panels succeed, so no rejecting diagnostic fires,
   no usage failure is reached, and neither the staged-artefact unwind nor its
   restore loop is entered. **A green lock is therefore silent about
   [ADR-0001](0001-pipeline-and-emitter-adapters.md)'s and
   [ADR-0005](0005-binary-emitter-payloads.md)'s "any error withholds every
   requested artefact"** — the claim a byte-comparison harness looks most like it
   should cover, and covers not at all.
3. **Read-back.** The lock hashes what the emitters wrote and never reads a
   document back, so the whole `from_document` half of the versioned codec is
   unentered.
4. **Whatever the two fixtures do not contain.** Neither carries a Form XObject, so
   the nesting and clip-intersection walk `CLAUDE.md` devotes four bullets to is
   unentered; the panels select the two smallest ISO 5457 sheets, so no larger
   sheet is ever chosen; and neither overflows, so no content-overflow marker is
   drawn.
5. **Anything outside `cli.build_pipeline`.** The lock drives the command line, so a
   stage reachable only by a library caller is structurally out of reach.

Do not trust that statement where it matters — re-measure it. Run the script's two
invocations under `coverage run --branch --source=stompdrill,stompmodel,stompgeom`
and read `coverage report -m`.

**Why no control pins those classes.** A control needs a guilty probe that must
make it fail and an innocent probe that must not. Here the only way to make "the
lock does not enter `from_document`" false is to *improve* the lock, so the guilty
probe and the innocent probe are the same event and the gate would fire on exactly
the change it should welcome. That is an anti-instrument. It would also put a
drifting enumeration of unreached paths under test, in a tracked document, which
this repository forbids.

**Why the complementary claim is pinned.** The script's header claims every
registered emitter appears at least once. That claim can go false *silently in the
harmful direction*: register a sixth emitter, touch nothing else, and both the
header and this ADR quietly overclaim. It is therefore checked mechanically against
the registry by `packages/stompdrill/tests/test_documentation.py`, with a guilty
probe (a format the script never emits must be named) and an innocent probe
(reordered flags and comment prose must not be) beside it in the same suite.

## Consequences

The commit messages citing the behaviour lock now resolve to a tracked file, and a
fourth preservation programme inherits the harness rather than rebuilding it.

The harness is opt-in and is not a gate on HEAD. Panel A needs the `1590B` model in
the cache, exactly like the `--hammond` suite, and the script refuses with the fetch
command rather than failing obscurely.

A panel that crashes and a panel that warns both leave the command line's exit code
at one, so a successful exit is not evidence that anything was written. The harness
clears the previous run's artefacts before the panels run, refuses to hash a panel
that wrote none of the artefacts it was asked for, and refuses to record a reference
over nothing — the same rule as the empty-reference guard, on the side that creates
the reference, where believing a run that did not happen does the greater damage.

A reference captured at a different commit reports a false break, so the discipline
is capture-then-verify within one episode. The script echoes the reference path it
used, and keeps the artefacts beside it, so a break can be diffed rather than
guessed at.

The digest format is `shasum -a 256`'s, which `sha256sum` also writes, so a
reference captured by an earlier copy of the harness remains valid input. The
architecture review's own copy under `.scratch/` is left in place and untouched for
the review in flight; it is ignored and dies with that directory.

**A tracked shell script is seen by neither `ruff` nor `mypy` nor the docstring
audit.** The emitter-coverage gate is its only automatic protection, and this ADR
states that rather than leaving a reader to assume the repository's Python gates
reach it.
