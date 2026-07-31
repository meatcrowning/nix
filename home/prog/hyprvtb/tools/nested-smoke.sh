#!/usr/bin/env bash
# hyprvtb smoke test — the Axis B half of the bump ritual (see ../PORTING.md).
#
# `nixos-rebuild build` already catches Axis A (symbols that moved: the plugin
# stops compiling). It cannot catch Axis B: hyprutils 0.14.0 tightened
# CWeakPointer::lock() and v2.48 compiled perfectly, then aborted the
# compositor seconds into login — from the roll animation's deferred callback.
# So this runs a real Hyprland, headless and nested, with the freshly built
# plugin, and exercises the paths that actually died:
#
#   decorate a window -> roll it up -> roll it back out -> close it
#
# then checks the nested compositor is still alive and its log is free of
# aborts.
#
# It nests inside the running Wayland session (aquamarine has no way to force
# its headless backend from the outside, and the DRM backend would want the
# seat), so it IS a window — but not one the user ever sees or types into: it
# is launched through `tools/sandbox.sh exec`, which parks it on a headless
# output and, via hyprland.lua's `sandbox-never-takes-the-seat` (no_focus on
# the `sandbox` tag), makes it incapable of taking his keyboard. It is
# otherwise a wholly separate compositor: it never touches the live session,
# its own windows, or its plugin instance.
#
# The `env WAYLAND_DISPLAY=…` prefix on that launch is required, not
# decoration: `hl.dsp.exec_cmd` runs BY THE COMPOSITOR and inherits the
# COMPOSITOR's environment, which on `top` has no WAYLAND_DISPLAY at all.
#
# The nested compositor runs with HOME pointed at a scratch dir. That is not
# hygiene, it is correctness: the plugin keeps its per-class geometry and its
# session snapshot under $HOME/.local/state/hyprvtb, so without it a smoke run
# would restore the real saved session into the nested compositor and then
# overwrite the real session.tsv with the nested window set (ask me how I know).
#
# Usage: ./nested-smoke.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed.
#
# Env: VTBSMOKE_EXPECT_FRAMES=0
#   Animation COMPLETION needs this nested compositor to receive frame
#   callbacks from its host. When its window is parked on a headless sandbox
#   output (tools/sandbox.sh) and the host session runs debug:vfr, it gets
#   none: the compositor never steps its animations, so a rolled-up window
#   never comes back OUT and a close animation never reaches sendClose. That is
#   the environment, not a regression — the roll-out step fails identically on
#   2.76 and on current builds, and a grim/screencopy pump does not unstick it
#   (screencopy renders the HOST output; the nested compositor still gets no
#   frame callback). Set 0 in such a run: the two animation-completion
#   assertions become clearly-labelled notes and every crash-class assertion
#   (compositor alive, log clean, decoration ownership) stays fully strict.
#   Leave unset (=1) unless you measure otherwise: on `top` 2026-07-30, with the
#   nested compositor on the sandbox's headless output, both animation
#   assertions passed at full strictness — the starvation is book's, not this
#   host's, so the default did NOT move when the sandbox became mandatory.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"   # …/home/prog/hyprvtb/tools -> repo root
SANDBOX="$REPO/tools/sandbox.sh"
# Short path on purpose: Hyprland refuses its IPC socket ("Socket2 path is too
# long") well before most people's idea of long.
RUN="/tmp/vtbsmk$$"
LOGDIR="$RUN"
mkdir -p "$RUN"

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
# HIS compositor. Recorded once, so everything below can refuse to touch it.
LIVE_SIG="${HYPRLAND_INSTANCE_SIGNATURE:-}"

