#!/usr/bin/env bash
# Run painter ON BOOK against top's ComfyUI, over an ssh tunnel.
#
# This is also painter's LAUNCHER on book: home/prog/painter.nix's `air` branch
# execs `comfy-tunnel.sh -- python3 main.py`, so opening painter from the runner
# does the whole thing by itself — probe top, start the backend there if it is
# not already up, forward 8188, wait until it actually answers, run the app,
# tear the forward down after.
#
# The backend is loopback-only on purpose (home/prog/painter.nix passes
# `--listen 127.0.0.1`, and sys/net/tailscale.nix opens only 22 and 445 on
# tailscale0). ComfyUI has no authentication and executes arbitrary graphs as
# lam, so the answer to "reach it from the other machine" is a forwarded port
# behind ssh's key auth, NOT a second listener. Nothing new is exposed: the
# tunnel rides the ssh hole that dbsync already uses.
#
#     ./comfy-tunnel.sh          # start the backend on top, forward 8188, hold
#     ./comfy-tunnel.sh -- painter   # ...and run painter, tearing down after
#
# painter's DEFAULT_URL is http://127.0.0.1:8188, so with the forward up it
# needs no configuration at all — it just talks to the local end.
#
# REACHING TOP IS A PRECONDITION, NOT A NICETY — the same rule, for the same
# reason, as player's air-launch.sh. Without top there is no backend at all, so
# a painter window that opens anyway is one that can only fail on the first
# Generate. Say why in a notification (launched from the runner, stderr goes
# nowhere a person is looking) and exit. PAINTER_NO_TUNNEL=1 restores a plain
# launch against whatever is on the local port, for UI work with no top.
#
# Host names, in order: `top.local` is mDNS and answers only on the home LAN;
# `top` is the tailscale MagicDNS name and works from any network. Same
# candidate list, and same reason, as player/tools/air-launch.sh.
set -uo pipefail

# The readiness probe writes onto a socket ssh may have closed a moment earlier
# (see comfy_answers): let that fail with EPIPE, which the probe handles, rather
# than take the default SIGPIPE and kill the script mid-wait.
trap '' PIPE

PORT="${COMFY_PORT:-8188}"
SSH="${COMFY_SSH:-/usr/bin/ssh}"   # Fedora's ssh: nix-built binaries on book
                                   # cannot resolve .local names (nss-mdns).
# How long to wait for the backend to serve. A warm one is seconds; a cold one
# is a torch import plus however many GB of weights; and if the nix-shell env
# has been garbage-collected since the last run it is a few hundred MB of store
# downloads BEFORE any of that. Hence ten minutes, not one.
READY_TIMEOUT="${COMFY_READY_TIMEOUT:-600}"
# Generous on purpose: a top that is mid-download answers sshd late, and reading
# "busy" as "asleep" is how this turns into a false "can't reach top".
CONNECT_TIMEOUT="${COMFY_CONNECT_TIMEOUT:-15}"

say() { printf 'comfy-tunnel: %s\n' "$*" >&2; }

die() {
    say "$*"
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a painter -u critical "painter" "$*" 2>/dev/null
    exit 1
}

# Does an HTTP server on 127.0.0.1:$PORT answer ComfyUI's /system_stats? Uses
# bash's /dev/tcp, so it needs neither curl nor ss on whatever PATH the runner
# hands us — and it is an HTTP probe, not a port check, because the ssh forward
# accepts connections locally from the moment it binds, long before the far end
# serves anything.
# Refusals are the NORMAL state while the backend warms up, and bash prints its
# own message for a failed /dev/tcp redirect regardless of a redirect on the
# exec itself — so the whole body is silenced, once, at the closing brace.
# `line=""`, not a bare `local line`, is load-bearing: while the backend warms
# up, ssh accepts the local connection and only then learns the far end refuses,
# so the read fails with ECONNRESET and never assigns it — and under `set -u`
# the unset variable then killed this script one second after it had started the
# backend, silently, exit 1. That was the whole "painter on book does nothing"
# bug.
comfy_answers() {
    local line=""
    exec 3<>"/dev/tcp/127.0.0.1/$PORT" || return 1
    printf 'GET /system_stats HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' >&3 ||
        { exec 3<&- 3>&-; return 1; }
    read -r -t 5 line <&3
    exec 3<&- 3>&-
    [[ "$line" == *" 200 "* ]]
} 2>/dev/null

