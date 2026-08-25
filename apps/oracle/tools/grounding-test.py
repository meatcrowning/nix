#!/usr/bin/env python3
"""Harness for the two things that keep chatter from inventing facts.

    <an app python> apps/oracle/tools/grounding-test.py

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched and
no model is ever loaded.

Both halves are asserted against the REAL POST body, not against the constants:

  * GROUNDING_NOTE rides every system prompt — say what you don't know, check a
    specific before stating it, never invent a citation.
  * the FACTUAL SAMPLER clamps temperature and top_p, EXCEPT under a preset he
    picked to be creative with (writer, casual). Chatter used to send no
    sampling options at all for most models, i.e. whatever hot default the
    Modelfile carried [his, 2026-08-24].
"""
import http.server
import json
import os
import sys
import threading
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

CHATS = []


class Stub(http.server.BaseHTTPRequestHandler):
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
        req = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.startswith("/api/chat"):
            self._json({})
            return
        CHATS.append(req)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for f in [{"message": {"content": "Done."}},
                  {"done": True, "done_reason": "stop",
                   "prompt_eval_count": 10, "eval_count": 1}]:
            self.wfile.write(json.dumps(f).encode() + b"\n")
            self.wfile.flush()

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]

from PySide6.QtCore import QTimer          # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                      # noqa: E402

app = QGuiApplication([])
o = oracle.Ollama()
done = []
o.replyDone.connect(lambda: done.append(1))
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"   [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


def pump(until, ms=8000):
    t = QTimer(); t.setSingleShot(True); t.timeout.connect(app.quit); t.start(ms)
    poll = QTimer(); poll.timeout.connect(lambda: until() and app.quit()); poll.start(20)
    app.exec(); poll.stop(); t.stop()


def turn(model="stub:latest", preset="default"):
    o._prior, o._prior_users = [], []
    o._prompt_choice = preset
    CHATS.clear(); done.clear()
    o.send(model, "who was ada lovelace", "[]")
    pump(lambda: bool(done))
    return CHATS[0]


print("chatter's grounding")

chat = turn()
system = "\n".join(m.get("content", "") for m in chat["messages"]
                   if m.get("role") == "system")

# ---- the contract is on the wire ----------------------------------------
check("the anti-confabulation block rides the system prompt",
      "DO NOT INVENT FACTS" in system)
check("it names the tool to check an encyclopedic fact with",
      "wikipedia" in oracle.GROUNDING_NOTE)
check("...and tells it to say so when it cannot check",
      "not sure" in oracle.GROUNDING_NOTE and "don't\nknow" not in oracle.GROUNDING_NOTE)
check("...and forbids an invented source outright",
      "Never invent a citation" in oracle.GROUNDING_NOTE)
check("...and covers his machine, where guessing is never necessary",
      "look, with the tools you have" in oracle.GROUNDING_NOTE)

# ---- the sampler is on the wire too -------------------------------------
opts = chat.get("options", {})
check("a factual turn sends a clamped temperature",
      opts.get("temperature") == oracle.FACTUAL_SAMPLER["temperature"], str(opts))
check("...and a tightened top_p", opts.get("top_p") == oracle.FACTUAL_SAMPLER["top_p"],
      str(opts))
check("...beside the window, which it must not have replaced",
      opts.get("num_ctx"), str(opts))

creative = turn(preset="writer").get("options", {})
check("a preset he picked to be CREATIVE with is left alone",
      "temperature" not in creative, str(creative))
check("...and still carries the window", creative.get("num_ctx"), str(creative))

# ---- the family defaults survive the floor ------------------------------
g = oracle.sampler_for("gemma4:26b", "default")
check("a published sampler keeps the knobs the floor does not touch",
      g.get("top_k") == 64 and g.get("min_p") == 0.0, str(g))
check("...but not its hot temperature", g.get("temperature") == 0.3, str(g))
check("...and under a creative preset it is untouched",
      oracle.sampler_for("gemma4:26b", "casual").get("temperature") == 1.0)
check("a custom base prompt is still a factual turn",
      oracle.sampler_for("stub:latest", "custom").get("temperature") == 0.3)

# ---- and describe_self reports what is actually sent --------------------
src = open(APP / "main.py").read()
check("describe_self reads its sampling off the same call, not off prose",
      '"sampling": dict(sampler_for(' in src)

print("FAILED: " + ", ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
