#!/usr/bin/env bash
# Bring a seed-once file's LIVE copy up to its nix SOURCE, carrying across the
# handful of values runtime scripts own.
#
# Two dotfiles here cannot be plain /nix/store symlinks, because runtime
# scripts rewrite them in place: wal-set.sh splices the wallpaper palette into
# both, and cursor-recolor.sh renames the cursor theme in hyprland.lua. They
# were therefore installed only if ABSENT — which meant a rebuild never updated
# them, so `git pull && rebuild` silently did not apply anything either file
# had changed. That is the whole of "seed drift": not a fussy check, but a pull
# that did not reach the running system.
#
# This script closes it. The nix source is authoritative for STRUCTURE; the
# live file is authoritative for the named runtime-owned VALUES, and those are
# carried forward onto the source before it is written back. Run from
# home.activation on every switch (home/prog/hyprland.nix, quickshell.nix), so
# the live copy can no longer fall behind.
#
#   seed-reconcile.sh <kind> <nix-source> <live-path>     # seed or reconcile
#   seed-reconcile.sh --dry-run <kind> <src> <live>       # report, write nothing
#
# <kind> is `hyprland-lua` or `theme-qml` — it selects which values are
# runtime-owned. tools/seed-drift.sh is the tripwire that says this script is
# not doing its job; the two must agree on that list.
#
# Exit: 0 = in sync, seeded, or reconciled.
#       1 = (--dry-run only) would seed or would reconcile — the normal state
#           between an edit and the next switch, and NOT a fault.
#       2 = cannot do it: a missing source, or a carry that would have written
#           the template value over a runtime-owned one. Activation runs this
#           with `|| true`, so 2 is a SILENT no-op there — it is the code
#           tools/seed-drift.sh --pre-switch fails preflight on. The two must
#           stay distinct: conflating them is what deadlocked the rebuild until
#           2026-08-07.

set -uo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && { DRY=1; shift; }

KIND="${1:?usage: seed-reconcile.sh [--dry-run] <kind> <src> <live>}"
SRC="${2:?}"
LIVE="${3:?}"

[ -f "$SRC" ] || { echo "seed-reconcile: missing source $SRC" >&2; exit 2; }

# Never seeded yet (fresh install): install the source verbatim and stop. There
# are no runtime values to carry, and wal-set.sh will write its own on first run.
if [ ! -e "$LIVE" ]; then
    [ "$DRY" -eq 1 ] && { echo "seed-reconcile: would SEED $LIVE"; exit 1; }
    install -D -m644 "$SRC" "$LIVE" || exit 2
    echo "seed-reconcile: seeded $LIVE"
    exit 0
fi

TMP="$(mktemp)" || exit 2
trap 'rm -f "$TMP" "$TMP.blk" "$TMP.out"' EXIT
cp "$SRC" "$TMP" || exit 2

