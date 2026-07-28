#!/usr/bin/env bash
# Exercise the panel's per-fan readout against a SYNTHETIC hwmon tree.
#
# WHY THIS EXISTS. Neither machine in this flake can produce a fan reading.
# `top` exposes no fan*_input at all (no Super-I/O driver is loaded for the
# B650's sensor chip — the hwmon devices are nvme, spd5118, k10temp, amdgpu,
# mt7921 and a trackball battery), and book is fanless. So the whole per-fan
# path — discovery, ordering, labelling, the pwm-duty percentage, the
# hide-at-zero case — has no hardware anywhere here to run against, not once.
# This script is the only way it is ever executed, and therefore the only way
# it can be regression-tested. Do not delete it when the user loads nct6775:
# it still covers the shapes that board does not happen to have (labels, two
# chips, a commanded-but-stalled fan).
#
# Two halves:
#   data — scripts/sysinfo.sh against fake sysfs, asserting the emitted field
#   derivation — Fans.qml driven offscreen at 0/1/2/5 fans, asserting the
#                headline, the line count, the tooltip and the colour ladder
#
#   ./tools/fan-harness.sh            # both halves, quiet on success
#
# Exit 0 = every case passed.
set -uo pipefail

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(cd -- "$HERE/.." && pwd)
QSDIR="$REPO/home/prog/quickshell-files"
SYSINFO="$QSDIR/scripts/sysinfo.sh"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL  %s\n' "$*"; }
check() { # check <what> <expected> <actual>
    if [ "$2" = "$3" ]; then ok; else bad "$1: expected [$2] got [$3]"; fi
}

