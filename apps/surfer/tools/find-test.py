#!/usr/bin/env python3
"""Headless check of surfer's find-in-page — `apps/surfer/tools/find-test.py`.

Runs the REAL `qml/FindBar.qml` over a REAL offscreen `WebEngineView` (an
off-the-record profile, so it cannot contend with the user's running browser for
its Chromium profile directory) against a local page with a known word count.
No screen, no network, nothing that touches the live session.

What it proves:
  * `HotkeyFilter` claims Ctrl+F (returns True, so the page never sees the key)
    and leaves every other key — Ctrl+K, a bare F — alone.
  * Ctrl+F opens the bar AND puts the keyboard in its field, from a standing
    start where the WebEngineView has the focus.
  * findText() counts: 3 matches for a word that appears 3 times, `n/m` stepping
    forward and backward with wraparound, "no matches" for a word that is not
    there, and nothing at all for an empty query.
  * Escape closes the bar, zeroes the count and drops the highlight
    (`searched` back to null), and hands the focus back to the page.
  * A second Ctrl+F over an open bar re-selects the query rather than appending
    to it.

What it does NOT prove: that the compositor delivers Ctrl+F to the window in the
first place. The events here are sent straight to the window object, so the
filter runs the same way it does live, but the platform leg is the same one
ZoomFilter's Ctrl +/-/0 already ride. Appearance is the user's visual check.

Run it after touching FindBar.qml, its wiring in Main.qml, or HotkeyFilter.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "find-test.qml"

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

# A bare `python3` on top is neither the interpreter surfer runs under nor
# carrying QtWebEngine's QML import path, and unlike split-geom-test.py this
# harness needs BOTH — an offscreen WebEngineView still has to find
# `qtwebenginequickplugin`. So borrow the packaged wrapper's environment: run the
# wrapper's own export lines in bash and dump the result.
#
# The wrapper is READ, never run. Its third line hands the arguments to a
# running surfer over the singleton socket and exits 0 — executing it would open
# a tab in the user's live browser, and its `exec >` line would swallow our
# output into ~/.cache/surfer.log.
def _borrow_wrapper_env():
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper to borrow PySide6 and the Qt env from")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("could not find main.py's interpreter in %s — if the "
                         "wrapper changed shape, update this harness" % wrapper)
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
        # keep this process's own HOME and offscreen decision. The platform and
        # the display variables are NOT negotiable: the wrapper is packaging for
        # a windowed app and anything it says about them would put a real window
        # on his monitor after the re-exec.
        if k in ("HOME", "PWD", "SHLVL", "_",
                 "QT_QPA_PLATFORM", "WAYLAND_DISPLAY", "DISPLAY"):
            continue
        env[k] = v
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    return py, env


if not os.environ.get("_SURFER_FIND_REEXEC"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_FIND_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

# scratch caches: nothing this writes should land in the user's own dirs
scratch = Path(tempfile.mkdtemp(prefix="surfer-find-"))
for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    d = scratch / var.lower()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(d)

sys.path.insert(0, str(HERE.parent))          # surfer's main.py
from PySide6.QtCore import (QUrl, QEvent, Qt, QCoreApplication, QEventLoop,
                            QTimer, QObject, Q_ARG)  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent                               # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent                     # noqa: E402
from PySide6.QtQuick import QQuickWindow                                           # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick                              # noqa: E402

import main as surfer                          # noqa: E402  (import-safe: main() is guarded)

QtWebEngineQuick.initialize()
app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
palette = surfer.Palette(surfer.PANEL_THEME)
style = surfer.DeskStyle()
hotkeys = surfer.HotkeyFilter(app)
ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
ctx.setContextProperty("Hotkeys", hotkeys)
theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(
    str(HERE.parent / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)
# The REAL DarkMode bridge — FindBar asks it to pre-compensate every colour it
# paints into a page, so a fixture without it would test the wrong branch.
# Prefs lands in the scratch XDG_STATE_HOME set above, never the user's.
prefs = surfer.Prefs(app)
darkmode = surfer.DarkMode(prefs, app)
ctx.setContextProperty("DarkMode", darkmode)

fixture = QQmlComponent(engine, QUrl.fromLocalFile(str(FIXTURE)))
if fixture.isError():
    raise SystemExit("the fixture would not compile:\n" + fixture.errorString())
engine.load(QUrl.fromLocalFile(str(FIXTURE)))
if not engine.rootObjects():
    raise SystemExit("the fixture would not load — see the QML errors above")
win = engine.rootObjects()[0]
win.installEventFilter(hotkeys)
# PySide cannot hand back a QML-declared type through property(), so the two
# objects are reached by objectName.
bar = win.findChild(QObject, "findBar")
page = win.findChild(QObject, "page")
if bar is None or page is None:
    raise SystemExit("the fixture did not expose findBar/page")

fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + "%-46s %r" % (name, got)
          + ("" if ok else " (want %r)" % (want,)))
    if not ok:
        fails.append(name)


def pump(ms=120):
    """Spin the event loop — QML bindings, findText callbacks, page loads."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def send_key(key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, text)
    QCoreApplication.sendEvent(win, ev)
    return ev.isAccepted()


