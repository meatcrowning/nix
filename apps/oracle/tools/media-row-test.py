#!/usr/bin/env python3
"""A picture or a video that ARRIVES on a wordless row is drawn.

The regression this exists for [his, 2026-08-23]: the model built a graph,
`view_image` looked at it, the picture landed on a round bubble with no text in
it — and nothing was drawn. Reloading the session showed it, which is what made
it look like a fluke: the bubble asked a CHILD inside itself whether it should
be visible (`imageCol.visible`), QML's `visible` is EFFECTIVE visibility, and a
hidden bubble therefore read its own child as hidden and latched off. A picture
already on the row when the row is born escapes it; one that arrives does not.

So this test drives the LIVE order — an empty reply row, then the tool's signal
— through the real Root.qml, offscreen, with a picture it generates itself.

    oracle-qtenv python3 tools/media-row-test.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-mediarow-"))

from PySide6.QtCore import (QMetaObject, QObject, Q_ARG, QTimer,  # noqa: E402
                            QUrl)
from PySide6.QtGui import QGuiApplication, QImage                 # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent    # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                             # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# ---- the real window, offscreen -------------------------------------------
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
parts = {"WalPalette": oracle.Palette(oracle.theme_source(oracle.PANEL_THEME)),
         "DeskStyle": oracle.DeskStyle(), "Titlebar": oracle.Titlebar(),
         "Ollama": oracle.Ollama(), "Backend": oracle.Backend(),
         "Sessions": oracle.Sessions(), "Clip": oracle.Clip(),
         "Md": oracle.MdFormat()}
for key, obj in parts.items():
    obj.setParent(app)                 # or PySide GCs it out from under QML
    ctx.setContextProperty(key, obj)
ctx.setContextProperty("ollamaHost", oracle.OLLAMA)
theme_comp = QQmlComponent(
    engine, QUrl.fromLocalFile(str(APP / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)
warns = []
engine.warnings.connect(lambda es: warns.extend(e.toString() for e in es))
engine.load(QUrl.fromLocalFile(str(APP / "qml" / "Main.qml")))
roots = engine.rootObjects()
if not roots:
    raise SystemExit("Main.qml failed to load")
win = roots[0]
content = win.findChild(QObject, "content")

pic = QImage(600, 300, QImage.Format.Format_RGB32)
pic.fill(0x2f4858)
PIC = _TMP / "graph.png"
pic.save(str(PIC))


def settle(ms=1200):
    for _ in range(3):
        app.processEvents()
    QTimer.singleShot(ms, app.quit)
    app.exec()
    win.grabWindow()                   # forces the polish a Column lays out on
    for _ in range(3):
        app.processEvents()


def visible_of(kind):
    """(effective visible, height) of the one item of `kind` in the tree."""
    found = []

    def walk(it):
        for ch in it.childItems():
            if kind.lower() in ch.metaObject().className().lower():
                found.append(ch)
            walk(ch)

    walk(content)
    live = [f for f in found if f.property("visible")]
    if live:
        return True, live[0].property("height")
    return False, (found[0].property("height") if found else 0)


# 1. a picture arriving on a row with NO text — the live order, the regression
QMetaObject.invokeMethod(content, "appendReplyRow", Q_ARG("QVariant", 1))
for _ in range(3):
    app.processEvents()
parts["Ollama"].imageFetchStarted.emit("")
parts["Ollama"].imageFetchResult.emit(json.dumps(
    {"ok": True, "url": "", "path": str(PIC), "alt": "a graph",
     "w": 600, "h": 300}))
settle()
vis, h = visible_of("ImageGallery")
check("a picture arriving on a wordless row is drawn", vis and h > 100,
      "visible=%s height=%s" % (vis, h))

# 2. the same for a video card, which shares the bubble's visibility rule
QMetaObject.invokeMethod(content, "appendReplyRow", Q_ARG("QVariant", 2))
for _ in range(3):
    app.processEvents()
parts["Ollama"].videoStarted.emit("https://x.test/w")
parts["Ollama"].videoResult.emit(json.dumps(
    {"ok": True, "url": "https://x.test/w", "src": "https://x.test/s.mp4",
     "title": "A Title", "alt": "", "w": 640, "h": 360, "duration": 90,
     "live": False}))
settle()
vis, h = visible_of("VideoDeck")
check("a video arriving on a wordless row is drawn", vis and h > 100,
      "visible=%s height=%s" % (vis, h))

check("no QML warnings", not warns, "; ".join(warns)[:300])
print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
