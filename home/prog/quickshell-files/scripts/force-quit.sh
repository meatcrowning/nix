#!/bin/sh
# Force-quit the process behind a taskbar window (SIGKILL).
#
# The panel's taskbar is driven by the Wayland foreign-toplevel list, which
# carries no pid — only appId/class + title. So resolve the pid from Hyprland:
# match a client by class+title, and if that's ambiguous fall back to a class
# match only when it's unique. Then SIGKILL the whole process (this is a force
# quit, not a graceful close — that's Toplevel.close() on the QML side).
#
# Args: $1 = class/appId, $2 = window title.
app="$1"
title="$2"
[ -n "$app" ] || exit 0

pid=$(hyprctl clients -j | jq -r --arg c "$app" --arg t "$title" '
  ([.[] | select(.class == $c and .title == $t)][0].pid)
  // ([.[] | select(.class == $c)] | if length == 1 then .[0].pid else null end)
  // empty')

[ -n "$pid" ] && [ "$pid" -gt 0 ] && exec kill -9 "$pid"
