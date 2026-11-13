"""Codex over ``codex app-server`` JSON-RPC (Qt-free).

One private app-server child per Coder window carries every Codex session in
it (docs/agents/coder-plan.md section 4.3). Never the CLI's managed background
daemon. Lines are JSON-RPC 2.0 objects; the server omits "jsonrpc" in its own
replies. Method and field names come from
``codex app-server generate-json-schema`` for codex-cli 0.166.0; unknown
notifications are ignored, unknown server requests answered with an error so
the server never waits on us.

``CodexServer`` owns the request ids and routes thread-scoped notifications to
the ``Codex`` session whose ``native_id`` matches ``params.threadId``.
"""

import itertools
import json

from proto import Backend, new_item, short

# (label, approvalPolicy, sandbox mode for thread/start, sandboxPolicy for turns)
MODES = [
    ("read-only", "on-request", "read-only", {"type": "readOnly", "networkAccess": False}),
    ("ask", "untrusted", "workspace-write", None),
    ("auto", "on-request", "workspace-write", None),
    ("full access", "never", "danger-full-access", {"type": "dangerFullAccess"}),
]
MODE_IDS = [m[0] for m in MODES]
EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]


def _mode(label):
    for m in MODES:
        if m[0] == label:
            return m
    return MODES[2]


def _workspace_policy(cwd):
    return {"type": "workspaceWrite", "writableRoots": [cwd] if cwd else [],
            "networkAccess": False, "excludeSlashTmp": False,
            "excludeTmpdirEnvVar": False}


