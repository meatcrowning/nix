#!/usr/bin/env bash
# Book's gqrx runs against top's RTL-SDR dongle: rtl_tcp starts on top's
# loopback and the IQ stream (1.8 Msps = 3.6 MB/s) rides an SSH forward, so
# nothing opens on tailscale0 (only 22/445). Tuning, demod and audio all
# happen here; closing gqrx closes the forward, which ends rtl_tcp on top.
#
#   gqrx-top          start rtl_tcp on top, forward it, run gqrx
#   gqrx-top --sync   first copy top's gqrx settings, bookmarks and bandplan
set -uo pipefail

PORT="${GQRX_TOP_PORT:-12345}"
HOST="${GQRX_TOP_HOST:-top}"
# Fedora's ssh: nix-built binaries on book cannot resolve .local.
SSH=/usr/bin/ssh
CONF="$HOME/.config/gqrx"
DEVICE="rtl_tcp=127.0.0.1:$PORT"
LOG="${XDG_RUNTIME_DIR:-/tmp}/gqrx-top.log"

die() { printf 'gqrx-top: %s\n' "$*" >&2; notify-send -a gqrx -- "gqrx-top" "$*" 2>/dev/null; exit 1; }

if [ "${1:-}" = --sync ] || [ ! -e "$CONF/default.conf" ]; then
    mkdir -p "$CONF"
    for f in default.conf bookmarks.csv bandplan.csv; do
        "$SSH" -o BatchMode=yes "$HOST" cat ".config/gqrx/$f" > "$CONF/$f.new" \
            && mv "$CONF/$f.new" "$CONF/$f" || die "could not copy $f from $HOST"
    done
fi

# gqrx has no device flag; point the saved config at the forward. A dropped
# link kills gqrx uncleanly, which sets crashed=true and turns the next
# launch into a "Crash Detected" prompt; clear it.
sed -i -e "s|^device=.*|device=\"$DEVICE\"|" -e "s|^crashed=true|crashed=false|" "$CONF/default.conf"

# Without a tty, killing this ssh does not signal the remote side, so rtl_tcp
# would outlive the session and hold the dongle. The remote shell instead
# waits on stdin (a never-writing pipe held here) and stops rtl_tcp at EOF,
# which comes when this script exits for any reason. A stale rtl_tcp from a
# lost link is replaced; a local SDR app on top is left alone.
exec 4< <(exec sleep infinity)
HOLD=$!
"$SSH" -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 \
    -L "$PORT:127.0.0.1:1234" "$HOST" \
    'pgrep -x "gqrx|sdrpp|rtl_433|dump1090" >/dev/null && { echo "dongle busy on top" >&2; exit 3; }
     pkill -x rtl_tcp && sleep 1
     stdbuf -oL rtl_tcp -a 127.0.0.1 -p 1234 >&2 & p=$!
     cat >/dev/null; kill $p' <&4 2>"$LOG" &
TUNNEL=$!
exec 4<&-
trap 'kill $HOLD $TUNNEL 2>/dev/null' EXIT

# The local end of the forward accepts before rtl_tcp listens, so wait for
# rtl_tcp's own "listening..." line rather than probing the port.
# (stdbuf: rtl_tcp block-buffers stdout without a tty.)
for _ in $(seq 1 75); do
    grep -q listening "$LOG" && break
    kill -0 "$TUNNEL" 2>/dev/null || die "rtl_tcp on $HOST did not start: $(tail -1 "$LOG")"
    sleep 0.2
done
grep -q listening "$LOG" || die "rtl_tcp on $HOST timed out: $(tail -1 "$LOG")"

gqrx "$@"
