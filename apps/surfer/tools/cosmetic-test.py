#!/usr/bin/env python3
"""Offscreen regression test for surfer's cosmetic ad-blocking INJECTION PATH.

Not a test of the filter engine — of the courier. It stands up a real
QtWebEngine profile carrying `COSMETIC_RUNTIME_JS` (the profile-level
document-creation script) plus `CosmeticInjector` on the `surfercos://` scheme,
points it at a local http server, and asserts what the old load-finished
injection could not provide:

  1. the rules are in place BEFORE THE PAGE PAINTS - checked twice, at the
     page's own parse-time inline script and again in its first
     requestAnimationFrame (the frame before which nothing has been shown);
  2. an element inserted LONG AFTER load, carrying a class the page did not
     have when the generic set was narrowed, gets hidden (MutationObserver);
  3. a history.pushState route change re-runs the pass against the NEW url's
     rules (the "all of YouTube after the first click" case);
  4. a `:has()` selector survives the pipe verbatim (Chromium 6.11 has it
     natively; nothing on this path may sanitise selectors);
  5. procedural filters are unwrapped and applied - `:has-text`, `:upward` with
     a `style` action applied BY ATTRIBUTE rather than inline, and an unknown
     operator hiding nothing rather than everything;
  6. a 1500-node mutation storm trips the observer's polling fallback and an ad
     slot arriving during it is still hidden.

The rule source is a STUB with `Cosmetic`'s slot signatures, deliberately: the
adblock-rust engine has no rules for localhost, and this harness is about the
delivery mechanism, not about which selectors the engine emits.

    tools/cosmetic-test.py        # exits 0 on pass, 1 on failure
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer, QUrl, Slot                # noqa: E402
from PySide6.QtGui import QGuiApplication                             # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                       # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineUrlScheme               # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                 # noqa: E402

# ---- the page under test ----------------------------------------------------
# The two probes have to be INLINE and EARLY: __early is read while the parser
# is still inside <body>, __frame in the first frame callback. Both are the
# honest before-paint tests; a check after load would prove nothing.
INDEX = b"""<!doctype html><html><head><title>t</title>
<script>
  window.__frame = 'pending';
  requestAnimationFrame(function(){
    var e = document.getElementById('banner');
    window.__frame = e ? getComputedStyle(e).display : 'missing';
  });
</script>
</head><body>
<div class="ad-banner" id="banner">AD</div>
<script>
  window.__early = getComputedStyle(document.getElementById('banner')).display;
  window.__pruned = !JSON.parse('{"adPlacements":[1],"ok":1}').adPlacements;
