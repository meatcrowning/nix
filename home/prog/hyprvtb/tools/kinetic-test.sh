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
# been told kinetic_set("unsafe_wet", 1) — there is no environment sniffing,
# the explicit opt-in IS the safety mechanism (vtbKinetic.cpp:1113) — so this
# script is the sanctioned way to run one, and the live session is never told.
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
# NOTHING here needs the nested compositor to RENDER. The engine is
# CEventLoopTimer-driven, not frame-driven, and wheel delivery needs a mapped
# surface with pointer focus, not a frame callback — which is why this suite
# still works in the environment that starves nested-smoke's animation
# assertions (nested window on a headless sandbox output, host at vfr).
#
# Skeleton (own HOME, PARENT_WL, instance-diff SIG discovery, hc(),
# kill-by-config-path cleanup, log scan) is nested-smoke.sh's, verbatim — same
# reasons, including the big one: without its own HOME the nested instance
# restores the real saved session and then overwrites the real session.tsv.
# Here that HOME is load-bearing twice over: it is also where the plugin
# publishes the introspection blobs this script reads.
#
# Usage: ./kinetic-test.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed.
# Env: KINETIC_PY=/path/to/python3   (a python3 that can import PySide6)
#
# Exits 0 with a SKIP if the plugin predates the kinetic module or no PySide6
# python is available; nonzero on any FAIL.

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
# superseded, and vtbKinetic.hpp:156 KIN_EMIT_EPS is 0.10). STOP_MS is the
# withhold that makes a client-side double fling impossible. WET_GAP_MS is
# STOP_MS minus a client-scheduling allowance: the wire-level version of the
# same assertion is the dry test's, which is exact.
EPS=0.10
STOP_MS=300
WET_GAP_MS=280
FRICTION_FALLBACK=3.6
FRICTION_TOL=0.10   # +/-10 % of -friction
R2_MIN=0.99
# kinetic_test(dy, n, ms [, wet]) — the 4th argument is WET, true = emit for
# real (main.cpp:812, `const bool WET = lua_toboolean(L, 4) != 0`). The
# integration design's recipe calls the same slot `dry`; it is wrong. The two
# dry-run assertions below (a trace WAS produced, and no client row appeared)
# would catch a polarity mistake either way.
WETARG=true
DRYARG=false

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

step "starting a nested Hyprland (a window on this session)"
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

# ---- talking to the plugin --------------------------------------------------
#
# `hyprctl eval` NEVER hands back a value on this Hyprland: a chunk that runs
# prints exactly "ok", and only a thrown error carries text
# (`eval 'error("x")'` -> `error: [string ...]: x`). So both channels here are
# one-way:
#
#   OUT — call a lua fn with `hc eval`. The only thing observable is whether it
#         threw, which is what kcall reports — and which the capability probe
#         below exploits deliberately, by throwing on purpose.
#   IN  — read a value from the FILES the introspection fns publish:
#         kinetic_dump()  -> $HOME/.local/state/hyprvtb/kinetic-dump.json
#         kinetic_stats() -> .../kinetic-stats.txt  (line 1 "seq N", line 2 JSON)
#         kinetic_get()   -> .../kinetic-get.txt    (same shape)
#         written atomically (tmp + rename), where $HOME is the COMPOSITOR's —
#         our own $RUN/home, never the user's. Every blob carries a monotonic
#         `seq`, so kfetch can tell a fresh write from a file that was already
#         lying there.

KSTATE="$RUN/home/.local/state/hyprvtb"
DUMPF="$KSTATE/kinetic-dump.json"
STATSF="$KSTATE/kinetic-stats.txt"
GETF="$KSTATE/kinetic-get.txt"

