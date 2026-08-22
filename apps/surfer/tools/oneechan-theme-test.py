#!/usr/bin/env python3
"""Offscreen regression test for surfer's OneeChan LIVE-THEME courier — the fix
for "OneeChan paints 4chan in its own baked hex colours, not the desktop
palette, and never follows a palette change".

OneeChan (a 4chan userscript) bakes hex colours from its own theme into a single
`<style id=ch4SS>` it appends to <head>; its `$SS` state is a private var in a
top-level IIFE, so its theme cannot be re-driven externally without a page
reload (which would lose scroll position and half-typed replies). So instead of
poking OneeChan, surfer adopts its OWN stylesheet, built from the live wallpaper
palette, over the `surferonee://` scheme — the same document-creation /
synchronous-XHR / adoptedStyleSheets courier shape as the dark-mode
`surferstyle://` one. An adopted sheet cascades AFTER any document `<style>`, so
with matching selectors + `!important` it beats `ch4SS` on ties — re-skinning
OneeChan's colours with no reload.

Two guards make it safe: it runs only on 4chan hosts, and it adopts only once
`document.documentElement` carries the `oneechan` class (OneeChan sets
`html.oneechan` when it initialises), so it themes ONLY when OneeChan is active,
never bare 4chan.

This harness stands up a real offscreen QtWebEngine profile carrying the EXACT
`Main.qml` concat line (cosmetic + page-style + OneeChan couriers together),
resolves `boards.4chan.org` to loopback (`--host-resolver-rules`) so the host
gate passes, and asserts:

  1. on a page that IS OneeChan-active (html.oneechan) with a baked ch4SS
     baseline, the palette colours WIN — body/reply backgrounds, post text,
     plain links and quotelinks all take the live palette, not the baked hexes
     (proves adopted-after-<style> + !important beats ch4SS on ties);
  2. the live-refresh hook `window.__surferOneeThemeRefresh` exists;
  3. LIVE: a WalPalette change (the watched Theme.qml rewritten) drives
     `__surferOneeThemeRefresh` and re-skins an already-painted page with no
     reload;
  4. SELF-GATE: a 4chan page WITHOUT html.oneechan is NOT themed — the baked
     ch4SS baseline survives untouched.
  5. the KStyle RELIEF layer (Plasma sessions): under a gradient KStyle
     (Oxygen) the sheet gains window/panel/header/button gradients that come
     AFTER the flat rules on the same selectors, so they win on source order;
     under a flat KStyle (Breeze) and in the Hyprland session it is absent
     entirely, so this desktop's own flat look is untouched;
  6. RENDERED light-palette collapse: on a light palette, every OneeChan inset
     surface — post header, reply chain, catalog cells (`Show Background`),
     inline-expanded quotes, text fields — computes to the plain page `bg`,
     asserted by getComputedStyle after a real load (not a string match), so a
     surface OneeChan paints near-black but surfer forgets to collapse cannot
     pass unnoticed the way the catalog cells and `.inline` did.

    tools/oneechan-theme-test.py        # exits 0 on pass, 1 on failure
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
# The KStyle relief layer is Plasma-session-only, and this harness may well be
# started FROM a Plasma session (XDG_CURRENT_DESKTOP=KDE), which would give
# every flat assertion below a gradient it is not expecting. Pin the session
# for the flat body of the run; the Plasma block flips it deliberately and puts
# it back.
os.environ["DESK_SESSION"] = "hypr"
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
# OneeChan's courier is host-gated to 4chan; point that name at our loopback
# server so location.hostname reads 'boards.4chan.org' and the gate passes.
# Must be set before QtWebEngineQuick.initialize().
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    + ' --host-resolver-rules="MAP boards.4chan.org 127.0.0.1"')

from PySide6.QtCore import QObject, QTimer, QUrl, Slot                # noqa: E402
from PySide6.QtGui import QGuiApplication                            # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                       # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineUrlScheme               # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                 # noqa: E402

# Two initial palettes and one live change, chosen so every asserted role gets a
# distinctive colour (no two roles share a value we check).
PAL_A = {
    "bg": "#102030", "bgAlt": "#203040", "border": "#304050", "accent": "#ff0088",
    "dim": "#8800ff", "text": "#00ff88", "textDim": "#445566", "highlight": "#123456",
    "ok": "#abcdef", "warn": "#fedcba", "crit": "#111222", "info": "#334455",
}
# the live change: a different bg so the re-skin is visible on body background
PAL_B = dict(PAL_A, bg="#010203", bgAlt="#0a0b0c")

# A LIGHT palette with DARK bgAlt/highlight, so "collapsed to bg" is
# distinguishable from "kept as the inset shade" in a real render. This is the
# case f66285e was about and the one his live wallpaper produces: on it, every
# OneeChan inset surface must read as the plain page `bg`, not a near-black
# inset. rel_lum(#f4efe2) ~= 0.85 > 0.2, so the collapse branch fires.
PAL_LIGHT = dict(PAL_A, bg="#f4efe2", bgAlt="#202020", highlight="#181818")


def rgb(hexstr):
    """'#rrggbb' -> 'rgb(r, g, b)' as getComputedStyle reports it."""
    h = hexstr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "rgb(%d, %d, %d)" % (r, g, b)


def write_theme(path, pal):
    """Write a Theme.qml the Palette watcher parses (only the `property color`
    lines matter)."""
    lines = ['import QtQuick', 'QtObject {']
    lines += ['    property color %s: "%s"' % (k, v) for k, v in pal.items()]
    lines += ['}', '']
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# A 4chan-ish page with a baked ch4SS baseline (light, !important like the real
# one) AND html.oneechan set — the OneeChan-active case. The bare variant drops
# the class to test the self-gate. `{cls}` is filled per request.
INDEX = """<!doctype html><html class="{cls}"><head><title>t</title>
<style id="ch4SS">
html,body{{color:#000000 !important}}
body{{background:#ffffff !important}}
.reply{{background:#eeeeee !important}}
a{{color:#0000ee !important}}
.quotelink{{color:#dd0000 !important}}
</style>
</head><body>
<div class="reply postContainer" id="r">reply
  <a class="quotelink" href="#">&gt;&gt;123</a>
</div>
<a id="lnk" href="#">a link</a>
<p class="postMessage" id="pm">post text</p>
<script src="/app.js"></script>
</body></html>"""

# probe: report every asserted computed colour + the refresh hook's presence
APP_JS = b"""\
setTimeout(function(){
  function cc(sel, prop){ try {
      var e = document.querySelector(sel);
      return getComputedStyle(e)[prop]; } catch(e){ return 'ERR'; } }
  document.title = JSON.stringify({
      bodyBg:    cc('body','backgroundColor'),
      bodyColor: cc('body','color'),
      replyBg:   cc('#r','backgroundColor'),
      aColor:    cc('#lnk','color'),
      qlColor:   cc('.quotelink','color'),
      hasRefresh: typeof window.__surferOneeThemeRefresh === 'function'
  });
}, 700);
"""


# A RENDERED light-palette page. The ch4SS baseline paints every inset surface
# the way his live OneeChan theme does — from a full-opacity near-black
# `mainColor`/`headerBGColor` — so "collapsed to bg" and "left as the dark
# inset" are visibly different. It covers the surfaces f66285e's string-only
# "20/20" never rendered: the post header, the catalog cells (`Show Background`
# mode), inline-expanded quotes, and a text field. Selectors and classes are
# verbatim from OneeChan's ch4SS so specificity ties exactly as in the browser.
INDEX_LIGHT = """<!doctype html>
<html class="oneechan header-gradient catalog-background">
<head><title>t</title>
<style id="ch4SS">
html,body{color:#000 !important}
body{background:#000 !important}
.reply,body.is_catalog .panel,.dialog{background:rgba(0,0,0,1)!important}
.postInfo{background:rgba(0,0,0,1)!important;border-bottom:2px solid rgb(0,0,0)!important}
:root.header-gradient #header-bar{background:linear-gradient(rgb(15,15,15),rgba(0,0,0,0.9))!important}
input:not(.jsColor),textarea,.captcha-root{background:#000 !important}
.inline{background:rgba(0,0,0,.8)!important}
:root.catalog-background #threads div.thread,:root.catalog-background .catalog-thread{background:rgba(0,0,0,1)!important}
</style></head><body>
<div id="header-bar" class="dialog">header</div>
<div class="reply postContainer" id="r"><div class="postInfo" id="pi">post header</div>reply</div>
<input id="inp" type="text">
<div id="threads"><div class="thread catalog-thread" id="ct">catalog cell</div></div>
<div class="inline" id="il">inline expand</div>
<script src="/applight.js"></script>
</body></html>"""

# probe for the light page: report the computed background of each inset. Both
# the flat colour AND the image, since a gradient shows up only as image.
APP_JS_LIGHT = b"""\
setTimeout(function(){
  function bg(sel){ try { var e=document.querySelector(sel);
      var s=getComputedStyle(e);
      return s.backgroundColor+'|'+s.backgroundImage; } catch(e){ return 'ERR'; } }
  document.title = JSON.stringify({
      header: bg('#header-bar'), reply: bg('#r'), input: bg('#inp'),
      catalog: bg('#ct'), inline: bg('#il'), postheader: bg('#pi')
  });
}, 900);
"""


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/app.js":
            body, ctype = APP_JS, "application/javascript"
        elif self.path == "/applight.js":
            body, ctype = APP_JS_LIGHT, "application/javascript"
        elif self.path.startswith("/light"):
            body, ctype = INDEX_LIGHT.encode("utf-8"), "text/html"
        else:
            cls = "oneechan" if self.path.startswith("/gated") else "notonee"
            body = INDEX.format(cls=cls).encode("utf-8")
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


QML = """
import QtQuick
import QtQuick.Window
import QtWebEngine
Window {
    visible: true; width: 800; height: 600
    WebEngineProfile {
        id: sharedProfile
        objectName: "sharedProfile"
        offTheRecord: true
        // the EXACT line Main.qml uses: cosmetic + page-style + OneeChan couriers
        Component.onCompleted: userScripts.collection =
            CosmeticInject.scripts.concat(PageStyle.scripts)
                                 .concat(OneeTheme.scripts)
    }
    WebEngineView { objectName: "view"; anchors.fill: parent; profile: sharedProfile }
}
"""


class StubCosmetic(QObject):
    """The minimal slot shape CosmeticInjector calls; no ad rules here, so the
    cosmetic courier degrades to empty while the OneeChan one runs."""

    @Slot(str, result=str)
    def specificJs(self, url):
        return ""

    @Slot(str, "QVariantList", "QVariantList", result=str)
    def genericJs(self, url, classes, ids):
        return ""

    @Slot(str, result=str)
    def proceduralJson(self, url):
        return "[]"


def main():
    for name in (b"surferstyle", b"surfercos", b"surferonee"):
        sch = QWebEngineUrlScheme(name)
        sch.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        sch.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                     | QWebEngineUrlScheme.Flag.CorsEnabled
                     | QWebEngineUrlScheme.Flag.FetchApiAllowed
                     | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
        QWebEngineUrlScheme.registerScheme(sch)

    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    # scratch state: never read or write the user's prefs.json / real Theme.qml
    scratch = Path(tempfile.mkdtemp(prefix="surfer-oneetheme-"))
    os.environ["XDG_STATE_HOME"] = str(scratch)
    theme = scratch / "Theme.qml"
    write_theme(theme, PAL_A)

    import main as surfer                                            # noqa: E402
    import chantheme          # noqa: E402  (pylib; main.py puts it on the path)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    gated = "http://boards.4chan.org:%d/gated.html" % port
    bare = "http://boards.4chan.org:%d/bare.html" % port
    lightgated = "http://boards.4chan.org:%d/light.html" % port

    # the live palette the OneeChan bridge reads (same parser/watcher as filer's)
    palette = surfer.Palette(str(theme), app)
    prefs = surfer.Prefs(app)
    dm = surfer.DarkMode(prefs, app)          # dark off: surferstyle serves empty
    ps = surfer.PageStyle(app)
    pshandler = surfer.PageStyleHandler(dm, app)
    cosinject = surfer.CosmeticInjector(StubCosmetic(app), app)
    oneetheme = surfer.OneeTheme(palette, app)
    oneehandler = surfer.OneeThemeHandler(oneetheme, app)

    eng = QQmlApplicationEngine()
    eng.warnings.connect(lambda ws: [print("QML:", w.toString()) for w in ws])
    eng.rootContext().setContextProperty("PageStyle", ps)
    eng.rootContext().setContextProperty("CosmeticInject", cosinject)
    eng.rootContext().setContextProperty("OneeTheme", oneetheme)
    eng.loadData(QML.encode(), QUrl("qrc:/harness.qml"))
    if not eng.rootObjects():
        print("FAIL: harness QML did not load")
        return 1
    ro = eng.rootObjects()[0]
    prof = ro.findChild(QObject, "sharedProfile")
    prof.installUrlSchemeHandler(b"surferstyle", pshandler)
    prof.installUrlSchemeHandler(b"surfercos", cosinject)
    prof.installUrlSchemeHandler(b"surferonee", oneehandler)
    view = ro.findChild(QObject, "view")

    # the LIVE wiring Main.qml has (Connections{target:WalPalette} onChanged ->
    # win.reinjectOnee()): a palette change re-runs the refresh hook.
    palette.changed.connect(
        lambda: view.runJavaScript("window.__surferOneeThemeRefresh"
                                   " && window.__surferOneeThemeRefresh()",
                                   lambda r: None))

    out = {}
    fails = []
    total = [0]

    def check(label, ok):
        total[0] += 1
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    # --- pure-python: the dark-mode link legibility lift (helper itself) ---
    # PAL_A's bg is dark and its dim link sits close to it; the helper lifts the
    # link until it clears the contrast floor, capped under the hover accent. A
    # light palette must leave OneeChan's dim link untouched.
    dark_bg, dim, acc = PAL_A["bg"], PAL_A["dim"], PAL_A["accent"]
    lifted = chantheme._legible_link(dim, dark_bg, acc)
    check("dark palette lifts the dim link's contrast against bg",
          chantheme._contrast(lifted, dark_bg) > chantheme._contrast(dim, dark_bg))
    check("lifted link clears the legibility floor (or hits the accent cap)",
          chantheme._contrast(lifted, dark_bg) >= 4.0 - 1e-6
          or chantheme._rel_lum(lifted) >= chantheme._rel_lum(acc) - 1e-9)
    check("lifted link stays no brighter than the hover accent",
          chantheme._rel_lum(lifted) <= chantheme._rel_lum(acc) + 1e-9)
    light = dict(PAL_A, bg="#f4f4f4")
    check("a light palette leaves OneeChan's dim link untouched",
          chantheme._legible_link(light["dim"], light["bg"], light["accent"]) == light["dim"])

    # --- pure-python: the LIGHT-palette background collapse ---
    # On a light palette, OneeChan's inset surfaces (open reply chains, post
    # backgrounds, post headers, catalog panels and text fields) must read as
    # the plain PAGE background, not the dark-tuned bgAlt/highlight shades. A
    # dark palette keeps the inset treatment untouched. Assert on the built CSS
    # via stable selector-tail fragments (each background rule ends on a
    # selector unique to that rule).
    class _StubPal:
        def __init__(self, d):
            self._d = d

        def hex(self, k):
            return self._d[k]

    def onee_css(pal):
        return surfer.OneeTheme(_StubPal(pal), app)._css()

    # distinct bgAlt/highlight so we can tell "collapsed to bg" from "kept"
    light_pal = dict(PAL_A, bg="#f0f0f0", bgAlt="#c8c8c8", highlight="#d0d0d0")
    dark_pal = dict(PAL_A)  # bg=#102030 (dark), bgAlt=#203040, highlight=#123456
    lcss, dcss = onee_css(light_pal), onee_css(dark_pal)

    def bg_rule(css, tail, color):
        return ("%s{background:%s!important}" % (tail, color)) in css

    check("light palette: reply/post-chain/catalog background collapses to bg",
          bg_rule(lcss, ".dd-menu ul", "#f0f0f0"))
    check("light palette: post header (#header-bar) background collapses to bg",
          bg_rule(lcss, "#header-bar", "#f0f0f0"))
    check("light palette: text input background collapses to bg",
          bg_rule(lcss, ".captcha-root", "#f0f0f0"))
    check("dark palette: reply/post background keeps bgAlt (inset untouched)",
          bg_rule(dcss, ".dd-menu ul", "#203040"))
    check("dark palette: post header background keeps bgAlt (inset untouched)",
          bg_rule(dcss, "#header-bar", "#203040"))
    check("dark palette: text input background keeps highlight (inset untouched)",
          bg_rule(dcss, ".captcha-root", "#123456"))

    # --- pure-python: the KStyle relief layer (Plasma sessions only) ---
    # kdetheme.kde_chrome() gates on the session AND on the style drawing a
    # window gradient. Point DESK_KDEGLOBALS at synthetic schemes so nothing
    # reads (or depends on) his live one.
    def scheme(style):
        f = scratch / ("kdeglobals-" + style)
        f.write_text(
            "[Colors:Window]\nBackgroundNormal=40,34,42\n"
            "[Colors:View]\nBackgroundNormal=32,27,36\n"
            "[Colors:Button]\nBackgroundNormal=58,51,58\n"
            "[KDE]\nwidgetStyle=%s\ncontrast=7\n" % style, encoding="utf-8")
        return str(f)

    check("hyprland session: no relief layer (this desktop stays flat)",
          "linear-gradient(to bottom" not in dcss)

    os.environ["DESK_SESSION"] = "plasma"
    try:
        os.environ["DESK_KDEGLOBALS"] = scheme("oxygen")
        ox = onee_css(dark_pal)
        check("plasma + oxygen: the window gets a gradient",
              "background-image:linear-gradient(to bottom" in ox)
        check("plasma + oxygen: posts get the panel gradient and a bevel",
              "box-shadow:inset 0 1px 0 rgba(255,255,255" in ox)
        check("plasma + oxygen: real buttons get the button gradient",
              "button,input[type=submit]" in ox)
        check("plasma + oxygen: the gradient rule comes AFTER the flat one "
              "(same selector, source order decides)",
              ox.rindex(".dd-menu ul{background:linear-gradient")
              > ox.index(".dd-menu ul{background:%s!important" % dark_pal["bgAlt"]))
        os.environ["DESK_KDEGLOBALS"] = scheme("breeze")
        check("plasma + breeze: a flat KStyle gets no relief layer",
              "linear-gradient(to bottom" not in onee_css(dark_pal))
    finally:
        os.environ["DESK_SESSION"] = "hypr"
        os.environ.pop("DESK_KDEGLOBALS", None)

    def read_title():
        t = view.property("title")
        if isinstance(t, str) and t:
            try:
                out.clear()
                out.update(json.loads(t))
                return True
            except Exception:
                pass
        return False

    # stage 0: load the OneeChan-ACTIVE page (dark off, only OneeChan themes it)
    QTimer.singleShot(300, lambda: view.setProperty("url", QUrl(gated)))

    def phase1():
        if not read_title():
            QTimer.singleShot(200, phase1)
            return
        check("body background takes the palette bg (beats ch4SS #ffffff)",
              out.get("bodyBg") == rgb(PAL_A["bg"]))
        check("post text takes the palette text colour (beats ch4SS #000000)",
              out.get("bodyColor") == rgb(PAL_A["text"]))
        check("reply background takes the palette bgAlt (beats ch4SS #eeeeee)",
              out.get("replyBg") == rgb(PAL_A["bgAlt"]))
        check("plain link takes the legibility-lifted palette dim (beats ch4SS #0000ee)",
              out.get("aColor")
              == rgb(chantheme._legible_link(PAL_A["dim"], PAL_A["bg"], PAL_A["accent"])))
        check("quotelink takes the palette accent (beats ch4SS #dd0000)",
              out.get("qlColor") == rgb(PAL_A["accent"]))
        check("live refresh hook installed", out.get("hasRefresh") is True)
        # phase 2: LIVE palette change -> watcher fires -> refresh re-skins
        write_theme(theme, PAL_B)
        QTimer.singleShot(900, phase2)

    def phase2():
        view.runJavaScript(
            "document.title=JSON.stringify({bodyBg:"
            "getComputedStyle(document.body).backgroundColor,replyBg:"
            "getComputedStyle(document.getElementById('r')).backgroundColor});",
            lambda r: None)
        QTimer.singleShot(500, phase2b)

    def phase2b():
        read_title()
        check("a palette change live-re-skinned the open page (new bg)",
              out.get("bodyBg") == rgb(PAL_B["bg"]))
        check("a palette change live-re-skinned reply background (new bgAlt)",
              out.get("replyBg") == rgb(PAL_B["bgAlt"]))
        # phase 3: SELF-GATE — a 4chan page WITHOUT html.oneechan is untouched
        view.setProperty("url", QUrl(bare))
        QTimer.singleShot(1200, phase3)

    def phase3():
        if not read_title():
            QTimer.singleShot(200, phase3)
            return
        check("self-gate: a page without html.oneechan keeps ch4SS body bg",
              out.get("bodyBg") == "rgb(255, 255, 255)")
        check("self-gate: a page without html.oneechan keeps ch4SS reply bg",
              out.get("replyBg") == "rgb(238, 238, 238)")
        # phase 4: RENDERED light-palette collapse. Switch to a light palette
        # (light bg, DARK bgAlt/highlight) and load a page whose ch4SS paints
        # every inset near-black, exactly like his live OneeChan theme. Assert
        # by RENDER (getComputedStyle after a real load), not by string match:
        # header, reply, catalog cells, inline expands and the text field must
        # all compute to the plain page bg — the gap that let a string-only
        # "20/20" miss the catalog cells and `.inline`, which f66285e never
        # collapsed.
        write_theme(theme, PAL_LIGHT)
        QTimer.singleShot(400, lambda: view.setProperty("url", QUrl(lightgated)))
        QTimer.singleShot(2000, phase4)

    def phase4():
        if not read_title() or "catalog" not in out:
            QTimer.singleShot(200, phase4)
            return
        want = rgb(PAL_LIGHT["bg"])

        def bgcolor(v):
            return (v or "").split("|")[0]

        def bgimage(v):
            return (v or "").split("|", 1)[1] if v and "|" in v else ""
        check("light render: post header (#header-bar) collapses to bg",
              bgcolor(out.get("header")) == want)
        check("light render: #header-bar clears OneeChan's gradient image",
              bgimage(out.get("header")) == "none")
        check("light render: reply chain collapses to bg",
              bgcolor(out.get("reply")) == want)
        check("light render: post header strip (.postInfo) collapses to bg",
              bgcolor(out.get("postheader")) == want)
        check("light render: text field collapses to bg",
              bgcolor(out.get("input")) == want)
        check("light render: catalog cell (Show Background) collapses to bg",
              bgcolor(out.get("catalog")) == want)
        check("light render: inline-expanded quote collapses to bg",
              bgcolor(out.get("inline")) == want)
        print("light probe:", json.dumps(out, sort_keys=True))
        n = total[0]
        print("%d/%d checks passed" % (n - len(fails), n))
        app.quit()

    # phase1 re-checks every 200ms until the probe lands; start at load+800ms
    QTimer.singleShot(800, phase1)
    QTimer.singleShot(20000, app.quit)   # hard bound so a hang can't wedge us
    app.exec()
    srv.shutdown()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
