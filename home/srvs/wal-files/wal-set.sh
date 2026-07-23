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
# burst, so we don't gate on a probe — we issue the real commands and gate on
# the `wallpaper` set's exit code (a successful set prints nothing). NOTE:
# `hyprpaper unload`/`listloaded` return "invalid hyprpaper request"
# unconditionally on this hyprpaper build (0.8.4) regardless of syntax (tested:
# "all", a specific path, comma-separated) — so they're deliberately not called
# here; retrying them would just burn the attempt budget for nothing.
#
# IMPORTANT: `preload` of an ALREADY-loaded image ALSO returns "invalid request"
# (exit 1) on this build. Preloading is best-effort (one shot, failure ignored)
# and only the `wallpaper` set is retried — otherwise every re-visit of an
# already-loaded image (i.e. almost every picker preview) would sleep the full
# 5×0.1s preload budget for nothing, which is exactly what made previews lag
# ~0.5s. The set is what actually needs to land, and it returns 0 once the image
# is loaded, so on a truly-fresh image the retry re-attempts preload+set until
# the set sticks.
printf '%s' "$PRELOADS" | while read -r p; do
    [ -n "$p" ] && hyprctl hyprpaper preload "$p" >/dev/null 2>&1
done
printf '%s' "$WALLLINES" | while read -r l; do
    [ -z "$l" ] && continue
    p="${l#*,}"
    for _ in 1 2 3 4 5; do
        hyprctl hyprpaper wallpaper "$l" >/dev/null 2>&1 && break
        hyprctl hyprpaper preload "$p" >/dev/null 2>&1   # fresh image: get it loaded, then retry the set
        sleep 0.1
    done
done

if [ "$WALLPAPER_ONLY" = 1 ]; then
    echo "wal-set: wallpaper-only, skipping theme apply"
    exit 0
fi

# ---- 3. load the palette (already extracted by wal-prepare.sh above) ---------
eval "$(cat "$THEMES/$KEY.env")"
echo "wal-set: source = ${IW}x${IH}, mode = $MODE, accent = #$ACCENT"

# NOTE: the Quickshell palette write (Theme.qml) is deliberately the LAST apply
# step (step 7 below), NOT here. Writing Theme.qml triggers a Quickshell
# hot-reload that tears down the entire QML tree — including WallpaperPicker.qml
# and the Process running this very script when the apply came from the picker —
# which kills this script wherever it's up to. Everything that must survive the
# reload (kitty, borders, kdeglobals) therefore runs first; Theme.qml goes last.

# ---- 4. kitty colours (reloaded via SIGUSR1) ---------------------------------
cat > "$CONFIG/kitty/theme.conf" <<KITTYEOF
# GENERATED by ~/.config/scripts/wal-set.sh from the current wallpaper.
# Normal text (foreground + the color7/color15 "white" slots) is ACCENT, not
# TEXT, so kitty's body text matches the focused window's titlebar — hyprvtb
# paints a focused title in col.accent (see vtbDeco.cpp: FOCUSED ? accentColor).
foreground            #$ACCENT
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
color7  #$ACCENT
color15 #$ACCENT
KITTYEOF

# make sure kitty.conf pulls in the generated file (once)
if ! grep -q '^include theme.conf' "$CONFIG/kitty/kitty.conf" 2>/dev/null; then
    printf '\ninclude theme.conf\n' >> "$CONFIG/kitty/kitty.conf"
fi
# live-reload every running kitty
pkill -USR1 -x kitty >/dev/null 2>&1

# ---- 5. Hyprland focused-window border + hyprvtb titlebars (live + persisted)
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

