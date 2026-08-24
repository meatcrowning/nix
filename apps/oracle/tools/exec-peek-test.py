#!/usr/bin/env python3
"""Two things a turn shows about ITSELF, asserted on the rendered items.

1. The collapsed "working with files" heading previews the LAST line the
   running program printed [his, 2026-08-23] — the tool is usually a download
   or a build, and the line being redrawn is the one worth seeing. Carriage
   returns count as line breaks, or a progress bar comes back as one huge line.
2. A bubble HUGS its text: a one-character message is a one-character bubble,
   not a 72px slab, and the speaker caption (which sits outside the bubble) is
   not measured into it.

Offscreen, in-process, against a stub ollama on 127.0.0.1 — his daemon is never
touched and nothing reaches his screen.
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


class Stub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"models": [{"name": "stub:latest"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]

from PySide6.QtCore import QUrl, QObject, Q_ARG, Q_RETURN_ARG, QMetaObject  # noqa: E402
from PySide6.QtGui import QGuiApplication                                   # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent              # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                                       # noqa: E402

app = QGuiApplication([])
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
ollama = oracle.Ollama()
# Held in a list, not passed inline: a QObject handed to setContextProperty and
# then dropped is garbage-collected, the context property goes null, and QML
# reads it as undefined — here that took `Theme.lineHeight` to 0 and collapsed
# every text row to nothing, which is a layout, not an error.
keep = [oracle.Palette(oracle.theme_source(oracle.PANEL_THEME)), oracle.DeskStyle(),
        oracle.Titlebar(), oracle.Backend(), oracle.Sessions(), oracle.Clip()]
ctx.setContextProperty("WalPalette", keep[0])
ctx.setContextProperty("DeskStyle", keep[1])
ctx.setContextProperty("Titlebar", keep[2])
ctx.setContextProperty("Ollama", ollama)
ctx.setContextProperty("Backend", keep[3])
ctx.setContextProperty("Sessions", keep[4])
ctx.setContextProperty("Clip", keep[5])
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


def spin(n=40):
    for _ in range(n):
        app.processEvents()


def walk(it, want, out, depth=0):
    """Every VISIBLE item the predicate `want` accepts, in the visual tree —
    a Repeater's delegates never appear in the QObject tree."""
    if it is None or depth > 20:
        return out
    for ch in (it.childItems() if hasattr(it, "childItems") else it.children()):
        if ch.property("visible") is not False and want(ch):
            out.append(ch)
        walk(ch, want, out, depth + 1)
    return out


# ---- 1. a bubble hugs its text -------------------------------------------
QMetaObject.invokeMethod(root, "loadTurns", Q_ARG("QVariant", "hug"),
                         Q_ARG("QVariant", "hug"),
                         Q_ARG("QVariant", json.dumps([
                             {"isUser": True, "who": "you", "body": "k",
                              "ts": 1787452020},
                             {"isUser": False, "who": "a-model-with-a-long-name:35b",
                              "body": "no", "ts": 1787452080}])))
spin()
spin(200)
bubbles = []
for b in walk(win, lambda c: c.property("user") is not None
              and c.property("face") is not None, []):
    if b not in bubbles:
        bubbles.append(b)
check("both bubbles are drawn", len(bubbles) == 2, str(len(bubbles)))
if len(bubbles) == 2:
    w = [b.property("width") for b in bubbles]
    check("a one-character message is a one-character bubble", max(w) < 48,
          str([round(x) for x in w]))
    check("and the speaker's name does not hold it open",
          w[1] < 48, str(round(w[1])))

# ---- the time under each bubble ------------------------------------------
# 1787452020 / 1787452080 are 60s apart, so the two rows must read different
# minutes — the local clock is whatever this machine is set to, which is why
# the assertion is on the SHAPE and the gap, not on two literal strings. The
# shape is 12h since 2026-08-23 ("2:07 pm").
import re                                                          # noqa: E402
stamps = [c.property("text") for c in
          walk(win, lambda c: isinstance(c.property("text"), str)
               and re.fullmatch(r"\d?\d:\d\d [ap]m", c.property("text") or ""), [])]
stamps = sorted(set(stamps))
check("every bubble carries the time it landed", len(stamps) == 2, repr(stamps))
check("a row with no stamp gets no label",
      all(not t.startswith("12:00 am") for t in stamps), repr(stamps))

# ---- 2. the heading previews the last line -------------------------------
QMetaObject.invokeMethod(root, "appendReplyRow", Q_ARG("QVariant", 1))
ollama.fileToolStarted.emit("run_bash")
ollama.execStarted.emit("bash")
# A download's progress: ONE line, redrawn with carriage returns.
ollama.execOutput.emit("Resolving deps\n 12% [==>      ]\r 61% [=====>   ]\r 94% [=======> ]\r")
spin()

shown = [c.property("text") for c in
         walk(win, lambda c: isinstance(c.property("text"), str)
              and "94%" in c.property("text"), [])]
# The whole tail is drawn too, inside the shut block — clipped to no height, so
# it is not on screen. The PEEK is the one-line copy of it in the heading.
peeks = [t for t in shown if "\n" not in t and "\r" not in t]
check("the collapsed heading previews the last line", bool(peeks), repr(shown))
check("and only that line, not the whole progress history",
      bool(peeks) and all("12%" not in t for t in peeks), repr(peeks))
# The peek is BOUND to the block being shut, so finding it at all is the
# assertion that a running program no longer springs the disclosure open.
check("the last line is what lastLine() picks",
      QMetaObject.invokeMethod(root, "lastLine", Q_RETURN_ARG("QVariant"),
                               Q_ARG("QVariant", "a\r\nb\rc  \r\n")) == "c")


def peek_items():
    """The one-line preview, wherever it is in the tree."""
    return [c for c in walk(win, lambda c: isinstance(c.property("text"), str)
                            and c.property("text") == "94% [=======> ]", [])]


# ---- 3. it sits UNDER the heading, not beside it --------------------------
# His, 2026-08-23: a path or a progress bar trailing "working with files…" on
# the same line leaves neither half room to read.
heads = walk(win, lambda c: c.property("text") == "working with files", [])
check("the heading says what it is working with", bool(heads),
      repr([c.property("text") for c in
            walk(win, lambda c: isinstance(c.property("text"), str)
                 and "working with" in c.property("text"), [])]))
pk = peek_items()
if heads and pk:
    hy = heads[0].mapToItem(None, 0, 0).y()
    py = pk[0].mapToItem(None, 0, 0).y()
    check("the last line is drawn under the heading, on its own line",
          py >= hy + heads[0].property("height") - 1,
          "head y=%.0f h=%.0f peek y=%.0f" % (hy, heads[0].property("height"), py))

# ---- 4. and it goes when the program does ---------------------------------
# A finished console has nothing live to preview, and its last line left under
# the heading reads as still going [his, 2026-08-23]. The whole tail stays in
# the block for anyone who opens it.
ollama.execFinished.emit()
spin()
check("the preview disappears when the console finishes", not peek_items(),
      repr([c.property("text") for c in peek_items()]))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
