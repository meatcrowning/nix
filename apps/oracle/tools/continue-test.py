#!/usr/bin/env python3
"""A cut-off reply offers `continue`, and continuing lands in the SAME row.

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched, no
model is ever loaded, and nothing reaches his screen. It covers:

  * `done_reason: "length"` raising `replyTruncated`
  * `continueReply` re-posting with the partial as an assistant message plus
    CONTINUE_PROMPT, and streaming onto the end of it
  * the `loading…` state: busy, with no content and no reasoning yet
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

REQUESTS = []      # every POST body
CHATS = []         # just the /api/chat ones, in order


class Stub(http.server.BaseHTTPRequestHandler):
    """/api/chat streams two frames and stops for `length`; /api/tags is empty."""

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
        REQUESTS.append(req)
        if not self.path.startswith("/api/chat"):
            self._json({})
            return
        CHATS.append(req)
        first = len(CHATS) == 1
        frames = ([{"message": {"content": "the answer stops mid-sen"}},
                   {"done": True, "done_reason": "length"}] if first
                  else [{"message": {"content": "tence and then finishes."}},
                        {"done": True, "done_reason": "stop"}])
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

chunks, truncated, done = [], [], []
o.replyChunk.connect(chunks.append)
o.replyTruncated.connect(truncated.append)
o.replyDone.connect(lambda: done.append(1))

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def pump(until, ms=6000):
    end = {"stop": False}
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(lambda: (end.__setitem__("stop", True), app.quit()))
    t.start(ms)
    poll = QTimer()
    poll.timeout.connect(lambda: until() and app.quit())
    poll.start(20)
    app.exec()
    poll.stop()
    t.stop()


o.send("stub:latest", "say something", "[]")
# The wait state: busy, with nothing said yet — what draws `loading…`.
check("busy with no content yet is the loading state",
      o.busy and not chunks)
pump(lambda: bool(done))
check("the reply streamed", "".join(chunks) == "the answer stops mid-sen",
      repr("".join(chunks)))
check("a length-capped reply reports truncated", truncated == ["length"],
      repr(truncated))

partial = "".join(chunks)
chunks.clear()
done.clear()
o.continueReply("stub:latest", "[]", partial)
pump(lambda: bool(done))
check("the continuation streams", "".join(chunks) == "tence and then finishes.",
      repr("".join(chunks)))
check("a stop-reason reply is not marked truncated", truncated == ["length"])

msgs = CHATS[1]["messages"]
check("the partial is sent back as the assistant message",
      msgs[-2]["role"] == "assistant" and msgs[-2]["content"] == partial,
      json.dumps(msgs[-2])[:120])
check("and the continue instruction follows it as a user turn",
      msgs[-1]["role"] == "user"
      and "cut off" in msgs[-1]["content"],
      json.dumps(msgs[-1])[:120])

# ---- view_image: a LOCAL picture, handed to the model ---------------------
# Through the real jailed executor (tools/sandbox-fs.py), against a PNG in a
# temp directory — the same path a model would take from find_files.
import tempfile                                          # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray           # noqa: E402
from PySide6.QtGui import QImage                         # noqa: E402

img = QImage(8, 6, QImage.Format.Format_RGB32)
img.fill(0x884422)
pic_path = str(Path(tempfile.mkdtemp()) / "local.png")
img.save(pic_path)

entries = []
o.imageFetchResult.connect(lambda j: entries.append(json.loads(j)))
CHATS.clear()

# A vision model, as far as the capability probe is concerned.
o._model = "stub:latest"
o._ctx_model = "stub:latest"
o._caps = ["vision"]
o._pending_vision = []
# A tool ROUND is an object now (`Ollama._new_round`): its `sink` is where the
# result lands, so a subagent's round cannot overwrite the turn's own.
vround = {"n": 1, "sink": [None]}
o._set_busy(True)
o._view_image({"path": pic_path}, 0, vround, [None])
pump(lambda: bool(CHATS))

res = json.loads(vround["sink"][0]["content"])
check("view_image reads the local file", res.get("ok") is True, json.dumps(res)[:140])
check("the bytes are NOT in the tool result", "b64" not in res)
check("the picture is shown to him too",
      any(e.get("ok") and e.get("path") == pic_path for e in entries),
      json.dumps(entries)[:160])
vis = [m for m in CHATS[-1]["messages"] if m.get("images")]
check("and handed to the model as a vision message", len(vis) == 1
      and vis[0]["role"] == "user", json.dumps(vis)[:80])
if vis:
    import base64                                        # noqa: E402
    check("the attached bytes are the file's",
          base64.b64decode(vis[0]["images"][0]) == open(pic_path, "rb").read())

# A model with no vision is told so, and no bytes are read.
o._caps = []
o._pending_vision = []
nround = {"n": 1, "sink": [None]}
o._set_busy(True)
o._view_image({"path": pic_path}, 0, nround, [None])
pump(lambda: nround["sink"][0] is not None, 2000)
res = json.loads(nround["sink"][0]["content"])
check("a model with no vision is refused honestly",
      "vision" in res.get("error", ""), json.dumps(res)[:120])
check("and nothing was attached", not o._pending_vision)

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
