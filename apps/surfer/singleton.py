"""surfer single-instance handoff — the CLIENT half, stdlib only.

Why this exists: surfer is the system default browser (`x-scheme-handler/
http(s)`, `text/html`, Plasma's `BrowserApplication`, `$BROWSER`), so every link
clicked in another app runs `surfer <url>`. But `qml/Main.qml` declares a
PERSISTENT `WebEngineProfile` (`storageName: "surfer"`, `offTheRecord: false`),
and a Chromium profile directory may only be owned by one process: a second
surfer means a ProcessSingleton failure, cookies/history that silently don't
persist, and — on book — a second `tools/sync.py` bracket plus a truncated
`~/.cache/surfer.log` interleaving with the live session's.

So: if a surfer is already running, hand it the URL over a Unix socket and exit.

This module is deliberately **stdlib only and Qt free**, and `main.py` imports
it BEFORE `PySide6`, so the handoff path costs a few milliseconds instead of the
seconds it takes to import PySide6 + initialize Chromium. The SERVER half is
`SingleInstance` in `main.py` (a `QLocalServer`, which speaks exactly this
protocol — QLocalServer is an ordinary `AF_UNIX` `SOCK_STREAM` listener).

Wire protocol, newline-terminated UTF-8:

    -> OPEN <url>     open <url> in a new tab (empty url == the home page)
    -> PING           liveness probe, used by the test harness
    <- OK             received

Escape hatches, both honoured here and in main.py:

    SURFER_SOCKET=<path>       override the socket path (test isolation)
    SURFER_NO_SINGLETON=1      disable entirely — always a fresh process

**The fallback must stay intact.** Every failure mode in here returns "carry on
and launch normally". A default browser that refuses to start is far worse than
a duplicated process.

Runnable standalone as a pure probe (this is what a shell wrapper would use to
skip an expensive launch bracket):

    python3 singleton.py [url]     # exit 0 = handed off, exit 10 = no server
"""
import os
import socket
import sys

_ACK_TIMEOUT = 2.0      # s to wait for the running instance's "OK"
_CONNECT_TIMEOUT = 1.0  # s to decide "nobody is listening"


def socket_path():
    """Per-user, per-machine socket path.

    `$XDG_RUNTIME_DIR` is already per-user AND per-machine (a tmpfs on the
    running system), which is exactly the scope we want; the `/tmp` fallback has
    to add the uid itself. The uid is in the name either way so a shared /tmp
    can never collide.
    """
    override = os.environ.get("SURFER_SOCKET", "")
    if override:
        return override
    uid = os.getuid()
    rt = os.environ.get("XDG_RUNTIME_DIR", "")
    if rt and os.path.isdir(rt):
        return os.path.join(rt, f"surfer-{uid}.sock")
    return os.path.join("/tmp", f"surfer-{uid}.sock")


def enabled():
    return not os.environ.get("SURFER_NO_SINGLETON", "")


def pick_url(argv):
    """First non-flag argument, the same rule `Exec=... %U` feeds us."""
    for arg in argv:
        if not arg.startswith("-"):
            return arg
    return ""


def send(url, path=None):
    """Hand `url` to a running surfer. True if it took it.

    False means "no live server" — either nothing is listening or the socket is
    a stale file left by a crash, in which case we unlink it here so the caller
    can bind the same path. Note the unlink happens only after a connect has
    ACTUALLY FAILED; unconditionally removing the socket would evict a healthy
    running instance from its own address.
    """
    path = path or socket_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(_CONNECT_TIMEOUT)
        try:
            s.connect(path)
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            # Nothing alive at this address. Clear a stale socket inode so the
            # server half can bind it; missing/racing-away is fine.
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
            return False
        s.sendall(("OPEN " + (url or "") + "\n").encode("utf-8", "replace"))
        # Wait for the ack, but treat a timeout as success anyway: the bytes are
        # in the running instance's receive buffer and it WILL process them, so
        # exiting is still better than starting a second profile owner.
        s.settimeout(_ACK_TIMEOUT)
        try:
            s.recv(64)
        except OSError:
            pass
        return True
    finally:
        try:
            s.close()
        except OSError:
            pass


def try_handoff(argv):
    """Called at the top of main.py. Exits the process if a surfer is running.

    Returns normally (== "you are the first instance, carry on") for every other
    outcome, including any unexpected exception.
    """
    if not enabled():
        return
    try:
        if send(pick_url(argv)):
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:              # never let this stop the browser
        sys.stderr.write(f"surfer: single-instance probe failed ({e})\n")


if __name__ == "__main__":
    sys.exit(0 if (enabled() and send(pick_url(sys.argv[1:]))) else 10)