def wait_for(pred, ms=8000):
    waited = 0
    while waited < ms and not pred():
        pump(50)
        waited += 50
    return pred()


# ---- the page: three "alpha", one "beta", no "zeta" -------------------------
pagefile = scratch / "page.html"
pagefile.write_text(
    "<html><body><p>alpha beta alpha</p><p>gamma alpha delta</p></body></html>",
    encoding="utf-8")
page.setProperty("url", QUrl.fromLocalFile(str(pagefile)))
if not wait_for(lambda: bool(win.property("loaded"))):
    raise SystemExit("the test page never finished loading")
page.metaObject().invokeMethod(page, "forceActiveFocus")
pump()

print("the browser's own wiring is still in place")
MAIN_QML = (HERE.parent / "qml" / "Main.qml").read_text(encoding="utf-8")
check("Main.qml instantiates FindBar", "FindBar {" in MAIN_QML, True)
check("Main.qml aims it at the focused pane",
      bool(re.search(r"FindBar \{[^}]*view: win\.current", MAIN_QML, re.S)), True)
check("Main.qml connects Hotkeys.find",
      bool(re.search(r"target: Hotkeys.*?onFind\(\)[^\n]*openFind\(\)", MAIN_QML, re.S)), True)

print("HotkeyFilter — which keys it claims")
# a throwaway filter, connected to nothing: calling eventFilter() on the live one
# would emit find() and open the bar before the next block gets to
probe = surfer.HotkeyFilter(app)
check("Ctrl+F consumed", probe.eventFilter(
    win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F,
                   Qt.KeyboardModifier.ControlModifier, "\x06")), True)
check("bare F passes through", probe.eventFilter(
    win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F,
                   Qt.KeyboardModifier.NoModifier, "f")), False)
check("Ctrl+K passes through", probe.eventFilter(
    win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K,
                   Qt.KeyboardModifier.ControlModifier, "\x0b")), False)

print("Ctrl+F opens the bar and takes the keyboard")
check("bar closed to begin with", bar.property("shown"), False)
send_key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier, "\x06")
pump()
check("shown", bar.property("shown"), True)
check("field has the focus", bar.property("fieldFocused"), True)
check("count blank with no query", bar.property("countLabel"), "")

print("findText counts, and steps both ways")
bar.setProperty("query", "alpha")
wait_for(lambda: bar.property("matches") == 3)
pump(400)   # let the find settle, or the step checks below race it
check("matches", bar.property("matches"), 3)
check("count label", bar.property("countLabel"), "1/3")
win.metaObject().invokeMethod(win, "stepNext")
wait_for(lambda: bar.property("activeMatch") == 2)
check("next -> 2/3", bar.property("countLabel"), "2/3")
win.metaObject().invokeMethod(win, "stepPrev")
wait_for(lambda: bar.property("activeMatch") == 1)
check("previous -> 1/3", bar.property("countLabel"), "1/3")
check("stepping is offered", bar.property("canStep"), True)

bar.setProperty("query", "zeta")
wait_for(lambda: bar.property("matches") == 0)
check("miss says so", bar.property("countLabel"), "no matches")
check("stepping is refused on a miss", bar.property("canStep"), False)

bar.setProperty("query", "")
pump()
check("empty query -> no count", bar.property("countLabel"), "")
check("empty query drops the highlight", bar.property("searched"), None)

print("a second Ctrl+F re-selects rather than appending")
bar.setProperty("query", "beta")
wait_for(lambda: bar.property("matches") == 1)
send_key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier, "\x06")
pump()
check("still open", bar.property("shown"), True)
check("query intact", bar.property("query"), "beta")
check("field still has the focus", bar.property("fieldFocused"), True)

