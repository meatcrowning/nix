#!/usr/bin/env python3
"""`continue` works on ANY finished reply, and a tool-capped turn still answers.

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched, no
model is ever loaded, and nothing reaches his screen. It covers the two halves
of "continue a previously generated response" [his, 2026-08-23]:

  * `continueReply(..., "extend")` on a FINISHED answer — the partial goes back
    as the assistant message and EXTEND_PROMPT asks for what comes next, not a
    mid-word resume
  * an EMPTY previous turn (all tools, no words) gets ANSWER_PROMPT and no
    assistant message to carry on from
  * the wrap-up round: a model still calling tools at MAX_TOOL_ROUNDS is
    re-posted ONCE with no `tools` at all plus TOOL_CAP_PROMPT, so the turn ends
    in prose instead of the empty message it used to hand him
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

CHATS = []          # every /api/chat body, in order
MODE = {"tool_loop": False}


class Stub(http.server.BaseHTTPRequestHandler):
    """Streams one plain answer — or, in tool_loop mode, a tool call every time
    tools are offered and prose the moment they are not."""

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
        if MODE["tool_loop"] and req.get("tools"):
            frames = [{"message": {"content": "", "tool_calls": [
                          {"function": {"name": "get_current_time",
                                        "arguments": {}}}]},
                       "done": False},
                      {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "and here is the rest of it."}},
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
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication               # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                   # noqa: E402

app = QGuiApplication([])
o = oracle.Ollama()

chunks, done = [], []
o.replyChunk.connect(chunks.append)
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


# ---- extend: a FINISHED answer, carried on -------------------------------
whole = "A complete answer, ending in a full stop."
o.continueReply("stub:latest", "[]", whole, "extend")
pump(lambda: bool(done))
check("the extension streams into the same row",
      "".join(chunks) == "and here is the rest of it.", repr("".join(chunks)))
msgs = CHATS[-1]["messages"]
check("the finished answer is sent back as the assistant message",
      msgs[-2]["role"] == "assistant" and msgs[-2]["content"] == whole,
      json.dumps(msgs[-2])[:120])
check("and it is asked for what comes NEXT, not a mid-word resume",
      msgs[-1]["role"] == "user" and "comes next" in msgs[-1]["content"]
      and "cut off" not in msgs[-1]["content"], json.dumps(msgs[-1])[:160])

# ---- an EMPTY previous turn ----------------------------------------------
chunks.clear()
done.clear()
o.continueReply("stub:latest", "[]", "", "resume")
pump(lambda: bool(done))
msgs = CHATS[-1]["messages"]
check("an empty turn has no assistant message to carry on from",
      msgs[-2]["role"] != "assistant", json.dumps(msgs[-2])[:100])
check("and is simply told to answer now",
      "never wrote an answer" in msgs[-1]["content"],
      json.dumps(msgs[-1])[:140])

# ---- the wrap-up round ----------------------------------------------------
MODE["tool_loop"] = True
CHATS.clear()
chunks.clear()
done.clear()
o.send("stub:latest", "go find something", "[]")
pump(lambda: bool(done))
check("the tool loop stops at the cap",
      len(CHATS) == oracle.MAX_TOOL_ROUNDS + 2,
      "%d chats for a cap of %d" % (len(CHATS), oracle.MAX_TOOL_ROUNDS))
last = CHATS[-1]
check("the wrap-up round carries NO tools", "tools" not in last,
      str(list(last))[:100])
check("and says why", last["messages"][-1]["role"] == "user"
      and "no tools on this message" in last["messages"][-1]["content"],
      json.dumps(last["messages"][-1])[:160])
check("so the turn ends in words, not an empty message",
      "".join(chunks) == "and here is the rest of it.", repr("".join(chunks)))
check("every earlier round DID carry tools",
      all(c.get("tools") for c in CHATS[:-1]))

# ---- the loop is long enough to DO something, and stops on context ---------
# He should not have to press `continue` to get one task finished [his,
# 2026-08-23], so the round cap is a runaway guard, not a work budget — and the
# thing that really ends a long turn is the context filling up.
check("the tool loop is a working budget, not four rounds",
      oracle.MAX_TOOL_ROUNDS >= 20, str(oracle.MAX_TOOL_ROUNDS))
check("the model is told to finish the job in one turn",
      "Finish the job in THIS turn" in oracle.PERSISTENCE_NOTE
      and str(oracle.MAX_TOOL_ROUNDS) in oracle.PERSISTENCE_NOTE)

o._messages = [{"role": "user", "content": "x"}]
check("an empty conversation has room for another round", o._ctx_room())
o._messages = [{"role": "user", "content": "x" * (oracle.CHAT_NUM_CTX * 4)}]
check("a conversation that has filled the window does not", not o._ctx_room())

# A full context wraps the turn up EARLY — no waiting for round 24.
MODE["tool_loop"] = True
CHATS.clear()
chunks.clear()
done.clear()
o.send("stub:latest", "go find something", "[]")
# One real round, then stuff the context: the next `_on_finished` must wrap up.
pump(lambda: len(CHATS) >= 2)
o._messages.append({"role": "user", "content": "x" * (oracle.CHAT_NUM_CTX * 4)})
pump(lambda: bool(done))
check("a full context wraps the turn up early",
      len(CHATS) < oracle.MAX_TOOL_ROUNDS, "%d chats" % len(CHATS))
check("and it still ends in words",
      "".join(chunks) == "and here is the rest of it.", repr("".join(chunks)))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
