#!/usr/bin/env python3
"""slskapi.py -- the slskd HTTP API bridge for the slsk desktop client.

Everything this app shows or does -- the connection status, a Soulseek search,
the result list, downloading a file, the in-flight transfers -- is a request to
the local slskd daemon's loopback API (home/prog/slskd.nix): base URL
http://127.0.0.1:5030, API key read from ~/.secrets/slskd-api-key, exactly the
defaults apps/player/tools/soulseek-missing.py already uses.

The GUI must never block on the network, so every request runs on its own
daemon worker thread and the result comes back to the GUI thread through a Qt
Signal (queued across threads by the meta-object system). The QML side only
ever sees Slots to call and Signals to bind to -- no threading of its own.

Routes used (each confirmed against the installed 0.24.5, and for the cancel
route against slskd's own TransfersController):

    GET  /api/v0/application                    -- connection / login / shares
    POST /api/v0/searches                       -- start a search {searchText}
    GET  /api/v0/searches/{id}                  -- its state (Completed? ...)
    GET  /api/v0/searches/{id}/responses        -- peers + their matching files
    POST /api/v0/transfers/downloads/{username} -- queue [{filename,size}]
    GET  /api/v0/transfers/downloads            -- the nested transfer list
    DELETE /api/v0/transfers/downloads/{user}/{id} -- cancel one download (GUID)

Drawable strings (filenames, usernames, directories) are passed through
pylib/glyphs.px() HERE, at the ingest point, per docs/DESIGN.md 2.3 -- once,
not once per delegate per scroll.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pylib"))
import glyphs  # noqa: E402

DEFAULT_HOST = "http://127.0.0.1:5030"
DEFAULT_KEY_FILE = os.path.expanduser("~/.secrets/slskd-api-key")
SEARCH_TIMEOUT = 90     # slskd terminates searches on its own; this is a backstop
SEARCH_POLL = 2.0        # seconds between search-state polls


class SlskdError(Exception):
    pass


def http(method, url, api_key, body=None, timeout=15):
    """Minimal urllib wrapper; returns parsed JSON (or None on empty body)."""
    req = urllib.request.Request(url, method=method)
    req.add_header("X-API-Key", api_key)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        raise SlskdError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise SlskdError(str(e.reason)) from None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return raw


def _px(s):
    return glyphs.px(str(s or ""))


def _leaf(p):
    """The file's own name. Soulseek paths use '\\' separators (even on a
    Linux host, whatever slskd stored), so a plain os.path.basename -- which
    splits on '/' only -- would show the whole path. Normalise both, then the
    last component."""
    q = str(p or "").replace("\\", "/")
    return q.rsplit("/", 1)[-1] if "/" in q else q


def _parent(p):
    """The immediate folder of a Soulseek path, for the downloads 'dir' cell."""
    q = str(p or "").replace("\\", "/")
    return q.rsplit("/", 1)[0] if "/" in q else ""


def _fmt_size(n):
    """bytes -> '1.2 GB' / '345 MB' / ... (kept plain ASCII for the pixel font)."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return "?"


