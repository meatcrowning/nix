"""Talk to a headless ComfyUI over its HTTP + websocket API.

Transport callbacks run on the Qt event loop, with bounded file-download workers.
The same client works in GUI and headless tools with a QCoreApplication.

Deliberate differences from the way cte drove ComfyUI:

* the websocket is connected before the first submit and carries completion, so
  there is no 0.5s /history polling loop;
* every `executed` message contributes its images, so a batch larger than one
  survives instead of being silently truncated to the first result;
* results are matched by the node's painter role, never by a hardcoded node id.
"""

from __future__ import annotations

import json
import copy
from pathlib import Path
import os
import re
import time
import uuid
import tempfile
import urllib.request

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


def _upload_name(path):
    suffix = Path(path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ""
    return uuid.uuid4().hex + suffix


def _journal_meta(meta):
    """Store output metadata, not registry Entry objects or tensor key sets."""
    result = copy.deepcopy(meta)
    pairing = result.pop("pairing", None)
    if pairing and isinstance(result.get("params"), dict):
        params = result["params"]
        params["family"] = pairing.get("family_id")
        for key in ("model", "encoder", "vae"):
            entry = pairing.get(key)
            params[key] = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
    return result


class Job(QtCore.QObject):
    """One submitted prompt and whatever came back for it."""

    def __init__(self, prompt: dict, meta: dict | None = None, parent=None):
        super().__init__(parent)
        self.prompt = copy.deepcopy(prompt)
        self.meta = copy.deepcopy(meta or {})
        self.request_id = str(uuid.uuid4())
        self.owner_id = ""
        self.terminal = False
        self.cancelled = False
        self.reconciling = False
        self.recovery_required = False
        self.needs_poll = False
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


class _DownloadSignals(QtCore.QObject):
    done = QtCore.Signal(object, str)


class _Download(QtCore.QRunnable):
    """Bounded streaming I/O outside the Qt event loop."""
    def __init__(self, url, path):
        super().__init__()
        self.url, self.path = url, Path(path)
        self.signals = _DownloadSignals()

    def run(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name, suffix='.part', dir=self.path.parent)
            deadline = time.monotonic() + 600
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(self.url, timeout=30) as response:
                expected = response.headers.get('Content-Length')
                written = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('output download exceeded ten minutes')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)
                if expected is not None and written != int(expected):
                    raise OSError('incomplete output download')
                if not written:
                    raise OSError('empty output download')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            temporary = None
            self.signals.done.emit(str(self.path), '')
        except Exception as exc:
            self.signals.done.emit(None, str(exc))
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


