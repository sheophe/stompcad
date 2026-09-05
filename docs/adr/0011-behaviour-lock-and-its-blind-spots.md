# ADR-0011: The behaviour lock and its blind spots

**Status:** Accepted

## Context

[ADR-0006](0006-toolpath-ordering-and-hole-numbering.md) makes artefact bytes a
function of geometry alone. A refactor can nevertheless pass every assertion
while changing a byte no test examines.
`packages/stompdrill/tests/test_layer1_model.py:49`'s
`test_two_fresh_processes_emit_identical_bytes` checks that two runs of the same
commit agree. Comparing a change with its predecessor needs a separate capture
of the predecessor's output; the working tree holds only the current code.

The `stompmodel` extraction, the `stompgeom` extraction and the 2026-08
architecture review each used the same preservation procedure: run fixed panels
through the CLI, hash whole artefacts, and compare them with a reference captured
before the change. Each built a temporary harness under `.scratch/`, which is
ignored. Commit messages citing those runs were the only lasting record of the
procedure.

The harness needed a tracked home. Git cannot re-include a file whose parent
directory is excluded, so keeping it under `.scratch/` would leave future work
to reconstruct it again.

## Decision

Track the procedure in `tools/verify-lock.sh`, beside `build_catalogue.py`,
`check_docstrings.py`, `fetch_case_model.py` and `workspace_membership.py`.
References in commit messages can then point to a reviewable file.

Never commit `SHA256SUMS`, in `tools/` or elsewhere. Capture the reference at the
base commit for the change being checked, in a caller-selected directory that
defaults to `.scratch/lock`. It remains ignored.

A passing lock is evidence of byte preservation for its two runs. It does not
replace the suite. Five classes of behaviour outside its reach are described
below; they are explanatory limits, not a list of paths held fixed by a test.

Verification requires the reference to name exactly the artefacts produced by
the run. A reference with fewer or additional names is refused before comparing
digests. A subset would leave bytes unchecked; additional names mean the
reference describes a different output set, not simply changed bytes.

The set consists of every file left in the output directory except the panel
console logs. It is discovered from the directory, so newly named outputs join
both capture and comparison automatically. A fixed list, or a filter for the
current `a.`/`b.` prefixes, could silently omit them. Blank reference lines name
no artefact and are ignored without affecting the completeness check.

## Rationale

### Keep references local to a change

A reference should not be committed for four reasons.

First, the bytes depend on inputs outside the repository. A STEP header carries
the OpenCASCADE processor version, and its geometry comes from a Hammond model
fetched at run time. A different `cadquery-ocp` wheel or a re-fetched model can
change the digest without a repository change.

Second, the historical claim is that bytes stayed the same across a particular
change. A committed digest instead fixes expected bytes for HEAD. Every intended
output change would need a new digest, and a reviewer could not distinguish an
intended regeneration from an accidental one by reading the hash.

Third, the reviewable reference already exists as the fact-set golden
`packages/stompdrill/tests/golden/tar-1590b.json`. `docs/FOUNDATION.md`'s
instrument table permits regression against a reference as a recorded response,
not a recorded artefact. The golden stores facts because four of the five
artefacts carry the panel path as provenance; the STEP writer's literal
fallback is the exception. A byte golden would fail on legitimate path changes,
and committing digests would reverse both existing decisions.

Fourth, `.gitignore` cannot re-include a file below an excluded parent. The
comment beside `.scratch/` records this limit and explains why the harness moved.

### What the two runs do not cover

The lock runs two successful CLI invocations. This leaves five classes of
behaviour outside its reach:

1. **Paths requiring unused flags.** Neither panel passes `--grid`,
   `--grid-warn`, `--drill-standard`, `--drill-sizes`, `--case-face lid`,
   `--form-depth` or `--title`. The grid options, fractional standard and its
   labels, drawer narrowing and lid frame are not exercised.
2. **Failure paths.** Neither run reaches a rejecting diagnostic, usage failure,
   staged-artefact unwind or restore loop. The lock gives no evidence for
   [ADR-0001](0001-pipeline-and-emitter-adapters.md)'s and
   [ADR-0005](0005-binary-emitter-payloads.md)'s guarantee that any error withholds
   every requested artefact.
