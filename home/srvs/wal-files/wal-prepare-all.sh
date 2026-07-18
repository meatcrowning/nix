#!/usr/bin/env bash
# wal-prepare-all.sh
#
# Runs wal-prepare.sh on every image under ~/Pictures/wall, so by the time you
# flip to one in quickshell's WallpaperPicker its tile/theme cache is already
# warm and wal-set.sh just has to apply it. Triggered by wal-prepare.path
# whenever that directory changes (a new image dropped in), and once at
# Hyprland startup to backfill anything already there.
set -u

"$HOME/.config/quickshell/scripts/list-wallpapers.sh" | while IFS= read -r img; do
    [ -n "$img" ] && "$HOME/.config/scripts/wal-prepare.sh" "$img"
done
