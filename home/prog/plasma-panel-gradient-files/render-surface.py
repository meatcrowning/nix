#!/usr/bin/env python3
"""Render the KDE style's window background as one screen-sized PNG.

The panels crop this image at their global coordinates.  Rendering a real,
never-shown QWidget is the same mechanism apps/pylib/kdeshell.py uses for the
pixel-exact background behind our Plasma QML apps; it does not map a window or
interact with the desktop.
"""

from pathlib import Path
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QImage, QRegion
from PySide6.QtWidgets import QApplication, QWidget


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1
    rect = screen.geometry()
    width, height = max(1, rect.width()), max(1, rect.height())

    # Oxygen only draws this primitive for a real top-level QWidget.
    proxy = QWidget()
    proxy.setAttribute(Qt.WA_StyledBackground, True)
    proxy.resize(width, height)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    proxy.render(image, QPoint(), QRegion(0, 0, width, height),
                 QWidget.DrawWindowBackground)

    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    state.mkdir(parents=True, exist_ok=True)
    target = state / "plasma-panel-surface.png"
    temporary = target.with_suffix(".new.png")
    if not image.save(str(temporary), "PNG"):
        return 1
    temporary.replace(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
