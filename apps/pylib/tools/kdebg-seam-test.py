#!/usr/bin/env python3
"""The styled background under the view continues the chrome's gradient.

A Plasma window of ours is native chrome (titlebar, toolbar, statusbar) around
a QQuickWidget, and the thing that makes it read as ONE window is Oxygen's
window background running unbroken from the decoration down behind the content
(apps/qmlcommon/StyledBackground.qml).  The QML half of that surface is an
image the style renders for us, so it is only unbroken while it is rendered
from the same colour ROLE the chrome uses.

Dressing the render in Base instead — the View role, reasonable-sounding for
"content" — starts a second, darker gradient at the view's top edge and draws a
hard seam straight across the window, on every light scheme where View and
Window differ (his: 184,212,216 against 198,221,224).  It is invisible on a
dark scheme, where `mint()` makes the two equal.  So the palette here is SET,
and light, rather than read from whatever scheme is live.

Offscreen and windowless — nothing reaches his session.
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DESK_SESSION"] = "plasma"
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
for _k in ("WAYLAND_DISPLAY", "DISPLAY"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kdeshell                                                     # noqa: E402

app = kdeshell.make_app([sys.argv[0]], "kdebg-seam-test")
from PySide6.QtCore import QPoint, Qt                                # noqa: E402
from PySide6.QtGui import QColor, QImage, QPalette, QRegion          # noqa: E402
from PySide6.QtWidgets import QWidget                                # noqa: E402

WINDOW, VIEW = QColor(198, 221, 224), QColor(184, 212, 216)
pal = QPalette(app.palette())
for _g in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
    pal.setColor(_g, QPalette.Window, WINDOW)
    pal.setColor(_g, QPalette.Base, VIEW)
app.setPalette(pal)

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


W, H, OFF = 630, 900, 100      # a chatter-shaped window; the view starts at OFF
provider_cls, _ = kdeshell._build_background_classes()
crop = provider_cls().requestImage(f"{W},{H},0,{OFF},{W},{H - OFF},1,a#1",
                                   None, None)

# What the native chrome above the view paints: the same style, the app palette.
proxy = QWidget()
proxy.setAttribute(Qt.WA_StyledBackground, True)
proxy.setPalette(kdeshell._group_palette(QPalette.Active))
proxy.resize(W, H)
chrome = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
chrome.fill(0)
proxy.render(chrome, QPoint(), QRegion(0, 0, W, H), QWidget.DrawWindowBackground)

# Away from the radial splash, so the comparison is the vertical gradient.
above = chrome.pixelColor(W - 6, OFF - 1).getRgb()[:3]
below = crop.pixelColor(W - 6, 0).getRgb()[:3]
check("no seam where the view meets the chrome",
      max(abs(a - b) for a, b in zip(above, below)) <= 1,
      "%s above, %s below" % (above, below))

# ...and it is the gradient continuing, not a flat fill of the right colour.
top, bottom = crop.pixelColor(W - 6, 0).getRgb()[:3], \
    crop.pixelColor(W - 6, crop.height() - 1).getRgb()[:3]
check("the crop still carries the gradient", top != bottom,
      "%s to %s" % (top, bottom))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
