#!/usr/bin/env bash
# Drain the Soulseek missing-track backlog unattended.
#
# apps/player/tools/soulseek-missing.py submits a batch of searches to the
# local slskd daemon and queues the best match of each for download; slskd's
# 50-slot downloader then pulls them in the background. Nothing ran that sweep
# on a schedule, so the download queue drained to a handful of items and sat
# idle until someone kicked it by hand. This wrapper is the scheduled kick,
# driven by soulseek-sweep.timer.
#
# It exists as a shell wrapper rather than an ExecStart straight at the python
# because the sweep MUST be a clean no-op when slskd is down, unreachable, or
# not logged in to Soulseek: the python raises SystemExit (a non-zero exit)
# with an explanatory message in every one of those cases, which would mark the
# service `failed` and, under a timer, do it on every tick. slskd being down is
# an ordinary state here (the daemon restarts, the network drops, the login
# secret was never added), not a fault of this unit — so we pre-check it and
# skip quietly instead.
#
# KILL SWITCH: `touch ~/.local/state/soulseek-sweep/off` to stop it running;
# delete that file to re-arm. Same style as board-watch / board-notify.
# LOG: ~/.cache/soulseek-sweep.log (this wrapper's own line-per-run trail; the
# python's verbose per-track output is appended under it).

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

log "running soulseek-missing sweep"
# Batch invocation (default --limit, currently 40 tracks/run). A keep-fed /
# continuous mode was being added to soulseek-missing.py concurrently but had
# not landed when this was written, so this wires the existing one-shot batch;
# swap in that flag when it lands.
python3 "$SWEEP" >> "$LOG" 2>&1
rc=$?
log "sweep finished (exit $rc)"
# Don't propagate the python's exit code: a mid-sweep hiccup (a peer 429, a
# search timeout) is normal and must not mark the unit failed on a timer.
exit 0