# The app to run, if any: everything after `--`.
APP=()
if [ "${1:-}" = "--" ]; then
    shift
    [ $# -gt 0 ] || { say "nothing to run after --"; exit 2; }
    APP=("$@")
fi

if [ -n "${PAINTER_NO_TUNNEL:-}" ]; then
    say "PAINTER_NO_TUNNEL set - not touching top"
    [ ${#APP[@]} -gt 0 ] && exec "${APP[@]}"
    exit 0
fi

# Already tunnelled — a second painter, or a manual forward being held. Use it
# rather than fight over the port.
if comfy_answers; then
    say "127.0.0.1:$PORT already answers - using it"
    [ ${#APP[@]} -gt 0 ] && exec "${APP[@]}"
    exit 0
fi

if [ -n "${COMFY_HOST:-}" ]; then
    CANDIDATES=("$COMFY_HOST")
else
    CANDIDATES=(top.local top)
fi

# One ssh master for the probe, the unit start and the forward: three
# handshakes become one. %C hashes (host, port, user), so top.local and top
# cannot collide on the socket name.
SSH_MUX=(-o ControlMaster=auto -o ControlPersist=30
         -o "ControlPath=${XDG_RUNTIME_DIR:-/tmp}/painter-comfy-ssh-%C")

HOST=""
for cand in "${CANDIDATES[@]}"; do
    if "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null; then
        HOST="$cand"; break
    fi
done
[ -n "$HOST" ] || die "can't reach top (tried: ${CANDIDATES[*]}) - is it awake? Off the home LAN this needs the tailnet up on both machines (tailscale status)."
say "reaching top as '$HOST'"

# Is the backend already up over there? The unit is the only thing that binds
# that port, so `is-active` is the cheap question — and whether it truly ANSWERS
# is proven below through the forward either way, so a wedged one is still
# caught.
STATE="$("$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
         'systemctl --user is-active comfy-painter.service' 2>/dev/null)"
if [ "$STATE" = "active" ]; then
    say "comfy-painter already running on $HOST"
else
    say "comfy-painter is ${STATE:-unknown} on $HOST - starting it"
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a painter "painter" "starting ComfyUI on top…" 2>/dev/null
    # No wantedBy on the unit, so it is not running unless someone asked for it.
    # Type=exec, so this returns once python is exec'd — long before the weights
    # are loaded, which is what the readiness poll below is for.
    "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
        'systemctl --user start comfy-painter.service' 2>/dev/null ||
        die "could not start comfy-painter on top (is a user session up there?)"
fi

# -N: no remote command. ExitOnForwardFailure so a refused bind is loud rather
# than a tunnel that silently forwards nothing.
FWD=("$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes
     -o ServerAliveInterval=20 -o ServerAliveCountMax=3
     -N -L "127.0.0.1:$PORT:127.0.0.1:$PORT" "$HOST")

if [ ${#APP[@]} -eq 0 ]; then
    say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT (ctrl-c to stop)"
    exec "${FWD[@]}"
fi

"${FWD[@]}" &
TUN=$!
trap 'kill "$TUN" 2>/dev/null' EXIT

deadline=$(( SECONDS + READY_TIMEOUT ))
until comfy_answers; do
    kill -0 "$TUN" 2>/dev/null ||
        die "ssh forward to $HOST died - on top: journalctl --user -u comfy-painter -n50"
    [ "$SECONDS" -lt "$deadline" ] ||
        die "ComfyUI on $HOST did not answer within ${READY_TIMEOUT}s - on top: journalctl --user -u comfy-painter -n50"
    sleep 1
done
say "backend ready on $HOST via 127.0.0.1:$PORT"

"${APP[@]}"
