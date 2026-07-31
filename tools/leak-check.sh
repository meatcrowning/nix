#!/bin/sh
# leak-check.sh — did a test leak into the user's live session?
#
# The enforcement half of AGENTS.md -> "Testing without interfering with the
# user". That rule is otherwise kept by discipline alone, and on 2026-07-30 it
# was not kept: workers took his keyboard and pointer focus while he was using
# the machine. This script cannot stop a test from grabbing focus, but it does
# catch the *residue* every leaked test leaves behind, at the one moment every
# agent here is already required to pass through: preflight.
#
# Four states, all of them things a harness is supposed to have cleaned up:
#   1. The systemd user manager pointing at a compositor that is not his
#      (hypr-session-env.sh --check — reused, never reimplemented; the full
#      story of why that store goes wrong is in AGENTS.md under
#      home/srvs/hypr-env.nix).
#   2. $XDG_RUNTIME_DIR/hypr/<sig>/ lock directories whose PID is dead.
#   3. A second, live Hyprland that is not the session one — a nested test
#      compositor still running, still able to hold a seat and a clipboard.
#   4. A sandbox monitor left standing (/tmp/vtb-sandbox), i.e. `sandbox.sh
#      start` without its `stop`.
#
# WARNS ONLY, AND MUST STAY THAT WAY. Every one of these states is one a real
# login can legitimately be in — he starts nested compositors himself, and a
# TTY has no session at all. Blocking his rebuild on a false positive is worse
# than the bug this exists to catch, so preflight ignores the exit status.
# Exit 1 means "found something" for any other caller that wants it.
set -u

found=0
warn() { found=1; printf '%s\n' "$@"; }

HYPR_ROOT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
ENVCHK="$HOME/.config/scripts/hypr-session-env.sh"
REPAIR="  repair:  $ENVCHK --restore"

# 1. Manager environment. rc 1 = drift; rc 3 = no live Hyprland (TTY, ssh,
#    another session type) and is not a fault.
live_sig=""
if [ -x "$ENVCHK" ]; then
  out=$("$ENVCHK" --check 2>&1); rc=$?
  [ "$rc" -eq 1 ] && warn "WARN: leaked test - $out"
  live_sig=$("$ENVCHK" --print 2>/dev/null | sed -n 's/^HYPRLAND_INSTANCE_SIGNATURE=//p')
fi

# 2 + 3. Lock directories: dead PID = a compositor that was SIGKILLed and never
#        cleaned up after; live PID that is not the session's = one still running.
for d in "$HYPR_ROOT"/*/; do
  [ -f "$d/hyprland.lock" ] || continue
  sig=$(basename "$d")
  pid=$(sed -n 1p "$d/hyprland.lock" 2>/dev/null)
  wl=$(sed -n 2p "$d/hyprland.lock" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) continue ;; esac
  if ! kill -0 "$pid" 2>/dev/null; then
    warn "WARN: dead compositor lock left behind: $d (pid $pid, ${wl:-?})" \
         "      A nested test compositor was killed without tearing down." \
         "      Safe to remove once nothing points at it:  rm -rf $d" \
         "$REPAIR"
  elif [ -n "$live_sig" ] && [ "$sig" != "$live_sig" ]; then
    warn "WARN: a second Hyprland is RUNNING: pid $pid on ${wl:-?} (not his session)." \
         "      If that is a test compositor, stop it - while it lives it owns a" \
         "      seat, a clipboard and this manager's environment." \
         "$REPAIR"
  fi
done

# 4. Sandbox left standing. The monitor is the part that matters — a HEADLESS-*
#    output in his live compositor is a test that never tore down — so it is
#    reported separately from the directory, which may just be litter (or a
#    sandbox another agent is using right now).
SBOX="${VTB_SANDBOX_DIR:-/tmp/vtb-sandbox}"
if hyprctl version >/dev/null 2>&1; then
  heads=$(hyprctl monitors -j 2>/dev/null | sed -n 's/.*"name": "\(HEADLESS-[0-9]*\)".*/\1/p')
  [ -n "$heads" ] && warn \
    "WARN: headless sandbox monitor(s) still in his live compositor: $heads" \
    "      A 'sandbox.sh start' with no 'stop'. Windows may still be on it." \
    "      repair:  $HOME/nix/tools/sandbox.sh stop"
fi
if [ -d "$SBOX" ] && [ -z "${heads:-}" ]; then
  warn "WARN: sandbox state left behind at $SBOX (no headless monitor, so the" \
       "      monitor half was torn down).  repair:  $HOME/nix/tools/sandbox.sh stop"
fi

exit "$found"