cleanup() {
  # Single-shot: the hc() guard aborts by SIGTERM, so this can be entered twice
  # (once for TERM, once for EXIT) and a second teardown only muddies the log.
  [ -n "${CLEANED:-}" ] && return 0
  CLEANED=1
  # Kill by CONFIG PATH. It was never $! — the Hyprland launcher hands off to a
  # child — and now it CANNOT be: the compositor is spawned by tools/sandbox.sh
  # and is not this script's child at all. That mistake stacked up ten orphaned
  # nested sessions before it was noticed. The path is unique per run, so this
  # can never touch the live session.
  [ -n "${GUARDPID:-}" ] && kill "$GUARDPID" 2>/dev/null
  if [ -f "${GUARD_FLAG:-/nonexistent}" ]; then
    LEAKED="$(cat "$GUARD_FLAG")"
    printf '\n\033[31mSESSION LEAK\033[0m the nested compositor was migrated onto %s (a REAL output);\n' "$(cat "$GUARD_FLAG")" >&2
    printf '             the watchdog killed it. Almost certainly another agent ran sandbox.sh stop.\n' >&2
  fi
  pkill -9 -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null
  [ -n "${HYPRPID:-}" ] && kill -9 "$HYPRPID" 2>/dev/null
  # …and take the headless output down with it IF WE MADE IT (see SBOX_MINE).
  # In the trap, not at the end of the happy path: a run that dies halfway is
  # exactly the one that would leave a sandbox standing for leak-check.sh.
  [ "${SBOX_MINE:-0}" = 1 ] && "$SANDBOX" stop >/dev/null 2>&1
  sleep 0.5
  rm -rf "$RUN"
  # Hyprland ITSELF runs `systemctl --user import-environment … WAYLAND_DISPLAY
  # HYPRLAND_INSTANCE_SIGNATURE …` at startup, so the nested instance pointed
  # the whole user manager (and the D-Bus activation store) at itself — and a
  # SIGKILL means it never ran the matching unset-environment. Left alone, every
  # user unit that shells out to hyprctl talks to a dead socket for the rest of
  # the login and still exits 0. See home/srvs/hypr-env.nix.
  "$HOME/.config/scripts/hypr-session-env.sh" --restore >/dev/null 2>&1 || true
  # The nested compositor appears to the LIVE session as a window of class
  # "aquamarine", so the live plugin remembers per-class geometry for it when
  # it closes. Drop that entry — it is an artefact of the test, not the desktop.
  G="$HOME/.local/state/hyprvtb/geometry.tsv"
  if [ -f "$G" ] && grep -q '^aquamarine	' "$G"; then
    grep -v '^aquamarine	' "$G" > "$G.tmp" && mv "$G.tmp" "$G"
  fi
  # A run that put anything on his screen did not pass, whatever else it found.
  [ -n "${LEAKED:-}" ] && exit 1
  return 0
}
trap cleanup EXIT INT TERM

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
note() { printf '   \033[33mnote\033[0m %s\n' "$*"; }
skip() { printf '   \033[33mSKIP\033[0m %s\n' "$*"; }
FAILED=0

# Frame-starved environments (see VTBSMOKE_EXPECT_FRAMES in the header) cannot
# finish an animation, so the two assertions that need one finished are reported
# rather than failed. Everything else stays strict — a crash is a crash.
EXPECT_FRAMES="${VTBSMOKE_EXPECT_FRAMES:-1}"
animfail() {
  if [ "$EXPECT_FRAMES" = 1 ]; then
    bad "$*"
  else
    note "$* — but VTBSMOKE_EXPECT_FRAMES=0: this nested compositor gets no host frame callbacks, so its animations never step. Not a plugin verdict."
  fi
}

# ---- the plugin under test --------------------------------------------------

# Default: the plugin the last `nixos-rebuild switch` installed. Run this
# AFTER the rebuild in the ritual, or pass a store path explicitly.
PLUGIN="${1:-$(readlink -f "$HOME/.config/hypr/plugins/libhyprvtb.so")}"
echo "plugin: $PLUGIN"
[ -f "$PLUGIN" ] || { echo "no such plugin: $PLUGIN"; exit 1; }

# ---- a minimal nested config ------------------------------------------------
#
# Lua, like the real session: the plugin only registers its Lua functions when
# the config is not CONFIG_LEGACY, and hyprctl eval is how we drive them.

cat > "$RUN/hyprland.lua" <<LUA
hl.plugin.load("$PLUGIN")
hl.set("animations:enabled", true)
hl.set("misc:disable_hyprland_logo", true)
hl.set("misc:disable_splash_rendering", true)
LUA

