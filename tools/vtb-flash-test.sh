#!/usr/bin/env bash
# Does the RUNNING hyprvtb draw the inner column's FOOTER text cold? Pixels,
# off-screen, no human.
#
# WHY THIS EXISTS
#
# `mainThreadTick` pre-uploads the app-button GLYPH textures off the render pass
# (`prewarmGlyphs`) precisely so a redraw never creates and samples a texture
# inside one tiler job — that is the flash-blank, and it is why that function
# exists at all. It walks `reg.buttons` and nothing else. The FOOTER is stacked
# text built by `renderStackedTex` **inside `renderBar`**, on the render thread,
# on the first frame after the string changes, and so is the stacked title. So
# the one text the inner column actually carries is on the cold path the button
# labels were taken off.
#
# That is a claim about a single frame, and no IPC in this plugin can see it:
# `ipc_dump()` shows the footer STORED, and a footer drawn blank for one frame
# looks identical from there. Hence pixels.
#
# THE EXPERIMENT: one probe window on the sandbox monitor, shot repeatedly,
# in two modes that differ ONLY in whether the footer string keeps changing.
#
#   still    the footer is set once and never changes -> every frame samples a
#            texture built on some earlier frame. This is the control.
#   vary     the footer alternates between "A" and "AAAAAAAA" -> the SELF-CHECK.
#            Its ink must swing, or the probe is not repainting at all and the
#            constant ink of the third mode means nothing. A harness that can
#            pass by testing nothing is worse than none.
#   churn    the footer alternates between two strings with the SAME glyph
#            multiset ("ABAB"/"BABA") every 16ms, so every repaint misses the
#            one-slot cache and builds its texture in the render pass. Ink must
#            not change: same glyphs, same count, same column.
#
# Ink in the footer strip that COLLAPSES in `churn` is the flash, measured. Ink
# that holds is this theory refuted — say so and stop, do not "fix" it anyway.
#
# SENSITIVITY, stated so a PASS is not read as more than it is: the bar repaints
# when `mainThreadTick` advances its snapshot (~150ms), and a cold-drawn frame
# would be blank for one frame (~16ms) of each of those. So one shot catches a
# per-repaint blank with probability ~1/9 — 12 shots is ~75% power, 30 is ~97%.
# Raise SHOTS if you need to state it strongly. Measured on hyprvtb 2.97, top:
# 12/12 shots at exactly 156px in both modes, i.e. no blank frame observed.
#
#   tools/vtb-flash-test.sh              # PASS/FAIL, artifacts in $OUT
#   SHOTS=30 tools/vtb-flash-test.sh     # more samples per mode (default 14)
#
# Needs `goetia` on PATH (its wrapper is reused verbatim for the Qt/PySide6
# environment, so nothing here hardcodes a store path), magick and grim. Every
# window goes onto tools/sandbox.sh's headless output and is torn down on exit,
# including on a failure or a Ctrl-C. Sibling harness, same shape, read it first:
# tools/vtb-titletext-test.sh.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=${OUT:-/tmp/vtb-flash-test}
SHOTS=${SHOTS:-14}
SANDBOX="$HERE/sandbox.sh"
TITLE=VTBFLASHPROBE
rc=0

say() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*"; rc=1; }

command -v goetia >/dev/null || { say "SKIP: goetia not on PATH (needed for its Qt env)"; exit 0; }
command -v magick >/dev/null || { say "SKIP: magick not on PATH"; exit 0; }
command -v grim   >/dev/null || { say "SKIP: grim not on PATH"; exit 0; }

mkdir -p "$OUT" || exit 1
cleanup() { "$SANDBOX" stop >/dev/null 2>&1; }
trap cleanup EXIT INT TERM

VER=$(hyprctl -j plugin list | python3 -c 'import json,sys; p=[x for x in json.load(sys.stdin) if x["name"]=="hyprvtb"]; print(p[0]["version"] if len(p)==1 else "")')
[ -n "$VER" ] || { fail "no single hyprvtb in \`hyprctl plugin list\`"; exit 1; }
say "running hyprvtb $VER"

# --- the probe client, in both modes ------------------------------------------
# Two files, not one env var: `hyprctl dispatch exec` spawns from the
# COMPOSITOR's environment, so a variable set here never reaches the child and
# both runs would silently be the same mode (the trap tools/vtb-titletext-test.sh
# already paid for).
for mode in still vary churn; do
    cat > "$OUT/probe-$mode.py" <<EOF
import sys
sys.path.insert(0, "$HERE/../apps/pylib")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer
from vtbclient import VtbClient

app = QApplication(sys.argv)
w = QWidget()
w.setWindowTitle("$TITLE")
w.resize(500, 700)
w.show()
c = VtbClient()
c.set_buttons([("a", "A", 0, ""), ("b", "B", 0, "")])
c.set_footer("ABAB")

if "$mode" != "still":
    # churn: same glyph multiset either way, so the ink is a constant and any
    # change in it is the plugin's, not the string's.
    # vary: deliberately different lengths — the self-check that the footer is
    # reaching the bar at all.
    pair = ("ABAB", "BABA") if "$mode" == "churn" else ("A", "AAAAAAAA")
    state = {"n": 0}
    def flip():
        state["n"] += 1
        c.set_footer(pair[state["n"] % 2])
    t = QTimer(); t.timeout.connect(flip); t.start(16 if "$mode" == "churn" else 120)

