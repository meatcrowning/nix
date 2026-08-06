#!/usr/bin/env python3
"""Prove QtWebEngine spell-checking actually marks a misspelling.

The failure this exists for is silent: `isSpellCheckEnabled()` returns True
whether or not a dictionary was found, so the only honest check is to right-
click a misspelled word in an editable field and read what Chromium put in the
context-menu request. Empty `misspelledWord` = the checker is dead.

    tools/spell-test.py            # the tag main.py would pick, must find one
    tools/spell-test.py en-US      # probe one tag explicitly

Offscreen and self-contained — a minimal Window/WebEngineView, never surfer's
own Main.qml (which needs a real compositor), and it touches nothing the user
can see. Exit 0 = misspelling detected with suggestions.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "pylib"))

from PySide6.QtCore import (QCoreApplication, QEvent,  # noqa: E402
                            QPointF, Qt, QTimer, QUrl)
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick  # noqa: E402

QML = """
import QtQuick
import QtQuick.Window
import QtWebEngine

Window {
    id: win
    width: 600; height: 400; visible: true
    property string word: ""
    property string suggestions: ""
    property bool answered: false
    WebEngineView {
        id: view
        objectName: "view"
        anchors.fill: parent
        profile: WebEngineProfile { offTheRecord: true }
        onContextMenuRequested: function(request) {
            request.accepted = true            // never show a menu
            win.word = "" + request.misspelledWord
            win.suggestions = request.spellCheckerSuggestions.join(", ")
            win.answered = true
        }
    }
}
"""

PAGE = ("data:text/html,<body><textarea id=t autofocus "
        "style='width:400px;height:200px'>wrongg</textarea></body>")


def main():
    # The resolver under test — same code path main.py uses at startup.
    from main import _spell_dirs, _spell_language

    tag = sys.argv[1] if len(sys.argv) > 1 else _spell_language()
    print(f"dictionary dirs: {_spell_dirs()}")
    if not tag:
        print("FAIL: no .bdic dictionary installed in any of those dirs")
        return 1
    print(f"probing tag: {tag}")

    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    eng = QQmlApplicationEngine()
    eng.loadData(QML.encode(), QUrl("qrc:/spell-test.qml"))
    if not eng.rootObjects():
        print("FAIL: probe QML did not load")
        return 1
    win = eng.rootObjects()[0]
    view = win.findChild(object, "view")

    prof = view.property("profile")
    prof.setSpellCheckLanguages([tag])
    prof.setSpellCheckEnabled(True)
    view.setProperty("url", QUrl(PAGE))

    def right_click():
        pos = QPointF(80, 40)
        gpos = win.mapToGlobal(pos.toPoint()).toPointF()
        for typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            QCoreApplication.sendEvent(win, QMouseEvent(
                typ, pos, gpos, Qt.RightButton, Qt.RightButton, Qt.NoModifier))

    # 3s is comfortably past load+first paint for a data: URL; the checker only
    # marks words the renderer has laid out.
    QTimer.singleShot(3000, right_click)
    QTimer.singleShot(5000, app.quit)   # the request arrives in ms, or not at all
    app.exec()

    if not win.property("answered"):
        print("FAIL: no context menu request — the probe click did not land")
        return 1
    word = win.property("word")
    sugg = win.property("suggestions")
    print(f"misspelledWord={word!r} suggestions={sugg!r}")
    if not word:
        print(f"FAIL: '{tag}' marked nothing — no {tag}.bdic Chromium can read")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
