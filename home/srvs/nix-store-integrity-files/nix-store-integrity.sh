#!/usr/bin/env bash
# Periodic /nix/store content check — the standing detector for silent bit rot.
#
# On `top`, 2026-07-30, three .drv files in /nix/store had single bits cleared
# on disk and nix eval broke in ways that look exactly like a config bug
# ("expected string '\"'", "derivation has incorrect output X, should be Y").
# Nothing on the machine noticed; the store is written once and then only read,
# so a flipped bit sits there until something happens to parse that file.
# See docs/agents/nix-store-bitrot-extent.md.
#
# What this is NOT: `nix-store --verify --check-contents`. That re-hashes the
# whole store (~14 min and every byte of it on top), needs root, and takes the
# nix db lock — far too heavy for a timer.
#
# What it IS, in two halves, both read-only and both runnable as the user:
#
#   1. EVERY .drv, every run. 76k of them re-hash in under two seconds, they
#      are where the rot actually bit, and a rotted drv is what breaks a
#      rebuild. This half is nearly free, so it is never sampled.
#   2. A ROTATING SLICE of the non-drv paths (1/$SLICES per run, advancing each
#      time), so the whole store is covered over a full cycle without any one
#      run costing more than a few minutes of nice'd I/O.
#
# Findings go to a state file rather than a notification: `tools/preflight.sh`
# reads it and warns before a rebuild, which is the moment store corruption
# actually matters. Nothing here ever repairs, deletes or garbage-collects —
# repair is `sudo nix-store --repair-path <path>` and that is a decision, not a
# timer's business.

set -uo pipefail

SLICES=${NSI_SLICES:-8}
JOBS=${NSI_JOBS:-4}

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/nix-store-integrity"
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/nix-store-integrity.log"
CORRUPT="$STATE/corrupt.txt"   # every path that has EVER failed here; preflight reads this
SLICEF="$STATE/slice"

mkdir -p "$STATE" "$(dirname "$LOG")"
say() { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }

command -v nix-store >/dev/null || { say "no nix-store on PATH; nothing to do"; exit 0; }
[ -d /nix/store ] || { say "no /nix/store; nothing to do"; exit 0; }

# --- mode: known ------------------------------------------------------------
# Re-check only the paths that have already been seen to rot. Instant, and the
# honest answer to "is that one still broken?" — used by hand and by preflight.
if [ "${1:-}" = "--known" ]; then
  [ -s "$CORRUPT" ] || exit 0
  # A path that has since been repaired or deleted is not a failure.
  xargs -a "$CORRUPT" -d '\n' -r -n 50 nix-store --verify-path 2>&1 |
    grep -F 'was modified!' || true
  exit 0
fi

started=$(date +%s)
work=$(mktemp) ; out=$(mktemp)
trap 'rm -f "$work" "$out"' EXIT

# Half 1: every .drv. Listed off the directory rather than out of the nix db —
# an UNREGISTERED corrupt drv is a real finding too (it needs no repair, only
# deletion, but it is evidence the rot is ongoing).
find /nix/store -maxdepth 1 -name '*.drv' -print > "$work"
ndrv=$(wc -l < "$work")

# Half 2: this run's slice of everything else. `nix path-info --all` is the
# registered set; sorted so the slicing is stable across runs, and the index
# advances by one each time so a full cycle covers the store.
slice=$(cat "$SLICEF" 2>/dev/null || echo 0)
slice=$(( slice % SLICES ))
nix path-info --all 2>/dev/null |
  grep -v '\.drv$' |
  sort |
  awk -v s="$slice" -v n="$SLICES" 'NR % n == s' >> "$work"
nslice=$(( $(wc -l < "$work") - ndrv ))
echo $(( (slice + 1) % SLICES )) > "$SLICEF"

# nix-store --verify-path is read-only and takes no db lock, so this cannot
# collide with a rebuild the user or another agent is running.
xargs -a "$work" -d '\n' -r -n 200 -P "$JOBS" \
  nice -n 19 ionice -c3 nix-store --verify-path 2>&1 |
  grep -F 'was modified!' > "$out" || true

# A failure here has two very different causes, and telling them apart is the
# whole point of this step. On top, 2026-07-30, a drv that hashed WRONG re-read
# CORRECT the moment the page cache was dropped: the bytes on disk were fine and
# the corruption lived in a cached page in DRAM. Same symptom, different machine
# to fix. `dd iflag=direct` bypasses the page cache with no root, so we can make
# that call in the report instead of leaving it to whoever reads the log.
# Only for regular files (drvs, and store paths that happen to be single files);
# a directory's hash is over its NAR and there is nothing to re-read directly.
reread() {
  p=$1
  [ -f "$p" ] || { echo "recheck-by-hand"; return; }
  cached=$(sha256sum < "$p" | cut -d' ' -f1)
  direct=$(dd if="$p" iflag=direct bs=1M status=none 2>/dev/null | sha256sum | cut -d' ' -f1)
  [ -z "$direct" ] && { echo "recheck-by-hand"; return; }
  if [ "$cached" = "$direct" ]; then echo "on-disk"; else echo "page-cache-only"; fi
}

nbad=$(wc -l < "$out")
elapsed=$(( $(date +%s) - started ))
say "slice $slice/$SLICES: ${ndrv} drv + ${nslice} other paths, ${nbad} corrupt, ${elapsed}s"

if [ "$nbad" -gt 0 ]; then
  # sed: pull the store path out of nix's message, which quotes it.
  sed -n "s/^path '\(.*\)' was modified!.*/\1/p" "$out" > "$out.paths"
  while IFS= read -r p; do
    say "CORRUPT [$(reread "$p")] $p"
  done < "$out.paths"
  cat "$out.paths" >> "$CORRUPT"
  sort -u -o "$CORRUPT" "$CORRUPT"
  rm -f "$out.paths"
fi

printf '{"when":"%s","slice":%d,"of":%d,"drvs":%d,"others":%d,"corrupt":%d,"seconds":%d}\n' \
  "$(date -Is)" "$slice" "$SLICES" "$ndrv" "$nslice" "$nbad" "$elapsed" > "$STATE/last-run.json"
exit 0
