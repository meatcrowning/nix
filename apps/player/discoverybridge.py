"""Qt adapter for Discover; one daemon worker serializes catalog writes."""
import copy
import json
from pathlib import Path
import queue
import socket
import threading
import time

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl

from discovery import Catalog, https_url
import discoveryacquire


class Discovery(QObject):
    changed = Signal()
    itemsChanged = Signal()
    settingsChanged = Signal()
    _ready = Signal(object)
    _preview = Signal(object, int)
    _ack = Signal(object)

    def __init__(self, db, state, root, player, parent=None):
        super().__init__(parent)
        self._player = player
        self._snapshot = {"items": [], "settings": {}, "message": "", "busy": False}
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._cancel_acquisition = threading.Event()
        self._outbox_path = Path(state) / "discovery-intents.json"
        try:
            self._outbox = json.loads(self._outbox_path.read_text())
        except (OSError, ValueError):
            self._outbox = []
        if not isinstance(self._outbox, list):
            self._outbox = []
        self._sequence = max([time.time_ns()] + [int(i[3]) for i in self._outbox])
        self._ack.connect(self._acknowledge)
        for intent in self._outbox:
            self._queue.put(tuple(intent))
        self._active = False
        self._pending_tick = False
        self._ready.connect(self._receive)
        self._preview.connect(self._play_preview)
        self._thread = threading.Thread(target=self._run, args=(db, state, root), daemon=True, name="player-discovery")
        self._thread.start()
        self._timer = QTimer(self)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @Property("QVariantList", notify=itemsChanged)
    def items(self): return self._snapshot["items"]

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self): return self._snapshot["settings"]

    @Property(str, notify=changed)
    def message(self): return self._snapshot["message"]

    @Property(bool, notify=changed)
    def busy(self): return self._snapshot["busy"]

    @Property(bool, constant=True)
    def canAcquire(self): return socket.gethostname().split(".")[0] == "top"

    def _write_outbox(self):
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._outbox_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._outbox))
        temp.chmod(0o600)
        temp.replace(self._outbox_path)

    def _enqueue(self, action, key="", value=None):
        token = 0
        if action in ("configure", "feedback"):
            self._sequence += 1
            token = self._sequence
            self._outbox.append([action, key, value, token])
            try:
                self._write_outbox()
            except OSError:
                self._outbox.pop()
                self._snapshot["message"] = "Could not save discovery settings or feedback."
                self.changed.emit()
                return
        self._queue.put((action, key, value, token))

    def _acknowledge(self, token):
        self._outbox = [i for i in self._outbox if i[3] > token]
        try:
            self._write_outbox()
        except OSError:
            pass  # Applied sequence lives atomically with catalog state; replay is inert.

    def _receive(self, snapshot):
        items_changed = self._snapshot["items"] != snapshot["items"]
        settings_changed = self._snapshot["settings"] != snapshot["settings"]
        self._snapshot = snapshot
        if items_changed:
            self.itemsChanged.emit()
        if settings_changed:
            self.settingsChanged.emit()
        self.changed.emit()
        if snapshot["settings"].get("mode") in ("review", "automatic"):
            self._active = True
        if not snapshot["busy"]:
            self._pending_tick = False

    def _tick(self):
        if self._active and not self._pending_tick and not self.busy:
            self._pending_tick = True
            self._enqueue("tick")

    @Slot()
    def activate(self):
        if not self._active:
            self._active = True
            self._enqueue("activate")

    @Slot()
    def refresh(self):
        if not self.busy:
            self._snapshot["busy"] = True
            self.changed.emit()
            self._enqueue("refresh")

    @Slot(str)
    def expand(self, key): self._enqueue("resolve", key)

    @Slot(str, int)
    def preview(self, key, index): self._enqueue("preview", key, index)

    @Slot(str, str)
    def feedback(self, key, value): self._enqueue("feedback", key, value)

    @Slot(str)
    def acquire(self, key): self._enqueue("acquire", key)

    @Slot(str, "QVariant")
    def configure(self, name, value):
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if name == "mode" and value == "automatic" and not self.canAcquire:
            self._snapshot["message"] = "Enable automatic acquisition on top."
            self.changed.emit()
            return
        if name == "mode":
            self._cancel_acquisition.set()
        self._enqueue("configure", name, value)

    @Slot(str)
    def openSource(self, url):
        if https_url(url, ("music.apple.com", "itunes.apple.com", "last.fm", "bandcamp.com")):
            QDesktopServices.openUrl(QUrl(url))

    def _play_preview(self, item, index):
        if not self._stop.is_set():
            self._player.startPreview(item, index)

    def shutdown(self):
        self._stop.set()
        self._cancel_acquisition.set()
        self._timer.stop()
        self._enqueue("stop")
        # Accepted local edits have a durable outbox; replay after a slow network
        # shutdown is idempotent and never waits on the remote provider.
        self._thread.join(timeout=.2)

    def _run(self, db, state, root):
        catalog = Catalog(db, state)
        message = ""

        def publish(busy=False):
            nonlocal message
            if self._stop.is_set():
                return
            try:
                items = catalog.visible()
            except Exception:
                items = []
                message = "Library is not ready; refresh after scanning."
            self._ready.emit(copy.deepcopy({"items": items, "settings": catalog.settings,
                                           "message": message, "busy": busy}))

        publish()
        while True:
            action, key, value, token = self._queue.get()
            if token and token <= catalog.state.get("intent_seq", 0):
                self._ack.emit(token)
                continue
            if action == "stop":
                return
            if self._stop.is_set() and action not in ("feedback", "configure"):
                continue
            message = ""
            publish(True)
            succeeded = False
            before_edit = copy.deepcopy(catalog.state) if token else None
            try:
                if (action == "refresh" or action == "activate" and not catalog.state["items"]
                        or action == "tick" and catalog.settings["mode"] != "manual"
                        and time.time() - catalog.state.get("refreshed", 0) > 86400):
                    message = catalog.refresh()
                elif action in ("resolve", "preview"):
                    item = catalog.resolve(key)
                    if action == "preview" and not self._stop.is_set():
                        if not any(t["preview"] for t in item["tracks"]):
                            message = "No preview available. Use the source link to listen on its website."
                        else:
                            self._preview.emit(copy.deepcopy(item), value)
                elif action == "feedback":
                    if value == "undo":
                        message = "Dismissals cleared. Refresh to include those releases again."
                        for fb in catalog.state["feedback"].values():
                            fb.pop("dismissed", None)
                    elif value in ("saved", "liked", "dismissed"):
                        fb = catalog.state["feedback"].setdefault(key, {})
                        fb[value] = not fb.get(value, False)
                    catalog.state["intent_seq"] = token
                    catalog.save()
                elif action == "configure":
                    allowed = {"mode": ("manual", "review", "automatic"), "weekly": (1, 2, 5, 10),
                               "budget": (1, 2, 5, 10), "quality": ("lossless", "high", "any")}
                    if key in allowed and value in allowed[key]:
                        if key == "mode" and value == "automatic" and not self.canAcquire:
                            raise ValueError("Enable automatic acquisition on top.")
                        catalog.settings[key] = value
                        if key == "mode" and value == "automatic":
                            self._cancel_acquisition.clear()
                        if key == "mode":
                            catalog.settings["host"] = socket.gethostname().split(".")[0]
                        catalog.state["intent_seq"] = token
                        catalog.save()
                elif action == "acquire":
                    self._cancel_acquisition.clear()
                    discoveryacquire.acquire(catalog, key, root, self._cancel_acquisition)
                if action in ("tick", "activate", "refresh") and not self._stop.is_set():
                    if self.canAcquire:
                        discoveryacquire.reconcile(catalog)
                    mode = catalog.settings["mode"]
                    candidates = [r for r in catalog.visible() if not r["status"]
                                  and catalog.state.get("retry_after", {}).get(r["key"], 0) <= time.time()]
                    if mode == "review":
                        for r in candidates[:catalog.settings["weekly"]]:
                            catalog.state["requests"][r["key"]] = {"status": "review", "detail": "Ready for your approval"}
                        catalog.save()
                    elif mode == "automatic" and candidates and self.canAcquire:
                        candidate = candidates[0]
                        key = candidate["key"]
                        try:
                            if not self._cancel_acquisition.is_set():
                                discoveryacquire.acquire(catalog, key, root, self._cancel_acquisition, automatic=True)
                        except discoveryacquire.DeferredAcquisition:
                            catalog.state.setdefault("retry_after", {})[key] = time.time() + 3600
                            catalog.save()
                            raise
                        except Exception as exc:
                            if key not in catalog.state["requests"]:
                                catalog.state["requests"][key] = {"status": "review", "detail": str(exc) if isinstance(exc, ValueError) else "Acquisition service unavailable"}
                                catalog.save()
                            raise
                succeeded = True
            except Exception as exc:
                if before_edit is not None:
                    catalog.state = before_edit
                    catalog.settings = catalog.state["settings"]
                # Do not expose URLs/API credentials from transport exceptions.
                message = str(exc) if isinstance(exc, ValueError) else "Discovery request failed; check the connection or acquisition service."
            if succeeded and token and catalog.state.get("intent_seq") == token:
                self._ack.emit(token)
            publish()
