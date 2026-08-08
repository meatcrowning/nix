#!/usr/bin/env python3
"""Headless check of surfer's file picker — `apps/surfer/tools/filepicker-test.py`.

The picker a page's `<input type=file>` pops is surfer's own (`qml/FilePicker.qml`),
not filer's and not the portal's, and this drives the REAL component offscreen
over a scratch directory tree. What it proves is the LOCATION BAR, which was a
read-only label until 2026-08-07 — so the only way to a folder was to walk there
from ~/Downloads one click at a time, and a path copied from anywhere else could
not be used at all:

  * it follows `cd` (and keeps following it after being typed into — a bound
    `text` would have been destroyed by the first keystroke);
  * a typed folder navigates, and Enter in the field is what does it;
  * a typed FILE is picked outright (and in save-as fills the name instead);
  * a path that is not there marks the box and changes nothing;
  * `~` expands, and a relative name resolves against the folder on screen.

Nothing here opens a window on his screen, touches his browser profile, or
answers a real page: no WebEngineView is created at all.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "filepicker-test.qml"

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back


def _borrow_wrapper_env():
    """surfer's packaged Qt env, without RUNNING the wrapper — its last line
    hands its arguments to the live browser over the singleton socket, which
    would open tabs in his session (apps/AGENTS.md, the app-wrapper trap).
    Same reader find-test.py uses."""
    wrapper = shutil.which("surfer")
    if not wrapper:
        raise SystemExit("no surfer wrapper to borrow PySide6 and the Qt env from")
    text = Path(os.path.realpath(wrapper)).read_text(errors="replace")
    m = re.search(r'(/nix/store/\S+?/bin/python3)"?\s+\S*main\.py', text)
    if not m:
        raise SystemExit("could not find main.py's interpreter in %s" % wrapper)
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
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    return m.group(1), env


if not os.environ.get("_SURFER_PICKER_REEXEC"):
    _py, _env = _borrow_wrapper_env()
    _env["_SURFER_PICKER_REEXEC"] = "1"
    os.execve(_py, [_py, str(Path(__file__).resolve())] + sys.argv[1:], _env)

scratch = Path(tempfile.mkdtemp(prefix="surfer-picker-"))
for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    d = scratch / var.lower()
    d.mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(d)

sys.path.insert(0, str(HERE.parent))
from PySide6.QtCore import QUrl, Qt, QObject, QEvent  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick  # noqa: E402

import main as surfer  # noqa: E402  (import-safe: main() is guarded)

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


QtWebEngineQuick.initialize()
app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

# ---- a tree to browse -------------------------------------------------------
tree = scratch / "tree"
(tree / "sub" / "deep").mkdir(parents=True)
for n in ("a.txt", "b.png"):
    (tree / n).write_text("x")
(tree / "sub" / "inner.txt").write_text("x")

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
palette = surfer.Palette(surfer.PANEL_THEME)
style = surfer.DeskStyle()
prefs = surfer.Prefs(app)
files = surfer.Files(prefs, app)
ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
ctx.setContextProperty("Files", files)
ctx.setContextProperty("WheelGain", 1.0)
theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(
    str(HERE.parent / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)

engine.load(QUrl.fromLocalFile(str(FIXTURE)))
roots = engine.rootObjects()
if not roots:
    raise SystemExit("the fixture failed to load")
win = roots[0]
picker = win.findChild(QObject, "picker")
if picker is None:
    raise SystemExit("no FilePicker in the fixture")


def spin(ms=80):
    import time
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def qml(js):
    """Evaluate JS in the picker's own scope — a QML `function` is not a slot."""
    expr = QQmlExpression(engine.contextForObject(picker), picker, js)
    val = expr.evaluate()
    if expr.hasError():
        raise SystemExit("QML expression %r: %s" % (js, expr.error().toString()))
    return val[0] if isinstance(val, tuple) else val


def type_location(text):
    """Put the keyboard in the location bar and TYPE, then press Return — the
    whole gesture, so `onTextEdited` and `onAccepted` are what run."""
    from PySide6.QtTest import QTest
    picker.setProperty("locationText", "")
    qml("focusLocation()")
    for ch in text:
        QTest.keyClick(win, ch)
    QTest.keyClick(win, Qt.Key_Return)
    spin(80)


MODE_OPEN, MODE_MULTI, MODE_FOLDER, MODE_SAVE = 0, 1, 2, 3   # FileDialogRequest

spin(200)
qml("mode = %d" % MODE_OPEN)
qml("cd('%s')" % tree)
spin(80)

print("\n== the location bar follows the folder ==")
check("it shows where you are", picker.property("locationText") == str(tree),
      picker.property("locationText"))
qml("cd('%s')" % (tree / "sub"))
spin(60)
check("...and keeps up with a click into a folder",
      picker.property("locationText") == str(tree / "sub"),
      picker.property("locationText"))

print("\n== typing a folder navigates ==")
type_location(str(tree))
check("an absolute folder path goes there", qml("dir") == str(tree), qml("dir"))
check("...and the box shows the new folder, still following after an edit",
      picker.property("locationText") == str(tree),
      picker.property("locationText"))
type_location("sub")
check("a RELATIVE folder name resolves against the folder on screen",
      qml("dir") == str(tree / "sub"), qml("dir"))
type_location("~")
check("~ expands", qml("dir") == os.path.expanduser("~"), qml("dir"))

print("\n== typing a file picks it ==")
qml("cd('%s')" % tree)
spin(60)
type_location("a.txt")
sel = qml("selected")
sel = sel.toVariant() if hasattr(sel, "toVariant") else sel
check("a typed file becomes the selection", sel == [str(tree / "a.txt")], sel)
qml("cd('%s')" % tree)
spin(60)
type_location(str(tree / "sub" / "inner.txt"))
sel = qml("selected")
sel = sel.toVariant() if hasattr(sel, "toVariant") else sel
check("...from anywhere, and the listing follows it there",
      sel == [str(tree / "sub" / "inner.txt")] and qml("dir") == str(tree / "sub"),
      (sel, qml("dir")))

print("\n== a path that is not there ==")
qml("cd('%s')" % tree)
spin(60)
type_location("nope/missing.txt")
check("says so instead of doing nothing in silence", qml("dirBad") is True)
check("...and did not move", qml("dir") == str(tree), qml("dir"))
qml("cd('%s')" % tree)
check("cd clears the mark", qml("dirBad") is False)

print("\n== save-as: a typed file is a NAME, not an answer ==")
qml("mode = %d" % MODE_SAVE)
qml("cd('%s')" % tree)
spin(60)
type_location(str(tree / "a.txt"))
res = qml("result()")
res = res.toVariant() if hasattr(res, "toVariant") else res
check("the name box takes it and the folder follows",
      res == [str(tree / "a.txt")], res)
sel = qml("selected")
sel = sel.toVariant() if hasattr(sel, "toVariant") else sel
check("...and nothing was 'picked' behind it", sel == [], sel)

print("\n== folder mode: only folders ==")
qml("mode = %d" % MODE_FOLDER)
qml("cd('%s')" % tree)
spin(60)
type_location("sub")
check("a folder still navigates", qml("dir") == str(tree / "sub"), qml("dir"))
qml("cd('%s')" % tree)
spin(60)
type_location("a.txt")
check("a file is refused, not silently accepted",
      qml("dirBad") is True and qml("dir") == str(tree), (qml("dirBad"), qml("dir")))

print("")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("all file-picker checks passed")
