#!/usr/bin/env bash
# Harness for tools/heavy-gate.sh — the gate that keeps a heavy rebuild and a
# loaded GPU backend from overlapping without his say-so (sys/nixos-rebuild.nix
# calls it).
#
# It drives the gate against STUB endpoints, never the real ComfyUI or the real
# ollama: a test may not put a job on his backend any more than it may put a
# window on his screen. The stubs' queue_remaining and /api/ps bodies are files
# this script writes, so "a render is in flight" and "a 23G model is warm" are
# states the test can turn on and off.
#
# THE TOAST IS NEVER RAISED HERE. `ask` is exercised through
# HEAVY_GATE_ASK_ANSWER, which is the same code path minus notify-send — his
# screen is his (AGENTS.md, "Testing without interfering with the user").
#
# What is NOT covered, deliberately: the real suspend/resume cycle against
# comfy-painter.service and ollama.service, because it stops services he may be
# using. Comfy's half was verified by hand on 2026-08-09 (stopped, genuinely
# masked so painter's own startBackend is refused, resumed, state file cleared).
set -uo pipefail

GATE="$(dirname "$0")/heavy-gate.sh"
CPORT=18188
OPORT=18434
TMP=$(mktemp -d)
Q="$TMP/queue"; PS="$TMP/ps"
echo 0 >"$Q"
echo '{"models":[]}' >"$PS"
fails=0

check() {
  if [ "$2" = "$3" ]; then printf '  ok   %s\n' "$1"
  else printf '  FAIL %s\n       wanted %-12s got %s\n' "$1" "$3" "$2"; fails=$((fails + 1)); fi
}

# One stub server per backend: comfy answers /prompt from $Q, ollama answers
# /api/ps from $PS verbatim.
python3 - "$CPORT" "$Q" "$OPORT" "$PS" <<'PY' &
import sys, threading, http.server
cport, qfile, oport, psfile = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]

def serve(port, body_fn):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = body_fn()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()

threading.Thread(target=serve, args=(cport, lambda: b'{"exec_info": {"queue_remaining": %d}}'
                                     % int(open(qfile).read().strip() or 0)), daemon=True).start()
serve(oport, lambda: open(psfile, "rb").read())
PY
STUB=$!
trap 'kill $STUB 2>/dev/null; rm -rf "$TMP"' EXIT INT TERM
sleep 1

export HEAVY_GATE_COMFY_URL="http://127.0.0.1:$CPORT"
export HEAVY_GATE_OLLAMA_URL="http://127.0.0.1:$OPORT"
export HEAVY_GATE_NO_NOTIFY=1

warm() {  # $1 = how many bytes resident
  printf '{"models":[{"name":"qwen3.6:35b-a3b","size":%s,"size_vram":%s}]}\n' "$1" "$1" >"$PS"
}
cold() { echo '{"models":[]}' >"$PS"; }

# --- ollama: warm is the signal, and it is independent of comfy -------------
if systemctl is-active --quiet ollama.service; then
  cold
  check "no resident model reads idle"              "$("$GATE" status | grep -c 'ollama=idle')" 1
  check "an idle ollama does not arm the gate"      "$("$GATE" loaded >/dev/null 2>&1; echo $?)" 1
  warm 24000000000
  check "a warm model arms the gate"                "$("$GATE" loaded >/dev/null 2>&1; echo $?)" 0
  check "status names the warm model and its size"  \
        "$("$GATE" status | grep -c 'ollama=warm(1 model, 22.4G)')" 1
  # The ask, stubbed at the answer: what matters here is that a warm ollama is
  # something the gate asks ABOUT rather than acts on by itself.
  check "a warm ollama is asked about, not assumed" \
        "$(HEAVY_GATE_ASK_ANSWER=stop "$GATE" ask 5 2>/dev/null)" stop
  check "no answer inside the timeout reads as 'anyway'" \
        "$(HEAVY_GATE_ASK_ANSWER=timeout "$GATE" ask 5 2>/dev/null)" timeout
  cold
else
  echo "  SKIP: ollama is not running, so its state can only answer 'down'"
  check "a stopped ollama does not arm the gate" \
        "$("$GATE" loaded >/dev/null 2>&1; echo $?)" 1
fi

# --- comfy: the queue, and the rule that a render is never cut --------------
if systemctl --user is-active --quiet comfy-painter.service; then
  echo 0 >"$Q"; check "an idle queue reads idle"        "$("$GATE" status | grep -c 'comfy=idle')" 1
  echo 2 >"$Q"; check "a queued job reads rendering"    "$("$GATE" status | grep -c 'comfy=rendering')" 1

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
  check "an unreachable comfy is not 'rendering'" \
        "$(HEAVY_GATE_COMFY_URL=http://127.0.0.1:1 "$GATE" status | grep -c 'comfy=starting')" 1
  echo 0 >"$Q"
else
  echo "  SKIP: comfy-painter is not running, so its state can only answer 'down'"
  check "a stopped comfy reads down" "$("$GATE" status | grep -c 'comfy=down')" 1
fi

# --- both down: nothing to ask, nothing to undo -----------------------------
if ! systemctl --user is-active --quiet comfy-painter.service \
   && ! { systemctl is-active --quiet ollama.service && grep -q '"name"' "$PS"; }; then
  check "ask with nothing loaded answers 'clear'" "$("$GATE" ask 1 2>/dev/null)" clear
fi
check "resume with nothing suspended is a no-op" "$("$GATE" resume >/dev/null 2>&1; echo $?)" 0

echo
[ "$fails" = 0 ] && echo "heavy-gate: all checks passed" || echo "heavy-gate: $fails FAILED"
exit $((fails > 0))