kcall() { # $1 = lua call text under hl.plugin.hyprvtb; 0 = ran, 1 = threw
  local out
  out="$(hc eval "hl.plugin.hyprvtb.$1" 2>&1)"
  case "$out" in *error*|*Error*) return 1 ;; esac
  return 0
}
kseq() { # the freshness token of a published blob, or empty if there is none
  case "$1" in
    *.json) sed -n 's/.*"seq":\([0-9][0-9]*\).*/\1/p' "$1" 2>/dev/null | head -1 ;;
    *)      sed -n '1s/^seq \([0-9][0-9]*\)$/\1/p' "$1" 2>/dev/null ;;
  esac
}
kfetch() { # $1 = published file, $2 = the lua call that writes it
  local before after i
  before="$(kseq "$1")"
  kcall "$2" || return 1
  for i in $(seq 1 40); do
    after="$(kseq "$1")"
    [ -n "$after" ] && [ "$after" != "$before" ] && return 0
    sleep 0.1
  done
  return 1
}
kdump()  { kfetch "$DUMPF" "kinetic_dump()"; }
kstats() { kfetch "$STATSF" "kinetic_stats()" && sed -n 2p "$STATSF"; }
kget()   { kfetch "$GETF" "kinetic_get()" && sed -n 2p "$GETF"; }

step "plugin loaded?"
if hc plugin list | grep -q hyprvtb; then
  ok "$(hc plugin list | grep -i version | head -1 | tr -d '\t')"
else
  bad "hyprvtb is not in the nested compositor's plugin list"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi

step "does this build have the kinetic module?"
# eval returns no values, so ASK BY THROWING: an absent field errors and
# hyprctl prints the message, a present one prints "ok".
PROBE="$(hc eval "if type(((hl.plugin or {}).hyprvtb or {}).kinetic_test) ~= 'function' then error('KINETIC_ABSENT') end" 2>&1)"
case "$PROBE" in
  *KINETIC_ABSENT*)
    skip "this .so has no kinetic_* lua functions — pre-kinetic build, nothing to test."
    hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
    exit 0
    ;;
  *error*|*Error*)
    skip "the capability probe itself errored, so this cannot be tested: $PROBE"
    hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
    exit 0
    ;;
  *) ok "kinetic_* lua functions are present (probe reply: $(printf '%s' "$PROBE" | tr -d '\n'))" ;;
esac

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
# This is not cosmetic — startGate refuses with "no-focus"/"not-window" if the
# pointer is not over a mapped toplevel, on the DRY path too.
read -r CX CY <<EOF
$(hc clients -j | jq -r --arg a "$WIN" '.[]|select(.address==$a)|"\(.at[0] + (.size[0]/2|floor)) \(.at[1] + (.size[1]/2|floor))"')
EOF
if [ -z "${CX:-}" ] || [ -z "${CY:-}" ]; then
  bad "could not read the window geometry"
  exit 1
fi
# This config is Lua: `hyprctl dispatch <name>` evaluates its argument AS LUA,
# so a bare dispatcher name is a nil global and silently does nothing. The warp
# is a DISPATCHER OBJECT — `hyprctl dispatch` on hl.dsp.cursor.move — which is
# the spelling that was found to actually move it; `hl.cursor.move` through
# eval builds the dispatcher without running it and leaves the cursor where it
# was. The others stay in the list as fallbacks, and every one is VERIFIED with
# cursorpos rather than trusted: the whole test rests on pointer focus.
cursor_at() { # $1 x, $2 y — is the NESTED cursor within 2 px of there?
  local p x y dx dy
  p="$(hc cursorpos 2>/dev/null | tr -d ' ')"
  x="${p%%,*}"; y="${p##*,}"
  case "$x$y" in ''|*[!0-9-]*) return 1 ;; esac
  dx=$(( x - $1 )); dy=$(( y - $2 ))
  [ "${dx#-}" -le 2 ] && [ "${dy#-}" -le 2 ]
}
WARPED=0
for form in "hl.dsp.cursor.move({ x = $CX, y = $CY })" "hl.cursor.move({ x = $CX, y = $CY })" "hl.cursor.move($CX, $CY)"; do
  hc dispatch "$form" >/dev/null 2>&1
  cursor_at "$CX" "$CY" && { WARPED=1; ok "cursor at $CX,$CY via dispatch \"$form\""; break; }
  hc eval "$form" >/dev/null 2>&1
  cursor_at "$CX" "$CY" && { WARPED=1; ok "cursor at $CX,$CY via eval \"$form\""; break; }
done
if [ "$WARPED" = 0 ]; then
  # Not fatal by itself: a fresh nested compositor parks the cursor in the
  # middle of its only monitor, which a single tiled window covers. Say so and
  # let the gate's own refusal reason (in kinetic_stats) decide.
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
kcall "kinetic_set(true)" || bad "kinetic_set(true) threw"
kcall "kinetic_set(\"unsafe_wet\", 1)" || bad "kinetic_set(\"unsafe_wet\", 1) threw"
GETJSON="$(kget)"
if [ -z "$GETJSON" ]; then
  bad "kinetic_get() published nothing to $GETF — introspection is broken, everything below reads blind"
