#!/usr/bin/env python3
"""The turn carries the core tools; the rest are an index, attached on demand.

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched and
no model is ever loaded.

Why any of this exists (measured 2026-08-23): 39 tool schemas are ~39.9k
characters, ~13k tokens, sent on every round of every turn. Against the 32k
window that was most of the room, and it is what put a music-library turn into
its wrap-up round with an answer that broke off mid-table.

  * `_offered_tools` carries `CORE_TOOL_NAMES` and nothing else — ~4.6k tokens
  * `tools_note` names every other tool in one line each — ~0.8k tokens
  * `get_tools` attaches by name or group and RETURNS THE SCHEMAS, so the model
    can call correctly on the very next round
  * a tool called straight off the index still runs (`_dispatch_tool` resolves
    by name) and attaches itself, so no round is spent asking for what it has
    already used correctly
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
# One tool call per round, scripted: a list of (name, arguments) the stub emits
# in order, then prose.
SCRIPT = []


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
        done = {"done": True, "done_reason": "stop",
                "prompt_eval_count": 900, "eval_count": 1}
        if SCRIPT:
            name, args = SCRIPT.pop(0)
            frames = [{"message": {"content": "", "tool_calls": [
                          {"function": {"name": name, "arguments": args}}]},
                       "done": False}, done]
        else:
            frames = [{"message": {"content": "Done."}}, done]
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
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication               # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                   # noqa: E402

app = QGuiApplication([])
o = oracle.Ollama()

done = []
o.replyDone.connect(lambda: done.append(1))

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def pump(until, ms=8000):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(app.quit)
    t.start(ms)
    poll = QTimer()
    poll.timeout.connect(lambda: until() and app.quit())
    poll.start(20)
    app.exec()
    poll.stop()
    t.stop()


def names(chat):
    return [t["function"]["name"] for t in chat.get("tools", [])]


def turn(script):
    o._prior, o._prior_users = [], []
    SCRIPT[:] = list(script)
    CHATS.clear()
    done.clear()
    o.send("stub:latest", "go", "[]")
    pump(lambda: bool(done))


# ---- the payload is the core set --------------------------------------------
reg = oracle.Ollama._main_registry()
core = [t["function"]["name"] for t in o._offered_tools()]
check("every core name resolves to a real tool",
      all(n in reg for n in oracle.CORE_TOOL_NAMES),
      str([n for n in oracle.CORE_TOOL_NAMES if n not in reg]))
check("the payload is exactly the core set", sorted(core) ==
      sorted(n for n in oracle.CORE_TOOL_NAMES if n in reg), str(core))
check("which is far smaller than the whole registry",
      len(core) * 3 < len(reg) * 2, "%d of %d" % (len(core), len(reg)))
big = len(json.dumps(oracle.Ollama._all_tools()))
small = len(json.dumps(o._offered_tools())) + len(oracle.tools_note())
check("and the wire is at least a third lighter for it",
      small < big * 0.67, "%d chars vs %d" % (small, big))

# ---- the index names everything the payload does not ------------------------
note = oracle.tools_note()
missing = [n for n in reg if n not in oracle.CORE_TOOL_NAMES
           and ("- " + n + " ") not in note and ("- " + n + "\n") not in note]
check("every non-core tool is named in the index", not missing, str(missing))
check("no core tool is listed there twice over",
      not any(("- " + n + " ") in note for n in oracle.CORE_TOOL_NAMES))
check("and it says how to get one", "get_tools" in note)
check("skill output contracts do not stop a larger tool workflow",
      "continue on to that tool" in oracle.skills_note())
check("the index is in the system prompt", note.split("\n")[0]
      in o._system_prompt(""))
check("one line each, not a schema",
      all(len(l) < 130 for l in note.split("\n") if l.startswith("- ")))

# ---- get_tools attaches, and hands back the schemas -------------------------
turn([("get_tools", {"names": "lastfm, music_library"})])
result = json.loads([m for m in CHATS[-1]["messages"]
                     if m.get("role") == "tool"][-1]["content"])
check("a get_tools round is answered as a tool result", "attached" in result,
      json.dumps(result)[:120])
check("naming exactly what it attached",
      result["attached"] == ["lastfm", "music_library"], str(result["attached"]))
check("with each one's full argument schema",
      len(result["schemas"]) == 2
      and all("parameters" in s["function"] for s in result["schemas"]))
check("and the NEXT round carries them",
      "lastfm" in names(CHATS[-1]) and "music_library" in names(CHATS[-1]),
      str(names(CHATS[-1])))
check("without dropping the core set",
      all(n in names(CHATS[-1]) for n in core), str(names(CHATS[-1])))

turn([("get_tools", {"names": ["lastfm", "music_library"]})])
result = json.loads([m for m in CHATS[-1]["messages"]
                     if m.get("role") == "tool"][-1]["content"])
check("tool names may be a JSON list",
      result["attached"] == ["lastfm", "music_library"],
      str(result["attached"]))

# ---- groups work, and a bad name is said out loud ---------------------------
turn([("get_tools", {"names": "images"})])
result = json.loads([m for m in CHATS[-1]["messages"]
                     if m.get("role") == "tool"][-1]["content"])
check("a group attaches all of it",
      set(result["attached"]) == set(oracle.EXTRA_TOOL_GROUPS["images"]),
      str(result["attached"]))
check("a job call brings its lifecycle companions",
      set(oracle.TOOL_COMPANIONS["run_job"])
      == {"run_job", "job_status", "job_log", "job_stop"})
check("a structured mutation brings its safer companions",
      set(oracle.TOOL_COMPANIONS["move_path"])
      == set(oracle.AGENT_TOOL_GROUPS["write"]))
check("tag lookup brings the image generator schema",
      oracle.TOOL_COMPANIONS["booru_tags"] == ["make_image"])

turn([("run_job", {"command": "true", "label": "test"})])
check("job companions are attached on the next round",
      all(n in names(CHATS[-1]) for n in oracle.EXTRA_TOOL_GROUPS["jobs"]),
      str(names(CHATS[-1])))

turn([("booru_tags", {"query": "hatsune miku"})])
check("a tag-check round carries make_image next",
      "make_image" in names(CHATS[-1]), str(names(CHATS[-1])))

turn([("get_tools", {"names": "nonesuch"})])
result = json.loads([m for m in CHATS[-1]["messages"]
                     if m.get("role") == "tool"][-1]["content"])
check("a name that does not exist is reported, not silently dropped",
      result.get("not_found") == ["nonesuch"] and result.get("available"),
      json.dumps(result)[:140])

# ---- calling straight off the index still works -----------------------------
turn([("describe_self", {})])
check("an unattached tool called by name RUNS",
      "unknown tool" not in json.dumps(CHATS[-1]["messages"]),
      json.dumps([m for m in CHATS[-1]["messages"]
                  if m.get("role") == "tool"][-1])[:140])
check("and attaches itself for the rest of the turn",
      "describe_self" in names(CHATS[-1]), str(names(CHATS[-1])))

# ---- a new turn starts lean again -------------------------------------------
turn([])
check("the next turn carries the core set again",
      sorted(names(CHATS[-1])) == sorted(core), str(names(CHATS[-1])))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
