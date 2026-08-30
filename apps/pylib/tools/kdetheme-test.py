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

# The literal regex apps/*/main.py's Palette uses. Kept verbatim: this test
# exists partly to prove the generated file is readable BY THAT, not by a
# parser written alongside it.
PALETTE_RE = re.compile(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"')

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
print("dark scheme -> the twelve tokens")
write_scheme(DARK)
pal = K.kde_palette()
check("every token is present", pal is not None and set(pal) == set(K.KEYS))
check("bg is the window background", K._hex(pal["bg"]) == "#1f2627")
check("bgAlt is the view background", K._hex(pal["bgAlt"]) == "#181f21")
check("text is the window foreground", K._hex(pal["text"]) == "#f4ebe7")
check("highlight is the selection background", K._hex(pal["highlight"]) == "#336b78")
check("accent clears the body-text floor",
      K._ratio(pal["accent"], pal["bg"]) >= K.TEXT_RATIO,
      f"{K._hex(pal['accent'])} vs {K._hex(pal['bg'])} = {K._ratio(pal['accent'], pal['bg']):.2f}")
for k in ("ok", "warn", "crit", "info"):
    check(f"{k} clears the status floor",
          K._ratio(pal[k], pal["bg"]) >= K.STATUS_RATIO,
          f"{K._hex(pal[k])} = {K._ratio(pal[k], pal['bg']):.2f}")
check("ok was LIFTED off Oxygen's unreadable 0,109,56",
      pal["ok"] != (0, 109, 56) and K._ratio((0, 109, 56), pal["bg"]) < K.STATUS_RATIO)
check("border sits between the surface and the text",
      K._lum(pal["bg"]) < K._lum(pal["border"]) < K._lum(pal["text"]))

print("light scheme -> the same twelve, other polarity")
write_scheme(LIGHT)
lp = K.kde_palette()
check("bg is light", K._lum(lp["bg"]) > 0.5)
check("accent clears the body-text floor on white",
      K._ratio(lp["accent"], lp["bg"]) >= K.TEXT_RATIO,
      f"{K._hex(lp['accent'])} = {K._ratio(lp['accent'], lp['bg']):.2f}")
check("accent was DARKENED, not lifted", K._lum(lp["accent"]) < K._lum((61, 174, 233)))
for k in ("ok", "warn", "crit", "info"):
    check(f"{k} clears the status floor on white",
          K._ratio(lp[k], lp["bg"]) >= K.STATUS_RATIO,
          f"{K._hex(lp[k])} = {K._ratio(lp[k], lp['bg']):.2f}")
check("border sits between the surface and the text",
      K._lum(lp["bg"]) > K._lum(lp["border"]) > K._lum(lp["text"]))

# --------------------------------------------------------------------------- #
print("the generated file is what Palette parses")
write_scheme(DARK)
env(DESK_SESSION="plasma")
src = Path(K.theme_source(Path("/nonexistent/panel/Theme.qml")))
check("theme_source points at the generated file", src == K.generated_path() and src.exists())
found = dict(PALETTE_RE.findall(src.read_text()))
check("the app's own regex finds all twelve", set(found) == set(K.KEYS), str(sorted(found)))
check("and they are the derived colours",
      found["bg"] == "#1f2627" and found["accent"] == K._hex(K.kde_palette()["accent"]))

mtime = src.stat().st_mtime_ns
check("an unchanged scheme is not rewritten", K.write_generated(K.kde_palette()) is False)
check("...and the file was left alone", src.stat().st_mtime_ns == mtime)
write_scheme(LIGHT)
check("a changed scheme is rewritten", K.write_generated(K.kde_palette()) is True)
check("no .tmp left behind", not list(src.parent.glob("*.tmp")))

print("degrading")
env(DESK_KDEGLOBALS=str(TMP / "absent-kdeglobals"))
default = Path("/some/panel/Theme.qml")
check("no kdeglobals in a Plasma session falls back to the panel theme",
      K.theme_source(default) == default)
write_scheme(DARK)
env(DESK_SESSION="hypr")
check("the Hyprland session always gets the panel theme",
      K.theme_source(default) == default)

# --------------------------------------------------------------------------- #
print("DeskStyle")
from PySide6.QtGui import QFont, QGuiApplication  # noqa: E402

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
check("hypr: Oxygen Mono keeps native hints", o.nativeHinting is True)
check("hypr: Oxygen Mono editor text keeps default hinting",
      o.editorFont.hintingPreference() == QFont.PreferDefaultHinting)

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
