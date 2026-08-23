#!/usr/bin/env python3
"""Measure Oxygen's real scrollbar, so `pylib/scrollcss.py` imitates it instead
of guessing at it.

A web page cannot hand its scrollbar to `QStyle` (Chromium paints its own in
Aura, never asking Qt or GTK), so the Plasma face of that module is the one
place on this desktop where a control is DRAWN rather than delegated. Every
ratio in it comes from here: this renders a real `QScrollBar` under the live
Oxygen style **offscreen** and prints the colour ladder down its middle, for
several colour schemes, plus the arrow bitmaps.

Offscreen and self-contained — `QT_QPA_PLATFORM=offscreen` with
`WAYLAND_DISPLAY`/`DISPLAY` cleared, a palette built in-process, nothing read
from his session and no window anywhere near his screen.

    apps/pylib/tools/oxygen-scrollbar-probe.py            # the ladder + the ratios
    apps/pylib/tools/oxygen-scrollbar-probe.py --arrows   # the stepper bitmaps

Needs PySide6, so run it through an app's Qt env: `player-qtenv python3 …`.

What it established (2026-08-23, Oxygen 6.7, six schemes from window lightness
0.06 to 1.0), and what scrollcss.py therefore encodes:

  * the bar is `ScrollBarWidth + 2` wide: 2px of window either side of a 1px
    darker groove border,
  * the groove is the window colour with its HLS lightness MULTIPLIED by ~0.845
    — a constant DELTA fits none of the six schemes, because Oxygen shades in
    HCY and compresses as the scheme darkens,
  * below ~0.08 window lightness that shade gives up and returns something
    LIGHTER than the window, which is why scrollcss has a floor branch,
  * the slider carries the BUTTON group's colour (not View/base) as a gradient
    from x0.99 to x0.93, with a 1px rim at x1.25 and a brighter top line,
  * the steppers are hollow chevrons on the bare window — no slab under them —
    inked with the FULL foreground, and their count is `oxygenrc`'s
    (`ScrollBarSubLineButtons` above, `ScrollBarAddLineButtons` below).
"""
from __future__ import annotations

import argparse
import colorsys
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"      # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)          # no way back to his session
os.environ.pop("DISPLAY", None)

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QColor, QPalette                       # noqa: E402
from PySide6.QtWidgets import (QApplication, QScrollBar,         # noqa: E402
                               QStyleFactory, QVBoxLayout, QWidget)

# window, button, foreground — six schemes spanning the lightness range.
SCHEMES = (("#efefef", "#efefef", "#202020"),
           ("#ffffff", "#f5f5f5", "#101010"),
           ("#808080", "#909090", "#101010"),
           ("#2a2a2e", "#3a3a3e", "#e0e0e0"),
           ("#221e18", "#2f2b23", "#ffe9d8"),
           ("#101010", "#1a1a1a", "#e0e0e0"))


def lum(name):
    c = QColor(name)
    return colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())[1]


def render(app, win, btn, fg, height=300):
    p = QPalette()
    for grp in (QPalette.Active, QPalette.Inactive):
        for role, col in ((QPalette.Window, win), (QPalette.Button, btn),
                          (QPalette.Base, win)):
            p.setColor(grp, role, QColor(col))
        for role in (QPalette.WindowText, QPalette.ButtonText, QPalette.Text):
            p.setColor(grp, role, QColor(fg))
    app.setPalette(p)
    w = QWidget()
    w.setPalette(p)
    w.setAutoFillBackground(True)
    w.resize(60, height)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(20, 0, 20, 0)
    sb = QScrollBar(Qt.Vertical)
    sb.setPalette(p)
    sb.setRange(0, 100)
    sb.setValue(50)
    sb.setPageStep(20)
    lay.addWidget(sb)
    w.show()
    app.processEvents()
    app.processEvents()
    # `w` comes back with them: it owns `sb`, and letting it fall out of scope
    # takes the C++ scrollbar with it before the caller can read its geometry.
    return sb, w.grab().toImage(), w


def ladder(app):
    print("%-9s %-9s | %-9s %-6s | %-9s %-9s %-6s" %
          ("window", "button", "groove", "ratio", "sliderTop", "sliderBot", "ratio"))
    for win, btn, fg in SCHEMES:
        sb, img, _owner = render(app, win, btn, fg)
        x = sb.x() + sb.width() // 2
        col = [img.pixelColor(x, y).name() for y in range(sb.y(), sb.y() + sb.height())]
        from collections import Counter
        groove = Counter(col[30:-30]).most_common(1)[0][0]
        # The slider's FILL, not its rim: drop the groove rows and the few
        # bright/dark edge rows either end of the run.
        band = [c for c in col[100:170] if c != groove]
        band = band[4:-4] if len(band) > 12 else band
        top, bot = (band[0], band[-1]) if band else (btn, btn)
        print("%-9s %-9s | %-9s %-6.3f | %-9s %-9s %-6.3f" %
              (win, btn, groove, lum(groove) / max(1e-6, lum(win)),
               top, bot, lum(bot) / max(1e-6, lum(btn))))


def arrows(app):
    win, btn, fg = SCHEMES[4]
    sb, img, _owner = render(app, win, btn, fg)
    base = QColor(win)
    x0, wd = sb.x(), sb.width()
    print("bar x=%d width=%d height=%d (ScrollBarWidth + 2 margins)"
          % (x0, wd, sb.height()))
    for y in range(sb.y(), sb.y() + sb.height()):
        row = ""
        for x in range(x0, x0 + wd):
            c = img.pixelColor(x, y)
            near = (abs(c.red() - base.red()) + abs(c.green() - base.green())
                    + abs(c.blue() - base.blue()))
            row += "#" if near > 90 else "."
        if "#" in row:
            print("%3d %s" % (y, row))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arrows", action="store_true",
                    help="print the stepper bitmaps instead of the ladder")
    a = ap.parse_args()
    app = QApplication(sys.argv)
    style = QStyleFactory.create("oxygen")
    if style is None:
        raise SystemExit("no Oxygen style plugin in this Qt env — "
                         "run me through an app's wrapper (player-qtenv python3 ...)")
    app.setStyle(style)
    (arrows if a.arrows else ladder)(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
