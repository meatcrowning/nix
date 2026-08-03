#!/usr/bin/env bash
# Report drift between the nix SOURCE of a seed-once file and its LIVE copy.
#
# Some dotfiles in this repo are installed by home-manager only if absent
# (`[ -e ... ] || install ...` in home/prog/hyprland.nix and
# home/prog/quickshell.nix), because runtime scripts rewrite them in place:
# wal-set.sh owns the palette lines and cursor-recolor.sh the cursor theme.
# The cost of that design is that a rebuild NEVER
# updates the live file, so an edit made only to the nix source silently does
# nothing on the running system — and an edit made only to the live file is
# lost on the next fresh install.
#
# This script diffs each pair with the runtime-owned VALUES masked out, so what
# survives is real drift: a line one side has and the other doesn't.
#
#   tools/seed-drift.sh          # human-readable report
#   tools/seed-drift.sh --quiet  # no output, exit 1 if drift  (for scripting)
#
# Exit: 0 = in sync, 1 = drift found, 2 = a file is missing.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }

# Mask the values runtime scripts are ALLOWED to rewrite, so they don't show up
# as drift. Keep the surrounding line intact — a line that only one side has
# must still appear in the diff.
normalize() {
    case "$1" in
        *hyprland.lua)
            sed -E -e 's/rgba\([0-9a-fA-F]{6,8}\)/rgba(<WAL>)/g' \
                   -e 's/GoogleDot-[A-Za-z0-9]+/GoogleDot-<ACCENT>/g' \
                   -e 's/(\["shadow_alpha"\][[:space:]]*=[[:space:]]*)[0-9.]+/\1<WAL>/g'
            ;;
        *Theme.qml)
            sed -E -e 's/"#[0-9a-fA-F]{3,8}"/"<WAL>"/g'
            ;;
        *) cat ;;
    esac
}

# pair: <nix source, repo-relative>|<live path>
PAIRS=(
    "home/prog/hypr-files/hyprland.lua|$CONFIG/hypr/hyprland.lua"
    "home/prog/quickshell-files/Theme.qml|$CONFIG/quickshell/Theme.qml"
)

rc=0
for pair in "${PAIRS[@]}"; do
    src="$REPO/${pair%%|*}"
    live="${pair##*|}"
    name="${pair%%|*}"

    if [ ! -f "$src" ];  then say "MISSING source: $src";  rc=2; continue; fi
    if [ ! -f "$live" ]; then say "MISSING live:   $live (not seeded yet — a rebuild will install it)"; rc=2; continue; fi

    d=$(diff -u --label "nix source: $name" --label "live: $live" \
            <(normalize "$src"  < "$src") \
            <(normalize "$live" < "$live") 2>/dev/null)

    if [ -n "$d" ]; then
        n=$(printf '%s\n' "$d" | grep -c '^[+-][^+-]')
        say ""
        say "=== DRIFT: $name  ($n differing lines) ==="
        say "$d"
        rc=1
    else
        say "ok: $name"
    fi
done

if [ "$rc" -eq 1 ]; then
    say ""
    say "Lines starting '-' exist only in the nix SOURCE  -> never reached the running system."
    say "Lines starting '+' exist only in the LIVE file   -> will be lost on a fresh install."
    say "Fix by editing BOTH copies; edit the live one IN PLACE (targeted string edit),"
    say "never overwrite it wholesale or you reset the runtime-owned palette lines."
fi

exit "$rc"
