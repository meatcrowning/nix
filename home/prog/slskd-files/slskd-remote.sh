#!/usr/bin/env bash
# Book's route to Soulseek: there is no slskd here. The daemon, the Soulseek
# credentials and the music library all live on top (home/prog/slskd.nix only
# installs the service there), so every slsk consumer on book -- the slsk app,
# apps/player/tools/soulseek-missing.py, the oracle soulseek_* tools -- talks
# to top's loopback API through an SSH forward, exactly like painter reaches
# top's ComfyUI via comfy-tunnel.sh.
#
#   slskd-remote ensure     start slskd on top, forward 5030, cache the api key
#   slskd-remote is-active  "active"/"inactive" of the daemon ON TOP
#   slskd-remote status     one human line
#   slskd-remote down       close the forward (leaves top's daemon running)
#   slskd-remote stop       stop top's daemon and close the forward
#
# ensure is idempotent and cheap: if the port already answers the API it does
# nothing. The api key is copied from top into ~/.secrets/slskd-api-key (600)
# so every existing consumer keeps its default path and needs no flags.
set -uo pipefail

PORT="${SLSKD_PORT:-5030}"
HOSTS="${SLSKD_SSH_HOSTS:-top top.local}"
# Fedora's ssh: nix-built binaries on book cannot resolve .local (nss-mdns).
SSH="${SLSKD_SSH:-/usr/bin/ssh}"
CTL="${XDG_RUNTIME_DIR:-/tmp}/slskd-remote.ctl"
KEY_FILE="$HOME/.secrets/slskd-api-key"
CONNECT_TIMEOUT="${SLSKD_CONNECT_TIMEOUT:-15}"
READY_TIMEOUT="${SLSKD_READY_TIMEOUT:-60}"

say() { printf 'slskd-remote: %s\n' "$*" >&2; }
die() { say "$*"; exit 1; }

ssh_to() {  # ssh_to <host> <args...>
    local h="$1"; shift
    "$SSH" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" "$h" "$@"
}

# Which of the candidate names answers? Cached per invocation only.
pick_host() {
    local h
    for h in $HOSTS; do
        if ssh_to "$h" true >/dev/null 2>&1; then printf '%s' "$h"; return 0; fi
    done
    return 1
}

api_answers() {
    local key="" ; [ -f "$KEY_FILE" ] && key="$(cat "$KEY_FILE")"
    curl -fsS -m 5 -H "X-API-Key: $key" \
        "http://127.0.0.1:$PORT/api/v0/application" >/dev/null 2>&1
}

forward_up() { "$SSH" -S "$CTL" -O check placeholder >/dev/null 2>&1; }

fetch_key() {
    local h="$1" key
    key="$(ssh_to "$h" 'cat ~/.secrets/slskd-api-key' 2>/dev/null)" || return 1
    [ -n "$key" ] || return 1
    mkdir -p "$HOME/.secrets" && chmod 700 "$HOME/.secrets"
    printf '%s' "$key" > "$KEY_FILE" && chmod 600 "$KEY_FILE"
}

cmd_ensure() {
    api_answers && { say "already up on 127.0.0.1:$PORT"; return 0; }
    local h; h="$(pick_host)" || die "top unreachable over ssh ($HOSTS)"
    fetch_key "$h" || die "could not read top's ~/.secrets/slskd-api-key"
    ssh_to "$h" 'systemctl --user start slskd' || die "could not start slskd on $h"
    forward_up || "$SSH" -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" \
        -f -N -M -S "$CTL" -L "$PORT:127.0.0.1:$PORT" "$h" ||
        die "could not forward $PORT from $h"
    local waited=0
    until api_answers; do
        [ "$waited" -ge "$READY_TIMEOUT" ] && die "slskd on $h did not answer in ${READY_TIMEOUT}s"
        sleep 1; waited=$((waited + 1))
    done
    say "slskd on $h, forwarded to 127.0.0.1:$PORT"
}

cmd_is_active() {
    local h; h="$(pick_host)" || { echo inactive; return 3; }
    local s; s="$(ssh_to "$h" 'systemctl --user is-active slskd' 2>/dev/null)"
    [ "$s" = active ] && { echo active; return 0; }
    echo "${s:-inactive}"; return 3
}

cmd_down() {
    forward_up && "$SSH" -S "$CTL" -O exit placeholder >/dev/null 2>&1
    say "forward closed"
}

cmd_stop() {
    local h; h="$(pick_host)" && ssh_to "$h" 'systemctl --user stop slskd'
    cmd_down
}

cmd_status() {
    local d; d="$(cmd_is_active)"
    local f="down"; forward_up && f="up"
    local a="no"; api_answers && a="yes"
    printf 'daemon on top: %s | forward: %s | api on 127.0.0.1:%s: %s\n' "$d" "$f" "$PORT" "$a"
}

case "${1:-status}" in
    ensure)    cmd_ensure ;;
    is-active) cmd_is_active ;;
    status)    cmd_status ;;
    down)      cmd_down ;;
    stop)      cmd_stop ;;
    *)         die "usage: slskd-remote {ensure|is-active|status|down|stop}" ;;
esac