# The compositor is not this script's child: it is spawned by tools/sandbox.sh,
# onto a headless output, under a no_focus rule. So its pid comes from the
# process table, matched on the per-run config path.
# Is anything of this run's still up? A launch goes through /bin/sh and then a
# nix wrapper before the compositor itself, so this deliberately matches loosely
# — it answers "did the launch die", not "which pid is the compositor".
nested_running() { pgrep -f "Hyprland -c $RUN/hyprland.lua" >/dev/null 2>&1; }
# THE compositor pid, from the instance lock — which the compositor writes
# itself, so it names the right one of the three processes that carry this
# config path in their argv (sh, the wrapper, the real thing). Guessing from
# the process table gets the wrapper, whose /proc/PID/maps has no plugin in it.
# /proc/<pid>/maps always stats as size 0, so `test -s` cannot ask this.
has_maps() { [ -n "$(head -c 1 "/proc/$1/maps" 2>/dev/null)" ]; }
nested_pid() {
  local lock p
  [ -n "${SIG:-}" ] || return 0
  lock="$(head -1 "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr/$SIG/hyprland.lock" 2>/dev/null)"
  # Prefer a pid whose address space is actually readable. hotswap-test's
  # dlclose/unmap assertion reads /proc/<pid>/maps, and on `top` 2026-07-30
  # that file came back EMPTY for BOTH Hyprland pids of a nested run (both
  # alive, State: S — so not the zombie-launcher theory; it reads like the
  # /proc permission that applies to a non-dumpable process). That assertion
  # therefore still skips itself here, out loud. The preference costs nothing
  # and picks the right pid wherever maps IS readable.
  if [ -n "$lock" ] && has_maps "$lock"; then echo "$lock"; return; fi
  for p in $(pgrep -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null); do
    has_maps "$p" && { echo "$p"; return; }
  done
  echo "$lock"
}

