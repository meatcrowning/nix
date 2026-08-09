#!/usr/bin/env bash
# apply-window-frame.sh — push the Settings "border width" / "corner rounding"
# pick (settings.json windowBorderWidth / windowRounding) at the compositor AND
# PERSIST it into the live hyprland.lua.
#
# The panel already sets both live over `hyprctl eval hl.config(...)`
# (SettingsApply.applyFrame). That is a RUNTIME OVERRIDE and Hyprland drops it
# on any config reload — and a reload happens for reasons that have nothing to
# do with the frame: apply-pixel-font.sh seds the font keys into hyprland.lua,
# which Hyprland AUTO-RELOADS, so changing the pixel font threw the corner
# radius (and the border width) back to the values still written in that file.
# Fixing the corner-rounding slider by nudging it off its value and back is what
# that looked like from the outside. Same story as shadow_alpha / title_rotated /
# the titlebar font, all of which are persisted for this reason.
#
# wal-set.sh writes the same two lines on every theme apply; this is the same
# write, on the change itself, so the file is never stale in between. Run:
#   * live, debounced, from the panel's SettingsApply.qml when either value
#     changes;
#   * by hand, to level the file with settings.json.
#
# The seds are GUARDED: hyprland.lua is autoreloaded on write, so rewriting an
# already-correct line would fire a needless reload of the whole config.
set -u

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
SETTINGS="$CONFIG/quickshell/settings.json"
LUA="$CONFIG/hypr/hyprland.lua"

# Defaults mirror SettingsStore.qml. A pick we cannot read is a pick we leave
# alone (docs/DESIGN.md §10.2) — pushing a default here would reset the frame on
# a read that lands inside the panel's debounced settings.json write.
BORDER_W=2
ROUNDING=0
if [ -f "$SETTINGS" ]; then
    v="$(sed -n 's/.*"windowBorderWidth"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] || exit 0
    BORDER_W="$v"
    v="$(sed -n 's/.*"windowRounding"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] || exit 0
    ROUNDING="$v"
fi

hyprctl eval "hl.config({ general = { border_size = ${BORDER_W} }, decoration = { rounding = ${ROUNDING} } })" >/dev/null 2>&1 || true

if [ -f "$LUA" ]; then
    # Anchored at line start so the commented-out examples further down cannot
    # match; `rounding[[:space:]]+` cannot reach rounding_power.
    lua_num() { # $1 = ERE for the assignment prefix, $2 = value
        grep -qE "^($1)$2([^0-9]|\$)" "$LUA" && return 0
        sed -i -E "s/^($1)[0-9]+/\1$2/" "$LUA"
    }
    lua_num '[[:space:]]*border_size[[:space:]]*=[[:space:]]*' "$BORDER_W"
    lua_num '[[:space:]]*rounding[[:space:]]+=[[:space:]]*' "$ROUNDING"
fi

echo "apply-window-frame: border=${BORDER_W}px rounding=${ROUNDING}px"
