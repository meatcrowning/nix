#!/usr/bin/env bash
# Compare the nix source and live copies of the runtime-mutable dotfiles.
# `seed-reconcile.sh` runs on every switch: source structure wins, while
# wallpaper/cursor-owned values are carried from the live file. Therefore source
# drift is expected before a switch; post-switch drift is the fault to investigate.
#
#   seed-drift.sh              human-readable post-switch report
#   seed-drift.sh --quiet      no output; exit 1 on drift
#   seed-drift.sh --pre-switch ask the reconciler what the next switch will do
#
# Exit 0: in sync (or nothing to do); 1: drift (pre-switch is benign); 2:
# missing file or reconciler failure. Runtime-owned values are masked before the
# comparison, and --pre-switch invokes the reconciler itself so the two stay in
# lockstep.

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
                   -e 's/(\["title_rotated"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g' \
                   -e 's/(\["titlebar_edge"\][[:space:]]*=[[:space:]]*)"[^"]*"/\1<WAL>/g' \
                   -e 's/(\["dim_unfocused"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g' \
                   -e 's/(\["compact"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g' \
                   -e 's/^([[:space:]]*dim_inactive[[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/' \
                   -e 's/(\["font"\][[:space:]]*=[[:space:]]*)"[^"]*"/\1<WAL>/g' \
                   -e 's/(\["font_size"\][[:space:]]*=[[:space:]]*)[0-9]+/\1<WAL>/g' \
                   -e 's/(\["font_smooth"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g' \
                   -e 's/(\["font_terminal_cell"\][[:space:]]*=[[:space:]]*)(true|false)/\1<WAL>/g' \
                   -e 's/^([[:space:]]*border_size[[:space:]]*=[[:space:]]*)[0-9]+/\1<WAL>/' \
                   -e 's/^([[:space:]]*rounding[[:space:]]+=[[:space:]]*)[0-9]+/\1<WAL>/'
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
