#!/usr/bin/env python3
"""oracle — a deliberately small chat window for the local ollama daemon.

The twelfth vendored app, and the plainest: a MODEL SELECTOR filled from the
ollama daemon's own `/api/tags`, and a PROMPT BOX that sends one chat turn to
`/api/chat` and shows the streamed reply. Nothing more — no history persistence,
no settings, no system prompt. It exists to talk to `http://127.0.0.1:11434`
and get out of the way.

It draws like the rest of the desktop rather than choosing anything here: pixel
font at the desktop's own size through `DeskStyle`, the wal palette parsed and
watched out of the panel's `Theme.qml` (mirrors reader/filer/viewer), motion
from `qmlcommon/Motion.qml`, `Kinetic*` views, and its titlebar chrome drawn by
the hyprvtb compositor plugin through `pylib/vtbclient.py` — see docs/DESIGN.md.

The whole ollama seam is `Ollama` below, on `QNetworkAccessManager`: `/api/tags`
for the model list, and a STREAMING `/api/chat` POST whose NDJSON reply is
parsed line by line and emitted as it arrives, so the reply grows on screen the
way it comes off the model.
"""
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import shlex

from PySide6.QtCore import (QObject, Slot, Signal, Property, QUrl,
                            QFileSystemWatcher, QProcess, QProcessEnvironment,
                            QTimer)
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                               QNetworkReply)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)

#: The local ollama daemon. Loopback-pinned like everything else that speaks to
#: a local backend here — never a new listener (root AGENTS.md → the tailnet).
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

#: Tavily's REST search endpoint. Reached only when the model calls the
#: `web_search` tool AND a key is configured — oracle opens no listener, and
#: without a key the tool reports itself unavailable rather than reaching out.
TAVILY_URL = "https://api.tavily.com/search"

#: The web-search tool offered to ollama on EVERY turn (his call — no toggle,
#: same as the file tools). ollama's function-calling: the model may emit a
#: `tool_calls` entry naming this and we run it, feed the result back as a
#: `role: tool` message, and let the model summarize and cite (the loop lives in
#: `Ollama` below).
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current or factual information you may "
            "not know. Returns a short answer plus source pages (title, URL, "
            "snippet). Use it for recent events, specific facts, or anything "
            "you are unsure of, then cite the sources in your reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "The search query."},
            },
            "required": ["query"],
        },
    },
}

#: The FILE TOOLS oracle offers the model on EVERY turn (no toggle — his call:
#: "always available to the model"). Reading and manipulation both, but every
#: one runs THROUGH tools/sandbox-fs.py against a jailed root the model cannot
#: escape (see FS below and apps/oracle/AGENTS.md). Descriptions tell the model
#: the paths are sandbox-relative and reads are paginated, so it asks for more
#: rather than assuming a short read is the whole file.
FILE_TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": ("List a directory in your sandbox. Paths are relative to "
                        "the sandbox root; '.' is the root. Long listings are "
                        "truncated."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Directory to list, sandbox-relative. Default '.'."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": ("Read a text file from your sandbox. Returns at most a few "
                        "hundred lines; if `truncated` is true read again with "
                        "`offset` set to `next_offset` to page through the rest."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File to read, sandbox-relative."},
            "offset": {"type": "integer",
                       "description": "0-based line to start at. Default 0."},
            "limit": {"type": "integer",
                      "description": "Max lines to return this call."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": ("Create or overwrite a text file in your sandbox with the "
                        "given content. Parent directories are created."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File to write, sandbox-relative."},
            "content": {"type": "string", "description": "Full new file contents."}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": ("Replace an exact substring in a sandbox file. `old` must "
                        "match once unless `replace_all` is set. Use write_file to "
                        "create a file or replace it wholesale."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File to edit, sandbox-relative."},
            "old": {"type": "string", "description": "Exact text to find."},
            "new": {"type": "string", "description": "Text to put in its place."},
            "replace_all": {"type": "boolean",
                            "description": "Replace every match, not just a unique one."}},
            "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "move_path",
        "description": "Move or rename a file or directory within your sandbox.",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string", "description": "Path to move, sandbox-relative."},
            "dst": {"type": "string", "description": "Destination, sandbox-relative."}},
            "required": ["src", "dst"]}}},
    {"type": "function", "function": {
        "name": "delete_path",
        "description": ("Delete a file or directory in your sandbox. Pass "
                        "`recursive` to delete a non-empty directory."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path to delete, sandbox-relative."},
            "recursive": {"type": "boolean",
                          "description": "Delete a directory and its contents."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "make_dir",
        "description": "Create a directory (and parents) in your sandbox.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory to create, sandbox-relative."}},
            "required": ["path"]}}},
]