else
  case "$GETJSON" in *'"enabled":true'*) ok "kinetic is enabled" ;; *) bad "kinetic_set(true) did not take: $GETJSON" ;; esac
  case "$GETJSON" in *'"unsafe_wet":true'*) ok "wet injection opted in, for instance $SIG only" ;; *) bad "unsafe_wet did not take — the wet half would be refused" ;; esac
  note "config: $GETJSON"
fi

# ---- helpers over the trace / the TSV ---------------------------------------

cat > "$RUN/trace-done.py" <<'PY'
# exit 0 once the published dump's trace ends in a 0.0 delta (the protocol stop)
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

cat > "$RUN/trace-empty.py" <<'PY'
# exit 0 if the published dump has an EMPTY trace (i.e. a refused injection)
import json, re, sys
m = re.search(r"\{.*\}", open(sys.argv[1]).read(), re.S)
if not m:
    sys.exit(2)
try:
    sys.exit(0 if not (json.loads(m.group(0)).get("trace") or []) else 1)
except Exception:
    sys.exit(2)
PY

rows() { local n; { n="$(wc -l < "$TSV" | tr -d ' ')"; } 2>/dev/null; echo "${n:-0}"; }

kin_run() { # $1 = full lua arg list for kinetic_test; runs it and waits it out
  kcall "kinetic_test($1)" || { note "kinetic_test threw"; return 1; }
  # injectTest clears the trace before it injects (vtbKinetic.cpp:1154), so a
  # terminal 0.0 in the published dump can only be THIS run's — no fixed sleep
  # is needed to avoid reading the previous fling's stop.
  for _ in $(seq 1 60); do
    sleep 0.25
    kdump || continue
    "$PY3" "$RUN/trace-done.py" "$DUMPF" && return 0
  done
  return 1
}

# ---- (a1 §8) refusal paths, first: nothing has ever been emitted yet, so an
# empty trace here is unambiguous.

step "refusal: kinetic disabled (a1 criterion 8)"
kcall "kinetic_set(false)"
kcall "kinetic_test(40, 8, 12, $DRYARG)"
sleep 1
if kdump && "$PY3" "$RUN/trace-empty.py" "$DUMPF"; then
  ok "empty trace with kinetic disabled"
else
  bad "kinetic_set(false) did not refuse the injection — dump: $(head -c 300 "$DUMPF" 2>/dev/null)"
fi
ST="$(kstats)"
# Either answer is correct: onAxis returns before it samples when the module is
# disabled (the shipped path really is inert), so the stop may never reach the
# gate that would count a refusal at all.
case "$ST" in
  *'"disabled":'*) ok "the gate recorded the refusal as \"disabled\"" ;;
  *) note "no refusal counter — disabled means onAxis returns before sampling, so nothing reaches the gate" ;;
esac
alive && ok "compositor alive" || { bad "compositor died on the disabled-path injection"; exit 1; }

step "refusal: velocity below the start floor (a1 criterion 8)"
kcall "kinetic_set(true)"
kcall "kinetic_test(1, 2, 12, $DRYARG)"    # ~83 px/s, under kinetic_min_start_velocity 200
sleep 1
if kdump && "$PY3" "$RUN/trace-empty.py" "$DUMPF"; then
  ok "empty trace for a sub-threshold flick"
else
  bad "a sub-threshold flick started a fling — dump: $(head -c 300 "$DUMPF" 2>/dev/null)"
fi
ST="$(kstats)"
case "$ST" in *'"slow":'*) ok "the gate recorded the refusal as \"slow\"" ;; *) note "no \"slow\" refusal counter: $ST" ;; esac
if [ "$(rows)" = 0 ]; then
  ok "the client has seen nothing so far (both refusals were silent on the wire)"
else
  bad "$(rows) wheel events reached the client from a REFUSED injection"
fi

# ---- (a1) the dry run --------------------------------------------------------

step "DRY injection: kinetic_test(40, 8, 12, $DRYARG)"
kcall "kinetic_set(\"unsafe_wet\", 1)"   # idempotent; re-assert after kinetic_set(false)
DRY_BASE=$(rows)
if kin_run "40, 8, 12, $DRYARG"; then
  ok "the trace terminated"