class CodexServer:
    """Request/response bookkeeping and routing for one app-server process."""

    def __init__(self, write, on_global=None):
        self.write = write
        self.on_global = on_global or (lambda method, params: None)
        self._ids = itertools.count(1)
        self._wait = {}           # id -> callback(result, error)
        self.sessions = {}        # threadId -> Codex
        self.ready = False
        self._queue = []          # requests sent before initialize returned
        self.models = []

    def request(self, method, params, cb=None):
        rid = next(self._ids)
        self._wait[rid] = cb
        line = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if self.ready or method == "initialize":
            self.write(line)
        else:
            self._queue.append(line)
        return rid

    def respond(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result if result is not None else {}
        self.write(json.dumps(msg))

    def start(self, version="0"):
        def done(result, error):
            self.ready = True
            self.write(json.dumps({"jsonrpc": "2.0", "method": "initialized"}))
            for line in self._queue:
                self.write(line)
            self._queue = []
            self.request("model/list", {}, self._models)
        self.request("initialize", {"clientInfo": {"name": "coder", "title": "Coder",
                                                   "version": version},
                                    "capabilities": {"experimentalApi": False}}, done)

    def _models(self, result, error):
        if error or not isinstance(result, dict):
            return
        self.models = [{"id": m.get("id") or m.get("model", ""),
                        "label": m.get("displayName") or m.get("id", ""),
                        "default": bool(m.get("isDefault")),
                        "effort": m.get("defaultReasoningEffort", ""),
                        "efforts": [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts") or []]}
                       for m in result.get("data") or [] if not m.get("hidden")]
        self.on_global("models", {"models": self.models})
        for s in list(self.sessions.values()):
            s.sink("caps", {"models": self.models, "commands": []})

    def attach(self, session):
        if session.native_id:
            self.sessions[session.native_id] = session

    def detach(self, session):
        if self.sessions.get(session.native_id) is session:
            del self.sessions[session.native_id]

    def on_line(self, line):
        try:
            msg = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(msg, dict):
            return
        if "method" in msg and "id" in msg:
            self._server_request(msg)
        elif "method" in msg:
            params = msg.get("params") or {}
            sess = self.sessions.get(params.get("threadId", "")) if isinstance(params, dict) else None
            if sess is None and isinstance(params, dict) and isinstance(params.get("thread"), dict):
                sess = self.sessions.get(params["thread"].get("id", ""))
            if sess is not None:
                sess.notify(msg["method"], params)
            else:
                self.on_global(msg["method"], params)
        elif "id" in msg:
            cb = self._wait.pop(msg.get("id"), None)
            if cb is not None:
                cb(msg.get("result"), msg.get("error"))

    def _server_request(self, msg):
        params = msg.get("params") or {}
        sess = self.sessions.get(params.get("threadId", "")) if isinstance(params, dict) else None
        if sess is not None and sess.server_request(msg["id"], msg["method"], params):
            return
        self.respond(msg["id"], error={"code": -32601,
                                       "message": "coder does not handle %s" % msg["method"]})

    def on_exit(self, code, stderr=""):
        for s in list(self.sessions.values()):
            s.on_exit(code, stderr)
        self.ready = False


class Codex(Backend):
    name = "codex"

    def __init__(self, sink, server, cwd="", model="", mode="auto", effort="",
                 resume="", fork=False):
        super().__init__(sink, server.write)
        self.server = server
        self.cwd = cwd
        self.model = model
        self.mode = mode or "auto"
        self.effort = effort
        self._resume = resume
        self._fork = fork
        self._turn = ""
        self._approvals = {}      # json-rpc id -> (item id, method)
        self._items = {}          # item id -> last item sent (for approvals)
        self._outbox = []         # sends made before the thread exists
        self._interrupting = False
        self.turns = 0

    # -- lifecycle --------------------------------------------------------
    def start(self):
        self.set_state("starting")
        m = _mode(self.mode)
        common = {"cwd": self.cwd or None, "model": self.model or None,
                  "approvalPolicy": m[1], "sandbox": m[2]}
        if self._resume and self._fork:
            self.server.request("thread/fork", dict(common, threadId=self._resume), self._started)
        elif self._resume:
            self.server.request("thread/resume", dict(common, threadId=self._resume), self._started)
        else:
            self.server.request("thread/start", common, self._started)

    def _started(self, result, error):
        if error or not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            self.sink("error", {"message": "codex could not open the thread: %s" % (
                (error or {}).get("message") if isinstance(error, dict) else error)})
            self.set_state("failed")
            return
        th = result["thread"]
        self.native_id = th.get("id", "")
        self.server.attach(self)
        self.model = result.get("model") or self.model
        if result.get("reasoningEffort") and not self.effort:
            self.effort = result["reasoningEffort"]
        self.sink("session", {"native_id": self.native_id, "model": self.model,
                              "cwd": result.get("cwd") or self.cwd, "mode": self.mode,
                              "effort": self.effort})
        if th.get("name"):
            self.sink("title", {"title": th["name"]})
        if self.server.models:
            self.sink("caps", {"models": self.server.models, "commands": []})
        self.set_state("idle")
        for args in self._outbox:
            self.send(*args)
        self._outbox = []

    # -- outgoing ---------------------------------------------------------
    def send(self, text, images=()):
        if not self.native_id:
            self._outbox.append((text, images))
            return
        inp = []
        if text:
            inp.append({"type": "text", "text": text, "text_elements": []})
        for img in images:
            if img.get("path"):
                inp.append({"type": "localImage", "path": img["path"], "detail": None})
        m = _mode(self.mode)
        params = {"threadId": self.native_id, "input": inp, "approvalPolicy": m[1],
                  "sandboxPolicy": m[3] if m[3] is not None else _workspace_policy(self.cwd)}
        if self.model:
            params["model"] = self.model
        if self.effort:
            params["effort"] = self.effort
        self.set_state("running")
        self.server.request("turn/start", params, self._turn_started)

    def _turn_started(self, result, error):
        if error:
            self.sink("error", {"message": "codex refused the turn: %s" % (
                error.get("message") if isinstance(error, dict) else error)})
            self.set_state("idle")
            return
        turn = (result or {}).get("turn") or {}
        self._turn = turn.get("id", self._turn)

    def interrupt(self):
        if self._turn and self.state in ("running", "waiting"):
            self._interrupting = True
            self.server.request("turn/interrupt", {"threadId": self.native_id, "turnId": self._turn})

    def set_mode(self, mode):
        self.mode = mode if mode in MODE_IDS else "auto"
        self.sink("session", {"mode": self.mode})

    def set_model(self, model):
        self.model = model
        self.sink("session", {"model": model})

    def set_effort(self, effort):
        self.effort = effort
        self.sink("session", {"effort": effort})

    def rename(self, name):
        if self.native_id:
            self.server.request("thread/name/set", {"threadId": self.native_id, "name": name})

    def answer(self, request_id, decision, note=""):
        entry = self._approvals.pop(request_id, None)
        if entry is None:
            return
        iid, method = entry
        # State first: the reply can make the server finish the turn at once.
        item = dict(self._items.get(iid, new_item(iid, "approval")))
        item["status"] = "allowed" if decision in ("allow", "always") else "denied"
        self.sink("item", item)
        if not self._approvals and self.state == "waiting":
            self.set_state("running")
        if method.endswith("requestApproval") and "permissions" not in method:
            value = {"allow": "accept", "always": "acceptForSession",
                     "deny": "decline", "cancel": "cancel"}.get(decision, "decline")
            self.server.respond(request_id, {"decision": value})
        elif method in ("applyPatchApproval", "execCommandApproval"):
            value = {"allow": "approved", "always": "approved_for_session"}.get(decision, "denied")
            self.server.respond(request_id, {"decision": value})
        else:
            self.server.respond(request_id, error={"code": -32000, "message": note or "declined in coder"})

    # -- incoming ---------------------------------------------------------
    def server_request(self, rid, method, params):
        if method in ("item/commandExecution/requestApproval", "execCommandApproval"):
            cmd = params.get("command") or ""
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            iid = "ap:%s" % rid
            item = new_item(iid, "approval", title="run %s" % short(cmd, 140),
                            text=params.get("reason") or "", detail=str(params.get("cwd") or ""),
                            status="waiting", meta={"request_id": rid, "tool": "command",
                                                    "can_always": True, "item": params.get("itemId", "")})
        elif method in ("item/fileChange/requestApproval", "applyPatchApproval"):
            iid = "ap:%s" % rid
            target = self._items.get(params.get("itemId", ""), {})
            item = new_item(iid, "approval", title="apply %s" % (target.get("title") or "file changes"),
                            text=params.get("reason") or "", detail=target.get("detail", ""),
                            status="waiting", meta={"request_id": rid, "tool": "patch",
                                                    "can_always": True, "item": params.get("itemId", "")})
        else:
            return False
        self._approvals[rid] = (iid, method)
        self._items[iid] = item
        self.sink("item", item)
        self.set_state("waiting")
        return True

    def notify(self, method, p):
        if method == "turn/started":
            self._turn = (p.get("turn") or {}).get("id", self._turn)
            self.turns += 1
            self.set_state("running")
        elif method == "turn/completed":
            turn = p.get("turn") or {}
            status = turn.get("status", "completed")
            err = (turn.get("error") or {}).get("message", "") if isinstance(turn.get("error"), dict) else ""
            if status == "inProgress":
                status = "completed"
            self.sink("turn", {"status": status, "error": err})
            self._interrupting = False
            self.set_state("idle")
        elif method in ("item/started", "item/completed"):
            item = self._item(p.get("item") or {}, done=method == "item/completed")
            if item is not None:
                self._items[item["id"]] = item
                self.sink("item", item)
        elif method == "item/agentMessage/delta":
            self.sink("delta", {"id": p.get("itemId", ""), "field": "text", "text": p.get("delta", "")})
        elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            self.sink("delta", {"id": p.get("itemId", ""), "field": "text", "text": p.get("delta", "")})
        elif method == "item/reasoning/summaryPartAdded":
            self.sink("delta", {"id": p.get("itemId", ""), "field": "text", "text": "\n\n"})
        elif method == "item/commandExecution/outputDelta":
            self.sink("delta", {"id": p.get("itemId", ""), "field": "text", "text": p.get("delta", "")})
        elif method == "item/plan/delta":
            self.sink("delta", {"id": p.get("itemId", ""), "field": "text", "text": p.get("delta", "")})
        elif method == "turn/plan/updated":
            steps = p.get("plan") or []
            mark = {"completed": "[x]", "inProgress": "[>]"}
            self.sink("item", new_item("todo", "plan", title="tasks", text="\n".join(
                "- %s %s" % (mark.get(s.get("status"), "[ ]"), s.get("step", "")) for s in steps),
                detail=p.get("explanation") or ""))
        elif method == "turn/diff/updated":
            self.sink("diff", {"turn": p.get("turnId", ""), "diff": p.get("diff", "")})
        elif method == "thread/tokenUsage/updated":
            tu = p.get("tokenUsage") or {}
            last = tu.get("last") or {}
            self.sink("usage", {"used": int(last.get("inputTokens") or 0) + int(last.get("outputTokens") or 0),
                                "window": int(tu.get("modelContextWindow") or 0)})
        elif method == "thread/name/updated":
            if p.get("threadName"):
                self.sink("title", {"title": p["threadName"]})
        elif method == "error":
            err = p.get("error") or {}
            self.sink("item", new_item("err:%s" % p.get("turnId", ""), "error",
                                       text=err.get("message", "error"),
                                       detail=str(err.get("codexErrorInfo") or "")))
        elif method == "thread/status/changed":
            st = (p.get("status") or {}).get("type")
            if st == "systemError":
                self.set_state("failed")
        elif method == "thread/compacted":
            self.sink("item", new_item("compact%d" % self.turns, "notice", text="context compacted"))
        elif method in ("warning", "configWarning", "deprecationNotice"):
            msg = p.get("message") or p.get("summary") or ""
            if msg:
                self.sink("item", new_item("warn:%s" % short(msg, 40), "notice", text=str(msg)))

    def _item(self, it, done):
        t = it.get("type")
        iid = it.get("id", "")
        status = "completed" if done else "running"
        if t == "userMessage":
            text = "\n".join(c.get("text", "") for c in it.get("content") or [] if c.get("type") == "text")
            imgs = [c.get("path", "") for c in it.get("content") or [] if c.get("type") == "localImage"]
            return new_item(iid, "user", text=text, status="completed", meta={"images": imgs})
        if t == "agentMessage":
            return new_item(iid, "assistant", text=it.get("text", ""), status=status)
        if t == "reasoning":
            text = "\n\n".join(it.get("summary") or []) or "\n\n".join(it.get("content") or [])
            return new_item(iid, "reasoning", text=text, status=status)
        if t == "commandExecution":
            st = it.get("status") or status
            st = {"inProgress": "running"}.get(st, st)
            exit_code = it.get("exitCode")
            return new_item(iid, "command", title=str(it.get("command", "")),
                            text=str(it.get("aggregatedOutput") or "")[-20000:],
                            detail="" if exit_code is None else "exit %s" % exit_code,
                            status=st, meta={"cwd": str(it.get("cwd") or "")})
        if t == "fileChange":
            changes = it.get("changes") or []
            st = {"inProgress": "running"}.get(it.get("status"), it.get("status") or status)
            paths = [c.get("path", "") for c in changes]
            return new_item(iid, "file_change", title=", ".join(short(p, 60) for p in paths[:4])
                            + (" +%d" % (len(paths) - 4) if len(paths) > 4 else ""),
                            text="\n".join(c.get("diff", "") for c in changes)[-40000:],
                            status=st, meta={"paths": paths})
        if t == "plan":
            return new_item(iid, "plan", text=it.get("text", ""), status=status)
        if t in ("mcpToolCall", "dynamicToolCall"):
            name = "%s.%s" % (it.get("server"), it.get("tool")) if t == "mcpToolCall" else it.get("tool", "")
            res = it.get("result")
            out = json.dumps(res, ensure_ascii=False)[:8000] if res is not None else ""
            return new_item(iid, "tool", title=name, detail=json.dumps(it.get("arguments"), ensure_ascii=False)[:4000],
                            text=out, status={"inProgress": "running"}.get(it.get("status"), it.get("status") or status))
        if t == "webSearch":
            return new_item(iid, "tool", title="search %s" % short(it.get("query", ""), 100), status=status)
        if t == "imageView":
            return new_item(iid, "image", title=str(it.get("path", "")), meta={"path": str(it.get("path", ""))})
        if t == "imageGeneration":
            return new_item(iid, "image", title=short(it.get("revisedPrompt") or "image", 100),
                            status=it.get("status") or status, meta={"path": str(it.get("savedPath") or "")})
        if t == "contextCompaction":
            return new_item(iid, "notice", text="context compacted")
        if t in ("collabAgentToolCall", "subAgentActivity"):
            return new_item(iid, "tool", title="agent %s" % short(it.get("prompt") or it.get("agentPath") or "", 100),
                            status=status)
        return None


def thread_items(thread):
    """A stored thread (thread/read with includeTurns) as normalized items."""
    tmp = Codex(lambda *_: None, CodexServer(lambda _l: None))
    out = []
    for turn in thread.get("turns") or []:
        for it in turn.get("items") or []:
            item = tmp._item(it, done=True)
            if item is not None:
                out.append(item)
    return out
