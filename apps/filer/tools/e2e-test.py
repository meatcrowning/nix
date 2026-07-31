#!/usr/bin/env python3
"""End-to-end seam test: the REAL portal.py spawning the REAL `filer --pick`.

Private session bus, and the picker runs under QT_QPA_PLATFORM=offscreen, so no
window is created anywhere. Verifies that a live OpenFile call starts filer with
a well-formed spec and that Close() aborts it into a clean response 1 rather
than a hang.
"""
import atexit
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

PORTAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portal.py")
IFACE = "org.freedesktop.impl.portal.FileChooser"
REQ_IFACE = "org.freedesktop.impl.portal.Request"
PATH = "/org/freedesktop/portal/desktop"
NAME = "org.freedesktop.impl.portal.desktop.filer"

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


tmp = os.environ["T_TMP"]
PICKER_PY = os.environ.get("FILER_TEST_PYTHON", "/usr/bin/python3")
if not os.access(PICKER_PY, os.X_OK):
    raise SystemExit("no PySide6 interpreter for the picker (%s) — run this "
                     "through portal-tests.sh, or set FILER_TEST_PYTHON" % PICKER_PY)
shim = os.path.join(tmp, "filer-offscreen")
with open(shim, "w") as f:
    # the -u pair goes BEFORE the assignment (env stops parsing options at the
    # first operand): with no display there is no fallback to his session, so a
    # picker that ignored the platform plugin aborts instead of mapping.
    # NOT sys.executable — this process is the one with `gi`, the picker needs
    # the one with PySide6 — and not a hardcoded /usr/bin/python3 either: that
    # path is book's and does not exist on top. portal-tests.sh passes filer's.
    f.write("#!/bin/sh\nexec env -u WAYLAND_DISPLAY -u DISPLAY "
            "QT_QPA_PLATFORM=offscreen "
            "%s /home/lam/nix/apps/filer/main.py \"$@\"\n" % PICKER_PY)
os.chmod(shim, 0o755)

conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
env = dict(os.environ, FILER_BIN=shim, FILER_PORTAL_DELEGATE="nosuchbackend")
proc = subprocess.Popen([sys.executable, PORTAL], env=env)


@atexit.register
def _reap_portal():
    """Teardown in a trap, not at the end of the happy path: a check that
    raises halfway used to leave the portal backend — and the picker it
    spawned — running against his session bus."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()

for _ in range(120):
    try:
        if conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                          "org.freedesktop.DBus", "NameHasOwner",
                          GLib.Variant("(s)", (NAME,)), GLib.VariantType("(b)"),
                          Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]:
            break
    except GLib.Error:
        pass
    time.sleep(0.05)

handle = "/org/freedesktop/portal/desktop/request/e2e/1"
box = {}
loop = GLib.MainLoop()


def cb(c, res):
    try:
        box["r"] = c.call_finish(res).unpack()
    except GLib.Error as e:
        box["e"] = e
    loop.quit()


opts = {
    "multiple": GLib.Variant("b", True),
    "current_folder": GLib.Variant("ay", list(os.fsencode(tmp) + b"\0")),
    "filters": GLib.Variant("a(sa(us))", [("Text", [(0, "*.txt")])]),
}
conn.call(NAME, PATH, IFACE, "OpenFile",
          GLib.Variant("(osssa{sv})", (handle, "org.test.App", "", "Pick a file", opts)),
          GLib.VariantType("(ua{sv})"), Gio.DBusCallFlags.NONE, 30000, None, cb)


def probe():
    out = subprocess.run(["pgrep", "-fa", "apps/filer/main.py"],
                         capture_output=True, text=True).stdout
    box["running"] = "--pick" in out
    box["cmd"] = out.strip()
    return False


GLib.timeout_add(5000, probe)
GLib.timeout_add(7000, lambda: (conn.call_sync(
    NAME, handle, REQ_IFACE, "Close", None, None,
    Gio.DBusCallFlags.NONE, 5000, None), False)[1])
GLib.timeout_add(25000, lambda: (loop.quit(), False)[1])
loop.run()

check("the real filer was spawned with --pick", box.get("running"), box.get("cmd"))
check("Close() on the real picker -> response 1 (no hang)",
      box.get("r", (None,))[0] == 1, box)
time.sleep(1)
leftover = subprocess.run(["pgrep", "-f", "apps/filer/main.py --pick"],
                          capture_output=True, text=True).stdout.strip()
check("the picker process was reaped, not left behind", leftover == "", leftover)

_reap_portal()
print()
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("end-to-end seam OK")
