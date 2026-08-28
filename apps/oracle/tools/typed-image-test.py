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

# 5. a picture the turn ALREADY fetched, named again in the write-up, is drawn
#    on the bubble that names it — no second download, and never twice on one
#    bubble. A turn that gathers pictures over several rounds and then writes
#    them up used to end with a list naming eleven of them and a bubble holding
#    none [his, 2026-08-22]: they were up-thread on the round bubbles that
#    fetched them, and the write-up's own markdown is demoted to links.
settle = QTimer()
settle.setSingleShot(True)
settle.timeout.connect(app.quit)
settle.start(1500)
app.exec()                       # let case 4's fetch land before we look
entries.clear()
o._acc_content = "here they all are\n\n![again](%s/a.png)" % BASE
o._row_urls = set()              # the write-up is its own bubble
check("naming a picture already fetched starts no second download",
      o._attach_typed_images() is False)
check("...and it is drawn on the bubble that names it",
      len(entries) == 1 and entries[0].get("ok") is True
      and entries[0].get("alt") == "again", json.dumps(entries)[:160])
entries.clear()
o._attach_typed_images()         # same bubble, same picture
check("...but never twice on the same bubble", entries == [],
      json.dumps(entries)[:160])
o._set_busy(False)

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

# ---- a typed LOCAL PATH is a picture too, and the path itself is not text --
# What he reported 2026-08-27: "unable to properly attach images to chat
# bubbles ... they often put a filepath to it when they should not". A model
# that has just made, screenshotted or found a picture writes
# `![it](/home/lam/.../x.png)`, and until this both halves failed at once —
# nothing matched a non-http target, so the picture never appeared AND
# MarkdownText demoted the markdown to a link showing his file path.
import tempfile as _tf                                      # noqa: E402

_dir = Path(_tf.mkdtemp(prefix="oracle-localimg-"))
LOCAL = _dir / "shot.png"
img.save(str(LOCAL))
NOTIMG = _dir / "notes.txt"
NOTIMG.write_text("not a picture")

entries.clear()
o._images_shown, o._paths_shown, o._row_urls = set(), set(), set()
o._acc_content = "here it is\n\n![the shot](%s)\n\nsaved to %s" % (LOCAL, LOCAL)
started = o._attach_typed_images()
check("a typed local path needs no fetch", started is False)
check("...and the picture is drawn anyway",
      len(entries) == 1 and entries[0].get("ok") is True
      and entries[0].get("path") == str(LOCAL) and entries[0].get("w") == 4,
      json.dumps(entries)[:200])

runs = json.loads(o.replyRuns(o._acc_content, json.dumps(entries)))
kinds = [r["t"] for r in runs["runs"]]
check("the picture lands where the model put it", kinds == ["text", "img"], str(kinds))
check("...and nothing is left over for the gallery", runs["leftovers"] == [])
check("the file path is not printed as text",
      all(str(LOCAL) not in r.get("md", "") for r in runs["runs"]),
      json.dumps(runs["runs"])[:200])
check("the prose around it survives",
      runs["runs"][0]["md"].strip() == "here it is", repr(runs["runs"][0]["md"]))

# a picture SHOWN from disk (show_image: no url at all) that the reply then
# points at inline must land at that spot too, not in the trailing gallery.
shown = [{"ok": True, "url": "", "path": str(LOCAL), "alt": "cover",
          "w": 4, "h": 4}]
runs = json.loads(o.replyRuns("look: ![cover](%s)" % LOCAL, json.dumps(shown)))
check("a show_image picture can be placed inline by its path",
      [r["t"] for r in runs["runs"]] == ["text", "img"]
      and runs["leftovers"] == [], json.dumps(runs)[:200])

# a path inside code is part of the command, and stays
runs = json.loads(o.replyRuns(
    "![x](%s)\n\nrun `ls %s` to see it" % (LOCAL, LOCAL), json.dumps(shown)))
check("a path inside code is left alone",
      any(str(LOCAL) in r.get("md", "") for r in runs["runs"]),
      json.dumps(runs["runs"])[:200])

# a picture shown WITHOUT being pointed at inline still lands in the gallery,
# and its path is still not prose the bubble has to carry.
gal = [{"ok": True, "url": "", "path": str(LOCAL), "alt": "c", "w": 4, "h": 4}]
runs = json.loads(o.replyRuns(
    "made you one. it is at %s" % LOCAL, json.dumps(gal)))
check("a gallery picture's path is not printed either",
      all(str(LOCAL) not in r.get("md", "") for r in runs["runs"])
      and runs["leftovers"] == gal, json.dumps(runs)[:200])
check("...and only the dangling half-sentence goes with it",
      "made you one." in "".join(r.get("md", "") for r in runs["runs"]),
      json.dumps(runs["runs"])[:200])

# the app's own markers, quoted back at him, are plumbing and not an answer
runs = json.loads(o.replyRuns(
    "[image in this chat: /x/y.png \u00b7 512x512]\n\nhere you go", "[]"))
check("a quoted app marker is not shown as text",
      "".join(r.get("md", "") for r in runs["runs"]).strip() == "here you go",
      json.dumps(runs["runs"])[:200])

# and a local target that is NOT an image is named, not silently dropped
entries.clear()
o._images_shown, o._paths_shown, o._row_urls = set(), set(), set()
o._acc_content = "![nope](%s)" % NOTIMG
o._attach_typed_images()
check("a local target that is not an image is named honestly",
      len(entries) == 1 and entries[0].get("ok") is False
      and "not an image" in entries[0].get("error", ""),
      json.dumps(entries)[:200])

srv.shutdown()
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
