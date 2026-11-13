#!/usr/bin/env python3
"""coder -- a native front end for the Claude Code and Codex CLIs.

Coder runs the real ``claude`` and ``codex`` binaries and shows their
sessions: a project-grouped session list, a streamed transcript with folded
tool rows and inline approvals, and a composer with model, effort and
permission pickers. Both CLIs keep their own configuration, hooks, skills
and session stores; Coder never writes them (apps/coder/AGENTS.md,
docs/agents/coder-plan.md).

Two roofs, one tree, as in painter and chatter: under Plasma ``qml/Root.qml``
sits in a kdeshell QMainWindow with native menus, toolbar and status bar;
under Hyprland ``qml/Main.qml`` is a Window around it and the hyprvtb
titlebar carries the buttons.

  coder [--selftest] [--face=plasma|hypr]
"""

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
sys.path.insert(0, str(HERE.parent / "pylib"))
sys.path.insert(0, str(HERE))

VERSION = "0.1"


def _selftest_env():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("DISPLAY", None)


selftest = "--selftest" in sys.argv
if selftest:
    sys.argv.remove("--selftest")
    _selftest_env()
face = ""
for _arg in list(sys.argv[1:]):
    if _arg.startswith("--face="):
        face = _arg.split("=", 1)[1]
        sys.argv.remove(_arg)
if face == "hypr":
    os.environ["DESK_SESSION"] = "hypr"
elif face == "plasma":
    os.environ["DESK_SESSION"] = "plasma"

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QColor, QIcon  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402
# Registers the QtQuick wrappers, so a QML Window root arrives as a
# QQuickWindow (the selftest's grabWindow) rather than a bare QWindow.
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401

import kdeshell  # noqa: E402
from deskstyle import DeskStyle  # noqa: E402
from kdetheme import is_plasma, theme_source  # noqa: E402
from nativepalette import session_palette  # noqa: E402
from styleparticipant import StyleParticipant  # noqa: E402

try:
    from vtbclient import VtbClient  # noqa: E402
except Exception:  # noqa: BLE001
    VtbClient = None

import session as sess  # noqa: E402

PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


@session_palette
class Palette(QObject):
    """The wallpaper palette (Hyprland face); Plasma forwards native roles."""
    changed = Signal()

    def __init__(self, path, parent=None):
        from PySide6.QtCore import QFileSystemWatcher
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        directory = os.path.dirname(self._path)
        if os.path.isdir(directory):
            self._watcher.addPath(directory)
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return False
        colors = dict(self._colors)
        parsed = False
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            if m.group(1) in PALETTE_KEYS:
                colors[m.group(1)] = m.group(2)
                parsed = True
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()
        return parsed

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    from PySide6.QtCore import Property as _P
    bg = _P(QColor, lambda s: s._c("bg"), notify=changed)
    bgAlt = _P(QColor, lambda s: s._c("bgAlt"), notify=changed)
    border = _P(QColor, lambda s: s._c("border"), notify=changed)
    accent = _P(QColor, lambda s: s._c("accent"), notify=changed)
    dim = _P(QColor, lambda s: s._c("dim"), notify=changed)
    text = _P(QColor, lambda s: s._c("text"), notify=changed)
    textDim = _P(QColor, lambda s: s._c("textDim"), notify=changed)
    highlight = _P(QColor, lambda s: s._c("highlight"), notify=changed)
    ok = _P(QColor, lambda s: s._c("ok"), notify=changed)
    warn = _P(QColor, lambda s: s._c("warn"), notify=changed)
    crit = _P(QColor, lambda s: s._c("crit"), notify=changed)
    info = _P(QColor, lambda s: s._c("info"), notify=changed)
    del _P


class Titlebar(QObject):
    """hyprvtb buttons for the Hyprland face; inert under Plasma."""
    clicked = Signal(str)
    buttonsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        if VtbClient is not None and not is_plasma():
            try:
                self._client = VtbClient(on_click=self.clicked.emit)
            except Exception:  # noqa: BLE001 - outside hyprvtb is fine
                self._client = None

    @Slot("QVariantList")
    def setButtons(self, buttons):
        if not self._client:
            return
        out = []
        for b in buttons:
            if hasattr(b, "toVariant"):
                b = b.toVariant()
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), False, bool(b.get("bottom", False))))
        try:
            self._client.set_buttons(out)
        except Exception:  # noqa: BLE001
            pass

    @Slot(str)
    def setFooter(self, text):
        if self._client:
            try:
                self._client.set_footer(text)
            except Exception:  # noqa: BLE001
                pass


