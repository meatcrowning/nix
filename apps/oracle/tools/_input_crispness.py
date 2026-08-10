#!/usr/bin/env python3
"""Is the prompt box crisp? Count the greys, don't look at it.

docs/DESIGN.md §2.2: an EDITABLE item ignores `antialiasing` / `renderType` /
`hintingPreference` for glyph rasterisation UNLESS the font itself carries
`QFont::NoAntialias` — and even then Qt's distance-field renderer will smooth it
back out, so the fix is the PAIR: the whole QFont from `DeskStyle`, plus
`renderType: Text.NativeRendering`. Oracle shipped only the first half, which is
what "the input box renders aliased and blurry" was.

This renders both variants offscreen and counts how many distinct grey levels
each glyph run is drawn with. A crisp pixel face draws in TWO colours (ink and
paper); an antialiased one smears across a dozen or more.

    apps/oracle/tools/_input_crispness.py

WHAT IT CAN AND CANNOT PROVE. Measured 2026-08-09: offscreen, BOTH variants
come back at 1 ink. That is not "the bug was imaginary" — it is the offscreen
platform rasterising through the software path, where there is no distance-field
glyph atlas to smear in the first place. The renderer this bug lives in is the
GL scenegraph in his live session. So a `crisp` result here is a floor (the
paired config is not smeared BY THE FONT), not a verdict on the fix; the fix is
confirmed by him looking at the box.

Offscreen only — QT_QPA_PLATFORM=offscreen, no window on his screen.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "pylib"))

import time  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from deskstyle import DeskStyle  # noqa: E402

QML = """
import QtQuick
import QtQuick.Window

Window {
    width: 420; height: 120; visible: true; color: "#000000"
    TextEdit {
        objectName: "paired"
        x: 8; y: 8; width: 400
        font: DeskStyle.editorFont
        renderType: Text.NativeRendering
        color: "#ffffff"
        text: "ask the model"
    }
    TextEdit {
        objectName: "fontOnly"
        x: 8; y: 60; width: 400
        font: DeskStyle.editorFont
        color: "#ffffff"
        text: "ask the model"
    }
}
"""


def inks(img, y0, y1):
    """Distinct non-background colours in a band — one per antialiasing step."""
    seen = set()
    for y in range(y0, min(y1, img.height())):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() and (c.red() or c.green() or c.blue()):
                seen.add((c.red(), c.green(), c.blue()))
    return seen


def main():
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    style = DeskStyle()
    engine.rootContext().setContextProperty("DeskStyle", style)
    qml = HERE / "_input_crispness.qml"
    qml.write_text(QML)
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        print("FAIL: QML did not load")
        return 2
    win = engine.rootObjects()[0]

    # PySide hands a QML `Window` root back as a bare QWindow — no grabWindow().
    # Reach the scene graph through the item tree and render with
    # QQuickItem.grabToImage, which is asynchronous (same pattern as
    # apps/player/tools/focus-fade-test.py).
    from PySide6.QtQuick import QQuickItem
    root = next(i for i in win.findChildren(QQuickItem) if i.parentItem() is None)
    end = time.time() + 2
    while time.time() < end:
        app.processEvents()

    res = root.grabToImage()
    if res is None:
        print("FAIL: grabToImage refused (no render target?)")
        return 2
    done = []
    res.ready.connect(lambda: done.append(True))
    end = time.time() + 5
    while not done and time.time() < end:
        app.processEvents()
    if not done:
        print("FAIL: grabToImage never became ready")
        return 2
    img = res.image()
    qml.unlink(missing_ok=True)

    paired = inks(img, 8, 52)
    font_only = inks(img, 60, 104)
    print("font + NativeRendering : %3d distinct inks" % len(paired))
    print("font alone             : %3d distinct inks" % len(font_only))
    ok = len(paired) <= 4 and len(paired) <= len(font_only)
    print("crisp" if ok else "STILL SMEARED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