# WHICH instance is ours: resolved EXACTLY, from the instance locks. Each lock
# records the pid of the compositor that owns it, and /proc says whether that
# process was started with OUR unique config path. The set-difference against a
# "before" snapshot that used to live here had two ways to name the WRONG
# instance, and `hyprctl -i <wrong>` is not a harmless mistake: an EMPTY -i
# silently talks to the LIVE session (measured on top 2026-07-30), so a harness
# that fell through spawned kitty windows on his desktop and warped his cursor
# — exactly what he reported. The two ways were: a `hyprctl instances` call that
# returned nothing made the LIVE signature look new, and a second harness
# running concurrently (several agents share this desktop) made ITS instance
# look like ours.
find_sig() {
  local d sig pid
  for d in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/hypr/*/; do
    sig="$(basename "$d")"
    [ -n "$LIVE_SIG" ] && [ "$sig" = "$LIVE_SIG" ] && continue
    pid="$(head -1 "$d/hyprland.lock" 2>/dev/null)"
    [ -n "$pid" ] || continue
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$RUN/hyprland.lua" || continue
    echo "$sig"
    return
  done
}

# The watchdog's eyes, kept in a file rather than inline so no shell quoting can
# silently break the one check that protects his screen.
PY_WITNESS="$RUN/onreal.py"
cat > "$PY_WITNESS" <<'PYWITNESS'
import json, subprocess, sys
pid = sys.argv[1]
mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"],
                                 capture_output=True, text=True).stdout)
phys = {m["id"]: m["name"] for m in mons if not m["name"].startswith("HEADLESS-")}
for c in json.load(sys.stdin):
    if str(c.get("pid")) == pid and c["monitor"] in phys:
        print(phys[c["monitor"]])
        break
PYWITNESS

# THE OFF-SCREEN WATCHDOG. The nested compositor is a WINDOW in his session,
# parked on a headless output. If that output goes away — another agent's
# `sandbox.sh stop`, a stray `hyprctl output remove` — Hyprland MIGRATES its
# windows onto a REAL monitor, i.e. into his face. Measured on top 2026-07-30,
# during a run of this very harness: `aquamarine` sat on DP-5 for twelve
# seconds. So poll the LIVE session for our own window (matched on the nested
# compositor's pid, which is exact) and if it ever lands on a physical output,
# kill it AT ONCE and fail the run — never let it wait for the next step.
GUARD_FLAG="$RUN/on-his-screen"
offscreen_guard() {
  local m
  while sleep 2; do
    m="$(hyprctl -j clients 2>/dev/null | python3 "$PY_WITNESS" "$HYPRPID")"
    if [ -n "$m" ]; then
      echo "$m" > "$GUARD_FLAG"
      pkill -9 -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null
      return
    fi
  done
}

step "starting a nested Hyprland (off-screen via tools/sandbox.sh, ~20s)"
mkdir -p "$RUN/home"
: > "$LOGDIR/hyprland.log"
# Own it only if we created it. Several agents share this desktop and
# sandbox.sh reuses an existing headless output, so an unconditional `stop` in
# our trap would pull the monitor out from under somebody else's running
# harness — and Hyprland migrates a removed output's windows onto a REAL one.
SBOX_OUT="$("$SANDBOX" start)" || { echo "could not start the off-screen sandbox"; exit 1; }
echo "$SBOX_OUT"
case "$SBOX_OUT" in
  *"reusing existing"*) SBOX_MINE=0 ;;
  *)                    SBOX_MINE=1 ;;
esac
# ONE PROCESS, from what the sandbox spawns down to the compositor. This is
# load-bearing, not tidiness: Hyprland keys an exec rule on the pid it forked,
# so if anything in the chain FORKS instead of exec-ing, the compositor is a
# grandchild and `[workspace N silent; tag +sandbox]` matches nothing — the
# window maps on the REAL monitor and, having no `no_focus` tag either, takes
# his keyboard and warps his pointer to itself. Measured on top 2026-07-30: a
# redirection written straight into the exec string is enough to do it, because
# it stops /bin/sh from exec-ing the last command. Hence this launcher: the
# redirection lives inside it, after an explicit `exec`.
#
# `env WAYLAND_DISPLAY=…` is required for a different reason, and equally not
# decoration: hl.dsp.exec_cmd runs BY THE COMPOSITOR and inherits the
# COMPOSITOR's environment, which on `top` has no WAYLAND_DISPLAY at all.
cat > "$RUN/launch.sh" <<LAUNCH
#!/bin/sh
exec env -u HYPRLAND_INSTANCE_SIGNATURE \
    WAYLAND_DISPLAY="$PARENT_WL" \
    HOME="$RUN/home" \
    Hyprland -c "$RUN/hyprland.lua" >"$LOGDIR/hyprland.log" 2>&1
LAUNCH
chmod +x "$RUN/launch.sh"
"$SANDBOX" exec "$RUN/launch.sh" \
    || { echo "sandbox could not launch the nested compositor"; exit 1; }

SIG=""
for _ in $(seq 1 60); do
  sleep 0.5
  SIG="$(find_sig)"
  [ -n "$SIG" ] && break
  # Once it has appeared, its disappearance means it died — stop waiting.
  if nested_running; then SEEN=1
  elif [ -n "${SEEN:-}" ]; then break
  fi
done
if [ -z "$SIG" ]; then
  bad "nested Hyprland never came up — log tail:"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi
HYPRPID="$(nested_pid)"
ok "instance $SIG (pid ${HYPRPID:-unknown})"
offscreen_guard & GUARDPID=$!

# EVERY hyprctl below is aimed at the NESTED instance, and this is the guard
# that makes that true rather than intended. `hyprctl -i ""` does NOT fail: it
# connects to the LIVE compositor. So an unset SIG turned every `hl.exec_cmd`,
# every cursor warp and every plugin call in this file into something that
# happened on HIS desktop. Refuse loudly instead of degrading — and SIGTERM the
# script itself, because a bare `exit` inside `$(hc ...)` only leaves the
# subshell and the run would carry on unaimed.
hc() {
  if [ -z "${SIG:-}" ] || { [ -n "$LIVE_SIG" ] && [ "$SIG" = "$LIVE_SIG" ]; }; then
    printf '\n\033[31mREFUSING\033[0m no nested instance (SIG=%s) — this hyprctl would drive the LIVE session: %s\n' \
      "'${SIG:-}'" "$*" >&2
    kill -TERM $$
    exit 1
  fi
  hyprctl -i "$SIG" "$@"
}

step "plugin loaded?"
if hc plugin list | grep -q hyprvtb; then
  ok "$(hc plugin list | grep -i version | head -1 | tr -d '\t')"
else
  bad "hyprvtb is not in the nested compositor's plugin list"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi

step "opening a window (it must get decorated)"
# hl.exec_cmd is the Lua spawn entry point (there is no hl.dsp.exec), and it
# has to go through `eval` — `dispatch` wants a dispatcher object back.
hc eval "hl.exec_cmd('kitty --class hyprvtb-smoke')" >/dev/null
for _ in $(seq 1 40); do
  sleep 0.5
  ADDR=$(hc clients -j | jq -r '.[]|select(.class=="hyprvtb-smoke" and .mapped)|.address' | head -1)
  [ -n "$ADDR" ] && break
done
[ -n "$ADDR" ] || { bad "the test window never mapped"; tail -30 "$LOGDIR/hyprland.log"; exit 1; }
ok "window $ADDR"

# Float it: roll-up, minimize, maximize and the edge-resize halo all bail on a
# tiled window (see CVtbDeco::toggleRollup), and the nested compositor tiles by
# default where the real session floats everything. Without this the roll calls
# below return successfully having done nothing at all.
hc dispatch "hl.dsp.window.float({ action = 'toggle' })" >/dev/null
sleep 1
if [ "$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.floating')" = "true" ]; then
  ok "window is floating"
else
  bad "could not float the test window — the roll tests below would be vacuous"
  exit 1
fi

alive()  { [ -n "${HYPRPID:-}" ] && kill -0 "$HYPRPID" 2>/dev/null && hc version >/dev/null 2>&1; }
# A rolled-up (shaded) window is genuinely hidden, not resized — so `hidden`
# is the observable that says the roll actually happened, rather than "the
# call returned and nothing crashed".
hidden() { [ "$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.hidden')" = "true" ]; }

step "roll up (the v2.48 abort path: deferred callback over a deco weak ref)"
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
alive && ok "compositor survived the roll-up" || bad "compositor died during roll-up"
hidden && ok "window is hidden (it really rolled up)" || bad "window is not hidden — the roll did not happen"

step "roll back out (open-reveal -> beginRollReveal doLater)"
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
alive && ok "compositor survived the roll-out" || bad "compositor died during roll-out"
hidden && animfail "window is still hidden — it never rolled back out" || ok "window is visible again"

step "kinetic momentum (2.78: a new timer + a weak ref to a surface)"
# Axis B is exactly the class this module can hit: v2.48 compiled perfectly and
# then aborted the compositor seconds into login, from a deferred callback. A
# fling is a CEventLoopTimer plus a per-surface weak ref, so run one dry (the
# estimator, the timer and the integrator, appending to a trace instead of the
# wire) and one wet (really at the seat — refused unless this instance is first
# told kinetic_set("unsafe_wet", 1); there is no automatic nested detection, the
# explicit opt-in IS the safety mechanism, and it is safe only because this
# compositor is a nested one we own).
# Acceptance here is only "alive and log clean": the numeric acceptance
# criteria live in kinetic-test.sh, which owns a real client to measure with.
# (The 4th argument is spelled `wet` in docs/kinetic-scroll.md and `dry` in the
# integration design. Both values are run below, so this step covers the timer
# either way; kinetic-test.sh is the one that has to know which is which.)
# `hyprctl eval` never hands back a value here (a chunk that runs prints exactly
# "ok"), so the capability question is asked by THROWING: an absent field errors
# and hyprctl prints the message.
KIN_PROBE="$(hc eval "if type(((hl.plugin or {}).hyprvtb or {}).kinetic_test) ~= 'function' then error('KINETIC_ABSENT') end" 2>&1)"
case "$KIN_PROBE" in
  *KINETIC_ABSENT*|*error*|*Error*)
    skip "no kinetic_* lua functions on this .so — pre-kinetic build, nothing to exercise"
    ;;
  *)
    # Counters, not return values: kinetic_stats() publishes its JSON to
    # $HOME/.local/state/hyprvtb/kinetic-stats.txt (our own $RUN/home), so
    # "flings" tells us whether the injection actually STARTED one — the
    # difference between a real timer test and a vacuous one.
    KSTATS="$RUN/home/.local/state/hyprvtb/kinetic-stats.txt"
    kflings() {
      hc eval "hl.plugin.hyprvtb.kinetic_stats()" >/dev/null 2>&1
      sed -n '2s/.*"flings":\([0-9][0-9]*\).*/\1/p' "$KSTATS" 2>/dev/null | head -1
    }
    # startGate refuses ("no-focus"/"not-window") unless the pointer is over a
    # mapped, visible toplevel — on the DRY path too. Aim at whatever visible
    # window there is.
    kin_centre() { # x y of the first visible mapped window, if any
      hc clients -j | jq -r 'first(.[]|select(.mapped and (.hidden|not)))|"\(.at[0] + (.size[0]/2|floor)) \(.at[1] + (.size[1]/2|floor))"' 2>/dev/null
    }
    KIN_TMPWIN=""
    read -r KCX KCY <<EOF