#: The CURRENT-TIME tool, offered on every turn beside the file and web tools.
#: Without it the model answers "now" from its training and gets timezone/DST
#: conversions wrong (it put Juneau an hour out — the classic AKDT/AKST slip).
#: This resolves any IANA zone through Python's zoneinfo, which carries the real
#: DST rules, so the model never has to compute an offset itself. Handled
#: locally in `Ollama` (no subprocess — a wall-clock instant is host-neutral).
TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": (
            "Get the current date and time. Pass an IANA timezone name to get "
            "the time there (correct for daylight saving); omit it for UTC. "
            "Always use this instead of computing a timezone offset yourself."),
        "parameters": {"type": "object", "properties": {
            "timezone": {"type": "string",
                         "description": ("IANA timezone, e.g. 'America/Juneau' "
                                         "or 'Europe/London'. Omit for UTC.")}},
            "required": []}},
}

#: tool name -> the `op` tools/sandbox-fs.py dispatches on.
FILE_OP = {"list_dir": "list", "read_file": "read", "write_file": "write",
           "edit_file": "edit", "move_path": "move", "delete_path": "delete",
           "make_dir": "mkdir"}
FILE_TOOL_NAMES = set(FILE_OP)

#: How many tool rounds one turn may take before we stop looping and let the
#: model answer with what it has — a guard against a model that keeps searching.
MAX_TOOL_ROUNDS = 4

#: The file tools' JAIL. Every file op runs against this one directory and
#: cannot escape it (tools/sandbox-fs.py enforces it, symlinks included). It is
#: the ONLY thing to change to widen the sandbox later ("maybe we let it run
#: free") — point ORACLE_SANDBOX at ~ or / and the tools reach further, no code
#: change. It lives on TOP, where oracle's ollama compute is: expanded here to
#: an absolute /home/lam/... path (identical on both machines, user `lam`) so it
#: needs no shell tilde-expansion when handed to top over ssh.
SANDBOX_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SANDBOX", "~/.local/share/oracle/sandbox"))

#: The jailed executor. Same absolute path on top and book (the repo lives at
#: /home/lam/nix on both), so `python3 <this>` runs unchanged locally on top or
#: over ssh to top from book. Pure stdlib — top's system python3 runs it.
FS_SCRIPT = str(HERE / "tools" / "sandbox-fs.py")

#: The named-session store. ONE canonical location so both machines share one
#: set of conversations rather than a per-machine split ("for now", his words).
#: Like the file-tool sandbox it lives where oracle's compute is — on `top` —
#: run locally there and over the tunnel's ssh master from `book`
#: (`Sessions._store_argv`, host-branched exactly like the file tools). Absolute
#: /home/lam/... path (identical on both, user `lam`) so it needs no shell
#: tilde-expansion when handed to top over ssh. Override with $ORACLE_SESSIONS.
SESSIONS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SESSIONS", "~/.local/share/oracle/sessions"))
SESSIONS_SCRIPT = str(HERE / "tools" / "sessions-store.py")

#: Which machine we run on, by OS hostname (`top` / `book`) — NOT the flake
#: attribute. On `book` there is no local `ollama.service`; the daemon lives on
#: `top` and oracle reaches both its HTTP API (over the tunnel that forwards
#: 11434, tools/ollama-tunnel.sh) and — for start/stop — its systemd unit over
#: the same ssh. See Backend below.
ON_BOOK = socket.gethostname() == "book"

#: oracle's own config dir (shared with tavily.key). Two optional, no-rebuild
#: files drive the model selector — drop them in and relaunch, same as the key:
#:   `last-model`     one line, the model to pre-select next launch. oracle
#:                    writes it on every pick/send, so the last model he used is
#:                    the default the next time he opens the window.
#:   `suggested.json` a JSON array of model names AGENTS write to recommend a
#:                    model. Those present in /api/tags are ranked ABOVE the rest
#:                    of the dropdown, in the file's order (see apps/oracle/AGENTS.md).
CONFIG_DIR = Path.home() / ".config" / "oracle"
LAST_MODEL_PATH = CONFIG_DIR / "last-model"
SUGGESTED_PATH = CONFIG_DIR / "suggested.json"


