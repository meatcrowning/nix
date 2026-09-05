"""warden — the app side of `ai-warden`, the AI-backend memory arbiter.

`home/srvs/ai-warden.nix` runs a small loopback daemon that stops chatter's
ollama and painter's ComfyUI from taking `top` down between them: 31 GiB of RAM,
two backends that each want most of it, and a collision that livelocks the
machine rather than failing an allocation (the full reasoning is in
`home/srvs/ai-warden-files/ai-warden.py`).

The contract for an app is two calls:

    self.warden = Warden(self)
    self.warden.reserve("comfy", nbytes=weights, cb=go)   # before you load/queue
    self.warden.done("comfy")                             # when the work ends

`cb(ok, reason)` — on `ok` go ahead; on not-ok, DRAW `reason` and do not start
(docs/DESIGN.md §10: an action that cannot happen says why, it does not silently
do nothing). The warden raises its own toast when it frees something, so the app
must not toast that as well.

**Fail open, always.** No warden, a timeout, a wedged daemon, a machine that is
not `top` — every one of those calls back `ok=True`. A memory supervisor that
becomes the reason he cannot send a message has failed at its job. That is why
the timeout below is generous but finite: a reserve can legitimately take ~20s
while the other backend gives its weights back, and anything past that is a
fault, not a wait.
"""
import json
import os
import socket
import urllib.error
import urllib.request
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

WARDEN = os.environ.get("AI_WARDEN_URL", "http://127.0.0.1:8199")

#: Long enough to cover a real unload (measured at a few seconds; 25s is the
#: warden's own ceiling on waiting for the memory to come back), short enough
#: that a wedged daemon is a two-breath pause and not a hang.
TIMEOUT_MS = 40000
CLIENT_RENEW_MS = 5000


class Warden(QObject):
    """One per app. Holds no state — the daemon owns the leases."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        #: What the last answer said, whole. `cb(ok, reason)` is deliberately
        #: two arguments (every caller unpacks exactly those), and the one other
        #: field a caller wants is `freed` — the warden raises its own toast
        #: when it unloads something, and that toast lands on TOP, which from
        #: book is a screen nobody is looking at. So the app can read this and
        #: say it where he IS (docs/DESIGN.md §10 — no silent change).
        self.last = {}

    def _post(self, path, payload, cb=None):
        req = QNetworkRequest(QUrl(WARDEN + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        req.setTransferTimeout(TIMEOUT_MS)
        reply = self._nam.post(req, json.dumps(payload).encode("utf-8"))
        if cb is None:
            reply.finished.connect(reply.deleteLater)
            return
        reply.finished.connect(lambda: self._done(reply, cb, self.last))

    def _post_strict(self, path, payload, cb):
        """Lifecycle cannot fail open: if the daemon is absent, the app must
        fall back to its direct systemctl path or it would never start."""
        req = QNetworkRequest(QUrl(WARDEN + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        req.setTransferTimeout(2000)
        reply = self._nam.post(req, json.dumps(payload).encode("utf-8"))
        reply.finished.connect(lambda: self._strict_done(reply, cb))

    @staticmethod
    def _strict_done(reply, cb):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                cb(False, "")
                return
            try:
                doc = json.loads(bytes(reply.readAll().data()) or b"{}")
            except (ValueError, TypeError):
                cb(False, "")
                return
            cb(bool(doc.get("ok", False)), str(doc.get("reason") or ""))
        finally:
            reply.deleteLater()

    @staticmethod
    def _done(reply, cb, box):
        try:
            box.clear()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                cb(True, "")               # fail open — see the module docstring
                return
            try:
                doc = json.loads(bytes(reply.readAll().data()) or b"{}")
            except (ValueError, TypeError):
                cb(True, "")
                return
            box.update(doc if isinstance(doc, dict) else {})
            cb(bool(doc.get("ok", True)), str(doc.get("reason") or ""))
        finally:
            reply.deleteLater()

    def reserve(self, backend, model="", nbytes=0, cb=None, lease=0):
        """Ask for room before loading. `backend` is "ollama" or "comfy";
        `model` lets the warden size an ollama turn from its own catalogue,
        `nbytes` is painter's own weights figure. `lease` (seconds) overrides
        how long the reservation counts as busy without a `/done` — pass one
        when the work is longer than the default and pair it with `renew`."""
        body = {"backend": backend}
        if model:
            body["model"] = model
        if nbytes:
            body["bytes"] = int(nbytes)
        if lease:
            body["lease"] = int(lease)
        self._post("/reserve", body, cb or (lambda ok, why: None))

    def renew(self, backend, lease=0):
        """Still working — push the lease deadline out.

        Only extends a lease already held; it never takes one, so it cannot
        admit anything, free anything or raise a toast. That is what makes it
        the right heartbeat for a long job: a re-`reserve` re-runs admission
        every beat, and would unload the other backend (and say so) once per
        beat. Keep the lease short and call this often — the interval, not the
        job's ceiling, is what a caller that dies mid-job costs the other side."""
        body = {"backend": backend}
        if lease:
            body["lease"] = int(lease)
        self._post("/renew", body)

    def done(self, backend, cb=None):
        """The work is over — release the lease so the other app can have the
        memory. Safe to call twice, and safe to call having never reserved.

        `cb` exists for the one caller that must not race itself: chatter drops
        its ollama lease and immediately reserves comfy, and two async posts
        fired together can arrive in either order — a reserve that overtakes the
        release sees a live lease and stands back from weights already given up.
        Chain the reserve off this instead."""
        self._post("/done", {"backend": backend}, cb and (lambda ok, why: cb()))

    def client_acquire(self, backend, client_id, cb=None):
        """Register one live app process and start its backend if this is the
        first client. This is separate from a generation lease: an open window
        is not itself a reply or render in flight."""
        self._post_strict("/client/acquire",
                          {"backend": backend, "client": client_id},
                          cb or (lambda ok, why: None))

    def client_renew(self, backend, client_id):
        self._post("/client/renew", {"backend": backend, "client": client_id})

    def client_release(self, backend, client_id):
        self._post("/client/release", {"backend": backend, "client": client_id})


class BackendClientLease(QObject):
    """A renewable claim held for the lifetime of one GUI process."""

    def __init__(self, warden, backend, parent=None):
        super().__init__(parent)
        self.warden = warden
        self.backend = backend
        self.client_id = "%s:%d:%s" % (
            socket.gethostname(), os.getpid(), uuid.uuid4().hex)
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(CLIENT_RENEW_MS)
        self._timer.timeout.connect(self._renew)

    def start(self, cb=None):
        if self._active:
            return
        self._active = True
        self.warden.client_acquire(self.backend, self.client_id, cb)
        self._timer.start()

    def _renew(self):
        if self._active:
            self.warden.client_renew(self.backend, self.client_id)

    def close(self):
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        # aboutToQuit ends Qt's network loop immediately after this slot. Send
        # the tiny release ourselves so a clean close starts the grace now;
        # expiry remains the net if this bounded request cannot get through.
        body = json.dumps({"backend": self.backend,
                           "client": self.client_id}).encode("utf-8")
        req = urllib.request.Request(WARDEN + "/client/release", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=0.4) as reply:
                reply.read()
        except (OSError, urllib.error.URLError):
            pass
