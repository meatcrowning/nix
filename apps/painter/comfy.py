"""Talk to a headless ComfyUI over its HTTP + websocket API.

Everything runs on the Qt event loop, so this works unchanged in the GUI and in
the headless tools (which just spin a QCoreApplication).

Deliberate differences from the way cte drove ComfyUI:

* the websocket is connected before the first submit and carries completion, so
  there is no 0.5s /history polling loop;
* every `executed` message contributes its images, so a batch larger than one
  survives instead of being silently truncated to the first result;
* results are matched by the node's painter role, never by a hardcoded node id.
"""

from __future__ import annotations

import json
import os
import time
import uuid

from PySide6 import QtCore, QtNetwork, QtWebSockets

# The backend is loopback-only BY DESIGN (home/prog/painter.nix passes
# `--listen 127.0.0.1`): ComfyUI runs arbitrary workflow graphs and reads and
# writes the filesystem as lam, so it must never get a listener on the LAN or
# the tailnet. To drive top's backend from air, forward the port over ssh —
#     ssh -N -L 8188:127.0.0.1:8188 top
# — and leave this default alone. PAINTER_COMFY_URL is the escape hatch for a
# forward parked on some other local port; pointing it at a remote host would
# put the API on the wire unauthenticated, so don't.
DEFAULT_URL = os.environ.get("PAINTER_COMFY_URL", "http://127.0.0.1:8188")


def _host_of(url: str) -> str:
    return url.split("://", 1)[-1].rstrip("/")


