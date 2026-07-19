#!/bin/sh
# SMART summary for each SSD (rotational=0), one line per drive:
#   device|health|temp_c|wear_pct|power_on_hours
# health: PASSED / FAILED / "" (unknown). Fields left blank when a drive
# doesn't report them (USB bridges often block SMART entirely — skipped).
# Uses the NOPASSWD smartctl rule from sys/disks.nix — which lists the
# resolved /nix/store path, so we must invoke that same real path (sudo
# doesn't canonicalize the /run/current-system/sw/bin symlink, so a bare
# `sudo smartctl` would miss the rule and prompt for a password).
SMARTCTL=$(readlink -f "$(command -v smartctl)" 2>/dev/null)
[ -n "$SMARTCTL" ] || exit 0

for d in /sys/block/*; do
    name=$(basename "$d")
    case "$name" in
        loop* | ram* | zram* | dm-*) continue ;;
    esac
    [ "$(cat "$d/queue/rotational" 2>/dev/null)" = "0" ] || continue
    dev="/dev/$name"
    j=$(sudo -n "$SMARTCTL" -a -j "$dev" 2>/dev/null) || continue
    [ -n "$j" ] || continue
    printf '%s|%s|%s|%s|%s\n' "$dev" \
        "$(printf '%s' "$j" | jq -r 'if .smart_status.passed == true then "PASSED" elif .smart_status.passed == false then "FAILED" else "" end')" \
        "$(printf '%s' "$j" | jq -r '.temperature.current // ""')" \
        "$(printf '%s' "$j" | jq -r '.nvme_smart_health_information_log.percentage_used // ""')" \
        "$(printf '%s' "$j" | jq -r '.power_on_time.hours // ""')"
done
