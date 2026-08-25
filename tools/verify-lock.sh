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
#   Artefacts are kept in DIR/artefacts either way, so a break can be diffed.
# Exit: 0 identical or captured, 1 a byte differs, 2 a run or precondition failed.
set -uo pipefail

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

sha256() {  # sha256sum on most Linux distributions, shasum on macOS; both print
            # "<digest>  <name>", which is the reference file's format.
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"
    else shasum -a 256 "$@"; fi
}

run() {  # run <label> <args...>; exit codes 0 and 1 are both successful runs,
         # because a panel carrying a warning exits 1 by the CLI's contract.
    local label="$1"; shift
    "$PY" -m stompdrill.cli "$@" >"$OUT/$label.log" 2>&1
    local rc=$?
    if [ "$rc" -gt 1 ]; then
        echo "LOCK FAILED: scenario $label exited $rc"; cat "$OUT/$label.log"; exit 2
    fi
}

run a packages/stompdrill/tests/fixtures/tar.ai \
    --case 1590B --case-model "$MODEL" \
    --emit excellon="$OUT/a.drl" --emit json="$OUT/a.json" \
    --emit drawing-svg="$OUT/a.svg" --emit drawing-pdf="$OUT/a.pdf" \
    --emit step="$OUT/a.stp"

run b packages/stompdrill/tests/fixtures/pax.ai \
    --emit excellon="$OUT/b.drl" --emit json="$OUT/b.json" \
    --emit drawing-svg="$OUT/b.svg" --emit drawing-pdf="$OUT/b.pdf"

if [ ! -f "$REFERENCE" ]; then
    (cd "$OUT" && sha256 a.* b.* | grep -v '\.log$') > "$REFERENCE"
    echo "reference captured: $REFERENCE"; cat "$REFERENCE"; exit 0
fi

fail=0
rows=0
while read -r want name; do
    rows=$((rows + 1))
    got=$(sha256 "$OUT/$name" 2>/dev/null | awk '{print $1}')
    if [ "$want" = "$got" ]; then echo "  ok       $name"
    else echo "  CHANGED  $name"; echo "    want $want"; echo "    got  ${got:-<missing>}"; fail=1; fi
done < "$REFERENCE"
if [ "$rows" -eq 0 ]; then
    echo "LOCK FAILED: $REFERENCE names no artefact; a comparison over nothing"
    echo "  is not a lock. Delete it and run again to capture a reference."
    exit 2
fi
[ "$fail" -eq 0 ] && echo "BEHAVIOUR LOCK HELD" || echo "BEHAVIOUR LOCK BROKEN"
exit "$fail"
