"""Coder's Qt layer: processes, the transcript model, sessions and the app.

The protocol objects (claude_proto, codex_proto) are Qt-free; this module
gives them processes and turns their events into list models QML binds to.
Processes are QProcess children of the app. A Claude session owns one
``claude -p`` process; every Codex session in the window shares one private
``codex app-server`` (docs/agents/coder-plan.md section 4.3).

CODER_FIXTURES=<dir> replaces both CLIs with ``fake.Replayer`` over the
fixtures in that directory, for --selftest and the offscreen harnesses.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QProcess,
                            QProcessEnvironment, QTimer, Qt, Property, Signal, Slot)

import claude_proto
import codex_proto
import fake
import history
from proto import new_item, short

STATE_PATH = Path(os.environ.get("CODER_STATE") or (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "coder" / "state.json"))


def find_binary(name):
    env = os.environ.get("CODER_" + name.upper())
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    for d in (Path.home() / ".nix-profile" / "bin", Path.home() / ".local" / "bin",
              Path("/etc/profiles/per-user") / os.environ.get("USER", "") / "bin"):
        if (d / name).exists():
            return str(d / name)
    return name


def cli_version(binary):
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10).stdout
        return out.strip().split()[-1] if out.strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------- processes
class LineProcess(QObject):
    """A CLI child whose stdout is newline-delimited JSON."""

    def __init__(self, argv, cwd, on_line, on_exit, parent=None):
        super().__init__(parent)
        self._buf = b""
        self._err = b""
        self.on_line = on_line
        self.on_exit = on_exit
        self.proc = QProcess(self)
        self.proc.setProgram(argv[0])
        self.proc.setArguments(argv[1:])
        if cwd and os.path.isdir(cwd):
            self.proc.setWorkingDirectory(cwd)
        env = QProcessEnvironment.systemEnvironment()
        # The CLIs must not inherit the Qt/QML plugin paths this wrapper set
        # up for Coder itself; a tool they run could pick them up.
        for k in list(env.keys()):
            if k.startswith(("QT_", "QML", "NIXPKGS_QT")):
                env.remove(k)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(self._read_err)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)

    def start(self):
        self.proc.start()

    def write(self, line):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.write((line + "\n").encode("utf-8"))

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            if raw.strip():
                self.on_line(raw.decode("utf-8", "replace"))

    def _read_err(self):
        self._err = (self._err + bytes(self.proc.readAllStandardError()))[-8000:]

    def _finished(self, code, _status):
        self._read()
        self.on_exit(code, self._err.decode("utf-8", "replace"))

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self.on_exit(127, "could not start %s" % self.proc.program())

    def stop(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.closeWriteChannel()
            self.proc.terminate()
            if not self.proc.waitForFinished(1500):
                self.proc.kill()
                self.proc.waitForFinished(500)


class FakeProcess(QObject):
    """LineProcess's interface over a fixture, dripping lines on a timer."""

    def __init__(self, fixture, kind, on_line, on_exit, parent=None):
        super().__init__(parent)
        self.on_line = on_line
        self.on_exit = on_exit
        self._q = []
        self._t = QTimer(self)
        self._t.setInterval(int(os.environ.get("CODER_FAKE_MS", "4")))
        self._t.timeout.connect(self._drip)
        self.rep = fake.Replayer(fake.load(fixture), kind, self._q.append)

    def start(self):
        self.rep.start()
        self._t.start()

    def write(self, line):
        self.rep.write(line)
        self._t.start()

    def _drip(self):
        if not self._q:
            self._t.stop()
            return
        self.on_line(self._q.pop(0))

    def drain(self):
        while self._q:
            self.on_line(self._q.pop(0))

    def stop(self):
        self._t.stop()


def fixture_for(kind, name=""):
    d = os.environ.get("CODER_FIXTURES")
    if not d:
        return None
    if name:
        return str(Path(d) / name)
    pick = os.environ.get("CODER_FIXTURE_" + kind.upper())
    if pick:
        return str(Path(d) / pick)
    return str(Path(d) / ("claude-approval.jsonl" if kind == "claude" else "codex-synthetic.jsonl"))


