#!/bin/sh
# Appends one JSONL sample (timestamp, CPU/GPU temp, per-fan RPM+duty) to
# ~/.local/state/thermal-history/<hostname>.jsonl. See
# docs/top-thermal-history.md for why this exists: nothing on this box ever
# sampled temps/fans over time, and on `top` no OS fan control is possible at
# all (nct6683's pwm nodes are read-only) — a sampled history is the only
# lever left for judging sustained-load behavior later.
#
# Host-neutral by construction, same discovery rules as
# home/prog/quickshell-files/scripts/sysinfo.sh's fan/temp block:
#   - CPU temp: k10temp's Tctl (top's AMD CPU); falls back to macsmc_hwmon's
#     "Battery Hotspot" (book, Apple Silicon under Asahi, no per-core temp).
#   - GPU temp: nvidia-smi only (top's RTX 5070). book has no NVIDIA GPU, so
#     gpu_temp_c is always null there.
#   - fans: every hwmon fan reporting a nonzero tachometer, with the sibling
#     pwm duty as a percentage where the chip has one. book is fanless, so
#     this is always [] there.
# A field this host cannot produce is JSON null, never a guessed number.

set -eu

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/thermal-history"
HOST=$(uname -n)
LOG="$STATE_DIR/$HOST.jsonl"
# Bound the log so it can't grow unbounded on a root fs that runs >80% full
# (docs/HARDWARE.md). ~150B/line at one sample per minute: 8 MiB is roughly
# 5-6 weeks of history before the rotation below ever trims it.
MAX_BYTES=8388608
KEEP_BYTES=4194304

mkdir -p "$STATE_DIR"

# Read the first line of a file into $_v without forking (see sysinfo.sh).
rd() { _v=''; [ -r "$1" ] && IFS= read -r _v < "$1" 2>/dev/null; :; }

# CPU package temp.
cputemp=""
for dir in /sys/class/hwmon/hwmon*/; do
    rd "$dir/name"; [ "$_v" = "k10temp" ] || continue
    for lbl in "$dir"temp*_label; do
        [ -f "$lbl" ] || continue
        rd "$lbl"; if [ "$_v" = "Tctl" ]; then
            rd "${lbl%_label}_input"; [ -n "$_v" ] && cputemp=$_v
            break
        fi
    done
    break
done
if [ -z "$cputemp" ]; then
    for dir in /sys/class/hwmon/hwmon*/; do
        rd "$dir/name"; [ "$_v" = "macsmc_hwmon" ] || continue
        for lbl in "$dir"temp*_label; do
            [ -f "$lbl" ] || continue
            rd "$lbl"; if [ "$_v" = "Battery Hotspot" ]; then
                rd "${lbl%_label}_input"; [ -n "$_v" ] && cputemp=$_v
                break
            fi
        done
        break
    done
fi
cpu_field=null
[ -n "$cputemp" ] && cpu_field=$(awk -v m="$cputemp" 'BEGIN{printf "%.1f", m/1000}')

# GPU temp (top only).
gpu_field=null
if command -v nvidia-smi >/dev/null 2>&1; then
    g=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1) || g=""
    case "$g" in ''|*[!0-9]*) ;; *) gpu_field=$g ;; esac
fi

# Per-fan RPM + pwm duty (%), one JSON object per fan that turns.
fans_json=""
for c in /sys/class/hwmon/hwmon*; do
    [ -d "$c" ] || continue
    rd "$c/name"; cn=$_v; [ -z "$cn" ] && cn="hwmon"
    for f in "$c"/fan*_input; do
        [ -r "$f" ] || continue
        i=${f##*/}; i=${i%_input}; i=${i#fan}
        rd "$f"; rpm=$_v
        case "$rpm" in ''|*[!0-9]*) rpm=0 ;; esac
        [ "$rpm" -eq 0 ] && continue
        pct=null
        if [ -r "$c/pwm$i" ]; then
            rd "$c/pwm$i"; pwm=$_v
            case "$pwm" in
                ''|*[!0-9]*) ;;
                *) [ "$pwm" -gt 255 ] && pwm=255
                   pct=$(( (pwm * 100 + 127) / 255 )) ;;
            esac
        fi
        lbl=""
        rd "$c/fan${i}_label"; [ -n "$_v" ] && lbl=$_v
        [ -z "$lbl" ] && lbl="fan$i"
        lbl=$(printf '%s' "$lbl" | tr ' ' '_' | tr -cd 'A-Za-z0-9._-' | cut -c1-16)
        [ -z "$lbl" ] && lbl="fan$i"
        fans_json="${fans_json:+$fans_json,}{\"name\":\"$lbl\",\"rpm\":$rpm,\"pct\":$pct}"
    done
done

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"ts":"%s","host":"%s","cpu_temp_c":%s,"gpu_temp_c":%s,"fans":[%s]}\n' \
    "$ts" "$HOST" "$cpu_field" "$gpu_field" "$fans_json" >> "$LOG"

size=$(wc -c < "$LOG" 2>/dev/null) || size=0
if [ "${size:-0}" -gt "$MAX_BYTES" ]; then
    tmp="$LOG.tmp.$$"
    tail -c "$KEEP_BYTES" "$LOG" > "$tmp"
    # tail -c can start mid-line; drop the first (possibly partial) line.
    tail -n +2 "$tmp" > "$LOG"
    rm -f "$tmp"
fi
