#!/usr/bin/env python3
"""What does goetia PUSH down the vtb socket when the minister cap changes?

The producer half of the inner-titlebar flash. `tools/vtb-flash-test.sh` and
`tools/vtb-titletext-test.sh` measure the PIXELS the running plugin draws; this
one measures the WIRE, off-screen, with no plugin involved at all: it stands up
a fake `hyprvtb-buttons.sock` in a scratch `$XDG_RUNTIME_DIR`, runs the real
app (real `main.py`, real `Main.qml`, real `Titlebar`/`VtbClient`) against it,
drives the real cap dropdown's `trigger()` through `QQmlExpression`, and prints
every line the app sent, timestamped from the moment of the change.

Everything the app touches is redirected into a scratch tree — the cap file,
`state.json`, and the board itself — so his live cap, his drafts and
`docs/board.md` are untouched. Nothing is drawn: `QT_QPA_PLATFORM=offscreen`.

    apps/board/tools/vtb-cap-probe.py           # trace, then PASS/FAIL
    apps/board/tools/vtb-cap-probe.py --keep    # keep the scratch tree

PASS is: a successful cap change publishes NOTHING to the inner bar — no
FOOTER, no re-REGISTER, no flag line — so the slot reads the same before,
during and after. [his, 2026-07-30] *"when i change the number of ministers in
goetia itll flash text indicating that on the inner bar"*: the confirmation was
the flash, and it is gone (`Main.qml` -> `capItems`). A FAILURE still reports;
that path is not exercised here, since it cannot be provoked without breaking
the store out from under a real write.
"""
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

# The app's Qt lives in its wrapper, not on the system python. Re-exec under
# the interpreter `goetia`'s own wrapper ends with, exactly as the shell
# harnesses reuse that wrapper rather than hardcoding a store path.
try:
    import PySide6  # noqa: F401
except ImportError:
    import re
    import shutil as _sh
    w = _sh.which("goetia")
    m = re.search(r'exec "([^"]+)"', open(w).read()) if w else None
    if not m:
        print("SKIP: no goetia wrapper to borrow a PySide6 from")
        raise SystemExit(0)
    os.execv(m.group(1), [m.group(1), os.path.abspath(__file__)] + sys.argv[1:])
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(os.path.dirname(APP), "pylib"))

SCRATCH = tempfile.mkdtemp(prefix="vtb-cap-probe.")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SCRATCH, "run")
os.environ["XDG_STATE_HOME"] = os.path.join(SCRATCH, "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")
os.environ["BOARD_NO_SYNC"] = "1"
for d in ("run", "state", "config"):
    os.makedirs(os.path.join(SCRATCH, d), exist_ok=True)

SOCK = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hyprvtb-buttons.sock")
BOARD = os.path.join(SCRATCH, "board.md")

TRACE = []          # (t, line)
T0 = [None]         # set to the moment the cap is changed


def _stamp():
    return None if T0[0] is None else time.monotonic() - T0[0]


def fake_plugin(stop):
    """A hyprvtb that does nothing but listen and write down what it is told."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(4)
    srv.settimeout(0.2)
    while not stop.is_set():
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        threading.Thread(target=_read, args=(c, stop), daemon=True).start()
    srv.close()


def _read(c, stop):
    c.settimeout(0.2)
    buf = b""
    while not stop.is_set():
        try:
            d = c.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not d:
            break
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            TRACE.append((_stamp(), line.decode("utf-8", "replace")))
    c.close()


def main():
    keep = "--keep" in sys.argv
    shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(APP)),
                                 "docs", "board.md"), BOARD)

    stop = threading.Event()
    threading.Thread(target=fake_plugin, args=(stop,), daemon=True).start()

    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    import main as boardmain

    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    settings = boardmain.Settings()
    palette = boardmain.Palette(boardmain.PANEL_THEME)
    style = boardmain.DeskStyle()
    titlebar = boardmain.Titlebar()
    board = boardmain.Board(BOARD)
    agents = boardmain.Agents()
    usage = boardmain.Usage()
    for k, v in (("Agents", agents), ("Usage", usage), ("WalPalette", palette),
                 ("DeskStyle", style), ("Titlebar", titlebar), ("Board", board),
                 ("Settings", settings)):
        ctx.setContextProperty(k, v)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(
        os.path.join(APP, "qml", "theme", "Theme.qml")))
    theme = comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + comp.errorString(), file=sys.stderr)
        return 1
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(APP, "qml", "Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return 1
    win = roots[0]

    def change_cap():
        cur = agents.property("cap")
        want = 6 if cur != 6 else 5
        T0[0] = time.monotonic()
        TRACE.append((0.0, "--- cap %d -> %d ---" % (cur, want)))
        # The REAL dropdown entry, closure and all.
        e = QQmlExpression(
            engine.rootContext(), win,
            "(function(n){ var r = capItems();"
            "  for (var i = 0; i < r.length; i++)"
            "    if (r[i].label.indexOf(String(n)) >= 0) { r[i].trigger(); return r[i].label; }"
            "  return 'no such entry'; })(%d)" % want)
        out = e.evaluate()
        if e.hasError():
            print("expression failed:", e.error().toString(), file=sys.stderr)
        else:
            print("clicked: {}".format(out))

    QTimer.singleShot(1200, change_cap)
    QTimer.singleShot(9000, app.quit)
    app.exec()
    stop.set()
    time.sleep(0.3)

    print("\n--- wire trace (t = seconds from the cap change) ---")
    for t, line in TRACE:
        print("  %8s  %s" % ("before" if t is None else "%+.2f" % t, line))

    foot = [(t, ln[len("FOOTER "):]) for t, ln in TRACE if ln.startswith("FOOTER ")]
    before = [f for t, f in foot if t is None or t < 0]
    b = before[-1] if before else ""
    sent = [(t, ln) for t, ln in TRACE
            if t is not None and t > 0 and not ln.startswith("---")]
    rc = 0
    print("\nfooter before the change: %r" % b)
    print("lines sent after it:      %d" % len(sent))
    if sent:
        for t, ln in sent:
            print("FAIL: +%.2f  %s" % (t, ln))
        print("FAIL: the cap change published to the inner bar")
        rc = 1
    else:
        print("PASS: a cap change publishes nothing to the inner bar")
    if keep:
        print("scratch kept at %s" % SCRATCH)
    else:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
