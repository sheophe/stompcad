#!/usr/bin/env bash
# Byte-comparison harness: two panels, every registered emitter, hashed.
#
# What it is for: proving that a change which must move no artefact byte moved
# none. Capture a reference on the base commit, make the change, run again.
# What it is NOT: a gate on HEAD. No reference is committed -- the digests carry
# the kernel build's own version string and descend from a Hammond model fetched
# at run time. ADR-0011 gives the reasons and bounds what a green run proves.
#
# Two panels, chosen to cover different paths:
#   A  tar.ai with a declared case and a supplied model -- runs the clearance
#      stage and the STEP cutter, and carries a duplicate-hole warning.
#   B  pax.ai with neither -- runs the outline-containment path instead, has
#      three tools rather than two, and reports a non-circular-path info.
# Every emitter in the registry appears at least once; that claim is checked by
# packages/stompdrill/tests/test_documentation.py, not left to the eye.
#
# Usage: bash tools/verify-lock.sh [DIR]        (DIR defaults to .scratch/lock)
#   DIR/SHA256SUMS absent  -> capture it;  present -> compare against it.
#   Artefacts are kept in DIR/artefacts either way, so a break can be diffed;
#   the previous run's are cleared first, so nothing stale is ever hashed.
#   A verify compares the whole set both sides name, so a reference that has
#   lost rows, or gained one this harness no longer writes, is refused rather
#   than certified over the artefacts it still happens to cover.
# Exit: 0 identical or captured, 1 a byte differs, 2 a run or precondition failed.
set -uo pipefail

# --- the seam the committed control drives -------------------------------
# packages/stompdrill/tests/test_lock_reference_completeness.py sources this
# file with LOCK_FUNCTIONS_ONLY set and calls the four functions below over a
# synthetic directory, so the comparison is probed without rendering artefacts.

sha256() {  # sha256sum on most Linux distributions, shasum on macOS; both print
            # "<digest>  <name>", which is the reference file's format.
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"
    else shasum -a 256 "$@"; fi
}

produced_artefacts() {  # produced_artefacts <dir>: the artefact names a run left
                        # there, sorted. One rule, so capture and verify cannot
                        # come to disagree about what "the set" means.
    (cd "$1" 2>/dev/null || return 0
     for name in a.* b.*; do
        case "$name" in *.log | 'a.*' | 'b.*') continue ;; esac
        [ -f "$name" ] && printf '%s\n' "$name"
     done | LC_ALL=C sort)
}

capture_reference() {  # capture_reference <reference> <dir>
    # Records exactly the set produced_artefacts names, so a later verify has
    # the whole set to demand back. The digests go through the shell function
    # one name at a time: xargs would find whatever `sha256` is on PATH.
    local reference="$1" dir="$2" name
    (cd "$dir" && produced_artefacts . | while IFS= read -r name; do
        sha256 "$name"
     done) > "$reference"
    if [ ! -s "$reference" ]; then
        rm -f "$reference"
        echo "LOCK FAILED: the panels left nothing to hash, so nothing was"
        echo "  captured; a reference over no artefact is not a reference."
        return 2
    fi
    echo "reference captured: $reference"; cat "$reference"
    return 0
}

compare_to_reference() {  # compare_to_reference <reference> <dir>
    # The reference must name exactly the set the run produced. Comparing a
    # subset finds nothing and says so in the same words as comparing
    # everything, which is the one failure a byte lock cannot afford.
    local reference="$1" dir="$2"
    local named produced short extra expected rows=0 fail=0 want name got
    named="$(awk '{print $2}' "$reference" | LC_ALL=C sort)"
    produced="$(produced_artefacts "$dir")"
    if [ -z "$named" ]; then
        echo "LOCK FAILED: $reference names no artefact; a comparison over nothing"
        echo "  is not a lock. Delete it and run again to capture a reference."
        return 2
    fi
    short="$(LC_ALL=C comm -13 <(printf '%s\n' "$named") <(printf '%s\n' "$produced") | tr '\n' ' ')"
    extra="$(LC_ALL=C comm -23 <(printf '%s\n' "$named") <(printf '%s\n' "$produced") | tr '\n' ' ')"
    if [ -n "${short// /}" ] || [ -n "${extra// /}" ]; then
        echo "LOCK FAILED: $reference does not name the set this run produced,"
        echo "  so a verdict over it would be a verdict over part of the panels."
        [ -n "${short// /}" ] && echo "  this run produced, unnamed by the reference:$short"
        [ -n "${extra// /}" ] && echo "  named by the reference, not produced here:$extra"
        echo "  Capture and verify within one episode: delete it and run again."
        return 2
    fi
    echo "reference: $reference"
    while read -r want name; do
        rows=$((rows + 1))
        got=$(sha256 "$dir/$name" 2>/dev/null | awk '{print $1}')
        if [ "$want" = "$got" ]; then echo "  ok       $name"
        else echo "  CHANGED  $name"; echo "    want $want"; echo "    got  ${got:-<missing>}"; fail=1; fi
    done < "$reference"
    expected="$(printf '%s\n' "$produced" | wc -l | tr -d ' ')"
    if [ "$rows" -ne "$expected" ]; then
        echo "LOCK FAILED: $reference names $expected artefacts but yielded $rows"
        echo "  rows; a final row with no newline ends the read without being"
        echo "  compared. Delete it and run again to capture a reference."
        return 2
    fi
    echo "  compared $rows artefacts, the whole set this run produced"
    if [ "$fail" -eq 0 ]; then echo "BEHAVIOUR LOCK HELD"; else echo "BEHAVIOUR LOCK BROKEN"; fi
    return "$fail"
}

