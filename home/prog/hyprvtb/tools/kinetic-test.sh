#!/usr/bin/env bash
# hyprvtb kinetic-scroll test — the WET end-to-end run, in a nested Hyprland.
#
# The dry half of the kinetic suite (kinetic_test's trace-only mode) is safe
# anywhere: it drives the estimator, the timer and the integrator and appends
# what it WOULD have sent to a trace instead of sending it. The wet half is
# not, and the reason is structural: CSeatManager::sendPointerAxis ignores any
# surface argument and delivers to whatever m_state.pointerFocusResource is —
# so a wet run in the live session sprays a scroll stream into whatever the
# user's cursor happens to be over. tools/sandbox.sh cannot help: it gives you
# an off-screen MONITOR, not an off-screen pointer focus, and moving the user's
# cursor is exactly what we must not do.
#
# Hence a nested compositor, where we own the cursor and the only client is a
# PySide wheel logger (tools/wheel-log.py) that prints one TSV row per wheel
# event. The plugin refuses a wet injection outright unless that instance has
# been told kinetic_set("unsafe_wet", 1) — there is no automatic nested
# detection, the explicit opt-in IS the safety mechanism — so this script is
# the sanctioned way to run one, and the live session is never told.
#
# What it proves, beyond "nothing crashed":
#   dry  — the decay really is exponential at the configured friction, is
#          monotone, never emits below the 0.10 px floor, ends with exactly one
#          zero (the protocol axis_stop) and withholds it >= 300 ms.
#   wet  — a REAL Qt client sees ScrollBegin ... ScrollUpdate ... ScrollEnd.
#          The ScrollBegin is the load-bearing one: QtWayland opens a phase
#          sequence only for axis_source_finger, so its presence proves the
#          module emitted FINGER and not CONTINUOUS (which is what the
#          savonovv reference plugin gets wrong, and what makes Firefox drop to
#          line-mode wheel jumps).
#
# Skeleton (own HOME, PARENT_WL, instance-diff SIG discovery, hc(),
# kill-by-config-path cleanup, log scan) is nested-smoke.sh's, verbatim — same
# reasons, including the big one: without its own HOME the nested instance
# restores the real saved session and then overwrites the real session.tsv.
#
# Usage: ./kinetic-test.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed.
# Env: KINETIC_PY=/path/to/python3   (a python3 that can import PySide6)
#
# Exits 0 with a SKIP if the plugin predates the kinetic module (2.78) or no
# PySide6 python is available; nonzero on any FAIL.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# Short path on purpose: Hyprland refuses its IPC socket ("Socket2 path is too
# long") well before most people's idea of long.
RUN="/tmp/vtbkin$$"
LOGDIR="$RUN"
mkdir -p "$RUN"
TSV="$RUN/wheel.tsv"
: > "$TSV"

# Acceptance constants. EPS is 0.10 px — 2.4x Qt's 0.042 px drop floor
# (docs/kinetic-scroll.md's emit-epsilon row; the integration design's 0.06 is
# superseded). STOP_MS is the withhold that makes a client-side double fling
# impossible. WET_GAP_MS is STOP_MS minus a client-scheduling allowance: the
# wire-level version of the same assertion is the dry test's, which is exact.
EPS=0.10
STOP_MS=300
WET_GAP_MS=280
FRICTION_FALLBACK=3.6
FRICTION_TOL=0.10   # +/-10 % of -friction
R2_MIN=0.99

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "no WAYLAND_DISPLAY — run this from inside the graphical session (a terminal in the Hyprland/Plasma session), not a bare TTY or an ssh shell."
  exit 1
