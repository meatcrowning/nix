#!/usr/bin/env bash
# Keep the Soulseek download pool fed, unattended.
#
# apps/player/tools/soulseek-missing.py --watch is a long-running feeder: it
# polls the local slskd daemon for how many transfers are still live and,
# whenever that falls below its low-water mark, searches and enqueues fresh
# tracks until the pool is topped up again; slskd's 50-slot downloader pulls
# them in the background. This wrapper is what soulseek-sweep.service execs to
# run it. (It used to run a one-shot batch on a 30-min timer, but a periodic
# one-shot cannot hold a pool at a low-water mark — the queue drained to a
# handful between ticks and sat idle, the symptom this replaces.)
#
# It exists as a shell wrapper rather than an ExecStart straight at the python
# because the feeder MUST be a clean no-op when slskd is down, unreachable, or
# not logged in to Soulseek: the python raises SystemExit (a non-zero exit)
# with an explanatory message in every one of those cases, which would mark the
# service `failed`. slskd being down is an ordinary state here (the daemon
# restarts, the network drops, the login secret was never added), not a fault
# of this unit — so we pre-check it and skip quietly (exit 0), leaving the timer
# to try again. Once slskd is up we `exec` the python so a crash still trips the
# unit's Restart=on-failure.
#
# KILL SWITCH: `touch ~/.local/state/soulseek-sweep/off` to stop it running;
# delete that file to re-arm, then `systemctl --user start soulseek-sweep`.
# Same style as board-watch / board-notify.
# LOG: ~/.cache/soulseek-sweep.log (this wrapper's own per-start precheck trail);
# the feeder's own per-poll / per-track output goes to journald
# (`journalctl --user -u soulseek-sweep`), which rotates it — a days-long run
# would otherwise grow the file without bound.

set -u

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/soulseek-sweep"
OFF_SWITCH="$STATE_DIR/off"
LOCK="$STATE_DIR/sweep.lock"
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/soulseek-sweep.log"
HOST="http://127.0.0.1:5030"
SWEEP="$HOME/nix/apps/player/tools/soulseek-missing.py"

mkdir -p "$STATE_DIR"

log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }

# Kill switch — his, in the documented style of the other services here.
if [ -e "$OFF_SWITCH" ]; then
  exit 0
fi

# NON-OVERLAP. A oneshot already won't be double-started by the timer, but a
# run can outlive a tick when searches are slow, so take a non-blocking lock:
# a tick that finds the previous run still going does nothing.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "previous sweep still running; skipping this tick"
  exit 0
fi

# Is slskd up and logged in? Web auth is disabled (loopback-only, one user), so
# the API needs no key. A connection refusal / timeout means the daemon is
# down or restarting: skip cleanly, don't spam.
app="$(curl -sf --max-time 5 "$HOST/api/v0/application" 2>/dev/null)" || {
  log "slskd not reachable at $HOST; skipping"
  exit 0
}

# Up but not logged in to the Soulseek network (no login secret, or mid-connect)
# — the sweep can queue nothing, so it too is a clean no-op rather than a
# failure. Cheap substring check; the field is `"isLoggedIn":true`.
case "$app" in
  *'"isLoggedIn":true'*) : ;;
  *)
    log "slskd up but not logged in to Soulseek; skipping"
    exit 0
    ;;
esac

log "starting soulseek-missing --watch"
# --watch is a LONG-RUNNING feeder, not a one-shot batch: it polls slskd for how
# many transfers are still live and, whenever that falls below its low-water
# mark, searches and enqueues fresh tracks until the pool is topped up again
# (soulseek-missing.py). A periodic one-shot could not hold the pool at a
# low-water mark -- it drained to a handful between ticks and sat idle -- which
# is exactly what this replaces.
#
# `exec` so systemd tracks the python directly: SIGTERM (stop/restart) reaches
# the loop, which stops cleanly after the current search; the python's exit code
# propagates, so a crash trips the unit's Restart=on-failure while a clean drain
# (exit 0) stays stopped until the timer re-checks for newly-missing tracks. The
# non-blocking flock on fd 9 is preserved across exec and held for the python's
# whole lifetime, so a second run still cannot overlap. Output goes to journald
# (long-running: journald rotates it; the file LOG keeps only this wrapper's
# per-start precheck trail).
exec python3 "$SWEEP" --watch
