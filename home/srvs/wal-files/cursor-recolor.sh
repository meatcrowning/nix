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
# greys interpolate between). `-channel RGB ... +channel` is essential — without
# it +level-colors also levels the ALPHA channel, forcing every pixel opaque so
# the cursor renders inside a black box. Then recompile with xcursorgen and
# hot-reload with `hyprctl setcursor`.
#
# The theme is named per-accent ("GoogleDot-<accent>") ON PURPOSE: hyprcursor
# caches a loaded theme by name for the life of the Hyprland process and a
# same-name `setcursor` does NOT re-read it from disk, so re-tinting a fixed
# name would keep drawing the stale (previous-accent) cursor until relogin. A
# fresh name per accent always loads fresh. We also point Hyprland's cursor env
# (in ~/.config/hypr/hyprland.lua) at the current name so a re-login loads the
# right theme natively at startup instead of relying on setcursor timing (which
# doesn't stick that early), and prune the other accent themes to save disk
# (~25MB each). Decompile is ~1s (once ever); the per-accent recolour is ~2.5s.
set -u

# xcur2png/xcursorgen/magick live in the Nix profile, not on the bare system
# PATH. wal-set.sh is often spawned from Quickshell (the wallpaper picker's
# commit), whose PATH is only /usr/bin etc. — so these tools would be "missing"
# and the whole cursor step would silently skip. @toolPath@ is substituted at
# build time (see home/srvs/wal.nix) with their store bin dirs; prepend it so we
# always find them regardless of the ambient PATH.
PATH="@toolPath@:$PATH"

# Serialise concurrent runs. wal-set.sh now fires this DETACHED (setsid &) on
# every theme apply, so a burst of wallpaper switches can overlap two of these,
# both recolouring into ~/.icons and pruning each other's dirs. Take an flock
# (blocking) up front so they run one-at-a-time and converge on the last accent;
# if flock is somehow missing, fall through and run unguarded rather than fail.
if command -v flock >/dev/null 2>&1 && [ "${_WAL_CURSOR_LOCKED:-}" != 1 ]; then
    mkdir -p "$HOME/.cache/wal"
    export _WAL_CURSOR_LOCKED=1
    exec flock "$HOME/.cache/wal/.cursor-recolor.lock" "$0" "$@"
fi

ACCENT="${1:-}"
SIZE="${2:-${XCURSOR_SIZE:-22}}"
case "$ACCENT" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) echo "cursor-recolor: bad accent '$ACCENT' (want rrggbb)" >&2; exit 1 ;;
esac
ACCENT="$(printf '%s' "$ACCENT" | tr 'A-F' 'a-f')"

SRC="$HOME/.icons/GoogleDot-Black"
NAME="GoogleDot-$ACCENT"
DST="$HOME/.icons/$NAME"
LUA="$HOME/.config/hypr/hyprland.lua"
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

# Point Hyprland's startup cursor env at $NAME (persists the accent cursor across
# a re-login). hyprland.lua is a seeded-once mutable file; edit the live copy in
# place, same as wal-set.sh does for the border colours.
pin_env() {
    [ -f "$LUA" ] || return 0
    sed -i -E 's/(hl\.env\("XCURSOR_THEME", ")GoogleDot-[^"]*(")/\1'"$NAME"'\2/' "$LUA"
    sed -i -E 's/(hl\.env\("HYPRCURSOR_THEME", ")GoogleDot-[^"]*(")/\1'"$NAME"'\2/' "$LUA"
}
# setcursor swaps the theme, but Hyprland keeps compositing the cursor buffer it
# already has until the pointer's shape next changes — i.e. until you hover onto
# a new surface — so the fresh tint doesn't show until you move the mouse over
# something. Issue the real set, then bounce the size by 1px and back: a size
# change forces hyprcursor to re-rasterise and re-upload the buffer NOW, which
# repaints the on-screen cursor immediately without waiting for a hover. The
# final call restores the correct size, so the 1px blip lasts one IPC round-trip.
apply() {
    hyprctl setcursor "$NAME" "$SIZE" >/dev/null 2>&1 || true
    hyprctl setcursor "$NAME" "$((SIZE + 1))" >/dev/null 2>&1 || true
    hyprctl setcursor "$NAME" "$SIZE" >/dev/null 2>&1 || true
}

