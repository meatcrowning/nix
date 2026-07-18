#!/bin/sh
# list-wallpapers.sh
#
# One absolute path per line for every image directly under ~/Pictures/wall,
# name-sorted. Used by WallpaperPicker.qml to populate its live picker list;
# it's rerun on a short poll while the picker is open so a newly-dropped-in
# image shows up without restarting anything (see WallpaperPicker.qml's
# rescanTimer).

DIR="$HOME/Pictures/wall"
[ -d "$DIR" ] || exit 0
find "$DIR" -maxdepth 1 -type f \( \
    -iname '*.png'  -o -iname '*.jpg' -o -iname '*.jpeg' \
    -o -iname '*.webp' -o -iname '*.bmp' \
    \) | sort
