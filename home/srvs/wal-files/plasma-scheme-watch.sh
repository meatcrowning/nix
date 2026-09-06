#!/usr/bin/env bash
# plasma-scheme-watch.sh — keep the user-selected dynamic Plasma scheme on the
# current wallpaper palette.
#
# System Settings → Colors writes only the chosen scheme name.  Our two Oxygen
# schemes are mutable files, so selecting one must also re-mint it from the
# current wallpaper palette; otherwise Plasma loads the last on-disk palette
# and the windows split from the wallpaper-derived desktop palette.
set -u

WAL_CACHE="$HOME/.cache/wal"
THEME="$HOME/.config/quickshell/Theme.qml"

# wal-set publishes `current` before it writes the live Plasma roles.  Reading
# Theme.qml here races its deliberately-last hot reload: the kdeglobals write
# wakes this unit while Theme.qml still has the previous wallpaper's accent,
# and this unit would then put that old palette straight back into Oxygen.
# The palette cache is the transaction's source of truth.  Theme.qml remains a
# fallback for a manual scheme selection before wal has ever populated a cache.
wall="$(cat "$WAL_CACHE/current" 2>/dev/null || true)"
key="$(printf '%s' "$wall" | md5sum | cut -d' ' -f1)"
accent="$(sed -n 's/^ACCENT=\([0-9a-fA-F]\{6\}\)$/\1/p' "$WAL_CACHE/themes/$key.env" 2>/dev/null | head -n1)"
if ! printf '%s' "$accent" | grep -qE '^[0-9a-fA-F]{6}$'; then
    accent="$(sed -n 's/^    readonly property color accent:    "#\([0-9a-fA-F]\{6\}\)".*/\1/p' "$THEME" | head -n1)"
fi
case "$accent" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) exit 0 ;;
esac

scheme="$(kreadconfig6 --file kdeglobals --group General --key ColorScheme 2>/dev/null || true)"
[ -n "$scheme" ] || exit 0

# The Plasma panel's continuous Oxygen surface is a rendered image, not a
# live SVG fill.  A wallpaper change rewrites the selected .colors file and
# wakes plasma-panel-surface.path, but switching between two already-minted
# schemes changes only kdeglobals: text follows immediately while that image
# keeps the previous scheme's background.  Queue one refresh for a genuine
# scheme-name transition.  The cache also absorbs this script's own KConfig
# notifications, and the renderer itself avoids a plasmashell restart when the
# resulting pixels are unchanged.
panel_scheme_cache="$WAL_CACHE/plasma-panel-scheme"
if [ "$(cat "$panel_scheme_cache" 2>/dev/null || true)" != "$scheme" ]; then
    mkdir -p "$WAL_CACHE"
    printf '%s' "$scheme" > "$panel_scheme_cache"
    systemctl --user --no-block start plasma-panel-surface.service \
        >/dev/null 2>&1 || true
fi

case "$scheme" in
    OxygenDarkFlat|OxygenDarkNeutral|OxygenLightFlat) ;;
    *) exit 0 ;;
esac

# Plasma can write its own wallpaper accent into kdeglobals AFTER wal-set has
# minted this scheme. A scheme+accent cache then lies: the inputs are unchanged
# while the live roles are not. Compare the roles that establish the whole
# surface instead, so our own notifications settle immediately but a later
# Plasma write is repaired.
MINTED="$HOME/.local/share/color-schemes/$scheme.colors"
role() {
    awk -v group="[$1]" -v key="$2" '
        $0 == group { in_group = 1; next }
        in_group && /^\[/ { exit }
        in_group && $0 ~ "^" key "=" { sub("^[^=]*=", ""); print; exit }
    ' "$MINTED" 2>/dev/null
}
in_sync=1
for pair in \
    'Colors:Window BackgroundNormal' \
    'Colors:Window DecorationFocus' \
    'Colors:View BackgroundNormal' \
    'Colors:Button BackgroundNormal' \
    'WM activeBackground'; do
    set -- $pair
    expected="$(role "$1" "$2")"
    actual="$(kreadconfig6 --file kdeglobals --group "$1" --key "$2" 2>/dev/null || true)"
    [ -n "$expected" ] && [ "$actual" = "$expected" ] || { in_sync=0; break; }
done
[ "$in_sync" = 1 ] && exit 0

# The generator owns the wallpaper-specific dark surface ladder. Carry the
# cached structural colour through when it is available; every other dark/light
# scheme keeps the template's normal derivation.
bg=""
surface=""
if { [ "$scheme" = OxygenDarkFlat ] || [ "$scheme" = OxygenDarkNeutral ]; } \
        && [ -n "$wall" ]; then
    bg="$(sed -n 's/^BG=\([0-9a-fA-F]\{6\}\)$/\1/p' "$WAL_CACHE/themes/$key.env" 2>/dev/null | head -n1)"
    surface="$(sed -n 's/^BGALT=\([0-9a-fA-F]\{6\}\)$/\1/p' "$WAL_CACHE/themes/$key.env" 2>/dev/null | head -n1)"
fi
if [ "$scheme" = OxygenDarkNeutral ] && [ -n "$surface" ]; then
    exec "$HOME/.config/scripts/plasma-scheme.py" --accent "$accent" \
        --surface-color "$surface"
elif [ "$bg" = 464540 ]; then
    exec "$HOME/.config/scripts/plasma-scheme.py" --accent "$accent" --background "$bg"
else
    exec "$HOME/.config/scripts/plasma-scheme.py" --accent "$accent"
fi
