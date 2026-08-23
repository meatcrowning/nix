#!/usr/bin/env python3
"""How a reply's LINES and PARAGRAPHS come out, and where sending leaves the view.

Three things, all measured off the laid-out document rather than the source:

1. A single newline is a LINE BREAK inside the paragraph — Qt's markdown reader
   joins it into the line above, so a reply written as short lines came back as
   one run-on block [his, 2026-08-23]. `Root.hardBreaks` turns it into U+2028.
2. A BLANK line still opens a new paragraph, and that paragraph stands off the
   one above it (`MdFormat.PARA_TOP`) — the gap that says "new paragraph" where
   Qt's own 6px read no stronger than a wrapped line. Bullets stay tight.
3. Sending scrolls him to the BOTTOM, wherever he was reading.

Offscreen, in-process, against a stub ollama on 127.0.0.1 — his daemon is never
touched and nothing reaches his screen.
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
ctx.setContextProperty("WalPalette",
                       oracle.Palette(oracle.theme_source(oracle.PANEL_THEME)))
ctx.setContextProperty("DeskStyle", oracle.DeskStyle())
ctx.setContextProperty("Titlebar", oracle.Titlebar())
ctx.setContextProperty("Ollama", ollama)
ctx.setContextProperty("Backend", oracle.Backend())
ctx.setContextProperty("Sessions", oracle.Sessions())
ctx.setContextProperty("Clip", oracle.Clip())
mdfmt = oracle.MdFormat()          # a temporary here is collected mid-run
ctx.setContextProperty("Md", mdfmt)
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


def spin(ms=600):
    """Real time, not just events: the document pass is debounced 60ms."""
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def walk(it, want, out, depth=0):
    if it is None or depth > 20:
        return out
    for ch in (it.childItems() if hasattr(it, "childItems") else it.children()):
        if ch.property("visible") is not False and want(ch):
            out.append(ch)
        walk(ch, want, out, depth + 1)
    return out


# ONE transcript for all three checks: `loadTurns` persists the outgoing
# session first, and the store is not wired in this harness — so it is called
# once, with the prose reply at the top and enough filler under it to make the
# log longer than the window.
BODY = ("alpha one paragraph.\n\n"
        "bravo two paragraph.\ncharlie the same paragraph, softly broken.\n\n"
        "- bullet one\n- bullet two\n\n"
        "delta last.")
turns = [{"isUser": True, "who": "you", "body": "x"},
         {"isUser": False, "who": "stub:latest", "body": BODY}]
for i in range(12):
    turns.append({"isUser": True, "who": "you", "body": "prompt %d" % i})
    turns.append({"isUser": False, "who": "stub:latest",
                  "body": ("reply %d.\n\n" % i) * 4})
QMetaObject.invokeMethod(root, "loadTurns", Q_ARG("QVariant", "prose"),
                         Q_ARG("QVariant", "prose"),
                         Q_ARG("QVariant", json.dumps(turns)))
spin(900)

# ---- 1 + 2. lines, paragraphs and the gaps between them -------------------
md = walk(win, lambda c: c.objectName() == "mdBody", [])
check("the reply is drawn", bool(md))
if md:
    body = md[0]
    # Keep the QQuickTextDocument alive: reading .textDocument() off a temporary
    # lets shiboken collect the wrapper and the QTextDocument with it.
    qdoc = body.property("textDocument")
    doc = qdoc.textDocument()
    blocks = []
    b = doc.begin()
    while b.isValid():
        blocks.append({"text": b.text(), "top": b.blockFormat().topMargin(),
                       "lines": b.layout().lineCount(),
                       "list": b.textList() is not None})
        b = b.next()
    check("a blank line opens a paragraph, a single newline does not",
          len(blocks) == 5, json.dumps([x["text"][:20] for x in blocks]))
    if len(blocks) == 5:
        check("the softly-broken line stays in its paragraph, on its own line",
              blocks[1]["lines"] == 2 and "\u2028" in blocks[1]["text"],
              repr(blocks[1]["text"]))
        check("a paragraph stands off the one above it",
              blocks[1]["top"] >= 8 and blocks[4]["top"] >= 8,
              str([x["top"] for x in blocks]))
        check("the first one does not, or the bubble opens with a gap",
              blocks[0]["top"] == 0, str(blocks[0]["top"]))
        check("bullets are one list, not a stack of paragraphs",
              blocks[2]["list"] and blocks[3]["top"] < 8,
              str([x["top"] for x in blocks]))
    # The COPY path is the model's own markdown — U+2028 is the render's doing
    # (MarkdownText.qml hands `source` to Clip.copyMarkdown).
    check("what gets copied is the model's text, verbatim",
          body.property("source") == BODY, repr(body.property("source"))[:80])

# ---- 3. sending scrolls him to the bottom ---------------------------------
# Scrolled back up through the log, a prompt goes: his own message must not
# land off-screen below him [his, 2026-08-23].
flick = walk(win, lambda c: c.objectName() == "replyFlick", [])
check("the log is longer than the window",
      bool(flick) and flick[0].property("contentHeight")
      > flick[0].property("height"),
      "%s of %s" % (flick[0].property("contentHeight") if flick else "-",
                    flick[0].property("height") if flick else "-"))
if flick:
    view = flick[0]
    view.setProperty("contentY", 0)
    spin(200)
    check("and he is reading at the top", view.property("contentY") == 0)
    root.setProperty("model", "stub:latest")
    box = walk(win, lambda c: c.objectName() == "promptBox", [])
    if box:
        box[0].setProperty("text", "and one more thing")
    QMetaObject.invokeMethod(root, "send")
    spin(600)
    bottom = max(0.0, view.property("contentHeight") - view.property("height"))
    check("sending puts him at the bottom",
          abs(view.property("contentY") - bottom) < 4,
          "%.0f of %.0f" % (view.property("contentY"), bottom))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
