#!/usr/bin/env bash
# hyprvtb hot-swap test — does `hyprctl reload` swapping the .so leave the
# compositor alive?
#
# This is the regression test for the 2026-07-25 session kill. `hyprland.lua`
# hands hl.plugin.load the readlink-resolved /nix/store path, so every rebuild
# is a new path STRING and a plain `hyprctl reload` makes Hyprland unload the
# old library and map the new one. The reload itself always looks perfect —
# new version, one instance, no config errors — and then the compositor
# SIGSEGVs at the next WINDOW CLOSE, jumping into the unmapped .so.
#
# The reason is CWindow::updateWindowDecos():
#
#     if (!m_isMapped || isHidden())
#         return;
#
# Removing a decoration only QUEUES it and calls that, so a HIDDEN window —
# and this plugin hides every rolled-up / minimized one — keeps owning a
# UP<CVtbDeco> across dlclose(). ~CWindow then runs a destructor that no longer
# exists. PLUGIN_EXIT therefore tears its own decorations off every window
# (Hl::detachOurDecos) instead of trusting the plugin system to.
#
# So the shape of the test is: roll a window up (hidden, holding a deco),
# hot-swap the plugin under it, then close that window and see who is left.
#
# 2.78 adds a second thing that must survive the swap, and it is worse: a
# kinetic fling in flight is a live CEventLoopTimer *plus* an OPEN
# wl_pointer axis sequence — code owned by the outgoing .so, and a protocol
# obligation owed to a client. So this file also starts a long fling into a
# PySide wheel logger (tools/wheel-log.py) before the swap and afterwards
# checks three things: the compositor is alive, the INCOMING instance is cold
# (empty trace, idle), and the client's last event is a ScrollEnd — the stop
# PLUGIN_EXIT owed it. Against a pre-2.78 .so the kinetic steps SKIP.
#
# Usage: ./hotswap-test.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed. Point it
# at a pre-2.65 build and it should FAIL — that is the bug reproducing.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="/tmp/vtbhs$$"
mkdir -p "$RUN"
KIN_TSV="$RUN/wheel.tsv"

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "no WAYLAND_DISPLAY — run this from inside the graphical session."
  exit 1