class Notifier(QObject):
    """A desktop toast when a turn ends behind an unfocused window."""

    def __init__(self, app_ctl, parent=None):
        super().__init__(parent)
        self.window = None
        self.enabled = not selftest and not os.environ.get("CODER_NO_NOTIFY")
        app_ctl.notify.connect(self.toast)
        self.app_ctl = app_ctl

    def toast(self, summary, body):
        if not self.enabled or not self.app_ctl.pref("notify", True):
            return
        w = self.window
        try:
            if w is not None and w.isActive() and w.isVisible():
                return
        except RuntimeError:
            pass
        try:
            subprocess.Popen(["notify-send", "-a", "Coder", "-i", "utilities-terminal", "--",
                              summary or "coder", body or ""],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def main():
    if face == "hypr":
        os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    else:
        kdeshell.pin_controls_style()
    app = kdeshell.make_app(sys.argv, "coder")
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r, not offscreen" % app.platformName())
    app.setApplicationName("coder")
    app.setApplicationDisplayName("Coder")
    app.setDesktopFileName("coder")

    palette = Palette(theme_source(PANEL_THEME))
    style_participant = StyleParticipant("coder", palette._load, app)  # noqa: F841 keep ref
    style = DeskStyle()
    plasma = is_plasma() if not face else face == "plasma"
    if plasma:
        screen = app.primaryScreen()
        scale = screen.devicePixelRatio() if screen is not None else 1.0
        app.setFont(style.labelFontForScale(scale))

    ctl = sess.App(version=VERSION)
    view = sess.SessionView(ctl)
    bar = Titlebar()
    notifier = Notifier(ctl)

    shell = kdeshell.shell("coder", size=(1180, 820), min_size=(640, 480)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        kdeshell.select_plasma_files(engine)
    ctx = engine.rootContext()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", bar)
    ctx.setContextProperty("App", ctl)
    ctx.setContextProperty("Session", view)
    ctx.setContextProperty("Sessions", ctl.list)
    from spellcheck import SpellCheck
    spell = SpellCheck()
    ctx.setContextProperty("Spell", spell)

    warnings = []
    engine.warnings.connect(lambda errs: warnings.extend(e.toString() for e in errs))

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        return 2
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    if plasma:
        if not shell.load(QML / "Root.qml"):
            print("failed to load Root.qml", file=sys.stderr)
            for w in shell.errors() + warnings:
                print("  %s" % w, file=sys.stderr)
            return 2
        root = shell.root
        shell.bind_chrome(None)
        shell.bind_status()
        shell.bind_title("windowTitle")
        window = shell.show()
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            for w in warnings:
                print("  %s" % w, file=sys.stderr)
            return 2
        window = engine.rootObjects()[0]
        root = window.findChild(QObject, "content")
        bar.clicked.connect(lambda bid: root.tbAction(bid))
    notifier.window = window if hasattr(window, "isActive") else getattr(shell, "handle", None)

    app.aboutToQuit.connect(ctl.shutdown)
    QTimer.singleShot(0, ctl.refresh)

    if not selftest:
        from winstate import WinState
        win_state = WinState(window, "coder")  # noqa: F841 keep ref: geometry
        return app.exec()
    return run_selftest(app, shell, window, root, ctl, view, plasma, warnings)


def run_selftest(app, shell, window, root, ctl, view, plasma, warnings):
    """Offscreen only. CODER_DRIVE=claude|codex replays a fixture turn,
    CODER_SHOT writes a PNG, CODER_MENUS prints the native chrome."""
    import json
    from PySide6.QtCore import QEventLoop

    def spin(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    spin(150)
    report = {"face": "plasma" if plasma else "hypr", "warnings": []}
    drive = os.environ.get("CODER_DRIVE", "")
    prompts = [p for p in os.environ.get("CODER_PROMPTS", "").split("||") if p]
    if drive:
        ctl.newSession(drive)
        spin(200)
        for p in prompts or ["hello"]:
            view.send(p, [])
            for _ in range(60):
                spin(50)
                s = ctl.current
                waiting = [r for r in s.transcript.rows() if r["kind"] == "approval"
                           and r.get("status") == "waiting"]
                for r in waiting:
                    rid = r["meta"]["request_id"]
                    deny = "rm " in (r.get("title", "") + json.dumps(r["meta"].get("input", {})))
                    view.answer(rid, "deny" if deny else "allow", "")
                if s.state == "idle" and not waiting and s.transcript.count > 1:
                    break
        spin(300)
        s = ctl.current
        report["items"] = [[r["kind"], r.get("status", ""), short_text(r)] for r in s.transcript.rows()]
        report["state"] = s.state
        report["usage"] = view.usageText
        report["limits"] = ctl.limitsText
        report["sessions"] = ctl.list.count
    if os.environ.get("CODER_SHOT"):
        spin(200)
        if plasma:
            img = shell.window.grab().toImage()
        else:
            img = window.grabWindow()
        img.save(os.environ["CODER_SHOT"])
        report["shot"] = os.environ["CODER_SHOT"]
    if plasma and os.environ.get("CODER_MENUS"):
        report["chrome"] = shell.dump_chrome()
    report["warnings"] = [str(w) for w in warnings]
    print("CODER_REPORT " + json.dumps(report))
    ctl.shutdown()
    return 1 if warnings else 0


def short_text(r):
    t = r.get("title") or r.get("text") or ""
    return " ".join(str(t).split())[:80]


if __name__ == "__main__":
    sys.exit(main())
