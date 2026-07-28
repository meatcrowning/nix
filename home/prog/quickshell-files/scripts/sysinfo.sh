#!/bin/sh
# Emits one pipe-delimited line:
#   rxBytes|txBytes|freeKb|usePct|volume|muted|cpuTotal|cpuIdle|cpuTempMilliC|gpuUsePct|gpuTempC|batteryPct|batteryCharging|memTotalKb|memAvailKb|swapTotalKb|swapFreeKb|load1|uptimeSec|gpuFanPct|gpuPowerW|gpuMemUsedMB|gpuMemTotalMB|fanAvgRpm|fanCount|dskReadSectors|dskWriteSectors|psiCpu|psiIo|psiMem|powerW|batStatus|fanDetail
#
# fanDetail is the one non-scalar field: comma-separated "name:rpm:pct" per
# hwmon fan (pct = pwm duty, -1 where the chip has none), empty where nothing
# reports a tachometer. See the fan block below for what is and is not listed.
#
# Fields are POSITIONAL and SysInfo.qml indexes them, so new ones go on the
# END. Everything after batteryCharging was added for the dock's task manager;
# each degrades to -1 where the host can't produce it (book has no nvidia-smi),
# so the readout shows "--" rather than a wrong number.
#
# Wifi stays dropped (both hosts are wired). Battery is DISCOVERED, not
# hardcoded — the node name differs per platform (BAT0/BAT1 on generic ACPI,
# `macsmc-battery` on Apple Silicon under Asahi, and neither is guaranteed) —
# but a bare type=Battery scan is what once picked up the Logitech trackball's
# own hidpp battery on a desktop with no laptop battery at all, so the scan
# also requires scope != Device, which is exactly what a peripheral sets and a
# system battery does not. -1|0|0 when nothing qualifies, so the panel shows
# "--" and stays hidden on a desktop.
# Brightness was dropped too: this machine's display is external (DDC/CI
# over I2C via ddcutil), and ddcutil takes ~1.5s per call — too slow for
# this 2s poll loop, so SysInfo.qml polls it separately on its own longer
# timer instead.

# Two arguments, both from the Settings program (Widgets > monitoring), both
# optional so a hand-run still behaves the way it always did:
#   $1  the filesystem behind the bar's free/used readout   (`rootMount`, "/")
#   $2  the interface behind the rx/tx readout              (`netInterface`,
#       "auto" = every interface but lo, summed, which is what this has always
#       reported — NOT the default route, whatever the old label claimed)
# An interface that doesn't exist yields 0|0 rather than an error, which the
# panel already draws as an idle link; a mount that doesn't exist falls back to
# / rather than emitting a short line the parser would drop wholesale.
MOUNT="${1:-/}"
IFACE="${2:-auto}"
[ -d "$MOUNT" ] || MOUNT=/

net=$(awk -v want="$IFACE" 'NR>2{gsub(/:/," ");
        if($1=="lo") next;
        if(want!="auto" && want!="" && $1!=want) next;
        rx+=$2; tx+=$10}
    END{printf "%d|%d", rx, tx}' /proc/net/dev)
disk=$(df -kP "$MOUNT" | awk 'NR==2{gsub(/%/,"",$5); printf "%d|%d", $4, $5}')

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