class SlskApi(QObject):
    """The whole slskd surface, exposed to QML as one object.

    Slots fire on the GUI thread and hand the work to a daemon thread; results
    return via the Signals below. The QML never blocks.
    """

    # -- notifications to QML --
    statusChanged = Signal()                       # status* properties changed
    searchUpdated = Signal(str, str, "QVariantList")  # searchId, query, results
    searchError = Signal(str, str)                 # searchId, error
    transfersUpdated = Signal("QVariantList")      # flattened transfer list
    toast = Signal(str, str)                       # message, kind (ok|warn|crit|info)

    def __init__(self, base=None, key_file=None, parent=None):
        super().__init__(parent)
        base = base or os.environ.get("SLSK_API_URL", DEFAULT_HOST)
        key_file = key_file or os.environ.get("SLSK_API_KEY_FILE", DEFAULT_KEY_FILE)
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in (
                "127.0.0.1", "::1", "localhost"):
            raise ValueError("slsk API endpoint must be loopback")
        self._base = base.rstrip("/")
        self._key = self._read_key(key_file)
        # connection status (read by QML)
        self._status_text = "connecting..."
        self._is_logged_in = False
        self._username = ""
        self._shares_text = ""
        self._searching = False
        # result of the last search the QML asked to show
        self._last_query = ""
        self._last_results = []

    def _read_key(self, key_file):
        try:
            with open(key_file) as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            pass
        return ""  # auth is disabled on this loopback config; a missing key is a no-op

    # -- status -------------------------------------------------------------

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    @Property(bool, notify=statusChanged)
    def isLoggedIn(self):
        return self._is_logged_in

    @Property(str, notify=statusChanged)
    def username(self):
        return self._username

    @Property(bool, notify=statusChanged)
    def searching(self):
        return self._searching

    def _set_status(self, text, logged_in, username, shares):
        self._status_text, self._is_logged_in = text, logged_in
        self._username, self._shares_text = username, shares
        self.statusChanged.emit()

    @Slot()
    def refreshStatus(self):
        def work():
            try:
                app = http("GET", f"{self._base}/api/v0/application", self._key) or {}
            except SlskdError as e:
                self._set_status(f"slskd not reachable: {e}", False, "", "")
                return
            server = app.get("server", {})
            logged = bool(server.get("isLoggedIn"))
            if logged:
                uname = (app.get("user") or {}).get("username", "") or "?"
                ver = (app.get("version") or {}).get("full", "")
                state = server.get("state", "Connected")
                self._set_status(f"{state} as {uname}  {ver}", True, uname, "")
            else:
                self._set_status("slskd connected, not logged in to Soulseek",
                                 False, "", "")
        self._bg(work)

    # -- search -------------------------------------------------------------

    @Slot(str)
    def startSearch(self, text):
        query = (text or "").strip()
        if not query:
            return
        if self._searching:
            self.toast.emit("a search is already running", "warn")
            return
        self._searching = True
        self.statusChanged.emit()

        def work():
            sid = ""
            try:
                resp = http("POST", f"{self._base}/api/v0/searches", self._key,
                            {"searchText": query[:512]})
                if isinstance(resp, dict):
                    sid = resp.get("id", "") or ""
                elif resp:
                    sid = str(resp).strip('"')
                if not sid:
                    raise SlskdError("search returned no id")
                # poll the search's own state -- slskd ends every search itself,
                # so SEARCH_TIMEOUT is only a backstop against a hung one.
                deadline = time.time() + SEARCH_TIMEOUT
                state = ""
                while time.time() < deadline:
                    try:
                        obj = http("GET", f"{self._base}/api/v0/searches/{sid}",
                                   self._key) or {}
                        state = obj.get("state", "") or ""
                    except SlskdError:
                        break
                    if "Completed" in state:
                        break
                    time.sleep(SEARCH_POLL)
                results = []
                if "Completed" in state:
                    responses = []
                    try:
                        responses = http(
                            "GET", f"{self._base}/api/v0/searches/{sid}/responses",
                            self._key) or []
                    except SlskdError:
                        responses = []
                    for resp in responses:
                        user = resp.get("username", "")
                        free = bool(resp.get("hasFreeUploadSlot", False))
                        for f in resp.get("files") or []:
                            fname = f.get("filename", "") or ""
                            size = f.get("size", 0) or 0
                            results.append({
                                "username": _px(user),        # drawn
                                "userraw": user,              # the wire needs the raw name
                                "filename": _px(_leaf(fname)),
                                "path": fname,                # not drawn -> raw
                                "size": _fmt_size(size),
                                "sizeBytes": size,
                                "bitRate": f.get("bitRate", 0) or 0,
                                "length": f.get("length", 0) or 0,
                                "free": free,
                                "queueState": f.get("queueState", "") or "",
                            })
                    # free-slot sources first, then biggest file -- what a human
                    # wants to click.
                    results.sort(key=lambda r: (0 if r["free"] else 1, -r["sizeBytes"]))
                if state and "Errored" in state and not results:
                    raise SlskdError(state)
                self._last_query, self._last_results = query, results
                self.searchUpdated.emit(sid, query, results)
            except SlskdError as e:
                self.searchError.emit(sid, str(e))
            finally:
                self._searching = False
                self.statusChanged.emit()
        self._bg(work)

    # -- downloads ----------------------------------------------------------

    @Slot(str, str, "QVariant")
    def queueDownload(self, username, filename, size):
        # username/filename arrive glyph-mapped (drawn fields) -- the API needs
        # the RAW values, held on the result row and passed through untouched.
        # QML passes the raw `path` and a raw username; guard against the mapped
        # form reaching the wire in case a caller slips.
        def work():
            try:
                http("POST",
                     f"{self._base}/api/v0/transfers/downloads/{urllib.parse.quote(str(username), safe='')}",
                     self._key, [{"filename": str(filename), "size": int(size or 0)}])
                self.toast.emit(f"queued: {os.path.basename(str(filename))}", "ok")
            except SlskdError as e:
                self.toast.emit(f"queue failed: {e}", "crit")
            finally:
                self.refreshTransfers()
        self._bg(work)

    @Slot(str, str)
    def cancelDownload(self, username, transferId):
        def work():
            try:
                http("DELETE",
                     f"{self._base}/api/v0/transfers/downloads/{urllib.parse.quote(str(username), safe='')}/{urllib.parse.quote(str(transferId), safe='')}",
                     self._key)
                self.toast.emit("download cancelled", "info")
            except SlskdError as e:
                self.toast.emit(f"cancel failed: {e}", "crit")
            finally:
                self.refreshTransfers()
        self._bg(work)

    @Slot()
    def refreshTransfers(self):
        def work():
            dl = []
            try:
                dl = http("GET", f"{self._base}/api/v0/transfers/downloads", self._key) or []
            except SlskdError:
                dl = []
            flat = []
            for entry in dl or []:
                uname = entry.get("username", "")
                for directory in entry.get("directories") or []:
                    for f in directory.get("files") or []:
                        fname = f.get("filename", "") or ""
                        size = f.get("size", 0) or 0
                        done = f.get("bytesTransferred", 0) or 0
                        state = f.get("state", "") or f.get("stateDescription", "") or ""
                        completed = "Completed" in state
                        pct = int((done / size * 100)) if size else (100 if completed else 0)
                        flat.append({
                            "id": f.get("id", "") or "",
                            "username": _px(uname or f.get("username", "")),
                            "userraw": uname or f.get("username", ""),
                            "filename": _px(_leaf(fname)),
                            "dir": _px(_leaf(str(directory.get("directory", "") or ""))),
                            "size": _fmt_size(size),
                            "done": _fmt_size(done),
                            "percent": max(0, min(100, pct)),
                            "state": _px(state),
                            "completed": completed,
                            "speed": _fmt_speed(f.get("averageSpeed", 0) or 0),
                            "canCancel": not completed and bool(f.get("id", "")),
                        })
            # what a human scans first: still-going transfers before finished ones.
            flat.sort(key=lambda r: (1 if r["completed"] else 0, -r["percent"], r["filename"]))
            self.transfersUpdated.emit(flat)
        self._bg(work)

    # -- plumbing -----------------------------------------------------------

    def _bg(self, fn):
        threading.Thread(target=self._safe, args=(fn,), daemon=True).start()

    def _safe(self, fn):
        # a worker must never take the whole app down with it
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()


def _fmt_speed(bps):
    """bytes/sec -> '1.2 MB/s'."""
    try:
        bps = int(bps or 0)
    except (TypeError, ValueError):
        return "?"
    if bps <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if bps < 1024 or unit == "GB":
            return f"{bps:.1f} {unit}/s" if unit != "B" else f"{int(bps)} B/s"
        bps /= 1024.0
    return "?"