class Job(QtCore.QObject):
    """One submitted prompt and whatever came back for it."""

    def __init__(self, prompt: dict, meta: dict | None = None, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.meta = meta or {}
        self.prompt_id = None
        self.images = []          # [{filename, subfolder, type, node, role}]
        self.error = None
        self.cached_nodes = []
        self.node_times = {}
        self.started_at = None
        self.finished_at = None
        self.current_node = None
        self.progress = (0, 0)

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    def role_of(self, node_id):
        node = self.prompt.get(node_id) or {}
        return (node.get("_meta") or {}).get("painter_role", node_id)


class ComfyClient(QtCore.QObject):
    """A single connection to one ComfyUI instance."""

    connected = QtCore.Signal()
    disconnected = QtCore.Signal()
    statusChanged = QtCore.Signal(int)                 # queue_remaining
    jobStarted = QtCore.Signal(object)                 # Job
    jobProgress = QtCore.Signal(object, int, int)      # Job, value, max
    jobNode = QtCore.Signal(object, str)               # Job, role
    jobPreview = QtCore.Signal(object, bytes, str)     # Job, image bytes, format
    jobFinished = QtCore.Signal(object)                # Job
    jobFailed = QtCore.Signal(object, str)             # Job, message
    logged = QtCore.Signal(str)

    def __init__(self, url: str = DEFAULT_URL, parent=None):
        super().__init__(parent)
        self.url = url.rstrip("/")
        self.client_id = str(uuid.uuid4())
        self.net = QtNetwork.QNetworkAccessManager(self)
        self.ws = QtWebSockets.QWebSocket()
        self.ws.textMessageReceived.connect(self._on_text)
        self.ws.binaryMessageReceived.connect(self._on_binary)
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.errorOccurred.connect(lambda e: self.logged.emit(f"ws error: {e}"))

        self._jobs = {}          # prompt_id -> Job
        self._pending = []       # submitted, awaiting a prompt_id
        self._active = None      # Job currently executing
        self._backoff = 500
        self._reconnect = QtCore.QTimer(self)
        self._reconnect.setSingleShot(True)
        self._reconnect.timeout.connect(self.connect_ws)
        self._want_ws = False
        self.queue_remaining = 0
        self.object_info = None

    # -- connection ---------------------------------------------------------

    def connect_ws(self):
        self._want_ws = True
        if self.ws.state() != QtNetwork.QAbstractSocket.SocketState.UnconnectedState:
            return
        ws_url = f"ws://{_host_of(self.url)}/ws?clientId={self.client_id}"
        self.ws.open(QtCore.QUrl(ws_url))

    def close(self):
        self._want_ws = False
        self.ws.close()

    def _on_connected(self):
        self._backoff = 500
        self.logged.emit("websocket connected")
        self.connected.emit()

    def _on_disconnected(self):
        self.disconnected.emit()
        if self._want_ws:
            self._reconnect.start(self._backoff)
            self._backoff = min(self._backoff * 2, 8000)

    # -- plain HTTP helpers -------------------------------------------------

    def _request(self, path: str) -> QtNetwork.QNetworkRequest:
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.url}{path}"))
        req.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        return req

    def _post(self, path: str, payload: dict, on_reply=None):
        data = QtCore.QByteArray(json.dumps(payload).encode("utf-8"))
        reply = self.net.post(self._request(path), data)
        if on_reply:
            reply.finished.connect(lambda r=reply: on_reply(r))
        else:
            reply.finished.connect(reply.deleteLater)
        return reply

    def _get(self, path: str, on_reply):
        reply = self.net.get(self._request(path))
        reply.finished.connect(lambda r=reply: on_reply(r))
        return reply

    def fetch_object_info(self, callback=None):
        def done(reply):
            try:
                if reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError:
                    self.object_info = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    if callback:
                        callback(self.object_info)
                elif callback:
                    callback(None)
            finally:
                reply.deleteLater()

        self._get("/object_info", done)

    def fetch_stats(self, callback):
        def done(reply):
            try:
                ok = reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError
                doc = json.loads(bytes(reply.readAll()).decode("utf-8")) if ok else None
                callback(doc)
            except Exception:  # noqa: BLE001 - a probe must never raise
                callback(None)
            finally:
                reply.deleteLater()

        self._get("/system_stats", done)

    # -- submitting ---------------------------------------------------------

    def submit(self, prompt: dict, meta: dict | None = None) -> Job:
        job = Job(prompt, meta, parent=self)
        payload = {
            "prompt": {k: {kk: vv for kk, vv in v.items() if kk != "_meta"}
                       for k, v in prompt.items()},
            "client_id": self.client_id,
        }
        # Keep _meta for ourselves; ComfyUI ignores it but there is no reason to ship it.
        self._pending.append(job)

        def done(reply):
            try:
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                    msg = self._explain_submit_error(raw, job) or raw or "submit failed"
                    if job in self._pending:
                        self._pending.remove(job)
                    job.error = msg
                    self.jobFailed.emit(job, msg)
                    return
                doc = json.loads(raw)
                job.prompt_id = doc.get("prompt_id")
                if job in self._pending:
                    self._pending.remove(job)
                if job.prompt_id:
                    self._jobs[job.prompt_id] = job
                    self.logged.emit(f"queued {job.prompt_id}")
            except Exception as exc:  # noqa: BLE001
                job.error = f"{exc}"
                self.jobFailed.emit(job, job.error)
            finally:
                reply.deleteLater()

        self._post("/prompt", payload, done)
        return job

    def _explain_submit_error(self, raw: str, job: Job) -> str | None:
        """Turn ComfyUI's node_errors blob into something a person can act on."""
        try:
            doc = json.loads(raw)
        except ValueError:
            return None
        parts = []
        err = doc.get("error") or {}
        if err.get("message"):
            detail = err.get("details")
            parts.append(f"{err['message']}{f' ({detail})' if detail else ''}")
        for node_id, ne in (doc.get("node_errors") or {}).items():
            role = job.role_of(node_id)
            for e in ne.get("errors") or []:
                extra = e.get("extra_info") or {}
                name = extra.get("input_name")
                parts.append(
                    f"{role}: {e.get('message')}"
                    + (f" [{name}]" if name else "")
                    + (f" - {e.get('details')}" if e.get("details") else "")
                )
        return "; ".join(parts) or None

    # -- cancelling ---------------------------------------------------------

    def interrupt(self):
        self._post("/interrupt", {})

    def cancel(self, job: Job):
        if job.prompt_id and self._active is job:
            self.interrupt()
        elif job.prompt_id:
            self._post("/queue", {"delete": [job.prompt_id]})
            self._jobs.pop(job.prompt_id, None)

    def cancel_all(self):
        ours = [pid for pid in self._jobs]
        if ours:
            self._post("/queue", {"delete": ours})
        self.interrupt()
        self._jobs.clear()
        self._active = None

    def free(self, unload_models: bool = True, callback=None):
        """Ask ComfyUI to drop its loaded weights.

        `callback(ok, detail)` fires on the reply, because "unloaded" is not
        something the caller may claim on the strength of having POSTed: with
        the backend down this is a connection refusal and the only visible
        result would otherwise be a toast saying it worked.
        """
        def done(reply):
            try:
                err = reply.error()
                ok = err == QtNetwork.QNetworkReply.NetworkError.NoError
                detail = "" if ok else (reply.errorString() or "request failed")
                if callback:
                    callback(ok, detail)
            finally:
                reply.deleteLater()

        self._post("/free", {"unload_models": unload_models, "free_memory": True},
                   done if callback else None)

    # -- websocket events ---------------------------------------------------

    def _job_for(self, data: dict):
        pid = data.get("prompt_id")
        if pid and pid in self._jobs:
            return self._jobs[pid]
        return self._active

    def _on_text(self, text: str):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        kind = msg.get("type")
        data = msg.get("data") or {}

        if kind == "status":
            info = ((data.get("status") or {}).get("exec_info") or {})
            self.queue_remaining = int(info.get("queue_remaining", 0))
            self.statusChanged.emit(self.queue_remaining)
            return

        if kind == "execution_start":
            job = self._job_for(data)
            if job:
                self._active = job
                job.started_at = time.time()
                self.jobStarted.emit(job)
            return

        if kind == "execution_cached":
            job = self._job_for(data)
            if job:
                job.cached_nodes = list(data.get("nodes") or [])
            return

        if kind == "executing":
            job = self._job_for(data)
            node = data.get("node")
            if job is None:
                return
            if node is None:
                # This prompt is done; results arrived via `executed`.
                self._complete(job)
            else:
                job.current_node = node
                self.jobNode.emit(job, job.role_of(node))
            return

        if kind in ("progress", "progress_state"):
            job = self._job_for(data)
            if job is None:
                return
            if kind == "progress":
                value, maximum = int(data.get("value", 0)), int(data.get("max", 0))
            else:
                # newer per-node shape: pick the node actually running
                nodes = (data.get("nodes") or {}).values()
                running = [n for n in nodes if n.get("state") == "running"] or list(nodes)
                if not running:
                    return
                cur = running[0]
                value, maximum = int(cur.get("value", 0)), int(cur.get("max", 0))
            job.progress = (value, maximum)
            self.jobProgress.emit(job, value, maximum)
            return

        if kind == "executed":
            job = self._job_for(data)
            if job is None:
                return
            node = data.get("node")
            images = (data.get("output") or {}).get("images") or []
            for img in images:
                job.images.append({
                    "filename": img.get("filename"),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                    "node": node,
                    "role": job.role_of(node),
                })
            return

        if kind in ("execution_error", "execution_interrupted"):
            job = self._job_for(data)
            if job is None:
                return
            if kind == "execution_interrupted":
                msg = "interrupted"
            else:
                role = job.role_of(data.get("node_id"))
                msg = f"{role} ({data.get('node_type')}): {data.get('exception_message')}"
                tb = data.get("traceback")
                if isinstance(tb, list) and tb:
                    msg += "\n" + "".join(tb[-3:])
            job.error = msg
            job.finished_at = time.time()
            self._jobs.pop(job.prompt_id, None)
            if self._active is job:
                self._active = None
            self.jobFailed.emit(job, msg)
            return

    def _on_binary(self, payload: QtCore.QByteArray):
        """Live previews arrive as event(u32) + format(u32) + image bytes."""
        raw = bytes(payload)
        if len(raw) < 8:
            return
        event = int.from_bytes(raw[0:4], "big")
        fmt = int.from_bytes(raw[4:8], "big")
        if event != 1:
            return
        job = self._active
        if job is None:
            return
        self.jobPreview.emit(job, raw[8:], "jpeg" if fmt == 1 else "png")

    def _complete(self, job: Job):
        job.finished_at = time.time()
        self._jobs.pop(job.prompt_id, None)
        if self._active is job:
            self._active = None
        if job.images:
            self.jobFinished.emit(job)
            return
        # No images seen on the socket: reconcile once against history, which also
        # covers the case where the websocket dropped mid-run.
        self._reconcile(job)

    def _reconcile(self, job: Job):
        def done(reply):
            try:
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                doc = json.loads(raw) if raw else {}
                entry = doc.get(job.prompt_id) or {}
                err = extract_history_error(entry)
                if err:
                    job.error = err
                    self.jobFailed.emit(job, err)
                    return
                for node_id, out in (entry.get("outputs") or {}).items():
                    for img in out.get("images") or []:
                        job.images.append({
                            "filename": img.get("filename"),
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                            "node": node_id,
                            "role": job.role_of(node_id),
                        })
                if job.images:
                    self.jobFinished.emit(job)
                else:
                    job.error = "finished with no images"
                    self.jobFailed.emit(job, job.error)
            except Exception as exc:  # noqa: BLE001
                job.error = f"history read failed: {exc}"
                self.jobFailed.emit(job, job.error)
            finally:
                reply.deleteLater()

        self._get(f"/history/{job.prompt_id}", done)

    # -- fetching results ---------------------------------------------------

    def view_url(self, image: dict) -> str:
        from urllib.parse import urlencode

        q = urlencode({
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        })
        return f"{self.url}/view?{q}"

    def download(self, image: dict, callback):
        """Fetch one output image's bytes."""
        def done(reply):
            try:
                ok = reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError
                callback(bytes(reply.readAll()) if ok else None)
            finally:
                reply.deleteLater()

        req = QtNetwork.QNetworkRequest(QtCore.QUrl(self.view_url(image)))
        reply = self.net.get(req)
        reply.finished.connect(lambda r=reply: done(r))


