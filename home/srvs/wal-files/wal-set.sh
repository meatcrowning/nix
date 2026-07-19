#!/usr/bin/env bash
# wal-set.sh — set a tiled wallpaper and recolour the whole desktop from it.
#
#   wal-set.sh [--wallpaper-only] [/path/to/wallpaper]
#
# With no argument it re-applies the last-used wallpaper (or wall.png on first
# run). It:
#   1. delegates to wal-prepare.sh for the mode decision + tiled PNG + colour
#      palette — all cached, so this is a fast no-op once an image has been
#      prepared (see wal-prepare-all.sh / wal-prepare.path, which pre-warm
#      every image under ~/Pictures/wall as soon as it's added)
#   2. sets it via hyprpaper (live if running, else started)
#   3. regenerates the Quickshell palette (panel hot-reloads)
#   4. regenerates the kitty colours (reloaded via SIGUSR1)
#   5. sets Hyprland's focused-window border (live + persisted)
#
# --wallpaper-only stops after step 2 — no Theme.qml write, so no Quickshell
# reload. Rewriting Theme.qml is exactly what makes Quickshell hot-reload its
# *entire* config (destroying and recreating every QML object, confirmed by
# testing — see CLAUDE.md's "Reload lifecycle gotchas"), which would close
# WallpaperPicker.qml's own window out from under you on every single flip.
# So the picker previews with --wallpaper-only while flipping (instant, no
# reload, stays open) and only runs the full apply once, when it closes.
#
# Everything is idempotent, so it is safe to run on every Hyprland start.
set -u

WALLPAPER_ONLY=0
if [ "${1:-}" = "--wallpaper-only" ]; then
    WALLPAPER_ONLY=1
    shift
fi

CONFIG="$HOME/.config"
CACHE="$HOME/.cache/wal"
SCRIPTS="$CONFIG/scripts"
STATE="$CACHE/current"
DEFAULT_WALL="$CONFIG/wall.png"
mkdir -p "$CACHE"

# ---- 1. resolve the wallpaper -------------------------------------------------
WALL="${1:-}"
if [ -z "$WALL" ]; then
    if [ -f "$STATE" ]; then WALL="$(cat "$STATE")"; else WALL="$DEFAULT_WALL"; fi
fi
if [ ! -f "$WALL" ]; then
    echo "wal-set: wallpaper not found: $WALL" >&2
    exit 1
fi
WALL="$(realpath "$WALL")"
printf '%s' "$WALL" > "$STATE"
echo "wal-set: wallpaper = $WALL"

# ---- 2. mode/tile/palette (delegated, cached — see wal-prepare.sh) -----------
"$SCRIPTS/wal-prepare.sh" "$WALL"
THEMES="$CACHE/themes"
KEY="$(printf '%s' "$WALL" | md5sum | cut -d' ' -f1)"
# shellcheck disable=SC1090
. "$THEMES/$KEY.mode"   # sets MODE, IW, IH

# `hyprctl monitors` gives "name width height"; we need per-monitor pixels to
# map each one to the right image below (tiled PNG or the source itself).
MONS="$(hyprctl monitors -j 2>/dev/null \
    | python3 -c 'import sys,json;[print(m["name"],m["width"],m["height"]) for m in json.load(sys.stdin)]' \
    2>/dev/null)"
[ -z "$MONS" ] && MONS="eDP-1 2560 1600"   # fallback if IPC not up yet

PRELOADS=""   # unique images to preload
WALLLINES=""  # "monitor,image" pairs
if [ "$MODE" = "tile" ]; then
    # wal-prepare.sh already generated the tiled PNG per monitor resolution.
    while read -r name w h; do
        [ -z "$name" ] && continue
        out="$CACHE/tiled-${KEY}-${w}x${h}.png"
        case "$PRELOADS" in *"$out"*) ;; *) PRELOADS="$PRELOADS$out
";; esac
        WALLLINES="$WALLLINES$name,$out
"
    done <<EOF
$MONS
EOF
else
    # Scale mode: preload the source once, let hyprpaper cover each monitor.
    PRELOADS="$WALL
"
    while read -r name w h; do
        [ -z "$name" ] && continue
        WALLLINES="$WALLLINES$name,$WALL
"
    done <<EOF
$MONS
EOF
fi

# persist for next login
{
    echo "splash = false"
    echo "ipc = on"
    printf '%s' "$PRELOADS" | while read -r p; do [ -n "$p" ] && echo "preload = $p"; done
    printf '%s' "$WALLLINES" | while read -r l; do [ -n "$l" ] && echo "wallpaper = $l"; done
} > "$CONFIG/hypr/hyprpaper.conf"

# start hyprpaper if needed, then give it a moment to come up
if ! pgrep -x hyprpaper >/dev/null 2>&1; then
    hyprpaper >/dev/null 2>&1 &
    for _ in 1 2 3 4 5; do
        pgrep -x hyprpaper >/dev/null 2>&1 && break
        sleep 0.3
    done
    sleep 0.5   # let the IPC socket settle before the first request
fi

# apply live. hyprpaper's IPC occasionally answers "invalid request" under a
# burst, so we don't gate on a probe — we issue the real commands, retrying by
# exit code (a successful set prints nothing). NOTE: `hyprpaper unload`/
# `listloaded` return "invalid hyprpaper request" unconditionally on this
# hyprpaper build (0.8.4) regardless of syntax (tested: "all", a specific
# path, comma-separated) — so it's deliberately not called here; retrying it
# would just burn the full 5-attempt budget for nothing every single run.
# Skipping it only means old preloaded images linger in hyprpaper's memory.
retry() { for _ in 1 2 3 4 5; do "$@" >/dev/null 2>&1 && return 0; sleep 0.1; done; return 1; }
printf '%s' "$PRELOADS"  | while read -r p; do [ -n "$p" ] && retry hyprctl hyprpaper preload "$p"; done
printf '%s' "$WALLLINES" | while read -r l; do [ -n "$l" ] && retry hyprctl hyprpaper wallpaper "$l"; done

