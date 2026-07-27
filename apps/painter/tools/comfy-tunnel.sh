#!/usr/bin/env bash
# Run painter ON AIR against top's ComfyUI, over an ssh tunnel.
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
# Host names, in order: `top.local` is mDNS and answers only on the home LAN;
# `top` is the tailscale MagicDNS name and works from any network. Same
# candidate list, and same reason, as player/tools/air-launch.sh.
set -uo pipefail

PORT="${COMFY_PORT:-8188}"
SSH="${COMFY_SSH:-/usr/bin/ssh}"   # Fedora's ssh: nix-built binaries on book
                                   # cannot resolve .local names (nss-mdns).

if [ -n "${COMFY_HOST:-}" ]; then
    CANDIDATES=("$COMFY_HOST")
else
    CANDIDATES=(top.local top)
fi

say() { printf 'comfy-tunnel: %s\n' "$*" >&2; }

HOST=""
for cand in "${CANDIDATES[@]}"; do
    if "$SSH" -o BatchMode=yes -o ConnectTimeout=4 \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null; then
        HOST="$cand"; break
    fi
done
if [ -z "$HOST" ]; then
    say "can't ssh to top (tried: ${CANDIDATES[*]}) — is it awake, and are both machines logged into the tailnet? (tailscale status)"
    exit 1
fi
say "reaching top as '$HOST'"

# Warm the backend. No wantedBy on the unit, so it is not running unless
# someone asked for it; weights take a while, hence painter's own probe loop.
"$SSH" -o BatchMode=yes "$HOST" \
    'systemctl --user start comfy-painter.service' \
    || say "could not start comfy-painter on top (is a user session up?) - continuing"

if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
    say "something already listens on 127.0.0.1:$PORT - not forwarding"
    exit 1
fi

# -N: no remote command. ExitOnForwardFailure so a refused bind is loud rather
# than a tunnel that silently forwards nothing.
FWD=("$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes
     -o ServerAliveInterval=20 -o ServerAliveCountMax=3
     -N -L "127.0.0.1:$PORT:127.0.0.1:$PORT" "$HOST")

if [ "${1:-}" = "--" ]; then
    shift
    [ $# -gt 0 ] || { say "nothing to run after --"; exit 2; }
    "${FWD[@]}" &
    TUN=$!
    trap 'kill "$TUN" 2>/dev/null' EXIT
    # Give the forward a moment to bind before the app probes it.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q . && break
        sleep 0.2
    done
    "$@"
else
    say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT (ctrl-c to stop)"
    exec "${FWD[@]}"
fi
