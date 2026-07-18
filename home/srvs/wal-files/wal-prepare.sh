#!/usr/bin/env bash
# wal-prepare.sh /path/to/image
#
# Pre-computes and caches everything wal-set.sh needs to APPLY an image, but
# never touches hyprpaper/Theme.qml/kitty/Hyprland itself:
#   - the tile-vs-scale mode decision + source dimensions
#   - the tiled PNG per current monitor resolution (tile mode only)
#   - the extracted colour palette (wal-extract.py)
#
# Idempotent and safe to call repeatedly — each step is skipped if its cache
# is already newer than the source image. wal-set.sh calls this itself as its
# first step (so a one-off manual wallpaper change still works standalone),
# and wal-prepare-all.sh calls it in bulk for every image under
# ~/Pictures/wall whenever that directory changes (see wal-prepare.path), so
# that by the time you flip to one in WallpaperPicker.qml the slow part
# (ImageMagick, PIL) has already happened and applying it is just hyprpaper/
# theme file writes.
set -u

CONFIG="$HOME/.config"
CACHE="$HOME/.cache/wal"
SCRIPTS="$CONFIG/scripts"
THEMES="$CACHE/themes"
mkdir -p "$CACHE" "$THEMES"

WALL="${1:?usage: wal-prepare.sh /path/to/image}"
[ -f "$WALL" ] || { echo "wal-prepare: not found: $WALL" >&2; exit 1; }
WALL="$(realpath "$WALL")"
KEY="$(printf '%s' "$WALL" | md5sum | cut -d' ' -f1)"
MODEFILE="$THEMES/$KEY.mode"
THEMEFILE="$THEMES/$KEY.env"

# ---- mode + dimensions ---------------------------------------------------
# Decide tile-vs-scale from the source image itself: a small, roughly-square
# image is treated as a repeating texture and tiled; anything else (a normal
# photo/aspect-ratio image) is scaled to cover. Override with WAL_MODE=tile|
# scale if you ever need to force it.
if [ ! -f "$MODEFILE" ] || [ "$WALL" -nt "$MODEFILE" ]; then
    IW="$(magick identify -format '%w' "$WALL" 2>/dev/null)"
    IH="$(magick identify -format '%h' "$WALL" 2>/dev/null)"
    MODE="${WAL_MODE:-}"
    if [ -z "$MODE" ]; then
        MODE="scale"
        if [ -n "$IW" ] && [ -n "$IH" ]; then
            max=$IW; min=$IH; [ "$IH" -gt "$IW" ] && { max=$IH; min=$IW; }
            if [ "$max" -le 512 ] && [ $((min * 4)) -ge $((max * 3)) ]; then
                MODE="tile"
            fi
        fi
    fi
    { echo "MODE=$MODE"; echo "IW=${IW:-0}"; echo "IH=${IH:-0}"; } > "$MODEFILE"
fi
# shellcheck disable=SC1090
. "$MODEFILE"

# ---- tiled PNG per current monitor resolution (tile mode only) ----------
if [ "$MODE" = "tile" ]; then
    MONS="$(hyprctl monitors -j 2>/dev/null \
        | python3 -c 'import sys,json;[print(m["name"],m["width"],m["height"]) for m in json.load(sys.stdin)]' \
        2>/dev/null)"
    [ -z "$MONS" ] && MONS="eDP-1 2560 1600"
    while read -r name w h; do
        [ -z "$name" ] && continue
        out="$CACHE/tiled-${w}x${h}.png"
        if [ ! -f "$out" ] || [ "$WALL" -nt "$out" ]; then
            magick -size "${w}x${h}" tile:"$WALL" "$out"
        fi
    done <<EOF
$MONS
EOF
fi

# ---- colour palette -------------------------------------------------------
if [ ! -f "$THEMEFILE" ] || [ "$WALL" -nt "$THEMEFILE" ]; then
    "$SCRIPTS/wal-extract.py" "$WALL" > "$THEMEFILE"
fi

echo "wal-prepare: $WALL ready (mode=$MODE, ${IW}x${IH})"
