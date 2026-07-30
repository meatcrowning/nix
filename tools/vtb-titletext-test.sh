#!/usr/bin/env bash
# Does the RUNNING hyprvtb honour `TITLETEXT 0`? Pixels, off-screen, no human.
#
# WHY THIS EXISTS
#
# `TITLETEXT <0|1>` (hyprvtb 2.95) is what goetia uses to say "my title region
# carries no text". It is a four-link chain — the app calls
# `VtbClient.set_title_text(False)`, the verb crosses the socket, the plugin
# stores a per-pid flag, and `renderPass` skips the stacked-title branch — and
# THREE of those links have no observable effect except drawn pixels. When it was
# reported still-broken (2026-07-29) the whole hunt was link-by-link source
# reading plus a hand-built sandbox probe, because:
#
#   * `apps/board/tools/board-test.py` covers link 1 only (the app SENDS it).
#   * `ipc_dump()` covers link 3 (the plugin STORED it) — and a stored flag the
#     render path ignores looks identical from there.
#   * link 4 is unobservable through any IPC this plugin has.
#
# A build with no TITLETEXT verb fails the `off` assertion by construction — it
# draws the title in both shots — but that direction has not been run against an
# actual pre-2.95 build, since swapping the live plugin backwards to prove it is
# not worth the session. What IS measured, on one build, is the asymmetry.
#
# So this drives the last two links the only way they can be driven: two real
# client windows on the sandbox monitor, one declaring TITLETEXT 0 and one not,
# and a diff of the bar strip each one is drawn with. It tests the plugin that is
# actually loaded, which is the point — a source read cannot tell you a hot swap
# landed.
#
#   tools/vtb-titletext-test.sh            # PASS/FAIL, artifacts in $OUT
#   OUT=/tmp/x tools/vtb-titletext-test.sh # keep them somewhere else
#
# Needs `goetia` on PATH (its wrapper is reused verbatim for the Qt/PySide6
# environment, so this script hardcodes no store path) plus magick and grim.
# Nothing it opens reaches the user's screen: every window goes onto
# tools/sandbox.sh's headless output and is torn down on exit, including on a
# failure or a Ctrl-C.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=${OUT:-/tmp/vtb-titletext-test}
SANDBOX="$HERE/sandbox.sh"
TITLE=VTBTITLETEXTPROBE
rc=0

say() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*"; rc=1; }

command -v goetia >/dev/null || { say "SKIP: goetia not on PATH (needed for its Qt env)"; exit 0; }
command -v magick >/dev/null || { say "SKIP: magick not on PATH"; exit 0; }

mkdir -p "$OUT" || exit 1
cleanup() { "$SANDBOX" stop >/dev/null 2>&1; }
trap cleanup EXIT INT TERM

# --- link 0: is a TITLETEXT-capable plugin even loaded? -----------------------
VER=$(hyprctl -j plugin list | python3 -c 'import json,sys; p=[x for x in json.load(sys.stdin) if x["name"]=="hyprvtb"]; print(p[0]["version"] if len(p)==1 else "")')
[ -n "$VER" ] || { fail "no single hyprvtb in \`hyprctl plugin list\`"; exit 1; }
say "running hyprvtb $VER"

# --- the probe client, in both flavours ---------------------------------------
# `hyprctl dispatch exec` spawns from the COMPOSITOR's environment, not this
# shell's, so the on/off choice cannot ride in on a variable — it is baked into
# two files. (That is not a detail: an env-var probe silently tested `off`
# twice, and two identical shots read as "the verb is ignored".)
for mode in off on; do
    cat > "$OUT/probe-$mode.py" <<EOF
import sys
sys.path.insert(0, "$HERE/../apps/pylib")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer
from vtbclient import VtbClient

app = QApplication(sys.argv)
w = QWidget()
w.setWindowTitle("$TITLE")     # long enough to fill the title run
w.resize(500, 500)
w.show()
c = VtbClient()
c.set_buttons([("a", "A", 0, ""), ("b", "B", 0, "")])
if "$mode" == "off":
    c.set_title_text(False)
QTimer.singleShot(60000, app.quit)   # never outlive the harness by much
app.exec()
EOF
    # reuse goetia's own wrapper for QT_PLUGIN_PATH/QML paths and its python
    head -n -1 "$(readlink -f "$(command -v goetia)")" > "$OUT/run-$mode.sh"
    PY=$(tail -1 "$(readlink -f "$(command -v goetia)")" | sed -E 's/^exec "([^"]+)".*/\1/')
    printf 'exec "%s" "%s"\n' "$PY" "$OUT/probe-$mode.py" >> "$OUT/run-$mode.sh"
    chmod +x "$OUT/run-$mode.sh"
done