else
  bad "the dry trace never ended in a 0.0 entry (15s) — dump: $(head -c 400 "$DUMPF" 2>/dev/null)"
  note "stats: $(kstats)"
fi
cp "$DUMPF" "$RUN/dump-dry.json" 2>/dev/null
if [ "$(rows)" = "$DRY_BASE" ]; then
  ok "the dry run touched no client (no new wheel events)"
else
  bad "the dry run emitted for real: $(( $(rows) - DRY_BASE )) wheel events reached the client"
fi
alive && ok "compositor alive" || { bad "compositor died during the dry injection"; exit 1; }
note "stats: $(kstats)"

step "DRY acceptance criteria"
"$PY3" - "$RUN/dump-dry.json" "$FRICTION_FALLBACK" "$EPS" "$STOP_MS" "$FRICTION_TOL" "$R2_MIN" "$RUN/v-dry" <<'PY'
import json, math, re, sys

dumpf, k_fallback, eps, stop_ms, tol, r2min, outf = sys.argv[1:8]
k_fallback, eps, stop_ms, tol, r2min = map(float, (k_fallback, eps, stop_ms, tol, r2min))
out = open(outf, "w")
def v(tag, msg): out.write("%s\t%s\n" % (tag, msg))

try:
    raw = open(dumpf).read()
except OSError as e:
    v("FAIL", "no published dump to read (%s)" % e)
    out.close(); sys.exit(0)
m = re.search(r"\{.*\}", raw, re.S)
if not m:
    v("FAIL", "the published dump is not JSON: %r" % raw[:200].strip())
    out.close(); sys.exit(0)
try:
    d = json.loads(m.group(0))
except Exception as e:
    v("FAIL", "the published dump did not parse (%s): %r" % (e, m.group(0)[:200]))
    out.close(); sys.exit(0)

trace = [(float(t), float(dl)) for t, dl in (d.get("trace") or [])]
state = d.get("state", "?")
try:
    k = float(d.get("friction", k_fallback))
except (TypeError, ValueError):
    k = k_fallback
v("NOTE", "state=%s friction=%g dry=%s owed=%s entries=%d" % (state, k, d.get("dry"), d.get("owed"), len(trace)))

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

# 3. no re-acceleration.
#
# NOT a raw sample-to-sample comparison. Each emitted delta is
# v*(1-e^-k*dt)/k, so its size is proportional to the length of the tick that
# produced it: a tick that lands 19 ms after its predecessor instead of 16
# emits ~8% MORE than that predecessor even though v fell the whole time.
# Measured here: dt ranges 16-19 ms and produces exactly one such rise, at the
# tail where the deltas are smallest. That is timer jitter, not physics.
#
# The physical claim is about the VELOCITY, so divide each delta by its own
# tick interval, taken from the trace's own timestamps, and require THAT to be
# non-increasing. On the same trace the normalised series is monotone to within
# 0.4% (timestamps are integer ms, so ~1/16 = 6% of quantisation noise is
# available before a real regression could hide) — a genuine re-acceleration is
# gross by comparison. Raw rises are reported as a note with their dt, so the
# jitter stays visible instead of being hidden by the tolerance.
mags = [abs(dl) for _, dl in nz]
raw_rise = [(i, mags[i], mags[i + 1], nz[i + 1][0] - nz[i][0]) for i in range(len(mags) - 1) if mags[i + 1] > mags[i]]
TOL = 1.15
vel = [(nz[i][0], mags[i] / max(1.0, nz[i][0] - nz[i - 1][0])) for i in range(1, len(nz))]
vrise = [(i, vel[i - 1][1], vel[i][1]) for i in range(1, len(vel)) if vel[i][1] > vel[i - 1][1] * TOL]
if len(vel) < 2:
    v("FAIL", "too few entries to test for re-acceleration")
elif not vrise:
    worst = max((vel[i][1] / vel[i - 1][1] for i in range(1, len(vel))), default=1.0)
    v("PASS", "no re-acceleration: rate-normalised |delta|/dt is non-increasing over %d entries (worst ratio %.4f, tol %.2f)" % (len(vel), worst, TOL))
