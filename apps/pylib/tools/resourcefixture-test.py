#!/usr/bin/env python3
"""Seat-free protocol test for pylib.resourcefixture."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QTimer
from resourcefixture import ResourceFixture

app = QCoreApplication(sys.argv)
control_r, control_w = os.pipe()
ready_r, ready_w = os.pipe()
seen = []
fixture = ResourceFixture(app, {"normal": lambda: seen.append("normal"),
                                "stress": lambda: seen.append("stress")},
                          settle_ms=0, control_fd=control_r, ready_fd=ready_w)

QTimer.singleShot(10, lambda: os.write(control_w, b"stress\n"))
QTimer.singleShot(30, lambda: os.write(control_w, b"quit\n"))
QTimer.singleShot(2000, app.quit)
app.exec()
os.close(ready_w)
out = os.read(ready_r, 4096).decode()
assert seen == ["normal", "stress"], seen
assert "READY normal" in out and "READY stress" in out, out
print("resourcefixture: protocol ok")
