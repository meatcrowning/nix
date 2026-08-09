#!/usr/bin/env bash
# ly-theme.sh — theme the ly login greeter from the wallpaper palette.
#
# Called by wal-set.sh with the three palette colours it needs:
#
#   ly-theme.sh ACCENT DIM CRIT
#
# The mapping follows the desktop convention (see docs/DESIGN.md and the
# kitty/kdeglobals steps in wal-set.sh): input text and the focused box
# border are ACCENT, the colormix waves mix ACCENT and DIM, the error line is
# bold CRIT. colormix_col3 stays hi-black — the desktop's backgrounds are pure
# black by design (the style byte is not a colour, so the palette has nothing
# to say about it).
#
# /etc/ly/config.ini is a symlink to /var/lib/ly/config.ini, seeded from the
# NixOS module output on every rebuild (the activation in sys/dsk/plasma.nix,
# which carries the colour keys below forward across switches). This script
# owns exactly those keys at runtime; every other key in the file is
# root-owned module state and is left alone.
#
# Failure is benign: on a missing or unwritable file (book, or a machine the
# activation has never seeded) it does nothing and ly keeps its current
# colours — login is unaffected. It never ADDS a key to the file, so it cannot
# grow the module-owned config.
set -u

ACCENT="${1:-}"
DIM="${2:-}"
CRIT="${3:-}"
if [ -z "$ACCENT" ] || [ -z "$DIM" ] || [ -z "$CRIT" ]; then
    echo "ly-theme: usage: ly-theme.sh ACCENT DIM CRIT" >&2
    exit 1
fi

CONF="${LY_CONFIG:-/var/lib/ly/config.ini}"
if [ ! -f "$CONF" ] || [ ! -w "$CONF" ]; then
    echo "ly-theme: $CONF missing or not writable, skipping"
    exit 0
fi

up() { printf '%s' "$1" | tr a-f A-F; }

# ly colours are 0xSSRRGGBB — a styling byte (01 = bold), then hex RGB.
col1="0x00$(up "$ACCENT")"   # colormix waves, primary = accent
col2="0x00$(up "$DIM")"      # colormix waves, secondary = dim
col3="0x20000000"            # backdrop, hi-black (matches the pure-black bg)
border_fg="0x00$(up "$ACCENT")"
fg="0x00$(up "$ACCENT")"
error_fg="0x01$(up "$CRIT")" # bold crit

for kv in "colormix_col1=$col1" "colormix_col2=$col2" "colormix_col3=$col3" \
          "border_fg=$border_fg" "fg=$fg" "error_fg=$error_fg"; do
    k="${kv%%=*}"
    grep -q "^$k=" "$CONF" || continue
    sed -i "s|^$k=.*|$kv|" "$CONF"
done
echo "ly-theme: recoloured $CONF (accent #$ACCENT, dim #$DIM, crit #$CRIT)"