# ---------------------------------------------------------------- fake sysfs
# mkchip <root> <hwmonN> <name> [fanIdx:rpm[:pwm] ...]
# A fan with no pwm term gets no pwmN node at all, which is the case this must
# cover: the chip is then unable to report a percentage and the panel has to
# fall back to RPM rather than invent a denominator.
mkchip() {
    local root=$1 dir=$2 name=$3; shift 3
    mkdir -p "$root/$dir"
    printf '%s\n' "$name" > "$root/$dir/name"
    local spec idx rpm pwm
    for spec in "$@"; do
        idx=${spec%%:*}; spec=${spec#*:}
        rpm=${spec%%:*}
        printf '%s\n' "$rpm" > "$root/$dir/fan${idx}_input"
        case "$spec" in
            *:*) pwm=${spec#*:}; printf '%s\n' "$pwm" > "$root/$dir/pwm${idx}" ;;
        esac
    done
}

# field <n> <line>  — 1-indexed pipe field
field() { printf '%s' "$2" | cut -d'|' -f"$1"; }

run_sysinfo() { SYSINFO_HWMON="$1" sh "$SYSINFO" 2>/dev/null; }

echo "== data: scripts/sysinfo.sh against synthetic hwmon =="

# --- 0 fans: nothing anywhere. This is TODAY on `top`, and the widget must
#     stay hidden rather than draw a permanent zero.
R=$WORK/n0; mkdir -p "$R"
mkchip "$R" hwmon0 k10temp
mkchip "$R" hwmon1 nvme
L=$(run_sysinfo "$R")
check "0 fans: fanAvgRpm" "0"  "$(field 24 "$L")"
check "0 fans: fanCount"  "0"  "$(field 25 "$L")"
check "0 fans: detail"    ""   "$(field 33 "$L")"

# --- 1 fan, with pwm: the percentage is real (duty), so it is reported.
R=$WORK/n1; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180:128
L=$(run_sysinfo "$R")
check "1 fan: fanCount" "1"              "$(field 25 "$L")"
check "1 fan: detail"   "fan1:1180:50"   "$(field 33 "$L")"

# --- 1 fan, NO pwm: pct must be -1, never a guessed fraction of some assumed
#     maximum. This is the honesty case.
R=$WORK/n1b; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180
L=$(run_sysinfo "$R")
check "1 fan no pwm: detail" "fan1:1180:-1" "$(field 33 "$L")"

# --- 2 fans, one chip, one with pwm and one without: mixed units in one list.
R=$WORK/n2; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180:128 2:820
L=$(run_sysinfo "$R")
check "2 fans: fanCount" "2"                          "$(field 25 "$L")"
check "2 fans: detail"   "fan1:1180:50,fan2:820:-1"   "$(field 33 "$L")"
check "2 fans: avg"      "1000"                       "$(field 24 "$L")"

# --- 5 fans across TWO chips: ordering must be stable (chip dir, then fan
#     index) and the labels must be chip-prefixed so they stay distinguishable.
R=$WORK/n5; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180:128 2:820:64 3:2400:255
mkchip "$R" hwmon2 amdgpu  1:1500:200 2:1500:200
L=$(run_sysinfo "$R")
check "5 fans: fanCount" "5" "$(field 25 "$L")"
check "5 fans: detail" \
  "nct6799.fan1:1180:50,nct6799.fan2:820:25,nct6799.fan3:2400:100,amdgpu.fan1:1500:78,amdgpu.fan2:1500:78" \
  "$(field 33 "$L")"
# ...and it is stable: the same tree twice must give the identical string.
L2=$(run_sysinfo "$R")
check "5 fans: stable ordering" "$(field 33 "$L")" "$(field 33 "$L2")"

# --- a header reading 0 rpm is NOT listed, whatever its pwm register says.
#     This is `top`'s own shape and the reason the rule is rpm-only: the board's
#     nct6687 publishes ten fan*_input and eight pwm, four headers have fans on
#     them, and the other four sit at 0 rpm with 23-100% duty. So a nonzero pwm
#     over a dead tachometer is an EMPTY HEADER here, not a stalled fan — and
#     sysfs offers nothing that tells the two apart. Listing on duty as well as
#     rpm showed eight fans on a machine with four.
R=$WORK/nz; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180:128 2:0:0 3:0:180
L=$(run_sysinfo "$R")
check "0-rpm headers dropped whatever their duty" \
  "fan1:1180:50" "$(field 33 "$L")"

# --- a driver-supplied label wins, and cannot smuggle a delimiter into the
#     field. "Chassis Fan, 2:x|y" must come back sanitised.
R=$WORK/nl; mkdir -p "$R"
mkchip "$R" hwmon0 nct6799 1:1180:128
printf 'Chassis Fan, 2:x|y\n' > "$R/hwmon0/fan1_label"
L=$(run_sysinfo "$R")
D=$(field 33 "$L")
# Spaces become '_', the delimiters ':' ',' '|' are stripped outright, and the
# result is capped at 12 characters — so nothing a driver puts in a label can
# add a field to this line or a row to the widget.
check "label sanitised"    "Chassis_Fan_" "$(printf '%s' "$D" | cut -d: -f1)"
check "label field intact" "3" "$(printf '%s' "$D" | awk -F: '{print NF}')"
check "one entry only"     "1" "$(printf '%s' "$D" | awk -F, '{print NF}')"

# --- the line still has the field count SysInfo.qml's guards expect.
check "field count" "33" "$(printf '%s' "$L" | awk -F'|' '{print NF}')"

# ------------------------------------------------------- the toast's shape
# The alarm's LOUDNESS is four behaviours the panel already implements for
# urgency 2 (soundCritical instead of the balloon, Do Not Disturb bypass,
# exemption from toast-stack eviction, and never auto-expiring), plus an
# explicit `-t 0` now that the panel honours a stated timeout. None of that is
# re-tested here — Notifications.qml owns it. What IS tested is that the alarm
# still ASKS for it, because losing `-u critical` or `-t 0` in an edit would
# silently downgrade a pump failure to a 5-second balloon and nothing would
# fail.
#
# Deliberately a source assertion and not a live send: a real notification here
# reaches the user's screen, and an agent's test toasts have already had to be
# cleared off it by hand once today. An isolated bus is no help either — with no
# name owner on it, notify-send's call is never dispatched to be observed.
echo "== the alarm's toast =="
NOTIFY=$(sed -n '/_notifyFanStopped/,/^    }/p' "$QSDIR/SysInfo.qml")
case "$NOTIFY" in
    *'"notify-send"'*) ok ;;
    *) bad "alarm: must route through notify-send like every other toast here" ;;
esac
case "$NOTIFY" in
    *'"-u", "critical"'*) ok ;;
    *) bad "alarm: must be urgency critical (sound, DND bypass, no eviction)" ;;
