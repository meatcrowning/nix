#!/usr/bin/env bash
# Report drift between the nix SOURCE of a seed-once file and its LIVE copy.
#
# Some dotfiles in this repo cannot be plain /nix/store symlinks, because
# runtime scripts rewrite them in place: wal-set.sh owns the palette lines and
# cursor-recolor.sh the cursor theme. They were therefore installed only if
# ABSENT, which meant a rebuild never updated them — an edit to the nix source
# silently did nothing on the running system.
#
# Since 2026-08-05 `tools/seed-reconcile.sh` runs from home.activation on every
# switch and closes that: the nix source wins on structure, the live file keeps
# the named runtime-owned values. So "source ahead of live" is now the NORMAL
# state between an edit and the next switch, and the question worth asking has
# two halves:
#
#   BEFORE a switch — what will the switch do?     --pre-switch  (preflight's mode)
#   AFTER  a switch — did the reconciler miss one?  default report
#
# Those are different questions and only the second is a fault. Until
# 2026-08-07 there was one answer to both and it was a hard FAIL, which
# deadlocked the repo: every commit that touched hyprland.lua made preflight
# fail, preflight gates `sudo rebuild-top`, and the switch was the only thing
# that could clear the drift. Nothing that changed a seed-once file could land —
# including `nix-pull apply`, whose whole job is to land other machines'
# commits unattended.
#
# This script diffs each pair with the runtime-owned VALUES masked out, so what
# survives is real drift: a line one side has and the other doesn't.
#
#   tools/seed-drift.sh              # human-readable report (the post-switch tripwire)
#   tools/seed-drift.sh --quiet      # no output, exit 1 if drift  (for scripting)
#   tools/seed-drift.sh --pre-switch # what the NEXT switch will do (preflight)
#
# Exit: 0 = in sync / nothing for the switch to do
#       1 = drift  (report mode: the reconciler missed it — investigate;
#                   --pre-switch: the switch resolves it — benign)
#       2 = a file is missing, or the reconciler CANNOT run (a real fault in
#           both modes)

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"

MODE=report
case "${1:-}" in
    "")           ;;
    --quiet)      MODE=quiet ;;
    --pre-switch) MODE=pre ;;
    *) echo "usage: seed-drift.sh [--quiet|--pre-switch]" >&2; exit 2 ;;
esac

say() { [ "$MODE" = quiet ] || printf '%s\n' "$*"; }

# Mask the values runtime scripts are ALLOWED to rewrite, so they don't show up
# as drift. Keep the surrounding line intact — a line that only one side has
# must still appear in the diff.
normalize() {
    case "$1" in
        *hyprland.lua)
            sed -E -e 's/rgba\([0-9a-fA-F]{6,8}\)/rgba(<WAL>)/g' \
                   -e 's/GoogleDot-[A-Za-z0-9]+/GoogleDot-<ACCENT>/g' \
                   -e 's/(\["shadow_alpha"\][[:space:]]*=[[:space:]]*)[0-9.]+/\1<WAL>/g' \
                   -e 's/(\["title_rotated"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g'
            ;;
        *Theme.qml)
            sed -E -e 's/"#[0-9a-fA-F]{3,8}"/"<WAL>"/g'
            ;;
        *) cat ;;
    esac
}

# pair: <seed-reconcile kind>|<nix source, repo-relative>|<live path>
# The kind is what tools/seed-reconcile.sh is invoked with from activation
# (home/prog/hyprland.nix, home/prog/quickshell.nix) — carried here so
# --pre-switch asks the reconciler itself rather than guessing what it will do.
PAIRS=(
    "hyprland-lua|home/prog/hypr-files/hyprland.lua|$CONFIG/hypr/hyprland.lua"
    "theme-qml|home/prog/quickshell-files/Theme.qml|$CONFIG/quickshell/Theme.qml"
)

rc=0
bump() { [ "$rc" -lt "$1" ] && rc="$1"; return 0; }

for pair in "${PAIRS[@]}"; do
    IFS='|' read -r kind name live <<<"$pair"
    src="$REPO/$name"

    if [ ! -f "$src" ]; then say "MISSING source: $src"; bump 2; continue; fi

    if [ ! -f "$live" ]; then
        if [ "$MODE" = pre ]; then
            say "seed: the switch will install $live (never seeded on this host)"
            bump 1
        else
            say "MISSING live:   $live (not seeded yet — a rebuild will install it)"
            bump 2
        fi
        continue
    fi

    d=$(diff -u --label "nix source: $name" --label "live: $live" \
            <(normalize "$src"  < "$src") \
            <(normalize "$live" < "$live") 2>/dev/null)

    if [ "$MODE" = pre ]; then
        # Ask the reconciler what it would do, rather than inferring it: this is
        # byte-for-byte the same script and the same <kind> that activation runs,
        # so the two cannot drift apart in their reading of the same pair.
        out=$(bash "$REPO/tools/seed-reconcile.sh" --dry-run "$kind" "$src" "$live" 2>&1)
        case "$?" in
            0) continue ;;
            1)
                only_src=$(printf '%s\n' "$d" | grep -c '^-[^-]')
                only_live=$(printf '%s\n' "$d" | grep -c '^+[^+]')
                say "seed: the switch will reconcile $live from $name"
                [ "$only_src" -gt 0 ] && \
                    say "      $only_src line(s) the nix source has will reach the running system."
                [ "$only_live" -gt 0 ] && \
                    say "      $only_live live-only line(s) will be REPLACED (backup: ~/.cache/seed-reconcile/)."
                bump 1
                ;;
            *)
                # The reconciler refuses — activation runs it with `|| true`, so
                # this is exactly the silent no-op that left book's live Theme.qml
                # behind for weeks (no awk on the activation PATH).
                say "SEED-RECONCILE CANNOT RUN for $live — the switch will NOT update it:"
                say "$out"
                bump 2
                ;;
        esac
        continue
    fi

    if [ -n "$d" ]; then
        n=$(printf '%s\n' "$d" | grep -c '^[+-][^+-]')
        say ""
        say "=== DRIFT: $name  ($n differing lines) ==="
        say "$d"
        bump 1
    else
        say "ok: $name"
    fi
done

if [ "$rc" -eq 1 ] && [ "$MODE" = report ]; then
    say ""
    say "Lines starting '-' exist only in the nix SOURCE  -> have not reached the running system."
    say "Lines starting '+' exist only in the LIVE file   -> will be replaced by the next switch."
    say ""
    say "Edit the nix SOURCE only; the switch reconciles the live copy (see"
    say "home/prog/AGENTS.md). If you have already switched and this still"
    say "reports drift, the reconciler missed a value it should carry —"
    say "tools/seed-reconcile.sh needs a matching \`carry\` call."
fi

exit "$rc"