# Average CHASSIS/CPU fan speed across every hwmon fan that reports a nonzero
# RPM, plus how many were counted. This is deliberately not the GPU fan (which
# nvidia-smi reports as a percentage below) — it is the case and cooler fans,
# a different set of hardware and the one that tells you whether the box as a
# whole is working hard. "0|0" where no fan node exists at all (book).
#
# HWMON_ROOT is overridable so tools/fan-harness.sh can drive this whole block
# against a SYNTHETIC hwmon tree. That is not a convenience: `top` reports no
# fans at all (no Super-I/O driver is loaded for the B650's sensor chip) and
# book is fanless, so there is no machine here on which this code path can
# otherwise be executed even once, let alone regression-tested.
HWMON_ROOT="${SYSINFO_HWMON:-/sys/class/hwmon}"
fans=$(awk 'BEGIN{ n=0; s=0 }
    { if ($1+0 > 0) { s += $1; n++ } }
    END{ printf "%d|%d", (n ? s/n : 0), n }' "$HWMON_ROOT"/hwmon*/fan*_input 2>/dev/null)
[ -z "$fans" ] && fans="0|0"

# PER-FAN detail, so the panel can show each fan instead of one average:
# comma-separated "name:rpm:pct" entries, empty where nothing reports a
# tachometer. Ordering is by chip directory then fan index — stable across
# polls, which matters because each entry is drawn as its own row.
#
# WHAT "pct" IS, EXACTLY: the sibling pwmN duty cycle (0-255) as a percentage,
# i.e. what the chip is COMMANDING the fan to do — NOT the fraction of the
# fan's maximum RPM. sysfs publishes no maximum, so there is no honest
# denominator available for the latter and we do not invent one. -1 where the
# chip exposes no pwm for that fan, and the panel then shows RPM alone rather
# than a made-up percentage.
#
# A fan is LISTED only when it TURNS (rpm > 0), and this rule was written the
# other way round first — "rpm > 0 OR duty commanded", on the reasoning that a
# fan being told to spin while reading 0 rpm is a stalled fan and a fault worth
# surfacing. This board disproves that. `top`'s nct6687 publishes ten
# fan*_input and eight pwm, of which exactly four headers have a fan on them
# (fan1-4); the other four read 0 rpm while their pwm registers sit at 23-100%
# duty. So a nonzero pwm on a dead tachometer is the ORDINARY state of an empty
# header here, not a fault, and the first rule listed eight fans on a machine
# with four. Measured, not inferred — and the reason a stalled fan is not
# distinguishable from an empty header in sysfs at all.
fandetail=""
_nchips=0
for _c in "$HWMON_ROOT"/hwmon*; do
    [ -d "$_c" ] || continue
    for _f in "$_c"/fan*_input; do
        [ -r "$_f" ] || continue
        _nchips=$((_nchips + 1))
        break
    done
done
for _c in "$HWMON_ROOT"/hwmon*; do
    [ -d "$_c" ] || continue
    _cn=$(cat "$_c/name" 2>/dev/null) || _cn=""
    [ -z "$_cn" ] && _cn="hwmon"
    for _f in "$_c"/fan*_input; do
        [ -r "$_f" ] || continue
        _i=${_f##*/}; _i=${_i%_input}; _i=${_i#fan}
        _rpm=$(cat "$_f" 2>/dev/null)
        case "$_rpm" in ''|*[!0-9]*) _rpm=0 ;; esac
        _pct=-1
        if [ -r "$_c/pwm$_i" ]; then
            _pwm=$(cat "$_c/pwm$_i" 2>/dev/null)
            case "$_pwm" in
                ''|*[!0-9]*) ;;
                *) [ "$_pwm" -gt 255 ] && _pwm=255
                   _pct=$(( (_pwm * 100 + 127) / 255 )) ;;
            esac
        fi
        [ "$_rpm" -eq 0 ] && continue
        # The driver's own label where it has one (some boards name the headers
        # "CPU Fan", "Chassis Fan 2"); fanN otherwise. Prefixed with the chip
        # only when more than one chip reports fans, so the common single-chip
        # case stays short — these are drawn in an 8px-per-character pixel font
        # in a panel that can be 270px wide.
        _lbl=""
        [ -r "$_c/fan${_i}_label" ] && _lbl=$(cat "$_c/fan${_i}_label" 2>/dev/null)
        [ -z "$_lbl" ] && _lbl="fan$_i"
        [ "$_nchips" -gt 1 ] && _lbl="$_cn.$_lbl"
        # ':' and ',' are this field's own delimiters and '|' is the line's, so
        # a driver-supplied label must not be able to carry any of them.
        _lbl=$(printf '%s' "$_lbl" | tr ' ' '_' | tr -cd 'A-Za-z0-9._-' | cut -c1-12)
        [ -z "$_lbl" ] && _lbl="fan$_i"
        fandetail="${fandetail:+$fandetail,}$_lbl:$_rpm:$_pct"
    done
done

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

