#!/usr/bin/env bash
# resize-mode-notify.sh enter|leave
#
# Toasts Hyprland's i3-style resize mode (see hypr/hyprland.lua) through the
# same notify-send path every other toast uses, so it renders as an identical
# card in the same corner instead of a bespoke overlay. Critical urgency keeps
# it on screen for the whole "enter" duration instead of auto-expiring;
# "leave" closes that exact notification by id.
set -u

STATE="${XDG_RUNTIME_DIR:-/tmp}/resize-mode-notif-id"

case "${1:-}" in
enter)
    id=$(notify-send -a quickshell -u critical -p \
        "Resize mode" "arrows resize · super+arrows move · super+R exit")
    printf '%s' "$id" > "$STATE"
    ;;
leave)
    [ -f "$STATE" ] || exit 0
    id=$(cat "$STATE")
    rm -f "$STATE"
    [ -n "$id" ] && busctl --user call org.freedesktop.Notifications \
        /org/freedesktop/Notifications org.freedesktop.Notifications \
        CloseNotification u "$id" >/dev/null 2>&1
    ;;
esac
