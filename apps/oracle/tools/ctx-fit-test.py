#!/usr/bin/env python3
"""The context stat is the window he ACTUALLY has, and the window is sized to fit.

Offscreen against a STUB ollama on 127.0.0.1 — his daemon is never touched and
no model is ever loaded. `CtxFit`'s journal read is exercised against a fake
`journalctl` on PATH, so nothing here needs (or reads) the real one.

What it pins, all from 2026-08-23 [his]: *"can you make the context indicator
represent the REAL amount of context i have based on my system specs for the
given model?"*

  * the stat is the window in force — ollama's `/api/ps` `context_length` once
    the model is loaded — never the model's trained ceiling, which is drawn dim
    beside it
  * a model whose KV cost has never been measured gets `CHAT_NUM_CTX`, exactly
    as every model did before this existed: nothing can shrink his window
  * a measured model gets a window sized from free VRAM + RAM, capped by
    `CHAT_NUM_CTX_CAP` and by what the model was trained for
  * the measurement itself comes from ollama's own load line, and only when its
    cell count matches the window `/api/ps` reports
"""
import http.server
import json
import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

TMP = tempfile.mkdtemp(prefix="ctxfit-test-")
os.environ["ORACLE_CTXFIT"] = os.path.join(TMP, "ctxfit.json")

# A fake `journalctl` and `nvidia-smi`, ahead of anything real on PATH. The
# journal text is the shape ollama actually prints (measured on top, qwen3.6:
# 640 MiB over 32768 cells = 20 KiB a token).
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
KV_LOG = ("load_tensors: offloaded 41/42 layers to GPU\n"
          "llama_context: n_ctx                 = 32768\n"
          "llama_kv_cache: size =  640.00 MiB ( 32768 cells,  10 layers,"
          "  1/1 seqs), K (f16):  320.00 MiB, V (f16):  320.00 MiB\n")
for name, body in (("journalctl", "#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % KV_LOG),
                   ("nvidia-smi", "#!/bin/sh\necho 8192\n")):   # 8 GiB free
    p = os.path.join(BIN, name)
    with open(p, "w") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")

MODEL = "stub:latest"
PS = {"models": []}


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
            self._json({"models": [{"name": MODEL, "size": 4 * 1024 ** 3}]})
        elif self.path.startswith("/api/ps"):
            self._json(PS)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        if self.path.startswith("/api/show"):
            self._json({"model_info": {"general.architecture": "stubarch",
                                       "stubarch.context_length": 262144},
                        "capabilities": ["completion", "tools"]})
        else:
            self._json({})

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

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def pump(until, ms=6000):
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


# ---- an unmeasured model is exactly as it always was ----------------------
o.refreshModels()
pump(lambda: bool(o.models))
o.refreshModelInfo(MODEL)
pump(lambda: o.contextTrained > 0)
check("the model's trained ceiling is read", o.contextTrained == 262144,
      str(o.contextTrained))
check("but the stat shows the window IN FORCE, not that ceiling",
      o.contextMax == oracle.CHAT_NUM_CTX, str(o.contextMax))
check("and that is what the turn asks ollama for",
      o._num_ctx == oracle.CHAT_NUM_CTX, str(o._num_ctx))

# ---- /api/ps is the ground truth once something is loaded ----------------
o.notePs(json.dumps({"models": [{"name": MODEL, "context_length": 8192}]}))
check("a loaded model's REAL window wins, even a small one",
      o.contextMax == 8192, str(o.contextMax))
check("and the next turn asks for THAT, rather than reloading the weights",
      o._num_ctx == 8192, str(o._num_ctx))
pump(lambda: o._ctx_fit.known(MODEL), 4000)
check("…and the load is what teaches CtxFit the KV cost",
      o._ctx_fit.known(MODEL) is False,
      "8192 cells != the 32768 in the log, so nothing was learned")

# ---- the measurement: cell count must match --------------------------------
o._ctx_fit._asked.clear()
o.notePs(json.dumps({"models": [{"name": MODEL, "context_length": 32768}]}))
pump(lambda: o._ctx_fit.known(MODEL), 4000)
check("a matching load line IS read", o._ctx_fit.known(MODEL))
check("and gives 20 KiB a token",
      abs(o._ctx_fit._kv[MODEL] - 20480) < 1, str(o._ctx_fit._kv.get(MODEL)))
check("which is written down for next launch",
      json.load(open(os.environ["ORACLE_CTXFIT"])).get(MODEL, 0) > 0)

# ---- a measured model is sized to the machine ------------------------------
# 8 GiB of VRAM free (the fake nvidia-smi) minus headroom, plus whatever RAM is
# over the floor, half of it, over 20 KiB a token — comfortably past the cap
# here, which is the point of the cap.
o.notePs(json.dumps({"models": []}))
o.refreshModelInfo(MODEL)
check("an unloaded measured model gets more than the old flat window",
      o._num_ctx > oracle.CHAT_NUM_CTX, str(o._num_ctx))
check("never more than the cap", o._num_ctx <= oracle.CHAT_NUM_CTX_CAP,
      str(o._num_ctx))
check("and never more than the model was trained for",
      o._num_ctx <= o.contextTrained, str(o._num_ctx))
check("the stat now shows that window", o.contextMax == o._num_ctx,
      "%d vs %d" % (o.contextMax, o._num_ctx))

# ---- the trained ceiling is never a floor ---------------------------------
o._ctx_train = 16384
o._set_window(MODEL)
check("a small-context model is not stretched to the flat default",
      o._num_ctx == 16384, str(o._num_ctx))

# ---- no memory to speak of: the floor holds -------------------------------
o._ctx_train = 262144
o._ctx_fit._vram_free = staticmethod(lambda: 0)
o._ctx_fit._mem_available = staticmethod(lambda: 0)
o._set_window(MODEL)
check("with nothing free it falls back to the flat window, not to zero",
      o._num_ctx == oracle.CHAT_NUM_CTX, str(o._num_ctx))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
