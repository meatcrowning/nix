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
    SURFER_ALLOW_HANDOFF=1     opt back in to a bare, no-URL invocation
    SURFER_DESKTOP_LAUNCH=1    set by surfer.desktop; "a human asked for this"

**A bare `surfer` from a script is refused** — see `refusal()`. It hands the
running browser an empty OPEN, i.e. a new home-page tab in the window the user
is looking at, and that has happened for real: on 2026-07-30 an agent borrowed
the packaged wrapper's Qt environment by sourcing it, which ran the wrapper's
own probe line three times and put three DuckDuckGo tabs in his live session.
A URL is never refused (link clicks are the whole point); a *no-URL* invocation
with no tty and no marker is never something anybody meant.

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


REFUSAL = """surfer: refusing a bare, no-URL launch from a non-interactive caller.

  With a surfer already running this opens a home-page tab in the window he is
  looking at; with none running it opens a window on his screen. Neither is
  something a script or an agent shell ever means to do. (Three DuckDuckGo tabs
  appeared in his live browser this way on 2026-07-30 — see singleton.py.)

  If you wanted surfer's Qt environment:  surfer-qtenv <command> [args...]
                                          eval "$(surfer-qtenv)"    # in a subshell
  If you wanted a window to test in:      QT_QPA_PLATFORM=offscreen, or
                                          ~/nix/tools/sandbox.sh
  If you really meant this:               SURFER_ALLOW_HANDOFF=1 surfer
"""


def _has_tty():
    """A human is plausibly on the other end of one of our three fds.

    Checked BEFORE the wrapper's `exec > ~/.cache/surfer.log` redirect, which is
    why the probe line has to stay ahead of it.
    """
    for fd in (0, 1, 2):
        try:
            if os.isatty(fd):
                return True
        except OSError:
            pass
    return False


def refusal(url):
    """The message to print instead of acting, or None to carry on.

    Deliberately keyed on "no URL", not on "no tty": every legitimate
    programmatic caller — a link click through `surfer.desktop`, anything using
    `$BROWSER` — names a URL, and refusing those would break the default
    browser. Nothing legitimate runs `surfer` with no arguments from a script.
    """
    if url:
        return None
    if os.environ.get("SURFER_ALLOW_HANDOFF", ""):
        return None
    if os.environ.get("SURFER_DESKTOP_LAUNCH", ""):
        return None
    if _has_tty():
        return None
    # The one blameless no-URL launch: offscreen AND with the handoff disabled,
    # so it can reach neither his screen nor his running browser. Offscreen
    # alone is NOT enough — the socket handoff happens before Qt exists and
    # would still put a tab in his window.
    if (not enabled()) and os.environ.get("QT_QPA_PLATFORM", "") in (
            "offscreen", "minimal", "vnc"):
        return None
    return REFUSAL


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
    outcome, including any unexpected exception — EXCEPT a refused bare launch,
    which exits 3 without starting a browser at all.
    """
    why = refusal(pick_url(argv))
    if why:
        sys.stderr.write(why)
        sys.exit(3)
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
    # Exit 0 means "handled, wrapper stops here". A refusal is deliberately 0:
    # the point is that the wrapper must NOT go on to launch a browser either.
    _url = pick_url(sys.argv[1:])
    _why = refusal(_url)
    if _why:
        sys.stderr.write(_why)
        sys.exit(0)
    sys.exit(0 if (enabled() and send(_url)) else 10)