fi
# The nested compositor is a Wayland client of the current session, so it needs
# the PARENT socket. Absolute path, so overriding XDG_RUNTIME_DIR is not needed
# (and must not happen — the parent socket lives there).
case "$WAYLAND_DISPLAY" in
  /*) PARENT_WL="$WAYLAND_DISPLAY" ;;
  *)  PARENT_WL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/$WAYLAND_DISPLAY" ;;
esac

cleanup() {
  # The wheel logger is a client of the NESTED compositor; its argv carries the
  # (unique) TSV path, so this can never match anything of the user's.
  pkill -9 -f "$TSV" 2>/dev/null
  # Kill by CONFIG PATH, not by $! — the Hyprland launcher hands off to a
  # child, so killing the pid we started leaves the compositor running. The
  # path is unique per run, so this can never touch the live session.
  pkill -9 -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null
  [ -n "${HYPRPID:-}" ] && kill -9 "$HYPRPID" 2>/dev/null
  sleep 0.5
  rm -rf "$RUN"
  # The nested compositor appears to the LIVE session as a window of class
  # "aquamarine", so the live plugin remembers per-class geometry for it when
  # it closes. Drop that entry — it is an artefact of the test, not the desktop.
  G="$HOME/.local/state/hyprvtb/geometry.tsv"
  if [ -f "$G" ] && grep -q '^aquamarine	' "$G"; then
    grep -v '^aquamarine	' "$G" > "$G.tmp" && mv "$G.tmp" "$G"
  fi
}
trap cleanup EXIT

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
note() { printf '   \033[33mnote\033[0m %s\n' "$*"; }
skip() { printf '   \033[33mSKIP\033[0m %s\n' "$*"; }
FAILED=0

# PASS/FAIL/NOTE lines produced by the python assertion blocks, rendered in
# this file's own idiom so a failure sets FAILED like any other.
verdicts() {
  if [ ! -s "$1" ]; then
    bad "the assertion block produced no verdicts (it died before writing $1)"
    return
  fi
  while IFS="$(printf '\t')" read -r v m; do
    case "$v" in
      PASS) ok "$m" ;;
      FAIL) bad "$m" ;;
      *)    note "$m" ;;
    esac
  done < "$1"
}

# ---- the plugin under test --------------------------------------------------

PLUGIN="${1:-$(readlink -f "$HOME/.config/hypr/plugins/libhyprvtb.so")}"
echo "plugin: $PLUGIN"
[ -f "$PLUGIN" ] || { echo "no such plugin: $PLUGIN"; exit 1; }

# ---- pythons ----------------------------------------------------------------
#
# Two different jobs. The assertions are stdlib-only and run OUT here, so any
# python3 does. The wheel logger runs INSIDE the nested compositor and needs
# PySide6 — on book that is Fedora's /usr/bin/python3 (nixpkgs' Qt cannot make
# a GPU context on Apple Silicon; same split as home/prog/viewer.nix), on top
# there is no /usr/bin/python3 at all, so point KINETIC_PY at one.

PY3="$(command -v python3)"
[ -n "$PY3" ] || { echo "no python3 on PATH"; exit 1; }

PYQT=""
for cand in "${KINETIC_PY:-}" /usr/bin/python3 "$PY3"; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  if "$cand" -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then PYQT="$cand"; break; fi
done
if [ -z "$PYQT" ]; then
  skip "no python3 that can import PySide6 (tried \$KINETIC_PY, /usr/bin/python3, $PY3)."
  skip "The wet half needs a real Qt client. Set KINETIC_PY=... and re-run."
  exit 0
fi
echo "wheel-log python: $PYQT"

# ---- a minimal nested config ------------------------------------------------
#
# Lua, like the real session: the plugin only registers its Lua functions when
# the config is not CONFIG_LEGACY, and hyprctl eval is how we drive them.
# disable_logs defaults TRUE and would silence the per-instance log this
# script's abort scan reads.

cat > "$RUN/hyprland.lua" <<LUA
hl.plugin.load("$PLUGIN")
hl.config({
    animations = { enabled = true },
    misc = { disable_hyprland_logo = true, disable_splash_rendering = true },
    debug = { disable_logs = false },
})
LUA

step "starting a nested Hyprland (a window on this session, ~60s)"
BEFORE=$(hyprctl instances -j 2>/dev/null | grep -o '"instance": *"[^"]*"' | cut -d'"' -f4 | sort)
mkdir -p "$RUN/home"
env -u HYPRLAND_INSTANCE_SIGNATURE \
    WAYLAND_DISPLAY="$PARENT_WL" \
    HOME="$RUN/home" \
    Hyprland -c "$RUN/hyprland.lua" >"$LOGDIR/hyprland.log" 2>&1 &
HYPRPID=$!

# The new instance is whichever signature wasn't there a moment ago.
SIG=""
for _ in $(seq 1 60); do
  sleep 0.5
  kill -0 "$HYPRPID" 2>/dev/null || break
  SIG=$(hyprctl instances -j 2>/dev/null | grep -o '"instance": *"[^"]*"' | cut -d'"' -f4 | sort | comm -13 <(echo "$BEFORE") - | head -1)
  [ -n "$SIG" ] && break
done
if [ -z "$SIG" ]; then
  bad "nested Hyprland never came up — log tail:"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi
ok "instance $SIG"

# Every hyprctl below is explicitly aimed at the NESTED instance. Never let one
# of these hit the live session — and note that with a lua config `eval` runs
# arbitrary lua, so an unaimed one is not merely a read.
hc()    { hyprctl -i "$SIG" "$@"; }
ILOG="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr/$SIG/hyprland.log"
alive() { kill -0 "$HYPRPID" 2>/dev/null && hc version >/dev/null 2>&1; }

# hyprctl eval hands back whatever the chunk produced, but whether it needs an
# explicit `return` is a build detail. Try bare, then `return`-prefixed, and
# keep whichever answered without an error.
heval() {
  local out alt
  out="$(hc eval "$1" 2>&1)"
  if [ -z "${out//[[:space:]]/}" ] || printf '%s' "$out" | grep -qi 'error'; then
    alt="$(hc eval "return $1" 2>&1)"
    if [ -n "${alt//[[:space:]]/}" ] && ! printf '%s' "$alt" | grep -qi 'error'; then
      printf '%s' "$alt"; return
    fi
  fi
  printf '%s' "$out"
}
kin()   { hc eval "hl.plugin.hyprvtb.$1" >/dev/null 2>&1; }   # fire and forget
kdump() { heval "hl.plugin.hyprvtb.kinetic_dump()"; }

step "plugin loaded?"
if hc plugin list | grep -q hyprvtb; then
  ok "$(hc plugin list | grep -i version | head -1 | tr -d '\t')"
else
  bad "hyprvtb is not in the nested compositor's plugin list"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi

step "does this build have the kinetic module? (2.78+)"
PROBE="$(heval "tostring(((hl.plugin or {}).hyprvtb or {}).kinetic_test)")"
KINETIC=0
case "$PROBE" in
  *function*) KINETIC=1 ;;
  *nil*)      KINETIC=0 ;;
  *)
    # The eval return channel told us nothing; ask behaviourally instead.
    if hc eval "hl.plugin.hyprvtb.kinetic_get()" 2>&1 | grep -qiE 'nil value|not a function|error'; then
      KINETIC=0
    else
      KINETIC=1
    fi
    ;;
esac
if [ "$KINETIC" = 0 ]; then
  skip "this .so has no kinetic_* lua functions — pre-2.78 build, nothing to test."
  hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
  exit 0
fi
ok "kinetic_* lua functions are present"

# ---- the client -------------------------------------------------------------

step "launching the wheel logger inside the nested compositor"
# hl.exec_cmd is the Lua spawn entry point (there is no hl.dsp.exec), and it
# has to go through `eval` — `dispatch` wants a dispatcher object back.
# QT_QPA_PLATFORM=wayland: DISPLAY is set in here too (the nested XWayland), and
# an XWayland client would be denied momentum by kinetic_deny_xwayland anyway.
hc eval "hl.exec_cmd('env QT_QPA_PLATFORM=wayland $PYQT $HERE/wheel-log.py $TSV')" >/dev/null
WIN=""
for _ in $(seq 1 60); do
  sleep 0.5
  WIN=$(hc clients -j | jq -r '.[]|select(.mapped and (.class=="wheel-log" or .title=="wheel-log"))|.address' | head -1)
  [ -n "$WIN" ] && break
done
if [ -z "$WIN" ]; then
  bad "the wheel logger never mapped — everything below would be vacuous"
  tail -20 "$LOGDIR/hyprland.log"
  exit 1
fi
ok "wheel-log window $WIN"

step "putting the NESTED cursor over it (pointer focus is what momentum follows)"
# Deliberately no float/fullscreen: a tiled single window already fills the
# workspace, and the geometry hyprctl reports is what we aim at either way.
read -r CX CY <<EOF
$(hc clients -j | jq -r --arg a "$WIN" '.[]|select(.address==$a)|"\(.at[0] + (.size[0]/2|floor)) \(.at[1] + (.size[1]/2|floor))"')
EOF
if [ -z "${CX:-}" ] || [ -z "${CY:-}" ]; then
  bad "could not read the window geometry"
  exit 1
fi
# This config is Lua: `hyprctl dispatch <name>` evaluates its argument AS LUA,
# so a bare dispatcher name is a nil global and silently does nothing. The
# cursor warp is hl.cursor.move({x,y}) — an immediate lua fn, so `eval`. Try
# the dispatch spelling too, and VERIFY with cursorpos rather than trusting
# either: the whole test rests on pointer focus being on this window.
cursor_at() { # $1 x, $2 y — is the NESTED cursor within 2 px of there?
  local p x y dx dy
  p="$(hc cursorpos 2>/dev/null | tr -d ' ')"
  x="${p%%,*}"; y="${p##*,}"
  case "$x$y" in ''|*[!0-9-]*) return 1 ;; esac
  dx=$(( x - $1 )); dy=$(( y - $2 ))
  [ "${dx#-}" -le 2 ] && [ "${dy#-}" -le 2 ]
}
WARPED=0
for form in "hl.cursor.move({ x = $CX, y = $CY })" "hl.dsp.cursor.move({ x = $CX, y = $CY })" "hl.cursor.move($CX, $CY)"; do
  hc eval "$form" >/dev/null 2>&1
  cursor_at "$CX" "$CY" && { WARPED=1; ok "cursor at $CX,$CY via eval \"$form\""; break; }
  hc dispatch "$form" >/dev/null 2>&1
  cursor_at "$CX" "$CY" && { WARPED=1; ok "cursor at $CX,$CY via dispatch \"$form\""; break; }
done
if [ "$WARPED" = 0 ]; then
  # Not fatal by itself: a fresh nested compositor parks the cursor in the
  # middle of its only monitor, which a single tiled window covers. Say so and
  # let the wet assertions decide.
  note "no cursor-warp spelling took ($(hc cursorpos 2>/dev/null)) — relying on the"
  note "     default centre-of-monitor cursor position instead"
fi

step "opting in to wet injection"
# A wet kinetic_test is REFUSED unless the instance has been told
# kinetic_set("unsafe_wet", 1). There is no automatic nested detection: the
# explicit opt-in IS the safety mechanism, and it is only ever safe here
# because this compositor is a nested one we own, whose single client is the
# wheel logger. Never send this to the live session — sendPointerAxis has no
# surface argument, so momentum lands on whatever the user's cursor is over.
kin "kinetic_set(true)"
kin "kinetic_set(\"unsafe_wet\", 1)"
ok "kinetic enabled and wet injection opted in for instance $SIG only"

# ---- helpers over the trace / the TSV ---------------------------------------

cat > "$RUN/trace-done.py" <<'PY'
# exit 0 once kinetic_dump()'s trace ends in a 0.0 delta (the protocol stop)
import json, re, sys
raw = open(sys.argv[1]).read()
m = re.search(r"\{.*\}", raw, re.S)
if not m:
    sys.exit(1)
try:
    tr = json.loads(m.group(0)).get("trace") or []
except Exception:
    sys.exit(1)
sys.exit(0 if tr and float(tr[-1][1]) == 0.0 else 1)
PY

rows() { local n; { n="$(wc -l < "$TSV" | tr -d ' ')"; } 2>/dev/null; echo "${n:-0}"; }

kin_run() { # $1 = full lua arg list for kinetic_test; runs it and waits it out
  kin "kinetic_test($1)"
  # A fling is capped by kinetic_max_duration_ms (2000) and the stop is
  # withheld kinetic_stop_delay_ms (300) after it, so 4 s covers the whole
  # thing. The fixed wait also removes the only race here: if kinetic_test does
  # NOT reset the trace, a poll alone would return on the PREVIOUS run's stop.
  sleep 4
  for _ in $(seq 1 32); do
    kdump > "$RUN/dump.json"
    "$PY3" "$RUN/trace-done.py" "$RUN/dump.json" && return 0
    sleep 0.25
  done
  return 1
}

# ---- (a1 §8) refusal paths, first: nothing has ever been emitted yet, so an
# empty trace here is meaningful whatever kinetic_test's reset semantics are.

step "refusal: kinetic disabled (a1 criterion 8)"
kin "kinetic_set(false)"
kin "kinetic_test(40, 8, 12, false)"
sleep 1
kdump > "$RUN/dump-off.json"
if "$PY3" - "$RUN/dump-off.json" <<'PY'
import json, re, sys
m = re.search(r"\{.*\}", open(sys.argv[1]).read(), re.S)
sys.exit(0 if m and not (json.loads(m.group(0)).get("trace") or []) else 1)
PY
then ok "empty trace with kinetic disabled"
else bad "kinetic_set(false) did not refuse the injection — dump: $(cat "$RUN/dump-off.json")"
fi
alive && ok "compositor alive" || { bad "compositor died on the disabled-path injection"; exit 1; }

step "refusal: velocity below the start floor (a1 criterion 8)"
kin "kinetic_set(true)"
kin "kinetic_test(1, 2, 12, false)"    # ~83 px/s, under kinetic_min_start_velocity 200
sleep 1
kdump > "$RUN/dump-slow.json"
if "$PY3" - "$RUN/dump-slow.json" <<'PY'
import json, re, sys
m = re.search(r"\{.*\}", open(sys.argv[1]).read(), re.S)
sys.exit(0 if m and not (json.loads(m.group(0)).get("trace") or []) else 1)
PY
then ok "empty trace for a sub-threshold flick"
else bad "a sub-threshold flick started a fling — dump: $(cat "$RUN/dump-slow.json")"
fi
if [ "$(rows)" = 0 ]; then
  ok "the client has seen nothing so far (both refusals were silent on the wire)"
else
  bad "$(rows) wheel events reached the client from a REFUSED injection"
fi

# ---- calibrate the 4th argument ---------------------------------------------

step "calibrating kinetic_test's 4th argument (wet vs dry polarity)"
# docs/kinetic-scroll.md's lua API calls the slot `wet` (true = emit for real);
# the integration design's recipe calls the same slot `dry` (true = trace
# only). Both spellings are in the tree, and getting it backwards would either
# make the dry assertions vacuous or spray scroll unexpectedly. So: ask.
# Safe to ask here — the only client is ours, and the compositor is nested.
WETARG=true
DRYARG=false
CAL_BASE=$(rows)
# Re-assert the opt-in: the refusal step above ran kinetic_set(false), and
# whether that also clears unsafe_wet is not something to depend on. Idempotent.
kin "kinetic_set(\"unsafe_wet\", 1)"
kin_run "40, 8, 12, $DRYARG" || note "the calibration fling never terminated in ~12s"
sleep 0.5
if [ "$(rows)" -gt "$CAL_BASE" ]; then
  WETARG=false
  DRYARG=true
  note "4th arg is DRY (true = trace only): the client saw rows with it false"
else
  ok "4th arg is WET (true = emit for real), as docs/kinetic-scroll.md specifies"
fi
alive && ok "compositor alive" || { bad "compositor died during calibration"; exit 1; }

# ---- (a1) the dry run --------------------------------------------------------

step "DRY injection: kinetic_test(40, 8, 12, $DRYARG)"
DRY_BASE=$(rows)
if kin_run "40, 8, 12, $DRYARG"; then
  ok "the trace terminated"
else
  bad "the dry trace never ended in a 0.0 entry (12s) — dump: $(head -c 400 "$RUN/dump.json")"
fi
cp "$RUN/dump.json" "$RUN/dump-dry.json" 2>/dev/null
if [ "$(rows)" = "$DRY_BASE" ]; then
  ok "the dry run touched no client (no new wheel events)"
else
  bad "the dry run emitted for real: $(( $(rows) - DRY_BASE )) wheel events reached the client"
fi
alive && ok "compositor alive" || { bad "compositor died during the dry injection"; exit 1; }
note "kinetic_stats: $(heval "hl.plugin.hyprvtb.kinetic_stats()" | tr '\n' ' ')"

step "DRY acceptance criteria"
"$PY3" - "$RUN/dump-dry.json" "$FRICTION_FALLBACK" "$EPS" "$STOP_MS" "$FRICTION_TOL" "$R2_MIN" "$RUN/v-dry" <<'PY'
import json, math, re, sys

dumpf, k_fallback, eps, stop_ms, tol, r2min, outf = sys.argv[1:8]
k_fallback, eps, stop_ms, tol, r2min = map(float, (k_fallback, eps, stop_ms, tol, r2min))
out = open(outf, "w")
def v(tag, msg): out.write("%s\t%s\n" % (tag, msg))

raw = open(dumpf).read()
m = re.search(r"\{.*\}", raw, re.S)
if not m:
    v("FAIL", "kinetic_dump() returned no JSON object: %r" % raw[:200].strip())
    out.close(); sys.exit(0)
try:
    d = json.loads(m.group(0))
except Exception as e:
    v("FAIL", "kinetic_dump() JSON did not parse (%s): %r" % (e, m.group(0)[:200]))
    out.close(); sys.exit(0)

trace = [(float(t), float(dl)) for t, dl in (d.get("trace") or [])]
state = d.get("state", "?")
try:
    k = float(d.get("friction", k_fallback))
except (TypeError, ValueError):
    k = k_fallback
v("NOTE", "state=%s friction=%g entries=%d" % (state, k, len(trace)))

# 1. the estimator produced a launch velocity from the 8-event / 96 ms burst
if len(trace) >= 10:
    v("PASS", "trace has %d entries (>= 10)" % len(trace))
else:
    v("FAIL", "trace has %d entries (want >= 10) — the estimator produced no fling" % len(trace))

nz = [(t, dl) for t, dl in trace if dl != 0.0]
zeros = [i for i, (_t, dl) in enumerate(trace) if dl == 0.0]

# 2. exponential decay: ln|delta| vs t is a straight line of slope -k
if len(nz) >= 3:
    xs = [t / 1000.0 for t, _ in nz]
    ys = [math.log(abs(dl)) for _, dl in nz]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else float("nan")
    inter = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + inter)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    want = -k
    dev = abs(slope - want) / abs(want) if want else float("inf")
    if dev <= tol:
        v("PASS", "decay slope %.3f /s vs -friction %.3f (%.1f%% off, <= %.0f%%)" % (slope, want, dev * 100, tol * 100))
    else:
        v("FAIL", "decay slope %.3f /s vs -friction %.3f (%.1f%% off, want <= %.0f%%)" % (slope, want, dev * 100, tol * 100))
    if r2 >= r2min:
        v("PASS", "fit R2 %.5f (>= %.2f) — the curve really is exponential" % (r2, r2min))
    else:
        v("FAIL", "fit R2 %.5f (want >= %.2f) — the decay is not exponential" % (r2, r2min))
else:
    v("FAIL", "only %d non-zero entries — cannot fit a decay curve" % len(nz))

# 3. monotone magnitude: no re-acceleration, no jitter
mags = [abs(dl) for _, dl in nz]
rise = [(i, mags[i], mags[i + 1]) for i in range(len(mags) - 1) if mags[i + 1] > mags[i]]
if not rise:
    v("PASS", "|delta| is monotone non-increasing over %d entries" % len(mags))
else:
    v("FAIL", "|delta| rises %d time(s), first at index %d: %.4f -> %.4f" % (len(rise), rise[0][0], rise[0][1], rise[0][2]))

# 4. sub-pixel floor: nothing below the emit epsilon ever goes on the wire
low = [(t, dl) for t, dl in nz if abs(dl) < eps - 1e-9]
if not low:
    v("PASS", "every non-terminal |delta| >= %.2f px (min %.4f)" % (eps, min(mags) if mags else float("nan")))
else:
    v("FAIL", "%d non-terminal deltas below the %.2f px floor, smallest %.4f at t=%.1f ms"
      % (len(low), eps, min(abs(dl) for _, dl in low), low[0][0]))

# 5. terminates with exactly one zero, and it is last
if len(zeros) == 1 and zeros[0] == len(trace) - 1:
    v("PASS", "exactly one 0.0 entry and it is last (the axis_stop)")
elif not zeros:
    v("FAIL", "no 0.0 entry at all — the sequence was never closed")
else:
    v("FAIL", "%d zero entries at indices %s (want exactly one, last of %d)" % (len(zeros), zeros, len(trace)))

# 6. the stop is withheld, so every client-side estimator computes zero velocity
if zeros and nz:
    gap = trace[zeros[-1]][0] - nz[-1][0]
    if gap >= stop_ms:
        v("PASS", "stop withheld %.0f ms after the last delta (>= %.0f)" % (gap, stop_ms))
    else:
        v("FAIL", "stop came %.0f ms after the last delta (want >= %.0f) — clients can re-fling" % (gap, stop_ms))

# informational: sign is carried, not re-derived
if nz:
    signs = set(1 if dl > 0 else -1 for _, dl in nz)
    v("NOTE" if len(signs) == 1 else "FAIL",
      "sign %s across the tail" % ("consistent" if len(signs) == 1 else "FLIPS"))
    v("NOTE", "first %.3f px, last %.3f px, span %.0f ms" % (nz[0][1], nz[-1][1], nz[-1][0] - nz[0][0]))
out.close()
PY
verdicts "$RUN/v-dry"

# ---- (a2) the wet run --------------------------------------------------------

step "WET injection: kinetic_test(40, 8, 12, $WETARG) — into a real Qt client"
WET_BASE=$(rows)
kin "kinetic_set(\"unsafe_wet\", 1)"   # idempotent; without it the wet call is refused
kin "kinetic_test(40, 8, 12, $WETARG)"
# Poll the CLIENT, not the trace: the TSV is the oracle here, and if
# kinetic_test does not reset the trace, its terminal 0.0 is already there.
for _ in $(seq 1 60); do
  sleep 0.25
  LAST=$(tail -n +$((WET_BASE + 1)) "$TSV" 2>/dev/null | tail -1 | cut -f6)
  [ "$LAST" = "ScrollEnd" ] && break
done
tail -n +$((WET_BASE + 1)) "$TSV" > "$RUN/wet.tsv" 2>/dev/null
ok "$(wc -l < "$RUN/wet.tsv" | tr -d ' ') wheel events reached the client"
alive && ok "compositor alive" || { bad "compositor died during the wet injection"; exit 1; }
note "kinetic_stats: $(heval "hl.plugin.hyprvtb.kinetic_stats()" | tr '\n' ' ')"

step "WET acceptance criteria"
"$PY3" - "$RUN/wet.tsv" "$WET_GAP_MS" "$RUN/v-wet" <<'PY'
import sys

tsvf, gap_ms, outf = sys.argv[1], float(sys.argv[2]), sys.argv[3]
out = open(outf, "w")
def v(tag, msg): out.write("%s\t%s\n" % (tag, msg))

rows = []
for line in open(tsvf):
    f = line.rstrip("\n").split("\t")
    if len(f) != 7:
        continue
    rows.append(dict(t=float(f[0]), px=int(f[1]), py=int(f[2]),
                     ax=int(f[3]), ay=int(f[4]), phase=f[5], inv=int(f[6])))

# 1. rows arrive at all => seat-level injection reaches a real Qt client
if rows:
    v("PASS", "%d wheel events arrived at the Qt client" % len(rows))
else:
    v("FAIL", "the client received NO wheel events — the wet injection never reached a surface")
    out.close(); sys.exit(0)

v("NOTE", "phases: " + " ".join("%s x%d" % (p, sum(1 for r in rows if r["phase"] == p))
                                for p in dict.fromkeys(r["phase"] for r in rows)))

# 2. ScrollBegin first => the module emitted FINGER, not CONTINUOUS
if rows[0]["phase"] == "ScrollBegin":
    v("PASS", "first row is ScrollBegin — Qt opened a phase sequence, so the source was FINGER")
else:
    v("FAIL", "first row is %s, not ScrollBegin — Qt opens a phase only for axis_source_finger, "
              "so the module emitted the wrong source" % rows[0]["phase"])

# 3. exactly one ScrollEnd, and it is last
ends = [i for i, r in enumerate(rows) if r["phase"] == "ScrollEnd"]
if len(ends) == 1 and ends[0] == len(rows) - 1:
    v("PASS", "exactly one ScrollEnd and it is the last row")
elif not ends:
    v("FAIL", "no ScrollEnd — the client is still mid-sequence, it believes scroll is in progress")
else:
    v("FAIL", "%d ScrollEnd rows at %s (want exactly one, last of %d)" % (len(ends), ends, len(rows)))

pre = rows[:ends[0]] if ends else rows
ups = [r for r in pre if r["phase"] in ("ScrollBegin", "ScrollUpdate", "ScrollMomentum")]

# 4. non-increasing |pixelDelta.y| across the update rows (ties allowed)
mags = [abs(r["py"]) for r in ups]
rise = [(i, mags[i], mags[i + 1]) for i in range(len(mags) - 1) if mags[i + 1] > mags[i]]
if not rise:
    v("PASS", "|pixelDelta.y| non-increasing across %d update rows" % len(mags))
else:
    v("FAIL", "|pixelDelta.y| rises %d time(s), first at row %d: %d -> %d"
      % (len(rise), rise[0][0], rise[0][1], rise[0][2]))
amags = [abs(r["ay"]) for r in ups]
arise = sum(1 for i in range(len(amags) - 1) if amags[i + 1] > amags[i])
v("NOTE", "|angleDelta.y| rises %d time(s) (the x12 quantisation is finer)" % arise)

# 5. no zero-delta row before the End. Split by what a zero MEANS: a row with
#    both deltas zero is a wire zero (== the protocol axis_stop, arriving
#    mid-flight); a row whose pixelDelta rounded to 0 while angleDelta survived
#    is Qt's integer QPoint truncating a sub-pixel tail delta, which the wire
#    cannot express and the dry test's >= 0.10 px assertion covers exactly.
wire0 = [i for i, r in enumerate(pre) if r["py"] == 0 and r["ay"] == 0]
round0 = [i for i, r in enumerate(pre) if r["py"] == 0 and r["ay"] != 0]
if not wire0:
    v("PASS", "no zero-delta row before the ScrollEnd")
else:
    v("FAIL", "%d row(s) with pixelDelta.y == 0 AND angleDelta.y == 0 before the End "
              "(first at row %d) — a zero on the wire IS the axis_stop" % (len(wire0), wire0[0]))
if round0:
    v("NOTE", "%d row(s) have pixelDelta.y == 0 with angleDelta.y != 0 (first at row %d, "
              "angleDelta %d): Qt's pixelDelta is an integer QPoint, so a sub-pixel tail "
              "delta rounds away there while the wire value was non-zero"
      % (len(round0), round0[0], pre[round0[0]]["ay"]))

# 6. the stop is withheld long enough that no client can re-fling
if ends and ups:
    gap = rows[ends[0]]["t"] - ups[-1]["t"]
    if gap >= gap_ms:
        v("PASS", "%.0f ms between the last update and the ScrollEnd (>= %.0f)" % (gap, gap_ms))
    else:
        v("FAIL", "only %.0f ms between the last update and the ScrollEnd (want >= %.0f)" % (gap, gap_ms))

inv = set(r["inv"] for r in rows)
v("NOTE", "inverted flag(s) seen: %s; first pixelDelta.y %d, last update %d"
  % (sorted(inv), rows[0]["py"], ups[-1]["py"] if ups else 0))
PY
verdicts "$RUN/v-wet"

# ---- (a1 §7) the plugin is still whole --------------------------------------

step "plugin state after the run"
kin "kinetic_cancel()"
kin "kinetic_set(false)"
INSTANCES=$(hc plugin list | grep -c 'hyprvtb by')
if [ "$INSTANCES" = 1 ]; then
  ok "exactly one hyprvtb instance"
else
  bad "$INSTANCES hyprvtb instances (want 1)"
fi
if [ -z "$(hc configerrors 2>/dev/null | tr -d '[:space:]')" ]; then
  ok "no config errors"
else
  bad "config errors after the run: $(hc configerrors)"
fi

step "log check"
if grep -qiE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|has crashed|safe mode' "$LOGDIR/hyprland.log" "$ILOG" 2>/dev/null; then
  bad "the nested log has an abort/assert:"
  grep -inhE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|has crashed|safe mode' "$LOGDIR/hyprland.log" "$ILOG" 2>/dev/null | head
else
  ok "no aborts, asserts or safe-mode entries"
fi

step "shutting the nested session down"
hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
sleep 1

if [ "$FAILED" = 0 ]; then
  printf '\n\033[32mKINETIC TEST PASSED\033[0m — decay, floor, stop withholding and the client-visible\nFINGER phase sequence all hold.\n'
else
  printf '\n\033[31mKINETIC TEST FAILED\033[0m — logs kept at /tmp/hyprvtb-kinetic.log, TSV at /tmp/hyprvtb-wheel.tsv\n'
  cp "$LOGDIR/hyprland.log" /tmp/hyprvtb-kinetic.log 2>/dev/null
  cat "$ILOG" >> /tmp/hyprvtb-kinetic.log 2>/dev/null
  cp "$TSV" /tmp/hyprvtb-wheel.tsv 2>/dev/null
fi
exit "$FAILED"