</script>
<div class="card"><span class="sponsored">s</span></div>
<div class="card" id="keep">real content</div>
<div class="promo" id="promo">Sponsored message</div>
<div class="promo" id="promokeep">ordinary message</div>
<div id="up"><span class="deep">x</span></div>
<div class="safe" id="safe">must survive an unknown operator</div>
<div id="content">hello</div>
<script src="/app.js"></script>
</body></html>"""

APP_JS = b"""
setTimeout(function(){
  var d = document.createElement('div');
  d.className = 'lazy-ad'; d.id = 'lazy'; d.textContent = 'LAZY';
  document.body.appendChild(d);
}, 200);
setTimeout(function(){
  history.pushState({}, '', '/route2');
  var d = document.createElement('div');
  d.className = 'spa-ad'; d.id = 'spa'; d.textContent = 'SPA';
  document.body.appendChild(d);
}, 900);
// A mutation STORM: enough records in one go to trip the observer's escape
// hatch (it disconnects and falls back to polling). The ad slot that arrives
// afterwards must still get hidden by the poll, with no observer running.
setTimeout(function(){
  for (var i = 0; i < 1500; i++) {
    var n = document.createElement('div'); n.className = 'noise' + i;
    document.body.appendChild(n);
  }
}, 1200);
setTimeout(function(){
  var d = document.createElement('div');
  d.className = 'storm-ad'; d.id = 'stormad'; d.textContent = 'STORM';
  document.body.appendChild(d);
}, 1700);
// The page reports its own verdict through document.title: PySide6 6.11 will
// not marshal a Python callable into WebEngineView.runJavaScript's QJSValue
// callback, and `title` is a plain readable QML property.
setTimeout(function(){
  function d(sel){ var e = document.querySelector(sel);
                   return e ? getComputedStyle(e).display : 'missing'; }
  function s(sel, prop){ var e=document.querySelector(sel);
                         return e ? getComputedStyle(e)[prop] : 'missing'; }
  document.title = JSON.stringify({
      early: window.__early || 'unset', frame: window.__frame || 'unset',
      pruned: !!window.__pruned,
      banner: d('#banner'), card: d('.card:has(> .sponsored)'),
      keep: d('#keep'), lazy: d('#lazy'), spa: d('#spa'),
      promo: d('#promo'), promokeep: d('#promokeep'), storm: d('#stormad'),
      up: s('#up', 'outlineColor') + '/' + s('#up', 'outlineStyle'),
      safe: d('#safe'),
      inline: document.getElementById('promo')
              ? document.getElementById('promo').getAttribute('style') : 'gone',
      href: location.href });
}, 3200);
"""


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = APP_JS if self.path == "/app.js" else INDEX
        ctype = "application/javascript" if self.path == "/app.js" else "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


# ---- the stub rule source ---------------------------------------------------
CALLS = {"s": [], "g": [], "p": []}


def _style(css, script=""):
    """Shaped byte-for-byte like Cosmetic._inject's output: `var css=<json
    literal>` and the trailing `try{...}catch(e){}` are the two seams
    CosmeticInjector reads the CSS and the scriptlet back out of."""
    js = ("(function(){try{var css=%s;if(css){"
          "var s=document.getElementById('surfer-cosmetic')"
          "||document.createElement('style');s.id='surfer-cosmetic';"
          "s.textContent=(s.textContent||'')+css;"
          "(document.head||document.documentElement).appendChild(s);}"
          % json.dumps(css))
    if script:
        js += "try{%s}catch(e){}" % script
    return js + "}catch(e){}})();"


# uBO's json-prune shape: shadow a page global before the page reads it. Inert
# unless it runs at document-start in the MAIN world.
SCRIPTLET = ("(function(){var o=JSON.parse;"
             "JSON.parse=function(t,r){var v=o(t,r);"
             "if(v&&v.adPlacements)delete v.adPlacements;return v;};})();")


class StubCosmetic(QObject):
    """The slots CosmeticInjector calls on the real Cosmetic."""

    @Slot(str, result=str)
    def specificJs(self, url):
        CALLS["s"].append(url)
        if "/route2" in url:
            return _style(".spa-ad{display:none!important}")
        # `:has()` goes through untouched — it is a native CSS selector here
        return _style(".ad-banner{display:none!important}\n"
                      ".card:has(> .sponsored){display:none!important}",
                      SCRIPTLET)

    @Slot(str, "QVariantList", "QVariantList", result=str)
    def genericJs(self, url, classes, ids):
        CALLS["g"].append((url, list(classes), list(ids)))
        cl = [str(c) for c in classes]
        if "lazy-ad" in cl:
            return _style(".lazy-ad{display:none!important}")
        if "storm-ad" in cl:
            return _style(".storm-ad{display:none!important}")
        return ""

    @Slot(str, result=str)
    def proceduralJson(self, url):
        """adblock-rust hands these back as a Vec of JSON STRINGS — so the stub
        returns them that way, to exercise the unwrapping in _procedural."""
        CALLS["p"].append(url)
        return json.dumps([
            # `.promo:has-text(Sponsored)` — hide
            json.dumps({"selector": [{"type": "css-selector", "arg": ".promo"},
                                     {"type": "has-text", "arg": "Sponsored"}]}),
            # `.deep:upward(1)` — style, applied by attribute
            json.dumps({"selector": [{"type": "css-selector", "arg": ".deep"},
                                     {"type": "upward", "arg": "1"}],
                        "action": {"type": "style", "arg": "outline:1px solid red"}}),
            # an operator we do not implement must hide NOTHING
            json.dumps({"selector": [{"type": "css-selector", "arg": ".safe"},
                                     {"type": "no-such-operator", "arg": "x"}]}),
        ])


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
        Component.onCompleted: userScripts.collection = CosmeticInject.scripts
    }
    WebEngineView { objectName: "view"; anchors.fill: parent; profile: sharedProfile }
}
"""

def seam_checks(surfer):
    """The two string seams CosmeticInjector reads Cosmetic._inject's output
    apart at. They are a fallback for as long as `Cosmetic` has no `specificCss`
    / `scriptletJs` slot, and they are the one part of this path that a change
    on the engine side can break silently — hence a direct check, including the
    "seam is gone" case, which must report None so the handler can serve the
    fallback marker instead of an empty (i.e. indistinguishable) body."""
    def inject(css, script):
        js = ("(function(){try{var css=%s;if(css){"
              "var s=document.getElementById('surfer-cosmetic')"
              "||document.createElement('style');s.id='surfer-cosmetic';"
              "s.textContent=(s.textContent||'')+css;"
              "(document.head||document.documentElement).appendChild(s);}"
              % json.dumps(css))
        if script:
            js += "try{%s}catch(e){}" % script
        return js + "}catch(e){}})();"

    cases = [
        ("a:has(> b){display:none!important}", "window.x=1;/*}catch(e){}*/"),
        ('.q\\"uote, .b\\\\slash{display:none!important}', ""),
        ("", "alert(1)"),
        ("p{display:none}", "(function(){var o=JSON.parse;JSON.parse=function(){};})();"),
    ]
    ok = all(surfer._css_of(inject(c, x)) == c and surfer._scriptlet_of(inject(c, x)) == x
             for c, x in cases)
    gone = surfer._css_of("garbage") is None and surfer._scriptlet_of("garbage") is None
    return [("the CSS/scriptlet seams survive quotes, backslashes and a "
             "scriptlet containing the terminator", ok),
            ("a MISSING seam reports None, not an empty rule set", gone)]


def main():
    for name in (b"surfercos",):
        sch = QWebEngineUrlScheme(name)
        sch.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        sch.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                     | QWebEngineUrlScheme.Flag.CorsEnabled
                     | QWebEngineUrlScheme.Flag.FetchApiAllowed
                     | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored)
        QWebEngineUrlScheme.registerScheme(sch)

    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)

    import main as surfer                                            # noqa: E402
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    stub = StubCosmetic(app)
    inject = surfer.CosmeticInjector(stub, app)

    eng = QQmlApplicationEngine()
    eng.warnings.connect(lambda ws: [print("QML:", w.toString()) for w in ws])
    eng.rootContext().setContextProperty("CosmeticInject", inject)
    eng.loadData(QML.encode(), QUrl("qrc:/harness.qml"))
    if not eng.rootObjects():
        print("FAIL: harness QML did not load")
        return 1
    ro = eng.rootObjects()[0]
    prof = ro.findChild(QObject, "sharedProfile")
    prof.installUrlSchemeHandler(b"surfercos", inject)
    view = ro.findChild(QObject, "view")

    out = {}

    def collect():
        try:
            out.update(json.loads(view.property("title")))
        except Exception as e:
            print("probe failed:", e, repr(view.property("title")))
        app.quit()

    QTimer.singleShot(300, lambda: view.setProperty("url", QUrl(base + "/")))
    QTimer.singleShot(4400, collect)
    QTimer.singleShot(12000, app.quit)
    app.exec()
    srv.shutdown()

    checks = [
        ("script ran at document-creation, before the page's own parse-time "
         "script", out.get("early") == "none"),
        ("hidden before the first frame", out.get("frame") == "none"),
        ("specific rule applied", out.get("banner") == "none"),
        (":has() selector survived the pipe", out.get("card") == "none"),
        ("a .card WITHOUT the sponsored child is untouched",
         out.get("keep") not in ("none", "missing")),
        ("MutationObserver hid a lazily-inserted slot", out.get("lazy") == "none"),
        ("pushState re-ran the pass with the new url's rules",
         out.get("spa") == "none"),
        ("both urls were asked for", len(CALLS["s"]) >= 2
         and any("/route2" in u for u in CALLS["s"])),
        ("generic pass was narrowed to real page tokens",
         any("ad-banner" in c for _, c, _ in CALLS["g"])),
        ("the scriptlet ran at document-start, main world, before the page "
         "read its own JSON", out.get("pruned") is True),
        ("procedural filters were fetched and unwrapped", bool(CALLS["p"])),
        ("procedural :has-text hid its match", out.get("promo") == "none"),
        ("...and left the non-matching sibling alone",
         out.get("promokeep") not in ("none", "missing")),
        ("procedural :upward + style action applied to the ANCESTOR",
         out.get("up", "").endswith("/solid")),
        ("...by attribute, not inline style", out.get("inline") in (None, "", "gone")),
        ("an unknown procedural operator hides nothing",
         out.get("safe") not in ("none", "missing")),
        ("a slot arriving during a 1500-node mutation storm is still hidden",
         out.get("storm") == "none"),
    ]
    checks += seam_checks(surfer)
    bad = 0
    for label, ok in checks:
        print(("  ok   " if ok else "  FAIL ") + label)
        bad += 0 if ok else 1
    print("probe:", json.dumps(out, sort_keys=True))
    print("specific requests:", CALLS["s"])
    print("generic requests:", [(len(c), len(i)) for _, c, i in CALLS["g"]])
    print("%d/%d checks passed" % (len(checks) - bad, len(checks)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
