#!/usr/bin/env python3
"""Headless check of IG_LAYOUT_JS (main.py) — stacking an opened Instagram
post's sidebar below the media instead of squeezing it beside it.

Two fabricated pages, both offscreen, never near his live browser:

  1. A "post view" page: a role=dialog overlay whose two children sit SIDE BY
     SIDE (a flex row, hashed classes on purpose — the script must not name
     one) — a media div holding a big <img>, and a sidebar div holding a
     header/comments/actions stand-in. Asserts the script finds the split by
     geometry, marks the row container + branches, and the injected style
     collapses it to a column with the media on top, full width.

  2. A normal feed post: media stacked ABOVE a caption, already vertical.
     Asserts the script leaves it alone (no data-surfer-ig-* attributes) —
     the side-by-side test must not fire on an already-stacked layout.

Run after touching IG_LAYOUT_JS in main.py or its wiring in Main.qml
(onLoadingChanged's isInstagram() gate).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # no way back to his session
os.environ.pop("DISPLAY", None)


def _borrow_wrapper_env():
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper to borrow PySide6 and the Qt env from")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("could not find main.py's interpreter in %s" % wrapper)
    py = m.group(1)
    body = "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("#!")
                     and "singleton.py" not in ln
                     and not ln.startswith("exec "))
    out = subprocess.run(["bash", "-c", body + "\nexec env -0\n"],
                         capture_output=True, check=True).stdout
    env = dict(os.environ)
    for entry in out.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        k, v = entry.decode(errors="replace").split("=", 1)
        if k in ("HOME", "PWD", "SHLVL", "_",
                 "QT_QPA_PLATFORM", "WAYLAND_DISPLAY", "DISPLAY"):
            continue
        env[k] = v
    return py, env


if not os.environ.get("_SURFER_IG_REEXEC") and not os.environ.get("SURFER_QTSHELL"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_IG_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

sys.path.insert(0, str(HERE.parent))          # surfer's main.py
from PySide6.QtCore import QUrl, QEventLoop, QTimer          # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView          # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick          # noqa: E402

import main as surfer                          # noqa: E402  (main() is guarded)


# PNG_1x1 stands in for a real photo so the image actually decodes and lays
# out at its declared box size (a broken/data-uri image can end up 0x0).
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")

# A post-view dialog: media (480x480 img) beside a fixed 400px sidebar, both
# hashed classes ("x1qjc9v5"-style, like Instagram's real atomic CSS) so the
# script has nothing to key off but geometry/structure.
POST_HTML = b"""<html><head><meta name=viewport content='width=1000'>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{width:1000px}
  .x1a{display:flex;flex-direction:row;width:900px;height:500px}
  .x2b{width:500px;height:500px;display:flex;align-items:center;justify-content:center}
  .x2b img{width:480px;height:480px}
  .x3c{width:400px;height:500px;overflow-y:scroll}
</style></head><body>
<div role="dialog">
  <div class="x1a">
    <div class="x2b"><img src="/img"></div>
    <div class="x3c"><div class="x4d">username</div><div class="x5e">caption text</div></div>
  </div>
</div>
</body></html>"""

# A normal feed post: media stacked ABOVE the caption/actions — already
# vertical, nothing side-by-side. Must be left untouched.
FEED_HTML = b"""<html><head><meta name=viewport content='width=500'>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{width:500px}
  article{width:470px}
  .y1a{width:470px;height:470px}
  .y1a img{width:470px;height:470px}
  .y2b{width:470px;height:120px}
</style></head><body>
<main role="main"><article>
  <div class="y1a"><img src="/img"></div>
  <div class="y2b">caption + like/comment/share</div>
</article></main>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/post":
            body = POST_HTML
        elif path == "/feed":
            body = FEED_HTML
        elif path == "/img":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_1x1)))
            self.end_headers()
            self.wfile.write(PNG_1x1)
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % port


