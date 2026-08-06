"""handoff — hand a request to an app that is ALREADY running, or find out that
you cannot.

The problem it exists for, measured on book: opening an image from filer cost
~0.5s, of which the file itself was 0.04s and everything else was starting a
process — python, PySide6, the QML engine, the theme, a GL context. Nothing
about the *work* is slow; the second viewer window is the slow part. So the
common case should not start one.

    client                                  server (the running app)
    ------                                  ------------------------
    send("viewer", {...})  ── AF_UNIX ──>   can I take this right now?
                           <── {"taken":…}  yes: does it, and says so
                                            no:  says so, changes nothing
    taken? done.  not taken? launch it the old way.

Three properties this is built around, in order of how much they matter:

* **A refusal must be cheap and honest.** The server answers "no" whenever it
  cannot *visibly* do the job — see `Listener` — and the caller then launches a
  fresh instance exactly as it always did. A click can therefore never go
  nowhere, which is the only outcome that would be worse than being slow.
* **The client half touches no Qt.** It is plain `socket` and `json`, so a
  caller can try the handoff BEFORE paying for `import PySide6` — which is
  0.10s of the 0.5s and the entire point of the exercise. `viewer`'s own
  `main.py` runs it above its imports for that reason.
* **Timeouts are short and total.** A busy or wedged server must cost a caller
  a fraction of a second, not the click. `TIMEOUT` is the whole budget.

The socket lives in `$XDG_RUNTIME_DIR`, so it is per-user and per-login and
disappears with the session; a stale one left by a killed process is detected
by the connect failing and removed by the next server to start.
"""
import json
import os
import socket

# The whole budget for "is someone there, and will they take it?" — a local
# socket answers in about a millisecond, so anything approaching this means the
# far side is busy and we are better off launching our own.
TIMEOUT = 0.3


def sock_path(name):
    """Where app `name` listens. $XDG_RUNTIME_DIR is per-user and cleaned at
    logout, which is exactly the lifetime a running-app socket should have."""
    root = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(root, "%s.sock" % name)


def send(name, payload, timeout=TIMEOUT):
    """Ask a running `name` to handle `payload`. Returns its reply dict, or
    None if nobody is listening, the socket is stale, or it did not answer in
    time. Never raises — every failure means the same thing to the caller
    ("do it yourself"), so distinguishing them here would only invite a caller
    to treat one of them as fatal."""
    p = sock_path(name)
    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(p)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf and len(buf) < 65536:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        if not buf:
            return None
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def _alive(path):
    """Is something actually accepting on `path`? The only way to tell a live
    socket from one a killed process left behind is to try it."""
    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def took(reply):
    """Did the running instance actually take it? A reply that is missing, or
    says no, or is any shape we did not expect, all mean the same: no."""
    return bool(reply) and reply.get("taken") is True


class Listener:
    """The server half. Qt-side, because it has to live in the app's event loop.

    Constructed with a callback that is asked, per request, `can_take()` ->
    bool, and if so `take(payload)`. Keeping the decision in the app rather
    than here is the point: only the app knows whether it is in a state where
    doing the work would be *visible* to the person who asked.

    Import this only from a process that already has Qt — the module's client
    half deliberately does not, and importing PySide6 up here would take that
    away from it."""

    def __init__(self, name, can_take, take, parent=None):
        from PySide6.QtCore import QObject  # noqa: PLC0415 — see the docstring
        from PySide6.QtNetwork import QLocalServer

        self._can_take = can_take
        self._take = take
        self._conns = []
        self._owner = QObject(parent)
        self._server = QLocalServer(self._owner)
        path = sock_path(name)
        # Listen FIRST and only clear the path if the name is taken by nothing
        # — `removeServer()` unconditionally deletes the file, so an
        # unconditional call means the second instance silently steals the
        # socket from the first and every later handoff goes to whichever one
        # started last. (Caught by tools/handoff-test.py, which is why it
        # bothers to stand up two Listeners.) Only a socket with nobody
        # accepting on it is ours to remove.
        self._ok = self._server.listen(path)
        if not self._ok and not _alive(path):
            QLocalServer.removeServer(path)
            self._ok = self._server.listen(path)
        if self._ok:
            self._server.newConnection.connect(self._accept)

    @property
    def listening(self):
        return self._ok

    def _accept(self):
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        self._conns.append(conn)
        conn.readyRead.connect(lambda c=conn: self._read(c))
        conn.disconnected.connect(lambda c=conn: self._drop(c))

    def _drop(self, conn):
        if conn in self._conns:
            self._conns.remove(conn)
        conn.deleteLater()

    def _read(self, conn):
        raw = bytes(conn.readAll().data())
        if b"\n" not in raw:
            return                       # a partial line; wait for the rest
        try:
            payload = json.loads(raw.split(b"\n", 1)[0].decode("utf-8"))
        except ValueError:
            payload = None
        taken = False
        if isinstance(payload, dict):
            try:
                if self._can_take():
                    self._take(payload)
                    taken = True
            except Exception:            # noqa: BLE001 — the caller must still
                taken = False            # get an answer, or it hangs to TIMEOUT
        conn.write((json.dumps({"taken": taken}) + "\n").encode("utf-8"))
        conn.flush()
        conn.disconnectFromServer()
