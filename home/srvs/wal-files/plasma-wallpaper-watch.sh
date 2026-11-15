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
SESSION_RESTORED="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/plasma-wallpaper-restored"

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

# The image this watcher saw on its previous run. It tells a stale containment
# image (unchanged since then) from a pick made in this session.
mkdir -p "$CACHE"
LAST_SEEN="$CACHE/plasma-last-image"
last_seen="$(cat "$LAST_SEEN" 2>/dev/null || true)"
printf '%s\n' "$WALL" > "$LAST_SEEN"

# The Plasma containment file survives while wallpaper choices made in the
# Hyprland session are recorded in the shared library marker.  On the first
# containment write of a Plasma login, restore that newer cross-session choice
# before treating Plasma's stale on-disk image as a new selection.
#
# Only a stale image qualifies: the one this watcher last saw, or Plasma's
# store default after a panel regeneration recreated the file. book's Plasma
# rewrites the file during login, so the first write there is always stale;
# top's often does not, so its first write can be a Dolphin "Set as
# Wallpaper", which this used to revert to the previous choice [2026-11-14].
stale=1
if [ -n "$last_seen" ] && [ "$WALL" != "$last_seen" ]; then
    case "$WALL" in /nix/store/*) ;; *) stale=0 ;; esac
fi
first_write=0
[ -e "$SESSION_RESTORED" ] || { first_write=1; : > "$SESSION_RESTORED"; }
if [ "$first_write" = 1 ] && [ "$stale" = 1 ]; then
    library="$(realpath "$HOME/Pictures/Wallpapers" 2>/dev/null || true)"
    selected="$(cat "$library/.current-wallpaper" 2>/dev/null || true)"
    selected="$library/$selected"
    if [ -n "$library" ] && [ -f "$selected" ]; then
        selected="$(realpath "$selected")"
        if [ "$selected" != "$WALL" ]; then
            mkdir -p "$CACHE"
            echo "plasma-wallpaper-watch: restoring $selected at login" >> "$LOG"
            exec "$HOME/.config/scripts/wal-set.sh" "$selected" >> "$LOG" 2>&1
        fi
    fi
fi

# Dolphin's "Set as Wallpaper" points Plasma at the file where it lies. The
# durable choice (.current-wallpaper, read at the next login) and DeskStyle
# only accept direct files of the library, so an outside pick was themed once
# and then reverted at the next login. Copy it in and theme from the copy;
# wal-set then repoints Plasma at it, and that write dedupes below.
library="$(realpath "$HOME/Pictures/Wallpapers" 2>/dev/null || true)"
ext="${WALL##*.}"
case "${ext,,}" in png|jpg|jpeg|webp|bmp) supported=1 ;; *) supported=0 ;; esac
if [ -n "$library" ] && [ -d "$library" ] && [ "$supported" = 1 ] \
   && [ "$(dirname "$WALL")" != "$library" ]; then
    name="${WALL##*/}"
    stem="${name%.*}"
    dest="$library/$name"
    n=2
    while [ -e "$dest" ] && ! cmp -s "$WALL" "$dest"; do
        dest="$library/$stem-$n.$ext"
        n=$((n + 1))
    done
    if [ -e "$dest" ] || cp --reflink=auto "$WALL" "$dest"; then
        # Already themed from the copy: a failed repoint must not loop.
        [ "$(cat "$CACHE/current" 2>/dev/null)" = "$dest" ] && exit 0
        mkdir -p "$CACHE"
        echo "plasma-wallpaper-watch: imported $WALL as $dest" >> "$LOG"
        exec "$HOME/.config/scripts/wal-set.sh" "$dest" >> "$LOG" 2>&1
    fi
fi

# Already themed from this image? Then this appletsrc write was some other
# applet's state and there is nothing to do.
if [ -f "$CACHE/current" ] && [ "$(cat "$CACHE/current")" = "$WALL" ]; then
    exit 0
fi

mkdir -p "$CACHE"
echo "plasma-wallpaper-watch: Plasma set $WALL" >> "$LOG"
exec "$HOME/.config/scripts/wal-set.sh" "$WALL" >> "$LOG" 2>&1