fi
case "$WAYLAND_DISPLAY" in
  /*) PARENT_WL="$WAYLAND_DISPLAY" ;;
  *)  PARENT_WL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/$WAYLAND_DISPLAY" ;;
esac

cleanup() {
  # The wheel logger is a client of the NESTED compositor; its argv carries the
  # (unique) TSV path, so this can never match anything of the user's.
  pkill -9 -f "$KIN_TSV" 2>/dev/null
  pkill -9 -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null
  [ -n "${HYPRPID:-}" ] && kill -9 "$HYPRPID" 2>/dev/null
  sleep 0.5
  rm -rf "$RUN"
  # Hyprland ITSELF runs `systemctl --user import-environment … WAYLAND_DISPLAY
  # HYPRLAND_INSTANCE_SIGNATURE …` at startup, so the nested instance pointed
  # the whole user manager (and the D-Bus activation store) at itself — and a
  # SIGKILL means it never ran the matching unset-environment. Left alone, every
  # user unit that shells out to hyprctl talks to a dead socket for the rest of
  # the login and still exits 0. See home/srvs/hypr-env.nix.
  "$HOME/.config/scripts/hypr-session-env.sh" --restore >/dev/null 2>&1 || true
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

# Same knob, same reason, as nested-smoke.sh (see its header): when this nested
# compositor gets no frame callbacks from its host — its window parked on a
# headless sandbox output, host session at vfr — animations never step, so a
# window that is asked to roll back OUT stays hidden forever. Exactly one
# assertion here depends on a finished animation; with VTBSMOKE_EXPECT_FRAMES=0
# it becomes a note. Every crash-class and ownership assertion stays strict.
EXPECT_FRAMES="${VTBSMOKE_EXPECT_FRAMES:-1}"
animfail() {
  if [ "$EXPECT_FRAMES" = 1 ]; then
    bad "$*"
  else
    note "$* — but VTBSMOKE_EXPECT_FRAMES=0: no host frame callbacks here, so a roll-out animation cannot finish and this check cannot discriminate. Not a plugin verdict."
  fi
}

PLUGIN="${1:-$(readlink -f "$HOME/.config/hypr/plugins/libhyprvtb.so")}"
[ -f "$PLUGIN" ] || { echo "no such plugin: $PLUGIN"; exit 1; }
echo "plugin: $PLUGIN"

# Two copies of the SAME build under different names. That is exactly what a
# rebuild looks like to Hyprland (it keys loaded plugins on the path string),
# without needing two builds to test the swap machinery.
cp "$PLUGIN" "$RUN/vtb-a.so"
cp "$PLUGIN" "$RUN/vtb-b.so"

write_config() { # $1 = which .so
  cat > "$RUN/hyprland.lua" <<LUA
hl.plugin.load("$1")
hl.config({
    animations = { enabled = true },
    misc = { disable_hyprland_logo = true, disable_splash_rendering = true },
    -- Hyprland defaults debug:disable_logs to TRUE, which silences the very
    -- [PluginSystem] load/unload lines this test asserts the swap on.
    debug = { disable_logs = false },
})
LUA
}

step "starting a nested Hyprland on vtb-a.so"
write_config "$RUN/vtb-a.so"
BEFORE=$(hyprctl instances -j 2>/dev/null | grep -o '"instance": *"[^"]*"' | cut -d'"' -f4 | sort)
mkdir -p "$RUN/home"
env -u HYPRLAND_INSTANCE_SIGNATURE \
    WAYLAND_DISPLAY="$PARENT_WL" \
    HOME="$RUN/home" \
    Hyprland -c "$RUN/hyprland.lua" >"$RUN/hyprland.log" 2>&1 &
HYPRPID=$!

SIG=""
for _ in $(seq 1 60); do
  sleep 0.5
  kill -0 "$HYPRPID" 2>/dev/null || break
  SIG=$(hyprctl instances -j 2>/dev/null | grep -o '"instance": *"[^"]*"' | cut -d'"' -f4 | sort | comm -13 <(echo "$BEFORE") - | head -1)
  [ -n "$SIG" ] && break
done
[ -n "$SIG" ] || { bad "nested Hyprland never came up"; tail -30 "$RUN/hyprland.log"; exit 1; }
ok "instance $SIG"

hc()    { hyprctl -i "$SIG" "$@"; }
# Hyprland's real log is per-instance under $XDG_RUNTIME_DIR (stdout gets only
# the banner) — the plugin load/unload lines we assert on live there.
ILOG="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr/$SIG/hyprland.log"
alive() { kill -0 "$HYPRPID" 2>/dev/null && hc version >/dev/null 2>&1; }

hc plugin list | grep -q hyprvtb || { bad "plugin did not load"; exit 1; }
ok "vtb-a.so loaded"

step "opening a window and rolling it up (hidden = holds a deco across the swap)"
hc eval "hl.exec_cmd('kitty --class hyprvtb-hs')" >/dev/null
for _ in $(seq 1 40); do
  sleep 0.5
  ADDR=$(hc clients -j | jq -r '.[]|select(.class=="hyprvtb-hs" and .mapped)|.address' | head -1)
  [ -n "$ADDR" ] && break
done
[ -n "$ADDR" ] || { bad "the test window never mapped"; exit 1; }
hc dispatch "hl.dsp.window.float({ action = 'toggle' })" >/dev/null
sleep 1
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
if [ "$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.hidden')" = "true" ]; then
  ok "window $ADDR is rolled up (hidden)"
else
  bad "window never rolled up — the test would be vacuous"
  exit 1
fi

step "arming a fling across the swap (kinetic, integration design 5b)"
# Momentum must be flowing INTO A REAL CLIENT when the .so is unmapped. A dry
# injection would exercise the timer but not the protocol obligation, which is
# the half nothing else in this plugin has ever had.
KINETIC=0
KIN_WET=0
KIN_PY=""
KIN_LAST_PRE=""
: > "$KIN_TSV"
# `hyprctl eval` hands back no values here (a chunk that runs prints exactly
# "ok"), so ask by THROWING: an absent field errors and hyprctl prints it.
KIN_PROBE="$(hc eval "if type(((hl.plugin or {}).hyprvtb or {}).kinetic_test) ~= 'function' then error('KINETIC_ABSENT') end" 2>&1)"
case "$KIN_PROBE" in *KINETIC_ABSENT*|*error*|*Error*) KINETIC=0 ;; *) KINETIC=1 ;; esac
if [ "$KINETIC" = 0 ]; then
  skip "no kinetic_* lua functions on this .so — pre-2.78 build, the mid-flight"
  skip "     swap case does not apply (same caveat shape as the 2.71 handoff assertion)"
else
  # The wheel logger needs PySide6: Fedora's /usr/bin/python3 on book, and on
  # top whatever KINETIC_PY points at (there is no /usr/bin/python3 there).
  for cand in "${KINETIC_PY:-}" /usr/bin/python3 "$(command -v python3)"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    "$cand" -c 'import PySide6.QtWidgets' >/dev/null 2>&1 && { KIN_PY="$cand"; break; }
  done
fi
if [ "$KINETIC" = 1 ] && [ -z "$KIN_PY" ]; then
  skip "no python3 that can import PySide6 — the client half of 5b is untestable here."
  skip "     Set KINETIC_PY=/path/to/python3 to enable it."
  KINETIC=0
fi
if [ "$KINETIC" = 1 ]; then
  hc eval "hl.plugin.hyprvtb.kinetic_set(true)" >/dev/null 2>&1
  # friction 0.5 => a slow, long fling, so it is still coasting when the async
  # swap finally lands. It is a runtime override, so no config edit, no reload.
  hc eval "hl.plugin.hyprvtb.kinetic_set(\"friction\", 0.5)" >/dev/null 2>&1
  # A wet injection is refused without this opt-in — there is no automatic
  # nested detection, the explicit opt-in IS the safety mechanism. Safe only
  # because this is a nested instance we own; the live session never gets it.
  hc eval "hl.plugin.hyprvtb.kinetic_set(\"unsafe_wet\", 1)" >/dev/null 2>&1
  ok "kinetic enabled, friction 0.5, wet injection opted in (runtime overrides)"
  hc eval "hl.exec_cmd('env QT_QPA_PLATFORM=wayland $KIN_PY $HERE/wheel-log.py $KIN_TSV')" >/dev/null
  KINWIN=""
  for _ in $(seq 1 60); do
    sleep 0.5
    KINWIN=$(hc clients -j | jq -r '.[]|select(.mapped and (.class=="wheel-log" or .title=="wheel-log"))|.address' | head -1)
    [ -n "$KINWIN" ] && break
  done
  if [ -z "$KINWIN" ]; then
    note "the wheel logger never mapped — skipping the client half of 5b"
    KINETIC=0
  else
    ok "wheel-log window $KINWIN"
    # Pointer focus is what momentum follows, and sendPointerAxis has no
    # surface argument — it goes wherever the cursor is. This config is Lua, so
    # a bare dispatcher name is a nil global: the warp is hl.cursor.move via
    # `eval`. Verify with cursorpos rather than trusting the call.
    read -r KCX KCY <<EOF
$(hc clients -j | jq -r --arg a "$KINWIN" '.[]|select(.address==$a)|"\(.at[0] + (.size[0]/2|floor)) \(.at[1] + (.size[1]/2|floor))"')
EOF
    # The warp is a DISPATCHER object, so `hyprctl dispatch` on
    # hl.dsp.cursor.move — `hl.cursor.move` through eval builds the dispatcher
    # without running it and moves nothing. Verify with cursorpos.
    hc dispatch "hl.dsp.cursor.move({ x = ${KCX:-0}, y = ${KCY:-0} })" >/dev/null 2>&1
    [ "$(hc cursorpos 2>/dev/null | tr -d ' ')" = "${KCX},${KCY}" ] || \
      hc eval "hl.cursor.move({ x = ${KCX:-0}, y = ${KCY:-0} })" >/dev/null 2>&1
    note "cursor at $(hc cursorpos 2>/dev/null | tr -d '\n') (window centre $KCX,$KCY)"
    # 4th arg is WET, true = emit for real (main.cpp:812). The integration
    # design's recipe calls the same slot `dry`; it is wrong.
    hc eval "hl.plugin.hyprvtb.kinetic_test(400, 20, 8, true)" >/dev/null 2>&1
    for _ in $(seq 1 12); do sleep 0.25; [ -s "$KIN_TSV" ] && break; done
    if [ -s "$KIN_TSV" ]; then
      KIN_WET=1
      ok "momentum is reaching the client ($(wc -l < "$KIN_TSV" | tr -d ' ') wheel events so far)"
    else
      note "no wheel events reached the client — the exit-obligation half will be untested"
    fi
  fi
fi

step "hot-swapping the plugin under it (vtb-a.so -> vtb-b.so, hyprctl reload)"
write_config "$RUN/vtb-b.so"
hc reload >/dev/null 2>&1
# The swap is ASYNC: Hyprland's own config-file watcher ("file modified,
# reloading") is usually what performs it, a beat after the write. Poll the log
# for the load line instead of sleeping a fixed amount, or the assertions below
# race it and the test lies.
# ...and poll it with an actual IPC call each round: an idle, occluded nested
# compositor does not process the inotify wakeup until something turns its
# event loop, so a poll that only greps the log waits forever and then reports
# "nothing was swapped" a beat before the swap lands.
SWAPPED=0
for i in $(seq 1 60); do
  # Check FIRST, arm second. The kinetic re-arm below injects into whichever
  # instance is live, so an iteration that armed before checking would inject
  # into the INCOMING one and then the "new instance is cold" assertion would
  # be measuring this script's own fling. Checking first means the last
  # injection is always the outgoing instance's, which is exactly the state the
  # swap has to survive.
  if grep -q "Loading plugin.*vtb-b.so" "$ILOG"; then SWAPPED=1; break; fi
  # Re-ask periodically: both `hyprctl reload` and Hyprland's own config
  # watcher end in CConfigManager::reload() -> handlePluginLoads(), but an
  # idle/occluded nested compositor can sit on either for a long time.
  [ $((i % 5)) = 1 ] && echo "   reload: $(hc reload 2>&1 | tr -d '\n')"
  hc clients >/dev/null 2>&1   # a real request, to actually turn the loop
  # RE-ARM the fling every round. A flight is capped at kinetic_max_duration_ms
  # (2000, and there is no runtime knob to lengthen it) while this poll can run
  # for tens of seconds, so a single injection before the loop is always over by
  # the time the swap lands — measured: 17 wheel events, then silence, and the
  # exit-obligation assertion below was vacuous. Each re-injection settles the
  # previous flight first (paying the stop it owed), so the TSV stays a
  # well-formed sequence. With this, the same run delivered 670 events over 20
  # sequences and was mid-ScrollUpdate when the swap landed.
  #
  # Both re-assertions before it are REQUIRED, for two different reasons:
  #
  #  * kinetic_set(true)/friction — CVtbKinetic::onConfigReloaded() CLEARS the
  #    runtime override map, and the config default is kinetic = false. So
  #    `hyprctl reload`, the very mechanism this test swaps the .so with,
  #    switches momentum off and ends the flight with cancel reason
  #    "config-disabled" before the swap has even landed. (Deliberate upstream:
  #    docs/kinetic-scroll.md makes a reload the documented rollback for a
  #    runtime enable.)
  #
  #  * unsafe_wet — NOT in the override map (it is a process-lifetime unlock),
  #    but "process" means the CVtbKinetic INSTANCE, and a hot swap constructs
  #    a new one. The incoming instance has m_unsafeWet = false and refuses
  #    every wet injection at the door (vtbKinetic.cpp:1113) before any counter
  #    is touched: the symptom is a stats blob reading flings 0, ticks 0,
  #    refusals {} while the client sits silent. Cost of re-asserting: nothing.
  if [ "$KINETIC" = 1 ] && [ "$KIN_WET" = 1 ]; then
    hc eval "hl.plugin.hyprvtb.kinetic_set(true)" >/dev/null 2>&1
    hc eval "hl.plugin.hyprvtb.kinetic_set(\"friction\", 0.5)" >/dev/null 2>&1
    hc eval "hl.plugin.hyprvtb.kinetic_set(\"unsafe_wet\", 1)" >/dev/null 2>&1
    hc eval "hl.plugin.hyprvtb.kinetic_test(400, 20, 8, true)" >/dev/null 2>&1
    # Keep the last pre-swap sample of the plugin's own counters: if momentum
    # stops reaching the client, its refusals/cancels map is the only thing
    # that says why, and after the swap the file belongs to the new instance.
    hc eval "hl.plugin.hyprvtb.kinetic_stats()" >/dev/null 2>&1
    cp "$RUN/home/.local/state/hyprvtb/kinetic-stats.txt" "$RUN/kin-stats-pre.txt" 2>/dev/null
    printf 'round %s cursor %s rows %s\n' "$i" "$(hc cursorpos 2>/dev/null | tr -d ' \n')" \
      "$(wc -l < "$KIN_TSV" 2>/dev/null | tr -d ' ')" >> "$RUN/kin-rounds.txt"
  fi
  sleep 0.3
  # ...and sample the client 0.3 s INTO that flight, while it is unambiguously
  # running. Sampling after the full second instead reads whatever state the
  # swap left — and since PLUGIN_EXIT pays the stop the instant it unloads, that
  # always reads "ScrollEnd", i.e. "the fling had already ended", which is
  # exactly the wrong conclusion. The flight lasts ~2.3 s (2000 ms cap + 300 ms
  # withhold), so anything the rest of this round observes is still in flight.
  [ "$KINETIC" = 1 ] && KIN_LAST_PRE="$(tail -n 1 "$KIN_TSV" 2>/dev/null | cut -f6)"
  sleep 0.7
done
if [ "$SWAPPED" = 0 ]; then
  bad "the swap never landed in 60s — everything below would be vacuous, stopping"
  grep -i "plugin\|\[lua\]" "$ILOG" | tail -5 | sed 's/^/         /'
  exit 1
fi
sleep 2
if ! alive; then
  bad "compositor died during the reload itself"
  tail -40 "$RUN/hyprland.log"
  exit 1
fi
ok "compositor survived the reload"
INSTANCES=$(hc plugin list | grep -c 'hyprvtb by' )
if [ "$INSTANCES" = 1 ]; then
  ok "exactly one hyprvtb instance after the swap"
else
  bad "$INSTANCES hyprvtb instances after the swap (want 1)"
fi
if [ -z "$(hc configerrors 2>/dev/null | tr -d '[:space:]')" ]; then
  ok "no config errors"
else
  bad "config errors after the swap: $(hc configerrors)"
fi
if grep -q "Unloading plugin.*vtb-a.so" "$ILOG" && grep -q "Loading plugin.*vtb-b.so" "$ILOG"; then
  ok "Hyprland really unloaded vtb-a.so and mapped vtb-b.so"
else
  bad "no unload/load pair in the log — nothing was swapped, the test is vacuous"
  grep -i "plugin" "$ILOG" | tail -5
fi

step "did the fling survive the swap? (kinetic, integration design 5b)"
if [ "$KINETIC" = 0 ]; then
  skip "kinetic steps were skipped above — nothing to assert here"
else
  # 1. The whole point: a timer firing into the unmapped image SIGSEGVs here.
  if alive; then
    ok "compositor alive after a reload with momentum in flight"
  else
    bad "compositor DIED on a reload with momentum in flight — the timer outlived its .so"
    tail -40 "$RUN/hyprland.log"
    exit 1
  fi
  # 2. The incoming instance must start cold: no trace, no timer, no state.
  #    (It also starts with kinetic OFF — the enable above was a RUNTIME
  #    override on the outgoing instance, so a state of "disabled" is fine;
  #    only an ACTIVE-looking state or a non-empty trace is a leak.)
  # kinetic_dump() returns nothing through hyprctl (eval never hands back a
  # value): it PUBLISHES its JSON to $HOME/.local/state/hyprvtb, where $HOME is
  # the compositor's — our own $RUN/home. Call it, then read the file.
  #
  # ...and the assertion has to survive the fact that DETECTION LAGS THE SWAP.
  # Hyprland's log is buffered, so "Loading plugin vtb-b.so" surfaces seconds
  # after the load really happened: measured here, the re-arm loop above went
  # on injecting for ~9 s INTO THE INCOMING INSTANCE before the line appeared
  # (proved by its own introspection — the blob carried this script's overrides
  # {enabled, friction 0.5}, unsafe_wet true and a seq of exactly 9 stats calls
  # plus every dump since). So "the new instance has a trace" is NOT evidence
  # of a leak; it is this test's own fling, and asserting an empty trace here
  # only ever measured the detection lag.
  #
  # What a leak actually looks like is a flight that never ends: a phase stuck
  # at flying/grace, or a tick timer still firing with nobody driving it. Both
  # are contamination-proof, because they are about MOTION, not about content.
  # So: let everything settle (a flight is capped at 2000 ms + a 300 ms
  # withheld stop), then require the engine to be at rest and to STAY at rest.
  KIN_DUMPF="$RUN/home/.local/state/hyprvtb/kinetic-dump.json"
  KIN_STATSF="$RUN/home/.local/state/hyprvtb/kinetic-stats.txt"
  sleep 3
  rm -f "$KIN_DUMPF"
  hc eval "hl.plugin.hyprvtb.kinetic_dump()" >/dev/null 2>&1
  for _ in $(seq 1 20); do [ -s "$KIN_DUMPF" ] && break; sleep 0.1; done
  cp "$KIN_DUMPF" "$RUN/kin-dump.txt" 2>/dev/null || : > "$RUN/kin-dump.txt"
  python3 - "$RUN/kin-dump.txt" <<'PY'
import json, re, sys
m = re.search(r"\{.*\}", open(sys.argv[1]).read(), re.S)
if not m:
    sys.exit(2)
try:
    d = json.loads(m.group(0))
except Exception:
    sys.exit(2)
tr = d.get("trace") or []
st = str(d.get("state", "")).lower()
# At rest: not mid-flight, and whatever it last emitted was properly closed
# with the terminal 0.0 that IS the protocol axis_stop.
if any(w in st for w in ("flying", "grace", "tracking", "coast", "decay")):
    sys.exit(1)
sys.exit(0 if (not tr or float(tr[-1][1]) == 0.0) else 1)
PY
  case $? in
    0) ok "the engine is at rest after the swap — state idle, last flight closed with its stop" ;;
    1) bad "the engine is not at rest after the swap: $(head -c 200 "$RUN/kin-dump.txt")" ;;
    *) bad "kinetic_dump() after the swap returned no JSON: $(head -c 200 "$RUN/kin-dump.txt")" ;;
  esac
  # No timer leaked: ticks must not move while nothing is flying. A timer that
  # survived the swap is the 2.65-class crash waiting for its callback.
  hc eval "hl.plugin.hyprvtb.kinetic_stats()" >/dev/null 2>&1
  KIN_T1="$(sed -n '2s/.*"ticks":\([0-9][0-9]*\).*/\1/p' "$KIN_STATSF" 2>/dev/null)"
  sleep 1.5
  hc eval "hl.plugin.hyprvtb.kinetic_stats()" >/dev/null 2>&1
  KIN_T2="$(sed -n '2s/.*"ticks":\([0-9][0-9]*\).*/\1/p' "$KIN_STATSF" 2>/dev/null)"
  if [ -n "$KIN_T1" ] && [ "$KIN_T1" = "$KIN_T2" ]; then
    ok "no timer left running across the swap (ticks steady at $KIN_T1 over 1.5 s)"
  else
    bad "the tick timer is still firing after the swap: ticks $KIN_T1 -> $KIN_T2"
  fi
  note "answering instance: $(sed -n 's/.*\("seq":[0-9]*\).*/\1/p' "$RUN/kin-dump.txt" 2>/dev/null), $(hc plugin list | grep -c 'hyprvtb by') plugin(s) loaded"
  # 3. The exit obligation. A client left mid-sequence believes a scroll is
  #    still in progress, forever — nothing else in this plugin has ever owed a
  #    client anything at unload.
  if [ "$KIN_WET" = 1 ]; then
    for _ in $(seq 1 20); do
      sleep 0.25
      [ "$(tail -n 1 "$KIN_TSV" 2>/dev/null | cut -f6)" = "ScrollEnd" ] && break
    done
    KIN_LAST="$(tail -n 1 "$KIN_TSV" 2>/dev/null | cut -f6)"
    note "client saw $(wc -l < "$KIN_TSV" | tr -d ' ') wheel events over $(cut -f6 "$KIN_TSV" | grep -c ScrollEnd) sequence end(s); last phase before the swap: ${KIN_LAST_PRE:-?}"
    note "last pre-swap counters: $(sed -n 2p "$RUN/kin-stats-pre.txt" 2>/dev/null)"
    note "poll rounds: $(tr '\n' ';' < "$RUN/kin-rounds.txt" 2>/dev/null)"
    if [ "$KIN_LAST" = "ScrollEnd" ]; then
      ok "the client's last event is ScrollEnd — the sequence was closed"
    else
      bad "the client's last event is '$KIN_LAST' — no axis_stop was ever sent, the client is stranded mid-scroll"
    fi
    case "${KIN_LAST_PRE:-}" in
      ScrollEnd) note "the fling had already ended before the swap landed (the async swap poll can" ;
                 note "     outlast kinetic_max_duration_ms), so that stop is the ordinary one, not PLUGIN_EXIT's" ;;
      "")        note "no pre-swap sample of the client's tail — cannot say whether momentum was in flight" ;;
      *)         ok "momentum WAS in flight when the swap landed (last pre-swap phase: $KIN_LAST_PRE)" ;;
    esac
  else
    note "no wheel events ever reached the client — the exit-obligation half is untested"
  fi
