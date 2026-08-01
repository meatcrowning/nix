#!/usr/bin/env python3
"""reader's PDF viewport gestures, offscreen: ctrl+scroll zoom and middle-drag pan.

Posts REAL `QWheelEvent`s and `QMouseEvent`s at `qml/PdfView.qml` and asserts
what the two gestures have to be true of:

  - ctrl+wheel zooms CONTINUOUSLY, about the pointer, clamped, dropping out of
    the fit mode — and a plain wheel still scrolls the document and does not
    zoom, because the handler leaves it unaccepted for the view's WheelScroll
  - `sourceSize` — the raster cache's key (`pdfdoc.py`) — SETTLES rather than
    being written per notch, and `smooth` is on exactly while it lags. The last
    block measures what that is worth: the same ten notches with `sourceSize`
    written per notch, which is what an unguarded zoom does.
  - middle-drag moves the content 1:1 with the pointer in both axes, clamps at
    the page edge, and stops at the release

Two rules this file is shaped by, both paid for once already:

  - **Never open a window on his screen**: offscreen is forced, hard, and
    asserted, exactly as `pdf-profile.py` does it.
  - **Drive it from QML, and never from Python's own loop.** Assigning `doc`
    from the main thread deadlocks the GUI thread against Qt's
    `QQuickPixmapReader` (the GIL), so the document is opened by a QML Timer
    and every step below runs as a `QTimer.singleShot` inside the event loop.

    reader/tools/pdf-zoom-test.py            # writes its own 30-page PDF
    reader/tools/pdf-zoom-test.py some.pdf   # or drive a real one

Env recipe is `../AGENTS.md`'s: source the wrapper's environment, run the
interpreter it names.
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # and nothing to fall back TO
os.environ.pop("DISPLAY", None)

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(os.path.dirname(APP), "pylib"))

from PySide6.QtCore import QPoint, QPointF, QTimer, QUrl, QObject, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent, QMouseEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)

import pdfdoc

PROBE_QML = """
import QtQuick
import QtQuick.Window
import "file:%s/qml"