def extract_history_error(entry: dict) -> str | None:
    """Pull a readable error out of ComfyUI's /history status block.

    `status.messages` is a list of [name, payload] pairs, which is easy to
    mis-parse; this mirrors the handling cte arrived at.
    """
    status = entry.get("status") or {}
    if status.get("status_str") not in (None, "error") and status.get("completed", True):
        return None
    for item in status.get("messages") or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        name, payload = item
        if name != "execution_error" or not isinstance(payload, dict):
            continue
        node = payload.get("node_type") or payload.get("node_id")
        msg = payload.get("exception_message") or payload.get("exception_type")
        return f"{node}: {msg}"
    if status.get("status_str") == "error":
        return "execution failed (no detail in history)"
    return None


# ---------------------------------------------------------------------------
# headless helper
# ---------------------------------------------------------------------------


def run_jobs(client: ComfyClient, submit_fn, timeout: float = 900.0):
    """Drive a client to completion under a bare QCoreApplication.

    `submit_fn(client)` returns the list of Jobs to wait for.  Returns that list
    once every job has either produced images or failed.
    """
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    jobs = []
    done = set()

    def finish(job):
        done.add(id(job))

    def failed(job, _msg):
        finish(job)

    client.jobFinished.connect(finish)
    client.jobFailed.connect(failed)

    def start():
        if not jobs:
            jobs.extend(submit_fn(client))

    # The socket usually survives between calls, in which case `connected` will
    # not fire again -- submit straight away rather than waiting for a signal
    # that has already been and gone.
    connected_state = QtNetwork.QAbstractSocket.SocketState.ConnectedState
    if client.ws.state() == connected_state:
        start()
    else:
        client.connected.connect(start)
        client.connect_ws()

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 100)
            if jobs and len(done) >= len(jobs):
                break
            QtCore.QThread.msleep(10)
        for job in jobs:
            if id(job) not in done and not job.error:
                job.error = "timed out"
    finally:
        client.jobFinished.disconnect(finish)
        client.jobFailed.disconnect(failed)
        try:
            client.connected.disconnect(start)
        except (RuntimeError, TypeError):
            pass
    return jobs