fi

step "who owns the hidden window's titlebar after the swap?"
# The discriminator. On a swap Hyprland is supposed to strip the old library's
# decorations, and the incoming instance decorates every existing window --
# hidden ones included -- so the count here must be exactly 2 (bar + shadow)
# AND they must belong to the NEW instance.
#
# Before 2.65 both halves failed silently: Hyprland's removal is a no-op on a
# hidden window (CWindow::updateWindowDecos early-returns on isHidden), and the
# incoming instance skipped hidden windows -- so the 2 decorations found here
# were the OLD library's, vtable-dangling, waiting for ~CWindow.
DECOS=$(hc -j decorations "address:$ADDR" | jq -r '[.[]|select(.decorationName|startswith("Hyprvtb"))]|length')
if [ "$DECOS" = 2 ]; then
  ok "2 hyprvtb decorations on the hidden window (one bar + one shadow)"
else
  bad "$DECOS hyprvtb decorations on the hidden window (want 2)"
  hc decorations "address:$ADDR" | sed 's/^/         /'
fi
step "did the window STAY rolled up across the swap? (2.71)"
# PLUGIN_EXIT must un-roll every window on the way out — a hidden window whose
# decoration is about to be unmapped is the crash this whole file is about. But
# an un-rolled window is not where the user left it: before 2.71 every rolled-up
# window snapped open on a `hyprctl reload` and stayed open. The outgoing
# instance now writes its roll/minimize states to handoff.tsv and the incoming
# one re-applies them, so the round trip is invisible.
#
# NB this asserts nothing on the FIRST swap from a pre-2.71 build: the outgoing
# instance is the one that has to write the file. Both halves here are the same
# build, so it applies.
if [ "$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.hidden')" = "true" ]; then
  ok "still rolled up after the swap — the handoff carried the state"