print("Enter steps forward, Shift+Enter back, from the field itself")
# Relative, not absolute: Chromium RESUMES a re-issued query near the match it
# was last on rather than at the first one (measured), so an absolute "2/3" here
# is a race against where the session happened to be.
bar.setProperty("query", "alpha")
wait_for(lambda: bar.property("matches") == 3)
pump(400)
before = bar.property("activeMatch")
send_key(Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r")
wait_for(lambda: bar.property("activeMatch") != before)
check("Enter -> next match", bar.property("activeMatch"), before % 3 + 1)
mid = bar.property("activeMatch")
send_key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier, "\r")
wait_for(lambda: bar.property("activeMatch") != mid)
check("Shift+Enter -> previous match", bar.property("activeMatch"), (mid + 1) % 3 + 1)

print("Escape closes, clears and gives the page its keyboard back")
send_key(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, "\x1b")
pump(300)
check("shown", bar.property("shown"), False)
check("matches zeroed", bar.property("matches"), 0)
check("highlight dropped", bar.property("searched"), None)
check("page has the focus", page.property("activeFocus"), True)


# ---- the marks, in pixels ---------------------------------------------------
# The reason this section exists: Chromium DOES light the matches, and under
# surfer's dark mode its yellow lands as #252500 on a near-black page, which is
# indistinguishable from a find that only scrolls. So the assertion is not
# "findText ran" but "the palette colours are actually on the glass, and the
# current match is a different one from the rest" — both with the page filter
# off and with it on.
print("the matches are marked in the palette, current one apart")


def js(src):
    page.metaObject().invokeMethod(page, "runJavaScript", Q_ARG(str, src))
    pump(250)


def mark_state():
    """FindBar's JS stashes what it marked on window.__surferFindHl; relay it
    through document.title, which PySide can read as a plain property."""
    js("document.title=JSON.stringify(window.__surferFindHl||null)")
    try:
        return json.loads(page.property("title"))
    except (TypeError, ValueError):
        return None


def swatch():
    """How many pixels of each colour the page area is showing."""
    img = QQuickWindow.grabWindow(win)
    seen = {}
    for y in range(0, min(90, img.height())):
        for x in range(0, min(820, img.width())):
            n = img.pixelColor(x, y).name()
            seen[n] = seen.get(n, 0) + 1
    return seen


DIM = theme.property("dim").name()
ACCENT = theme.property("accent").name()

# dark mode needs a HOST (isSiteEnabled is false for a hostless file:// URL), so
# this half of the check is served over loopback rather than off the disk
srv_root = scratch / "www"
srv_root.mkdir(exist_ok=True)
(srv_root / "p.html").write_text(
    "<html><body style='background:#fff;color:#000;font:20px monospace'>"
    "<p>alpha beta alpha gamma alpha delta</p></body></html>", encoding="utf-8")
httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler,
                                                      directory=str(srv_root)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d/p.html" % httpd.server_address[1]

for dark in (False, True):
    darkmode.setEnabled(dark)
    win.setProperty("loaded", False)
    page.setProperty("url", QUrl(base))
    if not wait_for(lambda: bool(win.property("loaded"))):
        raise SystemExit("the loopback page never loaded")
    pump(300)
    js(darkmode.js(base))          # what Main.qml runs on every load
    label = "dark on" if dark else "dark off"

    bar.setProperty("query", "")
    pump(200)
    send_key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier, "\x06")
    pump()
    bar.setProperty("query", "alpha")
    wait_for(lambda: bar.property("matches") == 3)
    pump(500)

    st = mark_state()
    check("%s: every match marked" % label, (st or {}).get("n"), 3)
    check("%s: one of them is the current one" % label,
          (st or {}).get("active") == bar.property("activeMatch") - 1, True)

    seen = swatch()
    # the two marks are drawn at the palette hex EXACTLY — under dark mode that
    # is DarkMode.compensate() cancelling the page filter, which is the whole
    # point of this branch
    check("%s: the other matches are Theme.dim" % label, seen.get(DIM, 0) > 200, True)
    check("%s: the current match is Theme.accent" % label, seen.get(ACCENT, 0) > 100, True)
    check("%s: the two are different colours" % label, DIM != ACCENT, True)

    send_key(Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, "\x1b")
    pump(300)
    seen = swatch()
    check("%s: closing the bar unmarks them" % label,
          seen.get(DIM, 0) + seen.get(ACCENT, 0) < 20, True)

httpd.shutdown()
darkmode.setEnabled(False)

print()
if fails:
    print("FAILED %d: %s" % (len(fails), ", ".join(fails)))
print("scratch:", scratch)
sys.exit(1 if fails else 0)
