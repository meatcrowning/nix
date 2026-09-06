#!/usr/bin/env python3
"""Probe: does WebEngineView.CopyImageToClipboard put image data on QClipboard?"""
import os
import sys
import re
import shutil
import subprocess
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent


def _borrow_wrapper_env():
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("no main.py interpreter in wrapper")
    py = m.group(1)
    body = "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("#!")
                     and "singleton.py" not in ln
                     and not ln.startswith("exec "))
    out = subprocess.run(["bash", "-c", body + "\nexec env -0\n"],
                         capture_output=True, check=True).stdout
    env = dict(os.environ)
    for entry in out.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        k, v = entry.decode(errors="replace").split("=", 1)
        if k in ("HOME", "PWD", "SHLVL", "_",
                 "QT_QPA_PLATFORM", "WAYLAND_DISPLAY", "DISPLAY"):
            continue
        env[k] = v
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    return py, env


if not os.environ.get("_SURFER_PROBE_REEXEC"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_PROBE_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

from PySide6.QtCore import (QCoreApplication, QEvent, QPointF, Qt,  # noqa: E402
                            QTimer, QUrl)
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick  # noqa: E402

import base64
import struct
import zlib


def make_png(w=4, h=4, rgb=(255, 0, 0)):
    """Hand-rolled PNG, same technique as clipfile-test.sh (no image lib)."""
    raw = b"".join(b"\0" + bytes(rgb) * w for _ in range(h))
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

QML = """
import QtQuick
import QtQuick.Window
import QtWebEngine

Window {
    id: win
    width: 600; height: 400; visible: true
    property string mediaType: ""
    property string mediaUrl: ""
    property bool answered: false
    WebEngineView {
        id: view
        objectName: "view"
        anchors.fill: parent
        profile: WebEngineProfile { offTheRecord: true }
        onContextMenuRequested: function(request) {
            request.accepted = true
            win.mediaType = request.mediaType
            win.mediaUrl = "" + request.mediaUrl
            win.answered = true
        }
    }
}
"""

PAGE = ("data:text/html,<body style='margin:0'>"
        "<img id=i src='data:image/png;base64," + base64.b64encode(make_png()).decode() + "' "
        "style='width:200px;height:200px'></body>")


def main():
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    print("platform:", app.platformName())
    if app.platformName() != "offscreen":
        return 2
    eng = QQmlApplicationEngine()
    eng.loadData(QML.encode(), QUrl("qrc:/probe.qml"))
    if not eng.rootObjects():
        print("FAIL: QML did not load")
        return 1
    win = eng.rootObjects()[0]
    view = win.findChild(object, "view")
    view.setProperty("url", QUrl(PAGE))

    state = {"phase": "load"}

    def right_click():
        state["phase"] = "click"
        pos = QPointF(100, 100)
        gpos = win.mapToGlobal(pos.toPoint()).toPointF()
        for typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            QCoreApplication.sendEvent(win, QMouseEvent(
                typ, pos, gpos, Qt.RightButton, Qt.RightButton, Qt.NoModifier))

    def trigger():
        state["phase"] = "trigger"
        # sanity: does a plain text copy land offscreen?
        clip0 = QGuiApplication.clipboard()
        clip0.setText("plain-sanity")
        print("text copy landed:", clip0.text() == "plain-sanity",
              "formats:", clip0.mimeData().formats())

        def run_js(cb, js):
            view.runJavaScript(js, cb)

        # select the whole page text, then trigger the Copy action
        def after_select():
            view.triggerWebAction(QWebEnginePage.WebAction.Copy.value)
            QTimer.singleShot(1500, after_copy)
        def after_copy():
            c = QGuiApplication.clipboard()
            print("after Copy action: text=", repr(c.text()[:40]),
                  "formats:", c.mimeData().formats())
            view.triggerWebAction(QWebEnginePage.WebAction.CopyImageUrlToClipboard.value)
            QTimer.singleShot(1500, after_url)
        def after_url():
            c = QGuiApplication.clipboard()
            print("after CopyImageUrl: text=", repr(c.text()[:60]),
                  "formats:", c.mimeData().formats())
            act = QWebEnginePage.WebAction.CopyImageToClipboard
            print("triggering WebAction", act.value)
            view.triggerWebAction(act.value)
            QTimer.singleShot(2500, read_clip)

        run_js(after_select, "document.body.focus();"
                             "var s=window.getSelection();"
                             "var r=document.createRange();"
                             "r.selectNodeContents(document.body);"
                             "s.removeAllRanges();s.addRange(r);"
                             "true")

    def read_clip():
        state["phase"] = "read"
        clip = QGuiApplication.clipboard()
        print("clipboard formats:", clip.mimeData().formats())
        print("hasImage:", clip.mimeData().hasImage())
        img = clip.image()
        print("image size:", img.width(), "x", img.height(),
              "null:", img.isNull())
        print("text:", repr(clip.text()[:60]))
        app.quit()

    QTimer.singleShot(3000, right_click)
    QTimer.singleShot(3200, trigger)  # request captured synchronously
    QTimer.singleShot(9000, app.quit)  # safety
    app.exec()

    print("answered:", win.property("answered"),
          "mediaType:", win.property("mediaType"),
          "mediaUrl:", win.property("mediaUrl"))
    print("phase:", state["phase"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
