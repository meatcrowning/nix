#!/usr/bin/env bash
# Run oracle on book against top's loopback Ollama through SSH. The `air`
# launcher invokes this as `ollama-tunnel.sh -- python3 main.py`, forwarding
# Ollama (11434) and ai-warden (8199) before starting the app.
#
# Ollama is a top SYSTEM unit; chatter's forwarded warden lease owns its
# lifecycle, while the app's start/stop buttons use the exported SSH master and
# the two passwordless `systemctl` commands allowed by sys/ai/ollama.nix.
# There are no model/output mounts: Ollama resolves its own store. A heavy gate
# may stop/mask Ollama; that is reported as a normal daemon-down state while
# the forward remains usable. `ORACLE_NO_TUNNEL=1` is the local/UI override.
#
# The local endpoint is the app default (127.0.0.1:11434). Host candidates are
# top, then top.local; each port reuses an existing forward before SSH adds it.
set -uo pipefail

trap '' PIPE

PORT="${OLLAMA_PORT:-11434}"
WPORT="${AI_WARDEN_PORT:-8199}"     # top's ai-warden; see the header comment
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

# HTTP readiness probe for Ollama. `line=""` is required under `set -u` when a
# warming forward resets the socket before returning a response.
ollama_answers() {
    local line=""
    exec 3<>"/dev/tcp/127.0.0.1/$PORT" || return 1
    printf 'GET /api/tags HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' >&3 ||
        { exec 3<&- 3>&-; return 1; }
    read -r -t 5 line <&3
    exec 3<&- 3>&-
    [[ "$line" == *" 200 "* ]]
} 2>/dev/null

# Port-bound check used for the warden forward; it may be a local daemon or an
# existing tunnel, so readiness is checked separately above.
port_open() {
    exec 3<>"/dev/tcp/127.0.0.1/$1" || return 1
    exec 3<&- 3>&-
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
    # top resolves quickly through LAN DNS or tailnet; top.local is the mDNS
    # fallback.
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

# Let the app's start/stop controls address top's system unit through this same
# SSH master; chat and unload remain HTTP over the forwarded port.
export OLLAMA_SSH_HOST="$HOST"
export OLLAMA_SSH="$SSH"
export OLLAMA_SSH_CTL="$SSH_CTL"

# Reuse each existing forward independently. This check must precede our SSH
# launch: binding one occupied port would make ExitOnForwardFailure reject both.
FWD_PORTS=()
if ollama_answers; then
    say "127.0.0.1:$PORT already answers - using it"
else
    FWD_PORTS+=("$PORT")
fi
if port_open "$WPORT"; then
    say "127.0.0.1:$WPORT already bound - using it for the warden"
else
    FWD_PORTS+=("$WPORT")
fi

if [ ${#FWD_PORTS[@]} -eq 0 ]; then
    if [ ${#APP[@]} -gt 0 ]; then
        "${APP[@]}"
        exit $?
    fi
    exit 0
fi

# -N: no remote command. ExitOnForwardFailure so a refused bind is loud rather
# than a tunnel that silently forwards nothing.
FWD=("$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes
     -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -N)
for p in "${FWD_PORTS[@]}"; do
    FWD+=(-L "127.0.0.1:$p:127.0.0.1:$p")
done
FWD+=("$HOST")

if [ ${#APP[@]} -gt 0 ]; then
    "${FWD[@]}" &
    TUN=$!
    trap 'kill "$TUN" 2>/dev/null' EXIT
fi

# Report Ollama's state; the app acquires its lease after the window opens, with
# direct systemctl controls as fallback.
STATE="$("$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
         'systemctl is-active ollama.service' 2>/dev/null)"
say "ollama.service is ${STATE:-unknown} on $HOST"

if [ ${#APP[@]} -eq 0 ]; then
    say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT (ctrl-c to stop)"
    exec "${FWD[@]}"
fi

# Wait for the local forward, not Ollama: a heavy-gate suspension may leave the
# daemon down, which the app reports itself.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    port_open "${FWD_PORTS[0]}" && break
    kill -0 "$TUN" 2>/dev/null ||
        die "ssh forward to $HOST died"
    sleep 0.1
done

"${APP[@]}"
