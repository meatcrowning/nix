#!/usr/bin/env bash
# apply-window-frame.sh — push the Settings frame + hyprvtb runtime picks
# (windowBorderWidth / windowRounding, plus titlebarEdge, dimUnfocused, compact) at
# the compositor AND PERSIST them into the live hyprland.lua.
#
# The panel already sets all of these live over `hyprctl eval hl.config(...)`
# (SettingsApply.applyFrame / applyVtb). That is a RUNTIME OVERRIDE and Hyprland
# drops it on any config reload — and a reload happens for reasons that have
# nothing to do with the setting: apply-pixel-font.sh seds the font keys into
# hyprland.lua, which Hyprland AUTO-RELOADS, so changing the pixel font threw the
# corner radius (and the border width) back to the values still written in that
# file. Fixing the corner-rounding slider by nudging it off its value and back is
# what that looked like from the outside. The titlebar anchor edge and the
# unfocus dim had the identical bug: the side snapped back to "right" and the dim
# to default-true on every theme change (a theme apply reloads the config).
# Same story as shadow_alpha / title_rotated / the titlebar font, all persisted
# for this reason.
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
TITLEBAR_EDGE=right
DIM=true
COMPACT=false
if [ -f "$SETTINGS" ]; then
    v="$(sed -n 's/.*"windowBorderWidth"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] || exit 0
    BORDER_W="$v"
    v="$(sed -n 's/.*"windowRounding"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] || exit 0
    ROUNDING="$v"
    # right | left | top | bottom — anything else is left as the default.
    v="$(sed -n 's/.*"titlebarEdge"[[:space:]]*:[[:space:]]*"\(right\|left\|top\|bottom\)".*/\1/p' "$SETTINGS" | head -n1)"
    [ -n "$v" ] && TITLEBAR_EDGE="$v"
    # dimUnfocused drives BOTH the plugin titlebar scrim (plugin:hyprvtb:
    # dim_unfocused) and Hyprland's native body dim (decoration:dim_inactive).
    grep -q '"dimUnfocused"[[:space:]]*:[[:space:]]*false' "$SETTINGS" && DIM=false
    # compact collapses the two-column bar into one (plugin:hyprvtb:compact).
    grep -q '"compact"[[:space:]]*:[[:space:]]*true' "$SETTINGS" && COMPACT=true
fi

# inactive_border is the THIRD surface the unfocus dim moves (titlebar + body +
# border, all as one — his call, docs/DESIGN.md §3.1.1): dim ON gives an
# unfocused window the static grey border; dim OFF distinguishes nothing, so the
# border matches the active accent. wal-set.sh owns the accent, so read the
# CURRENT active_border out of hyprland.lua rather than re-derive the palette.
IB_HEX=595959aa
if [ "$DIM" = false ] && [ -f "$LUA" ]; then
    ab="$(sed -n 's/^[[:space:]]*active_border[[:space:]]*=[[:space:]]*"rgba(\([0-9a-fA-F]*\))".*/\1/p' "$LUA" | head -n1)"
    [ -n "$ab" ] && IB_HEX="$ab"
fi

hyprctl eval "hl.config({ general = { border_size = ${BORDER_W}, col = { inactive_border = \"rgba(${IB_HEX})\" } }, decoration = { rounding = ${ROUNDING}, dim_inactive = ${DIM} }, plugin = { hyprvtb = { [\"titlebar_edge\"] = \"${TITLEBAR_EDGE}\", [\"dim_unfocused\"] = ${DIM}, [\"compact\"] = ${COMPACT} } } })" >/dev/null 2>&1 || true

if [ -f "$LUA" ]; then
    # Anchored at line start so the commented-out examples further down cannot
    # match; `rounding[[:space:]]+` cannot reach rounding_power.
    lua_num() { # $1 = ERE for the assignment prefix, $2 = value
        grep -qE "^($1)$2([^0-9]|\$)" "$LUA" && return 0
        sed -i -E "s/^($1)[0-9]+/\1$2/" "$LUA"
    }
    lua_num '[[:space:]]*border_size[[:space:]]*=[[:space:]]*' "$BORDER_W"
    lua_num '[[:space:]]*rounding[[:space:]]+=[[:space:]]*' "$ROUNDING"
    # The two hyprvtb block keys are `["key"] = value`; the native dim is a
    # bare `dim_inactive = <bool>` at line start (the commented dim examples
    # further down are prefixed, so the ^ anchor cannot reach them). All guarded
    # so an already-correct value fires no needless autoreload.
    grep -qE '^\s*\["titlebar_edge"\]\s*=\s*"'"$TITLEBAR_EDGE"'"' "$LUA" || \
        sed -i -E 's/(\["titlebar_edge"\][[:space:]]*=[[:space:]]*")[^"]*"/\1'"$TITLEBAR_EDGE"'"/' "$LUA"
    grep -qE '^\s*\["dim_unfocused"\]\s*=\s*'"$DIM"'\b' "$LUA" || \
        sed -i -E 's/(\["dim_unfocused"\][[:space:]]*=[[:space:]]*)(true|false)/\1'"$DIM"'/' "$LUA"
    grep -qE '^\s*\["compact"\]\s*=\s*'"$COMPACT"'\b' "$LUA" || \
        sed -i -E 's/(\["compact"\][[:space:]]*=[[:space:]]*)(true|false)/\1'"$COMPACT"'/' "$LUA"
    grep -qE '^[[:space:]]*dim_inactive[[:space:]]*=[[:space:]]*'"$DIM"'\b' "$LUA" || \
        sed -i -E 's/^([[:space:]]*dim_inactive[[:space:]]*=[[:space:]]*)(true|false)/\1'"$DIM"'/' "$LUA"
    # inactive_border floor — a bare `inactive_border = "rgba(...)"` at line start
    # (the commented col examples are prefixed, so ^ cannot reach them). Guarded.
    grep -qE '^[[:space:]]*inactive_border[[:space:]]*=[[:space:]]*"rgba\('"$IB_HEX"'\)"' "$LUA" || \
        sed -i -E 's/(^[[:space:]]*inactive_border[[:space:]]*=[[:space:]]*")rgba\([0-9a-fA-F]+\)(")/\1rgba('"$IB_HEX"')\2/' "$LUA"
fi

echo "apply-window-frame: border=${BORDER_W}px rounding=${ROUNDING}px titlebar=${TITLEBAR_EDGE} dim=${DIM} compact=${COMPACT} inactive_border=rgba(${IB_HEX})"
