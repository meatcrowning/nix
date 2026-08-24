#!/usr/bin/env python3
"""Checks for the Vivaldi userscript generator (`chan-userscript.py`) and the
loopback courier that keeps it live (`chan-theme-server.py`).

Qt-free and offline — it never reads his live `kdeglobals`, never writes to
`~/.local/share`, and never touches a browser. The courier half binds an
EPHEMERAL loopback port of its own, never 8791, so a run cannot disturb the
one his Vivaldi is polling. What it guards is the seam that makes two browsers
wear ONE sheet: the CSS the userscript bakes must be byte-identical to the CSS
surfer's courier serves for the same palette, the courier must serve those same
bytes with a moving ETag, and the userscript's own scaffolding (self-gate,
adoption, match rules, the gmxhr grant, a version that moves only when the
colours do) must survive an edit.

    apps/pylib/tools/chan-userscript-test.py    # exits 0 on pass, 1 on failure
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TMP = Path(tempfile.mkdtemp(prefix="chan-userscript-"))
os.environ["DESK_SESSION"] = "hypr"          # nothing here may read his session

import chansource                                                   # noqa: E402
import userscript                                                   # noqa: E402
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
             "@grant        GM_xmlhttpRequest", "@connect      127.0.0.1"):
    check("header carries %r" % want.split()[0] + " " + want.split()[-1],
          want in text)
check("self-gate on html.oneechan survives",
      'var GATE = "oneechan"' in text and "classList.contains(GATE)" in text)
check("adopts rather than appends (cascades after ch4SS)",
      "adoptedStyleSheets" in text)
check("a <style> fallback exists for no constructable stylesheets",
      "desk-chan-theme" in text)

# --- the live half: the script must ASK, not only wear what it was baked with
check("the script polls the loopback courier",
      "http://127.0.0.1:%d/chan.css" % chansource.PORT in text)
check("it asks through GM_xmlhttpRequest (a 4chan page is https)",
      "GM_xmlhttpRequest({" in text)
check("it sends If-None-Match, so an unmoved palette costs a 304",
      "If-None-Match" in text)
check("it re-polls on an interval rather than once",
      "setInterval(pull" in text)
check("the baked sheet is still applied first, as the courier-down fallback",
      "apply(CSS);" in text)

# Version: derived from the script's OWN sources, so it steps forward when the
# script changes and stands still for a palette change — which needs no
# reinstall at all, the installed script polls the courier for it. It must
# never go backwards: Tampermonkey silently refuses a same-or-older version,
# which a content hash (no order) would have caused half the time.
v1 = re.search(r"@version\s+(\S+)", text).group(1)
v2 = re.search(r"@version\s+(\S+)", gen.build("plasma", TMP / "out.user.js")[0]).group(1)
os.environ["DESK_KDEGLOBALS"] = scheme("breeze")
v3text, v3prov = gen.build("plasma", TMP / "out.user.js")
v3 = re.search(r"@version\s+(\S+)", v3text).group(1)
check("the version is stable across an unchanged regeneration", v1 == v2)
check("a palette change does NOT churn it — the script is unchanged", v1 == v3)
# An hour on, not "now": the version has minute resolution, so a source edited
# in this same minute reads as unchanged.
later = TMP / "newer.py"
later.write_text("# a source edited after the real ones\n")
os.utime(later, (time.time() + 3600, time.time() + 3600))
check("it moves when a source of the script does",
      userscript.source_version([later], major=3) > v1)
check("and it sorts as a version, newest last",
      sorted(["3.20260101.0000", v1, "3.19700101.0000"])[-1] == v1)
check("the updater is pointed at the courier, not file:// (which it refuses)",
      "@updateURL    http://127.0.0.1:%d/chan.meta.js" % chansource.PORT in text
      and "@downloadURL  http://127.0.0.1:%d/chan.user.js" % chansource.PORT in text)
check("plasma + breeze: a flat KStyle bakes no gradient",
      "linear-gradient(to bottom" not in v3text)

# --- the courier: same bytes, moving ETag, 304 on an unmoved palette --------
# Ephemeral port, bound in-process on 127.0.0.1; never 8791, so his own
# chan-theme.service and whatever Vivaldi is polling are untouched.
os.environ["DESK_SESSION"] = "plasma"
os.environ["DESK_KDEGLOBALS"] = scheme("oxygen")

import threading                                                    # noqa: E402
import urllib.error                                                 # noqa: E402
import urllib.request                                               # noqa: E402
from http.server import ThreadingHTTPServer                         # noqa: E402

_sspec = importlib.util.spec_from_file_location("srv", HERE / "chan-theme-server.py")
srv = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(srv)

httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
httpd.verbose = False
httpd.daemon_threads = True
base = "http://127.0.0.1:%d" % httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
try:
    with urllib.request.urlopen(base + "/chan.css", timeout=5) as r:
        served = r.read().decode("utf-8")
        etag = r.headers.get("ETag")
        ctype = r.headers.get("Content-Type")
    check("the courier serves the same bytes the userscript bakes", served == baked)
    check("it is text/css", (ctype or "").startswith("text/css"))
    check("it carries an ETag", bool(etag))

    req = urllib.request.Request(base + "/chan.css", headers={"If-None-Match": etag})
    code = None
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    check("an unmoved palette answers 304, not the sheet again", code == 304)

    # The whole point: nothing notifies the courier, it rebuilds per request.
    os.environ["DESK_KDEGLOBALS"] = scheme("breeze")
    with urllib.request.urlopen(base + "/chan.css", timeout=5) as r:
        moved, etag2 = r.read().decode("utf-8"), r.headers.get("ETag")
    check("a palette change is picked up with nothing restarted", moved != served)
    check("and moves the ETag, so an open tab re-adopts", etag2 != etag)

    # The update seat: Tampermonkey's updater fetches the SCRIPT over http,
    # never file://, so the courier has to hand out the script itself.
    for name in ("chan", "scrollbar"):
        with urllib.request.urlopen(base + "/%s.user.js" % name, timeout=5) as r:
            body, jtype = r.read().decode("utf-8"), r.headers.get("Content-Type")
        check("the courier serves /%s.user.js" % name, "==UserScript==" in body)
        check("  as javascript", "javascript" in (jtype or ""))
        check("  pointing its updater back here",
              ("@updateURL    http://127.0.0.1:%d/%s.meta.js"
               % (chansource.PORT, name)) in body)
        with urllib.request.urlopen(base + "/%s.meta.js" % name, timeout=5) as r:
            meta = r.read().decode("utf-8")
        check("  and the check itself is metadata only, not the whole sheet",
              meta.endswith("// ==/UserScript==\n") and len(meta) < len(body) / 4)
        check("  carrying the same version the script does",
              re.search(r"@version\s+(\S+)", meta).group(1)
              == re.search(r"@version\s+(\S+)", body).group(1))

    # An extension asking cross-origin sends a preflight first, and the stdlib
    # answers an unhandled method with 501 — which is what Tampermonkey's
    # "Install from URL" showed as *unable to load script from url*.
    pre = urllib.request.Request(base + "/scrollbar.user.js", method="OPTIONS",
                                 headers={"Origin": "chrome-extension://tm",
                                          "Access-Control-Request-Method": "GET"})
    with urllib.request.urlopen(pre, timeout=5) as r:
        check("a CORS preflight is answered, not 501", r.status == 204)
        check("  naming GET as allowed",
              "GET" in (r.headers.get("Access-Control-Allow-Methods") or ""))
    hreq = urllib.request.Request(base + "/scrollbar.user.js", method="HEAD")
    with urllib.request.urlopen(hreq, timeout=5) as r:
        check("a HEAD gets the headers and no body",
              r.status == 200 and r.read() == b""
              and int(r.headers.get("Content-Length") or 0) > 0)

    with urllib.request.urlopen(base + "/version", timeout=5) as r:
        ver = json.loads(r.read().decode("utf-8"))
    check("/version names the stamp and the provenance",
          ver.get("stamp") == chansource.stamp(moved) and "breeze" in ver.get("provenance", ""))
finally:
    httpd.shutdown()
    httpd.server_close()

os.environ["DESK_SESSION"] = "hypr"
os.environ.pop("DESK_KDEGLOBALS", None)

n = total[0]
print("%d/%d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
