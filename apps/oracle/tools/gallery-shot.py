#!/usr/bin/env python3
"""Render chatter's image gallery and its lightbox offscreen, to PNGs to LOOK at.

Hard offscreen, and it never touches his session: it builds the two components
on their own with generated test pictures in a temp directory, so it needs no
daemon, no model and no real turn (docs/DESIGN.md — the PNG is what HE checks).

    oracle-qtenv python3 tools/gallery-shot.py [N] [--out DIR] [--width W]
"""
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

_TMP = Path(tempfile.mkdtemp(prefix="oracle-gallery-"))
os.environ["ORACLE_CONFIG"] = str(_TMP / "config")
os.environ["ORACLE_SESSIONS"] = str(_TMP / "sessions")

from PySide6.QtCore import QTimer, QUrl, Qt, QEvent                # noqa: E402
from PySide6.QtGui import (QGuiApplication, QImage, QPainter, QColor,  # noqa: E402
                           QFont, QKeyEvent)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent    # noqa: E402

import main as oracle                                             # noqa: E402

N, WIDTH = 6, 560
OUT = Path(os.environ.get("TMPDIR", "/tmp"))
argv = sys.argv[1:]
for i, a in enumerate(argv):
    if a == "--out" and i + 1 < len(argv):
        OUT = Path(argv[i + 1])
    elif a == "--width" and i + 1 < len(argv):
        WIDTH = int(argv[i + 1])
    elif a.isdigit():
        N = int(a)
OUT.mkdir(parents=True, exist_ok=True)

app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

# ---- test pictures: different aspects on purpose, so the crop is visible ----
SHAPES = [(640, 640), (900, 500), (400, 700), (1200, 1200), (300, 300),
          (800, 450), (500, 900), (1000, 700)]
HUES = [0, 40, 80, 140, 200, 260, 300, 340]
entries = []
for i in range(N):
    w, h = SHAPES[i % len(SHAPES)]
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor.fromHsv(HUES[i % len(HUES)], 150, 110))
    p = QPainter(img)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPixelSize(max(24, h // 6))
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter,
               "%d\n%dx%d" % (i + 1, w, h))
    p.setPen(QColor("black"))
    p.drawRect(0, 0, w - 1, h - 1)
    p.end()
    path = _TMP / ("pic%d.png" % i)
    img.save(str(path))
    entries.append({"ok": True, "url": "https://example.test/%d.png" % i,
                    "path": str(path),
                    "alt": "test picture %d, %dx%d" % (i + 1, w, h),
                    "w": w, "h": h})
# ...and one honest failure, which must still be drawn as a crit line.
entries.append({"ok": False, "url": "https://example.test/gone.png",
                "error": "fetch failed: host not found"})
oks = [e for e in entries if e.get("ok")]

QMLDIR = (APP / "qml").as_uri()
WRAP = _TMP / "Wrap.qml"
WRAP.write_text('''
import QtQuick
Item {
    id: root
    property var entries: []
    property var oks: []
    property alias gallery: galLoader.item
    property alias lightbox: lbLoader.item
    Rectangle { anchors.fill: parent; color: Theme.bg }
    Loader {
        id: galLoader
        x: 20; y: 20
        width: root.width - 40
        source: "%s/ImageGallery.qml"
        onLoaded: item.entries = Qt.binding(function () { return root.entries })
    }
    Loader {
        id: lbLoader
        anchors.fill: parent
        source: "%s/Lightbox.qml"
    }
}
''' % (QMLDIR, QMLDIR), encoding="utf-8")

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
palette = oracle.Palette(oracle.PANEL_THEME)
palette.setParent(app)          # or PySide GCs it and every colour reads black
from deskstyle import DeskStyle                                   # noqa: E402
style = DeskStyle()
style.setParent(app)
ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
theme_comp = QQmlComponent(
    engine, QUrl.fromLocalFile(str(APP / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)

# The window is a plain QQuickWindow around the wrapper — grabWindow() needs a
# QQuickWindow, and Main.qml's own Window would drag the whole app in.
SHELL = _TMP / "Shell.qml"
SHELL.write_text('''
import QtQuick
import QtQuick.Window
Window {
    width: %d; height: %d
    visible: true
    color: Theme.bg
    Wrap { id: wrap; objectName: "wrap"; anchors.fill: parent }
}
''' % (WIDTH + 40, 900), encoding="utf-8")

engine.addImportPath(str(_TMP))
engine.warnings.connect(lambda ws: [print("QML WARN:", w.toString()) for w in ws])
engine.load(QUrl.fromLocalFile(str(SHELL)))
roots = engine.rootObjects()
if not roots:
    raise SystemExit("the harness QML failed to load")
win = roots[0]
wrap = None
for ch in win.children():
    if ch.objectName() == "wrap":
        wrap = ch
if wrap is None:
    raise SystemExit("the wrapper item is not in the tree")
wrap.setProperty("entries", entries)
wrap.setProperty("oks", oks)


def shot(name):
    img = win.grabWindow()
    p = OUT / name
    img.save(str(p))
    print("wrote", p, "%dx%d" % (img.width(), img.height()))


def open_lightbox():
    lb = wrap.property("lightbox")
    if lb is None:
        raise SystemExit("no Lightbox loaded")
    lb.setProperty("entries", oks)
    lb.setProperty("index", 1)
    lb.setProperty("opened", True)


def keys():
    """The lightbox's keyboard, checked here rather than on his screen: the
    overlay must take focus when it opens, step on the arrows and close on
    Escape (docs/DESIGN.md §11 — and root AGENTS.md, never his session)."""
    lb = wrap.property("lightbox")
    ok = True

    def press(key):
        app.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, key,
                                     Qt.KeyboardModifier.NoModifier))
        app.sendEvent(win, QKeyEvent(QEvent.Type.KeyRelease, key,
                                     Qt.KeyboardModifier.NoModifier))

    start = lb.property("index")
    press(Qt.Key.Key_Right)
    if lb.property("index") != (start + 1) % len(oks):
        print("FAIL: right arrow did not step (%s -> %s)"
              % (start, lb.property("index")))
        ok = False
    press(Qt.Key.Key_Left)
    if lb.property("index") != start:
        print("FAIL: left arrow did not step back")
        ok = False
    press(Qt.Key.Key_Escape)
    if lb.property("opened"):
        print("FAIL: escape did not close the lightbox")
        ok = False
    else:
        lb.setProperty("opened", True)      # put it back for the second grab
    print("lightbox keyboard: " + ("ok" if ok else "FAILED"))
    globals()["KEYS_OK"] = ok


QTimer.singleShot(900, lambda: shot("chatter-gallery-%d.png" % N))
QTimer.singleShot(1000, open_lightbox)
QTimer.singleShot(1600, keys)
QTimer.singleShot(2000, lambda: shot("chatter-lightbox-%d.png" % N))
QTimer.singleShot(2200, app.quit)
app.exec()
if not globals().get("KEYS_OK", True):
    raise SystemExit("the lightbox keyboard check failed")
print("done")
