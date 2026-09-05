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
#   2. PUBLISHES the wallpaper for the Quickshell panel to draw, by writing two
#      tiny state files — $CACHE/current (absolute path) and $CACHE/current.mode
#      (the single word `tile` or `scale`). Nothing else here paints anything.
#   3. regenerates the Quickshell palette (panel hot-reloads)
#   4. regenerates the kitty colours (reloaded via SIGUSR1)
#   5. sets Hyprland's focused-window border (live + persisted)
#
# WHY NO hyprpaper ANY MORE (removed 2026-07-26): Quickshell draws the wallpaper
# itself now, on a Background-layer window, and this script's whole job on the
# wallpaper side shrank to "write two state files". Two things forced the move:
#
#   * hyprpaper re-renders its background layer surface on every set, and that
#     re-render reads on screen as a wallpaper FLASH. A large slice of this file
#     used to exist purely to dodge it — an "already applied" marker keyed to the
#     hyprpaper PID, a retry loop around an IPC that answers "invalid request"
#     under a burst, and a rule never to re-set an image that was already up. The
#     panel can simply CROSS-FADE between two images instead, so the flash (and
#     all of that machinery) is gone rather than worked around.
#   * hyprpaper has no notion of an OFFSET: it centres the image on the whole
#     monitor, so in dock mode (the panel grown to a third of the screen) the
#     subject of the art sat behind the panel. The workaround was an ImageMagick
#     compose per (image, monitor size, panel edge, width) — a fresh full-screen
#     PNG on every dock-width step, each one another hyprpaper set, i.e. another
#     flash. The panel knows the region it doesn't cover and can just offset the
#     art into it, per frame, for free. That compose pipeline is gone too.
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

# ---- 2b. publish it for the panel to draw ------------------------------------
# These two files ARE the wallpaper apply. The panel watches them and does the
# painting: $CACHE/current (written in step 1) is the absolute path of the image,
# $CACHE/current.mode is the single word `tile` or `scale` — the decision
# wal-prepare.sh already made from the image's dimensions, which the panel has no
# way to re-derive cheaply and must not second-guess (both sides disagreeing on
# tile-vs-scale is exactly how a wallpaper ends up drawn twice differently).
#
# Written UNCONDITIONALLY on every run, including when the value is unchanged: a
# no-op rewrite costs nothing now that nobody re-renders a layer surface for it,
# and it means the pair can never be left stale by an early exit somewhere.
#
# Written IN PLACE (truncate + write, same inode), never tmp+mv: Quickshell
# watches a file by inode, so an atomic rename hands it a new inode while it
# keeps watching the old, now-unlinked one — the same trap documented for
# Theme.qml in step 7. One tiny write, so the truncated window is not observable
# in practice. No trailing newline, matching $STATE's own convention.
printf '%s' "$MODE" > "$STATE.mode"
# $CACHE/current.blur is the pre-blurred backdrop wal-prepare.sh cached for this
# image (see there for why it is a real Gaussian and not a runtime effect). The
# panel falls back to blurring the source itself if this is missing or stale, so
# it is safe to publish the path unconditionally.
printf '%s' "$CACHE/blur-$KEY.png" > "$STATE.blur"

if [ "$WALLPAPER_ONLY" = 1 ]; then
    # Preview path (the picker, arrow-keying through images): writing $STATE and
    # $STATE.mode above IS the whole wallpaper apply now, so there is nothing
    # left to do but get out before the theme/palette work — which is the slow
    # part AND the part that rewrites Theme.qml and would hot-reload the panel,
    # closing the picker out from under the user mid-flip.
    echo "wal-set: wallpaper-only ($MODE), skipping theme apply"
    exit 0
fi

# ---- 3. load the palette (already extracted by wal-prepare.sh above) ---------
eval "$(cat "$THEMES/$KEY.env")"
echo "wal-set: source = ${IW}x${IH}, mode = $MODE, accent = #$ACCENT"

