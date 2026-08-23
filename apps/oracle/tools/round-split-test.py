#!/usr/bin/env python3
"""A turn that takes tool rounds is one bubble PER ROUND, not one for all of it.

Everything a turn did used to pile into a single row — every round's prose,
every tool name and the final answer — so there was no telling where a round
began [his, 2026-08-23]. This drives one real prompt through the real window
(offscreen) against a STUB ollama on 127.0.0.1 that asks for two tool rounds,
and reads the chat rows back:

    row 0  you           the prompt
    row 1  model          round 1's prose + the tool it called
    row 2  model         round 2's prose + its tool
    row 3  model         the answer

His daemon is never touched, no model is loaded, nothing reaches his screen.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
ROUNDS = {"n": 0}
fails = []


class Stub(http.server.BaseHTTPRequestHandler):
    """Two rounds of one tool call each, then a plain answer."""

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
        self.rfile.read(n)
        if not self.path.startswith("/api/chat"):
            self._json({})
            return
        ROUNDS["n"] += 1
        i = ROUNDS["n"]
        if i <= 2:
            frames = [{"message": {"content": "looking at round %d." % i,
                                   "tool_calls": [
                                       {"function": {"name": "get_current_time",
                                                     "arguments": {}}}]},
                       "done": False},
                      {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "and here is the answer."}},
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
env["ORACLE_SEND"] = "do the thing"
env["QT_QPA_PLATFORM"] = "offscreen"
env["XDG_CURRENT_DESKTOP"] = "Hyprland"
env.pop("QT_QPA_PLATFORMTHEME", None)
env.pop("DESK_SESSION", None)
env.pop("WAYLAND_DISPLAY", None)
env.pop("DISPLAY", None)
out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                     env=env, capture_output=True, text=True, timeout=240)
srv.shutdown()
txt = out.stdout + out.stderr
m = re.search(r"^rows: (.*)$", txt, re.M)
if not m:
    print(txt[-1500:])
    print("FAILED: the harness printed no rows")
    sys.exit(1)
rows = json.loads(m.group(1))

check("the window still loads clean", "0 QML warning(s)" in txt)
check("the prompt is its own row", rows and rows[0]["isUser"])
replies = [r for r in rows if not r["isUser"]]
check("two tool rounds and an answer are THREE rows", len(replies) == 3,
      json.dumps([(r["step"], r["body"][:24]) for r in replies]))
if len(replies) == 3:
    check("the rows are numbered by the round they belong to",
          [r["step"] for r in replies] == [1, 2, 3],
          str([r["step"] for r in replies]))
    check("each round's prose stays on its own row",
          replies[0]["body"].strip() == "looking at round 1."
          and replies[1]["body"].strip() == "looking at round 2."
          and replies[2]["body"].strip() == "and here is the answer.",
          json.dumps([r["body"] for r in replies]))
    check("and so does the tool it called",
          replies[0]["toolCount"] == 1 and replies[1]["toolCount"] == 1
          and replies[2]["toolCount"] == 0,
          str([r["toolCount"] for r in replies]))
    check("nothing is left reading as still streaming",
          not any(r["streaming"] for r in rows))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