$(kin_centre)
EOF
    if [ -z "${KCX:-}" ]; then
      # Nothing visible to point at: a frame-starved roll-out leaves the smoke
      # window hidden for good, and without a target the injections below would
      # be refused and prove nothing. Put a window there — and take it away
      # again before the rest of the smoke test runs, so nothing downstream
      # sees a stranger.
      note "no visible window (starved roll-out) — opening a temporary one to aim at"
      hc eval "hl.exec_cmd('kitty --class hyprvtb-kin')" >/dev/null
      for _ in $(seq 1 40); do
        sleep 0.5
        KIN_TMPWIN=$(hc clients -j | jq -r '.[]|select(.class=="hyprvtb-kin" and .mapped)|.address' | head -1)
        [ -n "$KIN_TMPWIN" ] && break
      done
      read -r KCX KCY <<EOF
$(kin_centre)
EOF
    fi
    if [ -n "${KCX:-}" ] && [ -n "${KCY:-}" ]; then
      # The warp is a DISPATCHER object: `hyprctl dispatch` on hl.dsp.cursor.move.
      # `hl.cursor.move` exists as a name but calling it through eval moves
      # nothing (it builds the dispatcher, it does not run it) — verified here,
      # the cursor stayed at 0,0. Verify with cursorpos rather than trusting it.
      hc dispatch "hl.dsp.cursor.move({ x = $KCX, y = $KCY })" >/dev/null 2>&1
      [ "$(hc cursorpos 2>/dev/null | tr -d ' ')" = "$KCX,$KCY" ] || hc eval "hl.cursor.move({ x = $KCX, y = $KCY })" >/dev/null 2>&1
      note "aiming at $KCX,$KCY; nested cursor now at $(hc cursorpos 2>/dev/null | tr -d '\n')"
    else
      note "no visible mapped window to point at — the gate will refuse; only the crash-class checks below apply"
    fi
    hc eval "hl.plugin.hyprvtb.kinetic_set(true)" >/dev/null 2>&1
    F0="$(kflings)"
    hc eval "hl.plugin.hyprvtb.kinetic_test(40, 8, 12, false)" >/dev/null 2>&1   # DRY: 4th arg is `wet`
    sleep 3   # coast (<= kinetic_max_duration_ms 2000) + the withheld stop (300)
    alive && ok "compositor survived a dry injection" || bad "compositor died during the dry injection"
    F1="$(kflings)"
    if [ -n "$F0" ] && [ -n "$F1" ] && [ "$F1" -gt "$F0" ]; then
      ok "a dry fling really started (flings $F0 -> $F1) — the timer path was exercised"
    else
      note "no fling started (flings $F0 -> $F1); the gate refused: $(sed -n 2p "$KSTATS" 2>/dev/null | sed 's/.*"refusals"://')"
    fi
    # The wet opt-in, for this nested instance only. Dry needs none.
    hc eval "hl.plugin.hyprvtb.kinetic_set(\"unsafe_wet\", 1)" >/dev/null 2>&1
    hc eval "hl.plugin.hyprvtb.kinetic_test(40, 8, 12, true)" >/dev/null 2>&1    # WET
    sleep 3
    alive && ok "compositor survived a wet injection" || bad "compositor died during the wet injection"
    F2="$(kflings)"
    if [ -n "$F1" ] && [ -n "$F2" ] && [ "$F2" -gt "$F1" ]; then
      ok "a wet fling really started (flings $F1 -> $F2) — real axis events went to the seat"
    else
      note "no wet fling started (flings $F1 -> $F2): $(sed -n 2p "$KSTATS" 2>/dev/null | sed 's/.*"refusals"://')"
    fi
    hc eval "hl.plugin.hyprvtb.kinetic_set(false)" >/dev/null 2>&1
    if [ -n "$KIN_TMPWIN" ]; then
      # Kill the CLIENT, not the window: a dispatched close is animated, and
      # animations are exactly what this environment cannot finish.
      KIN_TMPPID=$(hc clients -j | jq -r --arg a "$KIN_TMPWIN" '.[]|select(.address==$a)|.pid')
      [ -n "$KIN_TMPPID" ] && [ "$KIN_TMPPID" != "null" ] && kill -9 "$KIN_TMPPID" 2>/dev/null
      sleep 1
      alive && ok "temporary window gone, compositor still alive" || bad "compositor died closing the temporary window"
    fi
    ;;
