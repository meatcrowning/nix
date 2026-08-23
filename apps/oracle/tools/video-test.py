#!/usr/bin/env python3
"""show_video: a watch page becomes a stream, and the card that plays it builds.

Offscreen and local-only. The resolver is a STUB script this test writes, so
yt-dlp is never run and nothing here reaches YouTube or any other site; the one
"direct" video is served off a throwaway HTTP server on 127.0.0.1. It covers
what the tool promises (docs/DESIGN.md §10 — a failure is surfaced, never a
blank card):

  * a direct media URL the server confirms is video IS the stream — no resolver
  * a watch page is resolved, with its title, duration and poster frame
  * a media-looking URL that HEADs as a page falls through to the resolver
  * a resolver that fails, and a resolver that is not installed, both say so
  * a non-http URL is refused before any request
  * VideoDeck/VideoCard build and bind against a real entry (which is also the
    check that QtMultimedia is in this wrapper's QML import path)

    oracle-qtenv python3 tools/video-test.py
"""
import http.server
import json
import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-video-"))
os.environ["ORACLE_IMAGES"] = str(_TMP / "images")

from PySide6.QtCore import QTimer, QUrl, QBuffer, QByteArray       # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage                  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent     # noqa: E402

ARGV = list(sys.argv[1:])                     # before main.py takes it over
sys.argv = [sys.argv[0], "--selftest"]        # temp config/sessions stores
import main as oracle                          # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# ---- a tiny server: one "video", one poster, one page wearing an .mp4 name --
img = QImage(8, 8, QImage.Format.Format_RGB32)
img.fill(0x336699)
_ba = QByteArray()
buf = QBuffer(_ba)
buf.open(QBuffer.OpenModeFlag.WriteOnly)
img.save(buf, "PNG")
buf.close()
PNG = bytes(_ba)


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, ctype, body=b""):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        if self.path.startswith("/clip.mp4"):
            self._send("video/mp4")
        elif self.path.startswith("/liar.mp4"):
            self._send("text/html")     # a PAGE wearing a media URL
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/poster.png"):
            self._send("image/png", PNG)
        elif self.path.startswith("/clip.mp4"):
            self._send("video/mp4", b"\x00" * 16)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def stub(body):
    """Write a resolver stub and point VIDEO_RESOLVER at it."""
    p = _TMP / "ytdlp-stub.sh"
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    oracle.VIDEO_RESOLVER = str(p)


o = oracle.Ollama()
entries = []
o.videoResult.connect(lambda j: entries.append(json.loads(j)))


def run(url, alt="", ms=6000):
    """One show_video call, to completion. `idx` is None: nothing is waiting on
    a tool result here, only the card."""
    entries.clear()
    o._set_busy(True)
    o._show_video(url, alt, None, None, None)
    if not entries:
        loop = QTimer()
        loop.setSingleShot(True)
        loop.timeout.connect(app.quit)
        loop.start(ms)
        o.videoResult.connect(app.quit)
        app.exec()
        o.videoResult.disconnect(app.quit)
    o._set_busy(False)
    return entries[0] if entries else None


# 1. a non-http URL never reaches the network
stub('echo "the resolver must not run" >&2; exit 1')
e = run("file:///etc/passwd")
check("a non-http url is refused before any request",
      e is not None and e.get("ok") is False and "http(s)" in e.get("error", ""),
      json.dumps(e)[:120])

# 2. a direct media URL the server confirms IS the stream — no resolver at all
stub('echo "the resolver must not run" >&2; exit 1')
e = run(BASE + "/clip.mp4", "a clip")
check("a confirmed video URL is the stream itself",
      e is not None and e.get("ok") is True and e.get("src") == BASE + "/clip.mp4"
      and e.get("alt") == "a clip", json.dumps(e)[:160])

# 3. a watch page: resolved, with title, duration and poster frame
INFO = {"title": "A Title", "duration": 213.0, "width": 640, "height": 360,
        "url": "https://stream.test/video.mp4",
        "thumbnail": BASE + "/poster.png", "is_live": False}
stub("cat <<'EOF'\n" + json.dumps(INFO) + "\nEOF")
e = run("https://www.youtube.test/watch?v=abc", "")
check("a watch page resolves to a stream",
      e is not None and e.get("ok") is True
      and e.get("src") == INFO["url"] and e.get("title") == "A Title"
      and e.get("duration") == 213 and e.get("w") == 640,
      json.dumps(e)[:200])
