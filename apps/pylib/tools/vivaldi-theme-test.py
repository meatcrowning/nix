#!/usr/bin/env python3
"""Checks for Vivaldi's chrome theme (`pylib/vivaldichrome.py`) and its writer
(`vivaldi-theme.py`).

Qt-free, offline and browser-free: it never launches Vivaldi, never reads his
profile and never writes to `~/.local/share` — the Preferences half runs
against a fabricated file in a temp directory. What it CANNOT prove from here
is that Vivaldi still reads these names; that is `tools/vivaldi-probe.py`, which
reads them off an isolated instance, and the list below is what it last saw.

    apps/pylib/tools/vivaldi-theme-test.py     # exits 0 on pass, 1 on failure
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TMP = Path(tempfile.mkdtemp(prefix="vivaldi-theme-"))
os.environ["DESK_SESSION"] = "hypr"          # nothing here may read his session

import vivaldichrome                                                # noqa: E402

sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("gen", HERE / "vivaldi-theme.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

PAL = {"bg": "#102030", "bgAlt": "#203040", "border": "#304050", "accent": "#ff0088",
       "dim": "#8800ff", "text": "#e8f0ff", "textDim": "#445566", "highlight": "#123456",
       "ok": "#abcdef", "warn": "#fedcba", "crit": "#111222", "info": "#334455"}
CHROME = {"windowTop": "#182838", "windowBottom": "#0c1826", "panelTop": "#1a2a3a",
          "panelBottom": "#0e1a28", "headerTop": "#1c2c3c", "headerBottom": "#0a1420",
          "buttonTop": "#243444", "buttonBottom": "#16222e",
          "bevel": "rgba(255,255,255,0.10)", "shade": "rgba(0,0,0,0.28)",
          "radius": 3, "style": "oxygen"}

fails, total = [], [0]


def check(label, ok):
    total[0] += 1
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        fails.append(label)


# --- the ladder --------------------------------------------------------------
v = vivaldichrome.variables(PAL.__getitem__)
# Every name Vivaldi's own engine sets on #browser, as last read by vivaldi-probe.
REQUIRED = [
    "colorBg", "colorBgLight", "colorBgLighter", "colorBgLightIntense", "colorBgDark",
    "colorBgDarker", "colorBgFaded", "colorBgIntense", "colorBgIntenser", "colorBgInverse",
    "colorBgInverser", "colorBgAlpha", "colorBgAlphaHeavy", "colorBgAlphaHeavier",
    "colorBgAlphaBlur", "colorFg", "colorFgIntense", "colorFgFaded", "colorFgFadedMore",
    "colorFgFadedMost", "colorFgAlpha", "colorBorder", "colorBorderSubtle",
    "colorBorderIntense", "colorBorderDisabled", "colorAccentBg", "colorAccentBgDark",
    "colorAccentBgDarker", "colorAccentBgFaded", "colorAccentBgFadedMore",
    "colorAccentBgFadedMost", "colorAccentBorder", "colorAccentBorderDark", "colorAccentFg",
    "colorAccentFgFaded", "colorAccentBgAlpha", "colorAccentBgAlphaHeavy",
    "colorAccentBgAlphaBlur", "colorAccentFgAlpha", "colorHighlightBg", "colorHighlightBgDark",
    "colorHighlightBgFaded", "colorHighlightBgAlpha", "colorHighlightFg",
    "colorHighlightFgAlpha", "colorHighlightFgAlphaHeavy", "colorErrorBg", "colorErrorBgAlpha",
    "colorErrorFg", "colorSuccessBg", "colorSuccessBgAlpha", "colorSuccessFg", "colorWarningBg",
    "colorWarningBgAlpha", "colorWarningFg", "colorImageBg", "colorImageFg", "colorImageTopBg",
    "colorImageTopFg", "colorImageBottomBg", "colorImageLeftBg", "colorImageRightBg",
    "colorImageCenterBg", "radius", "radiusCap", "radiusHalf", "radiusRounded",
    "radiusRoundedLess", "radiusWindow",
]
missing = [k for k in REQUIRED if k not in v]
check("every property Vivaldi's engine sets is defined (%d)" % len(REQUIRED), not missing)
if missing:
    print("       missing: " + ", ".join(missing))
check("the corner is Oxygen's 3px, not Vivaldi's 8", v["radius"] == "3px")
check("the surface is the palette's, not a derived guess", v["colorBg"] == PAL["bg"])
check("the elevated surface is the scheme's View colour", v["colorBgIntense"] == PAL["bgAlt"])
check("a dark palette still ladders UP for the light steps",
      vivaldichrome.hexcolor.lum(v["colorBgLighter"]) > vivaldichrome.hexcolor.lum(v["colorBg"]))
check("and DOWN for the dark ones",
      vivaldichrome.hexcolor.lum(v["colorBgDarker"]) < vivaldichrome.hexcolor.lum(v["colorBg"]))
check("accent ink is readable ON the accent",
      vivaldichrome.hexcolor.contrast(v["colorAccentFg"], v["colorAccentBg"]) >= 4.5)
check("selection ink is readable on the selection",
      vivaldichrome.hexcolor.contrast(v["colorHighlightFg"], v["colorHighlightBg"]) >= 4.5)
check("the Image* zones follow the surface, not Vivaldi's light-theme default",
      all(v["colorImage%sBg" % z] == PAL["bg"] for z in ("", "Top", "Bottom", "Left", "Right")))

# --- the relief --------------------------------------------------------------
oxy = vivaldichrome.relief_css(PAL.__getitem__, CHROME)
flat = vivaldichrome.relief_css(PAL.__getitem__, None)
check("a gradient KStyle draws slabs", "linear-gradient(to bottom" in oxy)
check("and the flat face draws none (DESIGN.md 2)", "linear-gradient" not in flat)
check("both name the same surfaces, so only the fill differs",
      [s.split("{")[0] for s in oxy.split("}") ] == [s.split("{")[0] for s in flat.split("}")])
for sel in ("#header", ".toolbar-mainbar", ".UrlBar-AddressField", ".ToolbarButton-Button",
            ".tab.active", "#panels-container", ".toolbar-statusbar"):
    check("the relief reaches %s" % sel, sel in oxy)
check("the address field is a HOLE (inset shadow), not a raised pill",
      "inset 0 1px 2px" in oxy)

# --- the whole sheet ---------------------------------------------------------
css = vivaldichrome.css(PAL.__getitem__, CHROME, extra="::-webkit-scrollbar{width:9px}")
check("the ladder is emitted on #browser, where the engine sets it", "#browser," in css)
check("every property is !important — the engine sets its own inline",
      css.count("!important;\n") >= len(REQUIRED))
check("the caller's extra sheet rides along", "::-webkit-scrollbar{width:9px}" in css)

# --- Preferences -------------------------------------------------------------
prefs = TMP / "Preferences"


def fresh(schedule_enabled=0, current="Vivaldi1"):
    prefs.write_text(json.dumps({
        "vivaldi": {
            "themes": {"current": current,
                       "user": [{"id": "his-own", "name": "Issuna", "colorBg": "#1d1e21"}]},
            "theme": {"schedule": {"enabled": schedule_enabled,
                                   "o_s": {"dark": "Vivaldi2", "light": "his-own"}}},
        }}), encoding="utf-8")


fresh()
path, changed = gen.write_prefs("hypr", prefs=prefs, force=True)
data = json.loads(prefs.read_text())
themes = data["vivaldi"]["themes"]
check("the theme is installed and made current", changed and themes["current"] == gen.THEME_ID)
check("his own theme is left in the list", any(t["id"] == "his-own" for t in themes["user"]))
check("exactly one of ours, never a pile",
      sum(1 for t in themes["user"] if t["id"] == gen.THEME_ID) == 1)
# THE thing that makes it apply at all: themes.current alone is ignored at
# startup (measured, Vivaldi 8.1) — the engine resolves through the schedule.
sched = data["vivaldi"]["theme"]["schedule"]
check("the schedule map names it for both light and dark",
      sched["o_s"] == {"dark": gen.THEME_ID, "light": gen.THEME_ID})
check("and scheduling stays OFF", sched["enabled"] == 0)
check("a second run changes nothing", gen.write_prefs("hypr", prefs=prefs, force=True)[1] is False)

fresh(schedule_enabled=1)
try:
    gen.write_prefs("hypr", prefs=prefs, force=True)
    check("a schedule he switched ON is refused, not overwritten", False)
except SystemExit as e:
    check("a schedule he switched ON is refused, not overwritten", "SCHEDULE" in str(e))
    check("and the file is untouched",
          json.loads(prefs.read_text())["vivaldi"]["themes"]["current"] == "Vivaldi1")

# --- the file it writes ------------------------------------------------------
uidir = TMP / "vivaldi-ui"
path, prov, changed = gen.write_ui("hypr", "flat", uidir)
check("custom.css lands in the folder Vivaldi is pointed at",
      path == uidir / "custom.css" and changed)
body = path.read_text()
check("it carries the chrome AND the scrollbar",
      "--colorBg" in body and "::-webkit-scrollbar" in body)
check("it names itself generated", "hand-edit" in body)
check("an unchanged palette does not rewrite it", gen.write_ui("hypr", "flat", uidir)[2] is False)

n = total[0]
print("%d/%d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
