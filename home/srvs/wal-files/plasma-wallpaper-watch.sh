#!/usr/bin/env bash
# plasma-wallpaper-watch.sh — make Plasma's own wallpaper picker drive wal-set.sh.
#
# Under Hyprland the wallpaper is picked by the Quickshell picker, which calls
# wal-set.sh itself, so the whole desktop re-themes with it. Under Plasma he
# picks it in Plasma's desktop settings, and NOTHING was wired to that: the wal
# palette froze at whatever the last Hyprland-side apply left behind, taking
# kitty, the 4chan sheet and Vivaldi's custom.css with it, while Plasma's own
# `accentColorFromWallpaper` moved the panel accent and nothing else. That is
# the "the top bar changed and the windows did not" split (2026-08-24).
#
# So: watch the containment config, read the image Plasma just set, and run the
# full wal-set.sh on it.
#
# Fired by plasma-wallpaper-watch.path on every write of the appletsrc, which
# Plasma touches for any applet's state — hence the dedupe against
# ~/.cache/wal/current before doing any work. A run where the wallpaper did not
# move costs one grep.
set -u

CACHE="$HOME/.cache/wal"
LOG="$CACHE/wallpaper-picker.log"

# A containment config is named after the SHELL package that owns it, so the
# file to read depends on which Plasma session is running: stock Plasma writes
# plasma-org.kde.plasma.desktop-appletsrc, AeroThemePlasma's forked shell writes
# plasma-io.gitgud.wackyideas.desktop-appletsrc [2026-08-28]. Only one shell can
# be up at a time, so take the most recently written of the two that exist —
# the other is last session's, and reading it would re-theme from a stale image.
APPLETSRC=""
for f in "$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc" \
         "$HOME/.config/plasma-io.gitgud.wackyideas.desktop-appletsrc"; do
    [ -f "$f" ] || continue
    if [ -z "$APPLETSRC" ] || [ "$f" -nt "$APPLETSRC" ]; then
        APPLETSRC="$f"
    fi
done
[ -n "$APPLETSRC" ] || exit 0

# Every containment writes its own [Wallpaper][org.kde.image][General] Image=;
# they are the same image in practice (one wallpaper across the desktops), so
# take the last one that resolves to a real file. A slideshow containment
# writes a DIRECTORY here — skipped by the -f test, since there is no single
# image to theme from.
WALL=""
while IFS= read -r line; do
    v="${line#Image=}"
    v="${v#file://}"
    case "$v" in
        "~"/*) v="$HOME/${v#\~/}" ;;
    esac
    [ -f "$v" ] && WALL="$v"
done < <(grep '^Image=' "$APPLETSRC" 2>/dev/null)

[ -n "$WALL" ] || exit 0
WALL="$(realpath "$WALL")"

# Already themed from this image? Then this appletsrc write was some other
# applet's state and there is nothing to do.
if [ -f "$CACHE/current" ] && [ "$(cat "$CACHE/current")" = "$WALL" ]; then
    exit 0
fi

mkdir -p "$CACHE"
echo "plasma-wallpaper-watch: Plasma set $WALL" >> "$LOG"
exec "$HOME/.config/scripts/wal-set.sh" "$WALL" >> "$LOG" 2>&1
