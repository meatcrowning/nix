#!/usr/bin/env python3
"""Headless check of surfer's file dialog — `apps/surfer/tools/filepicker-test.py`.

The dialog behind a page's `<input type=file>` is **filer**, run as
`filer --pick <spec.json>` (the same protocol the FileChooser portal backend
uses), not a picker surfer draws itself. What this proves is the seam:

  * the spec surfer writes says what Chromium asked for — all four modes map
    onto filer's three, the suggested name and the starting folder go with it;
  * an answer comes back as local paths and reaches `dialogAccept`;
  * no result file (a cancel, or a dead picker) is a `dialogReject`, never a
    page left waiting;
  * requests QUEUE per view: a background tab's dialog is not run over the page
    you are on, and closing a tab kills the dialog it opened;
  * `filer` missing is a cancel, not a hang.

**`FILER_BIN` is pointed at a stub** that writes a result file and exits, so no
window opens anywhere and the real filer is never started. The stub records the
spec it was handed, which is the assertion surface.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

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

# ---- the stub that stands in for `filer --pick` -----------------------------
# It records the spec and answers with whatever ANSWER holds: a JSON list of
# paths to return, or "cancel" (write nothing, which filer's protocol reads as a
# cancel), or "hang" (sleep until killed, for the tab-closed case).
SPECS = scratch / "specs.jsonl"
ANSWER = scratch / "answer"
stub = scratch / "filer-stub"
stub.write_text("""#!/usr/bin/env python3
import json, os, sys, time
spec = json.load(open(sys.argv[2]))
open(%r, "a").write(json.dumps(spec) + "\\n")
want = open(%r).read().strip()
if want == "hang":
    time.sleep(120)
    sys.exit(0)
if want == "cancel":
    sys.exit(0)
uris = ["file://" + p for p in json.loads(want)]
json.dump({"uris": uris}, open(spec["result"], "w"))
""" % (str(SPECS), str(ANSWER)))
stub.chmod(0o755)
os.environ["FILER_BIN"] = str(stub)
ANSWER.write_text("cancel")

sys.path.insert(0, str(HERE.parent))
from PySide6.QtCore import QUrl, QObject, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression  # noqa: E402
from PySide6.QtWebEngineQuick import QtWebEngineQuick  # noqa: E402

import main as surfer  # noqa: E402  (import-safe: main() is guarded)

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def spin(ms=120):
    import time
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def wait_for(fn, ms=6000):
    import time
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if fn():
            return True
        spin(50)
    return False


def unwrap(v):
    return list(v.toVariant()) if hasattr(v, "toVariant") else (list(v) if v else v)


def specs():
    if not SPECS.exists():
        return []
    return [json.loads(l) for l in SPECS.read_text().splitlines() if l.strip()]


def answer(v):
    ANSWER.write_text(v if isinstance(v, str) else json.dumps(v))


QtWebEngineQuick.initialize()
app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

tree = scratch / "tree"
tree.mkdir()
(tree / "a.txt").write_text("x")

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

engine.load(QUrl.fromLocalFile(str(HERE / "filepicker-test.qml")))
roots = engine.rootObjects()
if not roots:
    raise SystemExit("the fixture failed to load")
win = roots[0]
picker = win.findChild(QObject, "picker")
fake = win.findChild(QObject, "requests")
if picker is None or fake is None:
    raise SystemExit("fixture is missing the picker or the request factory")


def qml(js, obj=None):
    o = obj if obj is not None else picker
    expr = QQmlExpression(engine.contextForObject(o), o, js)
    val = expr.evaluate()
    if expr.hasError():
        raise SystemExit("QML expression %r: %s" % (js, expr.error().toString()))
    return val[0] if isinstance(val, tuple) else val


def request(mode=0, name="", view="v1"):
    """Make a stub FileDialogRequest in the fixture and hand it to the picker."""
    return qml("makeRequest(%d, '%s', '%s')" % (mode, name, view), fake)


MODE_OPEN, MODE_MULTI, MODE_FOLDER, MODE_SAVE = 0, 1, 2, 3

print("\n== the spec surfer hands filer ==")
prefs.savePickerDir(str(tree))
answer([str(tree / "a.txt")])
qml("currentView = 'v1'")
request(MODE_OPEN, "", "v1")
check("filer was run", wait_for(lambda: len(specs()) == 1), specs())
sp = specs()[-1]
check("...in open mode, single", sp["mode"] == "open" and sp["multiple"] is False, sp)
check("...starting where the last pick came from",
      sp["current_folder"] == str(tree), sp["current_folder"])
check("...and the answer reaches dialogAccept",
      wait_for(lambda: qml("acceptedWith", fake) is not None)
      and unwrap(qml("acceptedWith", fake)) == [str(tree / "a.txt")],
      qml("acceptedWith", fake))

print("\n== the other three modes ==")
for mode, want, multi in ((MODE_MULTI, "open", True),
                          (MODE_FOLDER, "dir", False),
                          (MODE_SAVE, "save", False)):
    qml("reset()", fake)
    before = len(specs())
    answer("cancel")
    request(mode, "note.txt" if mode == MODE_SAVE else "", "v1")
    check("mode %d asks filer for %r" % (mode, want),
          wait_for(lambda: len(specs()) > before)
          and specs()[-1]["mode"] == want and specs()[-1]["multiple"] is multi,
          specs()[-1] if specs() else None)
    if mode == MODE_SAVE:
        check("...carrying the suggested name",
              specs()[-1]["current_name"] == "note.txt", specs()[-1])
    check("...and a cancel rejects, so the page is not left waiting",
          wait_for(lambda: qml("rejected", fake) is True))

print("\n== one at a time, and only for the tab you are looking at ==")
qml("reset()", fake)
answer("hang")
before = len(specs())
request(MODE_OPEN, "", "v1")
check("the front request runs", wait_for(lambda: len(specs()) == before + 1))
request(MODE_OPEN, "", "v1")
spin(300)
check("a second one waits its turn", len(specs()) == before + 1, specs())
check("...and the tab's badge counts both", qml("countFor('v1')") == 2,
      qml("countFor('v1')"))
request(MODE_OPEN, "", "v2")
spin(300)
check("a BACKGROUND tab's request does not run over you",
      len(specs()) == before + 1, specs())

print("\n== closing the tab takes its dialog with it ==")
answer("cancel")
qml("dropView('v1')")
check("the running dialog is killed and answered",
      wait_for(lambda: qml("countFor('v1')") == 0), qml("countFor('v1')"))
# v2 was the only bucket left; with v1 gone and v2 current, its request runs
qml("currentView = 'v2'")
check("...and the next tab's request gets its turn",
      wait_for(lambda: len(specs()) >= before + 2), specs())

print("\n== filer missing is a cancel, not a hang ==")
qml("reset()", fake)
files.setProperty("x", 0)      # no-op; keep the object referenced
os.environ["FILER_BIN"] = str(scratch / "does-not-exist")
qml("currentView = 'v3'")
request(MODE_OPEN, "", "v3")
check("the page is told no", wait_for(lambda: qml("rejected", fake) is True))
os.environ["FILER_BIN"] = str(stub)

print("")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("all file-picker checks passed")
