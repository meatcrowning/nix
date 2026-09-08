#!/usr/bin/env bash
# wal-prepare.sh /path/to/image
#
# Pre-computes and caches everything wal-set.sh needs to APPLY an image, but
# never touches Theme.qml/kitty/Hyprland itself:
#   - the tile-vs-scale mode decision + source dimensions
#   - the tiled PNG per current monitor resolution (tile mode only)
#   - the extracted colour palette (wal-extract.py)
#   - a versioned profile manifest and the three writable Oxygen schemes
#
# Idempotent and safe to call repeatedly — each step is skipped if its cache
# is already newer than the source image. wal-set.sh calls this itself as its
# first step (so a one-off manual wallpaper change still works standalone),
# and wal-prepare-all.sh calls it in bulk for every image under
# ~/Pictures/Wallpapers whenever that directory changes (see wal-prepare.path), so
# that by the time you flip to one in WallpaperPicker.qml the slow part
# (ImageMagick, PIL) has already happened and applying it is just a handful of
# small file writes.  The profile manifest is deliberately separate from the
# live files: a future appearance controller can validate and install a whole
# already-prepared generation without treating this warm-cache job as an apply.
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
PROFILES="$CACHE/profiles"
mkdir -p "$CACHE" "$THEMES" "$PROFILES"

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
# settings.json is in that list because several Appearance keys are INPUTS to
# wal-extract.py (themeMode, accentOverride, paletteColorCount, pureBlackBg,
# paletteVariant, lightMode — it reads them itself). Keying on the
# file's mtime rather than on those values costs a re-extract (~0.2s, for one
# image, lazily) after any unrelated
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

# ---- prepared profile ----------------------------------------------------
# A profile is an immutable-in-practice cache entry for one wallpaper and the
# palette inputs that produced it.  It is NOT the active theme state: writing it
# must never repaint Plasma, notify applications, or replace a live scheme.
#
# Keep the three scheme bodies beside the palette rather than in their live
# ~/.local/share/color-schemes destination.  plasma-scheme.py's --no-apply
# mode only mints files; it deliberately avoids KConfig, D-Bus, and KWin.  The
# appearance controller can later copy the selected already-minted body into
# that live destination as its short critical transaction.
PROFILE_DIR="$PROFILES/$KEY"
MANIFEST="$PROFILE_DIR/manifest.json"
PROFILE_SIG="$PROFILE_DIR/input.sha256"
mkdir -p "$PROFILE_DIR"

# The resolved paths are content-addressed for Nix-installed scripts/templates,
# unlike their epoch mtimes.  Include both script and template identities so a
# rebuild that changes scheme minting invalidates old prepared artifacts.
scheme_sig() {
    for f in \
        "$SCRIPTS/plasma-scheme.py" \
        "$SCRIPTS/plasma-scheme-template.colors" \
        "$SCRIPTS/plasma-light-scheme-template.colors"; do
        [ -e "$f" ] && readlink -f "$f" || printf 'missing:%s\n' "$f"
    done
}
INPUT_SIG="$(
    {
        printf 'profile-v1\nwall=%s\n' "$WALL"
        # The extractor's output is itself the complete set of wallpaper and
        # Settings-derived palette inputs.  Include its bytes, not only its
        # mtime, so profileHash changes whenever a palette option changes.
        printf 'palette='
        sha256sum "$THEMEFILE" | cut -d' ' -f1
        scheme_sig
    } | sha256sum | cut -d' ' -f1
)"

# shellcheck disable=SC1090
. "$THEMEFILE"
UI_ACCENT="${PLASMA_ACCENT:-$ACCENT}"

prepare_scheme() {
    name="$1"
    template="$2"
    shift 2
    out="$PROFILE_DIR/$name.colors"
    # The profile's signature covers the script/template identities, while the
    # palette file mtime covers every Settings-derived colour input.
    if [ ! -f "$out" ] || [ "$THEMEFILE" -nt "$out" ] \
       || [ "$(cat "$PROFILE_SIG" 2>/dev/null)" != "$INPUT_SIG" ]; then
        "$SCRIPTS/plasma-scheme.py" --template "$template" --name "$name" \
            --out "$out" --accent "$ACCENT" --ui-accent "$UI_ACCENT" \
            --no-apply "$@"
    fi
}

