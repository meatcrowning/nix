#!/usr/bin/env python3
"""handoff-test — the running-app socket (pylib/handoff.py), both halves.

Stands a real `Listener` up in a Qt event loop, drives it with the real
stdlib client, and asserts the contract the callers depend on. The one that
matters most is the REFUSAL: filer only skips launching a viewer because a
viewer that cannot show the image says so, and a false "taken" is a click that
does nothing — the single outcome worse than the 0.5s this exists to avoid.

  * nobody listening -> None, fast, no exception (the very common case: the
    first open of a session);
  * a stale socket file with no process behind it -> None, and the next server
    can still claim the name;
  * a server that says it cannot take it -> {"taken": false}, and its `take`
    callback is never called;
  * a server whose `take` raises -> still answers {"taken": false} rather than
    leaving the caller to time out;
  * the payload arrives intact, and several requests in a row all work;
  * a second Listener on the same name does not steal it.

Offscreen, no windows, no files outside a temp XDG_RUNTIME_DIR of its own — it
points $XDG_RUNTIME_DIR at a temp dir first, so it can never collide with the
socket of the viewer the user has open.

    ./tools/handoff-test.py
"""
import os
import shutil
import sys
import tempfile
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
# Before importing handoff: its socket path is read from here, and the whole
# point is to stay away from the live viewer's.
_RT = tempfile.mkdtemp(prefix="t_handoff-")
os.environ["XDG_RUNTIME_DIR"] = _RT

PYLIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PYLIB)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

import handoff  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def ask(payload, timeout=2.0):
    """Run the real client on a worker thread and pump Qt until it answers —
    the server half is event-loop driven, so a blocking call on this thread
    would deadlock against the thing it is talking to."""
    out = {}

    def run():
        out["reply"] = handoff.send("probe", payload, timeout=timeout)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    while t.is_alive():
        QGuiApplication.processEvents()
    t.join()
    return out.get("reply")


def main():
    app = QGuiApplication(sys.argv)   # noqa: F841
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    try:
        run()
    finally:
        shutil.rmtree(_RT, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all handoff checks passed")
    return 0


def run():
    path = handoff.sock_path("probe")
    check("the socket lives in XDG_RUNTIME_DIR", path.startswith(_RT), path)

    # ---- nobody home -------------------------------------------------------
    check("no server: send() returns None", handoff.send("probe", {"a": 1}) is None)
    check("no server: took(None) is False", handoff.took(None) is False)

    # ---- a stale socket file, no process behind it -------------------------
    open(path, "w").close()
    check("stale socket: send() still returns None, no exception",
          handoff.send("probe", {"a": 1}) is None)

    # ---- a live server that ACCEPTS ---------------------------------------
    seen, verdict = [], {"can": True, "boom": False}

    def can_take():
        return verdict["can"]

    def take(payload):
        if verdict["boom"]:
            raise RuntimeError("decode blew up")
        seen.append(payload)

    lis = handoff.Listener("probe", can_take, take)
    check("a server claims the name even over a stale socket file", lis.listening)

    r = ask({"argv": ["--order", "/tmp/x", "/tmp/a.png"], "cwd": "/tmp"})
    check("it answers taken=true", handoff.took(r), r)
    check("...and the payload arrived intact",
          seen and seen[-1]["argv"] == ["--order", "/tmp/x", "/tmp/a.png"]
          and seen[-1]["cwd"] == "/tmp", seen[-1] if seen else None)

    r = ask({"argv": ["/tmp/b.png"]})
    check("a second request works on the same server", handoff.took(r) and len(seen) == 2,
          len(seen))

    # ---- the refusal — the whole safety property ---------------------------
    verdict["can"] = False
    before = len(seen)
    r = ask({"argv": ["/tmp/c.png"]})
    check("a server that cannot take it says so", r == {"taken": False}, r)
    check("...and took() reads that as no", not handoff.took(r))
    check("...and it did NOT do the work anyway", len(seen) == before, len(seen))

    # ---- a server whose work raises still ANSWERS --------------------------
    verdict["can"], verdict["boom"] = True, True
    r = ask({"argv": ["/tmp/d.png"]})
    check("a take() that raises still replies, rather than hanging the caller",
          r == {"taken": False}, r)
    verdict["boom"] = False

    # ---- junk on the wire --------------------------------------------------
    # Off the GUI thread, like ask(): a blocking recv here would stop the event
    # loop that has to run for the server to reply, and the "failure" would be
    # the test deadlocking against itself.
    import socket as _s
    junk = {}

    def send_junk():
        c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        c.settimeout(2.0)
        try:
            c.connect(path)
            c.sendall(b"this is not json\n")
            junk["got"] = c.recv(256)
        except OSError as e:
            junk["got"] = b"ERR " + str(e).encode()
        finally:
            c.close()
    t = threading.Thread(target=send_junk, daemon=True)
    t.start()
    while t.is_alive():
        QGuiApplication.processEvents()
    t.join()
    got = junk.get("got", b"")
    check("a malformed request is answered with taken=false, not a crash",
          b'"taken": false' in got or b'"taken":false' in got, got)

    # ---- a second Listener must not steal a claimed name -------------------
    other = handoff.Listener("probe", can_take, take)
    check("a second server does not take the name from the first",
          not other.listening)
    r = ask({"argv": ["/tmp/e.png"]})
    check("...and the first one is still the one answering", handoff.took(r), r)


if __name__ == "__main__":
    sys.exit(main())