# Publish the quantised cluster list (dominant first, comma-separated bare hex)
# for the Settings swatch row (SetSwatches.qml) — the display the user picks
# palette colours from. In place, same inode rule as $STATE.mode above. An env
# cached before CLUSTERS existed publishes empty; the next re-extract fills it.
printf '%s' "${CLUSTERS:-}" > "$STATE.clusters"

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

# ---- 4b. ly login greeter colours (read at his next login) ------------------
# /etc/ly/config.ini is a symlink to /var/lib/ly/config.ini, seeded from the
# NixOS module by sys/dsk/plasma.nix's activation; the six colour keys there
# are OURS to rewrite (the activation carries them forward across rebuilds),
# the rest is root-owned module state. No-op where the file does not exist
# (book). Must stay before step 7 like everything else — a quick local file
# write, but the Theme.qml reload tears the script down mid-run.
"$SCRIPTS/ly-theme.sh" "$ACCENT" "$DIM" "$CRIT"

# ---- 5. Hyprland focused-window border + hyprvtb titlebars (live + persisted)
# `hyprctl keyword` doesn't exist on the lua-config parser ("use eval"), so
# both the border and the hyprvtb titlebar-plugin colours go through one
# `hyprctl eval hl.config(...)` call for the live update, and sed against the
# palette-tagged lines in hyprland.lua for persistence across restarts.
#
# shadow_alpha is a USER setting (Settings > Appearance > drop shadow), not a
# palette colour — it lives in settings.json and the panel applies it live. But
# this hl.config re-asserts the plugin.hyprvtb block, which reverted shadow_alpha
# to the plugin default (0.6) on every theme/wallpaper change: the colours
# survived because they are re-asserted here (and persisted in hyprland.lua) and
# the shadow was not. So read the user's value and re-assert it in the SAME call,
# so a theme switch RETAINS the chosen opacity instead of resetting it.
SETTINGS="$CONFIG/quickshell/settings.json"
SHADOW_ALPHA=0.6
TITLE_ROTATED=false
BORDER_W=2
ROUNDING=0
if [ -f "$SETTINGS" ]; then
    v="$(sed -n 's/.*"shadowAlpha"[[:space:]]*:[[:space:]]*\([0-9.]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] && SHADOW_ALPHA="$v"
    # titleOrientation is the other USER key riding this block (same reasoning
    # as shadow_alpha above): re-asserted live and persisted in hyprland.lua so
    # a `hyprctl reload` keeps the sideways title instead of reverting it.
    grep -q '"titleOrientation"[[:space:]]*:[[:space:]]*"horizontal"' "$SETTINGS" && TITLE_ROTATED=true
    # ...and the GLOBAL frame (Settings > appearance > theme): border width and
    # corner rounding for every window on the desktop. Same persistence story.
    v="$(sed -n 's/.*"windowBorderWidth"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] && BORDER_W="$v"
    v="$(sed -n 's/.*"windowRounding"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] && ROUNDING="$v"
    # dimUnfocused also decides the unfocused-window BORDER (the third surface
    # the dim moves — see apply-window-frame.sh / docs/DESIGN.md §3.1.1). ON: the
    # static grey. OFF: match the active accent so nothing distinguishes an
    # unfocused window. Recomputed here because a theme change moves the accent,
    # and the OFF border must follow it.
    grep -q '"dimUnfocused"[[:space:]]*:[[:space:]]*false' "$SETTINGS" && DIM_UNFOCUSED=false