else:
    v("FAIL", "re-acceleration: rate-normalised |delta|/dt rises %d time(s), first at index %d: %.4f -> %.4f px/ms"
      % (len(vrise), vrise[0][0], vrise[0][1], vrise[0][2]))
if raw_rise:
    v("NOTE", "%d raw sample-to-sample rise(s) from tick jitter, largest at index %d: %.4f -> %.4f over a %d ms tick (mean tick %.1f ms)"
      % (len(raw_rise), raw_rise[0][0], raw_rise[0][1], raw_rise[0][2], raw_rise[0][3],
         (nz[-1][0] - nz[0][0]) / max(1, len(nz) - 1)))

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

step "DRY sign symmetry: dy = -40 mirrors it (a1 criterion 9)"
if kin_run "-40, 8, 12, $DRYARG"; then
  cp "$DUMPF" "$RUN/dump-neg.json" 2>/dev/null
  "$PY3" - "$RUN/dump-neg.json" "$FRICTION_TOL" "$RUN/v-neg" <<'PY'
import json, math, re, sys
dumpf, tol, outf = sys.argv[1], float(sys.argv[2]), sys.argv[3]
out = open(outf, "w")
def v(tag, msg): out.write("%s\t%s\n" % (tag, msg))
m = re.search(r"\{.*\}", open(dumpf).read(), re.S)
d = json.loads(m.group(0)) if m else {}
trace = [(float(t), float(dl)) for t, dl in (d.get("trace") or [])]
nz = [(t, dl) for t, dl in trace if dl != 0.0]
k = float(d.get("friction", 3.6))
if not nz:
    v("FAIL", "a negative flick produced no trace at all")
else:
    bad_signs = sum(1 for _, dl in nz if dl >= 0)
    if not bad_signs:
        v("PASS", "all %d deltas are negative — the direction is carried, not re-derived" % len(nz))
    else:
        v("FAIL", "%d of %d deltas are not negative — the sign was lost" % (bad_signs, len(nz)))
    xs = [t / 1000.0 for t, _ in nz]; ys = [math.log(abs(dl)) for _, dl in nz]
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else float("nan")
    dev = abs(slope + k) / k
    if dev <= tol:
        v("PASS", "mirrored decay slope %.3f /s vs -friction %.3f (%.1f%% off)" % (slope, -k, dev * 100))
    else:
        v("FAIL", "mirrored decay slope %.3f /s vs -friction %.3f (%.1f%% off)" % (slope, -k, dev * 100))
PY
  verdicts "$RUN/v-neg"
else
  bad "the negative-direction dry run never terminated — dump: $(head -c 300 "$DUMPF" 2>/dev/null)"
fi
alive && ok "compositor alive" || { bad "compositor died during the negative dry injection"; exit 1; }

# ---- (a2) the wet run --------------------------------------------------------

step "WET injection: kinetic_test(40, 8, 12, $WETARG) — into a real Qt client"
WET_BASE=$(rows)
kcall "kinetic_set(\"unsafe_wet\", 1)"   # idempotent; without it the wet call is refused
kcall "kinetic_test(40, 8, 12, $WETARG)" || bad "the wet kinetic_test threw"
# Poll the CLIENT, not the trace: the TSV is the oracle here.
for _ in $(seq 1 80); do
  sleep 0.25
  LAST=$(tail -n +$((WET_BASE + 1)) "$TSV" 2>/dev/null | tail -1 | cut -f6)
  [ "$LAST" = "ScrollEnd" ] && break
done
tail -n +$((WET_BASE + 1)) "$TSV" > "$RUN/wet.tsv" 2>/dev/null
WETROWS=$(wc -l < "$RUN/wet.tsv" | tr -d ' ')
if [ "$WETROWS" != 0 ]; then
  ok "$WETROWS wheel events reached the client"
else
  bad "no wheel events reached the client"
  note "stats (refusals/cancels say why): $(kstats)"
  note "cursor $(hc cursorpos 2>/dev/null | tr -d '\n'), focus $(hc activewindow -j 2>/dev/null | jq -r '.class // "none"')"
fi
alive && ok "compositor alive" || { bad "compositor died during the wet injection"; exit 1; }
note "stats: $(kstats)"

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

