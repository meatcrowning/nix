#!/usr/bin/env python3
"""A model that TYPES `![alt](url)` still gets the picture attached.

Offscreen and local-only: the image comes off a throwaway HTTP server on
127.0.0.1, so the test reaches neither his screen nor the network. It covers
the three outcomes of `_attach_typed_images`: a real image lands as an `ok`
entry, a mistyped booru md5 is refused BEFORE any request, and a reply with no
image markdown starts nothing.
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

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage       # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray          # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]                  # temp config/sessions
import main as oracle                                   # noqa: E402

app = QGuiApplication([])

# ---- a 4x4 PNG on a local port -------------------------------------------
img = QImage(4, 4, QImage.Format.Format_RGB32)
img.fill(0x336699)
_ba = QByteArray()
buf = QBuffer(_ba)
buf.open(QBuffer.OpenModeFlag.WriteOnly)
img.save(buf, "PNG")
buf.close()
PNG = bytes(_ba)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith(".png"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]

o = oracle.Ollama()
entries = []
o.imageFetchResult.connect(lambda j: entries.append(json.loads(j)))
done = {"n": 0}
o.replyDone.connect(lambda: done.__setitem__("n", done["n"] + 1))

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def run(body):
    entries.clear()
    done["n"] = 0
    o._images_shown = set()
    o._md_images = {"n": 0}
    o._acc_content = body
    o._set_busy(True)
    started = o._attach_typed_images()
    if not started:
        o._set_busy(False)
    return started


# 1. nothing typed -> nothing started
check("a reply with no image markdown starts no fetch",
      run("just text, and a [link](http://example.com) that is not an image")
      is False)

# 2. a real image -> one ok entry, and replyDone waits for it
run("here you go\n\n![a swatch](%s/a.png)" % BASE)
loop = QTimer()
loop.setSingleShot(True)
loop.timeout.connect(app.quit)
loop.start(5000)
o.replyDone.connect(app.quit)
app.exec()
check("a typed image is downloaded and shown",
      len(entries) == 1 and entries[0].get("ok") is True,
      json.dumps(entries)[:160])
check("replyDone waits for the typed image", done["n"] == 1)

# 3. a mistyped booru md5 is refused with no request at all
run("![kairi](https://cdn.donmai.us/original/12/a9/12a90ec8d770cc4898c17bece1ee561.jpg)")
check("a 31-char booru md5 is refused before the request",
      len(entries) == 1 and entries[0].get("ok") is False
      and "32 hex" in entries[0].get("error", ""),
      json.dumps(entries)[:160])

# 4. the same URL twice in one reply is fetched once
run("![one](%s/a.png)\n![one again](%s/a.png)" % (BASE, BASE))
check("a repeated URL is fetched once", o._md_images["n"] == 1)

# ---- copying a reply keeps its markdown ----------------------------------
# The clipboard here is the OFFSCREEN platform's own, process-local — his
# session's clipboard is never touched (root AGENTS.md).
from PySide6.QtGui import QTextDocument                  # noqa: E402

SRC = ("first line of the prompt\n\nintegrated_multimodal_description: "
       "[Shot 1] <Picture 1> is referenced.\n\n- one\n- two\n")
doc = QTextDocument()
doc.setMarkdown(SRC)


class _QD:
    def __init__(self, d):
        self._d = d

    def textDocument(self):
        return self._d


clip = oracle.Clip()
check("a flattened copy is what we are fixing",
      "\n\n" not in doc.toPlainText())
clip.copyMarkdown(_QD(doc), 0, doc.characterCount() - 1, SRC)
got = QGuiApplication.clipboard().text()
check("a whole-message copy is the source verbatim", got == SRC, repr(got)[:120])
clip.copyMarkdown(_QD(doc), 0, 60, SRC)
part = QGuiApplication.clipboard().text()
check("a partial copy keeps the blank line and unescapes",
      "\n\n" in part and "\\<" not in part and "\\[" not in part, repr(part)[:160])

# ---- and the QML side reaches it ----------------------------------------
# The real path is a TextEdit handing its QQuickTextDocument to the slot; a
# `QObject` mismatch there would only ever show up on a live Ctrl+C.
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402
from PySide6.QtCore import QUrl                          # noqa: E402
import tempfile                                          # noqa: E402

eng = QQmlApplicationEngine()
eng.rootContext().setContextProperty("Clip", clip)
qml = Path(tempfile.mkdtemp()) / "T.qml"
qml.write_text("""
import QtQuick
Item {
    property alias ed: ed
    property string src: "a\\n\\nb\\n"
    TextEdit { id: ed; textFormat: TextEdit.MarkdownText; text: parent.src }
    function copyAll() {
        ed.selectAll();
        return Clip.copyMarkdown(ed.textDocument, ed.selectionStart,
                                 ed.selectionEnd, src);
    }
}
""")
comp = QQmlComponent(eng, QUrl.fromLocalFile(str(qml)))
item = comp.create()
check("MarkdownText.qml's copy path is wired", item is not None,
      comp.errorString())
if item is not None:
    QGuiApplication.clipboard().setText("")
    ok = item.copyAll()
    check("Ctrl+C from QML returns the markdown source",
          bool(ok) and QGuiApplication.clipboard().text() == "a\n\nb\n",
          repr(QGuiApplication.clipboard().text()))

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