fi
if [ "${DIM_UNFOCUSED:-true}" = false ]; then IB="${ACCENT}ee"; else IB="595959aa"; fi
hyprctl eval 'hl.config({
    general = { border_size = '"${BORDER_W}"', col = { active_border = "rgba('"${ACCENT}"'ee)", inactive_border = "rgba('"${IB}"')" } },
    decoration = { rounding = '"${ROUNDING}"' },
    plugin = { hyprvtb = {
        ["bg_color"]          = "rgba('"${BG}"'ff)",
        ["col.text"]          = "rgba('"${TEXTDIM}"'ff)",
        ["col.button_border"] = "rgba('"${BORDER}"'ff)",
        ["col.accent"]        = "rgba('"${ACCENT}"'ff)",
        ["col.bg_alt"]        = "rgba('"${BGALT}"'ff)",
        ["col.crit"]          = "rgba('"${CRIT}"'ff)",
        ["col.warn"]          = "rgba('"${WARN}"'ff)",
        ["shadow_alpha"]      = '"${SHADOW_ALPHA}"',
        ["title_rotated"]     = '"${TITLE_ROTATED}"',
    } },
})' >/dev/null 2>&1
LUA="$CONFIG/hypr/hyprland.lua"
if [ -f "$LUA" ]; then
    sed -i -E 's/(\<active_border[[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${ACCENT}"'ee)\2/' "$LUA"
    sed -i -E 's/(^[[:space:]]*inactive_border[[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${IB}"')\2/' "$LUA"
    sed -i -E 's/(\["bg_color"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${BG}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.text"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${TEXTDIM}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.button_border"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${BORDER}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.accent"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${ACCENT}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.bg_alt"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${BGALT}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.crit"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${CRIT}"'ff)\2/' "$LUA"
    sed -i -E 's/(\["col\.warn"\][[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"${WARN}"'ff)\2/' "$LUA"
    # Persist shadow_alpha too — the live hl.config above reverts on the next
    # `hyprctl reload` (which re-reads this file), so the colours survived and
    # the shadow did not. Rewriting the seed line here makes it survive a
    # reload and a restart, exactly as the colour lines do.
    sed -i -E 's/(\["shadow_alpha"\][[:space:]]*=[[:space:]]*)[0-9.]+/\1'"${SHADOW_ALPHA}"'/' "$LUA"
    sed -i -E 's/(\["title_rotated"\][[:space:]]*=[[:space:]]*)(true|false)/\1'"${TITLE_ROTATED}"'/' "$LUA"
    # The global frame. Anchored at line start so the commented-out examples
    # further down cannot match; `rounding[[:space:]]` cannot reach
    # rounding_power.
    sed -i -E 's/^([[:space:]]*border_size[[:space:]]*=[[:space:]]*)[0-9]+/\1'"${BORDER_W}"'/' "$LUA"
    sed -i -E 's/^([[:space:]]*rounding[[:space:]]+=[[:space:]]*)[0-9]+/\1'"${ROUNDING}"'/' "$LUA"
fi

# ---- 6. KDE / Qt apps (kdeglobals colours + pixel font; live-reloaded) --------
# Qt apps read their palette and fonts from ~/.config/kdeglobals: KDE apps
# (Dolphin, Kate, dialogs) always do, and every other Qt app does too now that
# hyprland.lua sets QT_QPA_PLATFORMTHEME=kde. Rewrite the colour groups from the
# wallpaper palette and pin the same pixel font the panel and kitty use, then
# poke running apps to reload. kwriteconfig6 edits keys surgically, so groups
# owned elsewhere (KFileDialog Settings from plasma-manager, ColorEffects, etc.)
# are left untouched.
#
# NOT IN A PLASMA SESSION. There kdeglobals is not this desktop's channel into
# Qt apps, it IS the desktop: the KDE global theme picked in System Settings,
# which the vendored apps follow too since 2026-08-18 (apps/pylib/kdetheme.py).
# Rewriting it from the wallpaper would silently replace his colour scheme,
# widget style and system font the first time a theme was applied — and
# wal-set.sh is reachable from a Plasma session (apps/pylib/systheme.py, the
# player's "create systheme"). One gate covers the fonts too:
# apply-pixel-font.sh is called from inside this block.
#
# That gate went in on 2026-08-18 and took the wallpaper OUT of the window
# colours in a Plasma session with it — the panel followed the wallpaper (via
# Plasma's own accentColorFromWallpaper) and the windows did not. The Plasma
# branch below is the answer: not a kdeglobals rewrite, a re-mint of the colour
# SCHEME FILE he picked, which plasma-apply-colorscheme then pushes into
# kdeglobals through KDE's own route — leaving widget style, icons and fonts
# alone.
KG="$CONFIG/kdeglobals"
PLASMA_SESSION=0
case ":$(printf '%s' "${XDG_CURRENT_DESKTOP:-}" | tr '[:lower:]' '[:upper:]'):" in
    *:KDE:*) PLASMA_SESSION=1 ;;
