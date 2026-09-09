#!/usr/bin/env python3
"""Numerically probe Oxygen's native content painting, entirely offscreen."""
import os
import sys
import tempfile
assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
assert not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPalette, QImage
from PySide6.QtWidgets import (QApplication, QWidget, QTreeView, QGraphicsView,
                               QTextEdit, QStyleFactory)
with tempfile.TemporaryDirectory(prefix="native-surface-test-") as temporary:
    os.environ["XDG_CONFIG_HOME"] = temporary
    os.environ["XDG_CACHE_HOME"] = temporary
    app = QApplication(["native-surface-test", "-style", "Fusion"])
    assert app.platformName() == "offscreen"
    app.addLibraryPath(sys.argv[1])
    style = QStyleFactory.create("oxygen")
    assert style is not None
    app.setStyle(style)
    pal = QPalette()
    for role, color in ((QPalette.Window, "#351c19"), (QPalette.WindowText, "#ffffff"),
                        (QPalette.Base, "#e0c9c4"), (QPalette.Text, "#201514")):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    win = QWidget()
    win.setAttribute(Qt.WA_StyledBackground)
    win.resize(500, 500)
    for cls in (QTreeView, QGraphicsView, QTextEdit):
        view = cls(win)
        view.setGeometry(20, 40, 450, 430)
        view.show()
        win.show()
        app.processEvents()
        image = QImage(win.size(), QImage.Format_ARGB32)
        win.render(image)
        a = image.pixelColor(350, 110)
        b = image.pixelColor(350, 400)
        assert a.lightnessF() > .5 and b.lightnessF() > .5, (cls, a.name(), b.name())
        assert a != b, (cls, "flat surface", a.name())
        print("ok - native content gradient:", cls.__name__, a.name(), b.name())
        view.setParent(None)
        view.deleteLater()
        app.processEvents()

    class KFilePlacesView(QTreeView):
        pass
    places = KFilePlacesView(win)
    assert places.inherits("KFilePlacesView")
    places.setGeometry(0, 0, 150, 450)
    places.show()
    app.processEvents()
    image = QImage(win.size(), QImage.Format_ARGB32)
    win.render(image)
    assert places.palette().text().color() == pal.windowText().color()
    print("ok - transparent Places delegate uses native WindowText")
    win.close()
