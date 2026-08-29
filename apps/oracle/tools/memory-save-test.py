#!/usr/bin/env python3
"""A memory the model saves ITSELF lands in the store, and comes back next turn.

He asked whether chatter is actually able to keep a fact on its own initiative
[his, 2026-08-22] — the store had two memories and nothing recent, which reads
the same from outside whether the mechanism is broken or the model simply never
called the tool. This settles it: a STUB ollama on 127.0.0.1 calls `save_memory`
exactly the way a model would, and the test reads back

  * the store file itself (`$ORACLE_MEMORY`, a temp dir — his own memories are
    never touched), and
  * the SYSTEM PROMPT of the next turn, which must now carry the fact.

So a failure here is the harness's fault, and a pass means an empty store is the
model declining to save, not chatter dropping it.

His daemon is never touched, no model is loaded, nothing reaches his screen.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
BODIES = []
fails = []
FACT = "He keeps his flake in ~/nix and rebuilds with rebuild-top."
MEM = Path(tempfile.mkdtemp(prefix="oracle-mem-"))


class Stub(http.server.BaseHTTPRequestHandler):
    """Turn 1 saves a memory then answers; turn 2 just answers."""

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [{"name": "stub:latest"}]})
        elif self.path.startswith("/api/ps"):
            self._json({"models": []})
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if not self.path.startswith("/api/chat"):
            self._json({})
            return
        try:
            BODIES.append(json.loads(raw))
        except ValueError:
            BODIES.append({})
        if len(BODIES) == 1:
            frames = [{"message": {"content": "worth keeping.",
                                   "tool_calls": [
                                       {"function": {"name": "save_memory",
                                                     "arguments": {
                                                         "text": FACT,
                                                         "source_quote":
                                                             "remember how i build this"}}}]},
                       "done": False},
                      {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "answer %d." % len(BODIES)}},
                      {"done": True, "done_reason": "stop"}]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for f in frames:
            self.wfile.write(json.dumps(f).encode() + b"\n")
            self.wfile.flush()

    def log_message(self, *a):
        pass


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()

env = dict(os.environ)
env["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]
env["ORACLE_MEMORY"] = str(MEM)
env["ORACLE_SEND"] = "remember how i build this;;what did you keep?"
env["QT_QPA_PLATFORM"] = "offscreen"
env["XDG_CURRENT_DESKTOP"] = "Hyprland"
env.pop("QT_QPA_PLATFORMTHEME", None)
env.pop("DESK_SESSION", None)
env.pop("WAYLAND_DISPLAY", None)
env.pop("DISPLAY", None)
out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                     env=env, capture_output=True, text=True, timeout=300)
srv.shutdown()
txt = out.stdout + out.stderr
if not re.search(r"^rows: ", txt, re.M):
    print(txt[-1500:])
    print("FAILED: the harness never finished a turn")
    sys.exit(1)

check("the window still loads clean", "0 QML warning(s)" in txt)

# --- the store ------------------------------------------------------------
store = MEM / "memories.json"
saved = []
if store.is_file():
    try:
        saved = json.loads(store.read_text()).get("memories", [])
    except ValueError:
        saved = []
check("the model's own save_memory call wrote the store", bool(saved),
      str(store))
check("and it wrote the fact it was given",
      any(FACT in str(m.get("text")) for m in saved),
      json.dumps(saved)[:200])
check("and records the user's supporting words",
      any(m.get("source_quote") == "remember how i build this" for m in saved),
      json.dumps(saved)[:200])

# --- and it comes back ----------------------------------------------------
if len(BODIES) >= 3:
    later = BODIES[-1].get("messages", [])
    sysmsg = later[0].get("content", "") if later else ""
    check("the next turn's system prompt carries it back", FACT in sysmsg,
          sysmsg[:160])
    check("under a heading that says these are its own memories",
          "memories you have saved" in sysmsg.lower(), "")
else:
    check("three requests: the save round, its answer, then turn 2",
          False, str(len(BODIES)))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