check("...and its poster frame is saved locally",
      bool(e) and bool(e.get("poster")) and os.path.exists(e.get("poster", "")),
      str(e.get("poster") if e else None))
check("...and the resolver's raw fields do not leak to QML",
      bool(e) and "poster_url" not in e)

# 4. a media-looking URL that is really a page falls through to the resolver
stub("cat <<'EOF'\n" + json.dumps(INFO) + "\nEOF")
e = run(BASE + "/liar.mp4")
check("a media-looking URL that HEADs as a page goes to the resolver",
      e is not None and e.get("ok") is True and e.get("src") == INFO["url"],
      json.dumps(e)[:160])

# 5. a resolver that fails says why, in its own words
stub('echo "ERROR: Video unavailable" >&2; exit 1')
e = run("https://www.youtube.test/watch?v=gone")
check("a failed resolve is surfaced with the reason",
      e is not None and e.get("ok") is False
      and e.get("error") == "Video unavailable", json.dumps(e)[:160])

# 6. a resolve that produced no single stream is a failure, whatever the exit
stub("echo '{\"title\": \"merge only\"}'")
e = run("https://www.youtube.test/watch?v=dash")
check("no single playable stream is a failure, not an empty card",
      e is not None and e.get("ok") is False, json.dumps(e)[:160])

# 7. no resolver installed: named, and only direct URLs left
oracle.VIDEO_RESOLVER = str(_TMP / "not-installed-anywhere")
e = run("https://www.youtube.test/watch?v=abc")
check("a missing resolver says so and names the limit",
      e is not None and e.get("ok") is False
      and "not installed" in e.get("error", ""), json.dumps(e)[:200])

# ---- the card itself builds and binds -------------------------------------
# In a real (offscreen) Window: a Column lays out on POLISH, and an item with no
# window is never polished — measured here, every height reads 0 without one.
QMLDIR = (APP / "qml").as_uri()
SHELL = _TMP / "Shell.qml"
SHELL.write_text('''
import QtQuick
import QtQuick.Window
Window {
    width: 600; height: 700
    visible: true
    color: Theme.bg
    property var entries: []
    property alias deck: loader.item
    Loader {
        id: loader
        objectName: "loader"
        x: 20; y: 20
        width: 560
        source: "%s/VideoDeck.qml"
        onLoaded: item.entries = Qt.binding(function () { return entries })
    }
}
''' % QMLDIR, encoding="utf-8")

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
palette = oracle.Palette(oracle.PANEL_THEME)
palette.setParent(app)          # or PySide GCs it and every colour reads black
from deskstyle import DeskStyle                                    # noqa: E402
style = DeskStyle()
style.setParent(app)
ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
theme_comp = QQmlComponent(
    engine, QUrl.fromLocalFile(str(APP / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)

warns = []
engine.warnings.connect(lambda ws: warns.extend(w.toString() for w in ws))
engine.load(QUrl.fromLocalFile(str(SHELL)))
roots = engine.rootObjects()
check("VideoDeck/VideoCard build (QtMultimedia present)", bool(roots),
      "; ".join(warns)[:400])
if roots:
    win = roots[0]
    win.setProperty("entries", [
        {"ok": True, "url": "https://x.test/w", "src": "https://x.test/s.mp4",
         "title": "A Title", "alt": "", "w": 640, "h": 360, "duration": 213,
         "live": False},
        {"ok": False, "url": "https://x.test/gone", "error": "Video unavailable"},
    ])
    for _ in range(3):
        app.processEvents()
    win.grabWindow()             # forces the polish a Column lays out on
    app.processEvents()
    deck = win.property("deck")
    h = deck.property("height") if deck else 0
    # one 16:9 card at 560 wide (315) + its caption + the failure line
    check("a card and a failure line both lay out", h > 315, "height=%s" % h)
    if "--shot" in ARGV:
        out = Path(os.environ.get("TMPDIR", "/tmp")) / "video-card.png"
        win.grabWindow().save(str(out))
        print("wrote", out)
check("no QML warnings from the card", not warns, "; ".join(warns)[:400])

print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