esac
case "$NOTIFY" in
    *'"-t", "0"'*) ok ;;
    *) bad "alarm: must set an explicit 0 timeout so it never expires" ;;
esac

# ---------------------------------------------------------------- the view
echo "== derivation: Fans.qml offscreen =="

QMLBIN=$(command -v qml || true)
if [ -z "$QMLBIN" ]; then
    echo "SKIP  qml runtime not on PATH; derivation cases not run"
else
    # Fans.qml is copied next to a STUB Theme rather than imported from the
    # panel directory: the real singletons there pull in Quickshell
    # (SettingsStore holds a FileView), which a bare `qml` cannot instantiate.
    # The component itself is unmodified, which is the point — it is pure
    # derivation over its `rows`/`hist` properties, and that is exactly what
    # makes it testable without a panel, a compositor, or a particular set of
    # fans. This board has four; the 0, 1, 2 and 5 cases have no hardware here.
    ST=$WORK/qml; mkdir -p "$ST"
    cp "$QSDIR/Fans.qml" "$ST/" || { echo "FAIL  cannot copy Fans.qml"; fail=$((fail+1)); }
    cp "$QSDIR/FanAlarm.qml" "$ST/" || { echo "FAIL  cannot copy FanAlarm.qml"; fail=$((fail+1)); }
    cat > "$ST/Theme.qml" <<'THEOF'
pragma Singleton
import QtQuick
QtObject {
    readonly property color accent: "#5c9fcc"
    readonly property color dim: "#2a4354"
}
THEOF
    cat > "$ST/qmldir" <<'DIREOF'
singleton Theme 1.0 Theme.qml
Fans 1.0 Fans.qml
FanAlarm 1.0 FanAlarm.qml
DIREOF

    cat > "$ST/Main.qml" <<'MAINEOF'
import QtQuick

