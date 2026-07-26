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
# Usage: ./hotswap-test.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed. Point it
# at a pre-2.65 build and it should FAIL — that is the bug reproducing.

set -uo pipefail

RUN="/tmp/vtbhs$$"
mkdir -p "$RUN"

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "no WAYLAND_DISPLAY — run this from inside the graphical session."
  exit 1
fi
case "$WAYLAND_DISPLAY" in
  /*) PARENT_WL="$WAYLAND_DISPLAY" ;;
  *)  PARENT_WL="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/$WAYLAND_DISPLAY" ;;
esac

cleanup() {
  pkill -9 -f "Hyprland -c $RUN/hyprland.lua" 2>/dev/null
  [ -n "${HYPRPID:-}" ] && kill -9 "$HYPRPID" 2>/dev/null
  sleep 0.5
  rm -rf "$RUN"
  G="$HOME/.local/state/hyprvtb/geometry.tsv"
  if [ -f "$G" ] && grep -q '^aquamarine	' "$G"; then
    grep -v '^aquamarine	' "$G" > "$G.tmp" && mv "$G.tmp" "$G"
  fi
}
trap cleanup EXIT

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0

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
  # Re-ask periodically: both `hyprctl reload` and Hyprland's own config
  # watcher end in CConfigManager::reload() -> handlePluginLoads(), but an
  # idle/occluded nested compositor can sit on either for a long time.
  [ $((i % 5)) = 1 ] && echo "   reload: $(hc reload 2>&1 | tr -d '\n')"
  hc clients >/dev/null 2>&1   # a real request, to actually turn the loop
  sleep 1
  if grep -q "Loading plugin.*vtb-b.so" "$ILOG"; then SWAPPED=1; break; fi
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
  bad "rollup() did nothing: the hidden window's titlebar belongs to the UNLOADED .so"
fi

step "did dlclose actually unmap the old image?"
# If vtb-a.so is still mapped, no dangling call can fault and the test below is
# not proving anything — say so out loud rather than passing quietly.
MAPS=$(cat "/proc/$HYPRPID/maps" 2>/dev/null)
if [ -z "$MAPS" ]; then
  printf '   \033[33mnote\033[0m cannot read /proc/%s/maps — skipping the unmap check\n' "$HYPRPID"
elif printf '%s' "$MAPS" | grep -q "vtb-a.so"; then
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
fi
exit "$FAILED"
