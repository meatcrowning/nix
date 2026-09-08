#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
unset DISPLAY WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE DBUS_SESSION_BUS_ADDRESS
export QT_QPA_PLATFORM=offscreen
source ../../tools/lib/session-guard.sh
sg_require_offscreen
exec npm test