QTimer.singleShot(120000, app.quit)
app.exec()
EOF
    head -n -1 "$(readlink -f "$(command -v goetia)")" > "$OUT/run-$mode.sh"
    PY=$(tail -1 "$(readlink -f "$(command -v goetia)")" | sed -E 's/^exec "([^"]+)".*/\1/')
    printf 'exec "%s" "%s"\n' "$PY" "$OUT/probe-$mode.py" >> "$OUT/run-$mode.sh"
    chmod +x "$OUT/run-$mode.sh"
done

# --- ink: pixels clearly lighter than the region's own background -------------
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

# --- one mode: launch, shoot $SHOTS times, print the ink of each shot ---------
run_mode() { # $1 = still|churn -> one ink count per line on stdout
    local mode=$1 geom= mon= i=0
    "$SANDBOX" start >/dev/null 2>&1 || { fail "sandbox start"; return 1; }
    # `exec` now verifies the window landed off-screen and fails if it did not,
    # so its exit status is load-bearing — swallowing it used to mean the run
    # carried on with a probe window sitting on the user's real monitor.
    "$SANDBOX" exec "$OUT/run-$mode.sh" \
      || { fail "$mode: sandbox exec refused the launch (see above) — not retrying"; return 1; }
    for _ in $(seq 40); do
        sleep 0.25
        geom=$(hyprctl -j clients | python3 -c "
import json,sys
for c in json.load(sys.stdin):
    # tagged AND titled: the tag is what says it is ours rather than a window of
    # his that happens to share a title, so the geometry below is never his.
    if c['title'] == '$TITLE' and 'sandbox' in [t.rstrip('*') for t in c.get('tags') or []]:
        print(*c['at'], *c['size']); break
")
        [ -n "$geom" ] && break
    done
    [ -n "$geom" ] || { fail "$mode: probe window never mapped"; return 1; }
    sleep 1.5                       # let the open animation and the bar settle
    mon=$(hyprctl -j monitors | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m['name'].startswith('HEADLESS'): print(m['x'], m['y'])
" | tail -1)
    [ -n "$mon" ] || { fail "$mode: no headless monitor geometry"; return 1; }
    read -r WX WY WW WH MX MY <<<"$geom $mon"
    # The bar hangs off the window's RIGHT edge, two columns of bar_width. The
    # INNER column is the left one and the footer is bottom-anchored in it, so
    # crop one column wide from the window's right edge and the bottom 120px.
    local CW SX SY SH
    CW=$(hyprctl getoption plugin:hyprvtb:bar_width | sed -n 's/^int: //p')
    SX=$((WX - MX + WW))
    SH=120
    SY=$((WY - MY + WH - SH - 4))
    printf '%s %s %s %s\n' "$SX" "$SY" "$CW" "$SH" > "$OUT/$mode-crop.txt"
    while [ $i -lt "$SHOTS" ]; do
        "$SANDBOX" shot "$OUT/$mode-$i.png" >/dev/null 2>&1 || { fail "$mode: shot"; return 1; }
        magick "$OUT/$mode-$i.png" -crop "${CW}x${SH}+${SX}+${SY}" +repage "$OUT/$mode-$i-footer.png" || { fail "crop"; return 1; }
        ink "$OUT/$mode-$i-footer.png"
        i=$((i + 1))
    done
    "$SANDBOX" stop >/dev/null 2>&1
}

STILL=$(run_mode still) || exit 1
VARY=$(run_mode vary)   || exit 1
CHURN=$(run_mode churn) || exit 1

say "footer ink per shot, still: $(echo "$STILL" | tr '\n' ' ')"
say "footer ink per shot, vary : $(echo "$VARY"  | tr '\n' ' ')   (self-check: must swing)"
say "footer ink per shot, churn: $(echo "$CHURN" | tr '\n' ' ')"

python3 - "$OUT" <<EOF || rc=1
import statistics, sys
still = [int(x) for x in """$STILL""".split()]
vary  = [int(x) for x in """$VARY""".split()]
churn = [int(x) for x in """$CHURN""".split()]
if not vary or min(vary) > 0.5 * max(vary):
    print(f"FAIL: the self-check never swung ({vary}) — a footer whose LENGTH changes "
          f"did not change the pixels, so the probe is not reaching the bar and the "
          f"churn numbers below would prove nothing")
    sys.exit(1)
if not still or not churn:
    print("FAIL: no samples"); sys.exit(1)
ms, mc = statistics.median(still), statistics.median(churn)
print(f"median ink  still={ms}  churn={mc}   blank shots: "
      f"still={sum(1 for v in still if v < ms*0.3)}/{len(still)} "
      f"churn={sum(1 for v in churn if v < ms*0.3)}/{len(churn)}")
if ms < 30:
    print("FAIL: the control drew almost no footer ink either — the probe never "
          "showed a footer, so this run proves nothing in either direction")
    sys.exit(1)
blank = sum(1 for v in churn if v < ms * 0.3)
if blank:
    print(f"FAIL: {blank} of {len(churn)} churn shots lost the footer text that the "
          f"control draws every time — the footer texture is being built inside the "
          f"render pass (the flash). Prewarm it off the pass, like prewarmGlyphs "
          f"does for the button labels.")
    sys.exit(1)
print("PASS: the footer holds its ink even when its string changes every frame")
EOF

say "artifacts: $OUT"
exit $rc