# Sourced by the control, the file stops here: nothing below is a definition,
# and the setup below would otherwise create directories in the caller's tree.
if [ -n "${LOCK_FUNCTIONS_ONLY:-}" ]; then return 0 2>/dev/null || exit 0; fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2
REF_DIR="${1:-$ROOT/.scratch/lock}"
mkdir -p "$REF_DIR/artefacts" || exit 2
REF_DIR="$(cd "$REF_DIR" && pwd)"          # absolute: the capture redirect below
REFERENCE="$REF_DIR/SHA256SUMS"            # must not resolve against $OUT
OUT="$REF_DIR/artefacts"
PY="$ROOT/.venv/bin/python"

# The cache location is tools/fetch_case_model.cache_dir()'s rule, not a second
# copy of it: $XDG_CACHE_HOME, or ~/.cache under it.
MODEL="${XDG_CACHE_HOME:-$HOME/.cache}/stompcad/cases/1590B.stp"
if [ ! -f "$MODEL" ]; then
    echo "LOCK FAILED: no 1590B model at $MODEL"
    echo "  fetch it with: $PY tools/fetch_case_model.py 1590B"
    exit 2
fi
if [ ! -x "$PY" ]; then
    echo "LOCK FAILED: no interpreter at $PY"
    echo "  create it with: uv venv && uv sync --all-packages"
    exit 2
fi

run() {  # run <label> <args...>; exit codes 0 and 1 are both successful runs,
         # because a panel carrying a warning exits 1 by the CLI's contract.
    local label="$1"; shift
    "$PY" -m stompdrill.cli "$@" >"$OUT/$label.log" 2>&1
    local rc=$?
    if [ "$rc" -gt 1 ]; then
        echo "LOCK FAILED: scenario $label exited $rc"; cat "$OUT/$label.log"; exit 2
    fi
}

wrote() {  # wrote <label> <name...>; a crash and a warning both leave rc 1, so
           # a panel is believed only once the artefacts it owed are present.
    local label="$1"; shift
    local absent=""
    for name in "$@"; do
        [ -s "$OUT/$name" ] || absent="$absent $name"
    done
    if [ -n "$absent" ]; then
        echo "LOCK FAILED: scenario $label wrote no:$absent"
        cat "$OUT/$label.log"; exit 2
    fi
}

rm -f "$OUT"/a.* "$OUT"/b.*   # a stale artefact would certify a run that crashed

run a packages/stompdrill/tests/fixtures/tar.ai \
    --case 1590B --case-model "$MODEL" \
    --emit excellon="$OUT/a.drl" --emit json="$OUT/a.json" \
    --emit drawing-svg="$OUT/a.svg" --emit drawing-pdf="$OUT/a.pdf" \
    --emit step="$OUT/a.stp"
wrote a a.drl a.json a.svg a.pdf a.stp

run b packages/stompdrill/tests/fixtures/pax.ai \
    --emit excellon="$OUT/b.drl" --emit json="$OUT/b.json" \
    --emit drawing-svg="$OUT/b.svg" --emit drawing-pdf="$OUT/b.pdf"
wrote b b.drl b.json b.svg b.pdf

if [ ! -f "$REFERENCE" ]; then
    capture_reference "$REFERENCE" "$OUT"
    exit $?
fi

compare_to_reference "$REFERENCE" "$OUT"
exit $?
