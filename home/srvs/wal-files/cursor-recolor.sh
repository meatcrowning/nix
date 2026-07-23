#!/usr/bin/env bash
# cursor-recolor.sh — regenerate an accent-tinted copy of the GoogleDot-Black
# cursor theme and apply it live, so the dot's white outline follows the
# wallpaper's accent colour (the black core stays black).
#
#   cursor-recolor.sh <accent-hex> [size]
#
# <accent-hex> is "rrggbb" (no leading #), the ACCENT var wal-set.sh derives
# from the wallpaper palette. Called from wal-set.sh on every theme apply.
#
# XCursor files are packed binaries, so we can't just recolour them in place.
# Instead: decompile GoogleDot-Black ONCE (cached under ~/.cache/wal/
# cursor-master — the source never changes), then per accent change batch-
# recolour every extracted PNG with ImageMagick's `+level-colors black,#accent`
# (maps the black core -> black, the white outline -> accent, the anti-aliased
# greys interpolate between, alpha preserved), recompile with xcursorgen into
# ~/.icons/GoogleDot-Accent, and hot-reload with `hyprctl setcursor`.
#
# Decompile is ~1s (once ever); the per-accent recolour is ~2.5s.
set -u

ACCENT="${1:-}"
SIZE="${2:-${XCURSOR_SIZE:-22}}"
case "$ACCENT" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) echo "cursor-recolor: bad accent '$ACCENT' (want rrggbb)" >&2; exit 1 ;;
esac
ACCENT="$(printf '%s' "$ACCENT" | tr 'A-F' 'a-f')"

SRC="$HOME/.icons/GoogleDot-Black"
DST="$HOME/.icons/GoogleDot-Accent"
CACHE="$HOME/.cache/wal"
MASTER="$CACHE/cursor-master"
STAMP="$CACHE/cursor-accent"
mkdir -p "$CACHE"

# nothing to tint if the base theme isn't installed
if [ ! -d "$SRC/cursors" ]; then
    echo "cursor-recolor: $SRC not found, skipping" >&2
    exit 0
fi
# tools (all in home.packages via wal.nix); no-op rather than fail the whole
# theme apply if something is missing.
for t in xcur2png xcursorgen magick; do
    command -v "$t" >/dev/null 2>&1 || { echo "cursor-recolor: missing $t, skipping" >&2; exit 0; }
done

apply() { hyprctl setcursor GoogleDot-Accent "$SIZE" >/dev/null 2>&1 || true; }

# already generated for this accent? just re-apply live and stop.
if [ "$(cat "$STAMP" 2>/dev/null)" = "$ACCENT" ] && [ -f "$DST/cursors/left_ptr" ]; then
    apply
    exit 0
fi

# ---- STAGE 1: decompile GoogleDot-Black once (rebuild only if source newer) --
if [ ! -f "$MASTER/.done" ] || [ "$SRC/index.theme" -nt "$MASTER/.done" ]; then
    rm -rf "$MASTER"; mkdir -p "$MASTER"
    ( cd "$MASTER"
      for f in $(find "$SRC/cursors" -maxdepth 1 -type f -printf '%f\n'); do
          xcur2png "$SRC/cursors/$f" -c "$f.conf" >/dev/null 2>&1
      done )
    touch "$MASTER/.done"
fi

# ---- STAGE 2: recolour + recompile into GoogleDot-Accent ---------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cursor-recolor.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/build" "$DST/cursors"

# One mogrify recolours every extracted frame at once; -path writes the copies
# into WORK so the cached grey master is left untouched.
magick mogrify -path "$WORK/build" +level-colors "black,#$ACCENT" "$MASTER"/*.png
cp "$MASTER"/*.conf "$WORK/build/"
# xcursorgen reads the PNG basenames from each .conf, so run it in that dir.
( cd "$WORK/build"
  for c in *.conf; do
      xcursorgen "$c" "$DST/cursors/${c%.conf}" 2>/dev/null || true
  done )
# Copy the alias symlinks (pointer -> left_ptr, the hashed names, ...) verbatim.
for l in $(find "$SRC/cursors" -maxdepth 1 -type l -printf '%f\n'); do
    cp -a "$SRC/cursors/$l" "$DST/cursors/$l" 2>/dev/null || true
done

cat > "$DST/index.theme" <<EOF
[Icon Theme]
Name=GoogleDot-Accent
Comment=GoogleDot-Black recoloured to the wallpaper accent by cursor-recolor.sh
Inherits="hicolor"
EOF
cp "$DST/index.theme" "$DST/cursor.theme" 2>/dev/null || true

printf '%s' "$ACCENT" > "$STAMP"
apply
echo "cursor-recolor: GoogleDot-Accent tinted #$ACCENT, applied at ${SIZE}px"
