#!/usr/bin/env bash
# Run painter on book against top's loopback ComfyUI through SSH. The `air`
# launcher invokes this as `comfy-tunnel.sh -- python3 main.py`: it forwards
# ComfyUI (8188) and ai-warden (top 8199), mounts top's model/output roots
# read-only, starts the app as soon as ports bind, and cleans up. The backend
# lease handles warm-up; the window opens immediately. Without `--`, this holds
# a forward and starts the user unit. `PAINTER_NO_TUNNEL=1` is the local/UI
# override. ComfyUI has no auth, so SSH is the only remote path; candidates are
# top, then top.local.
set -uo pipefail

# Let the readiness probe handle EPIPE when a warming SSH socket closes.
trap '' PIPE

PORT="${COMFY_PORT:-8188}"
WPORT="${PAINTER_WARDEN_PORT:-8200}"
SSH="${COMFY_SSH:-/usr/bin/ssh}"   # Fedora's ssh: nix-built binaries on book
                                   # cannot resolve .local names (nss-mdns).
# Same reason for sshfs and fusermount3 — Fedora's, under /usr/sbin.
SSHFS="${COMFY_SSHFS:-/usr/sbin/sshfs}"
FUSERMOUNT="${COMFY_FUSERMOUNT:-/usr/sbin/fusermount3}"
MODELS_REMOTE="${COMFY_MODELS:-/home/lam/models}"
MODELS_LOCAL="${PAINTER_MODELS_MOUNT:-${XDG_CACHE_HOME:-$HOME/.cache}/painter/models-top}"
OUT_REMOTE="${COMFY_OUT:-/home/lam/Pictures/painter/out}"
OUT_LOCAL="${PAINTER_PEER_OUT_MOUNT:-${XDG_CACHE_HOME:-$HOME/.cache}/painter/out-top}"
# Cold starts include torch/weights and store downloads; allow ten minutes.
READY_TIMEOUT="${COMFY_READY_TIMEOUT:-600}"
# A busy top may answer SSH late; do not mistake that for an asleep host.
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

port_open() {
    exec 3<>"/dev/tcp/127.0.0.1/$1" || return 1
    exec 3<&- 3>&-
} 2>/dev/null

# The GUI renews its own warden client lease, but that timer is driven by Qt's
# event loop.  A stalled painter window used to let the 15-second claim expire
# even though this launcher, its SSH tunnel, and the backend were all still
# alive.  The warden then quite reasonably stopped ComfyUI as an orphan as soon
# as a render finished.  Keep the same client identity alive from this separate
# shell process; its EXIT cleanup still releases the claim when the app exits.
warden_client_post() {
    local path="$1" payload line=""
    payload="{\"backend\":\"comfy\",\"client\":\"$PAINTER_BACKEND_CLIENT_ID\"}"
    exec 3<>"/dev/tcp/127.0.0.1/$WPORT" || return 1
    printf 'POST %s HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s' \
        "$path" "${#payload}" "$payload" >&3 || { exec 3<&- 3>&-; return 1; }
    # Reading the status line lets the daemon finish handling the request before
    # this short-lived connection is closed.  A failed heartbeat is harmless:
    # painter's own client renew and the daemon's expiry backstop remain.
    read -r -t 2 line <&3 || true
    exec 3<&- 3>&-
    [[ "$line" == *" 200 "* ]]
} 2>/dev/null

KEEPER=""
start_client_keeper() {
    # `renew` heals a daemon restart by acquiring an unknown client, so this
    # first request also covers the small interval before Python enters Qt's
    # event loop.  The UUID is supplied below and shared with BackendClientLease.
    warden_client_post /client/renew || true
    (
        while sleep 5; do
            warden_client_post /client/renew || true
        done
    ) &
    KEEPER=$!
}

stop_client_keeper() {
    [ -n "$KEEPER" ] || return 0
    kill "$KEEPER" 2>/dev/null || true
    wait "$KEEPER" 2>/dev/null || true
    warden_client_post /client/release || true
    KEEPER=""
}

