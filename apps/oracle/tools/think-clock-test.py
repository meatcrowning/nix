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
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_config = tempfile.TemporaryDirectory(prefix="chatter-thinking-")
os.environ["ORACLE_CONFIG"] = _config.name

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

HOLD = {"tool": True, "thinking": True}  # control the stub's first tool round


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
            time.sleep(1.2)
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
            frames = ([{"message": {"thinking": REASONING}}]
                      if HOLD["thinking"] else []) + [
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
REASONING = "\n".join("line %d: let me look that up" % n for n in range(32))
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
            # A collapsed disclosure leaves its children with local
            # `visible: true`, but they are not actually drawn.  Inspect the
            # effective QQuickItem visibility so an old, hidden row cannot be
            # mistaken for a second live state.
            if (hasattr(ch, "isVisible") and not ch.isVisible()) \
                    or ch.property("visible") is False:
                continue
            if isinstance(t, str) and (t.startswith("waiting")
                                       or t.startswith("thinking")
                                       or t.startswith("thought")
                                       or t.startswith("loading")
                                       or t.endswith(" tokens") or t.endswith(" token")):
                out.append(t)
            walk(ch, d + 1)

    walk(win)
    return out


def items_named(name, root_item=win):
    """QQuickItem's visual tree is not always its QObject child tree."""
    found = []
    def walk(it, d=0):
        if d > 18 or it is None:
            return
        if it.property("objectName") == name:
            found.append(it)
        for ch in (it.childItems() if hasattr(it, "childItems") else it.children()):
            walk(ch, d + 1)
    walk(root_item)
    return found


def captions():
    """The effective speaker captions, in transcript order."""
    return [item.property("text") for item in items_named("speakerCaption")
            if item.isVisible()]


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
check("assistant bubbles use Nyx by default", "Nyx" in captions(), repr(captions()))
QMetaObject.invokeMethod(root, "tbAction", Q_ARG("QVariant", "show-model-name"))
spin(50)
check("Settings can reveal the selected model name",
      "stub:latest" in captions(), repr(captions()))
QMetaObject.invokeMethod(root, "tbAction", Q_ARG("QVariant", "show-model-name"))
spin(50)
check("Settings can return captions to Nyx", "Nyx" in captions(), repr(captions()))
# THE ARGUMENT IS NOT OPTIONAL FROM HERE. `continueReply(forced)` grew that
# parameter with the resume/extend split (2026-08-23), and `invokeMethod` with
# no args does not match a QML function that declares one — it returns False and
# does NOTHING, which read as "the clock never showed a state" and failed all
# four checks. Empty string is the falsy `forced`, i.e. decide the mode from the
# row, exactly what the button does.
if not QMetaObject.invokeMethod(root, "continueReply", Q_ARG("QVariant", "")):
    print("FAILED: continueReply did not accept the call")
    sys.exit(1)
# Open the real disclosure while its tool call is outstanding. Its text is
# deliberately longer than the ten-line viewport, so this also proves that the
# reasoning is a bounded scrolling log and opens at its live end.
spin(350)
thinking = next((it for it in items_named("thinkingDisclosure")
                 if bool(it.property("visible"))), None)
thinking_scroll = (items_named("thinkingScroll", thinking)[0]
                   if thinking is not None else None)
check("the live reasoning disclosure exists", thinking is not None)
turn = thinking
while turn is not None and turn.property("userSet") is None:
    turn = turn.parentItem()
if turn is not None:
    turn.setProperty("userSet", True)
    turn.setProperty("userOpen", True)
spin(100)
check("an open reasoning disclosure stays open while `waiting…`",
      thinking is not None and bool(thinking.property("expanded"))
      and any(x.startswith("waiting") for x in headings()),
      "expanded=%r headings=%r" %
      (None if thinking is None else thinking.property("expanded"), headings()))
check("expanded reasoning is a bounded auto-following scroll box",
      thinking_scroll is not None
      and thinking_scroll.property("contentHeight") > thinking_scroll.property("height")
      and thinking_scroll.property("contentY") >=
          thinking_scroll.property("contentHeight") - thinking_scroll.property("height") - 2,
      "scroll=%r" % ((None if thinking_scroll is None else
                        (thinking_scroll.property("contentY"),
                         thinking_scroll.property("contentHeight"),
                         thinking_scroll.property("height"))),))
spin(2050)
check("a tool round in flight reads `waiting…`",
      any(x.startswith("waiting") for x in SEEN), repr(SEEN))

spin(100)

h = headings()
check("once it settles it reads `thought for …`",
      any(x.startswith("thought for") for x in h), repr(h))
# The count moved out of the clock heading and onto the speaker caption beside
# the name [his, 2026-09-05] — still one PixelText in the tree, without the "·"
# that used to rule it off from the state text.
check("the token count is drawn, beside the speaker's name",
      any(x.endswith(" token") or x.endswith(" tokens") for x in h), repr(h))
check("no state text is left running",
      not any(x.startswith("waiting") or x.startswith("thinking") for x in h),
      repr(h))

# ---- ONE STATE AT A TIME -------------------------------------------------
# An empty bubble out on its first tool satisfied both the `loading` line and
# the clock's `waiting…`, and drew them stacked on top of each other [his,
# 2026-08-22]. `loading` owns a bubble with nothing in it; the clock takes over
# once there is something to show.
HOLD["tool"] = True
HOLD["thinking"] = False
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

# ---- A FRESH ROUND DOES NOT FOLD THE PREVIOUS REASONING -------------------
# The next tool round begins as `loading…`: it has no text of its own yet, but
# the turn above it already has reasoning. That state used to hide the entire
# disclosure, despite it being explicitly open.
QMetaObject.invokeMethod(root, "loadTurns", Q_ARG("QVariant", "loadingtest"),
                         Q_ARG("QVariant", "loading test"), Q_ARG("QVariant", json.dumps([
                             {"isUser": True, "who": "you", "body": "go on"},
                             {"isUser": False, "who": "stub:latest",
                              "thinking": "the first round's reasoning", "thinkMs": 1000}])) )
QMetaObject.invokeMethod(root, "appendReplyRow", Q_ARG("QVariant", 2))
spin(100)
thinking = next((it for it in items_named("thinkingDisclosure")
                 if bool(it.property("visible"))), None)
turn = thinking
while turn is not None and turn.property("userSet") is None:
    turn = turn.parentItem()
if turn is not None:
    turn.setProperty("userSet", True)
    turn.setProperty("userOpen", True)
spin(100)
check("an open reasoning disclosure remains visible through `loading…`",
      thinking is not None and bool(thinking.property("visible"))
      and bool(thinking.property("expanded"))
      and any(x.startswith("loading") for x in headings()),
      "visible=%r expanded=%r headings=%r" %
      (None if thinking is None else thinking.property("visible"),
       None if thinking is None else thinking.property("expanded"), headings()))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
