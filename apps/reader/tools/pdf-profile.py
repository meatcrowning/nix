#!/usr/bin/env python3
"""Where the time goes in reader's PDF mode — offscreen, on real documents.

Two layers, because "rough" has two possible causes and only one of them is the
rasterizer:

  1. **Python side** (`--pages`): `QPdfDocument.load`, the page-size sweep and
     the outline that `PdfLibrary.open` does before QML sees anything, then
     `render()` at the pixel sizes fit-width actually asks for, and one
     `Pdf.search` sweep.
  2. **Live view** (`--view`): the real `qml/PdfView.qml` in an offscreen
     window, scrolled by setting `contentY` from a timer, with a 4 ms heartbeat
     measuring how long the GUI thread is unavailable. A stall is what a reader
     feels; a render time is only its cause. It also records which THREAD the
     image provider is called on, which is the difference between
     `asynchronous: true` meaning something and meaning nothing.

Never opens a window on his screen: offscreen is forced, hard, and asserted.
"""
import os
import sys
import time
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # and nothing to fall back TO
os.environ.pop("DISPLAY", None)

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(os.path.dirname(APP), "pylib"))

from PySide6.QtCore import QSize, QTimer, QUrl, QObject, Slot, Qt, QElapsedTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

import pdfdoc


def stats(xs):
    xs = sorted(xs)
    if not xs:
        return "n=0"
    n = len(xs)
    return ("n=%d  min %.1f  med %.1f  p95 %.1f  max %.1f  mean %.1f"
            % (n, xs[0], xs[n // 2], xs[min(n - 1, int(n * 0.95))], xs[-1],
               sum(xs) / n))


def profile_pages(path, width_px, npages):
    lib = pdfdoc.PdfLibrary()
    t0 = time.perf_counter()
    info = lib.open("left", path)
    t_open = (time.perf_counter() - t0) * 1000
    if not info["ok"]:
        print("  ! %s" % info["error"])
        return
    n = info["pageCount"]
    print("  open()            %8.1f ms   (%d pages, %d outline rows)"
          % (t_open, n, len(info["outline"])))

    # what the delegate asks for at fit-width in a ~1000px pane
    times = []
    step = max(1, n // npages)
    for i in range(0, n, step):
        pw = info["pages"][i]["w"]
        ph = info["pages"][i]["h"]
        scale = width_px / pw
        size = QSize(int(pw * scale), int(ph * scale))
        t = time.perf_counter()
        img = lib.render("left", info["gen"], i, size)
        times.append((time.perf_counter() - t) * 1000)
        if img is None:
            print("  ! render returned None on page %d" % i)
    print("  render @%4dpx     %s ms" % (width_px, stats(times)))

    t = time.perf_counter()
    hits = lib.search("left", "the")
    print("  search('the')     %8.1f ms   (%d pages hit)"
          % ((time.perf_counter() - t) * 1000, len(hits)))
    lib.close("left")


PROBE_QML = """
import QtQuick
import QtQuick.Window
import "file:%s/qml"

// Everything here is driven from QML, exactly as the app drives it: the
// document is opened by a call from JS and the scroll is a QML Timer. Driving
// it from Python instead DEADLOCKS — the GUI thread holds the GIL inside the
// PySide call while Qt's QQuickPixmapReader thread waits for it, which is the
// same contention this harness exists to measure, only fatal.
Window {
    id: win
    width: 1000; height: 900; visible: true
    property var gaps: []
    property real last: 0
    property real speed: probeSpeed
    property int ticks: 0
    readonly property int halfTicks: probeMs / 16 / 2

    PdfView { id: v; anchors.fill: parent; docKey: "left" }

    Timer {                                   // 4ms heartbeat: GUI-thread stalls
        id: hb; interval: 4; repeat: true; running: false
        onTriggered: { var n = Date.now(); win.gaps.push(n - win.last); win.last = n; }
    }
    Timer {                                   // the scroll itself, ~60Hz
        id: scroller; interval: 16; repeat: true; running: false
        onTriggered: { var lv = v.children[0];
                       // half the run down, half back up: the way back is what
                       // shows whether the page cache is a cache.
                       if (win.ticks++ > win.halfTicks) win.speed = -Math.abs(win.speed);
                       lv.contentY = Math.max(0, lv.contentY + win.speed); }
    }
    Timer {                                   // settle, then run, then report
        interval: 400; running: true
        onTriggered: { v.doc = Probe.openDoc(); win.last = Date.now();
                       hb.start(); scroller.start(); stopper.start(); }
    }
    Timer {
        id: stopper; interval: probeMs; running: false
        onTriggered: { hb.stop(); scroller.stop(); Probe.report(win.gaps); }
    }
}
""".replace("%s", APP)


class _Probe(pdfdoc.PageProvider):
    """The real provider, instrumented — a subclass, because Qt calls the C++
    virtual and would never see a Python attribute assigned over the method."""

    def __init__(self, lib):
        super().__init__(lib)
        self.threads = {}
        self.ms = []
        self.iids = []

    def requestImage(self, iid, size, requested):
        tid = threading.get_ident()
        self.threads[tid] = self.threads.get(tid, 0) + 1
        t = time.perf_counter()
        img = super().requestImage(iid, size, requested)
        self.ms.append((time.perf_counter() - t) * 1000)
        self.iids.append("%s@%dx%d" % (iid, requested.width(), requested.height()))
        return img


class _Driver(QObject):
    """What the probe QML calls: open the document, and take the gap list back."""

    def __init__(self, lib, path, prov, app):
        super().__init__()
        self._lib, self._path, self._prov, self._app = lib, path, prov, app
        self.open_ms = 0.0

    @Slot(result="QVariantMap")
    def openDoc(self):
        t = time.perf_counter()
        info = self._lib.open("left", self._path)
        self.open_ms = (time.perf_counter() - t) * 1000
        if not info["ok"]:
            raise SystemExit(info["error"])
        return info

    @Slot("QVariantList")
    def report(self, gaps):
        gaps = [float(g) for g in gaps]
        prov = self._prov
        print("  Pdf.open()        %8.1f ms  (blocks the GUI thread)" % self.open_ms)
        print("  provider threads  %s"
              % ", ".join("%s%s x%d"
                          % (t, " GUI" if t == threading.main_thread().ident else " worker", c)
                          for t, c in prov.threads.items()))
        print("  provider call     %s ms" % stats(prov.ms))
        print("  GUI stall (4ms hb)%s ms" % stats(gaps))
        over = [g for g in gaps if g > 20]
        print("  beats > 20ms      %d of %d  (%.0f%%)"
              % (len(over), len(gaps), 100.0 * len(over) / max(1, len(gaps))))
        n = len(prov.iids)
        uniq = len(set(prov.iids))
        lib = self._lib
        print("  provider calls    %d for %d distinct pages  (%d re-requested)"
              % (n, uniq, n - uniq))
        print("  of those          %d RASTERIZED, %d served from the page cache"
              % (lib.rastered, lib.cached))
        self._app.quit()


def profile_view(path, seconds, px_per_tick):
    from PySide6.QtQml import QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)

    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

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
    ctx.setContextProperty("probeMs", int(seconds * 1000))
    ctx.setContextProperty("probeSpeed", float(px_per_tick))
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

    app.exec()
    lib.close("left")


def selftest(path):
    """The three things the caches must not get wrong, checked rather than
    assumed: a repeat is served, a reload is NOT, and a stale generation is
    refused. Cheap enough to run on any PDF."""
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    lib = pdfdoc.PdfLibrary()
    info = lib.open("left", path)
    if not info["ok"]:
        raise SystemExit(info["error"])
    size = QSize(600, 800)
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print("%s  %s  %s" % ("PASS" if cond else "FAIL", name, detail))

    a = lib.render("left", info["gen"], 0, size)
    n0 = lib.rastered
    b = lib.render("left", info["gen"], 0, size)
    check("a repeated page is served from the cache",
          lib.rastered == n0 and lib.cached >= 1 and b is not None)
    check("...and it is the same image", a is not None and b is not None
          and a.sizeInBytes() == b.sizeInBytes())
    check("a stale generation is refused",
          lib.render("left", info["gen"] - 1, 0, size) is None)

    info2 = lib.open("left", path)
    n1 = lib.rastered
    lib.render("left", info2["gen"], 0, size)
    check("a reload rasterizes again rather than serving the old page",
          lib.rastered == n1 + 1, "gen %d -> %d" % (info["gen"], info2["gen"]))

    small = pdfdoc.CACHE_BYTES
    pdfdoc.CACHE_BYTES = 1
    lib2 = pdfdoc.PdfLibrary()
    i2 = lib2.open("left", path)
    lib2.render("left", i2["gen"], 0, size)
    lib2.render("left", i2["gen"], min(1, i2["pageCount"] - 1), size)
    check("the budget evicts rather than growing without limit",
          len(lib2._raster) <= 1, "%d entries at a 1-byte budget" % len(lib2._raster))
    pdfdoc.CACHE_BYTES = small

    t = time.perf_counter()
    lib.search("left", "the")
    cold = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    lib.search("left", "them")
    warm = (time.perf_counter() - t) * 1000
    check("a second find keystroke does not re-extract the document",
          warm < max(2.0, cold / 10), "cold %.1f ms, next key %.2f ms" % (cold, warm))
    lib.close("left")
    check("close forgets the pages it held", not lib._raster and not lib._text)
    print("all checks passed" if ok else "FAILURES")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--width", type=int, default=980)
    ap.add_argument("--pages", type=int, default=12)
    ap.add_argument("--view", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--speed", type=float, default=40.0)
    a = ap.parse_args()
    print(os.path.basename(a.pdf))
    if a.selftest:
        selftest(a.pdf)
    elif a.view:
        profile_view(a.pdf, a.seconds, a.speed)
    else:
        profile_pages(a.pdf, a.width, a.pages)
