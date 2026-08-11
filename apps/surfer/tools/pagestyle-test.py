#!/usr/bin/env python3
"""Offscreen regression test for surfer's dark-mode / system-font INJECTION
PATH — the fix for "the theme only lands AFTER images finish loading".

Before this change the dark-mode <style> was injected per-view at
`LoadSucceededStatus` (load-finished), so the page painted light first and
flipped dark only once images and scripts had finished — the reported bug.
It now rides a profile-level document-creation courier (PAGE_STYLE_RUNTIME_JS
+ PageStyleHandler on the `surferstyle://` scheme) that adopts the style as a
constructed CSSStyleSheet before the first frame.

This harness stands up a real offscreen QtWebEngine profile carrying that
courier, points it at a local http server, and asserts:

  1. the theme is already applied AT PARSE TIME and in the FIRST frame — the
     page's own inline (document-start) probe reads the invert filter on
     <html>, so the fix is that the style is on the page before it paints,
     not after images;
  2. the "late" (settled) state still holds the filter, and the refresh hook
     exists;
  3. LIVE refresh: changing brightness and re-asking the courier updates an
     already-painted page with no reload;
  4. STRIP: turning dark mode off and refreshing strips the dark filter
     (filter back to 'none');
  5. FONT INHERIT: unstyled page text takes the desktop face — the pick's
     size-adjusted web TWIN, a real installed family (see below) — at the
     desktop's apparent size: the layer divides by the twin's 1.14x factor,
     so its ink matches the raw 15px face, and CRISP (0 antialiased grey
     pixels); a page's own font styling beats the layer, and a subframe gets
     the fonts-only body — the face, never the dark filter (no double-invert);
  6. FORCE: the system-font force (GLOBAL by default, per-site exceptions)
     imposes the family over the page's own styling while its font-size
     survives (family only), the forced text renders at the site's own size
     with the proportional x-height (twin@N ink = the raw face at N x 1.14)
     and CRISP (0 grey), and icon-font elements are carved out.

The pick is imposed by a REAL installed face — its size-adjusted web twin
" (web)", outlines/advances/metrics pre-scaled 1.14x
(home/pkgs/desktop/font-files/scale-vga.py) — never a `src:local()`
@font-face alias: Chromium grayscale-antialiases any @font-face-resolved
face and ignores the fontconfig `antialias=false` pin, which softened every
web glyph (970147b's size-adjust alias, dropped 2026-08-09 in 310cdc3). Naming
a real face keeps the AA under fontconfig's control — and since his board
decision 2026-08-10 surfer PINS the twin antialias=true (home/prog/surfer.nix),
so off-grid web text goes soft instead of autohint-striped. The grey checks
below are the regression guard for that soft render; the ink checks guard the
parity the twin restores. (The alias could not be turned off at all; the real
face can, which is why the alias route is still wrong.)

Deliberately only the page-style courier is installed here — cosmetic
ad-blocking has its own harness (cosmetic-test.py) and must not interfere.

    tools/pagestyle-test.py        # exits 0 on pass, 1 on failure
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
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

from PySide6.QtCore import QObject, QTimer, QUrl, Slot                # noqa: E402
from PySide6.QtGui import QGuiApplication                             # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                       # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineUrlScheme, QWebEngineScript  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                 # noqa: E402

# The two probes are INLINE and EARLY — both fire before load-finished, which
# is exactly what the old code could not provide:
#   __early  — read while the parser is still inside <head>, before <body>
#   __frame  — read in the first requestAnimationFrame (the frame before which
#              nothing has been shown)
INDEX = b"""<!doctype html><html><head><title>t</title>
<script>
  window.__early = '';
  try { window.__early = getComputedStyle(document.documentElement).filter || 'none'; }
  catch(e){ window.__early = 'ERR'; }
  window.__frame = 'pending';
  requestAnimationFrame(function(){
    try { window.__frame = getComputedStyle(document.documentElement).filter || 'none'; }
    catch(e){ window.__frame = 'ERR'; }
  });
