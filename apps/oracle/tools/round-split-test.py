#!/usr/bin/env python3
"""A turn that takes tool rounds is one bubble PER ROUND, not one for all of it.

Everything a turn did used to pile into a single row — every round's prose,
every tool name and the final answer — so there was no telling where a round
began [his, 2026-08-23]. This drives one real prompt through the real window
(offscreen) against a STUB ollama on 127.0.0.1, and reads the chat rows back.

Two scenarios, mode-selected so each stays independent:

    MODE=rounds  (default, the original) — two plain tool rounds, no media:
        row 0  you           the prompt
        row 1  model          round 1's prose + the tool it called
        row 2  model         round 2's prose + its tool
        row 3  model         the answer
    A turn with no media splits once per round, and a round that said nothing
    is drawn only as the turn's meta block.

    MODE=media — round 1 shows a picture and says nothing, round 2 answers:
        row 0  you           the prompt
        row 1  model          the picture AND "here is the picture…" (ONE row)
    A media-only round does NOT open a fresh bubble [his, 2026-08-23]: the next
    round's text lands on the same row, so the image and the answer it
    accompanies read as one message instead of a detached picture floating
    above a separate text bubble.

His daemon is never touched, no model is loaded, nothing reaches his screen.
"""
import base64
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
fails = []
ST = {"n": 0}


def make_png():
    """A tiny 1x1 PNG for `show_image` to draw — real pixels, no network."""
    p = Path(tempfile.mkdtemp()) / "pix.png"
    p.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYA"
        "AAAAYAAjCB0C8AAAAASUVORK5CYII="))
    return str(p)


class Stub(http.server.BaseHTTPRequestHandler):
    mode = "rounds"
    png = ""

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
        ST["n"] += 1
        i = ST["n"]
        if self.mode == "preamble":
            # WHAT HE ACTUALLY SAW [2026-08-24]: the round that shows the
            # picture announces it first, and the round after says the same
            # thing again in a bubble of its own with nothing in it.
            if i == 1:
                frames = [{"message": {"content": "Here's your Lain image:",
                                       "tool_calls": [
                                           {"function": {"name": "show_image",
                                                         "arguments": {"path": self.png}}}]},
                           "done": False},
                          {"done": True, "done_reason": "stop"}]
            else:
                frames = [{"message": {"content": "Here you go — here's Lain:"}},
                          {"done": True, "done_reason": "stop"}]
        elif self.mode == "media":
            if i == 1:
                # Round 1 shows a picture and says nothing — a media-only round.
                frames = [{"message": {"content": "",
                                       "tool_calls": [
                                           {"function": {"name": "show_image",
                                                         "arguments": {"path": self.png}}}]},
                           "done": False},
                          {"done": True, "done_reason": "stop"}]
            else:
                frames = [{"message": {"content": "here is the picture I looked at."}},
                          {"done": True, "done_reason": "stop"}]
        else:
            if i <= 2:
                # Round 1 says NOTHING and only calls a tool — the bookkeeping that
                # folds. Round 2 speaks, which is output and must stay drawn.
                frames = [{"message": {"content": "" if i == 1 else "looking at round 2.",
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


def run_app():
    ST["n"] = 0                     # each scenario is a fresh conversation
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ)
    env["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]
    env["ORACLE_SEND"] = "do the thing"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CURRENT_DESKTOP"] = "Hyprland"
    for k in ("QT_QPA_PLATFORMTHEME", "DESK_SESSION", "WAYLAND_DISPLAY", "DISPLAY"):
        env.pop(k, None)
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=240)
    srv.shutdown()
    return out


def parse(out):
    txt = out.stdout + out.stderr
    m = re.search(r"^rows: (.*)$", txt, re.M)
    mf = re.search(r"^turns: (.*)$", txt, re.M)
    if not m:
        print(txt[-1500:])
        print("FAILED: the harness printed no rows")
        sys.exit(1)
    return txt, json.loads(m.group(1)), (json.loads(mf.group(1)) if mf else None)


# ---- MODE=rounds: the original split behaviour -----------------------------
Stub.mode = "rounds"
txt, rows, turns = parse(run_app())
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
          replies[0]["body"].strip() == ""
          and replies[1]["body"].strip() == "looking at round 2."
          and replies[2]["body"].strip() == "and here is the answer.",
          json.dumps([r["body"] for r in replies]))
    check("and so does the tool it called",
          replies[0]["toolCount"] == 1 and replies[1]["toolCount"] == 1
          and replies[2]["toolCount"] == 0,
          str([r["toolCount"] for r in replies]))
    check("nothing is left reading as still streaming",
          not any(r["streaming"] for r in rows))
check("the turn block reports itself", bool(turns))
if turns:
    check("his prompt is in no turn", turns[0]["head"] == -1)
    check("every model row of the turn points at the same head",
          [t["head"] for t in turns] == [-1, 1, 1, 1],
          json.dumps([t["head"] for t in turns]))
    check("the head is the only row carrying the block",
          turns[1]["rounds"] == 3 and turns[2]["rounds"] == 0,
          json.dumps([t["rounds"] for t in turns]))
    check("the block counts every round's tools",
          turns[1]["tools"] == 2, str(turns[1]["tools"]))
    check("a round that said nothing is drawn only as the block",
          turns[1]["drawn"] and turns[2]["drawn"] and turns[3]["drawn"],
          json.dumps([t["drawn"] for t in turns]))

# ---- MODE=media: a media-only round merges with the following text ---------
Stub.mode = "media"
Stub.png = make_png()
txt, rows, turns = parse(run_app())
check("the window still loads clean (media)", "0 QML warning(s)" in txt)
check("the prompt is its own row (media)", rows and rows[0]["isUser"])
replies = [r for r in rows if not r["isUser"]]
check("a media-only round and its answer are ONE row", len(replies) == 1,
      json.dumps([(r["step"], r["body"][:28], r["images"]) for r in replies]))
if len(replies) == 1:
    r = replies[0]
    check("the picture landed on the merged row", r["images"] not in ("", "[]"),
          r["images"][:60])
    check("the following round's text landed on the SAME row",
          r["body"].strip() == "here is the picture I looked at.",
          json.dumps(r["body"]))
    check("no second bubble was opened for the answer", r["step"] == 1,
          str(r["step"]))
    check("nothing is left reading as still streaming (media)",
          not any(x["streaming"] for x in rows))

# ---- MODE=preamble: a short line in front of the picture is not an answer --
# The row that called the tool wrote before it saw the result; the round after
# it then repeats itself in an empty bubble. The preamble is dropped and the two
# merge, so one picture gets one bubble and one sentence.
Stub.mode = "preamble"
txt, rows, turns = parse(run_app())
check("the window still loads clean (preamble)", "0 QML warning(s)" in txt)
replies = [r for r in rows if not r["isUser"]]
check("an announcement in front of a picture does not split the turn",
      len(replies) == 1,
      json.dumps([(r["step"], r["body"][:34], r["images"][:20]) for r in replies]))
if len(replies) == 1:
    r = replies[0]
    check("the picture is on the one row", r["images"] not in ("", "[]"),
          r["images"][:60])
    check("the announcement is gone and the answer stands",
          r["body"].strip() == "Here you go — here's Lain:", json.dumps(r["body"]))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