# Qt's PHASE MARKERS. QtWayland announces the start and the end of a scroll
# phase with events that carry no delta at all — every field zero — separately
# from the events that carry data, and on this build it emits TWO of each
# (same timestamp, all zeros). They are client-side bookkeeping: the wire had
# exactly 83 axis events and exactly one axis_stop for this fling, which is
# what the dry suite asserts exactly. So markers are identified structurally
# (all four deltas zero) and excluded from the data-row assertions below —
# they are not "zero deltas the compositor sent".
def marker(r): return r["px"] == 0 and r["py"] == 0 and r["ax"] == 0 and r["ay"] == 0
data = [r for r in rows if not marker(r)]

# 2. ScrollBegin first => the module emitted FINGER, not CONTINUOUS
if rows[0]["phase"] == "ScrollBegin":
    v("PASS", "first row is ScrollBegin — Qt opened a phase sequence, so the source was FINGER")
else:
    v("FAIL", "first row is %s, not ScrollBegin — Qt opens a phase only for axis_source_finger, "
              "so the module emitted the wrong source" % rows[0]["phase"])

# 3. the sequence is CLOSED, and closed only at the end: the last row is a
#    ScrollEnd and no ScrollEnd interrupts the data rows. (How MANY stops went
#    on the wire is the dry suite's assertion — exactly one — and it is exact
#    there; here a repeated marker says nothing about the wire.)
ends = [i for i, r in enumerate(rows) if r["phase"] == "ScrollEnd"]
last_data = max((i for i, r in enumerate(rows) if not marker(r)), default=-1)
if not ends:
    v("FAIL", "no ScrollEnd — the client is still mid-sequence, it believes scroll is in progress")
elif rows[-1]["phase"] != "ScrollEnd":
    v("FAIL", "the last row is %s, not ScrollEnd" % rows[-1]["phase"])
elif [i for i in ends if i < last_data]:
    v("FAIL", "a ScrollEnd arrives at row %d, before the last data row (%d) — the sequence was closed mid-fling"
      % ([i for i in ends if i < last_data][0], last_data))
else:
    v("PASS", "the sequence closes with ScrollEnd and nothing follows it (%d trailing End marker(s))" % len(ends))

pre = [r for r in data if r["phase"] != "ScrollEnd"]

# 4. non-increasing magnitude (ties allowed), asserted on angleDelta — the
#    finer of the two, since pixelDelta is an integer QPoint of a sub-pixel
#    value and the tail legitimately alternates -1, 0, -1, 0 once the wire
#    delta falls below half a pixel. Both are reported.
#
#    Per DELIVERY BATCH, not per row. A client that has not drained its socket
#    receives several compositor frames at once — they arrive with the SAME
#    millisecond — and Qt may merge two of them into one wheel event. Measured
#    at startup here, three data rows landed on one millisecond as 689, 569 and
#    then 1114: that last one is two ticks added together, so row-to-row it
#    looks like the fling doubled its speed, and nothing about it came off the
#    wire that way. Grouping by arrival timestamp and comparing the LARGEST
#    event of each batch is the statement that survives batching: no batch may
#    carry more than the one before it.
#
#    Still with a tolerance, for the same reason the dry suite normalises by
#    dt: a tick landing 19 ms after its predecessor instead of 16 carries ~8%
#    more distance (observed worst here: x1.075). A real re-acceleration is not
#    a few-percent event.
TOL = 1.15
groups = []
for r in pre:
    if groups and groups[-1][0] == r["t"]:
        groups[-1][1] = max(groups[-1][1], abs(r["ay"]))
    else:
        groups.append([r["t"], abs(r["ay"])])
gmax = [g[1] for g in groups]
grise = [(i, gmax[i], gmax[i + 1]) for i in range(len(gmax) - 1) if gmax[i + 1] > gmax[i]]
gbig = [x for x in grise if x[1] > 0 and x[2] > x[1] * TOL]
# ISOLATED vs SUSTAINED. Even grouped, delivery can hand one batch two ticks'
# worth (a merge that lands alone on its own millisecond), and that is a ~x2
# spike this side of the wire that the wire never had. The discriminator is
# what happens NEXT: a delivery artifact is a one-off and the series returns
# to where the decay had got to, whereas re-acceleration is a LEVEL SHIFT —
# the batch after it is still above where it started. So a spike that comes
# straight back down is reported, and only a sustained one fails.
sustained = [x for x in gbig if x[0] + 2 < len(gmax) and gmax[x[0] + 2] > gmax[x[0]]]
# ...and a slow ramp would clear the per-step allowance every time while still
# being a re-acceleration (verified: a synthetic +6%/tick climb went entirely
# undetected by the spike rule). Jitter and delivery produce ISOLATED rises;
# sustained motion produces CONSECUTIVE ones, and it ends higher than it began.
runs, cur = [], 0
for i in range(len(gmax) - 1):
    cur = cur + 1 if gmax[i + 1] > gmax[i] else 0
    runs.append(cur)
