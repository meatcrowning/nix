#!/usr/bin/env python3
"""Headless check of surfer's Instagram "save original image" context action.

Two halves, both offscreen and never near his live browser:

  1. The page-side resolver (IG_RESOLVE_JS): loaded against a real offscreen
     QtWebEngine page whose <img> carries a downscaled `src` plus a `srcset`
     with a larger candidate, and an overlay <div> painted ON TOP of the image
     (the case that swallows the right-click on a real post). Asserts the
     resolver walks past the overlay to the <img> and returns the LARGEST
     srcset candidate, not the rendered src.

  2. The UrlDownloader bridge: a real image served slowly over loopback is
     downloaded by UrlDownloader.save(), and we assert the file lands in the
     Downloads dir with a repaired extension and that the Downloads bridge saw a
     completion toast carrying the file path (identical UX to a normal save).

Plus a wiring drift-guard over Main.qml.

Run it after touching IG_RESOLVE_JS / UrlDownloader in main.py or the Instagram
block in Main.qml's showContextMenu.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # no way back to his session
os.environ.pop("DISPLAY", None)


# ---- borrow the packaged wrapper's env, exactly as download-test.py does ------
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

# scratch: nothing here touches the user's dirs or his running browser
scratch = Path(tempfile.mkdtemp(prefix="surfer-ig-"))
for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    d = scratch / var.lower()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(d)
dl_home = scratch / "Downloads"
dl_home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(scratch)

sys.path.insert(0, str(HERE.parent))          # surfer's main.py
from PySide6.QtCore import QUrl, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication                                      # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage           # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView                           # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                           # noqa: E402

import main as surfer                          # noqa: E402  (main() is guarded)


# ---- a 1x1 PNG served for every candidate, plus the resolver test page --------
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")

FILE_BYTES = 200 * 1024
CHUNK = 8 * 1024
CHUNK_PAUSE = 0.05


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/post":
            # An <img> whose rendered src is the small candidate, srcset offering
            # a larger one, and an overlay div painted over the whole thing that
            # captures pointer events (the real-post right-click swallow).
            body = (
                b"<html><head><meta name=viewport content='width=800'>"
                b"<style>*{margin:0;padding:0}"
                b"#wrap{position:relative;width:400px;height:400px}"
                b"img{width:400px;height:400px}"
                b".ov{position:absolute;inset:0;z-index:5}</style></head><body>"
                b"<div id=wrap>"
                b"<img src='/img?w=320' "
                b"srcset='/img?w=320 320w, /img?w=640 640w, /img?w=1080 1080w'>"
                b"<div class=ov></div>"
                b"</div></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/img":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_1x1)))
            self.end_headers()
            self.wfile.write(PNG_1x1)
        elif path == "/photo":
            # an extensionless path served as jpeg (the twitter/instagram case:
            # the save name must be repaired to .jpg from the Content-Type)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(FILE_BYTES))
            self.end_headers()
            sent = 0
            while sent < FILE_BYTES:
                n = min(CHUNK, FILE_BYTES - sent)
                self.wfile.write(b"\x7f" * n)
                self.wfile.flush()
                sent += n
                time.sleep(CHUNK_PAUSE)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % port


# ---- a spy over the real Downloads bridge (no notify-send offscreen) ----------
class SpyDownloads(surfer.Downloads):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sends = []

    def _send(self, key, title, body, value, persist=False, path=None):
        rid = self._ids.get(key)
        assigned = len(self.sends) + 1
        self.sends.append({"key": key, "title": title, "value": value,
                           "persist": persist, "path": path, "rid": rid})
        self._ids[key] = assigned


def pump(ms=60):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on %r, not offscreen" % app.platformName())
    QtWebEngineQuick.initialize()
    profile = QWebEngineProfile("ig-test", app)

    ok = True

    # -- 1. resolver picks the largest srcset candidate, through the overlay ----
    # A real, sized view: elementsFromPoint needs a laid-out viewport, so the
    # click coords land inside the 400x400 image (offscreen platform — no window
    # ever reaches his screen).
    view = QWebEngineView()
    view.setPage(QWebEnginePage(profile, view))
    view.resize(800, 800)
    view.show()
    page = view.page()
    page.load(QUrl(BASE + "/post"))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and page.url().path() != "/post":
        pump()
    pump(400)  # let layout settle

    js = surfer.IG_RESOLVE_JS.replace("__X__", "200").replace("__Y__", "200")
    result = {"v": None, "done": False}

    def cb(v):
        result["v"], result["done"] = v, True

    page.runJavaScript(js, 0, cb)
    d2 = time.monotonic() + 10
    while not result["done"] and time.monotonic() < d2:
        pump()

    got = result["v"] or ""
    want_tail = "/img?w=1080"
    r_ok = got.endswith(want_tail)
    ok &= r_ok
    print(("  ok   " if r_ok else "  FAIL ")
          + "resolver returns largest srcset candidate: %r" % got)

    # a point over the overlay resolves to the same image (overlay swallow case)
    result = {"v": None, "done": False}
    page.runJavaScript(js, 0, cb)
    d2 = time.monotonic() + 10
    while not result["done"] and time.monotonic() < d2:
        pump()
    o_ok = (result["v"] or "").endswith(want_tail)
    ok &= o_ok
    print(("  ok   " if o_ok else "  FAIL ")
          + "resolver walks past the overlay to the <img>")

    # -- 2. UrlDownloader.save writes the file + fires the completion toast -----
    dl = SpyDownloads(app)
    saver = surfer.UrlDownloader(dl, str(dl_home), app)
    saver.set_user_agent("test-agent")
    saver.save(BASE + "/photo", BASE + "/post")

    d3 = time.monotonic() + 30
    while time.monotonic() < d3 and not [s for s in dl.sends
                                         if s["title"].startswith("download ")]:
        pump(120)

    completes = [s for s in dl.sends if s["title"] == "download complete"]
    c_ok = len(completes) == 1
    ok &= c_ok
    print(("  ok   " if c_ok else "  FAIL ")
          + "one completion toast for the saved image (%d)" % len(completes))

    if completes:
        p = completes[-1]["path"] or ""
        name_ok = p.endswith(".jpg") and os.path.dirname(p) == str(dl_home)
        ok &= name_ok
        print(("  ok   " if name_ok else "  FAIL ")
              + "saved into Downloads with repaired .jpg extension: %r"
              % os.path.basename(p))
        size_ok = os.path.exists(p) and os.path.getsize(p) == FILE_BYTES
        ok &= size_ok
        print(("  ok   " if size_ok else "  FAIL ")
              + "file on disk is the full %d bytes" % FILE_BYTES)
        prog = [s for s in dl.sends if s["title"].startswith("downloading ")]
        print("     (progress toasts during the slow save: %d)" % len(prog))

    # a second save of the same URL must not overwrite the first
    saver.save(BASE + "/photo", BASE + "/post")
    d3 = time.monotonic() + 30
    while time.monotonic() < d3 and len([s for s in dl.sends
                                         if s["title"] == "download complete"]) < 2:
        pump(120)
    comps = [s for s in dl.sends if s["title"] == "download complete"]
    if len(comps) >= 2:
        p1, p2 = comps[-2]["path"], comps[-1]["path"]
        uniq_ok = p1 != p2 and "(1)" in os.path.basename(p2 or "")
        ok &= uniq_ok
        print(("  ok   " if uniq_ok else "  FAIL ")
              + "second save does not overwrite: %r" % os.path.basename(p2 or ""))

    # -- 3. Main.qml wiring drift-guard ----------------------------------------
    print("\n-- Main.qml wiring --")
    qml = (HERE.parent / "qml" / "Main.qml").read_text(encoding="utf-8")
    checks = [
        ("has isInstagram() host check",     "function isInstagram(url)" in qml),
        ("has saveInstagramOriginal()",      "function saveInstagramOriginal(view" in qml),
        ("resolver runs on the view with substituted coords",
         bool(re.search(r"igResolveJs\.replace\(\"__X__\".*replace\(\"__Y__\"", qml))),
        ("resolved URL goes to ImgDownload.save",
         "ImgDownload.save(" in qml),
        ("empty result -> ImgDownload.notFound (no silent fail)",
         "ImgDownload.notFound(" in qml),
        ("offers 'Save original image...' on instagram",
         "Save original image..." in qml),
        ("snapshot carries view-relative viewPos",
         "viewPos:" in qml),
    ]
    for label, cond in checks:
        ok &= cond
        print(("  ok   " if cond else "  FAIL ") + label)

    print("\n" + ("ok   : instagram-image test PASSED" if ok
                  else "FAIL : see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
