#!/usr/bin/env python3
"""handoff-test — viewer's half of the running-app socket.

`pylib/tools/handoff-test.py` covers the transport; this covers what viewer
does with it — the part where getting it wrong means a click that appears to do
nothing:

  * an EXPOSED window takes a request and actually swaps to the image asked
    for, keeping its pane layout;
  * a NOT-exposed window (another workspace, rolled up, minimised) refuses, and
    does not quietly load the image where nobody can see it;
  * `--order` is honoured on a handoff exactly as it is on the command line, so
    the flip order still follows filer's sort;
  * relative paths resolve against the CALLER's directory, not viewer's;
  * a request with nothing openable in it is refused rather than blanking the
    window;
  * `--new-window` never reaches the file list as a path to open.

Reuses `split-test.py`'s engine setup, and points $XDG_RUNTIME_DIR at a temp
directory before importing anything, so it can never touch the socket of the
viewer the user has open. Offscreen; no window is ever mapped.

    ./tools/handoff-test.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_RT = tempfile.mkdtemp(prefix="t_vhandoff-")
os.environ["XDG_RUNTIME_DIR"] = _RT           # before handoff computes a path

VIEWER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VIEWER)
sys.path.insert(0, os.path.join(os.path.dirname(VIEWER), "pylib"))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QJSValue  # noqa: E402

import handoff  # noqa: E402
import main as viewermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def ask(payload, timeout=2.0):
    """The real client, off the GUI thread, pumping Qt while it waits."""
    out = {}
    t = threading.Thread(
        target=lambda: out.update(r=handoff.send("viewer", payload, timeout=timeout)),
        daemon=True)
    t.start()
    while t.is_alive():
        QGuiApplication.processEvents()
    t.join()
    return out.get("r")


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_vhandoff-imgs-")
    try:
        run(app, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(_RT, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all viewer handoff checks passed")
    return 0


def run(app, tmp):
    spec = importlib.util.spec_from_file_location(
        "vsplit", os.path.join(VIEWER, "tools", "split-test.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    names = []
    for i, c in enumerate(("#ff0000", "#00ff00", "#0000ff", "#ffff00")):
        p = os.path.join(tmp, "img%d.png" % i)
        im = QImage(32, 32, QImage.Format_RGB32)
        im.fill(c)
        im.save(p, "png")
        names.append(p)

    entries = [{"name": os.path.basename(p), "path": p} for p in names]
    engine, win, keep = mod.build(app, entries, 0, 1)   # noqa: F841
    win.show()
    mod.spin(400)

    def shown():
        """The path the focused pane is displaying."""
        imgs = unwrap(win.property("images")) or []
        i = int(win.paneIdx(win.property("focusPane")))
        return imgs[i]["path"] if 0 <= i < len(imgs) else None

    check("the window starts on the first image", shown() == names[0], shown())

    exposed = {"v": True}
    listener = handoff.Listener("viewer", lambda: exposed["v"],
                                lambda pl: _take(win, pl), parent=app)
    check("the listener claimed the socket", listener.listening)

    # ---- an exposed window takes it ---------------------------------------
    r = ask({"argv": [names[2]], "cwd": tmp})
    mod.spin(250)
    check("an exposed viewer takes the request", handoff.took(r), r)
    check("...and is showing the image that was asked for", shown() == names[2], shown())

    # ---- the refusal -------------------------------------------------------
    exposed["v"] = False
    r = ask({"argv": [names[1]], "cwd": tmp})
    mod.spin(250)
    check("a viewer nobody can see refuses", r == {"taken": False}, r)
    check("...and did NOT load the image into a hidden window",
          shown() == names[2], shown())
    exposed["v"] = True

    # ---- --order is honoured, and consumed --------------------------------
    order = os.path.join(tmp, "order")
    with open(order, "wb") as f:                      # filer's own format
        f.write("\0".join([names[3], names[1]]).encode())
    r = ask({"argv": ["--order", order, names[1]], "cwd": tmp})
    mod.spin(250)
    imgs = unwrap(win.property("images")) or []
    check("a handoff honours --order", handoff.took(r) and len(imgs) == 2
          and imgs[0]["path"] == names[3], [e["path"] for e in imgs])
    check("...positioned on the file that was clicked", shown() == names[1], shown())

    # ---- relative paths resolve against the CALLER -------------------------
    r = ask({"argv": ["img0.png"], "cwd": tmp})
    mod.spin(250)
    check("a relative path resolves against the caller's cwd",
          handoff.took(r) and shown() == names[0], shown())

    # ---- nothing openable --------------------------------------------------
    before = shown()
    r = ask({"argv": [os.path.join(tmp, "nope.png")], "cwd": tmp})
    mod.spin(200)
    check("a request with nothing openable is refused", r == {"taken": False}, r)
    check("...and the window still shows what it did", shown() == before, shown())

    # ---- --new-window is a flag, never a path ------------------------------
    o, s, b, rest = viewermain.split_args(["--new-window", names[0]])
    check("--new-window is consumed, not treated as a file",
          rest == [names[0]] and o is None and s is False and b == "", rest)


def _take(win, payload):
    """What main.py's real `_take` does, kept in step with it deliberately —
    the argv/cwd handling is the part worth testing."""
    argv = [str(a) for a in (payload.get("argv") or [])]
    cwd = payload.get("cwd") or os.getcwd()
    here = os.getcwd()
    try:
        os.chdir(cwd)
        entries, index, _panes = viewermain.images_for(argv)
    finally:
        os.chdir(here)
    if not entries:
        raise ValueError("nothing openable")
    win.openSet(entries, index)


if __name__ == "__main__":
    sys.exit(main())
