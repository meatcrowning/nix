#!/bin/sh
# Emits one pipe-delimited line:
#   rxBytes|txBytes|freeKb|usePct|volume|muted|cpuTotal|cpuIdle|cpuTempMilliC|gpuUsePct|gpuTempC
#
# Battery/AC and wifi were dropped (desktop box, no laptop battery — the
# "bat" reading used to pick up the Logitech trackball's own hidpp battery
# via the generic power_supply scan, not anything meaningful). Brightness
# was dropped too: this machine's display is external (DDC/CI over I2C via
# ddcutil), and ddcutil takes ~1.5s per call — too slow for this 2s poll
# loop, so SysInfo.qml polls it separately on its own longer timer instead.

net=$(awk 'NR>2{gsub(/:/," "); if($1!="lo"){rx+=$2; tx+=$10}} END{printf "%d|%d", rx, tx}' /proc/net/dev)
disk=$(df -kP / | awk 'NR==2{gsub(/%/,"",$5); printf "%d|%d", $4, $5}')

# Default sink volume (percent) + mute flag via wireplumber.
vraw=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null)
mute=0
case "$vraw" in *MUTED*) mute=1 ;; esac
vol=$(printf '%s\n' "$vraw" | awk '{printf "%d", ($2*100)+0.5}')
[ -z "$vol" ] && vol=-1

# CPU utilization: cumulative jiffies (total + idle) straight from /proc/stat.
# Raw counters, not a percentage — like rxBytes/txBytes above, SysInfo.qml
# diffs two polls 2s apart to get a usage percentage.
cpu=$(awk '/^cpu /{idle=$5+$6; total=0; for (i=2;i<=8;i++) total+=$i; printf "%d|%d", total, idle}' /proc/stat)

# CPU die temp via k10temp (AMD), the "Tctl" control-temp reading — the
# conventional one to show as "CPU temp". Search by driver name + label
# rather than a hardcoded hwmon index, since hwmon numbering isn't stable
# across boots (driver load order dependent).
cputemp=-1
for dir in /sys/class/hwmon/hwmon*/; do
    [ "$(cat "$dir/name" 2>/dev/null)" = "k10temp" ] || continue
    for lbl in "$dir"temp*_label; do
        [ -f "$lbl" ] || continue
        if [ "$(cat "$lbl" 2>/dev/null)" = "Tctl" ]; then
            input="${lbl%_label}_input"
            raw=$(cat "$input" 2>/dev/null)
            [ -n "$raw" ] && cputemp=$raw
            break
        fi
    done
    break
done

# GPU utilization + temp via nvidia-smi (NVIDIA proprietary driver). One cheap
# (~20ms) query for both. "gpuUsePct|gpuTempC"; -1|-1 if nvidia-smi is missing
# or errors (so the panel shows "--" rather than a stale value).
gpu="-1|-1"
if command -v nvidia-smi >/dev/null 2>&1; then
    graw=$(nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv,noheader,nounits 2>/dev/null)
    g=$(printf '%s\n' "$graw" | awk -F',' 'NR==1{gsub(/ /,""); if($1!="" && $2!="") printf "%d|%d", $1, $2}')
    [ -n "$g" ] && gpu="$g"
fi

printf '%s|%s|%s|%s|%s|%s|%s\n' "$net" "$disk" "$vol" "$mute" "$cpu" "$cputemp" "$gpu"
