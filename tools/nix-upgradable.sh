#!/usr/bin/env bash
# tools/nix-upgradable.sh — READ-ONLY preview of what `nix flake update` would bring.
#
# Rolling-unstable question: "what can I upgrade?" — answered without committing
# to it. The real flake.lock is never touched:
#
#   1. prints the current inputs (rev, date, age) from flake.lock
#   2. hardlink-copies the repo to a throwaway dir (real copies of flake.nix +
#      flake.lock), and runs `nix flake update` THERE — the repo's lock cannot
#      move, by construction
#   3. builds the toplevel from the CURRENT inputs (cheap — it is normally the
#      running system, already in the store) and from the UPDATED inputs (the
#      one real download/build — that is the price of seeing the diff)
#   4. `nix store diff-closures` between the two — exactly which packages
#      (kernel, mesa, chrome, qtwebengine, ...) would move, and to what versions
#
# Read-only proof: flake.lock is sha256'd before and after; a mismatch aborts
# with exit 1. `nvd diff` shows the same data grouped; this uses the builtin so
# nothing extra is downloaded.
#
# Works on both hosts: x86_64 (top, NixOS #top) builds
# nixosConfigurations.top.config.system.build.toplevel; aarch64 (book,
# home-manager #air) builds homeConfigurations.air.activationPackage. Override
# with --attr <flake-attr>.
#
#   tools/nix-upgradable.sh               # full preview (builds the new closure)
#   tools/nix-upgradable.sh --no-build    # inputs summary + update preview only
#   tools/nix-upgradable.sh --input NAME  # preview only ONE input's move (and,
#                                         # without --no-build, the exact packages
#                                         # it changes — that is the per-input diff)
#
# Exit: 0 = diff shown (or --no-build completed); 1 = update/build failed (the
# repo and the running system are untouched either way); 2 = bad usage.

set -uo pipefail

usage() {
    sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  --attr <flake-attr>   build this attr instead of the host default"
    echo "  --input <name>        update only this one input in the copy"
    echo "  --no-build            skip the toplevel builds and the diff"
    exit "${1:-0}"
}

NO_BUILD=0
ATTR=""
INPUT=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --no-build) NO_BUILD=1; shift ;;
        --attr)     [ "$#" -ge 2 ] || { echo "--attr needs a value" >&2; usage 2; }
                    ATTR="$2"; shift 2 ;;
        --input)    [ "$#" -ge 2 ] || { echo "--input needs a value" >&2; usage 2; }
                    INPUT="$2"; shift 2 ;;
        -h|--help)  usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 2 ;;
    esac
done

REPO="${NIX_UPGRADABLE_REPO:-$HOME/nix}"
[ -f "$REPO/flake.nix" ] || { echo "no flake at $REPO" >&2; exit 2; }
[ -f "$REPO/flake.lock" ] || { echo "no flake.lock at $REPO — nothing to compare against" >&2; exit 2; }

# Host gate: the same flake is NixOS on top and home-manager-only on book, and
# the architecture is the reliable tell (book is aarch64 Asahi).
if [ -z "$ATTR" ]; then
    case "$(uname -m)" in
        aarch64*) ATTR="homeConfigurations.air.activationPackage" ;;
        *)        ATTR="nixosConfigurations.top.config.system.build.toplevel" ;;
    esac
fi

LOCK_SHA=$(sha256sum "$REPO/flake.lock" | awk '{print $1}')

echo "== current inputs ($REPO/flake.lock) =="
python3 - "$REPO/flake.lock" <<'PY'
import json, sys, time
lock = json.load(open(sys.argv[1]))
now = time.time()
roots = lock.get("nodes", {}).get("root", {}).get("inputs", {})
for name in sorted(roots):
    key = roots[name]
    if isinstance(key, list):
        print(f"  {name:<24} follows {key[0]}")
        continue
    locked = lock.get("nodes", {}).get(key, {}).get("locked") or {}
    if not locked:
        print(f"  {name:<24} (unlocked)")
        continue
    rev = (locked.get("rev") or locked.get("ref") or "?")[:10]
    lm = locked.get("lastModified") or 0
    date = time.strftime("%Y-%m-%d", time.gmtime(lm)) if lm else "?"
    age = int((now - lm) / 86400) if lm else -1
    print(f"  {name:<24} {rev}  {date}  {age}d old")
PY

TMP=$(mktemp -d "${TMPDIR:-/tmp}/nix-upgradable.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

# Hardlink copy of the tree (cheap, no extra disk); fall back to a real copy
# when /tmp is a different filesystem. Then UNLINK the copy's .git (a plain
# path flake, no shared git state) and replace flake.nix + flake.lock with
# REAL files: `rm -f` first, then `cp`. Plain `cp` (even -f) REFUSES to copy a
# file onto its own hardlink ("are the same file") and leaves the hardlink in
# place — and `nix flake update` would then write the new lock straight through
# it into the real repo. That bug actually fired during testing; only rm breaks
# the link. The sha check below is the net behind it.
if ! cp -al "$REPO"/. "$TMP"/ 2>/dev/null; then
    cp -a "$REPO"/. "$TMP"/
fi
rm -rf "$TMP/.git"
rm -f "$TMP/flake.nix" "$TMP/flake.lock"
cp "$REPO/flake.nix" "$TMP/flake.nix"
cp "$REPO/flake.lock" "$TMP/flake.lock"

verify_lock() {
    local now
    now=$(sha256sum "$REPO/flake.lock" | awk '{print $1}')
    if [ "$LOCK_SHA" != "$now" ]; then
        echo "ERROR: $REPO/flake.lock CHANGED during the run — aborting." >&2
        exit 1
    fi
}

echo ""
if [ -n "$INPUT" ]; then
    echo "== nix flake update $INPUT (on the throwaway copy $TMP — repo untouched) =="
    upd=(nix flake update "$INPUT")
else
    echo "== nix flake update (on the throwaway copy $TMP — repo untouched) =="
    upd=(nix flake update)
fi
if ! (cd "$TMP" && "${upd[@]}"); then
    echo "FAIL: nix flake update in the copy failed; nothing was changed." >&2
    exit 1
fi
verify_lock

if [ "$NO_BUILD" -eq 1 ]; then
    echo ""
    echo "inputs updated in the copy; the repo's flake.lock was not touched."
    echo "run without --no-build to build both toplevels and diff the closures."
    exit 0
fi

echo ""
echo "== building $ATTR from CURRENT inputs =="
CUR=$(nix build --no-link --print-out-paths --no-update-lock-file "$REPO#$ATTR") \
    || { echo "FAIL: could not build $ATTR from the current inputs" >&2; exit 1; }
echo "  $CUR"

echo ""
echo "== building $ATTR from UPDATED inputs (the real download/build) =="
NEW=$(nix build --no-link --print-out-paths --no-update-lock-file "$TMP#$ATTR") \
    || { echo "FAIL: the UPDATED toplevel does not build with the new inputs." >&2
         echo "      The repo and the running system are untouched; the current" >&2
         echo "      system stays exactly as it is." >&2
         exit 1; }
echo "  $NEW"

echo ""
echo "== nix store diff-closures: current -> updated =="
nix store diff-closures "$CUR" "$NEW" || true

verify_lock
echo ""
echo "read-only confirmed: $REPO/flake.lock unchanged (sha256 $LOCK_SHA)"