else
  bad "the window snapped open across the swap — handoff.tsv was not written or not applied"
fi

step "does the NEW instance own the titlebar?"
# rollup() walks the live plugin's own bar list, so it can only move a window
# the CURRENT .so decorates — a stale titlebar just sits there. The window is
# rolled up (asserted above), so ONE call must bring it back out.
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
if ! alive; then
  bad "compositor DIED rolling the window back out — it was driving a dead .so"
  tail -40 "$RUN/hyprland.log"
  exit 1
fi
if [ "$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.hidden')" = "false" ]; then
  ok "the new instance owns it — rollup() brought the window back"
else
  # The un-hide happens at the END of the reveal animation, so in a frame-
  # starved nested compositor a WORKING rollup() and a stale titlebar look
  # identical from here. The decoration-ownership check above (2 decos, and
  # they belong to the incoming instance) and the survived-close check below
  # are the frame-independent evidence, and both stay strict.
  animfail "rollup() did nothing: the hidden window's titlebar belongs to the UNLOADED .so"
fi

step "did dlclose actually unmap the old image?"
# If vtb-a.so is still mapped, no dangling call can fault and the test below is
# not proving anything — say so out loud rather than passing quietly.
MAPS=$(cat "/proc/$HYPRPID/maps" 2>/dev/null)
if [ -z "$MAPS" ]; then
  printf '   \033[33mnote\033[0m cannot read /proc/%s/maps — skipping the unmap check\n' "$HYPRPID"
