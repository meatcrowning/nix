#!/usr/bin/env bash
# Run oracle ON BOOK against top's ollama daemon, over an ssh tunnel.
#
# This is also oracle's LAUNCHER on book: home/prog/oracle.nix's `air` branch
# execs `ollama-tunnel.sh -- python3 main.py`, so opening oracle from the
# runner does the whole thing by itself — probe top and forward 11434 before
# the window ever opens. Modelled directly on painter's
# apps/painter/tools/comfy-tunnel.sh; read that file's comments for the parts
# that are identical here (host candidates, the ssh control-master reuse, the
# EPIPE trap, exec 3<>). This script only carries what differs:
#
#   * ollama is a SYSTEM unit (sys/ai/ollama.nix), not a `--user` one like
#     comfy-painter, and it is `enable = true` (started at boot) rather than
#     started on demand. So there is nothing here to start over ssh — that
#     runs from oracle's own Backend (apps/oracle/main.py): on book its
#     start/stop buttons `ssh $HOST sudo -n systemctl {start,stop}
#     ollama.service`, which is why this script exports OLLAMA_SSH_HOST /
#     OLLAMA_SSH / OLLAMA_SSH_CTL below (the Backend reuses this master).
#     top grants lam passwordless sudo for exactly those two commands
#     (sys/ai/ollama.nix); top askpass cannot prompt over a tty-less ssh.
#   * no models/output sshfs mounts — oracle has no model files of its own to
#     read (ollama resolves model names against ITS OWN store) and no
#     generated-output gallery to peer.
#   * heavy-gate.sh can SUSPEND ollama.service (stop + runtime-mask) around a
#     heavy rebuild on top. That is a normal, expected "down" — this script
#     reports it and forwards the port anyway, exactly like painter's
#     "comfy-painter is inactive" path, so oracle opens and says the daemon is
#     unreachable rather than the tunnel refusing to start.
#
# oracle's OLLAMA env var defaults to http://127.0.0.1:11434, so with the
# forward up it needs no configuration at all.
#
# REACHING TOP IS A PRECONDITION, NOT A NICETY — same rule as comfy-tunnel.sh
# and player's air-launch.sh. ORACLE_NO_TUNNEL=1 restores a plain launch
# against whatever is on the local port, for UI work with no top.
set -uo pipefail

trap '' PIPE

PORT="${OLLAMA_PORT:-11434}"
SSH="${OLLAMA_SSH:-/usr/bin/ssh}"   # Fedora's ssh: nix-built binaries on book
                                    # cannot resolve .local names (nss-mdns).
CONNECT_TIMEOUT="${OLLAMA_CONNECT_TIMEOUT:-15}"

say() { printf 'ollama-tunnel: %s\n' "$*" >&2; }

die() {
    say "$*"
    command -v notify-send >/dev/null 2>&1 &&
        notify-send -a oracle -u critical "oracle" "$*" 2>/dev/null
    exit 1
}

# Does an HTTP server on 127.0.0.1:$PORT answer ollama's /api/tags? Same
# /dev/tcp probe as comfy_answers in comfy-tunnel.sh, and `line=""` is
# load-bearing for the identical reason documented there.
ollama_answers() {
    local line=""
    exec 3<>"/dev/tcp/127.0.0.1/$PORT" || return 1
    printf 'GET /api/tags HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' >&3 ||
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

if [ -n "${ORACLE_NO_TUNNEL:-}" ]; then
    say "ORACLE_NO_TUNNEL set - not touching top"
    [ ${#APP[@]} -gt 0 ] && exec "${APP[@]}"
    exit 0
fi

if [ -n "${OLLAMA_SSH_HOST:-}" ]; then
    CANDIDATES=("$OLLAMA_SSH_HOST")
else
    # `top` FIRST — see comfy-tunnel.sh for the ~5s vs 0.04s measurement that
    # justifies this order.
    CANDIDATES=(top top.local)
fi

# One ssh master for the probe, the status check and the forward.
SSH_CTL="${XDG_RUNTIME_DIR:-/tmp}/oracle-ollama-ssh-%C"
SSH_MUX=(-o ControlMaster=auto -o ControlPersist=30 -o "ControlPath=$SSH_CTL")

HOST=""
for cand in "${CANDIDATES[@]}"; do
    if "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null ||
       "$SSH" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null; then
        HOST="$cand"; break
    fi
done
[ -n "$HOST" ] || die "can't reach top (tried: ${CANDIDATES[*]}) - is it awake? Off the home LAN this needs the tailnet up on both machines (tailscale status)."
say "reaching top as '$HOST'"

# Hand the resolved host, ssh binary and control path to oracle's Backend so its
# start/stop buttons (apps/oracle/main.py) drive top's ollama.service over the
# SAME ssh — `ssh $HOST sudo -n systemctl {start,stop} ollama.service`, reusing
# this master. Chat + UNLOAD are HTTP over the forward; only start/stop need ssh.
export OLLAMA_SSH_HOST="$HOST"
export OLLAMA_SSH="$SSH"
export OLLAMA_SSH_CTL="$SSH_CTL"

# Already tunnelled — a second oracle, or a manual forward being held. Use it
# rather than fight over the port. THIS TEST MUST COME BEFORE OUR OWN FORWARD
# STARTS — see comfy-tunnel.sh for why the order matters.
if ollama_answers; then
    say "127.0.0.1:$PORT already answers - using it"
    if [ ${#APP[@]} -gt 0 ]; then
        "${APP[@]}"
        exit $?
    fi
    exit 0
fi

# -N: no remote command. ExitOnForwardFailure so a refused bind is loud rather
# than a tunnel that silently forwards nothing.
FWD=("$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes
     -o ServerAliveInterval=20 -o ServerAliveCountMax=3
     -N -L "127.0.0.1:$PORT:127.0.0.1:$PORT" "$HOST")

if [ ${#APP[@]} -gt 0 ]; then
    "${FWD[@]}" &
    TUN=$!
    trap 'kill "$TUN" 2>/dev/null' EXIT
fi

# Say (not start) ollama's state on top. Nothing here starts the SYSTEM unit —
# see the header comment: that is root's job and oracle's own start button
# already shells out to it (and fails visibly on book, which is correct).
STATE="$("$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
         'systemctl is-active ollama.service' 2>/dev/null)"
say "ollama.service is ${STATE:-unknown} on $HOST"

if [ ${#APP[@]} -eq 0 ]; then
    say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT (ctrl-c to stop)"
    exec "${FWD[@]}"
fi

# WAIT FOR THE FORWARD, NOT FOR OLLAMA — the port must be bound before oracle's
# first /api/ps poll, but a suspended/masked ollama (heavy-gate.sh) may never
# answer at all; oracle's own status poll already handles "down" (Backend.
# pollStatus in main.py), so this loop only guards against the forward itself
# failing to bind.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
    kill -0 "$TUN" 2>/dev/null ||
        die "ssh forward to $HOST died"
    sleep 0.1
done

"${APP[@]}"