# Drop stale per-accent themes (keep the current one and the GoogleDot-Black
# base). Match only the 6-hex accent suffix so "GoogleDot-Black" is never hit.
prune() {
    for d in "$HOME"/.icons/GoogleDot-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]; do
        [ -d "$d" ] || continue
        [ "$d" = "$DST" ] && continue
        rm -rf "$d"
    done
}

# already generated for this accent? just re-pin + re-apply and stop.
if [ "$(cat "$STAMP" 2>/dev/null)" = "$ACCENT" ] && [ -f "$DST/cursors/left_ptr" ]; then
    pin_env; apply; prune
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

# ---- STAGE 2: recolour + recompile into GoogleDot-<accent> -------------------
# Build in a temp theme dir and mv it into place so a re-login can never catch a
# half-written theme.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cursor-recolor.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/build" "$WORK/theme/cursors"

# Recolour every extracted frame with `+level-colors black,#accent` (black core
# -> black, white outline -> accent). `-channel RGB ... +channel` keeps the alpha
# intact (see the header note on the black box); -path writes the copies into
# WORK so the cached grey master is left untouched.
#
# This is the whole cost of a re-tint (~2.4s single-threaded over the master's
# ~1800 frames). mogrify itself is one process, so split the frames across all
# cores with xargs -P — each batch is an independent mogrify writing its own
# basenames into the same -path dir, no collisions — which cuts it to ~0.6s. Fall
# back to a single mogrify if nproc/xargs somehow aren't around.
JOBS="$(nproc 2>/dev/null || echo 1)"
if command -v xargs >/dev/null 2>&1 && [ "$JOBS" -gt 1 ]; then
    printf '%s\n' "$MASTER"/*.png \
        | xargs -P "$JOBS" -n 64 magick mogrify -path "$WORK/build" -channel RGB +level-colors "black,#$ACCENT" +channel
else
    magick mogrify -path "$WORK/build" -channel RGB +level-colors "black,#$ACCENT" +channel "$MASTER"/*.png
fi
cp "$MASTER"/*.conf "$WORK/build/"
# Recompile each cursor. xcursorgen reads the PNG basenames from each .conf, so
# run it in that dir; parallelise across cores too (cheap, but free). The conf
# names are our own extracted cursor names, so splicing WORK into the child is
# safe.
( cd "$WORK/build"
  if command -v xargs >/dev/null 2>&1 && [ "$JOBS" -gt 1 ]; then
      printf '%s\n' *.conf | xargs -P "$JOBS" -I{} sh -c \
          'c="$1"; xcursorgen "$c" "'"$WORK"'/theme/cursors/${c%.conf}" 2>/dev/null || true' _ {}
  else
      for c in *.conf; do
          xcursorgen "$c" "$WORK/theme/cursors/${c%.conf}" 2>/dev/null || true
      done
  fi )
# Copy the alias symlinks (pointer -> left_ptr, the hashed names, ...) verbatim.
for l in $(find "$SRC/cursors" -maxdepth 1 -type l -printf '%f\n'); do
    cp -a "$SRC/cursors/$l" "$WORK/theme/cursors/$l" 2>/dev/null || true
done
cat > "$WORK/theme/index.theme" <<EOF
[Icon Theme]
Name=$NAME
Comment=GoogleDot-Black recoloured to the wallpaper accent by cursor-recolor.sh
Inherits="hicolor"
EOF
cp "$WORK/theme/index.theme" "$WORK/theme/cursor.theme"

rm -rf "$DST"
mv "$WORK/theme" "$DST"

printf '%s' "$ACCENT" > "$STAMP"
pin_env; apply; prune
echo "cursor-recolor: $NAME tinted #$ACCENT, applied at ${SIZE}px"
