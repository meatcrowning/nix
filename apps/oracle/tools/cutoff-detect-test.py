#!/usr/bin/env python3
"""A reply that ends mid-sentence is marked cut off, even when ollama says "stop".

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched, no
model is ever loaded, and nothing reaches his screen.

The bug this covers, observed 2026-08-23: a music-library turn spent its 32k
window on tool rounds (ollama's own log: `n_tokens = 32767, truncated = 1`),
fell into the wrap-up round, and wrote a table that breaks off mid-row. ollama
reported an ordinary `done_reason` of "stop" — it shifts the context rather than
failing — so `replyTruncated` never fired, the row was never `cutOff`, and the
half-answer was handed to him with no `continue` on it.

Two halves, and BOTH are needed:

  * shape alone is not enough — one finished reply in nine ends on a bare word
    (a bullet list, a heading, a trailing link), so `_ends_abruptly` may never
    mark a row on its own
  * a SQUEEZED turn (a round that filled the window, or a wrap-up round forced
    by the tool cap) plus that shape is a truncation, and says so
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
# What the stub does: `text` is the prose it streams, `used` the token
# accounting it reports on the done frame, `reason` its done_reason.
MODE = {"text": "and here is the rest of it.", "used": 900, "reason": "stop",
        "tool_loop": False}


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
        done = {"done": True, "done_reason": MODE["reason"],
                "prompt_eval_count": MODE["used"], "eval_count": 1}
        if MODE["tool_loop"] and req.get("tools"):
            frames = [{"message": {"content": "", "tool_calls": [
                          {"function": {"name": "get_current_time",
                                        "arguments": {}}}]},
                       "done": False}, done]
        else:
            frames = [{"message": {"content": MODE["text"]}}, done]
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

done, cut = [], []
o.replyDone.connect(lambda: done.append(1))
o.replyTruncated.connect(cut.append)

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


def turn(text, used=900, reason="stop", tool_loop=False):
    """One whole turn against the stub. Returns the truncation reason, if any."""
    o._prior, o._prior_users = [], []
    MODE.update(text=text, used=used, reason=reason, tool_loop=tool_loop)
    CHATS.clear()
    done.clear()
    cut.clear()
    o.send("stub:latest", "go", "[]")
    pump(lambda: bool(done))
    return cut[0] if cut else ""


# ---- the shape test, on its own -------------------------------------------
ABRUPT = [
    "1. **Kanye West** — absolutely massive",     # the real one, 2026-08-23
    "| Artist | Plays |\n|---|---|\n| Blawan | 218 |\n| Andy Stott",
    "The library is heavy on ambient, and the biggest hole in it is",
    "Here is the script:\n\n```python\nprint('x')",   # fence never closed
]
WHOLE = [
    "Done — 19,479 tracks across 1,515 artists.",
    "Which of the two do you want me to use?",
    "The song playing now is **Causers of This**. 🎵",  # an emoji ending
    "See [the channel](https://www.youtube.com/@toroymoi)",
    "| Artist | Plays |\n|---|---|\n| Blawan | 218 |",
]
for t in ABRUPT:
    check("mid-sentence: %r" % t[-30:], oracle.Ollama._ends_abruptly(t))
for t in WHOLE:
    check("finished: %r" % t[-30:], not oracle.Ollama._ends_abruptly(t))
check("and nothing at all is not a truncation",
      not oracle.Ollama._ends_abruptly(""))

# The ambiguous shape, and why the gate exists: a finished bullet list ending on
# a bare word is indistinguishable from a cut one. Shape flags it; only
# `_squeezed` decides whether that means anything.
AMBIGUOUS = "- **Capabilities:** vision, tools, thinking"
check("a finished bullet ending on a bare word LOOKS cut",
      oracle.Ollama._ends_abruptly(AMBIGUOUS))

# ---- shape ALONE never marks a row ---------------------------------------
# The measured false-positive rate on his own saved sessions is ~11%, so an
# unsqueezed turn that happens to end on a word is left alone.
check("a roomy turn ending mid-sentence is NOT marked",
      turn("1. **Kanye West** — absolutely massive", used=900) == "",
      repr(cut))
check("…nor is the ambiguous bullet list", turn(AMBIGUOUS, used=900) == "")

# ---- ollama's own flag still wins ----------------------------------------
check("done_reason length is a truncation, whatever the shape",
      turn("A complete sentence.", used=900, reason="length") == "length")

# ---- the window filled: shape now counts ---------------------------------
FULL = int(oracle.CHAT_NUM_CTX * 0.99)
check("a round that filled the window + a mid-sentence end = context",
      turn("1. **Kanye West** — absolutely massive", used=FULL) == "context")
check("…but a squeezed turn that FINISHED its sentence is left alone",
      turn("Done — 19,479 tracks across 1,515 artists.", used=FULL) == "")

# ---- the forced wrap-up round counts as squeezed too ----------------------
# Still calling tools when the loop is capped: the answer it then writes is
# written under duress, exactly like the real 2026-08-23 turn.
o._ctx_room_real = o._ctx_room
o._ctx_room = lambda: False
r = turn("1. **Kanye West** — absolutely massive", used=900, tool_loop=True)
o._ctx_room = o._ctx_room_real
check("a wrap-up round that ends mid-sentence is a truncation", r == "context",
      repr(r))

# ---- and the flag does not leak into the next turn ------------------------
check("the next turn starts unsqueezed",
      turn("1. **Kanye West** — absolutely massive", used=900) == "")

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
