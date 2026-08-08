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
  5. FONT INHERIT: unstyled page text takes the desktop face at the desktop
     size, a page's own font styling beats the layer, and a subframe gets the
     fonts-only body — the face, never the dark filter (no double-invert);
  6. FORCE: opting the site into the system-font override imposes the family
     over the page's own styling while its font-size survives (family only).

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
      hasRefresh: typeof window.__surferPageStyleRefresh === 'function'
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
        check("unstyled text inherits the desktop font at the desktop size",
              "More Perfect DOS VGA" in (out.get("u") or "")
              and "15px" in (out.get("u") or ""))
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
        # phase 4: the per-site FORCE — family imposed over the page's own
        # styling, the page's size kept (family only, DESIGN.md 16)
        dm.toggleSystemFontSite(base)
        view.runJavaScript("window.__surferPageStyleRefresh()", lambda r: None)
        QTimer.singleShot(400, phase4)

    def phase4():
        view.runJavaScript(
            "document.title=JSON.stringify({s:(function(){"
            "var c=getComputedStyle(document.getElementById('s'));"
            "return c.fontFamily+'|'+c.fontSize;})()});",
            lambda r: None)
        QTimer.singleShot(400, phase4b)

    def phase4b():
        read_title()
        check("per-site force imposes the family but keeps the page's size",
              "More Perfect DOS VGA" in (out.get("s") or "")
              and "20px" in (out.get("s") or ""))
        print("probe:", json.dumps(out, sort_keys=True))
        n = 11
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
