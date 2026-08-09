#!/usr/bin/env bash
# Get ComfyUI out of the way of a heavy rebuild — without ever killing a render.
#
# The 2026-08-09 freeze was a rebuild compiling ollama's CUDA kernels while a
# ComfyUI video run held the other half of 30 GiB. Capping the build cgroup
# (sys/nix-build-limits.nix) makes that survivable; this makes the two never
# meet, which is better: a throttled build and a throttled render are both bad
# outcomes, and they are avoidable by simply not overlapping.
#
# The order is his, and each step exists for a reason:
#
#   1. A render in flight is NEVER interrupted. We wait for it — however long.
#   2. Weights merely sitting in VRAM are not a reason to wait: they are freed
#      (`/free`), which costs him a reload later and nothing else.
#   3. Then comfy is stopped AND runtime-masked, so a new render cannot start
#      halfway through the build. Masking is the half that matters: painter
#      fires `startBackend` on its own launch (main.py:790), so a stop alone
#      would be undone by him opening painter while the build ran.
#   4. He is told, both times, by name: a backend that vanished with no
#      explanation is exactly the "silent change" docs/DESIGN.md §10 forbids.
#   5. Resume restores only what we changed, and only if we changed it — a
#      comfy that was already down before the rebuild stays down.
#
# Usage:  comfy-gate.sh status | wait [timeout] | suspend | resume
#
# Runs as root (from rebuild-top) or as lam by hand; the user-side half is
# re-entered with runuser when root. Idempotent: every verb is safe to repeat,
# and `resume` with no suspension recorded does nothing at all.
set -uo pipefail

