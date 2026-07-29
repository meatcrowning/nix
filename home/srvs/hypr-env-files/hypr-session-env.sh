#!/bin/sh
# hypr-session-env.sh — resolve the LIVE compositor, then run something under it.
#
# WHY THIS EXISTS
#
# The systemd user manager's HYPRLAND_INSTANCE_SIGNATURE / WAYLAND_DISPLAY are
# not trustworthy, and never were. Hyprland itself — not our config — runs, at
# every startup (string is in the Hyprland binary, verified on 0.56.0):
#
#   systemctl --user import-environment DISPLAY WAYLAND_DISPLAY \
#       HYPRLAND_INSTANCE_SIGNATURE XDG_CURRENT_DESKTOP QT_QPA_PLATFORMTHEME \
#       PATH XDG_DATA_DIRS
#   dbus-update-activation-environment --systemd  (same list)
#
# and the mirror-image `unset-environment` at clean shutdown. That store is
# manager-global, has one slot per variable and no notion of who owns it, so
# EVERY Hyprland process on the machine writes over the previous one:
#
#   - a NESTED compositor (hyprvtb/tools/nested-smoke.sh, hotswap-test.sh,
#     kinetic-test.sh) points the whole user manager at itself for its lifetime;
#   - killed with SIGKILL — which is exactly how those harnesses tear down —
#     it never runs the unset, so its dead signature is left in place for the
#     rest of the login;
#   - allowed to exit cleanly it is no better: the unset DELETES the real
#     session's values rather than restoring them.
#
# Measured on `top` 2026-07-28: the manager held a signature whose compositor
# had been dead for an hour (`hyprctl` -> "Couldn't connect to
# .../.socket.sock"), and WAYLAND_DISPLAY=wayland-2 while the session ran on
# wayland-1. Anything that inherited it — wal-set.service being the one that
# matters — would have talked to nothing, silently, with exit status 0.
#
# So: do not inherit, RESOLVE. An agent runs nested compositors here routinely,
# and a fix that merely re-imports at the right moment is undone by the next one.
#
# HOW IT RESOLVES  (no forks, no hyprctl round-trip)
#
# $XDG_RUNTIME_DIR/hypr/<sig>/hyprland.lock is two lines: the compositor's PID
# and its wayland socket name. An instance is a candidate when that PID is still
# alive AND the directory still has a .socket.sock. Among candidates the REAL
# session is the one that is not itself a Wayland client: a nested Hyprland is
# started with WAYLAND_DISPLAY pointing at its parent, and that shows in
# /proc/<pid>/environ; the session compositor on DRM has no WAYLAND_DISPLAY
# there. Ties break oldest-first (the signature's middle field is the start
# time), because the session always predates the harness testing it.
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

  # A nested Hyprland is a client of another compositor and says so in the
  # environment it was started with. rank 0 = the session, rank 1 = nested.
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
    # Only the two variables that IDENTIFY a compositor are checked. PATH and
    # friends are clobbered by the same mechanism but are identical between a
    # session and a nested instance launched from it, so a mismatch there is
    # not evidence of anything.
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
    # comes up pointing at the dead instance and screen-share fails for the
    # rest of the login. dbus-update-activation-environment reads its OWN
    # environment, hence the export.
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