esac
if [ "$PLASMA_SESSION" = 1 ]; then
    # The KDE global theme stays his — but the COLOUR SCHEME follows the
    # wallpaper, by re-minting the scheme file he already picked with its hue
    # moved onto the accent and re-applying it under the same name. Oxygen's
    # shape survives; only its family of blues becomes the wallpaper's colour.
    # See plasma-scheme.py for the maths and for why it refuses to apply when
    # the live scheme is not the one it templates.
    echo "wal-set: Plasma session — KDE theme untouched, re-minting its colour scheme"
    "$SCRIPTS/plasma-scheme.py" --accent "$ACCENT"

    # ---- AeroThemePlasma glass ------------------------------------------
    # In the ATP session the titlebar and panel colour is NOT art: smod's frame
    # tiles are neutral greys (#212121 / #373737) and the colour arrives from
    # the aeroglassblur kwin effect, which colorizes the DECORATION region as
    # well as the window behind it. Its input is four ints in kwinrc — Win7's
    # "Window Color" panel, hue/saturation/brightness/intensity — so the
    # wallpaper accent reaches the whole chrome with a config write and no
    # asset work at all.
    #
    # Gated on the EFFECT being enabled, not on a session name: ATP's session
    # sets DesktopNames=KDE like every other Plasma session, so nothing in the
    # environment tells them apart, while `aeroglassblurEnabled` is true only
    # where ATP's own setup wizard has run.
    #
    # BlurEffect::reconfigure() reads the `kwinaero` shared-memory segment only
    # on its FIRST config and kwinrc on every one after, so kwriteconfig6 plus
    # one reconfigureEffect is the whole apply — there is no need to reproduce
    # the KCM's shared-memory writer.
    if command -v kwriteconfig6 >/dev/null 2>&1 && command -v kreadconfig6 >/dev/null 2>&1 \
       && [ "$(kreadconfig6 --file kwinrc --group Plugins --key aeroglassblurEnabled 2>/dev/null)" = "true" ]; then
        # accent hex -> HSV in the effect's own units (H 0-359, S/V 0-100).
        r=$((16#${ACCENT:0:2})); g=$((16#${ACCENT:2:2})); b=$((16#${ACCENT:4:2}))
        amax=$r; [ "$g" -gt "$amax" ] && amax=$g; [ "$b" -gt "$amax" ] && amax=$b
        amin=$r; [ "$g" -lt "$amin" ] && amin=$g; [ "$b" -lt "$amin" ] && amin=$b
        ad=$((amax - amin))
        if   [ "$ad" -eq 0 ];        then AH=0
        elif [ "$amax" -eq "$r" ];   then AH=$(( (60 * (g - b) / ad + 360) % 360 ))
        elif [ "$amax" -eq "$g" ];   then AH=$(( (60 * (b - r) / ad + 120) % 360 ))
        else                              AH=$(( (60 * (r - g) / ad + 240) % 360 ))
        fi
        AS=0; [ "$amax" -gt 0 ] && AS=$((100 * ad / amax))
        AV=$((100 * amax / 255))
        # A dark accent would make near-black glass, and Aero draws its titlebar
        # caption in BLACK — so floor the value. Hue and saturation pass through
        # untouched, which is what keeps a grey wallpaper's glass grey.
        [ "$AV" -lt 55 ] && AV=55
        # Intensity is how much of that colour is mixed in — his taste, not the
        # wallpaper's. Keep whatever the Window Color panel was left on.
        AI="$(kreadconfig6 --file kwinrc --group Effect-aeroglassblur --key AeroIntensity 2>/dev/null)"
        case "$AI" in ""|*[!0-9]*) AI=50 ;; esac
        for kv in "AeroHue $AH" "AeroSaturation $AS" "AeroBrightness $AV" "AeroIntensity $AI"; do
            kwriteconfig6 --file kwinrc --group Effect-aeroglassblur \
                --key "${kv%% *}" -- "${kv#* }"
        done
        dbus-send --session --dest=org.kde.KWin --type=method_call \
            /Effects org.kde.kwin.Effects.reconfigureEffect \
            string:aeroglassblur >/dev/null 2>&1 || true
        echo "wal-set: aero glass -> hue $AH sat $AS val $AV intensity $AI"
    fi
elif command -v kwriteconfig6 >/dev/null 2>&1; then
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
    # The font roles (and kitty + the hyprvtb titlebar) now follow the Settings
    # "pixel font" pick — apply-pixel-font.sh reads fontFamily/fontSize from
    # settings.json and writes them here, so whoever runs on login (wal-set.sh)
    # and whenever the pick changes (the panel) share one writer. kwriteconfig6
    # below only handles the colour groups; the font delegate lives out of the
    # wallpaper derive because it is a Settings value, not a wallpaper value.
    "$CONFIG/scripts/apply-pixel-font.sh" >/dev/null 2>&1 || true

    # Reload palette (0), fonts (1), style (2) and icons (4) in running KDE/Qt
    # apps without a relogin. Harmless if there's no session bus or no listeners.
    # (apply-pixel-font.sh already sent the fonts(1) notify; this catches the
    # colour/style/icon rates too.)
    if command -v dbus-send >/dev/null 2>&1; then
        for change in 0 2 4; do
            dbus-send --session --type=signal /KGlobalSettings org.kde.KGlobalSettings.notifyChange int32 "$change" int32 0 >/dev/null 2>&1 || true
        done
    fi
fi

# Wine and Ableton read their colours only at process startup. Mint their next
# startup theme after kdeglobals, because Ableton uses the active KDE scheme's
# normal white foreground. There is deliberately no attempt to repaint an
# already-running Windows process.
if command -v ableton-theme >/dev/null 2>&1 \
   && [ -d "$HOME/.wine/drive_c/ProgramData/Ableton/Live 11 Suite" ]; then
    ableton-theme || echo "wal-set: Ableton theme update failed" >&2
fi

# ---- 6b. Cursor: outline -> accent, core -> bg -------------------------------
# Regenerate ~/.icons/GoogleDot-<accent><bg> from the base theme, recoloured to
# this wallpaper's accent (outline) and bg (core), and setcursor it live (see
# cursor-recolor.sh — the core follows bg so the cursor matches the theme in
# light mode too, not just the dark-mode near-black). Cheap (~9ms)
# when the accent is unchanged; ~2.9s when it actually has to re-tint — and that
# re-tint is pure ImageMagick/xcursorgen work the rest of the theme apply does
# NOT depend on. It used to run inline right here, so a wallpaper switch to a new
# accent stalled the whole desktop recolor (panel/kitty/borders) ~3s waiting on
# the cursor. Now it's fired DETACHED (setsid → its own session), so:
#   * it can't block step 7 (the Quickshell palette write) — the panel, kitty and
#     borders land in ~0.2s and the cursor catches up a couple seconds later; and
#   * it survives the step-7 hot-reload that tears this script down mid-run
#     (setsid puts it outside this script's process group, so the reload's
#     teardown can't kill it — which is why it no longer has to run *before*
#     step 7). cursor-recolor.sh flocks itself, so overlapping fires serialise
#     and still converge on the last accent.
setsid "$SCRIPTS/cursor-recolor.sh" "$ACCENT" "$BG" "${XCURSOR_SIZE:-22}" \
    >>"$CACHE/wallpaper-picker.log" 2>&1 </dev/null &

# ---- 6c. RGB hardware: DRAM sticks + motherboard headers on the accent -------
# rgb-set.py pushes ACCENT to every controller via the system openrgb.service
# SDK server (a no-op if that's down, and a no-op if `rgbFollowTheme` is off —
# it reads that key itself, since this script has no json reader on its pinned
# PATH). Detached for the same reasons as the
# cursor: the ENE DRAM SMBus writes aren't instant, nothing later depends on
# them, and setsid keeps it alive through the step-7 Quickshell reload.
setsid "$SCRIPTS/rgb-set.py" "$ACCENT" \
    >>"$CACHE/wallpaper-picker.log" 2>&1 </dev/null &

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
