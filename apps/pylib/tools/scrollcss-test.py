#!/usr/bin/env python3
"""Checks for the browser scrollbar sheet (`pylib/scrollcss.py`) and the two
things that carry it into Vivaldi (`scrollbar-userscript.py`).

Qt-free by default and offline — it never reads his live `kdeglobals`, never
writes to `~/.local/share`, and never touches a browser. With `--web` it also
loads the sheet into an OFFSCREEN QtWebEngine page (`WAYLAND_DISPLAY` and
`DISPLAY` cleared first) and asserts Chromium kept every rule and actually
changed the scrollbar's width — the half no amount of string-checking can
prove, since a rule Chromium does not understand is dropped silently.

    apps/pylib/tools/scrollcss-test.py           # exits 0 on pass, 1 on failure
    surfer-qtenv apps/pylib/tools/scrollcss-test.py --web
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TMP = Path(tempfile.mkdtemp(prefix="scrollcss-"))
os.environ["DESK_SESSION"] = "hypr"          # nothing here may read his session

import chansource                                                    # noqa: E402
import scrollcss                                                    # noqa: E402

sys.path.insert(0, str(HERE))
import importlib.util                                               # noqa: E402
_spec = importlib.util.spec_from_file_location("gen", HERE / "scrollbar-userscript.py")
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


def scheme(style, window="40,34,42", button="58,51,58"):
    f = TMP / ("kdeglobals-" + style)
    f.write_text("[Colors:Window]\nBackgroundNormal=%s\n"
                 "ForegroundNormal=255,230,236\nDecorationFocus=108,73,146\n"
                 "[Colors:View]\nBackgroundNormal=32,27,36\n"
                 "[Colors:Button]\nBackgroundNormal=%s\n"
                 "[Colors:Selection]\nBackgroundNormal=84,59,110\n"
                 "[KDE]\nwidgetStyle=%s\ncontrast=7\n" % (window, button, style),
                 encoding="utf-8")
    return str(f)


# --- the desktop's own three variants ---------------------------------------
for style, width in (("win31", 16), ("beveled", 14), ("flat", 11)):
    css = scrollcss.desktop_css(PAL.__getitem__, style)
    check("%s: the bar is %dpx (DESIGN.md 9.2)" % (style, width),
          "width:%dpx!important" % width in css)
    check("%s: no radius and no gradient anywhere" % style,
          "border-radius:0!important" in css and "linear-gradient" not in css)
    has_buttons = "background-image:url(data:image/svg" in css
    check("%s: steppers %s" % (style, "drawn" if style == "win31" else "hidden"),
          has_buttons == (style == "win31"))

check("a site's own scrollbar-color cannot take the standard rendering path",
      "scrollbar-color:auto!important" in scrollcss.desktop_css(PAL.__getitem__))
check("win31 forces Blink to materialise its native stepper parts",
      "::-webkit-scrollbar-button{display:block!important" in
      scrollcss.desktop_css(PAL.__getitem__, "win31"))

# --- the Oxygen face ---------------------------------------------------------
oxy = scrollcss.oxygen_css(PAL.__getitem__, {"scrollWidth": 15, "scrollSubButtons": 1,
                                             "scrollAddButtons": 2,
                                             "scrollButtonHeight": 14},
                           button="#3a3340")
check("the bar is ScrollBarWidth + 2 (the style's real extent)",
      "width:17px!important" in oxy)
check("the slider is a top-lit gradient, not a flat pill",
      "linear-gradient(to bottom" in oxy)
check("the groove is the TRACK, so it runs unbroken under the slider",
      "::-webkit-scrollbar-track{" in oxy and "track-piece{background:transparent" in oxy)
check("the slider carries the Button group, not bgAlt",
      "#3a3340" not in oxy and PAL["bgAlt"] not in oxy)

# oxygenrc owns the stepper COUNT: one above, two below, by upstream default.
def buttons(css):
    return set(re.findall(r"::-webkit-scrollbar-button(:vertical:\w+:\w+)\{display:block", css))

check("one stepper above and two below, per oxygenrc",
      buttons(oxy) == {":vertical:start:decrement", ":vertical:end:decrement",
                       ":vertical:end:increment"})
check("the base button part is block, so Blink materialises native steppers",
      "::-webkit-scrollbar-button{display:block!important" in oxy)
check("the unused start:increment is hidden, not left default",
      ":vertical:start:increment{display:none" in oxy.replace(
          "::-webkit-scrollbar-button", "").replace(",", "{display:none"))
none_bar = scrollcss.oxygen_css(PAL.__getitem__, {"scrollWidth": 15, "scrollSubButtons": 0,
                                                  "scrollAddButtons": 0,
                                                  "scrollButtonHeight": 14})
check("no steppers configured means no steppers drawn", not buttons(none_bar))
check("the stepper is a hollow chevron (Oxygen), not a solid triangle (win31)",
      "polyline" in oxy and "polygon" not in oxy)

# A very dark scheme: Oxygen's shade() gives up and lightens, and so must this.
dark = scrollcss.oxygen_css({**PAL, "bg": "#050505"}.__getitem__)
m = re.search(r"scrollbar-track\{background-color:(#[0-9a-f]{6})", dark)
check("a near-black scheme gets a LIGHTER groove, not a black one",
      bool(m) and int(m.group(1)[1:3], 16) > 5)

# --- which face the session gets --------------------------------------------
os.environ["DESK_SESSION"] = "plasma"
os.environ["DESK_KDEGLOBALS"] = scheme("oxygen")
css, prov = scrollcss.build()
check("plasma + a gradient KStyle -> Oxygen's own bar", "Oxygen's own bar" in prov)
check("and it is the Oxygen sheet, not a variant", "linear-gradient(to bottom" in css)
os.environ["DESK_KDEGLOBALS"] = scheme("breeze")
css, prov = scrollcss.build()
check("plasma + a flat KStyle -> the desktop's own variant", "desktop's" in prov)
check("which draws no gradient (DESIGN.md 2)", "linear-gradient" not in css)
os.environ["DESK_SESSION"] = "hypr"
os.environ.pop("DESK_KDEGLOBALS", None)

# --- the userscript ----------------------------------------------------------
text, prov = gen.build("plasma", "flat", TMP / "out.user.js")
check("it matches every site, not just one", "@match        *://*/*" in text)
check("it asks through GM_xmlhttpRequest (an https page, an http courier)",
      "@grant        GM_xmlhttpRequest" in text and "GM_xmlhttpRequest({" in text)
check("it polls the scrollbar route, not the 4chan one",
      "/scrollbar.css" in text and "/chan.css" not in text)
check("it has no gate — the scrollbar rides everywhere", "var GATE = null" in text)
v1 = re.search(r"@version\s+(\S+)", text).group(1)
v2 = re.search(r"@version\s+(\S+)", gen.build("plasma", "flat", TMP / "o.js")[0]).group(1)
v3 = re.search(r"@version\s+(\S+)", gen.build("plasma", "win31", TMP / "o.js")[0]).group(1)
check("the version is stable across an unchanged regeneration", v1 == v2)
# It tracks the script's own sources, not the palette: a style or colour change
# needs no reinstall (the installed script polls the courier for it), and the
# version must only ever step FORWARD — Tampermonkey silently refuses one that
# is not newer, which an unordered content hash caused half the time.
check("a style change does NOT churn it — the script is unchanged", v1 == v3)
check("the updater is pointed at the courier, not file:// (which it refuses)",
      "@updateURL    http://127.0.0.1:%d/scrollbar.meta.js" % chansource.PORT in text)

# Vivaldi's custom.css is written by vivaldi-theme.py (one writer, chrome and
# scrollbar in one file) and checked by vivaldi-theme-test.py.

# --- Chromium itself, offscreen ---------------------------------------------
ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--web", action="store_true",
                help="also load the sheet into an offscreen QtWebEngine page")
if ap.parse_args().web:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"      # hard, never setdefault
    os.environ.pop("WAYLAND_DISPLAY", None)          # no way back to his session
    os.environ.pop("DISPLAY", None)
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    sheet = scrollcss.desktop_css(PAL.__getitem__, "win31")
    rules = sheet.count("}")
    app = QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.resize(500, 400)
    out = {}

    def injected(result):
        out.update(json.loads(result))
        app.quit()

    def load_done(_ok):
        view.page().runJavaScript("""
        (function(){
          var before = document.documentElement.clientWidth;
          var s = document.createElement('style');
          s.textContent = %s;
          document.head.appendChild(s);
          return JSON.stringify({before: before, parsed: s.sheet ? s.sheet.cssRules.length : -1,
                                 after: document.documentElement.clientWidth});
        })()""" % json.dumps(sheet), injected)

    view.loadFinished.connect(load_done)
    view.setHtml("<html><body style='height:3000px'>x</body></html>",
                 QUrl("http://localhost/"))
    view.show()
    QTimer.singleShot(20000, app.quit)
    app.exec()
    check("Chromium parsed every rule (a rule it cannot read is dropped silently)",
          out.get("parsed") == rules)
    # The viewport loses exactly the bar's width once the sheet lands.
    check("and the page's scrollbar actually took the 16px width",
          500 - out.get("after", 0) == 16)

n = total[0]
print("%d/%d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
