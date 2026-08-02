#!/usr/bin/env bash
# wal-prepare.sh /path/to/image
#
# Pre-computes and caches everything wal-set.sh needs to APPLY an image, but
# never touches Theme.qml/kitty/Hyprland itself:
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
# (ImageMagick, PIL) has already happened and applying it is just a handful of
# small file writes.
#
# Everything this script caches is a property of the IMAGE, which is what makes
# it worth warming over the whole directory. Anything that depends on the LIVE
# DESKTOP instead (monitor geometry, how much of the screen the panel currently
# covers) deliberately does NOT belong here — it would mean redoing the work for
# every image on every desktop change, almost all of it for images that never
# get applied. The Quickshell panel handles that side itself now, per frame,
# when it draws the wallpaper.
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

# ---- NOTE: no pre-tiled PNG any more --------------------------------------
# This used to render a full-screen pre-tiled PNG per monitor resolution, purely
# because hyprpaper could only display one image and had no tiling of its own.
# The panel draws the wallpaper now (quickshell-files/Wall.qml) and tiles the
# SOURCE directly with Image.Tile at its natural size, which is the same picture
# with no intermediate file — so the whole step is gone, along with an
# ImageMagick pass per wallpaper per monitor size.

# ---- colour palette -------------------------------------------------------
# Regenerate when the cache is missing, the wallpaper changed, the extractor
# itself changed, OR the Settings program's model changed — otherwise a palette
# cached by an older wal-extract.py (e.g. before the pastel-saturation pass)
# sticks forever and the desktop keeps the old, harsher colours for that
# wallpaper.
#
# settings.json is in that list because four Appearance keys are INPUTS to
# wal-extract.py (themeMode, accentOverride, paletteColorCount, pureBlackBg —
# it reads them itself). Keying on the file's mtime rather than on the four
# values costs a re-extract (~0.2s, for one image, lazily) after any unrelated
# settings edit, and buys not having to parse JSON in two languages and keep
# the two parsers agreeing. The panel re-runs wal-set.sh when one of the four
# changes (SettingsApply.qml), which is what turns this into "the toggle
# applies immediately".
#
# "the extractor itself changed" cannot be an mtime test: wal-extract.py is a
# /nix/store symlink and every store path carries the epoch mtime, so
# `wal-extract.py -nt $THEMEFILE` is ALWAYS false and the cache would keep an
# old palette forever after a rebuild that changed the derivation. Instead key
# on the RESOLVED store path, which is content-addressed — it changes iff the
# extractor's bytes change — recorded in a sidecar and compared.
SETTINGS="$CONFIG/quickshell/settings.json"
EXTRACT_SIG="$(readlink -f "$SCRIPTS/wal-extract.py")"
SIGFILE="$THEMEFILE.src"
if [ ! -f "$THEMEFILE" ] || [ "$WALL" -nt "$THEMEFILE" ] \
   || [ "$(cat "$SIGFILE" 2>/dev/null)" != "$EXTRACT_SIG" ] \
   || { [ -f "$SETTINGS" ] && [ "$SETTINGS" -nt "$THEMEFILE" ]; }; then
    "$SCRIPTS/wal-extract.py" "$WALL" > "$THEMEFILE"
    printf '%s\n' "$EXTRACT_SIG" > "$SIGFILE"
fi

# ---- blurred backdrop -----------------------------------------------------
# The panel draws this behind the sharp wallpaper, filling the strip that opens
# up between the panel edge and the wallpaper while the panel is being narrowed
# (WallpaperLayer.qml).
#
# It is a REAL Gaussian, computed once and cached, not a runtime effect. The
# first attempt just decoded the wallpaper at ~96px and let the GPU stretch it,
# on the theory that a bilinear upscale is a free blur — it is free, but it is
# not a blur: at 20x magnification the image was still plainly legible, with
# interpolation facets. Downscaling to 400px and applying a real blur gives
# something genuinely diffuse and smooth, and upscaling THAT is invisible
# because the content no longer has any high frequencies left to alias.
#
# PNG, not JPEG: the output is nothing but smooth gradients, which is the exact
# case where JPEG bands visibly. It costs ~35K and a third of a second, once.
BLUR="$CACHE/blur-$KEY.png"
if [ ! -f "$BLUR" ] || [ "$WALL" -nt "$BLUR" ]; then
    magick "${WALL}[0]" -auto-orient -resize 400x -blur 0x36 -strip "$BLUR" 2>/dev/null || true
fi

# ---- picker thumbnail -----------------------------------------------------
# A small, persistent thumbnail so WallpaperPicker.qml's grid paints instantly
# instead of decoding the full-res original (some are 4000px+) on every open —
# the picker's QML tree is torn down and rebuilt on every apply's hot-reload, so
# without this the big decodes happen again each time. Same idea as filer's
# thumbnail cache, keyed by the KEY (md5 of the realpath) this script already
# uses, so list-wallpapers.sh can point the grid straight at it. Cheap and
# cached; regenerated only when the source is newer. `[0]` takes the first frame
# (harmless for the single-frame formats the picker lists); JPEG since wallpapers
# are opaque photos/textures and it decodes faster/smaller than PNG.
THUMBS="$CACHE/thumbs"
THUMB="$THUMBS/$KEY.jpg"
mkdir -p "$THUMBS"
if [ ! -f "$THUMB" ] || [ "$WALL" -nt "$THUMB" ]; then
    magick "${WALL}[0]" -auto-orient -strip -thumbnail '400x400>' -quality 82 "$THUMB" 2>/dev/null || true
fi

echo "wal-prepare: $WALL ready (mode=$MODE, ${IW}x${IH})"
