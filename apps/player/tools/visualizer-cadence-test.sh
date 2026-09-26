#!/usr/bin/env bash
# Private KWin framebuffer and session bus; never connects to the live seat.
set -euo pipefail
if [[ ${1:-} != --private-bus ]]; then
    exec dbus-run-session -- bash "$0" --private-bus
fi
repo=$(cd "$(dirname "$0")/../../.." && pwd)
scratch=$(mktemp -d /tmp/player-cadence.XXXXXX)
trap 'kill "${compositor:-}" 2>/dev/null || true; wait "${compositor:-}" 2>/dev/null || true; rm -rf "$scratch"' EXIT
unset DISPLAY WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE SESSION_MANAGER
export XDG_RUNTIME_DIR="$scratch/runtime" XDG_CONFIG_HOME="$scratch/config" XDG_CACHE_HOME="$scratch/cache" XDG_STATE_HOME="$scratch/state" XDG_DATA_HOME="$scratch/data"
mkdir -m700 -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME" "$XDG_DATA_HOME"
export QT_QPA_PLATFORM=offscreen QT_QUICK_CONTROLS_STYLE=Basic QT_STYLE_OVERRIDE=oxygen
unset QT_QPA_PLATFORMTHEME
export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$scratch/no-system" PIPEWIRE_REMOTE=/dev/null PULSE_SERVER=unix:/dev/null
source "$repo/tools/lib/session-guard.sh"
sg_require_offscreen
kwin_wayland --virtual --no-lockscreen --no-global-shortcuts --no-kactivities --width 1920 --height 1080 --socket cadence-test > "$scratch/kwin.log" 2>&1 &
compositor=$!
for i in {1..100}; do [[ -S "$XDG_RUNTIME_DIR/cadence-test" ]] && break; sleep .05; done
[[ -S "$XDG_RUNTIME_DIR/cadence-test" ]] || { cat "$scratch/kwin.log"; exit 1; }
export WAYLAND_DISPLAY="$XDG_RUNTIME_DIR/cadence-test" QT_QPA_PLATFORM=wayland
sg_require_nested || exit $?
DBUS_SESSION_BUS_ADDRESS="unix:path=$scratch/no-bus" NO_AT_BRIDGE=1 player-qtenv python3 "$repo/apps/player/tools/visualizer-cadence-test.py"