elif case "$MAPS" in *vtb-a.so*) true ;; *) false ;; esac; then   # no pipe: grep -q would SIGPIPE the printf
  printf '   \033[33mnote\033[0m vtb-a.so is STILL MAPPED after the unload (dlclose kept it):\n'
  grep "vtb-a.so" "/proc/$HYPRPID/maps" | head -3 | sed 's/^/         /'
  UNMAPPED=0
else
  ok "vtb-a.so is gone from the address space (a stale call would fault)"
  UNMAPPED=1
fi

step "closing the hidden window — THE CRASH: ~CWindow calls into the unmapped .so"
# Kill the CLIENT, not the window: a dispatched close is only a polite request
# (and a hidden window may never act on it), while the surface destroy is what
# runs ~CWindow and, with it, the destructor of a deco whose code is gone.
CPID=$(hc clients -j | jq -r --arg a "$ADDR" '.[]|select(.address==$a)|.pid')
[ -n "$CPID" ] && [ "$CPID" != "null" ] && kill -9 "$CPID" 2>/dev/null
for _ in $(seq 1 20); do
  sleep 0.5
  hc clients -j 2>/dev/null | jq -e --arg a "$ADDR" 'any(.[]; .address==$a)' >/dev/null || break
done
if alive && hc clients -j | jq -e --arg a "$ADDR" 'any(.[]; .address==$a)' >/dev/null; then
  bad "the window never went away — the destroy path was never exercised"
