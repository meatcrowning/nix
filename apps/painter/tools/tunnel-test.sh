#!/usr/bin/env bash
# comfy-tunnel.sh's own regression harness — the launcher, not the app.
#
# `ui-test.py` covers everything inside the window and can see none of this: the
# port, the mount and the teardown are the launcher's, and BOTH bugs that left
# painter unusable on book lived here rather than in the QML —
#
#   * the readiness probe's unset variable killing the script one second after it
#     started the backend (silently, exit 1: "painter does nothing");
#   * the reuse check reading OUR OWN forward as somebody else's and killing it,
#     so the app talked to a closed port for ever ("backend is not ready yet").
#
# So the thing this asserts is the one thing that matters: WHEN THE LAUNCHER
# HANDS OVER, THE APP CAN REACH COMFYUI. Everything else here is teardown.
#
# It uses the real top, over the real tunnel, and runs no GUI:
#
#     apps/painter/tools/tunnel-test.sh          # on book
#
# Nothing it does touches his session — no window, no notification (notify-send
# is kept off the PATH the launcher sees), and the backend is left exactly as it
# was found, running or not.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNEL="$HERE/comfy-tunnel.sh"
PORT="${COMFY_PORT:-8188}"
MOUNT="${PAINTER_MODELS_MOUNT:-${XDG_CACHE_HOME:-$HOME/.cache}/painter/models-top}"
FAILS=0

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
check() { if [ "$1" = "0" ]; then pass "$2"; else fail "$2 ${3:-}"; fi; }

# The launcher's own environment, minus anything that could reach him: no
# notify-send on this PATH, so a failure cannot toast his desktop mid-test.
run_launcher() {
    env PATH=/usr/bin:/bin:/usr/sbin timeout 120 bash "$TUNNEL" "$@" 2>&1
}

# What the APP does: an HTTP GET on the forwarded port. This is the assertion —
# a port that merely accepts is not a backend that answers.
PROBE='
exec 3<>/dev/tcp/127.0.0.1/'"$PORT"' || { echo PROBE=refused; exit 0; }
printf "GET /system_stats HTTP/1.0\r\n\r\n" >&3
read -r -t 5 line <&3
case "$line" in *" 200 "*) echo PROBE=ok ;; *) echo "PROBE=$line" ;; esac
'

echo "== the app can reach ComfyUI when the launcher hands over =="
out="$(run_launcher -- bash -c "$PROBE")"
grep -q "PROBE=ok" <<<"$out"
check $? "a command run under the launcher gets 200 from /system_stats" \
      "$(grep -E 'PROBE=|comfy-tunnel:' <<<"$out" | tr '\n' ' ')"

echo "== ...and again with a forward ALREADY held (the reuse path) =="
# A manual forward, exactly like a second painter or a hand-held tunnel. The
# launcher must use it rather than kill it or fight it for the port.
/usr/bin/ssh -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -N -L "127.0.0.1:$PORT:127.0.0.1:$PORT" top >/dev/null 2>&1 &
HELD=$!
trap 'kill "$HELD" 2>/dev/null' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
    sleep 0.2
done
out="$(run_launcher -- bash -c "$PROBE")"
grep -q "PROBE=ok" <<<"$out"
check $? "the reuse path leaves the app a working port" \
      "$(grep -E 'PROBE=|comfy-tunnel:' <<<"$out" | tr '\n' ' ')"
kill -0 "$HELD" 2>/dev/null
check $? "...and does not kill the forward it borrowed"
kill "$HELD" 2>/dev/null
trap - EXIT

echo "== the model root is mounted while the app runs =="
# Tagged, because the launcher's own progress lines share this stream.
out="$(run_launcher -- bash -c 'echo ENTRIES=$(ls "$PAINTER_MODELS" 2>/dev/null | wc -l)')"
n="$(grep -o 'ENTRIES=[0-9]*' <<<"$out" | head -1 | cut -d= -f2)"
[ "${n:-0}" -gt 0 ] 2>/dev/null
check $? "top's models are visible to the app" "entries=$n"

echo "== nothing is left behind =="
findmnt -rn "$MOUNT" >/dev/null 2>&1
[ $? -ne 0 ]
check $? "the sshfs mount is gone after the app exits"
pgrep -f -- "-N -L 127.0.0.1:$PORT:127.0.0.1:$PORT" >/dev/null
[ $? -ne 0 ]
check $? "no forward is left running"

echo
echo "$FAILS check(s) failed"
exit $((FAILS > 0))
