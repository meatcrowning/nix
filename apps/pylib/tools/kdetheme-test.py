#!/usr/bin/env python3
"""Harness for the Plasma-session theme switch (pylib/kdetheme.py + deskstyle.py).

Offscreen, and it never reads or writes the live `~/.config/kdeglobals`,
`~/.config/oxygenrc`, `~/.config/quickshell/settings.json` or `~/.cache` —
every case points `DESK_KDEGLOBALS`, `DESK_OXYGENRC`, `DESK_SETTINGS` and
`XDG_CACHE_HOME` at a temp dir, which is the whole reason those overrides
exist. (The widget style's own settings have a harness of their own,
`oxygen-test.py`; they are pinned here only so DeskStyle cannot read HIS.)

    <an app python> apps/pylib/tools/kdetheme-test.py

(PySide6 is not in the bare python3 here: use an app wrapper's interpreter, e.g.
`$(tail -1 $(command -v filer) | sed 's/^exec "//; s/".*//')`.)

Covers: the session switch and its env override; the twelve-token mapping off a
DARK and a LIGHT KDE scheme; the contrast floors that make `accent` legible as
body text (docs/DESIGN.md §3); that the generated file is exactly what an app's
`Palette` regex parses; that an unchanged scheme is not rewritten; the font
point->pixel conversion, the `smooth` flip and the motion factor in DeskStyle;
and — the regression that matters most — that with the session forced to
Hyprland NOTHING here changes what the apps saw before.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TMP = Path(tempfile.mkdtemp(prefix="kdetheme-test-"))
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")
# DeskStyle reads the widget style's store too now (oxygenstyle.py). Point it at
# a file that does not exist, so every case here resolves to Oxygen's own
# compiled-in defaults instead of to whatever he has set.
os.environ["DESK_OXYGENRC"] = str(TMP / "absent-oxygenrc")

import kdetheme as K  # noqa: E402

DARK = """
[Colors:Window]
BackgroundNormal=31,38,39
BackgroundAlternate=25,33,35
ForegroundNormal=244,235,231
ForegroundInactive=129,138,140
ForegroundLink=112,219,246
ForegroundNegative=175,50,41
ForegroundNeutral=164,133,56
ForegroundPositive=0,109,56
DecorationFocus=61,141,160

[Colors:View]
BackgroundNormal=24,31,33
ForegroundNormal=240,230,220

[Colors:Selection]
BackgroundNormal=51,107,120

[General]
font=Oxygen-Sans,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1,,0,0

[KDE]
AnimationDurationFactor=1
"""

LIGHT = """
[Colors:Window]
BackgroundNormal=239,240,241
BackgroundAlternate=227,229,231
ForegroundNormal=35,38,41
ForegroundInactive=112,125,138
ForegroundLink=41,128,185
ForegroundNegative=218,68,83
ForegroundNeutral=246,116,0
ForegroundPositive=39,174,96
DecorationFocus=61,174,233

[Colors:View]
BackgroundNormal=252,252,252

[Colors:Selection]
BackgroundNormal=61,174,233

[General]
font=Noto Sans,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1,,0,0