# Battery percentage + charging flag + state code.
#
# The node is FOUND, never assumed. Well-known names first (BAT*/ for generic
# ACPI, macsmc-battery/ for Apple Silicon under Asahi), then — only if neither
# exists — a scan of every power_supply device for a type=Battery whose scope
# is explicitly "System".
#
# That last clause is the whole reason this isn't a plain type=Battery scan.
# A HID++ peripheral publishes a type=Battery node too, which is how the
# Logitech trackball on `top` once became "the laptop battery" of a desktop
# with no battery at all; every peripheral gauge (hid-logitech-hidpp,
# hid-input's generic one) reports scope=Device. Requiring "System" — not
# merely "not Device" — keeps the discovery pass from ever claiming a node
# that declines to say what it belongs to, which is the only failure mode that
# would change `top`'s panel. A real laptop battery is either named BAT* or
# says System (book's macsmc-battery does).
#
# Percentage is computed from the energy_now/energy_full ratio (equivalently
# charge_now/charge_full) — the same figure `upower -b` reports — NOT the raw
# `capacity` node. On book's macsmc-battery `capacity` is the SMC's own gauge
# and reads several points high (e.g. 99 vs upower's 93), so the panel used to
# disagree with upower. Falls back to `capacity` on hosts lacking the
# energy/charge_* pair, where capacity already matches.
#
# batStatus is a code, so the panel never string-matches a kernel label:
# 0 no battery, 1 discharging, 2 charging, 3 full, 4 not charging (on AC and
# idle), 5 present but unknown. "on AC" and "discharging" are separate states
# on purpose — the same wattage means opposite things in each.
bat="-1|0"
batstat=0
batdir=""
for dir in /sys/class/power_supply/BAT*/ /sys/class/power_supply/macsmc-battery/; do
    [ -f "$dir/capacity" ] || continue
    [ "$(cat "$dir/scope" 2>/dev/null)" = "Device" ] && continue
    batdir="$dir"
    break
done
if [ -z "$batdir" ]; then
    for dir in /sys/class/power_supply/*/; do
        [ -f "$dir/capacity" ] || continue
        [ "$(cat "$dir/type" 2>/dev/null)" = "Battery" ] || continue
        [ "$(cat "$dir/scope" 2>/dev/null)" = "System" ] || continue
        batdir="$dir"
        break
    done
fi

if [ -n "$batdir" ]; then
    chg=0
    case "$(cat "$batdir/status" 2>/dev/null)" in
        Charging)      chg=1; batstat=2 ;;
        Discharging)   batstat=1 ;;
        Full)          batstat=3 ;;
        "Not charging") batstat=4 ;;
        *)             batstat=5 ;;
    esac

    # `status` is authoritative and is NOT second-guessed — a laptop on a
    # too-small charger really is discharging while plugged in, and overriding
    # that with "on ac" would be a lie the card draws for hours. The mains
    # supply is consulted for the UNKNOWN case only, where the gauge has told
    # us nothing and a coin-flip between "draining" and "plugged in" is worse
    # than one sysfs read.
    #
    # type=Mains ONLY. book also publishes two tps6598x type=USB *source*
    # nodes, which describe power the laptop is SUPPLYING to a peripheral;
    # their `online` has nothing to do with whether it is on the charger.
    if [ "$batstat" = "5" ]; then
        batstat=1
        for dir in /sys/class/power_supply/*/; do
            [ "$(cat "$dir/type" 2>/dev/null)" = "Mains" ] || continue
            [ "$(cat "$dir/online" 2>/dev/null)" = "1" ] && { batstat=4; break; }
        done
    fi

    now=""; full=""
    if [ -r "$batdir/energy_now" ] && [ -r "$batdir/energy_full" ]; then
        now=$(cat "$batdir/energy_now" 2>/dev/null); full=$(cat "$batdir/energy_full" 2>/dev/null)
    elif [ -r "$batdir/charge_now" ] && [ -r "$batdir/charge_full" ]; then
        now=$(cat "$batdir/charge_now" 2>/dev/null); full=$(cat "$batdir/charge_full" 2>/dev/null)
    fi
    # energy_full can legitimately be 0 or missing on a freshly-reset gauge, so
    # the ratio is only taken when the denominator is genuinely positive.
    if [ -n "$now" ] && [ -n "$full" ] && [ "$full" -gt 0 ] 2>/dev/null; then
        cap=$(awk -v n="$now" -v f="$full" 'BEGIN{ printf "%d", n*100/f + 0.5 }')  # rounded, float-safe
    else
        cap=$(cat "$batdir/capacity" 2>/dev/null)
    fi
    if [ -n "$cap" ]; then
        bat="$cap|$chg"
    else
        batstat=0   # a node with no readable charge is no better than none
    fi