QtObject {
    id: win
    // `h` overrides the default history length, `v` is the set of fans ever
    // seen to move.
    property var cases: [
        { name: "n0", rows: [] },
        { name: "n1", rows: [ {name:"fan1", rpm:1180, pct:50} ] },
        // mixed: one fan with a duty, one with only a tachometer. The one
        // without must keep its row in the tooltip and get NO line.
        { name: "n2", rows: [ {name:"fan1", rpm:1180, pct:50},
                              {name:"fan2", rpm:820,  pct:-1} ] },
        // nothing reports a duty at all: the headline must fall back to rpm
        // rather than print a percent sign over a number that is not one.
        { name: "nr", rows: [ {name:"fan1", rpm:1180, pct:-1},
                              {name:"fan2", rpm:820,  pct:-1} ] },
        // five, including a gpu-shaped row (a percentage and no tachometer).
        { name: "n5", rows: [ {name:"fan1", rpm:1180, pct:50}, {name:"fan2", rpm:820, pct:25},
                              {name:"fan3", rpm:2400, pct:100},{name:"fan4", rpm:1500, pct:78},
                              {name:"gpu",  rpm:-1,   pct:37} ],
                     v: ["fan1","fan2","fan3","fan4","gpu"] },
        // THE PUMP. Pinned at 100%, never once observed to move, long history.
        // It must not be the headline (that is fan3 at 59%), must keep its line
        // and its tooltip row, and must be marked.
        { name: "pump", rows: [ {name:"fan1", rpm:459,  pct:11},
                                {name:"fan2", rpm:3458, pct:100},
                                {name:"fan3", rpm:1846, pct:59} ],
                        v: ["fan1","fan3"] },
        // THE THERMAL EVENT - the case that makes "exclude anything at 100%" a
        // bad rule. fan3 has ramped to 100% and HAS moved before, so it must
        // take the headline back off the pump.
        { name: "therm", rows: [ {name:"fan1", rpm:459,  pct:11},
                                 {name:"fan2", rpm:3458, pct:100},
                                 {name:"fan3", rpm:2400, pct:100} ],
                         v: ["fan1","fan3"] },
        // TOO SOON. Same pump, only 5 samples in - under settleSamples nothing
        // is judged, so it is still the headline.
        { name: "young", rows: [ {name:"fan1", rpm:459,  pct:11},
                                 {name:"fan2", rpm:3458, pct:100} ],
                         v: ["fan1"], h: 5 },
        // EVERY fan fixed. The rule would empty the headline, so it falls back
        // to all of them rather than summarising nothing.
        { name: "allfix", rows: [ {name:"fan1", rpm:3458, pct:100},
                                  {name:"fan2", rpm:3400, pct:100} ],
                          v: [] },
        // A STOPPED fan, as SysInfo re-emits one: 0 rpm, no duty, stopped flag.
        // It must never be caught by the hide rule and must be called out.
        { name: "stop", rows: [ {name:"fan1", rpm:459, pct:11},
                                {name:"fan2", rpm:0, pct:-1, stopped:true} ],
                        v: ["fan1"] },
    ]
    property var probe: Fans { }
    Component.onCompleted: {
        for (var c = 0; c < win.cases.length; c++) {
            var kase = win.cases[c];
            var n = kase.h === undefined ? win.probe.settleSamples + 5 : kase.h;
            var samples = [];
            for (var k = 0; k < n; k++) samples.push(50);
            var h = {}, vd = {};
            for (var j = 0; j < kase.rows.length; j++)
                h[kase.rows[j].name] = samples;
            // No `v` at all means "everything has moved" - the pre-pump cases,
            // which must be unaffected by the rule.
            if (kase.v === undefined) {
                for (var j2 = 0; j2 < kase.rows.length; j2++) vd[kase.rows[j2].name] = true;
            } else {
                for (var j3 = 0; j3 < kase.v.length; j3++) vd[kase.v[j3]] = true;
            }
            win.probe.rows = kase.rows;
            win.probe.hist = h;
            win.probe.varied = vd;
            var shades = [];
            for (var i = 0; i < kase.rows.length; i++)
                shades.push(String(win.probe.shade(i)));
            console.warn("CASE " + kase.name
                + " n=" + win.probe.count
                + " shown=" + win.probe.shown
                + " lines=" + win.probe.series.length
                + " headline=" + win.probe.headline
                + " sub=[" + win.probe.subline + "]"
                + " detail=" + win.probe.detail.split("\n").length
                + " stopped=" + (win.probe.detail.split("STOPPED").length - 1)
                + " shades=" + shades.join("/"));
        }
        win.alarmCases();
        Qt.exit(0);
    }

    // ---- the pump-failure alarm ------------------------------------------
    // Replays whole EPISODES poll by poll. A real pump stop cannot be staged
    // and must never be staged on the live machine, so this is the only place
    // the alarm is ever exercised. Nothing here can reach a notification
    // server: FanAlarm returns a name and SysInfo is what would send the toast,
    // and SysInfo is not loaded.
    property var alarm: FanAlarm { }

    // Drive `n` polls of one fan being stopped and count how many times the
    // alarm fires. `hist` is how long it ran first, `varied` whether it was
    // ever controlled, `hadRpm` whether it ever had a tachometer.
    function runStopped(n, histLen, varied, hadRpm) {
        var rows = [ {name: "fanX", rpm: 0, pct: -1, stopped: true} ];
        var h = {}; var samples = [];
        for (var i = 0; i < histLen; i++) samples.push(100);
        h["fanX"] = samples;
        var vd = {}; if (varied) vd["fanX"] = true;
        var hr = {}; if (hadRpm) hr["fanX"] = true;
        var fires = 0;
        for (var p = 0; p < n; p++)
            if (win.alarm.update(rows, h, vd, hr) !== "") fires++;
        return fires;
    }
    function resetAlarm() { win.alarm.stoppedFor = ({}); win.alarm.alerted = ({}); }

    function alarmCases() {
        var polls = win.alarm.alarmPolls;
        var settle = win.alarm.settleSamples;

        // A real failure: ran for a minute, never controlled, had a tacho.
        // Fires exactly ONCE however long it stays stopped.
        resetAlarm();
        console.warn("ALARM real fires=" + runStopped(polls * 4, settle + 10, false, true)
                     + " active=[" + win.alarm.active + "]");

        // Not yet. One poll short of the threshold must be silent - this is the
        // debounce that keeps a tachometer glitch from crying wolf.
        resetAlarm();
        console.warn("ALARM early fires=" + runStopped(polls - 1, settle + 10, false, true)
                     + " active=[" + win.alarm.active + "]");

        // fan5 SHAPED: spun ~20s (10 samples), under settleSamples. An
        // unpopulated header that twitches once is not a fan that failed.
        resetAlarm();
        console.warn("ALARM young fires=" + runStopped(polls * 4, 10, false, true));

        // A fan the machine CONTROLS. It has a line on the card, so its
        // stopping is already visible; this alarm is for the hidden one.
        resetAlarm();
        console.warn("ALARM varied fires=" + runStopped(polls * 4, settle + 10, true, true));

        // NO TACHOMETER (the gpu). "0 rpm" is its normal reading, so an
        // nvidia-smi hiccup must not announce a dead graphics card fan.
        resetAlarm();
        console.warn("ALARM notacho fires=" + runStopped(polls * 4, settle + 10, false, false));

        // RECOVERY then a SECOND failure: the fan comes back, the episode is
        // forgotten, and a genuine second failure notifies again.
        resetAlarm();
        var f1 = runStopped(polls, settle + 10, false, true);
        var running = [ {name: "fanX", rpm: 1200, pct: 50} ];
        var h2 = {}; var s2 = []; for (var i = 0; i < settle + 10; i++) s2.push(100);
        h2["fanX"] = s2;
        for (var r = 0; r < 3; r++) win.alarm.update(running, h2, {}, {fanX: true});
        var f2 = runStopped(polls, settle + 10, false, true);
        console.warn("ALARM recover first=" + f1 + " second=" + f2);
    }
}
MAINEOF

    # QT_FORCE_STDERR_LOGGING is NOT optional here. Without it this Qt build
    # emits nothing at all from console.warn/log — the run exits 0 in silence,
    # which reads exactly like a harness whose assertions all vanished. (Same
    # family as the panel's own "qs drops console.log" trap, different cause.)
    OUT=$(QT_QPA_PLATFORM=offscreen QT_FORCE_STDERR_LOGGING=1 \
          "$QMLBIN" -I "$ST" "$ST/Main.qml" 2>&1 </dev/null)
    printf '%s\n' "$OUT" | grep -vE '^qml: (CASE|ALARM) ' | grep -E '.' | sed 's/^/  /'

    getcase() { printf '%s\n' "$OUT" | grep "CASE $1 " ; }
    v() { printf '%s\n' "$2" | tr ' ' '\n' | grep "^$1=" | cut -d= -f2- ; }

    # 0 fans: nothing to say and nothing to draw. The card's consumers hide on
    # this, rather than drawing a permanent zero.
    C=$(getcase n0)
    check "n0: count"    "0"  "$(v n "$C")"
    check "n0: no lines" "0"  "$(v lines "$C")"
    check "n0: headline" "--" "$(v headline "$C")"

    C=$(getcase n1)
    check "n1: one line"  "1"    "$(v lines "$C")"
    check "n1: headline"  "50%"  "$(v headline "$C")"
    check "n1: sub"       "[1180r]" "$(v sub "$C")"

    # A fan with no duty is NOT plotted — there is no honest denominator to put
    # it on a 0-100 axis with — but it keeps its tooltip row and its exact rpm.
    C=$(getcase n2)
    check "n2: two fans"       "2"   "$(v n "$C")"
    check "n2: one line only"  "1"   "$(v lines "$C")"
    check "n2: both in tooltip" "2"  "$(v detail "$C")"
    check "n2: headline"       "50%" "$(v headline "$C")"

    # No duty anywhere: rpm headline, no lines, everything in the tooltip.
    C=$(getcase nr)
    check "nr: no lines"  "0"       "$(v lines "$C")"
    check "nr: headline"  "1180rpm" "$(v headline "$C")"
    check "nr: no sub"    "[]"      "$(v sub "$C")"

    # Five fans, one of them tachometer-less (a gpu). The headline is the
    # FASTEST going, and its sub is that same fan's rpm — not the highest rpm
    # on the machine, which would be a second claim quietly disagreeing.
    C=$(getcase n5)
    check "n5: five lines"   "5"      "$(v lines "$C")"
    check "n5: headline"     "100%"   "$(v headline "$C")"
    check "n5: sub is ITS rpm" "[2400r]" "$(v sub "$C")"
    check "n5: tooltip rows" "5"      "$(v detail "$C")"

    # --- THE PUMP. [his] "i dont need to see it at all" - so pinned at max and
    #     never seen to move means GONE: no line, no tooltip row, no headline.
    C=$(getcase pump)
    check "pump: hidden from the card"     "2"       "$(v shown "$C")"
    check "pump: no line for it"           "2"       "$(v lines "$C")"
    check "pump: not in the tooltip"       "2"       "$(v detail "$C")"
    check "pump: headline is the real fan" "59%"     "$(v headline "$C")"
    check "pump: sub is that fan's rpm"    "[1846r]" "$(v sub "$C")"

    # --- THE THERMAL EVENT. A fan that has moved before and is now at 100% must
    #     stay VISIBLE and take the headline. This is why "hide anything at max"
    #     alone is a bad rule - it would now delete the fan worth seeing, not
    #     merely drop it from a summary.
    C=$(getcase therm)
    check "thermal: maxed chassis fan still SHOWN"     "2"       "$(v shown "$C")"
    check "thermal: it has a line"                     "2"       "$(v lines "$C")"
    check "thermal: it is the headline"                "100%"    "$(v headline "$C")"
    check "thermal: and it is the one that moved"      "[2400r]" "$(v sub "$C")"

    # --- TOO SOON. Under settleSamples nothing is judged constant, or a fresh
    #     panel would blank fans it has simply not watched yet. This guard is
    #     more important now that the consequence is deletion.
    C=$(getcase young)
    check "young: nothing hidden yet"   "2"    "$(v shown "$C")"
    check "young: still the headline"   "100%" "$(v headline "$C")"

    # --- ALL FIXED. The rule must never empty the CARD; a card of constants
    #     says more than a blank one.
    C=$(getcase allfix)
    check "all fixed: falls back to all" "2"    "$(v shown "$C")"
    check "all fixed: still drawn"       "2"    "$(v lines "$C")"
    check "all fixed: has a headline"    "100%" "$(v headline "$C")"

    # --- A STOPPED FAN. The cost of hiding the pump is that a pump failure has
    #     no indicator, so SysInfo re-emits a fan that stops reporting at 0 rpm.
    #     At 0 it is nowhere near maximum, so the hide rule cannot catch it: it
    #     must be visible and called out.
    C=$(getcase stop)
    check "stopped: shown"        "2" "$(v shown "$C")"
    check "stopped: in tooltip"   "2" "$(v detail "$C")"
    check "stopped: called out"   "1" "$(v stopped "$C")"

    # ---- the pump-failure alarm ------------------------------------------
    # A real pump stop cannot be staged, so these replay whole episodes poll by
    # poll. False alarms are the entire risk: a wrong "your CPU is cooking" at
    # 3am is worse than the tooltip-only status quo, so four of the six cases
    # here are things that must stay SILENT.
    ga() { printf '%s\n' "$OUT" | grep "ALARM $1 " ; }
    check "alarm: real failure fires exactly once" "fires=1" "$(ga real | tr ' ' '\n' | grep '^fires=')"
    check "alarm: and the card knows"              "active=[fanX]" "$(ga real | tr ' ' '\n' | grep '^active=')"
    check "alarm: one poll short is silent"        "fires=0" "$(ga early | tr ' ' '\n' | grep '^fires=')"
    check "alarm: fan5-shaped header is silent"    "fires=0" "$(ga young | tr ' ' '\n' | grep '^fires=')"
    check "alarm: a controlled fan is silent"      "fires=0" "$(ga varied | tr ' ' '\n' | grep '^fires=')"
    check "alarm: no tachometer is silent"         "fires=0" "$(ga notacho | tr ' ' '\n' | grep '^fires=')"
    check "alarm: recovers and can re-fire"        "first=1" "$(ga recover | tr ' ' '\n' | grep '^first=')"
    check "alarm: second failure notifies again"   "second=1" "$(ga recover | tr ' ' '\n' | grep '^second=')"

    # Five lines must come out as five DISTINCT shades. The palette is one hue
    # (docs/DESIGN.md 3.1), so these are steps on a brightness ladder rather than
    # different colours — the check is that no two steps collapse together.
    SH=$(v shades "$C")
    N=$(printf '%s' "$SH" | awk -F/ '{print NF}')
    U=$(printf '%s' "$SH" | tr '/' '\n' | sort -u | wc -l)
    check "n5: 5 distinct shades" "$N" "$U"
fi

echo "-- $pass passed, $fail failed"
[ "$fail" -eq 0 ]