# --- one window at a time, so neither can occlude the other's bar -------------
shoot() { # $1 = off|on -> "WX WY WW WH MX MY" on stdout, shot at $OUT/$1.png
    local mode=$1 geom= mon=
    "$SANDBOX" start >/dev/null 2>&1 || { fail "sandbox start"; return 1; }
    "$SANDBOX" exec "$OUT/run-$mode.sh" >/dev/null 2>&1
    for _ in $(seq 40); do
        sleep 0.25
        geom=$(hyprctl -j clients | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    if c['title'] == '$TITLE':
        print(*c['at'], *c['size']); break
")
        [ -n "$geom" ] && break
    done
    [ -n "$geom" ] || { fail "$mode: probe window never mapped"; return 1; }
    sleep 1.5                        # let the open animation and the bar settle
    "$SANDBOX" shot "$OUT/$mode.png" >/dev/null 2>&1 || { fail "$mode: shot"; return 1; }
    # grim shoots ONE output and the sandbox monitor is not at the origin, so the
    # crop needs its origin — and it must be read while the monitor still exists.
    mon=$(hyprctl -j monitors | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m['name'].startswith('HEADLESS'): print(m['x'], m['y'])
" | tail -1)
    [ -n "$mon" ] || { fail "$mode: no headless monitor geometry"; return 1; }
    printf '%s %s\n' "$geom" "$mon"
    "$SANDBOX" stop >/dev/null 2>&1
}

GOFF=$(shoot off) || exit 1
GON=$(shoot on)   || exit 1
[ "$GOFF" = "$GON" ] || fail "the two probes were placed differently ($GOFF vs $GON) — the crops below are not comparable"

# --- crop the bar strip and diff it -------------------------------------------
# The bar hangs off the window's RIGHT edge. Crop in monitor-local coordinates
# (grim shoots one output, and the sandbox monitor is not at the origin), from
# 8px inside the edge to 62px outside it: two cells plus padding plus a sliver of
# wallpaper, which is identical in both shots and so cancels in the diff.
read -r WX WY WW WH MX MY <<<"$GON"

SX=$((WX - MX + WW - 8))
SY=$((WY - MY))
SW=70
# The title run starts below the window-button group — measured ~150px down with
# five buttons at the default cell size. 200 leaves a margin; 140 is the control
# region, which holds the buttons and must look the SAME in both shots.
CTRL_H=140
TITLE_Y=200
TITLE_H=$((WH - TITLE_Y))

for mode in off on; do
    magick "$OUT/$mode.png" -crop "${SW}x${WH}+${SX}+${SY}" +repage "$OUT/$mode-bar.png" || { fail "crop $mode"; exit 1; }
    magick "$OUT/$mode-bar.png" -crop "${SW}x${CTRL_H}+0+0"          +repage "$OUT/$mode-buttons.png"
    magick "$OUT/$mode-bar.png" -crop "${SW}x${TITLE_H}+0+$TITLE_Y"  +repage "$OUT/$mode-title.png"
done

# "Ink": pixels lighter than the region's own background by a clear margin. An
# absolute count, not a diff, so a PASS says "there is text here" / "there is
# none" rather than only "these two differ somewhere".
ink() { magick "$1" -depth 8 txt:- | python3 -c '
import sys, re, statistics
lum = []
for line in sys.stdin:
    m = re.search(r"#([0-9A-Fa-f]{6})", line)
    if m:
        r, g, b = (int(m.group(1)[i:i+2], 16) for i in (0, 2, 4))
        lum.append(0.299*r + 0.587*g + 0.114*b)
bg = statistics.median(lum)
print(sum(1 for v in lum if v > bg + 18))
'; }

for mode in off on; do
    eval "INK_${mode}_T=$(ink "$OUT/$mode-title.png")"
    eval "INK_${mode}_B=$(ink "$OUT/$mode-buttons.png")"
done
say "ink in the title run:  TITLETEXT 0 -> $INK_off_T px,  default -> $INK_on_T px"
say "ink in the buttons (control): $INK_off_B vs $INK_on_B px  (${SW}x${WH} strip at +${SX}+${SY})"

python3 - "$INK_off_T" "$INK_on_T" "$INK_off_B" "$INK_on_B" <<'EOF' || rc=1
import sys
offT, onT, offB, onB = (int(x) for x in sys.argv[1:5])
ok = True
if onT < 200:
    print(f"FAIL: only {onT}px of ink in the title run WITHOUT the verb — the probe "
          f"never drew a title, so this run proves nothing either way")
    ok = False
if offT > 40:
    print(f"FAIL: {offT}px of ink in the title run WITH `TITLETEXT 0` — the RUNNING "
          f"plugin draws the stacked title anyway, i.e. the verb is not honoured")
    ok = False
if abs(offB - onB) > max(40, 0.25 * max(offB, onB)):
    print(f"FAIL: the buttons differ between shots ({offB} vs {onB}px of ink) — the "
          f"two windows were not laid out alike, so the title numbers are not evidence")
    ok = False
sys.exit(0 if ok else 1)
EOF

[ $rc -eq 0 ] && say "PASS: hyprvtb $VER draws the stacked title only without TITLETEXT 0"
say "artifacts: $OUT"
exit $rc