# The app to run, if any: everything after `--`.
APP=()
if [ "${1:-}" = "--" ]; then
    shift
    [ $# -gt 0 ] || { say "nothing to run after --"; exit 2; }
    APP=("$@")
fi

# A second painter must not inherit the first one's loopback forwards.  When
# the first window exits it quite properly tears those down, which otherwise
# strands the surviving window on two closed ports.  If the normal ports already
# answer, give this process private loopback ports and tell its Python child
# exactly where ComfyUI is.  The first window retains the familiar 8188/8200
# pair; this branch is only the overlap case.
PRIVATE_PORTS=0

if [ -n "${PAINTER_NO_TUNNEL:-}" ]; then
    say "PAINTER_NO_TUNNEL set - not touching top"
    [ ${#APP[@]} -gt 0 ] && exec "${APP[@]}"
    exit 0
fi

if [ -n "${COMFY_HOST:-}" ]; then
    CANDIDATES=("$COMFY_HOST")
else
    # `top` FIRST, and this is worth 5 seconds of every launch. Measured on book:
    # resolving `top.local` takes ~5s (mDNS, after the other resolvers time out)
    # against 0.04s for `top` — which the LAN's own DNS answers at home and
    # tailscale's MagicDNS answers everywhere else. Trying the mDNS name first
    # meant the window waited five seconds on a name lookup before anything else
    # could even begin. `top.local` stays as the fallback for a network where
    # neither DNS knows the name.
    CANDIDATES=(top top.local)
fi

# One ssh master for the probe, the unit start and the forward: three
# handshakes become one. %C hashes (host, port, user), so top.local and top
# cannot collide on the socket name.
SSH_CTL="${XDG_RUNTIME_DIR:-/tmp}/painter-comfy-ssh-%C"
SSH_MUX=(-o ControlMaster=auto -o ControlPersist=30 -o "ControlPath=$SSH_CTL")

HOST=""
for cand in "${CANDIDATES[@]}"; do
    # Twice, and the second time WITHOUT the shared master: a previous painter's
    # ControlPersist socket expiring underneath this connect fails the whole
    # probe, and "can't reach top" for a top that is sitting right there is the
    # worst message this script can produce. Observed once in testing.
    if "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null ||
       "$SSH" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
              -o StrictHostKeyChecking=accept-new "$cand" true 2>/dev/null; then
        HOST="$cand"; break
    fi
done
[ -n "$HOST" ] || die "can't reach top (tried: ${CANDIDATES[*]}) - is it awake? Off the home LAN this needs the tailnet up on both machines (tailscale status)."
say "reaching top as '$HOST'"

# The app's own start/stop/status controls drive `systemctl --user` on the unit,
# and on book that unit is TOP's — a local systemctl finds nothing and every
# control fails, backend running or not. Hand the app the host we resolved and
# the master socket we already opened, so it drives systemd where the backend
# actually is. main.py's unit_cmd() reads exactly these three.
export PAINTER_BACKEND_SSH="$HOST"
export PAINTER_BACKEND_SSH_BIN="$SSH"
export PAINTER_BACKEND_SSH_CTL="$SSH_CTL"
# A book launcher and its child Python process jointly own one warden client
# claim.  The random suffix prevents two painter windows from renewing or
# releasing one another's claim.
export PAINTER_BACKEND_CLIENT_ID="book-painter-$$-${RANDOM}${RANDOM}"
# Chatter already uses local 8199 for this same remote warden. Painter gets its
# own local port so either launcher can own or reuse its forward independently.
export AI_WARDEN_URL="http://127.0.0.1:$WPORT"

# THE MODELS ARE TOP'S TOO, and painter identifies them by READING THEM: the
# registry fingerprints every file's tensor header (fingerprint.py), and LoRA
# compatibility re-reads the base's and the adapter's headers later on demand.
# None of that can be answered from a file list, and /home/lam/models does not
# exist on book — so the app found nothing to load and offered an empty model
# picker. Mount top's model root read-only over sshfs and point PAINTER_MODELS
# at it; only headers ever cross the wire (57 files, a few KB each, cached by
# size+mtime after the first scan), never the 249G.
#
# The graphs are unaffected: they name a model by BASENAME and ComfyUI resolves
# it against top's own extra_model_paths.yaml, so this mount is for
# identification here and nothing else.
#
# ro: nothing here ever writes to top. follow_symlinks: the model roots were
# consolidated in 2026-07 and the tree still holds server-side symlinks, which
# would otherwise arrive as dangling links.
#
# Only what WE mounted is unmounted again — a mount already standing belongs to
# another painter, or to him, and pulling it out from under either is worse than
# leaving it.
MOUNTS=()

mount_ro() {
    local remote="$1" here="$2"
    findmnt -rn "$here" >/dev/null 2>&1 && return 0
    mkdir -p "$here" || return 1
    "$SSHFS" -o ro,follow_symlinks,reconnect,BatchMode=yes \
             -o ServerAliveInterval=15,ServerAliveCountMax=3 \
             "$HOST:$remote" "$here" 2>/dev/null || return 1
    MOUNTS+=("$here")
    return 0
}

unmount_ours() {
    local d
    for d in ${MOUNTS[@]+"${MOUNTS[@]}"}; do
        "$FUSERMOUNT" -u "$d" 2>/dev/null
    done
}

# COMFY_ENSURE_BACKEND: for a NON-interactive consumer that will not start the
# backend itself the way painter's main.py does — systheme's headless render. It
# turns comfy-painter on before the app and, ONLY if we were the one who turned
# it on, off again after, so a temporary generative pass leaves top exactly as
# it found it and never fights a painter the user has open (which owns its own
# lifecycle). Left unset, nothing here touches the unit — painter's launch path
# is unchanged.
STARTED_BACKEND=""
stop_backend_ours() {
    [ -n "$STARTED_BACKEND" ] || return 0
    say "stopping comfy-painter on $HOST (we started it)"
    "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
        'systemctl --user stop comfy-painter.service' 2>/dev/null || true
    STARTED_BACKEND=""
}

if [ -z "${PAINTER_NO_MODELS_MOUNT:-}" ] && [ ${#APP[@]} -gt 0 ]; then
    # The path is known before the mount exists, so the app can be told where the
    # models WILL be and started straight away — sshfs takes about a second, and
    # that second was spent with no window on screen. main.py's scan retries
    # while the list is empty, so it picks them up as soon as the mount lands.
    export PAINTER_MODELS="$MODELS_LOCAL"
    if mount_ro "$MODELS_REMOTE" "$MODELS_LOCAL"; then
        say "models from $HOST:$MODELS_REMOTE at $MODELS_LOCAL"
    else
        # Not fatal: the backend is what painter cannot work without, and the
        # picker being empty says so plainly. Say why, once, rather than let it
        # read as "top has no models".
        say "could not mount $HOST:$MODELS_REMOTE - the model picker will be empty"
        command -v notify-send >/dev/null 2>&1 &&
            notify-send -a painter -u critical "painter" \
                "could not mount top's models over sshfs - the model picker will be empty" 2>/dev/null
    fi
fi

# THE HISTORY IS BOTH MACHINES' TOO. Every result book asks for is produced by
# top's backend, which files it in TOP's output directory whoever asked; book
# only ever holds the copy it downloaded afterwards. So top's gallery has always
# shown everything either machine made and book's showed the tail of it. Mount
# top's output root beside its models and hand it over as a PEER root —
# main.py's Gallery globs it alongside the local one and shows the file that is
# in both once (by name; the local copy wins, being the one with painter's
# parameter chunk in it).
#
# Cheap, and not fatal: measured 0.14s to mount, and a failure costs the older
# half of the history rather than the ability to generate — so it says so on
# stderr and does not put a notification in front of him.
if [ -z "${PAINTER_NO_PEER_OUT:-}" ] && [ ${#APP[@]} -gt 0 ]; then
    if mount_ro "$OUT_REMOTE" "$OUT_LOCAL"; then
        export PAINTER_PEER_OUT="$OUT_LOCAL"
        say "outputs from $HOST:$OUT_REMOTE at $OUT_LOCAL"
    else
        say "could not mount $HOST:$OUT_REMOTE - the history will show book's own outputs only"
    fi
fi

# Already tunnelled — a second painter, or a manual forward being held. Use it
# rather than fight over the port.
#
# THIS TEST MUST COME BEFORE WE START OUR OWN FORWARD. It did not, briefly, and
# the answer it got was our own tunnel one moment old — so the branch killed the
# forward it had just started, the app found nothing on 8188, and painter sat on
# "backend is not ready yet" for ever.
FWD_SPECS=()
if comfy_answers; then
    if [ ${#APP[@]} -gt 0 ]; then
        PRIVATE_PORTS=1
        PORT=$((18000 + ($$ % 10000)))
        WPORT=$((28000 + ($$ % 10000)))
        export PAINTER_COMFY_URL="http://127.0.0.1:$PORT"
        export AI_WARDEN_URL="http://127.0.0.1:$WPORT"
        say "existing painter forward found - using private ports $PORT/$WPORT"
        FWD_SPECS+=("$PORT:8188" "$WPORT:8199")
    else
        say "127.0.0.1:$PORT already answers - using it"
    fi
else
    FWD_SPECS+=("$PORT:$PORT")
fi
if [ "$PRIVATE_PORTS" -eq 0 ] && port_open "$WPORT"; then
    say "127.0.0.1:$WPORT already bound - using it for the warden"
else
    FWD_SPECS+=("$WPORT:8199")
fi

if [ ${#FWD_SPECS[@]} -eq 0 ]; then
    if [ ${#APP[@]} -gt 0 ]; then
        # Run, do not `exec`: exec replaces this shell and the EXIT trap never
        # fires, so the sshfs mount we just made would outlive the app.
        trap 'stop_client_keeper; unmount_ours' EXIT
        start_client_keeper
        "${APP[@]}"
        exit $?
    fi
    exit 0
fi

# -N: no remote command. ExitOnForwardFailure so a refused bind is loud rather
# than a tunnel that silently forwards nothing.
FWD=("$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes
     -o ServerAliveInterval=20 -o ServerAliveCountMax=3
     -N)
for spec in "${FWD_SPECS[@]}"; do
    local_port="${spec%%:*}"
    remote_port="${spec##*:}"
    FWD+=(-L "127.0.0.1:$local_port:127.0.0.1:$remote_port")
done
FWD+=("$HOST")

# Backgrounded, so the app starts as soon as the port is bound rather than after
# a full handshake — the window opens in about a quarter of a second and must not
# wait on anything it does not strictly need.
if [ ${#APP[@]} -gt 0 ]; then
    "${FWD[@]}" &
    TUN=$!
    # One trap, set once, covering every exit including the die()s below: a
    # forward left running or a mount left behind is exactly the residue that
    # makes the NEXT launch take a stale path.
    cleanup() {
        stop_client_keeper
        stop_backend_ours
        kill "$TUN" 2>/dev/null || true
        unmount_ours
    }
    trap cleanup EXIT
fi

# STARTING THE BACKEND IS THE APP'S JOB, NOT THIS SCRIPT'S — when there is an
# app. main.py acquires a renewable lease through the forwarded warden, which
# starts ComfyUI for the first painter and keeps multiple windows/machines from
# stopping one another. Its direct systemctl path is the fallback if the warden
# cannot answer.
#
# With no app (`comfy-tunnel.sh` holding a forward by hand) there is nobody else
# to ask, so it still starts it here.
if [ ${#APP[@]} -eq 0 ]; then
    STATE="$("$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
             'systemctl --user is-active comfy-painter.service' 2>/dev/null)"
    if [ "$STATE" = "active" ]; then
        say "comfy-painter already running on $HOST"
    else
        say "comfy-painter is ${STATE:-unknown} on $HOST - starting it"
        "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
            'systemctl --user start comfy-painter.service' 2>/dev/null ||
            die "could not start comfy-painter on top (is a user session up there?)"
    fi
fi

if [ ${#APP[@]} -eq 0 ]; then
    say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT (ctrl-c to stop)"
    exec "${FWD[@]}"
fi
# WAIT FOR THE FORWARD, NOT FOR THE BACKEND. The port has to be bound before the
# app's first probe or it gives up on a connection refused — but waiting for
# ComfyUI to actually SERVE held the window closed for the whole cold start
# (weights, and a rebuilt nix-shell before them: minutes of no window at all).
# The app opens now and says "waiting for ComfyUI..." while it polls; its model
# list does not need the backend either, so there is something to do meanwhile.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    port_open "${FWD_SPECS[0]%%:*}" && break
    kill -0 "$TUN" 2>/dev/null ||
        die "ssh forward to $HOST died - on top: journalctl --user -u comfy-painter -n50"
    sleep 0.1
done
say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT; starting painter"

# The shell's heartbeat is deliberately started only after both forwards have
# bound, so it cannot accidentally talk to an unrelated local HTTP service.
start_client_keeper

# COMFY_ENSURE_BACKEND: the consumer will not start comfy-painter itself, so do
# it here and wait for it to actually SERVE before running the app — a headless
# render has no window to sit in front of while the backend warms. Only stop it
# after if we were the one who started it (stop_backend_ours checks the flag).
if [ -n "${COMFY_ENSURE_BACKEND:-}" ]; then
    STATE="$("$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
             'systemctl --user is-active comfy-painter.service' 2>/dev/null)"
    if [ "$STATE" = "active" ] && comfy_answers; then
        say "comfy-painter already serving on $HOST - leaving it as found"
    else
        if [ "$STATE" != "active" ]; then
            say "comfy-painter is ${STATE:-unknown} on $HOST - starting it"
            "$SSH" "${SSH_MUX[@]}" -o BatchMode=yes "$HOST" \
                'systemctl --user start comfy-painter.service' 2>/dev/null ||
                die "could not start comfy-painter on top (is a user session up there?)"
            STARTED_BACKEND=1
        fi
        say "waiting up to ${READY_TIMEOUT}s for comfy-painter to serve"
        deadline=$(( $(date +%s) + READY_TIMEOUT ))
        until comfy_answers; do
            if [ "$(date +%s)" -ge "$deadline" ]; then
                die "comfy-painter did not serve within ${READY_TIMEOUT}s - on top: journalctl --user -u comfy-painter -n50"
            fi
            kill -0 "$TUN" 2>/dev/null ||
                die "ssh forward to $HOST died while waiting for the backend"
            sleep 1
        done
        say "comfy-painter is serving on $HOST"
    fi
fi

"${APP[@]}"