esac

step "session save"
hc eval "hl.plugin.hyprvtb.save_session()" >/dev/null
sleep 1
alive && ok "compositor survived save_session" || bad "compositor died during save_session"

step "graceful close (the animated close path)"
# close_active works on the FOCUSED window, and a rolled-up window is hidden
# (hence unfocusable) — so this has to run with the window rolled back out,
# which the roll-out step above left it as, refocused by toggleRollup.
hc eval "hl.plugin.hyprvtb.close_active()" >/dev/null
sleep 2
alive && ok "compositor survived the close" || bad "compositor died during the close"
# The close is animated: roll the window up, fade the bar out, THEN sendClose.
# The roll-up half is observable at once (the window goes hidden) and is what
# this asserts. The fade half only advances while the compositor renders, and a
# nested compositor whose window is occluded on the parent gets no frame
# callbacks — so the client actually exiting is checked but only warned about.
if hidden; then
  ok "close animation started (window hidden)"
else
  # Also downgraded when frames are absent: close_active works on the FOCUSED
  # window, and a window the roll-out could not un-hide is unfocusable, so this
  # branch reports the starvation upstream rather than a plugin fault.
  animfail "close_active did nothing — the window never even rolled up"
fi
for _ in 1 2 3 4 5 6 7 8; do
  sleep 1
  hc clients -j | jq -e --arg a "$ADDR" 'any(.[]; .address==$a)' >/dev/null || break
