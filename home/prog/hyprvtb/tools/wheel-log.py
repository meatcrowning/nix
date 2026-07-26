#!/usr/bin/env python3
"""wheel-log — a window that prints one TSV row per wheel event.

The wet-end oracle for the kinetic-scroll harness (kinetic-test.sh, and the
mid-flight swap case in hotswap-test.sh). A bare QWidget on purpose, not QML:
the fewer layers between wl_pointer.axis and the printed row, the less the
oracle can lie.

`phase` is the load-bearing column. QtWayland opens a ScrollBegin/Update/End
phase sequence ONLY for axis_source_finger (isDefinitelyTerminated is
`return src == 1`), so a missing ScrollBegin means the compositor emitted
CONTINUOUS instead of FINGER — the one mistake the reference plugin makes.

Columns (tab separated, one line per event, flushed):
    monotonic_ms  pixelDelta.x  pixelDelta.y  angleDelta.x  angleDelta.y
    phase  inverted
`source` is deliberately absent: Qt6's QWheelEvent has no wayland axis source.
NB pixelDelta is an integer QPoint, so a sub-pixel tail delta rounds to 0 here
while angleDelta (x12) survives — read both before calling a row "a zero".

Run under Fedora's /usr/bin/python3 (python3-pyside6) on book.
Usage: python3 wheel-log.py [out.tsv]      (default: stdout)
"""

import sys
import time

from PySide6.QtWidgets import QApplication, QWidget

PHASES = {0: "NoScrollPhase", 1: "ScrollBegin", 2: "ScrollUpdate", 3: "ScrollEnd", 4: "ScrollMomentum"}


class WheelLog(QWidget):
    def __init__(self, out):
        super().__init__()
        self.out = out
        self.setWindowTitle("wheel-log")
        self.resize(900, 700)

    def wheelEvent(self, ev):
        ph = ev.phase()
        name = getattr(ph, "name", None) or PHASES.get(getattr(ph, "value", ph), str(ph))
        p, a = ev.pixelDelta(), ev.angleDelta()
        self.out.write(
            "%d\t%d\t%d\t%d\t%d\t%s\t%d\n"
            % (time.monotonic() * 1000, p.x(), p.y(), a.x(), a.y(), name, 1 if ev.inverted() else 0)
        )
        self.out.flush()
        ev.accept()


def main():
    app = QApplication(sys.argv)
    # app_id/class: QtWayland takes it from desktopFileName, else from the
    # binary's name — which here would be "python3". The harness matches on it.
    app.setApplicationName("wheel-log")
    app.setDesktopFileName("wheel-log")
    out = open(sys.argv[1], "a", buffering=1) if len(sys.argv) > 1 else sys.stdout
    w = WheelLog(out)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
