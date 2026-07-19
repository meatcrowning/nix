#!/bin/sh
# One line per mounted real block device, for the disk-hover popup:
#   device|label|mountpoint|size_bytes|used_bytes|rota|model
# rota: 1 spinning HDD, 0 SSD/flash. External and internal both included.
df -B1 --output=source,size,used,target 2>/dev/null | tail -n +2 | while read -r src size used target; do
    case "$src" in
        /dev/*) ;;
        *) continue ;;
    esac
    base=$(lsblk -no pkname "$src" 2>/dev/null | head -n1)
    [ -z "$base" ] && base=$(basename "$src")
    rota=$(cat "/sys/block/$base/queue/rotational" 2>/dev/null)
    label=$(lsblk -no label "$src" 2>/dev/null | head -n1)
    model=$(cat "/sys/block/$base/device/model" 2>/dev/null | sed 's/  */ /g;s/^ //;s/ $//')
    printf '%s|%s|%s|%s|%s|%s|%s\n' "$src" "$label" "$target" "$size" "$used" "${rota:-1}" "$model"
done