</script>
</head><body>
<div id="probe" style="background:#fff">content</div>
<p id="u">unstyled text</p>
<p id="s" style="font-family:serif;font-size:20px">page-styled text</p>
<span id="ic" class="material-icons" style="font-family:'Material Icons'">star</span>
<iframe id="fr" src="/f.html"></iframe>
<script src="/app.js"></script>
</body></html>"""

# The subframe: takes the fonts-only body ('f' on surferstyle://) — its text
# must inherit the desktop font while the dark filter must NOT run here (the
# top frame's html filter already composites over it).
FRAME = b"""<!doctype html><html><head><title>f</title></head>
<body><p id="fu">frame text</p></body></html>"""

APP_JS = b"""\
setTimeout(function(){
  function f(){ try { return getComputedStyle(document.documentElement).filter || 'none'; }
               catch(e){ return 'ERR'; } }
  function cs(id, d){ try { d = d || document; var e = d.getElementById(id);
      var c = d.defaultView.getComputedStyle(e);
      return c.fontFamily + '|' + c.fontSize; } catch(e){ return 'ERR'; } }
  // ink width of 'x' at (family, size) - the pixel-level check. Inherited
  // text renders at the desktop's APPARENT size (the web twin's ink = the
  // raw 15px face); forced site text renders at the SITE's size with the
  // proportional x-height (twin@N ink = the raw face at N x 1.14) - the
  // twin is a real face, no size-adjust, so neither is scaled by CSS.
  function ink(fam, size){
    var c = document.createElement('canvas'); c.width=200; c.height=80;
    var g = c.getContext('2d');
    g.fillStyle='#000'; g.font = size + 'px ' + fam; g.textBaseline='alphabetic';
    g.fillText('x', 10, 60);
    var d = g.getImageData(0,0,200,80).data;
    var minX=200, maxX=-1;
    for (var y=0;y<80;y++) for (var xx=0;xx<200;xx++){
      if (d[(y*200+xx)*4+3] > 40){ if (xx<minX)minX=xx; if (xx>maxX)maxX=xx; }
    }
    return maxX<0 ? 0 : maxX-minX+1;
  }
  // CRISPNESS: count antialiased edge pixels (alpha strictly between 0 and
  // 255) when rasterising text at (family, size). A pixel-exact aliased face
  // honouring the fontconfig antialias=false pin renders ONLY fully-opaque or
  // fully-transparent pixels - 0 grey. An @font-face alias forced grayscale-AA
  // and came back ~60-80% grey; this is the regression guard for that.
  function grey(fam, size){
    var c = document.createElement('canvas'); c.width=200; c.height=80;
    var g = c.getContext('2d');
    g.fillStyle='#000'; g.font = size + 'px ' + fam; g.textBaseline='alphabetic';
    g.fillText('surf', 10, 60);
    var d = g.getImageData(0,0,200,80).data, n=0;
    for (var i=0;i<d.length;i+=4){ var a=d[i+3]; if (a>0 && a<255) n++; }
    return n;
  }
  // The force is EXCEPTED for this host during phase1 (un-excepted in phase4),
  // so the #s element still reads its own serif here - its forced-face ink and
  // crispness are measured in phase4, after the force applies. This probe only
  // measures the always-on inherit layer (#u).
  var cu = cs('u').split('|');
  var fdoc = null, ffilter = 'ERR';
  try { fdoc = document.getElementById('fr').contentDocument;
        ffilter = fdoc.defaultView.getComputedStyle(fdoc.documentElement).filter || 'none'; }
  catch(e){}
  document.title = JSON.stringify({
      early: window.__early || 'unset',
      frame: window.__frame || 'unset',
      late: f(),
      u: cs('u'),
      s: cs('s'),
      fu: fdoc ? cs('fu', fdoc) : 'ERR',
      ffilter: ffilter,
      hasRefresh: typeof window.__surferPageStyleRefresh === 'function',
      uInk: ink(cu[0], parseFloat(cu[1])),
      raw15Ink: ink('"More Perfect DOS VGA"', 15),
      uGrey: grey(cu[0], parseFloat(cu[1]))
  });
}, 700);
"""


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (APP_JS if self.path == "/app.js"
                else FRAME if self.path == "/f.html" else INDEX)
        ctype = "application/javascript" if self.path == "/app.js" else "text/html"
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
        // the exact line Main.qml uses: cosmetic + page-style couriers together
        Component.onCompleted: userScripts.collection =
            CosmeticInject.scripts.concat(PageStyle.scripts)
    }
    WebEngineView { objectName: "view"; anchors.fill: parent; profile: sharedProfile }
}
"""