# carry <ere-prefix> <ere-value>
# Read the value the live file currently holds for the line matching
# ^<prefix><value>, and write it into the same line of the working copy. The
# prefix must anchor tightly enough to name exactly one line: a loose one (say,
# any rgba) would drag across the WRONG line — hyprland.lua's active_border and
# inactive_border sit two lines apart and are both runtime-owned now, so each
# needs its own line-start-anchored prefix rather than a shared rgba match.
#
# Two constraints on the patterns, both paid for (title_rotated reverted to the
# seed's `false` on every switch until 2026-08-08, and the sed never said why):
#   * neither may contain a literal `%` — it is the sed delimiter here. The old
#     `|` delimiter was terminated by the alternation in `(true|false)`, so
#     both boolean carries errored to stderr and silently carried nothing.
#   * <ere-value> must contain no capture groups — carry's own parens are the
#     only ones, or \3 stops being "the rest of the line". Alternate with a
#     bare `true|false`; carry's wrap gives it its scope.
carry() {
    local pre="$1" val="$2" v esc
    v=$(sed -nE "s%^(${pre})(${val})(.*)\$%\2%p" "$LIVE" | head -1)
    [ -n "$v" ] || return 0
    esc=${v//\\/\\\\}; esc=${esc//%/\\%}; esc=${esc//&/\\&}
    sed -i -E "s%^(${pre})(${val})(.*)\$%\1${esc}\3%" "$TMP"
}

case "$KIND" in
  hyprland-lua)
    # wal-set.sh steps 5-6: the general border colour, seven named plugin
    # colours and the shadow alpha. Anchored at line start so `active_border`
    # cannot match inside `inactive_border`, and requiring `= "` so it cannot
    # match the commented-out gradient form on the next line.
    carry '[[:space:]]*active_border[[:space:]]*=[[:space:]]*"' 'rgba\([0-9a-fA-F]+\)'
    # inactive_border became runtime-owned 2026-08-09 — it follows the
    # dimUnfocused pick (grey when on, the accent when off; wal-set.sh /
    # apply-window-frame.sh). Distinct line from active_border above (the ^
    # anchor makes `active_border` unable to match inside `inactive_border`).
    carry '[[:space:]]*inactive_border[[:space:]]*=[[:space:]]*"' 'rgba\([0-9a-fA-F]+\)'
    for k in bg_color 'col\.text' 'col\.button_border' 'col\.accent' 'col\.bg_alt' 'col\.crit' 'col\.warn'; do
        carry "[[:space:]]*\\[\"${k}\"\\][[:space:]]*=[[:space:]]*\"" 'rgba\([0-9a-fA-F]+\)'
    done
    carry '[[:space:]]*\["shadow_alpha"\][[:space:]]*=[[:space:]]*' '[0-9.]+'
    carry '[[:space:]]*\["title_rotated"\][[:space:]]*=[[:space:]]*' 'true|false'
    carry '[[:space:]]*\["font"\][[:space:]]*=[[:space:]]*' '"[^"]*"'
    carry '[[:space:]]*\["font_size"\][[:space:]]*=[[:space:]]*' '[0-9]+'
    carry '[[:space:]]*\["font_smooth"\][[:space:]]*=[[:space:]]*' 'true|false'
    carry '[[:space:]]*\["font_terminal_cell"\][[:space:]]*=[[:space:]]*' 'true|false'
    carry '[[:space:]]*border_size[[:space:]]*=[[:space:]]*' '[0-9]+'
    carry '[[:space:]]*rounding[[:space:]]+=[[:space:]]*' '[0-9]+'
    # apply-window-frame.sh: titlebar anchor edge, the unfocus dim (both the
    # plugin titlebar scrim and Hyprland's native content dim) and the compact
    # bar layout. seed-drift.sh already masks these four as runtime-owned; this
    # carry is what makes that true instead of just claimed — without it, a
    # rebuild silently reset all four to the nix-source seed on every switch,
    # discarding whatever Settings > Appearance had persisted.
    carry '[[:space:]]*\["titlebar_edge"\][[:space:]]*=[[:space:]]*"' '[^"]*'
    carry '[[:space:]]*\["dim_unfocused"\][[:space:]]*=[[:space:]]*' 'true|false'
    carry '[[:space:]]*\["compact"\][[:space:]]*=[[:space:]]*' 'true|false'
    carry '[[:space:]]*dim_inactive[[:space:]]*=[[:space:]]*' 'true|false'
    # cursor-recolor.sh: the generated GoogleDot-<accent><outline> theme name.
    carry 'hl\.env\("XCURSOR_THEME", "'    'GoogleDot-[^"]*'
    carry 'hl\.env\("HYPRCURSOR_THEME", "' 'GoogleDot-[^"]*'
    ;;
  theme-qml)
    # wal-set.sh step 7 rewrites everything between the two markers wholesale,
    # so carry the live block across rather than value by value — a new colour
    # role added to the block by wal-set.sh then needs no change here.
    if grep -q '// >>> wal palette' "$LIVE" && grep -q '// >>> wal palette' "$TMP"; then
        sed -n '/\/\/ >>> wal palette/,/\/\/ <<< wal palette/p' "$LIVE" \
            | sed '1d;$d' > "$TMP.blk"
        # Bail rather than write, if the carry could not be done: what is in
        # $TMP at this point is the nix source with the DEFAULT palette, and
        # writing that recolours the whole desktop off the wallpaper. This is
        # not hypothetical — book's home-manager activation had no `awk` on its
        # PATH, so this block failed silently on every switch and the live wal
        # palette was replaced by the source's each time (fixed in
        # home/prog/quickshell.nix, which now supplies gawk).
        if [ ! -s "$TMP.blk" ]; then
            echo "seed-reconcile: the live wal palette block is empty; leaving $LIVE alone" >&2
            exit 2
        fi
        if ! awk -v inc="$TMP.blk" '
            /\/\/ >>> wal palette/ { print; while ((getline line < inc) > 0) print line; skip=1; next }
            /\/\/ <<< wal palette/ { skip=0 }
            !skip { print }
        ' "$TMP" > "$TMP.out"; then
            echo "seed-reconcile: cannot carry the live wal palette across; leaving $LIVE alone" >&2
            rm -f "$TMP.out"
            exit 2
        fi
        mv "$TMP.out" "$TMP"
    fi
    ;;
  *)
    echo "seed-reconcile: unknown kind '$KIND'" >&2; exit 2 ;;
esac

if cmp -s "$TMP" "$LIVE"; then
    exit 0
fi

if [ "$DRY" -eq 1 ]; then
    echo "seed-reconcile: would RECONCILE $LIVE ($(diff "$LIVE" "$TMP" | grep -c '^[<>]') differing lines)"
    exit 1
fi

# Keep a copy of what the live file said. The nix source wins here, so a change
# made ONLY to the live copy — an agent testing in place, a hand edit on the
# wrong side — is about to be discarded, and it should be recoverable.
BAK="${XDG_CACHE_HOME:-$HOME/.cache}/seed-reconcile"
mkdir -p "$BAK"
STAMP="$(date +%Y%m%d-%H%M%S)"
cp "$LIVE" "$BAK/$(basename "$LIVE").$STAMP.bak" 2>/dev/null

# In place, same inode, never a rename: Quickshell watches each loaded QML file
# by inode, so `mv` over Theme.qml leaves the panel watching the old unlinked
# one and the change is never seen. (Harmless for hyprland.lua; done the same
# way so there is one rule.)
cat "$TMP" > "$LIVE" || exit 2
echo "seed-reconcile: reconciled $LIVE from nix source (was backed up to $BAK/$(basename "$LIVE").$STAMP.bak)"