class ComfyClient(QtCore.QObject):
    """A single connection to one ComfyUI instance."""

    connected = QtCore.Signal()
    disconnected = QtCore.Signal()
    statusChanged = QtCore.Signal(int)                 # queue_remaining
    jobStarted = QtCore.Signal(object)                 # Job
    jobProgress = QtCore.Signal(object, int, int)      # Job, value, max
    jobNode = QtCore.Signal(object, str)               # Job, role
    # Job, image bytes, format, metadata ({"frame": n, "frames": total} for a
    # video latent — see `_on_binary` and the local ComfyUI patch it reads).
    jobPreview = QtCore.Signal(object, bytes, str, dict)
    jobFinished = QtCore.Signal(object)                # Job
    jobFailed = QtCore.Signal(object, str)             # Job, message
    jobRecovered = QtCore.Signal(object)
    logged = QtCore.Signal(str)

    def __init__(self, url: str = DEFAULT_URL, parent=None, journal_dir=None):
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
        self._recovery_timer = QtCore.QTimer(self)
        self._recovery_timer.setInterval(5000)
        self._recovery_timer.timeout.connect(self._poll_recovery)
        self.queue_remaining = 0
        self.object_info = None
        self._download_pool = QtCore.QThreadPool(self)
        self._download_pool.setMaxThreadCount(2)
        self._downloads = set()
        self._journal = None
        self._recovery_started = False
        if journal_dir is not None:
            self.enable_journal(journal_dir)

    # -- connection ---------------------------------------------------------

    def connect_ws(self):
        self._want_ws = True
        if self.ws.state() != QtNetwork.QAbstractSocket.SocketState.UnconnectedState:
            return
        ws_url = f"ws://{_host_of(self.url)}/ws?clientId={self.client_id}"
        self.ws.open(QtCore.QUrl(ws_url))

    def enable_journal(self, path):
        from job_journal import JobJournal
        if self._journal is None:
            backend = os.environ.get("PAINTER_BACKEND_SSH") or self.url
            self._journal = JobJournal(path, self.client_id, backend)

    def _remember(self, job):
        if self._journal is not None:
            try:
                self._journal.put(job.request_id, dict(request_id=job.request_id,
                    prompt_id=job.prompt_id, owner_id=job.owner_id, prompt=job.prompt,
                    meta=_journal_meta(job.meta), cancelled=job.cancelled))
            except (OSError, TypeError, ValueError) as exc:
                self.logged.emit(f"job recovery journal unavailable: {exc}")

    def _forget(self, job):
        if self._journal is not None:
            try:
                self._journal.remove(job.request_id)
            except OSError as exc:
                self.logged.emit(f"job recovery journal unavailable: {exc}")

    def acknowledge(self, job, saved=True):
        """Release a terminal job after saves; retain its journal when saves failed."""
        if saved and not job.recovery_required:
            self._forget(job)
        if job.terminal:
            job.setParent(None)
            job.deleteLater()

    def _terminal(self, job, error=None, preserve=False):
        if job.terminal:
            return
        job.terminal = True
        job.recovery_required = preserve
        job.finished_at = time.time()
        self._jobs.pop(job.prompt_id, None)
        if job in self._pending:
            self._pending.remove(job)
        if self._active is job:
            self._active = None
        # Python consumers hold the object through their save callbacks. Removing
        # Qt ownership bounds legacy clients too; no delete while saves use it.
        job.setParent(None)
        if error:
            job.error = error
            if not preserve:
                self._forget(job)
            self.jobFailed.emit(job, error)
        else:
            self.jobFinished.emit(job)

    def close(self):
        self._want_ws = False
        self._reconnect.stop()
        self._recovery_timer.stop()
        self.ws.close()
        # Keep the recovery lock for this client's object/process lifetime.
        # aboutToQuit can run before download/save workers finish; releasing
        # here would let another window recover and publish the same job.

    def _on_connected(self):
        self._backoff = 500
        # THE FIRST MESSAGE IS THE FEATURE HANDSHAKE, and it has to be first:
        # ComfyUI only reads feature flags from a client's opening frame
        # (server.py, `first_message`). Announcing this one moves previews from
        # the old event-1 shape to event 4, which carries a metadata blob — the
        # only channel that can say WHICH frame of a clip a preview is.
        self.ws.sendTextMessage(json.dumps({
            "type": "feature_flags",
            "data": {"supports_preview_metadata": True},
        }))
        self.logged.emit("websocket connected")
        self.connected.emit()
        if self._journal is not None and not self._recovery_started:
            self._recovery_started = True
            for row in self._journal.recover():
                job = Job(row.get("prompt", {}), row.get("meta", {}), self)
                job.request_id = row["request_id"]
                job.owner_id = row.get("owner_id", "")
                job.prompt_id = row.get("prompt_id")
                job.cancelled = bool(row.get("cancelled"))
                job.needs_poll = True
                self._recovery_timer.start()
                if job.prompt_id:
                    self._jobs[job.prompt_id] = job
                else:
                    self._pending.append(job)
                self.jobRecovered.emit(job)
        self.reconcile_outstanding()

    def _on_disconnected(self):
        self.logged.emit("websocket disconnected")
        self.disconnected.emit()
        if self._want_ws:
            self._reconnect.start(self._backoff)
            self._backoff = min(self._backoff * 2, 8000)

    # -- plain HTTP helpers -------------------------------------------------

    def _request(self, path: str) -> QtNetwork.QNetworkRequest:
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.url}{path}"))
        req.setTransferTimeout(30000)
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
            except (ValueError, TypeError):
                if callback:
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
        job.owner_id = self.client_id
        saved_meta = _journal_meta(job.meta)
        payload = {
            "extra_data": {"painter_request_id": job.request_id,
                           "extra_pnginfo": {"painter": saved_meta.get("params", saved_meta)}},
            "prompt": {k: {kk: vv for kk, vv in v.items() if kk != "_meta"}
                       for k, v in prompt.items()},
            "client_id": self.client_id,
        }
        # Keep _meta for ourselves; ComfyUI ignores it but there is no reason to ship it.
        self._pending.append(job)
        self._remember(job)

        def done(reply):
            try:
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                    # A lost response does not prove rejection. Never resubmit:
                    # find our request marker in queue/history on reconnection.
                    status = reply.attribute(QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                    if status and int(status) in (400, 401, 403, 404, 422):
                        self._terminal(job, self._explain_submit_error(raw, job) or raw or "submit failed")
                    else:
                        self.logged.emit("submission acknowledgement lost; checking queue/history")
                        job.needs_poll = True
                    self._recovery_timer.start()
                    self._find_pending(job)
                    return
                doc = json.loads(raw)
                job.prompt_id = doc.get("prompt_id")
                if not job.prompt_id:
                    self._find_pending(job)
                    return
                if job in self._pending:
                    self._pending.remove(job)
                self._jobs[job.prompt_id] = job
                self._remember(job)
                self.logged.emit(f"queued {job.prompt_id}")
                if job.cancelled:
                    self.cancel(job)
                else:
                    self._reconcile(job, check_queue=True)
            except (ValueError, TypeError) as exc:
                self.logged.emit(f"submission reply unreadable: {exc}; checking queue/history")
                self._find_pending(job)
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

    def _owned_stop(self, job, hard, callback=None):
        if job is None or not job.prompt_id:
            if callback:
                callback(False, "no owned job is running")
            return
        def done(reply):
            try:
                ok = reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError
                doc = json.loads(bytes(reply.readAll()).decode("utf-8")) if ok else {}
                stopped = bool(doc.get("stopping"))
                detail = doc.get("error", "") if ok else "Backend cannot safely stop this job; update Painter's backend node."
                if callback:
                    callback(stopped, detail)
                elif detail:
                    self.logged.emit(detail)
            except (ValueError, TypeError):
                if callback:
                    callback(False, "bad stop reply")
            finally:
                reply.deleteLater()
        def capability(reply):
            try:
                doc = self._read_json(reply)
                if doc.get("ownership_version") != 1:
                    raise ValueError("unsupported ownership protocol")
            except (ValueError, TypeError, AttributeError):
                detail = "Backend cannot safely stop this job; update Painter's backend node."
                if callback:
                    callback(False, detail)
                else:
                    self.logged.emit(detail)
                return
            finally:
                reply.deleteLater()
            self._post("/painter/interrupt" if hard else "/painter/stop",
                       {"prompt_id": job.prompt_id, "client_id": job.owner_id}, done)
        # Older /painter/stop accepts any body and stops the global sampler.
        # Never call it until the server advertises ownership enforcement.
        self._get("/painter/control", capability)

    def interrupt(self):
        self._owned_stop(self._active, True)

    def stop_and_save(self, callback=None):
        self._owned_stop(self._active, False, callback)

    def cancel(self, job: Job):
        job.cancelled = True
        self._remember(job)
        if not job.prompt_id:
            return  # acknowledgement/reconciliation will delete only this job
        self._post("/queue", {"delete": [job.prompt_id]})
        # Backend checks both identifiers atomically, including queue-to-running
        # races; it refuses to interrupt any different job.
        def stopped(ok, detail):
            if ok:
                self._forget(job)
            elif detail:
                self.logged.emit(detail)
        self._owned_stop(job, True, stopped)
        self._terminal(job, "cancelled", preserve=True)

    def cancel_all(self):
        for job in list(self._pending) + list(self._jobs.values()):
            self.cancel(job)

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
        if pid:
            return self._jobs.get(pid)
        return self._active

    def _on_text(self, text: str):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        data = msg.get("data") or {}
        if not isinstance(data, dict):
            return

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
                self.logged.emit(f"started {job.prompt_id}")
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
                role = job.role_of(node)
                self.jobNode.emit(job, role)
                self.logged.emit(f"running {role}")
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
            self.logged.emit(f"error: {msg}")
            self._terminal(job, msg)
            return

    def _on_binary(self, payload: QtCore.QByteArray):
        """Live previews, in either of ComfyUI's two shapes.

        Event 1 (UNENCODED_PREVIEW_IMAGE): event(u32) + format(u32) + image.
        Event 4 (PREVIEW_IMAGE_WITH_METADATA): event(u32) + len(u32) + JSON +
        image — sent instead of event 1 to a client that announced
        `supports_preview_metadata`, which we do in `_on_connected`. Both are
        handled because the flag is the server's choice, not ours: an older
        backend, or one whose handshake we missed, keeps sending event 1.
        """
        raw = bytes(payload)
        if len(raw) < 8:
            return
        event = int.from_bytes(raw[0:4], "big")
        if event == 1:
            job = self._active
            if job is None:
                return
            fmt = int.from_bytes(raw[4:8], "big")
            self.jobPreview.emit(job, raw[8:], "jpeg" if fmt == 1 else "png", {})
            return
        if event != 4:
            return
        mlen = int.from_bytes(raw[4:8], "big")
        if len(raw) < 8 + mlen:
            return
        try:
            meta = json.loads(raw[8:8 + mlen].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            meta = {}
        if not isinstance(meta, dict):
            return
        # Modern ComfyUI previews name their prompt in event-4 metadata. Use it
        # rather than trusting `_active`: a delayed `executing` completion for
        # another queued job can clear `_active` while this job is still sending
        # frames, which silently discarded every otherwise-valid preview.
        job = self._job_for(meta)
        if job is None:
            return
        fmt = "png" if str(meta.get("image_type", "")).endswith("png") else "jpeg"
        self.jobPreview.emit(job, raw[8 + mlen:], fmt, meta)

    def _complete(self, job: Job):
        if job.terminal:
            return
        if job.images:
            self._terminal(job)
        else:
            self._reconcile(job)

    @staticmethod
    def _read_json(reply):
        if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
            raise ValueError(reply.errorString())
        return json.loads(bytes(reply.readAll()).decode("utf-8"))

    def _poll_recovery(self):
        jobs = [j for j in self._jobs.values() if j.needs_poll]
        if not jobs and not self._pending:
            self._recovery_timer.stop()
            return
        for job in jobs:
            self._reconcile(job, check_queue=True)
        for job in list(self._pending):
            self._find_pending(job)

    def reconcile_outstanding(self):
        for job in list(self._jobs.values()):
            self._reconcile(job, check_queue=True)
        for job in list(self._pending):
            self._find_pending(job)

    def _find_pending(self, job):
        if job.terminal or job.reconciling:
            return
        job.reconciling = True
        job.needs_poll = True
        self._recovery_timer.start()
        def accept(rows):
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) < 4:
                    continue
                extra = row[3] or {}
                if extra.get("painter_request_id") == job.request_id and extra.get("client_id") == job.owner_id:
                    job.prompt_id = row[1]
                    if job in self._pending:
                        self._pending.remove(job)
                    self._jobs[job.prompt_id] = job
                    self._remember(job)
                    job.reconciling = False
                    if job.cancelled:
                        self.cancel(job)
                    else:
                        self._reconcile(job, check_queue=True)
                    return True
            return False
        def history(reply):
            handed_off = False
            try:
                doc = self._read_json(reply)
                handed_off = accept([entry.get("prompt") for entry in doc.values()])
                if not handed_off:
                    # Keep the record: history may have been evicted, or the
                    # accepted request may not yet be visible. No blind retry.
                    self._terminal(job, "Submission outcome unknown; retained for recovery, not resubmitted.", preserve=True)
            except (ValueError, TypeError, AttributeError) as exc:
                self.logged.emit(f"submission recovery deferred: {exc}")
            finally:
                if not handed_off:
                    job.reconciling = False
                reply.deleteLater()
        def queue(reply):
            try:
                doc = self._read_json(reply)
                if not accept(doc.get("queue_running", []) + doc.get("queue_pending", [])):
                    self._get("/history?max_items=1000", history)
            except (ValueError, TypeError, AttributeError) as exc:
                job.reconciling = False
                self.logged.emit(f"submission recovery deferred: {exc}")
            finally:
                reply.deleteLater()
        self._get("/queue", queue)

    def _reconcile(self, job: Job, check_queue=False, missing_is_unknown=False):
        if job.terminal or job.reconciling:
            return
        job.reconciling = True
        def queue(reply):
            handed_off = False
            try:
                doc = self._read_json(reply)
                rows = doc.get("queue_running", []) + doc.get("queue_pending", [])
                if job.cancelled and any(len(row) > 1 and row[1] == job.prompt_id for row in rows):
                    self.cancel(job)
                    return
                running = doc.get("queue_running", [])
                if any(len(row) > 1 and row[1] == job.prompt_id for row in running) and self._active is not job:
                    self._active = job
                    if job.started_at is None:
                        job.started_at = time.time()
                        self.jobStarted.emit(job)
                if not any(len(row) > 1 and row[1] == job.prompt_id for row in rows):
                    # Completion can land between our first history read and
                    # this queue snapshot. Check history once more before
                    # declaring the outcome unknown.
                    job.reconciling = False
                    handed_off = True
                    self._reconcile(job, missing_is_unknown=True)
            except (ValueError, TypeError) as exc:
                self.logged.emit(f"queue recovery deferred: {exc}")
            finally:
                if not handed_off:
                    job.reconciling = False
                reply.deleteLater()
        def done(reply):
            handed_off = False
            try:
                doc = self._read_json(reply)
                entry = doc.get(job.prompt_id) or {}
                if not entry:
                    if check_queue:
                        handed_off = True
                        self._get("/queue", queue)
                    elif missing_is_unknown:
                        if job.cancelled:
                            self._terminal(job, "cancelled")
                        else:
                            self._terminal(job, f"Job {job.prompt_id} is absent from queue/history; retained for recovery.", preserve=True)
                    return
                err = extract_history_error(entry)
                if err:
                    self._terminal(job, err)
                    return
                known = {(i.get("node"), i.get("filename"), i.get("subfolder", "")) for i in job.images}
                for node_id, out in (entry.get("outputs") or {}).items():
                    for img in out.get("images") or []:
                        key = (node_id, img.get("filename"), img.get("subfolder", ""))
                        if key not in known:
                            job.images.append(dict(img, node=node_id, role=job.role_of(node_id)))
                            known.add(key)
                if job.images:
                    self._terminal(job)
                elif (entry.get("status") or {}).get("completed"):
                    self._terminal(job, "finished with no images")
            except (ValueError, TypeError, AttributeError) as exc:
                self.logged.emit(f"history recovery deferred: {exc}")
            finally:
                if not handed_off:
                    job.reconciling = False
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

    def upload_image(self, path: str, callback, subfolder: str = "painter"):
        """Put a local file in ComfyUI's input directory; `callback(ref, error)`.

        `ref` is what a LoadImage node takes — "subfolder/name" — and it has to
        travel over HTTP rather than being read off disk: on book the backend is
        top's, behind the ssh forward, and the only thing the two machines share
        is that socket. Uploading under our own subfolder keeps his input
        directory from filling up with painter's drops.
        """
        try:
            fh = QtCore.QFile(path)
            if not fh.open(QtCore.QIODevice.OpenModeFlag.ReadOnly):
                callback(None, f"cannot read {os.path.basename(path)}")
                return
        except Exception as exc:  # noqa: BLE001
            callback(None, f"{exc}")
            return

        upload_name = _upload_name(path)
        multipart = QtNetwork.QHttpMultiPart(
            QtNetwork.QHttpMultiPart.ContentType.FormDataType)
        image_part = QtNetwork.QHttpPart()
        image_part.setHeader(
            QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,
            f'form-data; name="image"; filename="{upload_name}"')
        image_part.setBodyDevice(fh)
        fh.setParent(multipart)          # the device must outlive the request
        multipart.append(image_part)
        for name, value in (("overwrite", "false"), ("subfolder", subfolder)):
            part = QtNetwork.QHttpPart()
            part.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                           f'form-data; name="{name}"')
            part.setBody(value.encode())
            multipart.append(part)

        def done(reply):
            try:
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                    callback(None, raw.strip() or reply.errorString())
                    return
                doc = json.loads(raw)
                sub = doc.get("subfolder") or ""
                name = doc.get("name") or upload_name
                callback(f"{sub}/{name}" if sub else name, None)
            except Exception as exc:  # noqa: BLE001
                callback(None, f"{exc}")
            finally:
                reply.deleteLater()

        req = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.url}/upload/image"))
        req.setTransferTimeout(120000)
        reply = self.net.post(req, multipart)
        multipart.setParent(reply)
        reply.finished.connect(lambda r=reply: done(r))

    def download_to_file(self, image: dict, path, callback):
        """Stream into a caller-owned scratch file; callback(path_or_None, error).

        Two workers bound memory and disk/network concurrency. The final path
        appears only after the complete response is flushed and renamed.
        """
        work = _Download(self.view_url(image), path)
        self._downloads.add(work)
        def done(result, error):
            self._downloads.discard(work)
            callback(result, error)
        work.signals.done.connect(done)
        self._download_pool.start(work)

    def download(self, image: dict, callback):
        """Fetch one output image's bytes."""
        def done(reply):
            try:
                ok = reply.error() == QtNetwork.QNetworkReply.NetworkError.NoError
                callback(bytes(reply.readAll()) if ok else None)
            finally:
                reply.deleteLater()

        req = QtNetwork.QNetworkRequest(QtCore.QUrl(self.view_url(image)))
        req.setTransferTimeout(120000)
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