# These templates are installed by plasma-colors.nix.  A non-Plasma host or a
# partial activation may not have them yet; leave a valid palette/asset profile
# behind and mark its scheme set incomplete in the manifest instead of failing
# the wallpaper pre-warm job.
SCHEMES_READY=true
DARK_TEMPLATE="$SCRIPTS/plasma-scheme-template.colors"
LIGHT_TEMPLATE="$SCRIPTS/plasma-light-scheme-template.colors"
if [ -f "$DARK_TEMPLATE" ] && [ -f "$LIGHT_TEMPLATE" ] \
   && [ -x "$SCRIPTS/plasma-scheme.py" ]; then
    if [ "$BG" = "464540" ]; then
        prepare_scheme OxygenDarkFlat "$DARK_TEMPLATE" --background "$BG" || SCHEMES_READY=false
    else
        prepare_scheme OxygenDarkFlat "$DARK_TEMPLATE" || SCHEMES_READY=false
    fi
    prepare_scheme OxygenDarkNeutral "$DARK_TEMPLATE" --surface-color "$BGALT" || SCHEMES_READY=false
    prepare_scheme OxygenLightFlat "$LIGHT_TEMPLATE" || SCHEMES_READY=false
    for scheme in OxygenDarkFlat OxygenDarkNeutral OxygenLightFlat; do
        [ -s "$PROFILE_DIR/$scheme.colors" ] || SCHEMES_READY=false
    done
else
    SCHEMES_READY=false
fi

# Raster Oxygen icons are the other wallpaper-coloured Plasma surface. Build
# their immutable accent-qualified theme while the old appearance is still
# live; wal-set activates this already-complete directory in the short commit.
if [ -x "$SCRIPTS/oxygen-live-icons.py" ]; then
    "$SCRIPTS/oxygen-live-icons.py" --accent "$UI_ACCENT" --no-activate \
        >/dev/null || SCHEMES_READY=false
fi

# Aero is installed only where the matching Plasma theme is present.  It is an
# owned candidate in plasma-scheme.py, but unlike the three shared Oxygen
# shapes it has no portable template.  Pre-mint it when the host supplies its
# own source; an absent Aero body remains an explicit unsupported selected
# scheme rather than falling back to minting during Apply.
for AERO_TEMPLATE in \
    /run/current-system/sw/share/color-schemes/Aero.colors \
    /usr/share/color-schemes/Aero.colors; do
    if [ -f "$AERO_TEMPLATE" ]; then
        prepare_scheme Aero "$AERO_TEMPLATE" || true
        break
    fi
done

# Atomic publication makes a reader see either the prior complete manifest or
# this complete one, never a half-written JSON document.  Artifact paths are
# deterministic and live in PROFILE_DIR; the controller must still check
# `schemesReady` before it treats this profile as apply-ready.
tmp_manifest="$(mktemp "$PROFILE_DIR/.manifest.json.XXXXXX")"
if ! jq -n \
    --arg source "$WALL" \
    --arg key "$KEY" \
    --arg mode "$MODE" \
    --arg blur "$BLUR" \
    --arg thumbnail "$THUMB" \
    --arg palette "$THEMEFILE" \
    --arg profileDir "$PROFILE_DIR" \
    --arg profileHash "$INPUT_SIG" \
    --arg accent "$ACCENT" \
    --arg uiAccent "$UI_ACCENT" \
    --argjson schemesReady "$SCHEMES_READY" \
    '{version: 1, source: $source, key: $key, mode: $mode,
      palette: {path: $palette, accent: $accent, uiAccent: $uiAccent},
      assets: {blur: $blur, thumbnail: $thumbnail},
      schemes: {ready: $schemesReady, directory: $profileDir,
                dark: ($profileDir + "/OxygenDarkFlat.colors"),
                darkNeutral: ($profileDir + "/OxygenDarkNeutral.colors"),
                light: ($profileDir + "/OxygenLightFlat.colors"),
                aero: ($profileDir + "/Aero.colors")},
      profileHash: $profileHash}' > "$tmp_manifest"; then
    rm -f "$tmp_manifest"
    echo "wal-prepare: could not publish profile manifest" >&2
    exit 1
fi
mv -f "$tmp_manifest" "$MANIFEST"
printf '%s\n' "$INPUT_SIG" > "$PROFILE_SIG"

echo "wal-prepare: $WALL ready (mode=$MODE, ${IW}x${IH})"