# ---- 6. KDE / Qt apps (kdeglobals colours + pixel font; live-reloaded) --------
# Qt apps read their palette and fonts from ~/.config/kdeglobals: KDE apps
# (Dolphin, Kate, dialogs) always do, and every other Qt app does too now that
# hyprland.lua sets QT_QPA_PLATFORMTHEME=kde. Rewrite the colour groups from the
# wallpaper palette and pin the same pixel font the panel and kitty use, then
# poke running apps to reload. kwriteconfig6 edits keys surgically, so groups
# owned elsewhere (KFileDialog Settings from plasma-manager, ColorEffects, etc.)
# are left untouched.
KG="$CONFIG/kdeglobals"
if command -v kwriteconfig6 >/dev/null 2>&1; then
    hx() { printf '%d,%d,%d' "0x${1:0:2}" "0x${1:2:2}" "0x${1:4:2}"; }   # "rrggbb" -> "R,G,B"
    kw() { kwriteconfig6 --file "$KG" "$@"; }
    # group, background, foreground — the remaining roles are shared across groups.
    kdecolor() {
        local g="$1" bg="$2" fg="$3"
        kw --group "$g" --key BackgroundNormal    "$(hx "$bg")"
        kw --group "$g" --key BackgroundAlternate "$(hx "$BGALT")"
        kw --group "$g" --key ForegroundNormal    "$(hx "$fg")"
        kw --group "$g" --key ForegroundInactive  "$(hx "$TEXTDIM")"
        kw --group "$g" --key ForegroundActive    "$(hx "$ACCENT")"
        kw --group "$g" --key ForegroundLink      "$(hx "$ACCENT")"
        kw --group "$g" --key ForegroundVisited   "$(hx "$TEXTDIM")"
        kw --group "$g" --key ForegroundNegative  "$(hx "$CRIT")"
        kw --group "$g" --key ForegroundNeutral   "$(hx "$WARN")"
        kw --group "$g" --key ForegroundPositive  "$(hx "$OK")"
        kw --group "$g" --key DecorationFocus     "$(hx "$ACCENT")"
        kw --group "$g" --key DecorationHover     "$(hx "$ACCENT")"
    }
    # Every background is pure black (BG) to match the panel/kitty/rest of the
    # system — the Breeze style below draws flat, so nothing gradients away from
    # it. Only selections (accent) and the near-black alternate-row stripe
    # (BackgroundAlternate = BGALT, set inside kdecolor) break the black.
    #
    # Normal foreground text is ACCENT, not TEXT, so a KDE/Qt app's body text
    # matches the red of the focused window's titlebar (hyprvtb draws the focused
    # title in col.accent). Same choice as kitty's foreground above — the whole
    # focused surface reads as one accent colour.
    kdecolor "Colors:Window"        "$BG"     "$ACCENT"
    kdecolor "Colors:View"          "$BG"     "$ACCENT"
    kdecolor "Colors:Button"        "$BG"     "$ACCENT"
    kdecolor "Colors:Selection"     "$ACCENT" "$BG"
    kdecolor "Colors:Tooltip"       "$BG"     "$ACCENT"
    kdecolor "Colors:Complementary" "$BG"     "$ACCENT"
    kdecolor "Colors:Header"        "$BG"     "$ACCENT"
    # Window-manager (titlebar) colours — used by KDE apps' own CSDs. Active title
    # text is ACCENT to match hyprvtb's focused titlebar (and the body text above).
    kw --group WM --key activeBackground   "$(hx "$BG")"
    kw --group WM --key activeForeground   "$(hx "$ACCENT")"
    kw --group WM --key inactiveBackground "$(hx "$BG")"
    kw --group WM --key inactiveForeground "$(hx "$TEXTDIM")"

    # Flat widget style (Breeze, not Oxygen's gradients/frames) + a dark icon
    # set whose light glyphs read on the black background. Static, but pinned
    # here so they always win over stale Plasma settings.
    kw --group KDE   --key widgetStyle "Breeze"
    kw --group Icons --key Theme        "breeze-dark"

    # Same pixel font AND size as kitty (font_size 11 in kitty.conf), everywhere.
    # Static (not wallpaper-derived), but re-pinned here so it lands on first
    # login and overrides any stale Plasma-set font.
    FSPEC="More Perfect DOS VGA,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"
    for k in font menuFont toolBarFont smallestReadableFont fixed; do
        kw --group General --key "$k" "$FSPEC"
    done
    kw --group WM --key activeFont "$FSPEC"

    # Reload palette (0), fonts (1), style (2) and icons (4) in running KDE/Qt
    # apps without a relogin. Harmless if there's no session bus or no listeners.
    if command -v dbus-send >/dev/null 2>&1; then
        for change in 0 1 2 4; do
            dbus-send --session --type=signal /KGlobalSettings org.kde.KGlobalSettings.notifyChange int32 "$change" int32 0 >/dev/null 2>&1 || true
        done
    fi
fi

# ---- 6b. Cursor: tint GoogleDot-Black's white outline to the accent ----------
# Regenerate ~/.icons/GoogleDot-Accent from the base theme, recoloured to this
# wallpaper's accent, and setcursor it live (see cursor-recolor.sh). Runs before
# step 7 because that Quickshell reload can tear this script down mid-run. Cheap
# (~9ms) when the accent is unchanged; ~2.5s when it actually has to re-tint.
"$SCRIPTS/cursor-recolor.sh" "$ACCENT" "${XCURSOR_SIZE:-22}" || true

# ---- 7. Quickshell palette (spliced into Theme.qml; panel hot-reloads) -------
# MUST BE THE LAST apply step — see the note where step 4 used to be. Writing
# Theme.qml makes Quickshell hot-reload and tear down the QML tree (and, from
# the picker, this script's own Process), so nothing may follow it.
#
# It also MUST edit Theme.qml in place (truncate + rewrite the SAME inode),
# never `mv` a temp file over it: Quickshell watches each loaded QML file by
# inode; an atomic rename gives Theme.qml a new inode while qs keeps watching
# the old (now-unlinked) one, so the panel never sees the new palette.
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

echo "wal-set: done."