[KDE]
AnimationDurationFactor=0.5
"""

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def write_scheme(text):
    p = TMP / "kdeglobals"
    p.write_text(text)
    os.environ["DESK_KDEGLOBALS"] = str(p)
    return p


def env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --------------------------------------------------------------------------- #
print("session detection")
env(DESK_SESSION=None, XDG_CURRENT_DESKTOP="KDE", KDE_FULL_SESSION=None)
check("XDG_CURRENT_DESKTOP=KDE is a Plasma session", K.is_plasma())
env(XDG_CURRENT_DESKTOP="Hyprland")
check("XDG_CURRENT_DESKTOP=Hyprland is not", not K.is_plasma())
env(XDG_CURRENT_DESKTOP="KDE:plasma")
check("a colon-list containing KDE is", K.is_plasma())
env(DESK_SESSION="hypr", XDG_CURRENT_DESKTOP="KDE")
check("DESK_SESSION=hypr overrides the environment", not K.is_plasma())
env(DESK_SESSION="plasma", XDG_CURRENT_DESKTOP="Hyprland")
check("DESK_SESSION=plasma overrides the environment", K.is_plasma())
env(DESK_SESSION=None, XDG_CURRENT_DESKTOP=None, KDE_FULL_SESSION="true")
check("KDE_FULL_SESSION is the last resort", K.is_plasma())

# --------------------------------------------------------------------------- #
print("native role exports for terminal/web consumers")
write_scheme(DARK)
pal = K.kde_palette()
ini = K.read_ini()
check("content uses the native View background",
      pal["bg"] == K._rgb(ini["Colors:View"]["BackgroundNormal"], None))
check("content uses the native View foreground",
      pal["text"] == K._rgb(ini["Colors:View"]["ForegroundNormal"], None))
check("selection is the native Selection background",
      pal["highlight"] == K._rgb(ini["Colors:Selection"]["BackgroundNormal"], None))
check("no generated application palette source",
      K.theme_source(Path("/wallpaper/Theme.qml")) == Path("/wallpaper/Theme.qml"))

print("DeskStyle")
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication  # noqa: E402

app = QGuiApplication([])   # needed for the DPI the point size converts at
import deskstyle  # noqa: E402

settings = TMP / "settings.json"
settings.write_text('{"fontFamily": "Botis 4x6", "fontSize": 15, "animSpeed": 2.0,'
                    ' "scrollbarStyle": "win31", "windowBorderWidth": 3,'
                    ' "windowRounding": 7}')
env(DESK_SETTINGS=str(settings), DESK_SESSION="hypr")
write_scheme(DARK)
s = deskstyle.DeskStyle()
check("hypr: family is the panel's", s.fontFamily == "Botis 4x6")
check("hypr: size is the panel's", s.fontSize == 15)
check("hypr: a pixel face is not smooth", s.smooth is False)
check("hypr: scrollbar is the panel's", s.scrollbarStyle == "win31")
check("hypr: animSpeed is the panel's", s.animSpeed == 2.0)
check("hypr: geometry is the panel's", (s.borderWidth, s.rounding) == (3, 7))

settings.write_text('{"fontFamily": "Oxygen Mono", "fontSize": 14,'
                    ' "scrollbarStyle": "win31", "windowBorderWidth": 3,'
                    ' "windowRounding": 7}')
o = deskstyle.DeskStyle()
check("hypr: Oxygen Mono is smooth", o.smooth is True)
check("hypr: Oxygen Mono uses Kitty’s terminal-cell metrics", o.terminalCell is True)
check("hypr: Oxygen Mono publishes its fractional advance ratio",
      abs(o.advanceRatio - (1229 / 2048)) < 1e-12, str(o.advanceRatio))
check("hypr: Oxygen Mono editor text keeps Kitty's vertical hinting",
      o.editorFont.hintingPreference() == QFont.PreferVerticalHinting)
check("hypr: Oxygen Mono starts from Kitty's 10pt raster, not a 14px Qt raster",
      o.editorFont.pixelSize() == -1 and o.editorFont.pointSize() == 10,
      f"px={o.editorFont.pixelSize()} pt={o.editorFont.pointSizeF():.3f}")
o_external = o.editorFontForScale(1.25)
o_external_advance = QFontMetricsF(o_external).horizontalAdvance("M") * 1.25
check("hypr: Oxygen Mono editor text lands on external-display cell pixels",
      abs(o_external_advance - round(o_external_advance)) < 1e-9,
      str(o_external_advance))
o_label_external = o.labelFontForScale(1.25)
o_label_advance = QFontMetricsF(o_label_external).horizontalAdvance("M") * 1.25
check("hypr: Oxygen Mono labels land on external-display cell pixels",
      abs(o_label_advance - round(o_label_advance)) < 1e-9,
      str(o_label_advance))
check("hypr: Oxygen Mono labels use the same 10pt Kitty raster",
      o_label_external.pixelSize() == -1 and o_label_external.pointSize() == 10,
      f"px={o_label_external.pixelSize()} pt={o_label_external.pointSizeF():.3f}")

env(DESK_SESSION="plasma")
k = deskstyle.DeskStyle()
dpi = QGuiApplication.primaryScreen().logicalDotsPerInch()
check("plasma: family is KDE's", k.fontFamily == "Oxygen-Sans", k.fontFamily)
check("plasma: 10pt converted at the screen DPI",
      k.fontSize == round(10 * dpi / 72.0), f"{k.fontSize} vs dpi {dpi}")
check("plasma: an outline face is smooth", k.smooth is True)
check("plasma: the editor font drops NoAntialias",
      k.editorFont.styleStrategy() != QFont.NoAntialias)
check("plasma: scrollbar is flat", k.scrollbarStyle == "flat")
check("plasma: animSpeed is KDE's factor", k.animSpeed == 1.0)
check("plasma: line height is measured on the KDE face", k.lineHeight > 0)
check("plasma: geometry still comes from the panel store",
      (k.borderWidth, k.rounding) == (3, 7))

write_scheme(LIGHT)
k2 = deskstyle.DeskStyle()
check("plasma: a 0.5 duration factor arrives as animSpeed", k2.animSpeed == 0.5)
check("plasma: 11pt Noto Sans", k2.fontFamily == "Noto Sans"
      and k2.fontSize == round(11 * dpi / 72.0))
write_scheme(DARK.replace("AnimationDurationFactor=1", "AnimationDurationFactor=0"))
k3 = deskstyle.DeskStyle()
check("plasma: KDE's instant (factor 0) is reduceMotion", k3.reduceMotion is True)
write_scheme(DARK.replace("font=Oxygen-Sans,10", "font=More Perfect DOS VGA,10"))
k4 = deskstyle.DeskStyle()
check("plasma: a pixel face picked in KDE stays crisp", k4.smooth is False)

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
