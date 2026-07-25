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
# seat), so expect a second Hyprland to open as a WINDOW for ~20 seconds. It
# is a wholly separate compositor: it never touches the live session, its own
# windows, or its plugin instance.
#
# Usage: ./nested-smoke.sh [path/to/libhyprvtb.so]
# Default plugin: whatever the last `nixos-rebuild switch` installed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
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

cleanup() {
  [ -n "${HYPRPID:-}" ] && kill "$HYPRPID" 2>/dev/null
  sleep 0.5
  [ -n "${HYPRPID:-}" ] && kill -9 "$HYPRPID" 2>/dev/null
  rm -rf "$RUN"
}
trap cleanup EXIT

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0

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

step "starting a nested Hyprland (a window on this session, ~20s)"
BEFORE=$(hyprctl instances -j 2>/dev/null | grep -o '"instance": *"[^"]*"' | cut -d'"' -f4 | sort)
env -u HYPRLAND_INSTANCE_SIGNATURE \
    WAYLAND_DISPLAY="$PARENT_WL" \
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

# Every hyprctl below is explicitly aimed at the NESTED instance. Never let
# one of these hit the live session.
hc() { hyprctl -i "$SIG" "$@"; }

step "plugin loaded?"
if hc plugin list | grep -q hyprvtb; then
  ok "$(hc plugin list | grep -i version | head -1 | tr -d '\t')"
else
  bad "hyprvtb is not in the nested compositor's plugin list"
  tail -30 "$LOGDIR/hyprland.log"
  exit 1
fi

step "opening a window (it must get decorated)"
hc dispatch "hl.dsp.exec('kitty --class hyprvtb-smoke')" >/dev/null 2>&1 || \
  hc dispatch exec "kitty --class hyprvtb-smoke" >/dev/null 2>&1
for _ in $(seq 1 40); do
  sleep 0.5
  ADDR=$(hc clients -j | grep -B20 'hyprvtb-smoke' | grep -o '"address": *"[^"]*"' | head -1 | cut -d'"' -f4)
  [ -n "$ADDR" ] && break
done
[ -n "$ADDR" ] || { bad "the test window never mapped"; tail -30 "$LOGDIR/hyprland.log"; exit 1; }
ok "window $ADDR"

alive() { kill -0 "$HYPRPID" 2>/dev/null && hc version >/dev/null 2>&1; }

step "roll up (the v2.48 abort path: deferred callback over a deco weak ref)"
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
alive && ok "compositor survived the roll-up" || bad "compositor died during roll-up"

step "roll back out (open-reveal -> beginRollReveal doLater)"
hc eval "hl.plugin.hyprvtb.rollup('address:$ADDR')" >/dev/null
sleep 2
alive && ok "compositor survived the roll-out" || bad "compositor died during roll-out"

step "session save"
hc eval "hl.plugin.hyprvtb.save_session()" >/dev/null
sleep 1
alive && ok "compositor survived save_session" || bad "compositor died during save_session"

step "graceful close (the animated close path)"
hc eval "hl.plugin.hyprvtb.close_active()" >/dev/null
sleep 2
alive && ok "compositor survived the close" || bad "compositor died during the close"

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
