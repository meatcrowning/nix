#!/bin/sh
# SMART summary for each drive, one line per drive:
#   device|health|temp_c|wear_pct|power_on_hours
# health: PASSED / FAILED / "" (unknown). Fields left blank when a drive
# doesn't report them (USB bridges often block SMART entirely — skipped).
# Uses the NOPASSWD `drive-smart` wrapper from sys/disks.nix (a fixed-arg
# `smartctl -a -j <device>`, so the passwordless-root grant can't run self-tests
# or feature toggles). The rule lists the resolved /nix/store path, so we invoke
# that same real path (sudo doesn't canonicalize the /run/current-system/sw/bin
# symlink, so a bare `sudo drive-smart` would miss the rule and prompt).
#
# $1 = "ssd" (default) polls flash only; "all" includes spinning disks. That is
# the Settings program's `smartSsdOnly` (Widgets > monitoring): the skip was
# unconditional here, so the toggle was drawn but described behaviour nothing
# could change. Off costs a spin-up on any parked HDD, which is why on is the
# shipped default.
ONLY="${1:-ssd}"

DRIVE_SMART=$(readlink -f "$(command -v drive-smart)" 2>/dev/null)
[ -n "$DRIVE_SMART" ] || exit 0

for d in /sys/block/*; do
    name=$(basename "$d")
    case "$name" in
        loop* | ram* | zram* | dm-*) continue ;;
    esac
    [ "$ONLY" = "all" ] || [ "$(cat "$d/queue/rotational" 2>/dev/null)" = "0" ] || continue
    dev="/dev/$name"
    j=$(sudo -n "$DRIVE_SMART" "$dev" 2>/dev/null) || continue
    [ -n "$j" ] || continue
    printf '%s|%s|%s|%s|%s\n' "$dev" \
        "$(printf '%s' "$j" | jq -r 'if .smart_status.passed == true then "PASSED" elif .smart_status.passed == false then "FAILED" else "" end')" \
        "$(printf '%s' "$j" | jq -r '.temperature.current // ""')" \
        "$(printf '%s' "$j" | jq -r '.nvme_smart_health_information_log.percentage_used // ""')" \
        "$(printf '%s' "$j" | jq -r '.power_on_time.hours // ""')"
done
