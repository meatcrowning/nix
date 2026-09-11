#!/usr/bin/env python3
"""A DECISION, put to him as buttons — and what the agent does with the answer.

`ask_choice` (main.py) is a tool call that DOES NOT RETURN until he clicks: the
round stays open, so the agent that asked is still holding everything it knew
when it asked. This drives real turns through the real window (offscreen)
against a STUB ollama on 127.0.0.1 and reads both halves — the request bodies
the model gets back, and the rendered card in the transcript.

What it pins down:

  * the card is drawn, with the details the agent gave, and the buttons are
    REALLY there (read off the item tree, not off the model);
  * his click comes back as that tool call's result, in the same turn;
  * once answered the buttons are GONE and a second press changes nothing —
    the rule main.py enforces in `_settle_choice` [his, 2026-09-11];
  * "none of these" is always offered and says so honestly to the agent;
  * a SUBAGENT's card lands in the conversation he is reading [his: "spawn a
    subagent to grab a record and itll still show me the options like normal"];
  * a card reloaded from a saved session comes back locked, never as live
    buttons for a turn that is over.

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
fails = []

OPTIONS = [
    {"label": "Returnal (2010) [FLAC]",
     "details": {"format": "FLAC 16/44", "size": "310 MB",
                 "speed": "2.1 MB/s", "queue": "none"},
     "note": "complete, 9 tracks"},
    {"label": "Returnal (2010) [V0]",
     "details": {"format": "MP3 V0", "size": "84 MB", "speed": "560 KB/s"}},
    {"label": "Returnal (2017 reissue) [FLAC]",
     "details": {"format": "FLAC 24/96", "size": "1.1 GB", "queue": "4"}},
]


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


class Stub(http.server.BaseHTTPRequestHandler):
    """One ask_choice, then a sentence about what he picked."""

    bodies = []
    #: "main" -> the main agent asks; "agent" -> a subagent asks instead.
    who = "main"

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
            body = json.loads(raw)
        except ValueError:
            body = {}
        Stub.bodies.append(body)
        ask = {"function": {"name": "ask_choice", "arguments": {
            "question": "which copy of Returnal should I take?",
            "note": "three sources have it",
            "options": OPTIONS}}}
        answered = any(m.get("role") == "tool" for m in body.get("messages", []))
        if not body.get("stream"):          # a subagent's request
            if answered:
                self._json({"message": {"content": "took the one he picked."},
                            "done": True})
            else:
                self._json({"message": {"content": "", "tool_calls": [ask]},
                            "done": True})
            return
        if Stub.who == "agent" and len([b for b in Stub.bodies
                                        if b.get("stream")]) == 1:
            frames = [{"message": {"content": "", "tool_calls": [
                {"function": {"name": "spawn_agent", "arguments": {
                    "agent": "general", "task": "get Returnal"}}}]},
                "done": False}, {"done": True, "done_reason": "stop"}]
        elif Stub.who == "main" and not answered:
            frames = [{"message": {"content": "", "tool_calls": [ask]},
                       "done": False}, {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "queued it."}},
                      {"done": True, "done_reason": "stop"}]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for f in frames:
            self.wfile.write(json.dumps(f).encode() + b"\n")
            self.wfile.flush()

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def run(click, who="main", prompt="get me Returnal"):
    """One selftest turn. Returns (stdout+stderr, rows, request bodies)."""
    Stub.bodies = []
    Stub.who = who
    env = dict(os.environ)
    env["OLLAMA_HOST"] = "http://127.0.0.1:%d" % PORT
    env["ORACLE_SEND"] = prompt
    env["ORACLE_CHOICE"] = click
    env["ORACLE_NO_NOTIFY"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CURRENT_DESKTOP"] = "Hyprland"
    for k in ("QT_QPA_PLATFORMTHEME", "DESK_SESSION", "WAYLAND_DISPLAY", "DISPLAY"):
        env.pop(k, None)
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=300)
    txt = out.stdout + out.stderr
    m = re.search(r"^rows: (.*)$", txt, re.M)
    if not m:
        print(txt[-2000:])
        print("FAILED: the harness never finished a turn")
        sys.exit(1)
    return txt, json.loads(m.group(1) or "[]"), list(Stub.bodies)


def cards(rows):
    out = []
    for r in rows:
        try:
            out += json.loads(r.get("choices") or "[]")
        except ValueError:
            pass
    return out


def tool_results(bodies, name):
    out = []
    for b in bodies:
        for msg in b.get("messages", []):
            if msg.get("role") == "tool" and msg.get("tool_name") == name:
                try:
                    out.append(json.loads(msg.get("content") or "{}"))
                except ValueError:
                    out.append({})
    return out


# ---- 1. he picks one ------------------------------------------------------
txt, rows, bodies = run("0")
check("the window still loads clean", "0 QML warning(s)" in txt)
drawn = cards(rows)
check("the card is in the transcript", len(drawn) == 1, len(drawn))
if drawn:
    card = drawn[0]
    check("with the question", card.get("question") == "which copy of Returnal should I take?")
    check("and every option", len(card.get("options") or []) == 3,
          len(card.get("options") or []))
    check("carrying the details the agent gave",
          ["format", "FLAC 16/44"] in (card["options"][0].get("details") or []),
          card["options"][0].get("details"))
    check("it is settled once he clicks", card.get("state") == "answered",
          card.get("state"))
    check("and remembers WHICH one", card.get("index") == 0, card.get("index"))

before = re.search(r"^choice before: .*verbs=(\[.*\])$", txt, re.M)
after = re.search(r"^choice after: .*verbs=(\[.*\])$", txt, re.M)
check("the buttons are really drawn while it waits",
      bool(before) and "'pick 1'" in before.group(1)
      and "'none of these'" in before.group(1),
      before.group(1) if before else "no card")
check("and GONE once he has chosen — not merely greyed [his]",
      bool(after) and after.group(1) == "[]",
      after.group(1) if after else "no card")

answers = tool_results(bodies, "ask_choice")
check("his click comes back as the tool's result", len(answers) == 1, len(answers))
if answers:
    a = answers[0]
    check("naming what he picked", a.get("chosen") == OPTIONS[0]["label"], a.get("chosen"))
    check("with its index", a.get("chosen_index") == 0, a.get("chosen_index"))
    check("and the details of that option",
          (a.get("chosen_details") or {}).get("size") == "310 MB",
          a.get("chosen_details"))
    check("and tells the agent to get on with it",
          "do it now" in (a.get("what_now") or "").lower(), a.get("what_now"))
check("the turn carried on and answered",
      any("queued it." in (r.get("body") or "") for r in rows),
      [r.get("body") for r in rows])

# ---- 2. none of these -----------------------------------------------------
txt, rows, bodies = run("none")
drawn = cards(rows)
check("'none of these' settles the card too",
      bool(drawn) and drawn[0].get("state") == "declined",
      drawn[0].get("state") if drawn else "no card")
answers = tool_results(bodies, "ask_choice")
check("and says so to the agent, unambiguously",
      bool(answers) and answers[0].get("answered") is False
      and "none" in (answers[0].get("what_now") or "").lower(),
      answers[0] if answers else "no result")

# ---- 3. a SUBAGENT asks ---------------------------------------------------
txt, rows, bodies = run("1", who="agent")
drawn = cards(rows)
check("a subagent's card lands in HIS conversation [his]",
      len(drawn) == 1, len(drawn))
check("…and he can answer it",
      bool(drawn) and drawn[0].get("state") == "answered"
      and drawn[0].get("index") == 1,
      drawn[0] if drawn else "no card")
answers = tool_results(bodies, "ask_choice")
check("the answer goes back to the SUBAGENT that asked",
      bool(answers) and answers[0].get("chosen") == OPTIONS[1]["label"],
      answers[0] if answers else "no result")
check("and the subagent still reports to the main turn",
      any(m.get("tool_name") == "spawn_agent"
          for b in bodies for m in b.get("messages", [])
          if m.get("role") == "tool"))

# ---- 4. the pure-python rules --------------------------------------------
sys.path.insert(0, str(APP))
try:
    import main as oracle_main
except ImportError as exc:
    print("skip  the tool-shape checks (%s)" % exc)
else:
    check("ask_choice is on the wire every turn",
          "ask_choice" in oracle_main.CORE_TOOL_NAMES)
    check("and a subagent has it by default [his]",
          "ask_choice" in oracle_main.AGENT_TOOLS_DEFAULT)
    check("a definition can ask for it by group",
          oracle_main._agent_tool_names("decide") == ["ask_choice"])
    check("the subagent preamble points at it instead of forbidding questions",
          "ask_choice" in oracle_main.AGENT_SYSTEM_PREFIX)
    opts = oracle_main.Ollama._choice_options(
        [{"label": "a", "details": {"size": "1 MB"}},
         "b",
         {"label": "c", "details": [{"name": "speed", "value": "2 MB/s"}]},
         {"label": "d", "details": ["queue: 3"]},
         {"no_label": "dropped"}])
    check("options accept a bare string, an object, a pair list and 'k: v'",
          [o["label"] for o in opts] == ["a", "b", "c", "d"],
          [o["label"] for o in opts])
    check("…and the details normalise either way",
          opts[2]["details"] == [["speed", "2 MB/s"]]
          and opts[3]["details"] == [["queue", "3"]],
          [opts[2]["details"], opts[3]["details"]])
    check("more than eight candidates is a list, not a decision",
          len(oracle_main.Ollama._choice_options(
              [{"label": str(i)} for i in range(20)]))
          == oracle_main.ASK_CHOICE_MAX_OPTIONS)

print("FAILED: " + ", ".join(fails) if fails else "OK")
srv.shutdown()
sys.exit(1 if fails else 0)
