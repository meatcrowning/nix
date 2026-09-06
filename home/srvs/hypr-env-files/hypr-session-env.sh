#!/bin/sh
# hypr-session-env.sh — resolve the live compositor, then run something under
# it.
#
# The systemd user manager's HYPRLAND_INSTANCE_SIGNATURE / WAYLAND_DISPLAY are
# not trustworthy: Hyprland imports them at startup and unsets them at clean
# shutdown, so nested compositors and SIGKILL can leave the manager pointed at
# the wrong instance. This script resolves the live session from
# `$XDG_RUNTIME_DIR/hypr/<sig>/hyprland.lock` instead of inheriting those
# values.
#
# A candidate instance must still have its socket and a live PID. The real
# session is the one that is not itself a Wayland client (nested Hyprland has
# WAYLAND_DISPLAY in /proc/<pid>/environ); ties break oldest-first. `--restore`
# pushes the resolved values back into both the user manager and the D-Bus
# activation store.
#
# USAGE
#   hypr-session-env.sh CMD [ARGS...]   run CMD with the corrected env
#   hypr-session-env.sh --print         KEY=VALUE lines, for `eval`/sourcing
#   hypr-session-env.sh --check         exit 0 if the systemd user manager
#                                       agrees with reality; 1 + diagnostic if
#                                       not (tools/preflight.sh calls this)
#   hypr-session-env.sh --restore       push the resolved values back into the
#                                       user manager + dbus activation store.
#                                       The nested harnesses call this on
#                                       teardown; it is the only way to fix the
#                                       D-Bus half, which units cannot wrap
#                                       (xdg-desktop-portal-hyprland is
#                                       activated, not started by us).
#
# Exit 3 = no live compositor at all (no session, or a bare TTY).
set -u

XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
HYPR_ROOT="$XDG_RUNTIME_DIR/hypr"

SIG=""
WL=""
BEST_RANK=9
BEST_TIME=""

[ -d "$HYPR_ROOT" ] || { echo "hypr-session-env: no $HYPR_ROOT" >&2; exit 3; }

for dir in "$HYPR_ROOT"/*/; do
  [ -d "$dir" ] || continue
  sig=$(basename "$dir")
  lock="$dir/hyprland.lock"
  [ -S "$dir/.socket.sock" ] || continue
  [ -r "$lock" ] || continue

  pid=$(sed -n 1p "$lock" 2>/dev/null)
  wl=$(sed -n 2p "$lock" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) continue ;; esac
  [ -d "/proc/$pid" ] || continue          # dead compositor, stale directory
  [ -n "$wl" ] || continue

  # A nested Hyprland is a client of another compositor and says so in its
  # environment. rank 0 = the session, rank 1 = nested.
  rank=0
  if tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -q '^WAYLAND_DISPLAY='; then
    rank=1
  fi

  # <commit>_<starttime>_<random>: the middle field orders instances by age.
  t=$(echo "$sig" | awk -F_ 'NF>=3 {print $(NF-1)}')
  case "$t" in ''|*[!0-9]*) t=0 ;; esac

  if [ "$rank" -lt "$BEST_RANK" ] || { [ "$rank" -eq "$BEST_RANK" ] && [ -n "$BEST_TIME" ] && [ "$t" -lt "$BEST_TIME" ]; }; then
    BEST_RANK=$rank; BEST_TIME=$t; SIG=$sig; WL=$wl
  fi
done

[ -n "$SIG" ] || { echo "hypr-session-env: no live Hyprland instance under $HYPR_ROOT" >&2; exit 3; }

case "${1-}" in
  --print)
    echo "HYPRLAND_INSTANCE_SIGNATURE=$SIG"
    echo "WAYLAND_DISPLAY=$WL"
    echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
    exit 0
    ;;
  --check)
    # Only the two variables that identify a compositor are checked. PATH and
    # friends are not evidence either way.
    env_sig=$(systemctl --user show-environment 2>/dev/null | sed -n 's/^HYPRLAND_INSTANCE_SIGNATURE=//p')
    env_wl=$(systemctl --user show-environment 2>/dev/null | sed -n 's/^WAYLAND_DISPLAY=//p')
    if [ "$env_sig" = "$SIG" ] && [ "$env_wl" = "$WL" ]; then
      exit 0
    fi
    echo "systemd user manager points at the WRONG compositor:"
    echo "  manager: HYPRLAND_INSTANCE_SIGNATURE=${env_sig:-<unset>} WAYLAND_DISPLAY=${env_wl:-<unset>}"
    echo "  live:    HYPRLAND_INSTANCE_SIGNATURE=$SIG WAYLAND_DISPLAY=$WL"
    echo "  Every Hyprland process overwrites this store, so a nested test"
    echo "  compositor (nested-smoke.sh / hotswap-test.sh / kinetic-test.sh)"
    echo "  leaves its own dead signature behind when SIGKILLed. Fix with:"
    echo "    ~/.config/scripts/hypr-session-env.sh --restore"
    exit 1
    ;;
  --restore)
    systemctl --user set-environment \
      "HYPRLAND_INSTANCE_SIGNATURE=$SIG" "WAYLAND_DISPLAY=$WL" || exit 1
    # D-Bus activation store too, or an activated xdg-desktop-portal-hyprland
    # comes up pointing at the dead instance and screen-share fails.
    if command -v dbus-update-activation-environment >/dev/null 2>&1; then
      HYPRLAND_INSTANCE_SIGNATURE="$SIG" WAYLAND_DISPLAY="$WL" \
        dbus-update-activation-environment --systemd \
          WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE >/dev/null 2>&1 || true
    fi
    echo "hypr-session-env: restored HYPRLAND_INSTANCE_SIGNATURE=$SIG WAYLAND_DISPLAY=$WL"
    exit 0
    ;;
  '')
    echo "usage: hypr-session-env.sh {CMD [ARGS...] | --print | --check | --restore}" >&2
    exit 2
    ;;
esac

export HYPRLAND_INSTANCE_SIGNATURE="$SIG"
export WAYLAND_DISPLAY="$WL"
export XDG_RUNTIME_DIR
exec "$@"
