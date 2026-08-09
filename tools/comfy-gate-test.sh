#!/usr/bin/env bash
# Harness for tools/comfy-gate.sh — the gate that keeps a heavy rebuild and a
# ComfyUI render from ever overlapping (sys/nixos-rebuild.nix calls it).
#
# It drives the gate against a STUB queue endpoint, never the real ComfyUI:
# a test may not put a job on his backend any more than it may put a window on
# his screen. The stub's queue_remaining is a file this script writes, so
# "a render is in flight" is something the test can turn on and off.
#
# What is NOT covered here, deliberately: the real suspend/resume cycle against
# comfy-painter.service, because it stops and starts a service he may be using.
# That was verified by hand on 2026-08-09 (stopped, genuinely masked so
# painter's own startBackend is refused, resumed, state file cleared).
set -uo pipefail

GATE="$(dirname "$0")/comfy-gate.sh"
PORT=18188
Q=$(mktemp -d)/queue
echo 0 >"$Q"
fails=0

check() {
  if [ "$2" = "$3" ]; then printf '  ok   %s\n' "$1"
  else printf '  FAIL %s\n       wanted %-12s got %s\n' "$1" "$3" "$2"; fails=$((fails + 1)); fi
}

python3 - "$PORT" "$Q" <<'PY' &
import sys, http.server
port, qfile = int(sys.argv[1]), sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        n = int(open(qfile).read().strip() or 0)
        body = b'{"exec_info": {"queue_remaining": %d}}' % n
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
STUB=$!
trap 'kill $STUB 2>/dev/null; rm -rf "$(dirname "$Q")"' EXIT INT TERM
sleep 1

export COMFY_GATE_URL="http://127.0.0.1:$PORT"
export COMFY_GATE_NO_NOTIFY=1

# status only reaches the queue when the unit is up; with it down, the answer is
# `down` whatever the queue says, and nothing else in the gate runs at all.
if systemctl --user is-active --quiet comfy-painter.service; then
  echo 0 >"$Q"; check "an idle queue reads idle"       "$("$GATE" status)" idle
  echo 2 >"$Q"; check "a queued job reads rendering"   "$("$GATE" status)" rendering
  echo 1 >"$Q"; check "one running job reads rendering" "$("$GATE" status)" rendering

  # The rule that matters most: a render in flight is never interrupted.
  check "suspend REFUSES while a render is in flight" \
        "$("$GATE" suspend >/dev/null 2>&1; echo $?)" 1

  # wait returns as soon as the queue drains, and not before.
  ( sleep 3; echo 0 >"$Q" ) &
  start=$(date +%s)
  "$GATE" wait 60 >/dev/null 2>&1; rc=$?
  waited=$(( $(date +%s) - start ))
  check "wait blocks until the queue drains" "$rc" 0
  check "and it really waited"               "$([ "$waited" -ge 3 ] && echo yes || echo no)" yes

  echo 5 >"$Q"
  check "wait gives up at its timeout rather than forever" \
        "$("$GATE" wait 1 >/dev/null 2>&1; echo $?)" 1

  # An unreachable backend is NOT a render: a comfy still starting up has
  # nothing in flight to protect, and reporting it as busy would hang a rebuild.
  COMFY_GATE_URL="http://127.0.0.1:1" \
    check "an unreachable comfy is not 'rendering'" "$(COMFY_GATE_URL=http://127.0.0.1:1 "$GATE" status)" starting
else
  echo "  SKIP: comfy-painter is not running, so status can only answer 'down'"
  check "a stopped comfy reads down" "$("$GATE" status)" down
  check "resume with nothing suspended is a no-op" "$("$GATE" resume >/dev/null 2>&1; echo $?)" 0
fi

echo
[ "$fails" = 0 ] && echo "comfy-gate: all checks passed" || echo "comfy-gate: $fails FAILED"
exit $((fails > 0))