Window {
    id: win
    width: 1000; height: 900; visible: true
    property var pv: v
    // The KineticListView inside the view. `children[0]` is the same handle
    // tools/pdf-profile.py takes, and asserting it here is what would catch a
    // new item being declared ahead of the view.
    property var lv: v.children[0]
    PdfView { id: v; anchors.fill: parent; docKey: "left" }
    Timer {
        interval: 400; running: true
        onTriggered: { v.doc = Probe.openDoc(); Probe.begin(); }
    }
}
""".replace("%s", APP)

FAILS = []


def check(name, cond, detail=""):
    print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAILS.append(name)


def make_pdf(path, pages=30):
    """Enough pages to scroll, written by Qt — no fixture file in the repo."""
    from PySide6.QtGui import QPdfWriter, QPainter, QFont, QPageSize
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setTitle("Zoom Harness")
    p = QPainter(w)
    f = QFont("Helvetica")
    f.setPointSize(24)
    p.setFont(f)
    for i in range(pages):
        if i:
            w.newPage()
        p.drawText(400, 800, "page %d" % (i + 1))
    p.end()


class _Probe(pdfdoc.PageProvider):
    """The real provider, recording every (page, pixel size) actually asked
    for — a subclass, because Qt calls the C++ virtual."""

    def __init__(self, lib):
        super().__init__(lib)
        self.iids = []

    def requestImage(self, iid, size, requested):
        img = super().requestImage(iid, size, requested)
        self.iids.append("%s@%dx%d" % (iid, requested.width(), requested.height()))
        return img


class _Driver(QObject):
    def __init__(self, lib, path, prov, app):
        super().__init__()
        self._lib, self._path, self.prov, self.app = lib, path, prov, app
        self.win = None
        self.steps = []

    @Slot(result="QVariantMap")
    def openDoc(self):
        info = self._lib.open("left", self._path)
        if not info["ok"]:
            raise SystemExit(info["error"])
        return info

    @Slot()
    def begin(self):
        self.v = self.win.property("pv")
        self.lv = self.win.property("lv")
        if self.lv is None or self.lv.property("contentY") is None:
            raise SystemExit("children[0] of PdfView is not the list view")
        self.steps = list(script(self))
        self._next()

    def _next(self):
        if not self.steps:
            self.finish()
            return
        delay, fn = self.steps.pop(0)
        QTimer.singleShot(delay, lambda: (fn(), self._next()))

    def finish(self):
        self._lib.close("left")
        print("\nall checks passed" if not FAILS else "\nFAILURES: %s" % FAILS)
        self.app.exit(1 if FAILS else 0)

    # ---- input, at the window ----
    def wheel(self, x, y, angle, ctrl):
        ev = QWheelEvent(QPointF(x, y), self.win.mapToGlobal(QPointF(x, y)),
                         QPoint(0, 0), QPoint(0, angle), Qt.NoButton,
                         Qt.ControlModifier if ctrl else Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QGuiApplication.sendEvent(self.win, ev)

    def _mouse(self, kind, x, y):
        rel = kind == QMouseEvent.Type.MouseButtonRelease
        ev = QMouseEvent(kind, QPointF(x, y), self.win.mapToGlobal(QPointF(x, y)),
                         Qt.MiddleButton,
                         Qt.NoButton if rel else Qt.MiddleButton, Qt.NoModifier)
        QGuiApplication.sendEvent(self.win, ev)

    def press(self, x, y):
        self._mouse(QMouseEvent.Type.MouseButtonPress, x, y)

    def move(self, x, y):
        self._mouse(QMouseEvent.Type.MouseMove, x, y)

    def release(self, x, y):
        self._mouse(QMouseEvent.Type.MouseButtonRelease, x, y)

    def p(self, n):
        return self.v.property(n)

    def c(self, n):
        return self.lv.property(n)


def script(d):
    """(delay_ms, step) pairs, run in order inside the event loop."""
    st = {}
    scales = []

    # ---- 1. a plain wheel is not a zoom -------------------------------------
    def start():
        print("  %d pages, fit-width %.4f, content %.0fpx"
              % (d.p("pageCount"), d.p("pageScale"), d.c("contentHeight")))
        st["y0"] = d.c("contentY")
        st["z0"] = d.p("pageScale")
        for _ in range(5):
            d.wheel(500, 400, -120, False)
    yield 1200, start

    def plain():
        check("a plain wheel still scrolls the document", d.c("contentY") > st["y0"],
              "contentY %.0f -> %.0f" % (st["y0"], d.c("contentY")))
        check("...and does not touch the zoom",
              abs(d.p("pageScale") - st["z0"]) < 1e-9, "%.4f" % d.p("pageScale"))
        # from a known free zoom, so ten notches cannot reach the clamp
        d.v.setProperty("fit", "none")
        d.v.setProperty("zoom", 0.5)
    yield 200, plain

    # ---- 2. ctrl+wheel: continuous, pointer-anchored ------------------------
    def notch():
        d.wheel(500, 400, 120, True)
        scales.append(d.p("pageScale"))

    def zoom_start():
        st["n0"] = len(d.prov.iids)
        st["top"] = d.p("topIndex")
        st["size0"] = tuple(sorted(set(i.split("@")[1] for i in d.prov.iids)))
        notch()
    yield 500, zoom_start
    for _ in range(9):
        yield 12, notch

    def during():
        check("ctrl+wheel zooms in", scales[-1] > 4.0,
              "0.5 -> %.4f over 10 notches (x1.25 each)" % scales[-1])
        check("...continuously - every notch moved it, none of them stepped",
              len(set("%.5f" % s for s in scales)) == 10,
              str(["%.2f" % s for s in scales]))
        check("...dropping out of the fit mode", d.p("fit") == "none", d.p("fit"))
        check("...and staying on the page under the pointer",
              abs(d.p("topIndex") - st["top"]) <= 1,
              "page %d -> %d" % (st["top"], d.p("topIndex")))
        check("the rasterized scale LAGS the displayed one mid-gesture",
              abs(d.p("rasterScale") - d.p("pageScale")) > 0.05,
              "raster %.4f vs shown %.4f" % (d.p("rasterScale"), d.p("pageScale")))
        check("...so `scaling` is true and the pixmap is filtered, not blocky",
              d.p("scaling") is True)
        st["mid"] = len(d.prov.iids)
    yield 5, during

    def settled():
        check("the raster settles to the displayed scale when the gesture stops",
              abs(d.p("rasterScale") - d.p("pageScale")) < 1e-9,
              "raster %.4f" % d.p("rasterScale"))
        check("...and `scaling` is false again at rest", d.p("scaling") is False)
        g = d.p("pageScale") * 400
        check("...on the 0.25% grid, so the same zoom reached twice is one raster",
              abs(g - round(g)) < 1e-6, "%.5f" % d.p("pageScale"))
        # A call DURING the gesture is only a bug if it asks for a new size: a
        # page still arriving from before it started is a straggler, not a
        # zoom's cost, and it turns up perhaps one run in three.
        got = d.prov.iids[st["n0"]:]
        during = [i for i in d.prov.iids[st["n0"]:st["mid"]]
                  if i.split("@")[1] not in st["size0"]]
        pages = set(i.split("@")[0] for i in got)
        check("ONE raster per visible page for the whole gesture",
              len(set(got)) == len(pages) and not during,
              "%d calls / %d pages, %d at a NEW size mid-gesture"
              % (len(got), len(pages), len(during)))
        st["debounced"] = len(got)
    yield 600, settled

    # ---- 3. clamped both ways ----------------------------------------------
    def clamp_hi():
        for _ in range(40):
            d.wheel(500, 400, 120, True)
    yield 50, clamp_hi

    def clamp_hi_check():
        check("the zoom clamps at maxZoom", abs(d.p("pageScale") - 8.0) < 1e-6,
              "%.4f" % d.p("pageScale"))
        for _ in range(120):
            d.wheel(500, 400, -120, True)
    yield 50, clamp_hi_check

    def clamp_lo():
        check("...and at minZoom", abs(d.p("pageScale") - 0.15) < 1e-6,
              "%.4f" % d.p("pageScale"))
        d.v.setProperty("fit", "width")
    yield 50, clamp_lo

    def fitw():
        check("fit-width stays EXACT, never gridded",
              abs(d.p("pageScale") - d.p("availW") / d.p("maxPtW")) < 1e-9)
        check("a page that fits the pane is centred, not draggable",
              d.p("panXMax") < 0.001, "panXMax %.2f" % d.p("panXMax"))
        d.lv.setProperty("contentY", 2000.0)
    yield 400, fitw

    # ---- 4. middle-drag pans ------------------------------------------------
    def pan_start():
        st["py"] = d.c("contentY")
        d.press(500, 500)
        d.move(500, 380)
    yield 300, pan_start

    def pan_check():
        check("middle-drag moves the content 1:1 with the pointer",
              abs((d.c("contentY") - st["py"]) - 120) < 1.5,
              "dy %.1f for a 120px drag" % (d.c("contentY") - st["py"]))
        d.move(500, 500)
    yield 40, pan_check

    def pan_back():
        check("...and back when the pointer comes back (1:1 from the PRESS)",
              abs(d.c("contentY") - st["py"]) < 1.5, "contentY %.1f" % d.c("contentY"))
        d.release(500, 500)
        d.move(500, 200)
    yield 40, pan_back

    def pan_done():
        check("...and a move after the release moves nothing",
              abs(d.c("contentY") - st["py"]) < 1.5)
        d.v.setProperty("fit", "none")
        d.v.setProperty("zoom", 3.0)
    yield 40, pan_done

    def hpan():
        check("a page zoomed past the pane can be dragged sideways",
              d.p("panXMax") > 100, "panXMax %.0f" % d.p("panXMax"))
        d.press(500, 500)
        d.move(420, 500)
    yield 400, hpan

    def hpan_check():
        check("...1:1 horizontally too", abs(d.p("panX") - 80) < 1.5,
              "panX %.1f" % d.p("panX"))
        d.move(15, 500)
    yield 40, hpan_check

    def hpan_clamp():
        want = min(d.p("panXMax"), 80 + 405)   # 500 -> 420 -> 15, from the press
        check("panX follows the drag and clamps at the page edge",
              abs(d.p("panX") - want) < 1.5,
              "panX %.1f, wanted %.1f (limit %.1f)"
              % (d.p("panX"), want, d.p("panXMax")))
        d.release(15, 500)
        d.v.setProperty("fit", "width")
    yield 40, hpan_clamp

    def recentre():
        check("going back to fit-width puts the sheet on the centre line",
              abs(d.p("panX")) < 0.001, "panX %.2f" % d.p("panX"))
        st["n1"] = len(d.prov.iids)
    yield 300, recentre

    # ---- 5. what the debounce is worth --------------------------------------
    def naive():
        d.wheel(500, 400, 120, True)
        d.v.setProperty("rasterScale", d.p("pageScale"))   # i.e. no debounce
    for _ in range(10):
        yield 12, naive

    def naive_report():
        n = len(d.prov.iids) - st["n1"]
        print("\n  ten notches, sourceSize debounced : %d rasters" % st["debounced"])
        print("  ten notches, sourceSize per notch : %d rasters" % n)
        check("the debounce is what keeps the rasters down",
              n > st["debounced"] * 3, "%d vs %d" % (n, st["debounced"]))
    yield 600, naive_report


def main(path):
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    if path is None:                      # AFTER the app: QPainter needs one
        tmp = os.path.join(tempfile.gettempdir(), "reader-zoom-harness")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, "pages.pdf")
        make_pdf(path)

    lib = pdfdoc.PdfLibrary()
    prov = _Probe(lib)
    driver = _Driver(lib, path, prov, app)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    import main as rdr
    from deskstyle import DeskStyle
    keep = [rdr.Palette(rdr.PANEL_THEME), DeskStyle(parent=engine), driver]
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Probe", driver)
    engine.addImageProvider("pdfpage", prov)

    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        os.path.join(APP, "qml", "theme", "Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    pc = QQmlComponent(engine)
    pc.setData(PROBE_QML.encode(), QUrl.fromLocalFile(
        os.path.join(APP, "qml", "probe.qml")))
    win = pc.create()
    if win is None:
        raise SystemExit("probe QML failed: " + pc.errorString())
    keep.append(win)
    driver.win = win
    sys.exit(app.exec())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