if [ "$WALLPAPER_ONLY" = 1 ]; then
    echo "wal-set: wallpaper-only, skipping theme apply"
    exit 0
fi

# ---- 3. load the palette (already extracted by wal-prepare.sh above) ---------
eval "$(cat "$THEMES/$KEY.env")"
echo "wal-set: source = ${IW}x${IH}, mode = $MODE, accent = #$ACCENT"

# ---- 4. Quickshell palette (spliced into Theme.qml; panel hot-reloads) -------
# Rewrite the block between the "wal palette" markers in Theme.qml in place, so
# Theme stays the single source of truth and there is no singleton-ordering race.
#
# IMPORTANT: this MUST edit Theme.qml in place (truncate + rewrite the SAME
# inode), never `mv` a temp file over it. Quickshell's hot-reload watches each
# loaded QML file by inode; an atomic rename gives Theme.qml a new inode while
# qs keeps watching the old (now-unlinked) one, so the panel/cheatsheet/
# notifications/launcher never see the new palette. Rewriting in place keeps the
# watched inode alive so qs reloads on every wallpaper change.
THEME="$CONFIG/quickshell/Theme.qml"
BLOCK="$CACHE/palette.inc"
cat > "$BLOCK" <<QMLEOF
    readonly property color bg:        "#$BG"
    readonly property color bgAlt:     "#$BGALT"
    readonly property color border:    "#$BORDER"
    readonly property color accent:    "#$ACCENT"   // active / occupied
    readonly property color dim:       "#$DIM"      // empty & unviewed
    readonly property color text:      "#$TEXT"
    readonly property color textDim:   "#$TEXTDIM"
    readonly property color highlight: "#$HIGHLIGHT"   // selection bg
    readonly property color ok:        "#$OK"
    readonly property color warn:      "#$WARN"
    readonly property color crit:      "#$CRIT"
    readonly property color info:      "#$INFO"
QMLEOF
awk -v inc="$BLOCK" '
    /\/\/ >>> wal palette/ { print; while ((getline line < inc) > 0) print line; skip=1; next }
    /\/\/ <<< wal palette/ { skip=0 }
    !skip { print }
' "$THEME" > "$THEME.tmp" && cat "$THEME.tmp" > "$THEME" && rm -f "$THEME.tmp"

# ---- 5. kitty colours (reloaded via SIGUSR1) ---------------------------------
cat > "$CONFIG/kitty/theme.conf" <<KITTYEOF
# GENERATED by ~/.config/scripts/wal-set.sh from the current wallpaper.
foreground            #$TEXT
background            #$BG
cursor                #$ACCENT
cursor_text_color     #$BG
selection_foreground  #$BG
selection_background  #$ACCENT
url_color             #$ACCENT
active_border_color   #$ACCENT
inactive_border_color #$BORDER
active_tab_foreground   #$BG
active_tab_background   #$ACCENT
inactive_tab_foreground #$TEXTDIM
inactive_tab_background #$BGALT

# Monochrome ANSI ramp on the wallpaper's hue.
color0  #$BG
color8  #$DIM
color1  #$CRIT
color9  #$CRIT
color2  #$OK
color10 #$OK
color3  #$WARN
color11 #$WARN
color4  #$INFO
color12 #$INFO
color5  #$TEXTDIM
color13 #$TEXT
color6  #$ACCENT
color14 #$ACCENT
color7  #$TEXT
color15 #$TEXT
KITTYEOF

# make sure kitty.conf pulls in the generated file (once)
if ! grep -q '^include theme.conf' "$CONFIG/kitty/kitty.conf" 2>/dev/null; then
    printf '\ninclude theme.conf\n' >> "$CONFIG/kitty/kitty.conf"
fi
# live-reload every running kitty
pkill -USR1 -x kitty >/dev/null 2>&1

# ---- 6. Hyprland focused-window border + hyprvtb titlebars (live + persisted)
# `hyprctl keyword` doesn't exist on the lua-config parser ("use eval"), so
# both the border and the hyprvtb titlebar-plugin colours go through one
# `hyprctl eval hl.config(...)` call for the live update, and sed against the
# palette-tagged lines in hyprland.lua for persistence across restarts.
hyprctl eval 'hl.config({
    general = { col = { active_border = "rgba('"${ACCENT}"'ee)" } },
    plugin = { hyprvtb = {
        ["col.text"]          = "rgba('"${TEXTDIM}"'ff)",
        ["col.button_border"] = "rgba('"${BORDER}"'ff)",
        ["col.accent"]        = "rgba('"${ACCENT}"'ff)",
        ["col.bg_alt"]        = "rgba('"${BGALT}"'ff)",
        ["col.crit"]          = "rgba('"${CRIT}"'ff)",
    } },
})' >/dev/null 2>&1
LUA="$CONFIG/hypr/hyprland.lua"
if [ -f "$LUA" ]; then
    sed -i -E 's/(\<active_border[[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${ACCENT}"'ee)\2/' "$LUA"
    sed -i -E 's/(\["col\.text"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${TEXTDIM}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.button_border"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${BORDER}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.accent"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${ACCENT}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.bg_alt"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${BGALT}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.crit"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${CRIT}"'ff)\2/' "$LUA"
fi

echo "wal-set: done."