maxrun = max(runs) if runs else 0
batched = len(pre) - len(groups)
if sustained:
    x = sustained[0]
    v("FAIL", "|angleDelta.y| re-accelerates and STAYS up %d time(s), first at batch %d (t=%d): %d -> %d (x%.2f), still %d two batches later"
      % (len(sustained), x[0], groups[x[0]][0], x[1], x[2], x[2] / x[1], gmax[x[0] + 2]))
elif maxrun >= 3:
    v("FAIL", "|angleDelta.y| rises %d batches in a row — a ramp, not jitter (jitter and delivery batching are isolated events)" % maxrun)
elif gmax and gmax[-1] >= gmax[0]:
    v("FAIL", "|angleDelta.y| ends at %d having started at %d — the fling never decayed" % (gmax[-1], gmax[0]))
else:
    worst = max((b / a for _, a, b in grise if a > 0), default=1.0)
    v("PASS", "|angleDelta.y| decays monotonically across %d delivery batches (%d data rows, %d of them batched; %d isolated rise(s), longest run %d, worst x%.3f)"
      % (len(gmax), len(pre), batched, len(grise), maxrun, worst))
if gbig:
    v("NOTE", "%d isolated spike(s) above the x%.2f jitter allowance — one delivery batch carrying two ticks; largest x%.2f at t=%d"
      % (len(gbig), TOL, max(x[2] / x[1] for x in gbig), groups[gbig[0][0]][0]))
pmags = [abs(r["py"]) for r in pre]
prise = sum(1 for i in range(len(pmags) - 1) if pmags[i + 1] > pmags[i])
v("NOTE", "|pixelDelta.y| rises %d time(s) — integer rounding of a sub-pixel tail (last 10: %s)"
  % (prise, pmags[-10:]))

# 5. no zero-delta DATA row before the End. A zero on the wire IS the protocol
#    axis_stop, so a data row with both deltas zero would mean the client was
#    handed a stop mid-flight. (A pixelDelta that rounded to 0 while angleDelta
#    survived is Qt's integer QPoint, not a wire zero; the wire-level version of
#    this criterion is the dry suite's >= 0.10 px floor.)
wire0 = [i for i, r in enumerate(pre) if r["py"] == 0 and r["ay"] == 0]
round0 = [i for i, r in enumerate(pre) if r["py"] == 0 and r["ay"] != 0]
if not wire0:
    v("PASS", "no zero-delta data row before the ScrollEnd")
else:
    v("FAIL", "%d data row(s) with pixelDelta.y == 0 AND angleDelta.y == 0 before the End "
              "(first at data row %d) — a zero on the wire IS the axis_stop" % (len(wire0), wire0[0]))
if round0:
    v("NOTE", "%d row(s) have pixelDelta.y == 0 with angleDelta.y != 0 (first at data row %d, "
              "angleDelta %d): Qt's pixelDelta is an integer QPoint, so a sub-pixel tail "
              "delta rounds away there while the wire value was non-zero"
      % (len(round0), round0[0], pre[round0[0]]["ay"]))

# 6. the stop is withheld long enough that no client can re-fling
ups = pre
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
kcall "kinetic_cancel()"
kcall "kinetic_set(false)"
# emitRefused is the wire-level analogue of the degenerate-rect assertion: a
# NaN or a literal 0.0 that reached the seam and was refused THERE rather than
# never being computed. It must be zero.
ST="$(kstats)"
case "$ST" in
  *'"emitRefused":0'*) ok "emitRefused is 0 — nothing degenerate ever reached the seam" ;;
  *) bad "emitRefused is not 0: $ST" ;;
esac
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
  cp "$RUN"/dump-*.json /tmp/ 2>/dev/null
fi
exit "$FAILED"
