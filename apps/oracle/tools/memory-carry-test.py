#!/usr/bin/env python3
"""What the agent did last turn is still there the next turn.

Until 2026-08-22 it was not: the message list was rebuilt from the chat log on
every turn (`_parse_history` keeps user/assistant TEXT and nothing else), so
every tool call and every tool RESULT died with the turn that made it. A real
session [his] shows what that costs — an agent asked to change something in
`~/nix` re-read the same files on turn after turn, re-derived the same
conclusion five times, and never reached the edit.

This drives TWO prompts through the real window (offscreen) against a STUB
ollama on 127.0.0.1, and reads the REQUEST BODIES the app sent:

    turn 1   the model calls read_file on a temp file, then answers
    turn 2   a plain prompt — and its request must still carry turn 1's
             tool call, its result, and the file's actual contents

The same bodies prove the other half: the first file tool to touch a tree that
has an `AGENTS.md` hands its path back with the result (`_house_note`), so the
house rules arrive without him naming them.

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
BODIES = []          # every /api/chat request body, in order
fails = []

TREE = Path(tempfile.mkdtemp(prefix="oracle-carry-"))
(TREE / "AGENTS.md").write_text("house rules for this fake tree\n")
NEEDLE = "the-answer-is-in-this-file"
(TREE / "note.txt").write_text(NEEDLE + "\n")


class Stub(http.server.BaseHTTPRequestHandler):
    """Turn 1 reads a file then answers; turn 2 answers straight away."""

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
        # The FIRST request of all asks for the file; everything after answers,
        # so turn 2 is a plain turn whose only interesting part is what the app
        # chose to send with it.
        if len(BODIES) == 1:
            frames = [{"message": {"content": "let me look.",
                                   "tool_calls": [
                                       {"function": {
                                           "name": "read_file",
                                           "arguments": {
                                               "path": str(TREE / "note.txt")}}}]},
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
env["ORACLE_SEND"] = "read that file;;so what did it say?"
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
check("three requests: two rounds of turn 1, then turn 2", len(BODIES) == 3,
      str(len(BODIES)))
if len(BODIES) < 3:
    print("FAILED: " + ", ".join(fails or ["too few requests"]))
    sys.exit(1)

first_round, tool_round, second_turn = BODIES[0], BODIES[1], BODIES[2]


def roles(body):
    return [m.get("role") for m in body.get("messages", [])]


def tools_in(body):
    return [m for m in body.get("messages", []) if m.get("role") == "tool"]


# --- the turn itself still works exactly as it did ------------------------
check("turn 1 opens with no tool results of its own",
      not tools_in(first_round), str(roles(first_round)))
check("its second round carries the result of the read",
      any(NEEDLE in str(m.get("content")) for m in tools_in(tool_round)))

# --- the fix: the NEXT turn still has it ----------------------------------
carried = tools_in(second_turn)
check("turn 2 still carries turn 1's tool result", bool(carried),
      str(roles(second_turn)))
check("and the file's actual contents are still in it",
      any(NEEDLE in str(m.get("content")) for m in carried))
check("the call that produced it is there too, so it is not repeated",
      any(m.get("role") == "assistant" and m.get("tool_calls")
          for m in second_turn.get("messages", [])))
check("the system message is rebuilt, not carried",
      roles(second_turn).count("system") == 1, str(roles(second_turn)))

# --- the house rules, handed over unasked ---------------------------------
check("the tree's AGENTS.md is named with the first read of it",
      any("AGENTS.md" in str(m.get("content")) for m in tools_in(tool_round)),
      "(guide note)")
check("and it is named ONCE, not on every result",
      sum(str(m.get("content", "")).count("house rules:")
          for m in tools_in(second_turn)) <= 1)

# --- the budget -----------------------------------------------------------
sys.path.insert(0, str(APP))
try:
    import main as oracle_main
    big = [{"role": "tool", "content": "x" * (oracle_main.TOOL_CARRY_CHARS + 50)},
           {"role": "assistant", "content": "keep me", "tool_calls": [{}]},
           {"role": "tool", "content": "y" * 100}]
    trimmed = oracle_main.Ollama._trim_carry([dict(m) for m in big])
    check("an over-budget older result is stubbed",
          trimmed[0]["content"] == oracle_main.TOOL_CARRY_STUB)
    check("the newest one survives whole", trimmed[2]["content"] == "y" * 100)
    check("the call that made it is untouched",
          trimmed[1]["content"] == "keep me" and trimmed[1].get("tool_calls"))
except ImportError as exc:      # no PySide6 in this interpreter
    print("skip  the budget check (%s)" % exc)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
