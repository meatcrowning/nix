#!/usr/bin/env python3
"""A reply's pictures render INLINE with its text, alpha intact.

[his, 2026-08-23] — "remove the 'all images must be at top of message'
requirement, allow them to be put in line i.e. in with the text, AND support
transparancy". This drives the real window offscreen: a reply whose prose
carries `![alt](url)` at a known spot must lay the picture out AT that spot
(between the text runs), keep a transparent PNG's alpha (a transparent frame
fill, not a solid slab), and still show a fetched-but-unreferenced picture in
the trailing gallery so nothing is hidden.

    oracle-qtenv python3 tools/inline-image-test.py
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

_TMP = Path(tempfile.mkdtemp(prefix="oracle-inline-"))

from PySide6.QtCore import (QMetaObject, QObject, Q_ARG, QTimer, QUrl)  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QColor                 # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent            # noqa: E402

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
         "Md": oracle.MdFormat(), "Jobs": oracle.Jobs()}
for key, obj in parts.items():
    obj.setParent(app)
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

# An opaque picture and a TRANSPARENT one (PNG with a real alpha channel).
OPAQUE = _TMP / "opaque.png"
pic = QImage(600, 300, QImage.Format.Format_RGB32)
pic.fill(QColor("#2f4858"))
pic.save(str(OPAQUE))

# A REAL landscape and a REAL portrait, at the shapes a render comes out at —
# the height cap is measured against the file's own pixels, so a stub with a
# different aspect than the entry claims would measure nothing.
WIDE = _TMP / "wide.png"
QImage(1856, 1088, QImage.Format.Format_RGB32).save(str(WIDE))
TALL = _TMP / "tall.png"
QImage(1088, 1856, QImage.Format.Format_RGB32).save(str(TALL))

TRANSP = _TMP / "transp.png"
tp = QImage(400, 400, QImage.Format.Format_ARGB32)
tp.fill(QColor(0, 0, 0, 0))                # fully transparent
for y in range(100, 300):                  # a 200px opaque slab in the middle
    for x in range(100, 300):
        tp.setPixelColor(x, y, QColor(30, 200, 120, 255))
tp.save(str(TRANSP))


def settle(ms=1200):
    for _ in range(3):
        app.processEvents()
    QTimer.singleShot(ms, app.quit)
    app.exec()
    win.grabWindow()
    for _ in range(3):
        app.processEvents()


def find(kind):
    """Every item whose class name contains `kind`, walking the whole tree."""
    found = []

    def walk(it):
        for ch in it.childItems():
            if kind.lower() in ch.metaObject().className().lower():
                found.append(ch)
            walk(ch)

    walk(content)
    return found


def reply_row(step):
    QMetaObject.invokeMethod(content, "appendReplyRow", Q_ARG("QVariant", step))
    for _ in range(3):
        app.processEvents()


def emit_body(text):
    parts["Ollama"].replyChunk.emit(text)
    for _ in range(3):
        app.processEvents()


def emit_image(entry):
    parts["Ollama"].imageFetchStarted.emit(entry.get("url", ""))
    parts["Ollama"].imageFetchResult.emit(json.dumps(entry))
    for _ in range(3):
        app.processEvents()


# ---- 1. an inline image lands BETWEEN its text runs -----------------------
# The model wrote `![a cat](u)` in the middle of its reply and fetched u; the
# picture must render at that spot, not hoisted to the top.
reply_row(1)
emit_body("before it: ![a cat](https://x/cat.png) and after it.")
emit_image({"ok": True, "url": "https://x/cat.png", "path": str(OPAQUE),
            "alt": "a cat", "w": 600, "h": 300})
settle()

imgs = [i for i in find("InlineImage") if i.property("visible")]
mds = [m for m in find("MarkdownText") if m.property("visible")]
check("an inline image is drawn at its place", len(imgs) == 1 and imgs[0].property("height") > 100,
      "inline=%d height=%s" % (len(imgs), (imgs[0].property("height") if imgs else "?")))
check("the text is split into runs around it (>=2 text runs)",
      len(mds) >= 2, "runs=%d" % len(mds))

# ---- 2. transparency survives ---------------------------------------------
# A transparent PNG must render with its alpha — the frame's fill is
# TRANSPARENT, so the bubble shows through the clear pixels rather than a
# solid slab.
reply_row(2)
emit_body("a sticker: ![logo](https://x/logo.png) end")
emit_image({"ok": True, "url": "https://x/logo.png", "path": str(TRANSP),
            "alt": "logo", "w": 400, "h": 400})
settle()
timg = [i for i in find("InlineImage") if i.property("visible")]
transparent_rects = []


def collect_transparent(it):
    for ch in it.childItems():
        col = ch.property("color")
        # The frame's fill is `color: "transparent"` — a QColor of alpha 0 —
        # so a transparent PNG's clear pixels show the bubble behind them.
        if col is not None and getattr(col, "isValid", lambda: False)() \
                and getattr(col, "alpha", lambda: 255)() == 0:
            transparent_rects.append(ch)
        collect_transparent(ch)


if timg:
    collect_transparent(timg[0])
check("a transparent PNG keeps its alpha (transparent frame fill)",
      len(transparent_rects) > 0, "inline=%d" % len(timg))

# ---- 3. a fetched picture the reply never referenced is still shown -------
# The gallery is the net: a picture that is not tied to a word must not vanish.
reply_row(3)
emit_body("no picture here")
emit_image({"ok": True, "url": "https://x/unref.png", "path": str(OPAQUE),
            "alt": "unreferenced", "w": 600, "h": 300})
settle()
gals = [g for g in find("ImageGallery") if g.property("visible")]
check("an unreferenced fetched picture still renders in the gallery",
      len(gals) == 1 and gals[0].property("height") > 100,
      "gal=%d height=%s" % (len(gals), (gals[0].property("height") if gals else "?")))

# ---- 3b. a PORTRAIT picture is capped by its HEIGHT ----------------------
# Sized by the column alone, a 2:3 render is nearly three times the height of a
# 16:9 one in the same chat and pushes the reply off the screen [his,
# 2026-08-24]. Both shapes go through the same gallery here, and the tall one
# must not tower over the wide one.
reply_row(5)
emit_image({"ok": True, "url": "https://x/wide.png", "path": str(WIDE),
            "w": 1856, "h": 1088})
settle()
gals = [g for g in find("ImageGallery") if g.property("visible")]
wide = gals[-1].property("height") if gals else 0
reply_row(6)
emit_image({"ok": True, "url": "https://x/tall.png", "path": str(TALL),
            "w": 1088, "h": 1856})
settle()
gals = [g for g in find("ImageGallery") if g.property("visible")]
tall = gals[-1].property("height") if gals else 0
check("a portrait picture is capped, not drawn at column width",
      0 < tall <= 360, "tall=%s wide=%s" % (tall, wide))
check("...and is not much taller than a landscape one",
      0 < wide and tall <= wide * 1.4, "tall=%s wide=%s" % (tall, wide))
check("...while a landscape one still fills the column",
      wide > 200, "wide=%s" % wide)

# ---- 4. a failed fetch names itself where the picture was meant to be -----
reply_row(4)
emit_body("here it is: ![oops](https://x/fail.png) done")
emit_image({"ok": False, "url": "https://x/fail.png", "error": "timeout"})
settle()
crit = [c for c in find("PixelText") if c.property("visible")
        and "image:" in str(c.property("text") or "")]
check("a failed fetch is named inline (not silently dropped)",
      len(crit) >= 1, "crit=%d" % len(crit))

# ---- 4b. a long caption is ONE elided line ON the picture, not a paragraph --
# An Anima prompt is forty tags; wrapped under the picture it was a slab taller
# than some replies [his, 2026-08-24]. The whole of it lives in the Lightbox.
LONG_ALT = ", ".join(["a very long danbooru style tag"] * 12)
reply_row(7)
emit_image({"ok": True, "url": "", "path": str(TALL), "alt": LONG_ALT,
            "meta": "anima-base-v1.0 · 1088x1856 · 50 steps · seed 12345",
            "w": 1088, "h": 1856})
settle()
gals = [g for g in find("ImageGallery") if g.property("visible")]
h = gals[-1].property("height") if gals else 0
check("a forty-tag caption does not make the picture a paragraph taller",
      0 < h <= 400, "height=%s" % h)
strips = [c for c in find("CaptionStrip") if c.property("visible")]
check("...it is a strip under the picture", len(strips) >= 1, "n=%d" % len(strips))
if strips:
    check("...one line for the caption and one for what made it",
          strips[-1].property("height") <= 40,
          "strip=%s" % strips[-1].property("height"))
# CENTRED: a portrait picture is narrower than the column it sits in, and the
# dead space belongs on BOTH sides of it.
pics = [i for i in find("Image") if i.property("visible")
        and i.property("width") > 40]
last = pics[-1] if pics else None
if last is not None and gals:
    left = last.mapToItem(gals[-1], 0, 0).x()
    right = gals[-1].property("width") - (left + last.property("width"))
    check("a portrait picture is centred in the bubble",
          left > 2 and abs(left - right) <= 3,
          "left=%.0f right=%.0f w=%.0f" % (left, right, last.property("width")))
else:
    check("a portrait picture is centred in the bubble", False, "no image found")

# ---- 5. the lightbox walks the WHOLE conversation, and takes the log with it
# Three rows have carried a picture by now. Opening the last one must offer all
# of them, and stepping must scroll the reply to the row the picture is on.
box = [b for b in find("Lightbox")]
check("the window has a lightbox", len(box) == 1, "n=%d" % len(box))
if box:
    QMetaObject.invokeMethod(content, "openPicture",
                             Q_ARG("QVariant", {"path": str(TALL), "url": ""}))
    settle()
    n = box[0].property("count")
    check("it offers every picture in the conversation, not just the row's",
          n >= 3, "count=%s" % n)
    at = box[0].property("index")
    check("...opened on the one that was clicked",
          at == n - 1, "index=%s of %s" % (at, n))
    flick = win.findChild(QObject, "replyFlick")
    QMetaObject.invokeMethod(box[0], "step", Q_ARG("QVariant", -1))
    settle()
    check("stepping back moves the lightbox",
          box[0].property("index") == at - 1, str(box[0].property("index")))
    check("...and the chat scrolled to that picture's row",
          box[0].property("currentRow") >= 0
          and flick.property("contentY") >= 0,
          "row=%s y=%s" % (box[0].property("currentRow"),
                           flick.property("contentY")))
    QMetaObject.invokeMethod(box[0], "close")
    settle()

check("no QML warnings", not warns, "; ".join(warns)[:300])
print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
