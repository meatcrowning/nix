#!/usr/bin/env python3
"""Checks for the Vivaldi userscript generator (`chan-userscript.py`).

Qt-free and offline — it never reads his live `kdeglobals`, never writes to
`~/.local/share`, and never touches a browser. What it guards is the seam that
makes two browsers wear ONE sheet: the CSS the userscript bakes must be
byte-identical to the CSS surfer's courier serves for the same palette, and the
userscript's own scaffolding (self-gate, adoption, match rules, a version that
moves only when the colours do) must survive an edit.

    apps/pylib/tools/chan-userscript-test.py    # exits 0 on pass, 1 on failure
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TMP = Path(tempfile.mkdtemp(prefix="chan-userscript-"))
os.environ["DESK_SESSION"] = "hypr"          # nothing here may read his session

import chantheme                                                    # noqa: E402
import kdetheme                                                     # noqa: E402
sys.path.insert(0, str(HERE))
import importlib.util                                               # noqa: E402
_spec = importlib.util.spec_from_file_location("gen", HERE / "chan-userscript.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

PAL = {"bg": "#102030", "bgAlt": "#203040", "border": "#304050", "accent": "#ff0088",
       "dim": "#8800ff", "text": "#00ff88", "textDim": "#445566", "highlight": "#123456",
       "ok": "#abcdef", "warn": "#fedcba", "crit": "#111222", "info": "#334455"}

fails = []
total = [0]


def check(label, ok):
    total[0] += 1
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        fails.append(label)


def scheme(style):
    f = TMP / ("kdeglobals-" + style)
    f.write_text("[Colors:Window]\nBackgroundNormal=40,34,42\n"
                 "ForegroundNormal=255,230,236\nDecorationFocus=108,73,146\n"
                 "[Colors:View]\nBackgroundNormal=32,27,36\n"
                 "[Colors:Button]\nBackgroundNormal=58,51,58\n"
                 "[Colors:Selection]\nBackgroundNormal=84,59,110\n"
                 "[KDE]\nwidgetStyle=%s\ncontrast=7\n" % style, encoding="utf-8")
    return str(f)


# --- the shared sheet: one source, two browsers -----------------------------
flat = chantheme.css(PAL.__getitem__, None)
check("the sheet builds with no chrome (the Hyprland face)", len(flat) > 1000)
check("no chrome means no gradient — DESIGN.md §2 holds on this desktop",
      "linear-gradient(to bottom" not in flat)

# The panel-palette parser reads exactly the literal shape every app's Palette
# does (and the shape kdetheme itself generates).
theme = TMP / "Theme.qml"
theme.write_text("import QtQuick\nQtObject {\n" + "".join(
    '    readonly property color %s: "%s"\n' % (k, v) for k, v in PAL.items())
    + '    readonly property color computed: Qt.rgba(1,0,0,1)\n}\n', encoding="utf-8")
check("the panel Theme.qml parser recovers all twelve tokens",
      gen.panel_palette(theme) == PAL)

# --- the generated userscript ----------------------------------------------
os.environ["DESK_SESSION"] = "plasma"
os.environ["DESK_KDEGLOBALS"] = scheme("oxygen")
text, prov = gen.build("plasma", TMP / "out.user.js")
css_line = re.search(r'var CSS = (".*");', text)
check("the userscript bakes the CSS as one JSON string literal", bool(css_line))
baked = json.loads(css_line.group(1)) if css_line else ""

# THE seam: what Vivaldi gets and what surfer serves must be the same bytes for
# the same palette + chrome. If this fails, one browser has drifted.
kpal = {k: kdetheme._hex(v) for k, v in kdetheme.kde_palette().items()}
check("baked CSS == the sheet surfer serves for the same palette",
      baked == chantheme.css(kpal.__getitem__, kdetheme.kde_chrome()))
check("plasma + oxygen: the baked sheet carries the KStyle relief",
      "background-attachment:fixed" in baked and "box-shadow:inset" in baked)
check("the provenance line names the style it came from", "oxygen" in prov)

for want in ("@run-at       document-start", "@match        *://boards.4chan.org/*",
             "@grant        none"):
    check("header carries %r" % want.split()[0] + " " + want.split()[-1],
          want in text)
check("self-gate on html.oneechan survives", "contains('oneechan')" in text)
check("adopts rather than appends (cascades after ch4SS)",
      "adoptedStyleSheets" in text)
check("a <style> fallback exists for no constructable stylesheets",
      "desk-chan-theme" in text)

# Version: content-derived, so regenerating an unchanged palette does not churn
# Tampermonkey's update check, and a colour change always moves it.
v1 = re.search(r"@version\s+(\S+)", text).group(1)
v2 = re.search(r"@version\s+(\S+)", gen.build("plasma", TMP / "out.user.js")[0]).group(1)
os.environ["DESK_KDEGLOBALS"] = scheme("breeze")
v3text, v3prov = gen.build("plasma", TMP / "out.user.js")
v3 = re.search(r"@version\s+(\S+)", v3text).group(1)
check("the version is stable across an unchanged regeneration", v1 == v2)
check("the version moves when the sheet does", v1 != v3)
check("plasma + breeze: a flat KStyle bakes no gradient",
      "linear-gradient(to bottom" not in v3text)

os.environ["DESK_SESSION"] = "hypr"
os.environ.pop("DESK_KDEGLOBALS", None)

n = total[0]
print("%d/%d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