URL=${COMFY_GATE_URL:-http://127.0.0.1:8188}   # overridden by the harness only
UNIT=comfy-painter.service
STATE=/run/comfy-gate.suspended   # tmpfs: a reboot mid-rebuild leaves nothing to undo
POLL=10

U=${SUDO_USER:-$(id -un)}
UID_=$(id -u "$U")

# Every systemctl --user / notify-send here has to reach HIS session bus, which
# root does not have. runuser + the two variables is the same shape the
# rebuild-top wrapper already uses for preflight.
as_user() {
  if [ "$(id -u)" = 0 ]; then
    runuser -u "$U" -- env XDG_RUNTIME_DIR="/run/user/$UID_" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_/bus" "$@"
  else
    "$@"
  fi
}

unit_active() { as_user systemctl --user is-active --quiet "$UNIT"; }

# `systemctl --user mask --runtime` DOES NOT WORK for this unit, and fails
# silently: it writes its /dev/null symlink into $XDG_RUNTIME_DIR/systemd/user,
# which in the USER manager's search path ranks BELOW $XDG_CONFIG_HOME/systemd/
# user — where home-manager puts comfy-painter.service. Measured 2026-08-09:
# symlink present, exit 0, `is-enabled` still `enabled-runtime`, and the unit
# started perfectly happily. `user.control` is the directory that outranks
# everything, so the mask goes there by hand. Anything left behind dies with
# the tmpfs at reboot.
CTL="/run/user/$UID_/systemd/user.control"
mask_on() {
  as_user mkdir -p "$CTL" \
    && as_user ln -sfn /dev/null "$CTL/$UNIT" \
    && as_user systemctl --user daemon-reload
}
mask_off() {
  as_user rm -f "$CTL/$UNIT"
  as_user systemctl --user daemon-reload
}

# queue_remaining counts the running job AND anything queued behind it, which is
# the right definition of "still busy": draining the queue is one wait, not one
# per prompt. An unreachable comfy is NOT reported as rendering — a backend that
# is still starting up has nothing in flight to protect.
queue_remaining() {
  local body
  body=$(curl -sf -m 3 "$URL/prompt" 2>/dev/null) || { echo ""; return; }
  printf '%s' "$body" | grep -o '"queue_remaining"[[:space:]]*:[[:space:]]*[0-9]\+' \
    | grep -o '[0-9]\+$' | head -1
}

notify() {
  # Echoed as well as sent, so the rebuild log says what he was told.
  echo "comfy-gate: notify: $1 — $2" >&2
  # COMFY_GATE_NO_NOTIFY exists for the harness: a test may not put a toast on
  # his screen (AGENTS.md, "Testing without interfering with the user").
  [ "${COMFY_GATE_NO_NOTIFY:-0}" = 1 ] && return 0
  # -- before the positionals: notify-send parses a leading dash in the summary
  # or body as an option and exits 1 with no notification.
  as_user notify-send -a "rebuild" -u normal -- "$1" "$2" >/dev/null 2>&1 || true
}

status() {
  if ! unit_active; then echo down; return; fi
  local q; q=$(queue_remaining)
  if [ -z "$q" ]; then echo starting; return; fi
  if [ "$q" -gt 0 ]; then echo rendering; else echo idle; fi
}

# Waits while a render is in flight. The timeout is a backstop against a hung
# queue, not a deadline for his work: it defaults to an hour and the caller
# decides what a timeout means (rebuild-top declines to suspend and builds
# under the cgroup caps instead, which is the throttled path).
do_wait() {
  local timeout=${1:-3600} waited=0 said=0
  while [ "$(status)" = rendering ]; do
    if [ "$said" = 0 ]; then
      echo "comfy-gate: a render is in flight — waiting for it to finish" >&2
      said=1
    fi
    if [ "$waited" -ge "$timeout" ]; then
      echo "comfy-gate: still rendering after ${timeout}s — giving up the wait" >&2
      return 1
    fi
    sleep "$POLL"; waited=$((waited + POLL))
  done
  [ "$said" = 1 ] && echo "comfy-gate: render finished after ${waited}s" >&2
  return 0
}

do_suspend() {
  if ! unit_active; then
    echo "comfy-gate: comfy is not running — nothing to suspend" >&2
    return 0
  fi
  if [ "$(status)" = rendering ]; then
    echo "comfy-gate: REFUSING to suspend a running render" >&2
    return 1
  fi
  # Free first: stopping the unit would drop the weights anyway, but asking
  # comfy to unload them itself lets it tear down its CUDA context cleanly.
  curl -sf -m 10 -X POST -H 'Content-Type: application/json' \
    -d '{"unload_models": true, "free_memory": true}' "$URL/free" >/dev/null 2>&1 || true
  as_user systemctl --user stop "$UNIT" || return 1
  mask_on
  masked=$(as_user systemctl --user is-enabled "$UNIT" 2>/dev/null)
  case "$masked" in
    masked*) ;;
    *) echo "comfy-gate: WARN: comfy is stopped but NOT masked ($masked) — opening painter could start it mid-build" >&2 ;;
  esac
  : >"$STATE"
  echo "comfy-gate: comfy suspended (stopped and runtime-masked)" >&2
  notify "ComfyUI suspended" "Rebuilding the system — the backend is stopped and will come back on its own."
  return 0
}

do_resume() {
  [ -e "$STATE" ] || return 0
  mask_off
  rm -f "$STATE"
  if as_user systemctl --user start "$UNIT"; then
    echo "comfy-gate: comfy resumed" >&2
    notify "ComfyUI back" "The rebuild is done and the backend is starting — the first render reloads its weights."
  else
    echo "comfy-gate: FAILED to restart comfy — start it from painter's settings drawer" >&2
    notify "ComfyUI did not restart" "The rebuild is done but comfy-painter failed to start. Start it from painter's settings drawer."
  fi
}

case "${1:-status}" in
  status)  status ;;
  wait)    do_wait "${2:-3600}" ;;
  suspend) do_suspend ;;
  resume)  do_resume ;;
  *) echo "usage: comfy-gate.sh status | wait [timeout] | suspend | resume" >&2; exit 2 ;;
esac
