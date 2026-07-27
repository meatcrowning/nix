#!/bin/sh
# Emits one pipe-delimited line:
#   rxBytes|txBytes|freeKb|usePct|volume|muted|cpuTotal|cpuIdle|cpuTempMilliC|gpuUsePct|gpuTempC|batteryPct|batteryCharging|memTotalKb|memAvailKb|swapTotalKb|swapFreeKb|load1|uptimeSec|gpuFanPct|gpuPowerW|gpuMemUsedMB|gpuMemTotalMB
#
# Fields are POSITIONAL and SysInfo.qml indexes them, so new ones go on the
# END. Everything after batteryCharging was added for the dock's task manager;
# each degrades to -1 where the host can't produce it (book has no nvidia-smi),
# so the readout shows "--" rather than a wrong number.
#
# Wifi stays dropped (both hosts are wired). Battery is back, scoped to
# /sys/class/power_supply/BAT* (generic ACPI laptops) and macsmc-battery
# (Apple Silicon under Asahi, book's driver) specifically — not a generic
# power_supply type=Battery scan, since that's what previously picked up the
# Logitech trackball's own hidpp battery on a desktop with no laptop battery
# at all. -1|0 when neither node exists, so the panel shows "--" and stays
# hidden on a desktop.
# Brightness was dropped too: this machine's display is external (DDC/CI
# over I2C via ddcutil), and ddcutil takes ~1.5s per call — too slow for
# this 2s poll loop, so SysInfo.qml polls it separately on its own longer
# timer instead.

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

# k10temp is AMD-only (top). book (Apple Silicon under Asahi) has no
# per-core CPU temp exposed at all, so fall back to macsmc_hwmon's
# "Battery Hotspot" sensor as a stand-in — it sits right next to the SoC and
# tracks load heat closely enough to serve as a "cpu temp" reading there.
if [ "$cputemp" = "-1" ]; then
    for dir in /sys/class/hwmon/hwmon*/; do
        [ "$(cat "$dir/name" 2>/dev/null)" = "macsmc_hwmon" ] || continue
        for lbl in "$dir"temp*_label; do
            [ -f "$lbl" ] || continue
            if [ "$(cat "$lbl" 2>/dev/null)" = "Battery Hotspot" ]; then
                input="${lbl%_label}_input"
                raw=$(cat "$input" 2>/dev/null)
                [ -n "$raw" ] && cputemp=$raw
                break
            fi
        done
        break
    done
fi

# Memory and swap, straight from /proc/meminfo. MemAvailable (not MemFree) is
# the kernel's own estimate of what a new allocation could actually get, i.e.
# free plus the reclaimable page cache — MemFree alone reads as "almost none"
# on any machine that has been up a while and is simply wrong to show a user.
mem=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^SwapTotal:/{st=$2} /^SwapFree:/{sf=$2} END{printf "%d|%d|%d|%d", t, a, st, sf}' /proc/meminfo)

# 1-minute load average and uptime in whole seconds.
load1=$(awk '{print $1}' /proc/loadavg)
uptime=$(awk '{printf "%d", $1}' /proc/uptime)

# GPU utilization + temp via nvidia-smi (NVIDIA proprietary driver). One cheap
# (~20ms) query for both. "gpuUsePct|gpuTempC"; -1|-1 if nvidia-smi is missing
# or errors (so the panel shows "--" rather than a stale value).
# The extra four (fan/power/vram) ride along in the SAME query — nvidia-smi's
# cost is process startup, not the number of columns, so they are free.
gpu="-1|-1"
gpux="-1|-1|-1|-1"
if command -v nvidia-smi >/dev/null 2>&1; then
    graw=$(nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,fan.speed,power.draw,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null)
    g=$(printf '%s\n' "$graw" | awk -F',' 'NR==1{gsub(/ /,""); if($1!="" && $2!="") printf "%d|%d", $1, $2}')
    [ -n "$g" ] && gpu="$g"
    gx=$(printf '%s\n' "$graw" | awk -F',' 'NR==1{gsub(/ /,"");
        f=($3=="" || $3=="[N/A]") ? -1 : $3;
        p=($4=="" || $4=="[N/A]") ? -1 : $4;
        mu=($5=="" || $5=="[N/A]") ? -1 : $5;
        mt=($6=="" || $6=="[N/A]") ? -1 : $6;
        printf "%d|%.1f|%d|%d", f, p, mu, mt}')
    [ -n "$gx" ] && gpux="$gx"
fi

# Battery percentage + charging flag via /sys/class/power_supply/BAT*
# (generic ACPI, e.g. top if it ever had one) or macsmc-battery (book).
# "-1|0" when neither node exists (desktop box, no battery).
#
# Percentage is computed from the energy_now/energy_full ratio (equivalently
# charge_now/charge_full) — the same figure `upower -b` reports — NOT the raw
# `capacity` node. On book's macsmc-battery `capacity` is the SMC's own gauge
# and reads several points high (e.g. 99 vs upower's 93), so the panel used to
# disagree with upower. Falls back to `capacity` on hosts lacking the
# energy/charge_* pair, where capacity already matches.
bat="-1|0"
for dir in /sys/class/power_supply/BAT*/ /sys/class/power_supply/macsmc-battery/; do
    [ -f "$dir/capacity" ] || continue
    status=$(cat "$dir/status" 2>/dev/null)
    chg=0
    [ "$status" = "Charging" ] && chg=1

    now=""; full=""
    if [ -r "$dir/energy_now" ] && [ -r "$dir/energy_full" ]; then
        now=$(cat "$dir/energy_now" 2>/dev/null); full=$(cat "$dir/energy_full" 2>/dev/null)
    elif [ -r "$dir/charge_now" ] && [ -r "$dir/charge_full" ]; then
        now=$(cat "$dir/charge_now" 2>/dev/null); full=$(cat "$dir/charge_full" 2>/dev/null)
    fi
    if [ -n "$now" ] && [ -n "$full" ] && [ "$full" -gt 0 ] 2>/dev/null; then
        cap=$(awk -v n="$now" -v f="$full" 'BEGIN{ printf "%d", n*100/f + 0.5 }')  # rounded, float-safe
    else
        cap=$(cat "$dir/capacity" 2>/dev/null)
    fi
    [ -n "$cap" ] && bat="$cap|$chg"
    break
done

printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' "$net" "$disk" "$vol" "$mute" "$cpu" "$cputemp" "$gpu" "$bat" "$mem" "$load1" "$uptime" "$gpux"
