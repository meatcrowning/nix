#!/usr/bin/env bash
# plasma-scheme-watch.sh — keep the user-selected dynamic Plasma scheme on the
# current wallpaper palette.
#
# System Settings → Colors writes only the chosen scheme name.  Our two Oxygen
# schemes are mutable files, so selecting one must also re-mint it from the
# current Theme.qml accent; otherwise Plasma loads the last on-disk palette and
# the windows split from the wallpaper-derived desktop palette.
set -u

THEME="$HOME/.config/quickshell/Theme.qml"
WAL_CACHE="$HOME/.cache/wal"

accent="$(sed -n 's/^    readonly property color accent:    "#\([0-9a-fA-F]\{6\}\)".*/\1/p' "$THEME" | head -n1)"
case "$accent" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) exit 0 ;;
esac

scheme="$(kreadconfig6 --file kdeglobals --group General --key ColorScheme 2>/dev/null || true)"
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
        && [ -f "$WAL_CACHE/current" ]; then
    wall="$(cat "$WAL_CACHE/current")"
    key="$(printf '%s' "$wall" | md5sum | cut -d' ' -f1)"
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
