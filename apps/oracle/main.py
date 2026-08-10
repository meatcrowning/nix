#!/usr/bin/env python3
"""oracle — a deliberately small chat window for the local ollama daemon.

The twelfth vendored app, and the plainest: a MODEL SELECTOR filled from the
ollama daemon's own `/api/tags`, and a PROMPT BOX that sends one chat turn to
`/api/chat` and shows the streamed reply. Nothing more — no history persistence,
no settings, no system prompt. It exists to talk to `http://127.0.0.1:11434`
and get out of the way.

It draws like the rest of the desktop rather than choosing anything here: pixel
font at the desktop's own size through `DeskStyle`, the wal palette parsed and
watched out of the panel's `Theme.qml` (mirrors reader/filer/viewer), motion
from `qmlcommon/Motion.qml`, `Kinetic*` views, and its titlebar chrome drawn by
the hyprvtb compositor plugin through `pylib/vtbclient.py` — see docs/DESIGN.md.

The whole ollama seam is `Ollama` below, on `QNetworkAccessManager`: `/api/tags`
for the model list, and a STREAMING `/api/chat` POST whose NDJSON reply is
parsed line by line and emitted as it arrives, so the reply grows on screen the
way it comes off the model.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QUrl, QFileSystemWatcher
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                               QNetworkReply)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)

#: The local ollama daemon. Loopback-pinned like everything else that speaks to
#: a local backend here — never a new listener (root AGENTS.md → the tailnet).
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


# ---- the wallpaper palette (mirrors reader/viewer/filer — see reader/main.py) --
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (identical to reader's and viewer's)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)   # dir watch catches atomic replaces
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
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge — oracle draws no chrome of its own, so the
    compositor draws the titlebar (docs/DESIGN.md §12). oracle has no history and
    no view modes, so it registers with the defaults and no buttons; the window
    title is still drawn by the plugin. The one thing it publishes is a FOOTER
    naming the connected daemon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient()

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Ollama(QObject):
    """The whole ollama seam: the model list and one streamed chat turn.

    `refreshModels` GETs `/api/tags`; `send` POSTs a single-turn `/api/chat`
    with `stream: true` and emits each NDJSON delta as it arrives, so QML never
    parses the wire — it receives `replyStarted` / `replyChunk` / `replyDone`,
    or `replyError` with a reason it can draw (docs/DESIGN.md §10: an action that
    cannot be reported must say so, not silently do nothing). One turn at a
    time: a new `send` aborts any reply still streaming."""

    modelsChanged = Signal()
    busyChanged = Signal()
    modelsError = Signal(str)

    replyStarted = Signal()
    replyChunk = Signal(str)
    replyThinking = Signal(str)   # a "thinking" model's reasoning deltas
    replyDone = Signal()
    replyError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._models = []
        self._busy = False
        self._reply = None       # the in-flight chat QNetworkReply, if any
        self._buf = b""          # partial NDJSON line carried between reads

    # ---- model list ----

    @Property("QStringList", notify=modelsChanged)
    def models(self):
        return self._models

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    @Slot()
    def refreshModels(self):
        req = QNetworkRequest(QUrl(OLLAMA + "/api/tags"))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_tags(reply))

    def _on_tags(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.modelsError.emit(reply.errorString())
                return
            data = bytes(reply.readAll().data())
            obj = json.loads(data or b"{}")
            names = sorted((m.get("name", "") for m in obj.get("models", [])
                            if m.get("name")), key=str.lower)
            if names != self._models:
                self._models = names
                self.modelsChanged.emit()
        except (ValueError, TypeError) as e:
            self.modelsError.emit(str(e))
        finally:
            reply.deleteLater()

    # ---- one streamed chat turn ----

    @Slot(str, str)
    def send(self, model, prompt):
        if not model or not prompt.strip():
            return
        self.cancel()          # one turn at a time
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }).encode("utf-8")
        req = QNetworkRequest(QUrl(OLLAMA + "/api/chat"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        self._buf = b""
        self._set_busy(True)
        self.replyStarted.emit()
        reply = self._nam.post(req, body)
        self._reply = reply
        reply.readyRead.connect(lambda: self._on_stream(reply))
        reply.finished.connect(lambda: self._on_finished(reply))

    @Slot()
    def cancel(self):
        if self._reply is not None:
            r, self._reply = self._reply, None
            r.readyRead.disconnect()
            r.finished.disconnect()
            r.abort()
            r.deleteLater()
            self._set_busy(False)

    def _on_stream(self, reply):
        if reply is not self._reply:
            return
        self._buf += bytes(reply.readAll().data())
        # NDJSON: one JSON object per line, and a read may split a line.
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("error"):
                self.replyError.emit(str(obj["error"]))
                continue
            msg = obj.get("message") or {}
            # A "thinking" model streams its reasoning in `thinking` with an
            # empty `content` until it starts answering; surface it (drawn
            # dimmed) so the window is not blank while it reasons.
            think = msg.get("thinking", "")
            if think:
                self.replyThinking.emit(think)
            piece = msg.get("content", "")
            if piece:
                self.replyChunk.emit(piece)

    def _on_finished(self, reply):
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        self._set_busy(False)
        err = reply.error()
        if err not in (QNetworkReply.NetworkError.NoError,
                       QNetworkReply.NetworkError.OperationCanceledError):
            self.replyError.emit(reply.errorString())
        else:
            self.replyDone.emit()
        reply.deleteLater()


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("oracle")
    app.setDesktopFileName("oracle")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    ollama = Ollama()

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Ollama", ollama)
    ctx.setContextProperty("ollamaHost", OLLAMA)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    ollama.refreshModels()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
