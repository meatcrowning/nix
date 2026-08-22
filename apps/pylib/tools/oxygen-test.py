#!/usr/bin/env python3
"""Harness for the widget style's own settings (pylib/oxygenstyle.py + the
`style*` half of deskstyle.py).

Offscreen, and it never reads the live `~/.config/oxygenrc` or `kdeglobals` —
every case points `DESK_OXYGENRC`, `DESK_KDEGLOBALS` and `DESK_SETTINGS` at a
temp dir, which is what those overrides exist for.

    <an app python> apps/pylib/tools/oxygen-test.py

(PySide6 is not in the bare python3 here: use an app wrapper's interpreter, e.g.
`painter-qtenv python3 apps/pylib/tools/oxygen-test.py`.)

Covers: that an absent rc resolves to upstream's compiled-in defaults rather
than to nothing; that a hand-edited nonsense value falls back instead of
reaching a QML binding; the two derived numbers Oxygen's own source computes
(the scrollbar button height, the expander triangle); that the animation master
switch and the per-kind flags zero the right durations; the gate — Plasma AND
Oxygen, so a Breeze session does not get dressed in Oxygen's metrics; and the
regression that matters most, that in a Hyprland session every one of these
properties is inert and nothing an app already drew has moved.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TMP = Path(tempfile.mkdtemp(prefix="oxygen-test-"))
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")

import oxygenstyle as O  # noqa: E402

fails = []


def check(label, ok):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        fails.append(label)


def env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)


def write_rc(text):
    p = TMP / "oxygenrc"
    p.write_text(text)
    env(DESK_OXYGENRC=p)
    return p


# A kdeglobals with nothing in it but the two keys the gate reads.
def write_kdeglobals(style="oxygen"):
    p = TMP / "kdeglobals"
    p.write_text(f"[KDE]\nwidgetStyle={style}\n"
                 "[General]\nfont=Oxygen-Sans,10,-1,5,50,0,0,0,0,0\n")
    env(DESK_KDEGLOBALS=p)
    return p


print("\n-- defaults, with no rc at all --")
env(DESK_OXYGENRC=TMP / "absent-oxygenrc")
ox = O.read_oxygen()
check("every key resolves", len(ox) == len(O._KEYS))
check("ScrollBarWidth is upstream's 15", ox["ScrollBarWidth"] == 15)
check("GenericAnimationsDuration is upstream's 150",
      ox["GenericAnimationsDuration"] == 150)
check("ViewDrawFocusIndicator is upstream's false",
      ox["ViewDrawFocusIndicator"] is False)
check("WindowDragMode is upstream's WD_FULL", ox["WindowDragMode"] == "WD_FULL")

print("\n-- a rc that says something --")
write_rc("[Style]\n"
         "ScrollBarWidth=21\n"
         "ScrollBarAddLineButtons=0\n"
         "ViewTriangularExpanderSize=TE_NORMAL\n"
         "GenericAnimationsDuration=400\n"
         "WindowDragMode=WD_MINIMAL\n"
         "ToolTipTransparent=false\n"
         "[Windeco]\nButtonSize=ButtonSmall\n")
ox = O.read_oxygen()
m = O.metrics(ox)
check("the int is read", ox["ScrollBarWidth"] == 21)
check("the enum is read", ox["WindowDragMode"] == "WD_MINIMAL")
check("the bool is read", ox["ToolTipTransparent"] is False)
check("a [Windeco] key is read alongside [Style]", ox["ButtonSize"] == "ButtonSmall")
check("a key the rc omits keeps its default",
      ox["MenuAnimationsDuration"] == 150)
# _singleButtonHeight = qMax(width * 7/10, 14) — kstyle/oxygenstyle.cpp:1788
check("scrollButtonHeight is Oxygen's own formula", m["scrollButtonHeight"] == 14)
check("a wider bar raises it", O.metrics({**ox, "ScrollBarWidth": 30})
      ["scrollButtonHeight"] == 21)
# genericArrow(): TE_NORMAL is a half-extent of 3.5 at a 1.6 pen
check("TE_NORMAL is a 7px triangle", m["expanderWidth"] == 7.0)
check("...at a 1.6 pen", m["expanderPen"] == 1.6)
check("0 add-line buttons survives", m["scrollAddButtons"] == 0)

print("\n-- a hand-edited rc cannot reach a binding --")
write_rc("[Style]\n"
         "ScrollBarWidth=wide\n"
         "WindowDragMode=WD_SOMETIMES\n"
         "ToolTipTransparent=maybe\n"
         "ViewTriangularExpanderSize=TE_ENORMOUS\n")
ox = O.read_oxygen()
check("a non-numeric int falls back", ox["ScrollBarWidth"] == 15)
check("an unknown enum member falls back", ox["WindowDragMode"] == "WD_FULL")
check("a non-boolean bool falls back", ox["ToolTipTransparent"] is True)
check("an unknown expander size still resolves to a triangle",
      O.metrics(ox)["expanderWidth"] == 5.0)

print("\n-- the animation switches --")
write_rc("[Style]\nAnimationsEnabled=false\n")
check("the master switch zeroes every duration",
      set(O.motion().values()) == {0})
write_rc("[Style]\nGenericAnimationsEnabled=false\nMenuAnimationsDuration=90\n")
mo = O.motion()
check("a per-kind flag zeroes only its own", mo["generic"] == 0 and mo["menu"] == 90)
write_rc("[Style]\nStackedWidgetTransitionsEnabled=true\n")
check("a transition off by default can be switched on",
      O.motion()["stack"] == 150)

print("\n-- the gate: Plasma AND Oxygen --")
write_rc("[Style]\nScrollBarWidth=21\n")
write_kdeglobals("oxygen")
env(DESK_SESSION="plasma")
check("plasma + oxygen", O.is_oxygen() is True)
write_kdeglobals("breeze")
check("plasma + breeze is not oxygen", O.is_oxygen() is False)
write_kdeglobals("oxygen")
env(DESK_SESSION="hypr")
check("hyprland is never oxygen", O.is_oxygen() is False)

print("\n-- DeskStyle publishes them --")
settings = TMP / "settings.json"
settings.write_text('{"fontFamily": "Botis 4x6", "fontSize": 17,'
                    ' "scrollbarStyle": "beveled", "animSpeed": 1.0}')
env(DESK_SETTINGS=settings)

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication(sys.argv)
import deskstyle  # noqa: E402

env(DESK_SESSION="plasma")
write_kdeglobals("oxygen")
d = deskstyle.DeskStyle()
check("plasma+oxygen: oxygen is true", d.oxygen is True)
check("plasma+oxygen: styleScrollWidth is the rc's", d.styleScrollWidth == 21)
check("plasma+oxygen: styleMs is the generic duration", d.styleMs == 150)
check("plasma+oxygen: styleExpanderWidth is a real number",
      d.styleExpanderWidth == 5.0)
check("plasma+oxygen: styleMnemonics is an enum member",
      d.styleMnemonics == "MN_ALWAYS")

write_rc("[Style]\nAnimationsEnabled=false\n")
d2 = deskstyle.DeskStyle()
check("plasma+oxygen: the style's animations-off arrives as reduceMotion",
      d2.reduceMotion is True and d2.styleMs == 0)

write_rc("[Style]\nScrollBarWidth=21\n")
write_kdeglobals("breeze")
d3 = deskstyle.DeskStyle()
check("plasma+breeze: no style numbers",
      d3.oxygen is False and d3.styleScrollWidth == 0 and d3.styleMs == 0)
check("plasma+breeze: the scrollbar is still flat", d3.scrollbarStyle == "flat")

env(DESK_SESSION="hypr")
write_kdeglobals("oxygen")
d4 = deskstyle.DeskStyle()
check("hypr: oxygen is false", d4.oxygen is False)
check("hypr: every style number is inert",
      (d4.styleMs, d4.styleMenuMs, d4.styleBusyMs, d4.styleScrollWidth,
       d4.styleScrollButtons, d4.styleExpanderWidth, d4.styleExpanderPen)
      == (0, 0, 0, 0, 0, 0.0, 0.0))
check("hypr: the string ones are empty, not a stale enum",
      d4.styleMnemonics == "" and d4.styleMenuHighlight == "")
check("hypr: the panel's own settings are untouched",
      d4.fontFamily == "Botis 4x6" and d4.fontSize == 17
      and d4.scrollbarStyle == "beveled")

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
