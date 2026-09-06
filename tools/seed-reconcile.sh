#!/usr/bin/env bash
# Reconcile a runtime-mutable live copy from its nix source while carrying the
# values owned by wallpaper/cursor scripts. Home activation runs this for
# `hyprland-lua` and `theme-qml` on every switch; `seed-drift.sh` must mask the
# same values.
#
#   seed-reconcile.sh <kind> <src> <live>
#   seed-reconcile.sh --dry-run <kind> <src> <live>
#
# Exit 0: in sync, seeded, or reconciled. Exit 1: dry-run would seed/reconcile.
# Exit 2: missing source or unsafe carry; activation's `|| true` makes that a
# silent no-op, while preflight reports it as a real failure.

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

# carry <ere-prefix> <ere-value>: copy one tightly anchored runtime value from
# LIVE into TMP. Prefixes must distinguish adjacent fields (not a generic rgba
# match). Patterns may not contain `%` (the sed delimiter) or capture groups
# (carry reserves its own groups; use bare `true|false`).
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
