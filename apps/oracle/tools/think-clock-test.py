#!/usr/bin/env python3
"""The thinking clock counts tool waits, and says `waiting…` while it does.

End-to-end and offscreen: the real `Root.qml` under a STUB ollama on 127.0.0.1,
driven through the two functions the window itself uses (`loadTurns`,
`continueReply`). His daemon is never touched, no model is loaded, nothing
reaches his screen. What is asserted is the HEADING TEXT the delegate renders —
the thing he actually reads — not an internal flag.
"""
import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

HOLD = {"tool": True}          # keep the "tool round" outstanding until cleared


class Stub(http.server.BaseHTTPRequestHandler):
    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/slow"):
            # The tool the stub asks for: a page that takes its time, so the
            # WAITING window is long enough to observe.
            time.sleep(0.6)
            body = b"the answer is 42"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/tags"):
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
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if HOLD["tool"]:
            HOLD["tool"] = False        # only the FIRST round calls the tool
            # Reason for a moment, then call a tool and stop the stream: the
            # turn is now WAITING, exactly as it is against the real daemon.
            frames = [{"message": {"thinking": "let me look that up"}},
                      {"message": {"tool_calls": [
                          {"function": {"name": "fetch_url",
                                        "arguments": {"url": SLOW_URL[0]}}}]}},
                      {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "done."}},
                      {"done": True, "done_reason": "stop"}]
        for f in frames:
            self.wfile.write(json.dumps(f).encode() + b"\n")
            self.wfile.flush()

    def log_message(self, *a):
        pass


SLOW_URL = [""]
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]
SLOW_URL[0] = "http://127.0.0.1:%d/slow" % srv.server_address[1]

from PySide6.QtCore import QTimer, QUrl, QObject, Q_ARG, QMetaObject   # noqa: E402
from PySide6.QtGui import QGuiApplication                              # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent         # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                                  # noqa: E402

app = QGuiApplication([])
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
palette = oracle.Palette(oracle.theme_source(oracle.PANEL_THEME))
style = oracle.DeskStyle()
ollama, backend, sessions, clip = (oracle.Ollama(), oracle.Backend(),
                                   oracle.Sessions(), oracle.Clip())
ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
ctx.setContextProperty("Titlebar", oracle.Titlebar())
ctx.setContextProperty("Ollama", ollama)
ctx.setContextProperty("Backend", backend)
ctx.setContextProperty("Sessions", sessions)
ctx.setContextProperty("Clip", clip)
ctx.setContextProperty("ollamaHost", oracle.OLLAMA)
theme_c = QQmlComponent(engine, QUrl.fromLocalFile(str(oracle.QML / "theme" / "Theme.qml")))
theme = theme_c.create()
assert theme is not None, theme_c.errorString()
theme.setParent(app)
ctx.setContextProperty("Theme", theme)
engine.load(QUrl.fromLocalFile(str(oracle.QML / "Main.qml")))
win = engine.rootObjects()[0]
root = win.findChild(QObject, "content")

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


SEEN = []


def spin(ms):
    """Run the event loop, recording every heading the window shows meanwhile —
    a transient state (`waiting…`) is only catchable by sampling."""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        for h in headings():
            if h not in SEEN:
                SEEN.append(h)
        time.sleep(0.01)


def headings():
    """Every PixelText in the tree whose text names a clock state."""
    out = []

    def walk(it, d=0):
        if d > 18 or it is None:
            return
        for ch in (it.childItems() if hasattr(it, "childItems") else it.children()):
            t = ch.property("text")
            if ch.property("visible") is False:
                continue
            if isinstance(t, str) and (t.startswith("waiting")
                                       or t.startswith("thinking")
                                       or t.startswith("thought")
                                       or t.startswith("loading")
                                       or t.endswith("tokens ·") or t.endswith("token ·")):
                out.append(t)
            walk(ch, d + 1)

    walk(win)
    return out


# A one-row transcript whose last turn is a cut-off model answer — the state
# `continueReply` acts on, and the only public way in without a prompt box.
QMetaObject.invokeMethod(root, "loadTurns", Q_ARG("QVariant", "clocktest"),
                         Q_ARG("QVariant", "clock test"),
                         Q_ARG("QVariant", json.dumps([
                             {"isUser": True, "who": "you", "body": "what time is it"},
                             {"isUser": False, "who": "stub:latest",
                              "body": "let me check", "cutOff": True}])))
spin(300)
root.setProperty("model", "stub:latest")
# THE ARGUMENT IS NOT OPTIONAL FROM HERE. `continueReply(forced)` grew that
# parameter with the resume/extend split (2026-08-23), and `invokeMethod` with
# no args does not match a QML function that declares one — it returns False and
# does NOTHING, which read as "the clock never showed a state" and failed all
# four checks. Empty string is the falsy `forced`, i.e. decide the mode from the
# row, exactly what the button does.
if not QMetaObject.invokeMethod(root, "continueReply", Q_ARG("QVariant", "")):
    print("FAILED: continueReply did not accept the call")
    sys.exit(1)
spin(2500)
check("a tool round in flight reads `waiting…`",
      any(x.startswith("waiting") for x in SEEN), repr(SEEN))

spin(100)

h = headings()
check("once it settles it reads `thought for …`",
      any(x.startswith("thought for") for x in h), repr(h))
check("the token count is beside it, on the left",
      any(x.endswith("token ·") or x.endswith("tokens ·") for x in h), repr(h))
check("no state text is left running",
      not any(x.startswith("waiting") or x.startswith("thinking") for x in h),
      repr(h))

# ---- ONE STATE AT A TIME -------------------------------------------------
# An empty bubble out on its first tool satisfied both the `loading` line and
# the clock's `waiting…`, and drew them stacked on top of each other [his,
# 2026-08-22]. `loading` owns a bubble with nothing in it; the clock takes over
# once there is something to show.
HOLD["tool"] = True
QMetaObject.invokeMethod(root, "loadTurns", Q_ARG("QVariant", "clocktest2"),
                         Q_ARG("QVariant", "clock test 2"),
                         Q_ARG("QVariant", json.dumps([
                             {"isUser": True, "who": "you", "body": "go look"},
                             {"isUser": False, "who": "stub:latest", "body": "",
                              "cutOff": True}])))
spin(300)
SEEN.clear()
both = []


def sample_pairs(ms):
    """Sample the two states TOGETHER — the bug is them coexisting, which a
    union of everything seen over time cannot tell apart from a handover."""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        h = headings()
        if any(x.startswith("loading") for x in h) and \
           any(x.startswith("waiting") for x in h):
            both.append(list(h))
        time.sleep(0.01)


if not QMetaObject.invokeMethod(root, "continueReply", Q_ARG("QVariant", "")):
    print("FAILED: continueReply did not accept the call")
    sys.exit(1)
sample_pairs(2500)
check("an empty bubble never shows `loading` and `waiting` at once",
      not both, repr(both[:2]))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