def tavily_key():
    """The Tavily API key, never hardcoded (see apps/oracle/AGENTS.md).

    Same shape as `OLLAMA` reads its endpoint: an env var first
    (`TAVILY_API_KEY`), then a convenience fallback file so the key can be set
    without a rebuild — `~/.config/oracle/tavily.key`, one line, the key. Empty
    string when neither is present; the tool then reports itself unavailable."""
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if key:
        return key
    try:
        return (Path.home() / ".config" / "oracle" / "tavily.key"
                ).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---- the wallpaper palette (mirrors reader/viewer/filer — see reader/main.py) --
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (identical to reader's and viewer's)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)   # dir watch catches atomic replaces
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge — oracle draws no chrome of its own, so the
    compositor draws the titlebar (docs/DESIGN.md §12). oracle has no history and
    no view modes, so it registers with the defaults and no buttons; the window
    title is still drawn by the plugin. The one thing it publishes is a FOOTER
    naming the connected daemon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient()

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Ollama(QObject):
    """The whole ollama seam: the model list and one streamed chat turn.

    `refreshModels` GETs `/api/tags`; `send` POSTs a single-turn `/api/chat`
    with `stream: true` and emits each NDJSON delta as it arrives, so QML never
    parses the wire — it receives `replyStarted` / `replyChunk` / `replyDone`,
    or `replyError` with a reason it can draw (docs/DESIGN.md §10: an action that
    cannot be reported must say so, not silently do nothing). One turn at a
    time: a new `send` aborts any reply still streaming."""

    modelsChanged = Signal()
    lastModelChanged = Signal()
    busyChanged = Signal()
    modelsError = Signal(str)

    replyStarted = Signal()
    replyChunk = Signal(str)
    replyThinking = Signal(str)   # a "thinking" model's reasoning deltas
    replyThinkTokens = Signal(int)  # running count of reasoning tokens this turn
    replyDone = Signal()
    replyError = Signal(str)

    # The web_search tool-call loop, surfaced so QML can draw a subordinated
    # "sources" disclosure per turn (docs/DESIGN.md §9.1): the model asked to
    # search, the search returned N sources (as themed-link markdown), or it
    # failed with a reason.
    webSearchStarted = Signal(str)          # query
    webSearchDone = Signal(str, str, int)   # query, sources markdown, result count
    webSearchError = Signal(str, str)       # query, reason

    # The file-tool activity, surfaced so QML can draw the same subordinated
    # per-turn disclosure the web search gets (docs/DESIGN.md §9.1, §10 — the
    # model touching files is shown, never silent): one op began, and one
    # finished with a short outcome line and whether it succeeded.
    fileToolStarted = Signal(str)           # a short "read notes.md" heading
    fileToolDone = Signal(str, bool)        # outcome line, ok

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._models = []
        self._last_model = self._load_last_model()  # pre-select this next launch
        self._suggested = self._load_suggested()    # agent-recommended, ranked first
        self._suggested_count = 0                   # how many of _models are suggested
        self._busy = False
        self._reply = None       # the in-flight chat QNetworkReply, if any
        self._buf = b""          # partial NDJSON line carried between reads
        self._think_tokens = 0   # reasoning tokens seen this turn (one per delta)
        self._model = ""         # the model for the current turn
        self._messages = []      # the growing message list across a tool loop
        self._acc_content = ""   # assistant content accumulated in this sub-turn
        self._tool_calls = []    # tool calls accumulated in this sub-turn
        self._tool_results = []  # results being gathered for the current round
        self._rounds = 0         # tool rounds taken this turn (MAX_TOOL_ROUNDS cap)
        self._procs = []         # live file-tool QProcesses, so none is GC'd mid-run

    # ---- model list ----

    @Property("QStringList", notify=modelsChanged)
    def models(self):
        return self._models

    @Property(str, notify=lastModelChanged)
    def lastModel(self):
        return self._last_model

    @Property(int, notify=modelsChanged)
    def suggestedCount(self):
        """How many leading entries of `models` are agent-suggested — so the
        dropdown can rule off the suggested group from the rest (§7.2)."""
        return self._suggested_count

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    # ---- the last-picked model, and the agent-suggested ranking ----

    @staticmethod
    def _load_last_model():
        try:
            return LAST_MODEL_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _load_suggested():
        """The agent-suggested model names, de-duped, order preserved. Missing
        or malformed file (or anything but a JSON list of strings) → none."""
        try:
            data = json.loads(SUGGESTED_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out, seen = [], set()
        for x in data:
            if isinstance(x, str) and x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _order(self, names):
        """Agent-suggested models the daemon actually has come first, in the
        order they were suggested; everything else follows alphabetically. Sets
        `_suggested_count` as a side effect (the size of that leading group)."""
        present = set(names)
        top = [m for m in self._suggested if m in present]
        seen = set(top)
        rest = sorted((n for n in names if n not in seen), key=str.lower)
        self._suggested_count = len(top)
        return top + rest

    @Slot(str)
    def rememberModel(self, name):
        """Persist `name` as the model to pre-select next launch (a pick or a
        send). No-op when unchanged; a write failure is swallowed — the setting
        is a convenience, not load-bearing."""
        name = (name or "").strip()
        if not name or name == self._last_model:
            return
        self._last_model = name
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            LAST_MODEL_PATH.write_text(name + "\n", encoding="utf-8")
        except OSError:
            pass
        self.lastModelChanged.emit()

    @Slot()
    def refreshModels(self):
        req = QNetworkRequest(QUrl(OLLAMA + "/api/tags"))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_tags(reply))

    def _on_tags(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.modelsError.emit(reply.errorString())
                return
            data = bytes(reply.readAll().data())
            obj = json.loads(data or b"{}")
            # Re-read the suggestions here (not just at startup) so an agent that
            # writes suggested.json while oracle runs is honoured on the next
            # daemon poll, with no relaunch.
            self._suggested = self._load_suggested()
            names = self._order([m.get("name", "") for m in obj.get("models", [])
                                 if m.get("name")])
            if names != self._models:
                self._models = names
                self.modelsChanged.emit()
        except (ValueError, TypeError) as e:
            self.modelsError.emit(str(e))
        finally:
            reply.deleteLater()

    # ---- one streamed chat turn ----

    @Slot(str, str)
    def send(self, model, prompt):
        if not model or not prompt.strip():
            return
        self.cancel()          # one turn at a time
        self._model = model
        self._messages = [{"role": "system", "content": self._system_prompt()},
                          {"role": "user", "content": prompt}]
        self._think_tokens = 0
        self._rounds = 0
        self._set_busy(True)
        self.replyStarted.emit()
        self._post_chat()

    @staticmethod
    def _system_prompt():
        """A minimal system message that pins an unambiguous `now`. The model
        otherwise dates itself from its training; here it gets the real instant
        in UTC and local time, and is told to call get_current_time for any
        other zone rather than guessing a DST offset."""
        now = datetime.now(timezone.utc)
        local = now.astimezone()
        return ("The current time is %s (UTC), which is %s local time (%s). "
                "For the time or date in any other place, call get_current_time "
                "with an IANA timezone rather than converting it yourself."
                % (now.strftime("%Y-%m-%d %H:%M:%S"),
                   local.strftime("%Y-%m-%d %H:%M:%S"),
                   local.tzname() or local.strftime("%z")))

    def _time_now(self, tz_name, idx, remaining, calls):
        """Resolve the current time in an IANA zone through zoneinfo (real DST
        rules), fed back like any other tool result. Synchronous — a wall clock
        needs no subprocess and the instant is the same on either host."""
        now = datetime.now(timezone.utc)
        tz_name = (tz_name or "").strip()
        try:
            zone = ZoneInfo(tz_name) if tz_name else timezone.utc
            here = now.astimezone(zone)
            result = {"timezone": tz_name or "UTC",
                      "iso": here.isoformat(),
                      "date": here.strftime("%Y-%m-%d"),
                      "time": here.strftime("%H:%M:%S"),
                      "abbreviation": here.tzname() or "",
                      "utc_offset": here.strftime("%z"),
                      "utc": now.isoformat()}
        except (ZoneInfoNotFoundError, ValueError):
            result = {"error": "unknown timezone: " + tz_name}
        self._tool_results[idx] = {"role": "tool", "tool_name": "get_current_time",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _post_chat(self):
        """POST the current message list, streaming, offering every tool.
        Re-entered after each tool round."""
        payload = {
            "model": self._model,
            "messages": self._messages,
            "stream": True,
        }
        # ALL tools are offered on EVERY turn (his call — no per-tool toggle):
        # the file tools and web_search alike. A model with no tool support will
        # reject a request carrying tools — the tradeoff of always-on tools,
        # spelled out in apps/oracle/AGENTS.md; point oracle at a tool-capable
        # model.
        payload["tools"] = list(FILE_TOOLS) + [WEB_SEARCH_TOOL, TIME_TOOL]
        body = json.dumps(payload).encode("utf-8")
        req = QNetworkRequest(QUrl(OLLAMA + "/api/chat"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        self._buf = b""
        self._acc_content = ""
        self._tool_calls = []
        reply = self._nam.post(req, body)
        self._reply = reply
        reply.readyRead.connect(lambda: self._on_stream(reply))
        reply.finished.connect(lambda: self._on_finished(reply))

    @Slot()
    def cancel(self):
        # Drops the whole turn: a pending tool fetch checks `busy` and bails, so
        # a search still in flight never re-posts to a cancelled turn.
        self._set_busy(False)
        if self._reply is not None:
            r, self._reply = self._reply, None
            r.readyRead.disconnect()
            r.finished.disconnect()
            r.abort()
            r.deleteLater()

    def _on_stream(self, reply):
        if reply is not self._reply:
            return
        self._buf += bytes(reply.readAll().data())
        # NDJSON: one JSON object per line, and a read may split a line.
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("error"):
                self.replyError.emit(str(obj["error"]))
                continue
            msg = obj.get("message") or {}
            # A "thinking" model streams its reasoning in `thinking` with an
            # empty `content` until it starts answering; surface it (drawn
            # dimmed) so the window is not blank while it reasons.
            think = msg.get("thinking", "")
            if think:
                self.replyThinking.emit(think)
                # ollama streams one token per NDJSON frame, so a running frame
                # count is the reasoning's live token count — surfaced so the
                # collapsed heading can show progress while it thinks.
                self._think_tokens += 1
                self.replyThinkTokens.emit(self._think_tokens)
            piece = msg.get("content", "")
            if piece:
                self._acc_content += piece
                self.replyChunk.emit(piece)
            # Tool calls arrive assembled by ollama (not partial deltas); a turn
            # may carry several. Accumulate them for the round.
            calls = msg.get("tool_calls")
            if calls:
                self._tool_calls.extend(calls)

    def _on_finished(self, reply):
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        err = reply.error()
        err_str = reply.errorString()
        reply.deleteLater()
        if err == QNetworkReply.NetworkError.OperationCanceledError:
            return                      # cancel() already cleared busy
        if err != QNetworkReply.NetworkError.NoError:
            self._set_busy(False)
            self.replyError.emit(err_str)
            return
        # A tool round: run the calls, feed the results back, and let the model
        # continue. Past the cap, stop looping and take the answer as-is.
        if self._tool_calls and self._rounds < MAX_TOOL_ROUNDS:
            self._rounds += 1
            self._messages.append({"role": "assistant",
                                   "content": self._acc_content,
                                   "tool_calls": self._tool_calls})
            self._run_tool_calls(self._tool_calls)
            return
        self._set_busy(False)
        self.replyDone.emit()

    # ---- the web_search tool loop ----

    def _run_tool_calls(self, calls):
        """Dispatch each tool call; when the last result is in, re-post the
        chat with the tool messages appended. Calls run concurrently."""
        self._tool_results = [None] * len(calls)
        remaining = {"n": len(calls)}
        for i, call in enumerate(calls):
            fn = call.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if name == "web_search":
                self._tavily_search(str(args.get("query", "")).strip(),
                                    i, remaining, calls)
            elif name == "get_current_time":
                self._time_now(str(args.get("timezone", "")), i, remaining, calls)
            elif name in FILE_TOOL_NAMES:
                self._run_fs_tool(name, args, i, remaining, calls)
            else:
                self._tool_results[i] = {
                    "role": "tool", "tool_name": name,
                    "content": json.dumps({"error": "unknown tool: " + name})}
                self._tool_done(remaining, calls)

    def _tavily_search(self, query, idx, remaining, calls):
        key = tavily_key()
        if not key:
            self.webSearchError.emit(query, "no Tavily API key configured")
            self._tool_results[idx] = {
                "role": "tool", "tool_name": "web_search",
                "content": json.dumps({"error": "web search unavailable: no "
                                       "Tavily API key configured"})}
            self._tool_done(remaining, calls)
            return
        self.webSearchStarted.emit(query)
        body = json.dumps({
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": 5,
        }).encode("utf-8")
        req = QNetworkRequest(QUrl(TAVILY_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        reply = self._nam.post(req, body)
        reply.finished.connect(
            lambda: self._on_tavily(reply, query, idx, remaining, calls))

    def _on_tavily(self, reply, query, idx, remaining, calls):
        if not self._busy:            # turn was cancelled mid-search
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = reply.errorString()
                try:                  # Tavily returns a JSON error body
                    o = json.loads(data or b"{}")
                    if isinstance(o, dict) and (o.get("error") or o.get("detail")):
                        msg = str(o.get("error") or o.get("detail"))
                except ValueError:
                    pass
                self.webSearchError.emit(query, msg)
                self._tool_results[idx] = {
                    "role": "tool", "tool_name": "web_search",
                    "content": json.dumps({"error": "web search failed: " + msg})}
                return
            obj = json.loads(data or b"{}")
            answer = obj.get("answer") or ""
            results = obj.get("results") or []
            # Fed back to the model to summarize and cite.
            self._tool_results[idx] = {"role": "tool", "tool_name": "web_search",
                                       "content": json.dumps({
                "query": query, "answer": answer,
                "results": [{"title": r.get("title", ""), "url": r.get("url", ""),
                             "content": r.get("content", "")} for r in results]})}
            self.webSearchDone.emit(query,
                                    self._sources_markdown(answer, results),
                                    len(results))
        except (ValueError, TypeError) as e:
            self.webSearchError.emit(query, str(e))
            self._tool_results[idx] = {
                "role": "tool", "tool_name": "web_search",
                "content": json.dumps({"error": str(e)})}
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    def _tool_done(self, remaining, calls):
        remaining["n"] -= 1
        if remaining["n"] > 0 or not self._busy:
            return
        for tr in self._tool_results:
            if tr is not None:
                self._messages.append(tr)
        self._post_chat()

    @staticmethod
    def _sources_markdown(answer, results):
        """The sources disclosure body: Tavily's own answer, then a themed-link
        list of the hits (docs/DESIGN.md §2 — drawn through MarkdownText)."""
        lines = []
        if answer:
            lines.append(answer.strip())
            lines.append("")
        for r in results:
            title = (r.get("title") or r.get("url") or "untitled").strip()
            url = (r.get("url") or "").strip()
            lines.append("- [" + title + "](" + url + ")" if url
                         else "- " + title)
        return "\n".join(lines)

    # ---- the file tools (jailed, on top) ----

    @staticmethod
    def _fs_argv():
        """The command that runs one file op through tools/sandbox-fs.py against
        the sandbox on top. On `top` it is local; on `book` it goes over the same
        ssh master tools/ollama-tunnel.sh holds open (OLLAMA_SSH*), so the tools
        always operate on top's filesystem. The op JSON is written to stdin."""
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(FS_SCRIPT),
                     shlex.quote(SANDBOX_ROOT)]
            return argv
        return [sys.executable, FS_SCRIPT, SANDBOX_ROOT]

    def _run_fs_tool(self, name, args, idx, remaining, calls):
        """Run one file tool as an async QProcess, feeding the JSON result back
        into the tool loop exactly as the web search does. Concurrent with any
        other call in the round."""
        req = {k: v for k, v in args.items()} if isinstance(args, dict) else {}
        req["op"] = FILE_OP[name]
        self.fileToolStarted.emit(self._fs_heading(name, args))
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            result = self._fs_result(out, err, rc)
            self._tool_results[idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(self._fs_outcome(name, args, result),
                                   "error" not in result)
            self._tool_done(remaining, calls)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)  # surfaced through finished
        proc.start(self._fs_argv()[0], self._fs_argv()[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @staticmethod
    def _fs_result(out, err, rc):
        """The sandbox executor prints one JSON object; anything else (an ssh
        failure, a crash) becomes an error result the model still gets."""
        try:
            obj = json.loads(out.decode("utf-8", "replace") or "{}")
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        tail = (err.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        return {"error": "file tool failed: " + (tail or ("exit %d" % rc))}

    @staticmethod
    def _fs_heading(name, args):
        a = args if isinstance(args, dict) else {}
        p = str(a.get("path") or a.get("src") or ".")
        verb = {"list_dir": "listing", "read_file": "reading",
                "write_file": "writing", "edit_file": "editing",
                "move_path": "moving", "delete_path": "deleting",
                "make_dir": "creating"}.get(name, name)
        return verb + " " + p

    @staticmethod
    def _fs_outcome(name, args, result):
        a = args if isinstance(args, dict) else {}
        if "error" in result:
            p = str(a.get("path") or a.get("src") or "")
            return (name + ": " + str(result["error"]))[:200]
        if name == "list_dir":
            return "listed %s · %d entries" % (result.get("path", "."),
                                               result.get("count", 0))
        if name == "read_file":
            s, e, t = (result.get("start_line", 0), result.get("end_line", 0),
                       result.get("total_lines", 0))
            if result.get("binary"):
                return "read %s · binary, %d B" % (result.get("path", ""),
                                                   result.get("bytes", 0))
            return "read %s · lines %d–%d of %d" % (result.get("path", ""), s, e, t)
        if name == "write_file":
            return "%s %s · %d B" % ("created" if result.get("created") else "wrote",
                                     result.get("path", ""), result.get("bytes", 0))
        if name == "edit_file":
            n = result.get("replacements", 0)
            return "edited %s · %d replacement%s" % (result.get("path", ""), n,
                                                     "" if n == 1 else "s")
        if name == "move_path":
            return "moved %s → %s" % (result.get("src", ""), result.get("dst", ""))
        if name == "delete_path":
            return "deleted " + str(result.get("path", ""))
        if name == "make_dir":
            return "created " + str(result.get("path", "")) + "/"
        return name + " ok"


class Backend(QObject):
    """The ollama server's lifecycle, drawn beside the model selector — the same
    backend controls painter gives ComfyUI (`apps/painter`: the systemd start/stop
    and comfy's `/free`), for a daemon oracle otherwise only talks to.

    Two things it exposes: UNLOAD the loaded model (ollama's analog of comfy's
    `/free` — a zero `keep_alive` on `/api/generate`, freeing the VRAM without
    stopping the daemon) and START/STOP the server. Ollama here is the SYSTEM
    `ollama.service` (`sys/ai/ollama.nix`), not a `--user` unit like
    comfy-painter, so start/stop go through `systemctl`, and a non-zero exit is
    reported as itself rather than as success (docs/DESIGN.md §10 — never report
    a change that did not happen).

    WHERE the systemctl runs is host-branched. On `top` the unit is local, so it
    is `sudo -A systemctl` (the NOPASSWD rule in `sys/ai/ollama.nix` means no
    prompt; the askpass dialog is only a fallback). On `book` there is no local
    `ollama.service` at all — the daemon runs on `top`, reached over the same ssh
    that `tools/ollama-tunnel.sh` forwards 11434 through — so start/stop is
    `ssh top sudo -n systemctl …`, non-interactive because top askpass cannot
    prompt over an ssh with no tty. That is why the NOPASSWD rule exists and why
    it is scoped to exactly `systemctl {start,stop} ollama.service`.

    Everything the controls light from is OBSERVED, not claimed (§10.6): `up`/
    `down` and the loaded model are polled from the daemon's own `/api/ps`,
    refreshed on a 3s timer and after every action, so the buttons follow what
    the server IS doing, not what the last click intended."""

    UNIT = "ollama.service"

    statusChanged = Signal()      # serverUp and/or the loaded-model list changed
    busyChanged = Signal()        # a start/stop is in flight
    note = Signal(str)            # a one-line result of an action, drawn as status

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._up = False
        self._loaded = []
        self._busy = False
        self._procs = []          # live QProcesses, so none is GC'd mid-run
        self._poll = QTimer(self)
        self._poll.setInterval(3000)
        self._poll.timeout.connect(self.pollStatus)
        self._poll.start()

    @Property(bool, notify=statusChanged)
    def serverUp(self):
        return self._up

    @Property("QStringList", notify=statusChanged)
    def loadedModels(self):
        return self._loaded

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    # ---- observed status: /api/ps tells us both reachability and what is loaded ----

    @Slot()
    def pollStatus(self):
        req = QNetworkRequest(QUrl(OLLAMA + "/api/ps"))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_ps(reply))

    def _on_ps(self, reply):
        try:
            up = reply.error() == QNetworkReply.NetworkError.NoError
            loaded = []
            if up:
                try:
                    obj = json.loads(bytes(reply.readAll().data()) or b"{}")
                    loaded = sorted((m.get("name", "") for m in obj.get("models", [])
                                     if m.get("name")), key=str.lower)
                except (ValueError, TypeError):
                    up = False
            if up != self._up or loaded != self._loaded:
                self._up, self._loaded = up, loaded
                self.statusChanged.emit()
        finally:
            reply.deleteLater()

    # ---- unload the loaded model(s): comfy's /free, in ollama's dialect ----

    @Slot()
    def unloadModels(self):
        if not self._loaded:
            self.note.emit("no model is loaded")
            return
        pending = list(self._loaded)
        for name in pending:
            body = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
            req = QNetworkRequest(QUrl(OLLAMA + "/api/generate"))
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/json")
            reply = self._nam.post(req, body)
            reply.finished.connect(lambda r=reply, n=name: self._on_unload(r, n))
        self.note.emit("unloading " + ", ".join(pending))

    def _on_unload(self, reply, name):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.note.emit("unload failed: " + reply.errorString())
            else:
                self.note.emit("unloaded " + name)
        finally:
            reply.deleteLater()
            self.pollStatus()

    # ---- start / stop the SYSTEM unit, through the askpass dialog ----

    def _systemctl(self, verb):
        if ON_BOOK:
            # No local unit here; drive top's over the same ssh the tunnel uses.
            # `sudo -n` (no tty over ssh) relies on top's NOPASSWD rule for
            # exactly this command; ollama-tunnel.sh exports the resolved host
            # and the ssh control path so this reuses the tunnel's master.
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "sudo", "-n", "systemctl", verb, self.UNIT]
            return argv
        return ["sudo", "-A", "systemctl", verb, self.UNIT]

    @Slot()
    def startServer(self):
        self._run(self._systemctl("start"), "starting the ollama server",
                  "server started", "start failed")

    @Slot()
    def stopServer(self):
        self._run(self._systemctl("stop"), "stopping the ollama server",
                  "server stopped", "stop failed")

    def _run(self, argv, reason, ok_msg, fail_label):
        self._set_busy(True)
        self.note.emit(reason + "…")
        proc = QProcess(self)
        self._procs.append(proc)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SUDO_ASKPASS_REASON", reason)  # the dialog shows WHY (root AGENTS.md)
        proc.setProcessEnvironment(env)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = (bytes(proc.readAllStandardOutput()).decode(errors="replace")
                       + bytes(proc.readAllStandardError()).decode(errors="replace"))
                rc = proc.exitCode()
            except RuntimeError:
                return
            self._set_busy(False)
            # Report what happened, not what was asked (docs/DESIGN.md §10).
            if rc != 0:
                tail = out.strip().splitlines()
                self.note.emit(fail_label + ": " + (tail[-1] if tail else f"exit {rc}"))
            else:
                self.note.emit(ok_msg)
            self.pollStatus()
            proc.deleteLater()

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # reported through finished
        proc.start(argv[0], argv[1:])


class Sessions(QObject):
    """Named conversation sessions and their transcripts.

    Each session is one JSON transcript file in the canonical store
    (`SESSIONS_ROOT`), reached through `tools/sessions-store.py` — the same
    QProcess idiom the file tools use, so a save never blocks the UI and
    list/load results arrive on signals. oracle GENERATES the session id (a
    stable `sess-<ms>-<rand>` token, in QML), so the store only ever validates
    and writes; there is no id to mint and thus no round-trip before the first
    save. The list is `[{"id","title","updated","turns"}]`, newest first, for the
    session picker; `loaded` hands a whole transcript back as JSON for QML to
    rebuild the log from."""

    listChanged = Signal()
    loaded = Signal(str, str, str)     # id, title, turns as a JSON string
    saved = Signal(str, str)           # id, title — after a persist landed
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._list = []
        self._procs = []               # live QProcesses, so none is GC'd mid-run

    @Property("QVariantList", notify=listChanged)
    def sessions(self):
        return self._list

    @staticmethod
    def _store_argv():
        """The command that runs one store op through tools/sessions-store.py
        against the canonical store on top. On `top` it is local; on `book` it
        goes over the same ssh master tools/ollama-tunnel.sh holds open
        (OLLAMA_SSH*), so the sessions/transcripts live in one canonical place
        keyed to top and both machines share them. The op JSON is written to
        stdin."""
        if ON_BOOK:
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
        proc.errorOccurred.connect(lambda *_: None)   # surfaced through finished
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
            return                      # nothing to persist yet
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


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("oracle")
    app.setDesktopFileName("oracle")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    ollama = Ollama()
    backend = Backend()
    sessions = Sessions()

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Ollama", ollama)
    ctx.setContextProperty("Backend", backend)
    ctx.setContextProperty("Sessions", sessions)
    ctx.setContextProperty("ollamaHost", OLLAMA)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    ollama.refreshModels()
    backend.pollStatus()
    sessions.refresh()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