fi
sleep 2
if alive; then
  ok "compositor survived closing the window that held the swapped-out deco"
else
  bad "compositor DIED closing that window — the deco outlived its .so"
  tail -40 "$RUN/hyprland.log"
fi

step "one more window, opened and closed entirely after the swap"
hc eval "hl.exec_cmd('kitty --class hyprvtb-hs2')" >/dev/null
for _ in $(seq 1 40); do
  sleep 0.5
  ADDR2=$(hc clients -j | jq -r '.[]|select(.class=="hyprvtb-hs2" and .mapped)|.address' | head -1)
  [ -n "$ADDR2" ] && break
done
if [ -n "${ADDR2:-}" ]; then
  CPID2=$(hc clients -j | jq -r --arg a "$ADDR2" '.[]|select(.address==$a)|.pid')
  [ -n "$CPID2" ] && [ "$CPID2" != "null" ] && kill -9 "$CPID2" 2>/dev/null
  sleep 3
  alive && ok "compositor survived a full open/close cycle on the new plugin" \
        || bad "compositor died on a post-swap window"
else
  printf '   \033[33mnote\033[0m second window never mapped (compositor may already be gone)\n'
  alive || bad "compositor is not alive"
fi

step "log check"
if grep -qiE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|has crashed|safe mode' "$RUN/hyprland.log" "$ILOG"; then
  bad "the nested log has an abort/assert:"
  grep -inhE 'ASSERTION FAILED|Aborting|terminate called|Segmentation fault|has crashed|safe mode' "$RUN/hyprland.log" "$ILOG" | head
else
  ok "no aborts, asserts or safe-mode entries"
fi

hc dispatch "hl.dsp.exit()" >/dev/null 2>&1
sleep 1

if [ "$FAILED" = 0 ]; then
  printf '\n\033[32mHOT-SWAP TEST PASSED\033[0m — a reload under a hidden window is survivable.\n'
else
  printf '\n\033[31mHOT-SWAP TEST FAILED\033[0m — log kept at /tmp/hyprvtb-hotswap.log\n'
  cp "$RUN/hyprland.log" /tmp/hyprvtb-hotswap.log 2>/dev/null
  # The per-instance log is where the [PluginSystem] and [lua] lines live, and
  # it disappears with the instance — keep it too, it is the only record of
  # what the swap actually did.
  cp "$ILOG" /tmp/hyprvtb-hotswap-instance.log 2>/dev/null
fi
exit "$FAILED"
