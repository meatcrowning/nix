#!/usr/bin/env python3
"""systheme-toast-test.py — the systheme progress TOAST, offscreen.

systheme creation reports itself as a toast with a progress bar
(qml/SysthemeToast.qml), driven by the real Bridge.systhemeProgress signal.
This builds the real Bridge over a scratch db, loads the real toast component,
and drives the python progress pipeline — the stderr phase parser, the ease
tick, and the terminal outcome — asserting both that the map the toast consumes
is right and that the QML resolves every binding (a control that draws but does
nothing shows up here as a QML warning and nowhere else).

Offscreen, hard: no window on his screen, no contact with the live player, its
socket, db or audio device.

    apps/player/tools/systheme-toast-test.py
"""
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_tmp = tempfile.TemporaryDirectory(prefix="systheme-toast-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())


def _relaunch_under_player_python():
    if os.environ.get("SYSTHEME_TEST_RELAUNCHED"):
        return
    p = shutil.which("player")
    text = open(p, encoding="utf-8", errors="replace").read() if p else ""
    m = re.search(r"/nix/store/[^\" ]+-env/bin/python3[0-9.]*", text)
    if not m:
        sys.exit("no PySide6, and no `player` wrapper to resolve its python from")
    os.environ["SYSTHEME_TEST_RELAUNCHED"] = "1"
    os.execv(m.group(0), [m.group(0), str(Path(__file__).resolve())] + sys.argv[1:])


try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    _relaunch_under_player_python()

from PySide6.QtCore import (Property, QObject, QUrl, QtMsgType, Signal, Slot,
                            qInstallMessageHandler)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

sys.path.insert(0, str(APP))
import main as P  # noqa: E402

QML = APP / "qml"
KEEP = []
QML_MSGS = []
FAILS = []
CHECKS = 0


def check(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    print(("PASS  " if cond else "FAIL  ") + name
          + (("  " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def on_qml_message(mtype, ctx, msg):
    if mtype in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg,
                 QtMsgType.QtFatalMsg):
        QML_MSGS.append(msg)


def no_qml_warnings(label):
    check(f"no QML warnings {label}", not QML_MSGS, " | ".join(QML_MSGS))
    QML_MSGS.clear()


class StubPlayer(QObject):
    queueChanged = Signal()
    currentChanged = Signal()

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {}

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return 0


class StubStyle(QObject):
    changed = Signal()

    @Property(str, notify=changed)
    def fontFamily(self): return "monospace"
    @Property(int, notify=changed)
    def fontSize(self): return 15
    @Property(bool, notify=changed)
    def reduceMotion(self): return True
    @Property(float, notify=changed)
    def animSpeed(self): return 1.0


class StubPalette(QObject):
    changed = Signal()

    @Property(QColor, notify=changed)
    def bg(self): return QColor("#101010")
    @Property(QColor, notify=changed)
    def bgAlt(self): return QColor("#202020")
    @Property(QColor, notify=changed)
    def border(self): return QColor("#303030")
    @Property(QColor, notify=changed)
    def accent(self): return QColor("#ff0000")
    @Property(QColor, notify=changed)
    def dim(self): return QColor("#404040")
    @Property(QColor, notify=changed)
    def text(self): return QColor("#e0e0e0")
    @Property(QColor, notify=changed)
    def textDim(self): return QColor("#a0a0a0")
    @Property(QColor, notify=changed)
    def highlight(self): return QColor("#0080ff")
    @Property(QColor, notify=changed)
    def ok(self): return QColor("#00ff00")
    @Property(QColor, notify=changed)
    def warn(self): return QColor("#ffff00")
    @Property(QColor, notify=changed)
    def crit(self): return QColor("#ff8000")
    @Property(QColor, notify=changed)
    def info(self): return QColor("#8000ff")


class StubProc:
    """Stands in for the systheme QProcess: the phase parser only calls
    readAllStandardError(). bytes() accepts what it returns."""
    def __init__(self, blob):
        self._blob = blob

    def readAllStandardError(self):
        return self._blob

    def readAllStandardOutput(self):
        return b""


def spin(app, ms=120):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()


HARNESS_QML = b"""
import QtQuick
import QtQuick.Window
Window {
    width: 480; height: 826; visible: true
    SysthemeToast { objectName: "toast"; anchors.fill: parent }
}
"""


def main():
    qInstallMessageHandler(on_qml_message)
    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on %r, not offscreen" % app.platformName())

    prefs = P.Prefs()
    library = P.Library(P.TagWriter(prefs))
    player = StubPlayer()
    bridge = P.Bridge(library, player, None)
    KEEP.extend([prefs, library, player, bridge])

    emitted = []
    bridge.systhemeProgress.connect(lambda m: emitted.append(dict(m)))

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    style, palette = StubStyle(), StubPalette()
    KEEP.extend([style, palette])
    ctx.setContextProperty("OnAir", False)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Library", bridge)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Prefs", prefs)

    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.append(theme)
    ctx.setContextProperty("Theme", theme)

    wrap = QQmlComponent(engine)
    wrap.setData(HARNESS_QML, QUrl.fromLocalFile(str(QML / "systheme-harness.qml")))
    win = wrap.create(ctx)
    if win is None:
        print("FAIL  the harness window did not build:", wrap.errorString())
        return 1
    KEEP.append(win)
    spin(app, 200)

    toast = win.findChild(QObject, "toast")
    check("SysthemeToast built", toast is not None)
    if toast is None:
        return 1
    check("toast is hidden before any run", toast.property("shown") is False)
    no_qml_warnings("on load")

    # ---- start: the run begins, the toast opens at a low fraction ----
    bridge._systheme_last_err = ""
    bridge._systheme_frac = 0.03
    bridge._systheme_target = 0.08
    bridge._systheme_label = "creating systheme…"
    bridge._systheme_emit(True)
    spin(app)
    check("start emits an active map", emitted and emitted[-1]["active"] is True, emitted[-1] if emitted else None)
    check("toast shows on start", toast.property("shown") is True)
    check("bar reflects the fraction", abs(float(toast.property("fraction")) - 0.03) < 1e-6,
          toast.property("fraction"))
    check("label reaches the toast", toast.property("label") == "creating systheme…")
    no_qml_warnings("on start")

    # ---- a phase line off systheme.py's stderr advances the bar + renames it ----
    bridge._systheme_proc = StubProc(b"systheme: comfy job abc123 submitted; waiting\n")
    bridge._on_systheme_stderr()
    spin(app)
    check("the 'waiting' phase raised the target to the render band",
          bridge._systheme_target >= 0.90, bridge._systheme_target)
    check("…and renamed the toast", toast.property("label") == "rendering",
          toast.property("label"))
    no_qml_warnings("after a phase line")

    # ---- the ease tick creeps the shown fraction toward the target ----
    before = bridge._systheme_frac
    bridge._systheme_tick()
    check("the ease tick moves the bar forward", bridge._systheme_frac > before,
          (before, bridge._systheme_frac))
    check("…but never past the phase ceiling", bridge._systheme_frac <= bridge._systheme_target)

    # ---- a failure ends the run: outcome shown, no bar, crit tint, then lingers ----
    QML_MSGS.clear()
    bridge._systheme_proc = StubProc(b"systheme: ComfyUI backend not healthy at ...\n")
    bridge._on_systheme_done(1, 0)
    spin(app)
    check("finish emits an inactive map", emitted[-1]["active"] is False)
    check("…with a fail outcome", emitted[-1]["outcome"] == "fail", emitted[-1])
    check("bar is full at the end", abs(emitted[-1]["fraction"] - 1.0) < 1e-6)
    check("toast still shown (result lingers, docs/DESIGN.md §7.2)",
          toast.property("shown") is True)
    check("failure reason reached the label",
          "systheme failed" in toast.property("label"), toast.property("label"))
    check("…and it is the FINAL stderr line, not a stale phase",
          "not healthy" in toast.property("label"), toast.property("label"))
    no_qml_warnings("on failure")

    # ---- a success outcome ----
    class FakeOut(StubProc):
        def readAllStandardOutput(self):
            return b'{"applied": true, "method": "comfy"}\n'
        def readAllStandardError(self):
            return b""
    bridge._systheme_proc = FakeOut(b"")
    bridge._on_systheme_done(0, 0)
    spin(app)
    check("success outcome is 'ok'", emitted[-1]["outcome"] == "ok", emitted[-1])
    check("success label names the method", "applied" in toast.property("label"))
    no_qml_warnings("on success")

    print()
    print(f"{CHECKS} checks, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
