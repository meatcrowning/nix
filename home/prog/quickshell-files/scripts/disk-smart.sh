#!/bin/sh
# SMART summary for each SSD (rotational=0), one line per drive:
#   device|health|temp_c|wear_pct|power_on_hours
# health: PASSED / FAILED / "" (unknown). Fields left blank when a drive
# doesn't report them (USB bridges often block SMART entirely — skipped).
# Uses the NOPASSWD smartctl rule from sys/disks.nix.
for d in /sys/block/*; do
    name=$(basename "$d")
    case "$name" in
        loop* | ram* | zram* | dm-*) continue ;;
    esac
    [ "$(cat "$d/queue/rotational" 2>/dev/null)" = "0" ] || continue
    dev="/dev/$name"
    j=$(sudo -n smartctl -a -j "$dev" 2>/dev/null) || continue
    [ -n "$j" ] || continue
    printf '%s|%s|%s|%s|%s\n' "$dev" \
        "$(printf '%s' "$j" | jq -r 'if .smart_status.passed == true then "PASSED" elif .smart_status.passed == false then "FAILED" else "" end')" \
        "$(printf '%s' "$j" | jq -r '.temperature.current // ""')" \
        "$(printf '%s' "$j" | jq -r '.nvme_smart_health_information_log.percentage_used // ""')" \
        "$(printf '%s' "$j" | jq -r '.power_on_time.hours // ""')"
done
