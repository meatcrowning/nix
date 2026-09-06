#!/usr/bin/env python3
"""The styled background follows the WINDOW's state, not the proxy's guess.

`kdeshell` draws the KStyle's window background inside the QQuickWidget from an
image a proxy top-level QWidget renders. That proxy is never a window on
screen, so Qt picks its colour group on its own — and with an inactive colour
effect on (`[ColorEffects:Inactive] Enable=true`, which his scheme has) the
chrome the style paints and the crop the QML draws came from two different
tones the moment the window lost focus. That is the state a "select window"
screenshot captures, and it is why the titlebar looked disconnected from the
window in one [his, 2026-08-23].

So: the URL carries `a`/`i`, the proxy is dressed in that group's colours, and
losing focus re-requests the image. Palettes are SET here rather than read from
his scheme, so the test means the same thing on a machine themed any way at
all.

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

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


app = kdeshell.make_app([sys.argv[0]], "kdebg-state-test")
from PySide6.QtCore import QEvent, Qt                                # noqa: E402
from PySide6.QtGui import QColor, QPalette                           # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget     # noqa: E402

# Two unmistakable tones, so what the crop used is readable off one pixel.
ACTIVE, INACTIVE = QColor(20, 120, 200), QColor(200, 60, 20)
pal = QPalette(app.palette())
pal.setColor(QPalette.Active, QPalette.Window, ACTIVE)
pal.setColor(QPalette.Inactive, QPalette.Window, INACTIVE)
app.setPalette(pal)

prov_cls, bg_cls = kdeshell._build_background_classes()
prov = prov_cls()


def crop_top(url):
    img = prov.requestImage(url, None, None)
    return img.pixelColor(3, 0).getRgb()[:3] if not img.isNull() else None


act = crop_top("400,300,0,40,400,260,1,a#1")
ina = crop_top("400,300,0,40,400,260,1,i#2")
check("the two states render differently", act is not None and act != ina,
      "%s vs %s" % (act, ina))


def near(c, ref, slack=90):
    """A KStyle gradients the base colour, so compare by dominant channel."""
    return c is not None and max(range(3), key=lambda i: c[i]) == \
        max(range(3), key=lambda i: ref.getRgb()[i])


check("the active crop is drawn from the ACTIVE group", near(act, ACTIVE),
      str(act))
check("the inactive crop is drawn from the INACTIVE group", near(ina, INACTIVE),
      str(ina))
check("a URL with no state field still works (and reads as active)",
      crop_top("400,300,0,40,400,260,1#3") == act)
check("a malformed URL is an empty image, not a crash",
      prov.requestImage("nonsense#4", None, None).isNull())

# ---- the URL says which state, and focus changes re-request it ------------
win = QMainWindow()
win.resize(400, 300)
view = QWidget()
win.setCentralWidget(view)
win.show()
app.processEvents()

bg = bg_cls(view, win)
seen = []
bg.changed.connect(lambda: seen.append(1))
url = bg.property("source")
check("the URL carries the window's state",
      url.split("#")[0].split(",")[-1] in ("a", "i"), url)
before = len(seen)
app.sendEvent(win, QEvent(QEvent.WindowDeactivate))
check("losing focus re-requests the image", len(seen) > before,
      "%d -> %d" % (before, len(seen)))
before = len(seen)
app.sendEvent(view, QEvent(QEvent.Show))
check("showing the final view geometry re-requests the image", len(seen) > before,
      "%d -> %d" % (before, len(seen)))
before = len(seen)
app.sendEvent(win, QEvent(QEvent.ApplicationPaletteChange))
check("...and so does a scheme change", len(seen) > before)

# ---- a QQuickWidget's palette follows the desktop's -----------------------
# The view is handed the palette once, at construction; the app object hearing
# ApplicationPaletteChange is what keeps that from going stale when the scheme
# moves under a running app.
from PySide6.QtQuickWidgets import QQuickWidget                      # noqa: E402

qv = QQuickWidget()
qv.setPalette(QApplication.palette())
kdeshell._palette_view_lists.append([qv])
NEW = QColor(10, 200, 90)
pal2 = QPalette(app.palette())
pal2.setColor(QPalette.Active, QPalette.Window, NEW)
pal2.setColor(QPalette.Inactive, QPalette.Window, NEW)
app.setPalette(pal2)
app.processEvents()
got = qv.palette().color(QPalette.Active, QPalette.Window).getRgb()[:3]
check("a scheme change re-dresses the QML view", got == NEW.getRgb()[:3],
      str(got))
# `clearColor` has no getter in PySide6, so the assertion is that setting it
# was ATTEMPTED with the new colour: a stub records the call.
calls = []
qv.setClearColor = lambda c: calls.append(c.getRgb()[:3])
pal3 = QPalette(app.palette())
LAST = QColor(240, 10, 120)
pal3.setColor(QPalette.Active, QPalette.Window, LAST)
pal3.setColor(QPalette.Inactive, QPalette.Window, LAST)
app.setPalette(pal3)
app.processEvents()
check("...and its clear colour with it", calls[-1:] == [LAST.getRgb()[:3]],
      str(calls))

# ...and it does it WITHOUT an application-wide event filter. One of those runs
# a Python function for every event in the program, including the QChildEvent a
# QObject sends from inside its own constructor, and PySide segfaulted tearing
# down the wrapper it had to build for that half-constructed object — chatter
# died in `PyObject_ClearWeakRefs` whenever the prompt box was clicked
# (2026-08-23). The app object's own `event` sees only what is sent to it.
src = (Path(kdeshell.__file__)).read_text()
check("no application-wide event filter", "instance().installEventFilter" not in src)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