fi

# ---- the three book replaces gpu/vram/fan with ---------------------------
# book has no source at all for those: Asahi's DRM driver publishes no fdinfo
# engine counters and no devfreq node (so there is no GPU utilization to read),
# its GPU memory is the system's (so there is no separate pool), and the machine
# is fanless. These three are what it CAN measure, and they are collected on
# both hosts anyway — they are three sysfs reads, and the panel picks the card
# set by host.

# Disk throughput: cumulative sectors read/written, summed over the PHYSICAL
# block devices only. /proc/diskstats lists partitions alongside their parent
# disk, so an unfiltered sum counts every I/O two or three times over. Raw
# counters like rxBytes/txBytes above — SysInfo.qml diffs two polls for a rate.
# Sectors are 512B in this interface regardless of the drive's real block size.
dsk=$(awk '$3 ~ /^(nvme[0-9]+n[0-9]+|sd[a-z]+|mmcblk[0-9]+|vd[a-z]+)$/ { r += $6; w += $10 }
    END { printf "%d|%d", r, w }' /proc/diskstats 2>/dev/null)
[ -z "$dsk" ] && dsk="0|0"

# Pressure stall information: the percentage of the last 10s during which at
# least one task was blocked waiting on cpu, io or memory. "some", not "full" —
# full means EVERY task was stalled, which on an interactive desktop is rare
# enough to read as a flat zero, while some is exactly the "why does this feel
# slow right now" signal. Printed by a function rather than an awk over all
# three, so a missing /proc/pressure/* yields "-1" instead of dropping the field
# and shifting every position after it.
psi_of() {
    v=$(awk '/^some /{ sub(/^avg10=/, "", $2); print $2; exit }' "/proc/pressure/$1" 2>/dev/null)
    [ -n "$v" ] || v=-1
    printf '%s' "$v"
}
psi="$(psi_of cpu)|$(psi_of io)|$(psi_of memory)"

# Whole-machine power draw, watts. book publishes it as macsmc_hwmon's "Total
# System Power": measured across an idle->busy step it tracks
# macsmc-battery/power_now exactly, one sample behind (4.7W idle, 18.7W with
# four spinners), so it is the system's draw and not just the SoC's. Falls back
# to a generic ACPI power_now. -1 where nothing reports it (top, a desktop),
# where this card is not drawn anyway.
powerw=-1
for dir in /sys/class/hwmon/hwmon*/; do
    [ "$(cat "$dir/name" 2>/dev/null)" = "macsmc_hwmon" ] || continue
    for lbl in "$dir"power*_label; do
        [ -f "$lbl" ] || continue
        [ "$(cat "$lbl" 2>/dev/null)" = "Total System Power" ] || continue
        raw=$(cat "${lbl%_label}_input" 2>/dev/null)
        [ -n "$raw" ] && powerw=$(awk -v u="$raw" 'BEGIN{ printf "%.2f", u / 1000000 }')
        break
    done
    break
done
# Fall back to the discovered battery's own power_now (see the battery block
# above) rather than re-globbing BAT*, so a machine whose node is named
# something else still gets a wattage.
if [ "$powerw" = "-1" ] && [ -n "$batdir" ] && [ -r "$batdir/power_now" ]; then
    raw=$(cat "$batdir/power_now" 2>/dev/null)
    # sign convention varies by driver; the magnitude is the draw either way
    [ -n "$raw" ] && powerw=$(awk -v u="$raw" 'BEGIN{ if (u < 0) u = -u; printf "%.2f", u / 1000000 }')
fi

printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' "$net" "$disk" "$vol" "$mute" "$cpu" "$cputemp" "$gpu" "$bat" "$mem" "$load1" "$uptime" "$gpux" "$fans" "$dsk" "$psi" "$powerw" "$batstat" "$fandetail"
