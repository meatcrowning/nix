#!/usr/bin/env bash
# Run painter ON BOOK against top's ComfyUI, over an ssh tunnel.
#
# This is also painter's LAUNCHER on book: home/prog/painter.nix's `air` branch
# execs `comfy-tunnel.sh -- python3 main.py`, so opening painter from the runner
# does the whole thing by itself — probe top, forward 8188 and mount top's model
# and output roots at the same time, start the backend there if it is not already
# up, run the app as soon as the port is bound, and tear it all down after. (The
# output root is what makes book's history the WHOLE history: top's backend files
# every result it produces on top, whichever machine asked for it.) It does NOT wait
# for ComfyUI to finish loading: the window opens now and says what it is waiting
# for.
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
# Same reason for sshfs and fusermount3 — Fedora's, under /usr/sbin.
SSHFS="${COMFY_SSHFS:-/usr/sbin/sshfs}"
FUSERMOUNT="${COMFY_FUSERMOUNT:-/usr/sbin/fusermount3}"
MODELS_REMOTE="${COMFY_MODELS:-/home/lam/models}"
MODELS_LOCAL="${PAINTER_MODELS_MOUNT:-${XDG_CACHE_HOME:-$HOME/.cache}/painter/models-top}"
OUT_REMOTE="${COMFY_OUT:-/home/lam/Pictures/painter/out}"
OUT_LOCAL="${PAINTER_PEER_OUT_MOUNT:-${XDG_CACHE_HOME:-$HOME/.cache}/painter/out-top}"
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
if comfy_answers; then
    say "127.0.0.1:$PORT already answers - using it"
    if [ ${#APP[@]} -gt 0 ]; then
        # Run, do not `exec`: exec replaces this shell and the EXIT trap never
        # fires, so the sshfs mount we just made would outlive the app.
        trap unmount_ours EXIT
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

# Backgrounded, so the app starts as soon as the port is bound rather than after
# a full handshake — the window opens in about a quarter of a second and must not
# wait on anything it does not strictly need.
if [ ${#APP[@]} -gt 0 ]; then
    "${FWD[@]}" &
    TUN=$!
    # One trap, set once, covering every exit including the die()s below: a
    # forward left running or a mount left behind is exactly the residue that
    # makes the NEXT launch take a stale path.
    trap 'stop_backend_ours; kill "$TUN" 2>/dev/null; unmount_ours' EXIT
fi

# STARTING THE BACKEND IS THE APP'S JOB, NOT THIS SCRIPT'S — when there is an
# app. main.py fires startBackend() on its first tick, over this same ssh
# connection and without blocking its GUI thread, and reports progress in the
# window where he can see it. Doing it here as well only added an ssh round trip
# in front of the window, to say the same thing in a toast.
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
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
    kill -0 "$TUN" 2>/dev/null ||
        die "ssh forward to $HOST died - on top: journalctl --user -u comfy-painter -n50"
    sleep 0.1
done
say "forwarding 127.0.0.1:$PORT -> $HOST:$PORT; starting painter"

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