done
if hc clients -j | jq -e --arg a "$ADDR" 'any(.[]; .address==$a)' >/dev/null; then
  printf '   \033[33mnote\033[0m the client had not exited after 8s — expected whenever this nested\n         compositor gets no frame callbacks (occluded, or on a headless\n         sandbox output): the fade never finishes, so sendClose never runs\n'
else
  ok "window is gone (the close ran end to end)"
fi

step "log check"
if grep -qiE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|safe mode' "$LOGDIR/hyprland.log"; then
  bad "the nested log has an abort/assert:"
  grep -inE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|safe mode' "$LOGDIR/hyprland.log" | head
else
  ok "no aborts, asserts or safe-mode entries"
fi

step "shutting the nested session down"
hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
sleep 1

if [ "$FAILED" = 0 ]; then
  printf '\n\033[32mSMOKE TEST PASSED\033[0m — Axis B paths clean. Now do the visual checklist (PORTING.md step 5).\n'
else
  printf '\n\033[31mSMOKE TEST FAILED\033[0m — full log kept at %s\n' "$LOGDIR/hyprland.log"
  cp "$LOGDIR/hyprland.log" /tmp/hyprvtb-smoke.log 2>/dev/null && echo "copy: /tmp/hyprvtb-smoke.log"
fi
exit "$FAILED"
