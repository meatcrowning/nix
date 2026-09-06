"""Named conversation-session QObject for chatter.

The store protocol remains in ``tools/sessions-store.py``.  This module owns
only the asynchronous Qt seam that exposes it to QML.
"""
import json
import os
import shlex
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, Signal, Slot

HERE = Path(__file__).resolve().parent
SESSIONS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SESSIONS", "~/.local/share/oracle/sessions"))
SESSIONS_SCRIPT = str(HERE / "tools" / "sessions-store.py")
STORE_LOCAL = bool(os.environ.get("ORACLE_MEMORY")
                   or os.environ.get("ORACLE_SESSIONS"))
ON_BOOK = socket.gethostname() == "book"


class Sessions(QObject):
    """Named conversation sessions and their persisted transcripts."""

    listChanged = Signal()
    loaded = Signal(str, str, str)
    saved = Signal(str, str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._list = []
        self._procs = []

    @Property("QVariantList", notify=listChanged)
    def sessions(self):
        return self._list

    @staticmethod
    def _store_argv():
        if ON_BOOK and not STORE_LOCAL:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(SESSIONS_SCRIPT),
                     shlex.quote(SESSIONS_ROOT)]
            return argv
        return [sys.executable, SESSIONS_SCRIPT, SESSIONS_ROOT]

    def _run(self, req, on_done):
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
            except RuntimeError:
                return
            proc.deleteLater()
            try:
                obj = json.loads(out.decode("utf-8", "replace") or "{}")
            except ValueError:
                tail = err.decode("utf-8", "replace").strip().splitlines()
                obj = {"error": "session store failed: "
                       + (tail[-1] if tail else "no output")}
            on_done(obj if isinstance(obj, dict) else {"error": "bad store reply"})

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)
        argv = self._store_argv()
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @Slot()
    def refresh(self):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self._list = obj.get("sessions", [])
            self.listChanged.emit()
        self._run({"op": "list"}, done)

    @Slot(str)
    def open(self, sid):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.loaded.emit(obj.get("id", ""), obj.get("title", ""),
                             json.dumps(obj.get("turns", [])))
        self._run({"op": "load", "id": sid}, done)

    @Slot(str, str, str)
    def save(self, sid, title, turns_json):
        try:
            turns = json.loads(turns_json or "[]")
        except ValueError:
            turns = []
        if not sid or not turns:
            return

        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.saved.emit(obj.get("id", sid), obj.get("title", title))
            self.refresh()
        self._run({"op": "save", "id": sid, "title": title, "turns": turns}, done)

    @Slot(str)
    def remove(self, sid):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.refresh()
        self._run({"op": "delete", "id": sid}, done)