class StubCosmetic(QObject):
    """The minimal slot shape CosmeticInjector calls; no ad rules for localhost,
    so the cosmetic courier degrades to empty while the page-style one runs."""

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
    for name in (b"surferstyle", b"surfercos"):
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

    # scratch state: never read or write the user's prefs.json
    scratch = Path(tempfile.mkdtemp(prefix="surfer-pagestyle-"))
    os.environ["XDG_STATE_HOME"] = str(scratch)

    import main as surfer                                            # noqa: E402

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/p.html" % srv.server_address[1]

    prefs = surfer.Prefs(app)
    dm = surfer.DarkMode(prefs, app)
    dm.setEnabled(True)          # on, 100/100 — a hostless file:// has no host,
    dm.setBrightness(100)        # so serve over loopback where isSiteEnabled true
    dm.setContrast(100)
    # The system-font force is GLOBAL by default; except this host so phases
    # 0-3 exercise the inherit layer alone. Phase 4 un-excepts it to test the
    # force. The default itself is asserted in phase4b (isSystemFontSite).
    dm.toggleSystemFontSite("http://127.0.0.1/")
    ps = surfer.PageStyle(app)
    handler = surfer.PageStyleHandler(dm, app)
    cosinject = surfer.CosmeticInjector(StubCosmetic(app), app)

    eng = QQmlApplicationEngine()
    eng.warnings.connect(lambda ws: [print("QML:", w.toString()) for w in ws])
    eng.rootContext().setContextProperty("PageStyle", ps)
    eng.rootContext().setContextProperty("CosmeticInject", cosinject)
    eng.loadData(QML.encode(), QUrl("qrc:/harness.qml"))
    if not eng.rootObjects():
        print("FAIL: harness QML did not load")
        return 1
    ro = eng.rootObjects()[0]
    prof = ro.findChild(QObject, "sharedProfile")
    prof.installUrlSchemeHandler(b"surferstyle", handler)
    prof.installUrlSchemeHandler(b"surfercos", cosinject)
    view = ro.findChild(QObject, "view")

    out = {}
    fails = []

    def check(label, ok):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    def read_title():
        t = view.property("title")
        if isinstance(t, str) and t:
            try:
                out.update(json.loads(t))
                return True
            except Exception:
                pass
        return False

    # stage 0: load the page with dark ON
    QTimer.singleShot(300, lambda: view.setProperty("url", QUrl(base)))
    # stage 1: after the probe reports, assert applied-before-paint, then do the
    # live-refresh and strip phases.
    def phase1():
        if not read_title():
            QTimer.singleShot(200, phase1)
            return
        f = out.get("late") or ""
        check("dark applied at parse time, before the page body painted",
              "invert(1) hue-rotate(180deg)" in (out.get("early") or ""))
        check("dark applied at the first frame",
              "invert(1) hue-rotate(180deg)" in (out.get("frame") or ""))
        check("theme still applied after everything settled", "invert(" in f)
        check("live refresh hook installed", out.get("hasRefresh") is True)
        # the font-inherit layer: unstyled text takes the desktop face at the
        # desktop size; a page's own font styling beats the layer (@layer
        # loses to any unlayered rule); the subframe inherits the face too but
        # never the dark filter.
        #
        # The face is the pick's web TWIN (a real installed family) - NO
        # @font-face alias (dropped 310cdc3): the alias forced grayscale-AA
        # and blurred every web glyph. Inherited text renders at the desktop's
        # apparent size (twin@13.158px ink = the raw 15px face). At that
        # off-grid size the antialias=true pin (his 2026-08-10 decision) renders
        # it SOFT, not the old striped-aliased render - so grey > 0 here is the
        # regression guard. A SITE-styled run keeps its own numbers and face.
        check("unstyled text inherits the pick's web twin (real family, no @font-face)",
              "(web)" in (out.get("u") or "")
              and "More Perfect DOS VGA" in (out.get("u") or ""))
        check("inherited text renders the desktop's apparent size (twin ink = raw 15px)",
              abs((out.get("uInk") or 0) - (out.get("raw15Ink") or 0)) <= 1)
        check("inherited text renders soft-AA off-grid (antialias=true, not striped)",
              (out.get("uGrey") if out.get("uGrey") is not None else 0) > 0)
        check("a page's own font styling beats the inherit layer",
              "serif" in (out.get("s") or "").split("|")[0]
              and "More Perfect DOS VGA" not in (out.get("s") or "")
              and "20px" in (out.get("s") or ""))
        check("subframe inherits the desktop font (fonts-only body)",
              "More Perfect DOS VGA" in (out.get("fu") or ""))
        check("subframe never takes the dark filter (no double-invert)",
              (out.get("ffilter") or "x") == "none")
        # phase 2: change brightness and live-refresh the open page
        dm.setBrightness(150)
        view.runJavaScript("window.__surferPageStyleRefresh()", lambda r: None)
        QTimer.singleShot(400, phase2)

    def phase2():
        # ask the page to report its current filter into the title again
        view.runJavaScript(
            "document.title=JSON.stringify({late:"
            "(getComputedStyle(document.documentElement).filter||'none')});",
            lambda r: None)
        QTimer.singleShot(400, phase2b)

    def phase2b():
        read_title()
        check("brightness change live-refreshed an open page (brightness(1.5))",
              "brightness(1.5)" in (out.get("late") or ""))
        # phase 3: turn dark OFF and refresh — the sheet must be STRIPPED
        dm.setEnabled(False)
        view.runJavaScript("window.__surferPageStyleRefresh()", lambda r: None)
        QTimer.singleShot(400, phase3)

    def phase3():
        view.runJavaScript(
            "document.title=JSON.stringify({late:"
            "(getComputedStyle(document.documentElement).filter||'none')});",
            lambda r: None)
        QTimer.singleShot(400, phase3b)

    def phase3b():
        read_title()
        check("disabling dark mode strips the theme from an open page (filter 'none')",
              (out.get("late") or "x") == "none")
        # phase 4: the FORCE (global by default; this host was excepted at
        # setup, so un-excepting it restores the default state) — family
        # imposed over the page's own styling, the page's size kept (family
        # only, DESIGN.md 16), icon-font elements carved out.
        dm.toggleSystemFontSite(base)
        view.runJavaScript("window.__surferPageStyleRefresh()", lambda r: None)
        QTimer.singleShot(400, phase4)

    def phase4():
        # Read the FORCED element AFTER the force applies, and canvas-measure its
        # ink + crispness at its computed (family,size) - the app.js probe ran
        # at phase1 while this host was still excepted, so it only ever saw the
        # page's own serif. This is where the forced pixel face is measured.
        view.runJavaScript(
            "document.title=JSON.stringify((function(){"
            "function cs(id){var c=getComputedStyle(document.getElementById(id));"
            "return c.fontFamily+'|'+c.fontSize;}"
            "function ink(fam,size){var c=document.createElement('canvas');"
            "c.width=200;c.height=80;var g=c.getContext('2d');g.fillStyle='#000';"
            "g.font=size+'px '+fam;g.textBaseline='alphabetic';g.fillText('x',10,60);"
            "var d=g.getImageData(0,0,200,80).data,mn=200,mx=-1;"
            "for(var y=0;y<80;y++)for(var xx=0;xx<200;xx++){"
            "if(d[(y*200+xx)*4+3]>40){if(xx<mn)mn=xx;if(xx>mx)mx=xx;}}"
            "return mx<0?0:mx-mn+1;}"
            "function grey(fam,size){var c=document.createElement('canvas');"
            "c.width=200;c.height=80;var g=c.getContext('2d');g.fillStyle='#000';"
            "g.font=size+'px '+fam;g.textBaseline='alphabetic';g.fillText('surf',10,60);"
            "var d=g.getImageData(0,0,200,80).data,n=0;"
            "for(var i=0;i<d.length;i+=4){var a=d[i+3];if(a>0&&a<255)n++;}return n;}"
            "var f=cs('s').split('|');var sz=parseFloat(f[1]);"
            "return {s:cs('s'),ic:cs('ic'),"
            "sInk:ink(f[0],sz),raw22_8Ink:ink('\"More Perfect DOS VGA\"',22.8),"
            "sGrey:grey(f[0],sz)};})());",
            lambda r: None)
        QTimer.singleShot(400, phase4b)

    def phase4b():
        read_title()
        check("the force is GLOBAL by default (an un-excepted host is on)",
              dm.isSystemFontSite("http://somewhere-never-toggled.example/"))
        # zoom compensation: the inherit layer divides its size by the shared
        # page zoom AND by the web twin's 1.14x factor, so inherited text
        # holds the desktop's DEVICE pixel size. 0.826446... = 1/1.21 (two
        # Ctrl+- steps); at zoom 1 the size is 15/1.14 = 13.1579 CSS px, and
        # at 0.826 zoom 13.1579/0.826446 = 15.9211 CSS px — which in the
        # 1.14x face renders the desktop's 15 device px.
        class FakeZoom:
            level = 1.0 / 1.21
        dmz = surfer.DarkMode(prefs, dm, zoom=FakeZoom())
        check("inherit layer zoom-compensates (15 device px at 0.826 zoom)",
              "font-size:15.9211px" in dmz._inherit_css())
        check("inherit layer divides by the twin's factor at zoom 1 (13.1579px)",
              "font-size:13.1579px" in dm._inherit_css())
        check("no @font-face alias in the page or subframe body (crisp real family)",
              "@font-face" not in dm.css(base)
              and "@font-face" not in dm.fontsCss(base))
        check("force imposes the web twin but keeps the page's size",
              "(web)" in (out.get("s") or "")
              and "More Perfect DOS VGA" in (out.get("s") or "")
              and "20px" in (out.get("s") or ""))
        check("forced site text reads the proportional x-height (twin@20 ink = raw 22.8px)",
              abs((out.get("sInk") or 0) - (out.get("raw22_8Ink") or 0)) <= 1)
        check("forced site text renders soft-AA off-grid (antialias=true, not striped)",
              (out.get("sGrey") if out.get("sGrey") is not None else 0) > 0)
        check("icon-font elements are carved out of the force",
              "More Perfect DOS VGA" not in (out.get("ic") or "ERR")
              and "Material Icons" in (out.get("ic") or ""))
        print("probe:", json.dumps(out, sort_keys=True))
        n = 20
        print("%d/%d checks passed" % (n - len(fails), n))
        app.quit()

    # phase1 re-checks every 200ms until the probe lands; start it at load+700ms
    QTimer.singleShot(800, phase1)
    QTimer.singleShot(15000, app.quit)   # hard bound so a hang can't wedge us
    app.exec()
    srv.shutdown()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