3. **Read-back.** Hashing emitted bytes does not read a document back. The
   versioned codec's `from_document` path is untested by the lock.
4. **Features absent from the fixtures.** Neither panel contains a Form XObject,
   so the nesting and clip-intersection walk described in `CLAUDE.md` is not
   exercised. The panels use only the two smallest ISO 5457 sheets, and neither
   overflows, leaving larger sheets and content-overflow markers untested.
5. **Stages outside `cli.build_pipeline`.** A stage available only to library
   callers cannot be reached through these CLI runs.

Re-measure these limits when relying on them. Run the script's two invocations
under `coverage run --branch --source=stompdrill,stompmodel,stompgeom` and inspect
`coverage report -m`.

A control does not hold these exclusions fixed. A useful control must fail for
a breach and pass for valid behaviour. If the lock starts exercising
`from_document`, for example, that improves coverage; a test asserting it
remains untested would reject the improvement. Such a test would also maintain a
changing inventory of unreached paths, which the repository's rules forbid.

### Verify reference completeness

Completeness can fail harmfully and silently: a reference might be edited,
truncated during capture, or left over from a harness producing another set.
`packages/stompdrill/tests/test_lock_reference_completeness.py` therefore tests
capture and comparison over a synthetic directory. It sources the script with
`LOCK_FUNCTIONS_ONLY` set, stopping before rendering.

Its controls cover:

- Refusal of a subset, an additional artefact name, an unterminated final row
  and an empty reference.
- A passing verdict for the unchanged whole set, including the reported count
  of compared artefacts.
- A break verdict, rather than refusal, when one artefact changes under a
  complete reference.

Calling the functions directly would not detect the script ceasing to use them.
A text scan therefore checks the calls in the script's own paths. The scan has
its own controls: it must report a call present only in a comment, and accept a
real call after reindentation, branch reformatting and an appended comment.

`LOCK_FUNCTIONS_ONLY` is checked in both contexts too. It must expose the
functions when the file is sourced, but refuse with an explanation when exported
into an executed run. Otherwise the script could exit successfully without
running a panel or comparing a byte.

### Verify coverage of registered emitters

The script's header claims that every registered emitter appears at least once.
Adding an emitter without updating the runs could silently invalidate that
claim. `packages/stompdrill/tests/test_documentation.py` checks it against the
registry. The same suite includes controls requiring an unrepresented format
to be reported and reordered flags or comment prose to be accepted.

## Consequences

Future work can reuse the tracked harness, and commit messages citing it refer
to a procedure readers can inspect.

The harness is opt-in and does not fix expected bytes for HEAD. Panel A requires
the cached `1590B` model, as the `--hammond` suite does. If it is missing, the
script reports the command to fetch it.

An uncaught Python exception can return exit 1, the same code used for panel
warnings. The harness therefore accepts CLI exit codes 0 and 1 only after
checking that every requested artefact exists and is non-empty. It clears the
previous run's output first, refuses missing or empty requested files, and
refuses to capture a reference over an empty set.

Capture before the change and verify against that reference within the same
change episode. An unrelated reference can report a false break. Both capture
and verification print the reference path, and keep artefacts beside it for
inspection when bytes differ.

One shared definition of the output set governs capture and verification.
Capture records exactly those names; verification demands exactly those names
before reading digests. Cleanup covers the same output directory, preventing
files from an older harness from joining the current set.

Verification also counts the reference rows actually compared. A final row
without a newline can be named by the set check but missed by the shell read
loop; the count detects that incomplete comparison.

The digest format is the one written by `shasum -a 256` and `sha256sum`.
References from an earlier harness remain valid if it emitted the same set.
The architecture review's copy under `.scratch/` remains untouched for the
review in progress and disappears with that ignored directory.

The shell script is outside `ruff`, `mypy` and the docstring audit. Two Python
gates cover it explicitly: the emitter-coverage check reads its text, and the
completeness controls source it and exercise capture and verification. The
repository's other Python checks do not validate the script.