# ---------------------------------------------------------------- transcript
ROLES = ["iid", "kind", "text", "title", "detail", "status", "meta", "open", "md"]

_FENCE = re.compile(r"^(\s*)(```|~~~)", re.M)


def md_safe(text):
    """Markdown with raw HTML and remote images neutralised.

    Qt's markdown reader renders inline HTML and fetches images, and model
    output is untrusted text (docs/DESIGN.md 2.6). Outside code, ``<`` becomes
    an entity and ``![`` loses its image meaning; code spans and fences are
    left exactly as written.
    """
    out, in_fence, fence = [], False, ""
    for line in str(text or "").split("\n"):
        m = _FENCE.match(line)
        if m:
            if not in_fence:
                in_fence, fence = True, m.group(2)
            elif m.group(2) == fence:
                in_fence = False
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        parts = line.split("`")
        for i in range(0, len(parts), 2):     # even parts are outside code spans
            parts[i] = parts[i].replace("<", "&lt;").replace("![", "!\\[")
        out.append("`".join(parts))
    return "\n".join(out)


class Transcript(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._index = {}
        self._dirty = set()
        self._flush = QTimer(self)
        self._flush.setInterval(40)        # coalesce streamed deltas
        self._flush.setSingleShot(True)
        self._flush.timeout.connect(self._emit_dirty)
        self.expand_all = False

    countChanged = Signal()

    def roleNames(self):
        return {Qt.UserRole + i: r.encode() for i, r in enumerate(ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        name = ROLES[role - Qt.UserRole] if role >= Qt.UserRole else ""
        if name == "iid":
            return row["id"]
        if name == "open":
            return bool(row.get("_open", self.expand_all))
        if name == "md":
            text = row.get("text", "")
            if row.get("_md_src") != text:
                row["_md_src"], row["_md"] = text, md_safe(text)
            return row["_md"]
        return row.get(name, "")

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    def clear(self):
        self.beginResetModel()
        self._rows, self._index = [], {}
        self.endResetModel()
        self.countChanged.emit()

    def set_items(self, items):
        self.beginResetModel()
        self._rows = [dict(i) for i in items]
        self._index = {r["id"]: n for n, r in enumerate(self._rows)}
        self.endResetModel()
        self.countChanged.emit()

    def upsert(self, item):
        n = self._index.get(item["id"])
        if n is None:
            n = len(self._rows)
            self.beginInsertRows(QModelIndex(), n, n)
            self._rows.append(dict(item))
            self._index[item["id"]] = n
            self.endInsertRows()
            self.countChanged.emit()
        else:
            keep_open = self._rows[n].get("_open")
            new = dict(item)
            # A completed message replaces streamed text; never blank it.
            if not new.get("text") and self._rows[n].get("text") and new["kind"] != "approval":
                new["text"] = self._rows[n]["text"]
            if keep_open is not None:
                new["_open"] = keep_open
            self._rows[n] = new
            self._mark(n)

    def patch(self, p):
        n = self._index.get(p["id"])
        if n is None:
            return
        row = self._rows[n]
        for k, v in p.items():
            if k == "meta_patch":
                row["meta"] = dict(row.get("meta") or {}, **v)
            elif k != "id":
                row[k] = v
        self._mark(n)

    def delta(self, iid, field, text):
        n = self._index.get(iid)
        if n is None:
            return
        self._rows[n][field] = (self._rows[n].get(field) or "") + text
        self._dirty.add(n)
        if not self._flush.isActive():
            self._flush.start()

    def _mark(self, n):
        self._dirty.discard(n)
        ix = self.index(n)
        self.dataChanged.emit(ix, ix)

    def _emit_dirty(self):
        for n in sorted(self._dirty):
            ix = self.index(n)
            self.dataChanged.emit(ix, ix)
        self._dirty.clear()

    def toggle(self, row):
        if 0 <= row < len(self._rows):
            r = self._rows[row]
            r["_open"] = not r.get("_open", self.expand_all)
            self._mark(row)

    def rows(self):
        return self._rows

    def find(self, iid):
        n = self._index.get(iid)
        return None if n is None else self._rows[n]


# ---------------------------------------------------------------- session
class Session(QObject):
    changed = Signal()
    finished = Signal(str, str)        # status, text for a notification

    def __init__(self, app, backend, cwd, native_id="", title="", stored_path="",
                 fork=False, parent=None):
        super().__init__(parent)
        self.app = app
        self.backend = backend
        self.key = "live:%s" % uuid.uuid4().hex[:12]
        self.cwd = cwd
        self.title = title
        self.native_id = native_id
        self.stored_path = stored_path
        self._fork = fork
        self.state = "idle"
        defaults = app.defaults(backend)
        self.model = defaults.get("model", "")
        self.mode = defaults.get("mode", "default" if backend == "claude" else "auto")
        self.effort = defaults.get("effort", "")
        self.models = []
        self.commands = []
        self.used = 0
        self.window = 0
        self.cost = None
        self.transcript = Transcript(self)
        self.diff = ""
        self.updated = time.time()
        self.proto = None
        self.proc = None
        self.pending = 0
        self.unread = False
        self.error = ""

    # -- exposed --------------------------------------------------------------
    def info(self):
        return {"key": self.key, "backend": self.backend, "title": self.display_title(),
                "cwd": self.cwd, "state": self.state, "live": self.proto is not None,
                "updated": self.updated, "pending": self.pending, "unread": self.unread,
                "nativeId": self.native_id}

    def display_title(self):
        if self.title:
            return self.title
        for r in self.transcript.rows():
            if r["kind"] == "user" and r.get("text"):
                return short(r["text"], 80)
        return "new %s session" % self.backend

    # -- lifecycle ------------------------------------------------------------
    def load_stored(self):
        if self.backend == "claude" and self.stored_path:
            self.transcript.set_items(history.load(self.stored_path))
        elif self.backend == "codex" and self.native_id:
            self.app.codex.read_thread(self.native_id, self._stored_codex)

    def _stored_codex(self, thread):
        if thread:
            self.transcript.set_items(codex_proto.thread_items(thread))
            self.changed.emit()

    def ensure_live(self):
        if self.proto is not None:
            return
        if self.backend == "claude":
            self.proto = claude_proto.Claude(self._event, self._write)
            fx = fixture_for("claude")
            if fx:
                self.proc = FakeProcess(fx, "claude", self.proto.on_line, self._exited, self)
            else:
                argv = claude_proto.argv(self.app.claude_bin, model=self.model, mode=self.mode,
                                         effort=self.effort, resume=self.native_id, fork=self._fork)
                self.proc = LineProcess(argv, self.cwd, self.proto.on_line, self._exited, self)
            self.proc.start()
            self.proto.start()
        else:
            server = self.app.codex.ensure()
            self.proto = codex_proto.Codex(self._event, server, cwd=self.cwd, model=self.model,
                                           mode=self.mode, effort=self.effort,
                                           resume=self.native_id, fork=self._fork)
            self.proto.start()
        self._fork = False
        self.changed.emit()

    def _write(self, line):
        if self.proc is not None:
            self.proc.write(line)

    def _exited(self, code, err):
        if self.proto is not None:
            self.proto.on_exit(code, err)
        self.proc = None
        self.proto = None
        if self.state != "idle":
            self._set_state("exited" if code == 0 else "failed")
        self.changed.emit()

    def close(self):
        if self.backend == "claude" and self.proc is not None:
            self.proc.stop()
        elif self.backend == "codex" and self.proto is not None and self.app.codex.server:
            self.app.codex.server.detach(self.proto)
        self.proc = None
        self.proto = None

    # -- actions ----------------------------------------------------------------
    def send(self, text, images):
        self.ensure_live()
        self.unread = False
        self.error = ""
        if self.backend == "codex":
            self.proto.send(text, images)
            # Codex echoes the prompt as an item; Claude rows are made locally.
        else:
            self.proto.send(text, images)
        self.updated = time.time()
        self.changed.emit()

    def interrupt(self):
        if self.proto is not None:
            self.proto.interrupt()

    def answer(self, request_id, decision, note=""):
        if self.proto is not None:
            self.proto.answer(request_id, decision, note)

    def set_answers(self, request_id, answers):
        if self.backend == "claude" and self.proto is not None:
            self.proto.set_answers(request_id, answers)

    def set_model(self, model):
        self.model = model
        self.app.remember(self.backend, model=model)
        if self.proto is not None:
            self.proto.set_model(model)
        self.changed.emit()

    def set_mode(self, mode):
        self.mode = mode
        if mode not in ("bypassPermissions", "full access"):
            self.app.remember(self.backend, mode=mode)
        if self.proto is not None:
            self.proto.set_mode(mode)
        self.changed.emit()

    def set_effort(self, effort):
        self.effort = effort
        self.app.remember(self.backend, effort=effort)
        if self.backend == "codex" and self.proto is not None:
            self.proto.set_effort(effort)
        elif self.backend == "claude" and self.proto is not None:
            # Effort is a launch flag for claude: restart on the next send.
            if self.state == "idle":
                self.close()
        self.changed.emit()

    def rename(self, name):
        self.title = name
        self.app.set_title(self, name)
        if self.backend == "codex" and self.proto is not None:
            self.proto.rename(name)
        self.changed.emit()

    # -- backend events ---------------------------------------------------------
    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.changed.emit()

    def _event(self, ev, p):
        t = self.transcript
        if ev == "item":
            t.upsert(p)
            self._count_pending()
        elif ev == "item_patch":
            t.patch(p)
        elif ev == "delta":
            t.delta(p["id"], p["field"], p["text"])
        elif ev == "state":
            prev = self.state
            self._set_state(p["state"])
            if p["state"] == "waiting" and prev != "waiting":
                self.finished.emit("waiting", "waiting for approval")
        elif ev == "session":
            if p.get("native_id"):
                self.native_id = p["native_id"]
                self.app.forget_stored(self)
            for k in ("model", "mode", "effort"):
                if p.get(k):
                    setattr(self, k, p[k])
            if p.get("cwd"):
                self.cwd = p["cwd"]
            self.changed.emit()
        elif ev == "caps":
            if p.get("models"):
                self.models = p["models"]
            if p.get("commands"):
                self.commands = p["commands"]
            self.changed.emit()
        elif ev == "usage":
            if p.get("used"):
                self.used = int(p["used"])
            if p.get("window"):
                self.window = int(p["window"])
            if p.get("cost") is not None:
                self.cost = p["cost"]
            self.changed.emit()
        elif ev == "limits":
            self.app.set_limit(self.backend, p)
        elif ev == "turn":
            self.updated = time.time()
            if p.get("status") == "failed" and p.get("error"):
                self.error = p["error"]
            last = ""
            for r in reversed(t.rows()):
                if r["kind"] == "assistant":
                    last = r.get("text", "")
                    break
            self.unread = True
            self.finished.emit(p.get("status", "completed"), short(last, 160))
            self.changed.emit()
        elif ev == "title":
            if not self.app.custom_title(self):
                self.title = p.get("title", "")
                self.changed.emit()
        elif ev == "error":
            t.upsert(new_item("err%d" % t.count, "error", text=p.get("message", "")))
        elif ev == "diff":
            self.diff = p.get("diff", "")
            self.changed.emit()

    def _count_pending(self):
        n = sum(1 for r in self.transcript.rows() if r["kind"] == "approval" and r.get("status") == "waiting")
        if n != self.pending:
            self.pending = n
            self.changed.emit()


# ---------------------------------------------------------------- codex host
class CodexHost(QObject):
    """The window's one private ``codex app-server``."""

    threadsChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.server = None
        self.proc = None
        self.threads = []

    def ensure(self):
        if self.server is not None and self.proc is not None:
            return self.server
        self.server = codex_proto.CodexServer(self._write, on_global=self._global)
        fx = fixture_for("codex")
        if fx:
            self.proc = FakeProcess(fx, "codex", self.server.on_line, self._exited, self)
        else:
            self.proc = LineProcess([self.app.codex_bin, "app-server"], str(Path.home()),
                                    self.server.on_line, self._exited, self)
        self.proc.start()
        self.server.start(version=self.app.version)
        return self.server

    def _write(self, line):
        if self.proc is not None:
            self.proc.write(line)

    def _exited(self, code, err):
        srv = self.server
        self.server = None
        self.proc = None
        if srv is not None:
            srv.on_exit(code, err)

    def _global(self, method, p):
        if method == "account/rateLimits/updated":
            rl = p.get("rateLimits") or {}
            prim = rl.get("primary") or {}
            if prim.get("usedPercent") is not None:
                self.app.set_limit("codex", {"label": "5h", "used_percent": prim["usedPercent"],
                                             "resets_at": prim.get("resetsAt")})

    def list_threads(self):
        if os.environ.get("CODER_FIXTURES"):
            return
        srv = self.ensure()

        def done(result, error):
            if error or not isinstance(result, dict):
                return
            self.threads = [{"id": t.get("id", ""), "cwd": str(t.get("cwd") or ""),
                             "title": t.get("name") or "", "prompt": short(t.get("preview") or "", 200),
                             "updated": t.get("updatedAt") or 0, "backend": "codex"}
                            for t in result.get("data") or []]
            self.threadsChanged.emit()
        srv.request("thread/list", {"limit": 100}, done)
        srv.request("account/rateLimits/read", None, self._limits)

    def _limits(self, result, error):
        if isinstance(result, dict):
            self._global("account/rateLimits/updated", {"rateLimits": result.get("rateLimits") or result})

    def read_thread(self, tid, cb):
        srv = self.ensure()
        srv.request("thread/read", {"threadId": tid, "includeTurns": True},
                    lambda r, e: cb((r or {}).get("thread") if not e and isinstance(r, dict) else None))

    def stop(self):
        if self.proc is not None:
            self.proc.stop()
        self.proc = None
        self.server = None


# ---------------------------------------------------------------- session list
SROLES = ["key", "backend", "title", "cwd", "project", "state", "live", "updated",
          "pending", "unread", "when"]


def rel_time(ts):
    if not ts:
        return ""
    d = max(0, time.time() - float(ts))
    if d < 60:
        return "now"
    if d < 3600:
        return "%dm" % (d // 60)
    if d < 86400:
        return "%dh" % (d // 3600)
    if d < 86400 * 30:
        return "%dd" % (d // 86400)
    return time.strftime("%Y-%m-%d", time.localtime(float(ts)))


class SessionList(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    countChanged = Signal()

    def roleNames(self):
        return {Qt.UserRole + i: r.encode() for i, r in enumerate(SROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        name = SROLES[role - Qt.UserRole] if role >= Qt.UserRole else ""
        r = self._rows[index.row()]
        if name == "project":
            return os.path.basename(r.get("cwd", "").rstrip("/")) or r.get("cwd", "") or "no project"
        if name == "when":
            return rel_time(r.get("updated"))
        return r.get(name, "")

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    def set_rows(self, rows):
        keys_old = [r["key"] for r in self._rows]
        keys_new = [r["key"] for r in rows]
        if keys_old == keys_new:
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def row_of(self, key):
        for n, r in enumerate(self._rows):
            if r["key"] == key:
                return n
        return -1


# ---------------------------------------------------------------- the app
class App(QObject):
    changed = Signal()
    currentChanged = Signal()
    sessionChanged = Signal()
    notify = Signal(str, str)

    def __init__(self, version="0", parent=None):
        super().__init__(parent)
        self.version = version
        self.claude_bin = find_binary("claude")
        self.codex_bin = find_binary("codex")
        self._state = self._load_state()
        self.sessions = {}            # key -> Session (opened this run)
        self.stored = {"claude": [], "codex": []}
        self.list = SessionList(self)
        self.codex = CodexHost(self, self)
        self.codex.threadsChanged.connect(self._threads)
        self._current = None
        self.limits = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._rebuild_list)
        self.expand_tools = bool(self._state.get("expandTools", False))

    # -- persisted state ----------------------------------------------------------
    def _load_state(self):
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=1), encoding="utf-8")
            os.replace(tmp, STATE_PATH)
        except OSError:
            pass

    def defaults(self, backend):
        return dict(self._state.get("defaults", {}).get(backend, {}))

    def remember(self, backend, **kw):
        d = self._state.setdefault("defaults", {}).setdefault(backend, {})
        d.update({k: v for k, v in kw.items() if v is not None})
        self._save()

    def set_title(self, session, name):
        titles = self._state.setdefault("titles", {})
        if session.native_id:
            titles["%s:%s" % (session.backend, session.native_id)] = name
            self._save()

    def custom_title(self, session):
        return self._state.get("titles", {}).get("%s:%s" % (session.backend, session.native_id), "")

    @Slot(str, "QVariant")
    def setPref(self, key, value):
        self._state[key] = value
        self._save()

    @Slot(str, "QVariant", result="QVariant")
    def pref(self, key, default=None):
        return self._state.get(key, default)

    # -- project ------------------------------------------------------------------
    @Property(str, notify=changed)
    def project(self):
        p = self._state.get("project") or ""
        if p and os.path.isdir(p):
            return p
        nix = Path.home() / "nix"
        return str(nix) if nix.is_dir() else str(Path.home())

    @Slot(str)
    def setProject(self, path):
        path = path.replace("file://", "")
        if path and os.path.isdir(path):
            self._state["project"] = path
            recent = [p for p in self._state.get("recentProjects", []) if p != path]
            self._state["recentProjects"] = [path] + recent[:9]
            self._save()
            self.changed.emit()

    @Property("QVariantList", notify=changed)
    def recentProjects(self):
        return [p for p in self._state.get("recentProjects", []) if os.path.isdir(p)]

    # -- history ------------------------------------------------------------------
    @Slot()
    def refresh(self):
        self.stored["claude"] = history.scan()
        self.codex.list_threads()
        self._rebuild_list()

    def _threads(self):
        self.stored["codex"] = list(self.codex.threads)
        self._rebuild_list()

    def forget_stored(self, session):
        self._refresh_timer.start()

    def _rebuild_list(self):
        rows, seen = [], set()
        for s in self.sessions.values():
            info = s.info()
            rows.append(info)
            if s.native_id:
                seen.add((s.backend, s.native_id))
        for backend in ("claude", "codex"):
            for h in self.stored[backend]:
                if (backend, h["id"]) in seen:
                    continue
                custom = self._state.get("titles", {}).get("%s:%s" % (backend, h["id"]), "")
                rows.append({"key": "%s:%s" % (backend, h["id"]), "backend": backend,
                             "title": custom or h.get("title") or h.get("prompt") or "untitled",
                             "cwd": h.get("cwd", ""), "state": "", "live": False,
                             "updated": h.get("updated", 0), "pending": 0, "unread": False})
        # Group by project, newest project first, newest session first.
        latest = {}
        for r in rows:
            latest[r["cwd"]] = max(latest.get(r["cwd"], 0), float(r.get("updated") or 0))
        rows.sort(key=lambda r: (-latest[r["cwd"]], r["cwd"], -float(r.get("updated") or 0)))
        self.list.set_rows(rows)
        self.changed.emit()

    # -- sessions -----------------------------------------------------------------
    def _add(self, s):
        self.sessions[s.key] = s
        s.changed.connect(self._session_changed)
        s.finished.connect(lambda status, text, s=s: self._finished(s, status, text))
        return s

    def _session_changed(self):
        self._refresh_timer.start()
        if self.sender() is self._current:
            self.sessionChanged.emit()

    def _finished(self, s, status, text):
        title = s.display_title()
        if status == "waiting":
            self.notify.emit("%s needs approval" % title, text)
        elif status == "failed":
            self.notify.emit("%s failed" % title, s.error or text)
        else:
            self.notify.emit(title, text or status)

    @Slot(str)
    def newSession(self, backend):
        s = self._add(Session(self, backend, self.project, parent=self))
        s.ensure_live()
        self._set_current(s)
        self._rebuild_list()

    @Slot(str)
    def open(self, key):
        s = self.sessions.get(key)
        if s is None and ":" in key and not key.startswith("live:"):
            backend, nid = key.split(":", 1)
            row = next((h for h in self.stored.get(backend, []) if h["id"] == nid), None)
            if row is None:
                return
            s = Session(self, backend, row.get("cwd") or self.project, native_id=nid,
                        title=self._state.get("titles", {}).get(key, "") or row.get("title", ""),
                        stored_path=row.get("path", ""), parent=self)
            s.key = key
            self._add(s)
            s.load_stored()
        if s is not None:
            s.unread = False
            self._set_current(s)
            self._rebuild_list()

    def _set_current(self, s):
        if s is not self._current:
            self._current = s
            self.currentChanged.emit()
            self.sessionChanged.emit()

    @Slot()
    def fork(self):
        s = self._current
        if s is None or not s.native_id:
            return
        f = self._add(Session(self, s.backend, s.cwd, native_id=s.native_id,
                              title="fork of " + s.display_title(), fork=True, parent=self))
        f.transcript.set_items(s.transcript.rows())
        f.model, f.mode, f.effort = s.model, s.mode, s.effort
        f.ensure_live()
        self._set_current(f)
        self._rebuild_list()

    @Slot()
    def closeCurrent(self):
        s = self._current
        if s is None:
            return
        s.close()
        self.sessions.pop(s.key, None)
        self._current = None
        self.currentChanged.emit()
        self.sessionChanged.emit()
        self.refresh()

    def set_limit(self, backend, p):
        self.limits[backend] = p
        self.changed.emit()

    @Property(str, notify=changed)
    def limitsText(self):
        out = []
        for b in ("claude", "codex"):
            p = self.limits.get(b)
            if p:
                out.append("%s %s %s%%" % (b, p.get("label", ""), p.get("used_percent", "?")))
        return "  ".join(out)

    @Property(QObject, notify=currentChanged)
    def current(self):
        return self._current

    @Property(str, notify=currentChanged)
    def currentKey(self):
        return self._current.key if self._current is not None else ""

    @Property(QObject, constant=True)
    def sessionList(self):
        return self.list

    @Property(bool, notify=changed)
    def expandTools(self):
        return self.expand_tools

    @Slot(bool)
    def setExpandTools(self, on):
        self.expand_tools = bool(on)
        self._state["expandTools"] = self.expand_tools
        self._save()
        for s in self.sessions.values():
            s.transcript.expand_all = self.expand_tools
            s.transcript.beginResetModel()
            s.transcript.endResetModel()
        self.changed.emit()

    @Property(int, notify=changed)
    def runningCount(self):
        return sum(1 for s in self.sessions.values() if s.state in ("running", "waiting"))

    def shutdown(self):
        for s in list(self.sessions.values()):
            s.close()
        self.codex.stop()


class SessionView(QObject):
    """What QML binds to for the current session (a stable object)."""

    changed = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        app.sessionChanged.connect(self.changed)
        app.currentChanged.connect(self.changed)
        self._empty = Transcript(self)

    def _s(self):
        return self.app._current

    @Property(bool, notify=changed)
    def active(self):
        return self._s() is not None

    @Property(QObject, notify=changed)
    def transcript(self):
        s = self._s()
        return s.transcript if s is not None else self._empty

    @Property(str, notify=changed)
    def backend(self):
        s = self._s()
        return s.backend if s else ""

    @Property(str, notify=changed)
    def title(self):
        s = self._s()
        return s.display_title() if s else ""

    @Property(str, notify=changed)
    def cwd(self):
        s = self._s()
        return s.cwd if s else ""

    @Property(str, notify=changed)
    def state(self):
        s = self._s()
        return s.state if s else ""

    @Property(bool, notify=changed)
    def busy(self):
        s = self._s()
        return bool(s and s.state in ("running", "waiting", "starting"))

    @Property(bool, notify=changed)
    def canFork(self):
        s = self._s()
        return bool(s and s.native_id and s.state not in ("running", "waiting"))

    @Property(str, notify=changed)
    def model(self):
        s = self._s()
        return s.model if s else ""

    @Property(str, notify=changed)
    def mode(self):
        s = self._s()
        return s.mode if s else ""

    @Property(str, notify=changed)
    def effort(self):
        s = self._s()
        return s.effort if s else ""

    @Property("QVariantList", notify=changed)
    def models(self):
        s = self._s()
        if not s:
            return []
        out = [{"id": m.get("id", ""), "label": m.get("label", "") or m.get("id", "")} for m in s.models]
        if s.model and not any(m["id"] == s.model for m in out):
            out.insert(0, {"id": s.model, "label": s.model})
        if not out:
            out = [{"id": "", "label": "default model"}]
        return out

    @Property("QVariantList", notify=changed)
    def modes(self):
        s = self._s()
        if not s:
            return []
        if s.backend == "claude":
            return [{"id": m, "label": l} for m, l in claude_proto.MODES]
        return [{"id": m, "label": m} for m in codex_proto.MODE_IDS]

    @Property("QVariantList", notify=changed)
    def efforts(self):
        s = self._s()
        if not s:
            return []
        levels = []
        for m in s.models:
            if m.get("id") == s.model and m.get("efforts"):
                levels = list(m["efforts"])
        if not levels:
            levels = list(claude_proto.EFFORTS if s.backend == "claude" else codex_proto.EFFORTS)
        return [{"id": "", "label": "default effort"}] + [{"id": e, "label": e} for e in levels]

    @Property("QVariantList", notify=changed)
    def commands(self):
        s = self._s()
        return [c for c in (s.commands if s else [])]

    @Property(str, notify=changed)
    def usageText(self):
        s = self._s()
        if not s:
            return ""
        parts = []
        if s.used and s.window:
            parts.append("context %d%%" % round(100.0 * s.used / s.window))
        elif s.used:
            parts.append("context %dk" % round(s.used / 1000))
        if s.cost:
            parts.append("$%.2f" % float(s.cost))
        return "  ".join(parts)

    @Property(int, notify=changed)
    def pending(self):
        s = self._s()
        return s.pending if s else 0

    @Property(str, notify=changed)
    def error(self):
        s = self._s()
        return s.error if s else ""

    @Property(str, notify=changed)
    def diff(self):
        s = self._s()
        return s.diff if s else ""

    # -- actions ------------------------------------------------------------------
    @Slot(str, "QVariantList")
    def send(self, text, attachments):
        s = self._s()
        if s is None or (not text.strip() and not attachments):
            return
        images = []
        for a in attachments or []:
            path = str(a).replace("file://", "")
            img = load_image(path)
            if img:
                images.append(img)
        s.send(text, images)

    @Slot()
    def interrupt(self):
        s = self._s()
        if s:
            s.interrupt()

    @Slot(str, str, str)
    def answer(self, request_id, decision, note):
        s = self._s()
        if s:
            s.answer(request_id, decision, note)

    @Slot(str, "QVariant")
    def setAnswers(self, request_id, answers):
        s = self._s()
        if s:
            if hasattr(answers, "toVariant"):
                answers = answers.toVariant()
            s.set_answers(request_id, answers or {})

    @Slot(str)
    def setModel(self, model):
        s = self._s()
        if s and model != s.model:
            s.set_model(model)

    @Slot(str)
    def setMode(self, mode):
        s = self._s()
        if s and mode != s.mode:
            s.set_mode(mode)

    @Slot(str)
    def setEffort(self, effort):
        s = self._s()
        if s and effort != s.effort:
            s.set_effort(effort)

    @Slot(str)
    def rename(self, name):
        s = self._s()
        if s and name.strip():
            s.rename(name.strip())

    @Slot(QObject, int, int, str)
    def correctSpelling(self, target, start, end, replacement):
        # A native commit replaces the range as one edit, keeping Undo.
        from PySide6.QtGui import QGuiApplication, QInputMethodEvent
        target.setProperty("cursorPosition", start)
        event = QInputMethodEvent()
        event.setCommitString(replacement, 0, end - start)
        QGuiApplication.sendEvent(target, event)

    @Slot(int)
    def toggle(self, row):
        s = self._s()
        if s:
            s.transcript.toggle(row)


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp"}


def load_image(path):
    import base64
    ext = os.path.splitext(path)[1].lower()
    if ext not in MIME or not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return None
        data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return None
    return {"path": path, "mime": MIME[ext], "data": data}
