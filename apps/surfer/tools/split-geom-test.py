#!/usr/bin/env python3
"""Headless check of surfer's split-view GEOMETRY — `apps/surfer/tools/split-geom-test.py`.

The companion to `split-test.py`, which drives the hyprvtb button socket and can
therefore assert *behaviour* (which tab is in which pane, what each button does)
but never sees a rect. This one asserts the rects.

It does NOT reimplement the layout: it lifts the split-view property block
straight out of `qml/Main.qml` — everything from `property bool splitOn` to the
last `paneB*` line — and instantiates just that inside a bare `Item`, offscreen.
So the numbers checked here are the ones the window actually uses, and the
extraction failing loudly is the only way this can go stale.

What it proves, on BOTH axes:
  * split off  -> pane A is the whole window
  * `|` on     -> A and B side by side, divider between them, no overlap
  * `_` on     -> A and B stacked, ditto
  * re-orienting keeps the same splitRatio (so the proportion survives)
  * the ratio clamps at both ends, and NO rect is ever zero-size — including in
    a window too small for two minimum panes, which is exactly how you would
    otherwise hand the compositor a degenerate box (see apps/AGENTS.md).

Run it after touching the split-view block. No window, no screen, no network.
"""
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_QML = HERE.parent / "qml" / "Main.qml"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# A bare `python3` on top is not the interpreter surfer runs under and has no
# PySide6; the packaged wrapper names the one that does, so re-exec into it
# rather than making the caller know the store path.
try:
    import PySide6  # noqa: F401
except ImportError:
    wrapper = shutil.which("surfer")
    py = None
    if wrapper:
        m = re.search(r"(/nix/store/\S+?/bin/python3)",
                      Path(os.path.realpath(wrapper)).read_text(errors="replace"))
        py = m.group(1) if m else None
    if not py or os.environ.get("_SURFER_GEOM_REEXEC"):
        raise SystemExit("no PySide6, and no surfer wrapper to borrow one from")
    os.environ["_SURFER_GEOM_REEXEC"] = "1"
    os.execv(py, [py, str(Path(__file__).resolve())] + sys.argv[1:])

from PySide6.QtCore import QUrl                       # noqa: E402
from PySide6.QtGui import QGuiApplication             # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine   # noqa: E402


def extract_block(text):
    """The split-view geometry declarations, verbatim from Main.qml."""
    start = re.search(r"^ *property bool splitOn:", text, re.M)
    end = re.search(r"^ *readonly property int paneBH:.*$", text, re.M)
    if not start or not end:
        raise SystemExit("could not find the split-view property block in %s — "
                         "if it was renamed, update this harness" % MAIN_QML)
    return text[start.start():end.end()]


BLOCK = extract_block(MAIN_QML.read_text(encoding="utf-8"))

app = QGuiApplication(sys.argv)
engine = QQmlEngine()
comp = QQmlComponent(engine)
comp.setData(("import QtQuick\nItem { id: win\n%s\n}\n" % BLOCK).encode(),
             QUrl("qrc:/splitgeom.qml"))
item = comp.create()
if item is None:
    raise SystemExit("QML would not compile:\n" + "\n".join(
        e.toString() for e in comp.errors()))

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def setup(w, h, on=True, vertical=True, ratio=0.5):
    item.setProperty("width", w)
    item.setProperty("height", h)
    item.setProperty("splitOn", on)
    item.setProperty("splitVertical", vertical)
    item.setProperty("splitRatio", ratio)
    g = {k: item.property(k) for k in
         ("paneAX", "paneAY", "paneAW", "paneAH",
          "paneBX", "paneBY", "paneBW", "paneBH",
          "paneALen", "paneBOff", "paneBLen", "splitterW")}
    return g


def nonzero(g):
    return g["paneAW"] > 0 and g["paneAH"] > 0 and g["paneBW"] > 0 and g["paneBH"] > 0


W, H = 1200, 800

# --- split off: one pane, the whole window ---
g = setup(W, H, on=False)
check("split off: pane A fills the window",
      (g["paneAX"], g["paneAY"], g["paneAW"], g["paneAH"]) == (0, 0, W, H), str(g))

# --- vertical (|): side by side ---
g = setup(W, H, vertical=True, ratio=0.5)
check("| A is the leading slice", g["paneAX"] == 0 and g["paneAY"] == 0 and g["paneAH"] == H)
check("| B is to the right of the divider",
      g["paneBX"] == g["paneAW"] + g["splitterW"] and g["paneBY"] == 0 and g["paneBH"] == H, str(g))
check("| the two panes plus the divider fill the width",
      g["paneAW"] + g["splitterW"] + g["paneBW"] == W, str(g))
check("| no overlap", g["paneAW"] <= g["paneBX"], str(g))
check("| no zero-size rect", nonzero(g), str(g))
check("| an even ratio is even", abs(g["paneAW"] - g["paneBW"]) <= 1, str(g))
vert_half = g["paneAW"]

# --- horizontal (_): stacked ---
g = setup(W, H, vertical=False, ratio=0.5)
check("_ A is the top slice", g["paneAX"] == 0 and g["paneAY"] == 0 and g["paneAW"] == W)
check("_ B is below the divider",
      g["paneBY"] == g["paneAH"] + g["splitterW"] and g["paneBX"] == 0 and g["paneBW"] == W, str(g))
check("_ the two panes plus the divider fill the height",
      g["paneAH"] + g["splitterW"] + g["paneBH"] == H, str(g))
check("_ no overlap", g["paneAH"] <= g["paneBY"], str(g))
check("_ no zero-size rect", nonzero(g), str(g))
check("_ an even ratio is even", abs(g["paneAH"] - g["paneBH"]) <= 1, str(g))

# --- one ratio, both axes: re-orienting keeps the proportion ---
r = 0.3
gv = setup(W, H, vertical=True, ratio=r)
gh = setup(W, H, vertical=False, ratio=r)
check("re-orienting keeps the proportion",
      abs(gv["paneAW"] / W - gh["paneAH"] / H) < 0.01,
      "%.3f vs %.3f" % (gv["paneAW"] / W, gh["paneAH"] / H))
check("re-orienting is not a reset", gv["paneAW"] != vert_half)

# --- the ratio clamps at both ends, on each axis ---
for vertical, axis, alen, blen in ((True, W, "paneAW", "paneBW"),
                                   (False, H, "paneAH", "paneBH")):
    tag = "|" if vertical else "_"
    for ratio in (-5.0, 0.0, 0.001, 0.999, 1.0, 42.0):
        g = setup(W, H, vertical=vertical, ratio=ratio)
        check("%s ratio %.3f keeps both panes >= 1px" % (tag, ratio), nonzero(g), str(g))
        check("%s ratio %.3f still fills the axis" % (tag, ratio),
              g[alen] + g["splitterW"] + g[blen] == axis, str(g))
        check("%s ratio %.3f leaves a usable minimum pane" % (tag, ratio),
              min(g[alen], g[blen]) >= 100, str(g))

# --- a window too small for two minimum panes must STILL not produce a
#     zero-size rect (a degenerate box aborts the compositor) ---
for w, h in ((200, 150), (40, 40), (8, 8), (1, 1), (0, 0)):
    for vertical in (True, False):
        for ratio in (0.08, 0.5, 0.92):
            g = setup(w, h, vertical=vertical, ratio=ratio)
            check("tiny window %dx%d %s r=%.2f: no zero-size rect"
                  % (w, h, "|" if vertical else "_", ratio), nonzero(g), str(g))

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