def pump(ms=60):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def load_and_run(path):
    profile = QWebEngineProfile()
    view = QWebEngineView()
    view.setPage(QWebEnginePage(profile, view))
    view.resize(1000, 900)
    view.show()
    page = view.page()
    page.load(QUrl(BASE + path))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and page.url().path() != path:
        pump()
    pump(300)  # let layout settle

    result = {"v": None, "done": False}

    def cb(v):
        result["v"], result["done"] = v, True

    page.runJavaScript(surfer.IG_LAYOUT_JS, 0, cb)
    d2 = time.monotonic() + 10
    while not result["done"] and time.monotonic() < d2:
        pump()
    pump(500)  # the script's own 250ms debounce before it actually applies

    probe = {"v": None, "done": False}

    def cb2(v):
        probe["v"], probe["done"] = v, True

    page.runJavaScript(
        r"""(function(){
          var root = document.querySelector('[data-surfer-ig-root]');
          var media = document.querySelector('[data-surfer-ig-media]');
          var side = document.querySelector('[data-surfer-ig-side]');
          return JSON.stringify({
            hasRoot: !!root,
            rootFlexDir: root ? getComputedStyle(root).flexDirection : '',
            mediaW: media ? media.getBoundingClientRect().width : -1,
            parentW: media && media.parentElement ?
              media.parentElement.getBoundingClientRect().width : -1,
            hasSide: !!side,
            sideTop: side ? side.getBoundingClientRect().top : -1,
            mediaBottom: media ? media.getBoundingClientRect().bottom : -1,
          });
        })()""", 0, cb2)
    d3 = time.monotonic() + 10
    while not probe["done"] and time.monotonic() < d3:
        pump()
    try:
        return json.loads(probe["v"] or "{}")
    except (TypeError, ValueError):
        return {}


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on %r, not offscreen" % app.platformName())
    QtWebEngineQuick.initialize()

    ok = True

    print("-- opened post (side-by-side media + sidebar) --")
    p = load_and_run("/post")
    checks = [
        ("finds the split and marks a root", p.get("hasRoot") is True),
        ("row container becomes a column", p.get("rootFlexDir") == "column"),
        ("marks the sidebar branch", p.get("hasSide") is True),
        ("media fills its (now full-width) container",
         p.get("mediaW", -1) > 0 and abs(p.get("mediaW", -1) - p.get("parentW", -2)) < 2),
        ("sidebar sits BELOW the media, not beside it",
         p.get("sideTop", -1) >= p.get("mediaBottom", 1e9) - 1),
    ]
    for label, cond in checks:
        ok &= cond
        print(("  ok   " if cond else "  FAIL ") + label + (" (%r)" % p if not cond else ""))

    print("\n-- normal feed post (already stacked) --")
    f = load_and_run("/feed")
    f_ok = f.get("hasRoot") is False and f.get("hasSide") is False
    ok &= f_ok
    print(("  ok   " if f_ok else "  FAIL ")
          + "left untouched, no data-surfer-ig-* attributes: %r" % f)

    # -- wiring drift-guard over Main.qml / main.py --------------------------
    print("\n-- wiring --")
    qml = (HERE.parent / "qml" / "Main.qml").read_text(encoding="utf-8")
    mp = (HERE.parent / "main.py").read_text(encoding="utf-8")
    wchecks = [
        ("main.py defines IG_LAYOUT_JS", "IG_LAYOUT_JS = r" in mp),
        ("exposed as a context property", 'ctx.setContextProperty("igLayoutJs"' in mp),
        ("Main.qml runs it only on instagram, at load-finished",
         bool(re.search(r'win\.isInstagram\("" \+ webview\.url\)\s*\)\s*\n\s*webview\.runJavaScript\(igLayoutJs\)', qml))),
    ]
    for label, cond in wchecks:
        ok &= cond
        print(("  ok   " if cond else "  FAIL ") + label)

    print("\n" + ("ok   : instagram-layout test PASSED" if ok
                  else "FAIL : see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
