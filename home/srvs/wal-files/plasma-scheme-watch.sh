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
CACHE="$HOME/.cache/wal/plasma-scheme-watch"

accent="$(sed -n 's/^    readonly property color accent:    "#\([0-9a-fA-F]\{6\}\)".*/\1/p' "$THEME" | head -n1)"
case "$accent" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) exit 0 ;;
esac

scheme="$(kreadconfig6 --file kdeglobals --group General --key ColorScheme 2>/dev/null || true)"
case "$scheme" in
    OxygenDarkFlat|OxygenLightFlat) ;;
    *) exit 0 ;;
esac

# plasma-scheme.py itself notifies kdeglobals, which wakes this path again.
# The pair makes that second pass a no-op while a genuine KCM choice has a new
# scheme name and is applied immediately.
mkdir -p "$(dirname "$CACHE")"
if [ "$(cat "$CACHE" 2>/dev/null || true)" = "$scheme:$accent" ]; then
    exit 0
fi
printf '%s' "$scheme:$accent" > "$CACHE"
exec "$HOME/.config/scripts/plasma-scheme.py" --accent "$accent"
