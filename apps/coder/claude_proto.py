"""Claude Code over its stream-json control protocol (Qt-free).

One ``claude -p`` process per live session. Wire format, as recorded from
claude 2.1.318 (fixtures/claude-*.jsonl):

  host -> cli   {"type":"control_request","request_id":ID,"request":{"subtype":S,...}}
                S = initialize | interrupt | set_permission_mode | set_model
  host -> cli   {"type":"user","session_id":"","message":{"role":"user","content":...},
                 "parent_tool_use_id":null}
  cli -> host   {"type":"control_response","response":{"subtype":"success",
                 "request_id":ID,"response":{...}}}
  cli -> host   {"type":"control_request","request_id":ID,
                 "request":{"subtype":"can_use_tool","tool_name",...}}
                answered with a control_response whose response is
                {"behavior":"allow","updatedInput":...[,"updatedPermissions":[...]]}
                or {"behavior":"deny","message":...}
  cli -> host   system/init, system/status, stream_event (partial messages),
                assistant, user (tool results), result, rate_limit_event

Permission prompts reach the host only with ``--permission-prompt-tool stdio``;
without it ``--permission-prompts host`` auto-denies anything that would ask.
"""

import itertools
import json

from proto import Backend, new_item, short

MODES = [
    # (cli value, label)
    ("default", "ask"),
    ("acceptEdits", "accept edits"),
    ("plan", "plan"),
    ("auto", "auto"),
    ("dontAsk", "don't ask"),
    ("bypassPermissions", "bypass"),
]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def argv(binary="claude", model="", mode="default", effort="", resume="",
         session_id="", fork=False):
    out = [binary, "-p", "--input-format", "stream-json",
           "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--permission-prompt-tool", "stdio",
           "--permission-mode", mode or "default"]
    if model:
        out += ["--model", model]
    if effort:
        out += ["--effort", effort]
    if resume:
        out += ["--resume", resume]
        if fork:
            out.append("--fork-session")
    elif session_id:
        out += ["--session-id", session_id]
    return out


def _text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "image":
                parts.append("[image]")
            elif c.get("type") == "tool_reference":
                parts.append("[%s]" % c.get("tool_name", "tool"))
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(p for p in parts if p)


def tool_title(name, inp):
    """A one-line label for a tool call, from its input."""
    inp = inp if isinstance(inp, dict) else {}
    for key in ("command", "file_path", "path", "pattern", "url", "query",
                "description", "prompt"):
        v = inp.get(key)
        if v:
            return "%s %s" % (name, short(v, 120))
    return name


class Claude(Backend):
    name = "claude"

    def __init__(self, sink, write):
        super().__init__(sink, write)
        self._ids = itertools.count(1)
        self._pending = {}        # our request_id -> subtype
        self._blocks = {}         # (msg_id, index) -> item id
        self._msg = ""            # current streamed api message id
        self._open = {}           # msg_id -> [item ids in block order]
        self._final = set()       # item ids already finalised from 'assistant'
        self._tools = {}          # tool_use_id -> item id
        self._approvals = {}      # request_id -> item id
        self._approval_meta = {}  # request_id -> input/suggestions/answers
        self._approval_items = {} # item id -> last approval item sent
        self._json = {}           # item id -> partial input json
        self._interrupting = False
        self._denied = set()      # tool item ids the CLI refused itself
        self._window = 0
        self._models = []
        self.turn = 0

    # -- outgoing ---------------------------------------------------------
    def _send(self, obj):
        self.write(json.dumps(obj))

    def _control(self, subtype, **kw):
        rid = "coder_%d" % next(self._ids)
        self._pending[rid] = subtype
        req = {"subtype": subtype}
        req.update(kw)
        self._send({"type": "control_request", "request_id": rid, "request": req})
        return rid

    def start(self):
        self.set_state("starting")
        self._control("initialize", hooks=None)

    def send(self, text, images=()):
        content = text
        if images:
            content = [{"type": "text", "text": text}] if text else []
            for img in images:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": img["mime"], "data": img["data"]}})
        self.turn += 1
        self.sink("item", new_item("u%d" % self.turn, "user", text=text,
                                   meta={"images": [i.get("path", "") for i in images]}))
        self.set_state("running")
        self._send({"type": "user", "session_id": "",
                    "message": {"role": "user", "content": content},
                    "parent_tool_use_id": None})

    def interrupt(self):
        if self.state in ("running", "waiting"):
            self._interrupting = True
            self._control("interrupt")

    def set_mode(self, mode):
        self._control("set_permission_mode", mode=mode)

    def set_model(self, model):
        self._control("set_model", model=model)

    def answer(self, request_id, decision, note=""):
        item_id = self._approvals.pop(request_id, None)
        meta = self._approval_meta.pop(request_id, {})
        allow = decision in ("allow", "always")
        if allow:
            resp = {"behavior": "allow", "updatedInput": meta.get("input", {})}
            if decision == "always" and meta.get("suggestions"):
                resp["updatedPermissions"] = meta["suggestions"]
            if meta.get("answers"):
                resp["updatedInput"] = dict(resp["updatedInput"], answers=meta["answers"])
        else:
            resp = {"behavior": "deny", "message": note or "denied in coder"}
            tool_item = self._tools.get(meta.get("tool_use_id", ""))
            if tool_item:
                self._denied.add(tool_item)
        # State first: the reply can make the CLI finish the turn at once.
        if item_id:
            self.sink("item", dict(self._approval_items.pop(item_id, new_item(item_id, "approval")),
                                   status="allowed" if allow else "denied"))
        if not self._approvals and self.state == "waiting":
            self.set_state("running")
        self._send({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id, "response": resp}})

    def set_answers(self, request_id, answers):
        """AskUserQuestion: the chosen labels, keyed by question text."""
        meta = self._approval_meta.get(request_id)
        if meta is not None:
            meta["answers"] = dict(answers)

    # -- incoming ---------------------------------------------------------
    def on_line(self, line):
        try:
            msg = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(msg, dict):
            return
        t = msg.get("type")
        fn = getattr(self, "_on_" + str(t), None)
        if fn is not None:
            fn(msg)

    def _on_control_response(self, msg):
        r = msg.get("response") or {}
        rid = r.get("request_id", "")
        what = self._pending.pop(rid, "")
        body = r.get("response") or {}
        if r.get("subtype") == "error":
            self.sink("error", {"message": "claude refused %s: %s" % (what, r.get("error", ""))})
            return
        if what == "initialize":
            self._models = body.get("models") or []
            self.sink("caps", {
                "models": [{"id": m.get("value", ""), "label": m.get("displayName") or m.get("value", ""),
                            "efforts": m.get("supportedEffortLevels") or []}
                           for m in self._models],
                "commands": [{"name": c.get("name", ""), "description": c.get("description", "")}
                             for c in body.get("commands") or []],
                "mode": body.get("current_permission_mode", ""),
            })
            if self.state == "starting":
                self.set_state("idle")
        elif what == "set_permission_mode":
            self.sink("session", {"mode": body.get("mode", "")})
        elif what == "set_model":
            self.sink("session", {"model": body.get("model", "")})
        elif what == "interrupt":
            pass

    def _on_system(self, msg):
        sub = msg.get("subtype")
        if sub == "init":
            self.native_id = msg.get("session_id", "") or self.native_id
            self.sink("session", {"native_id": self.native_id, "model": msg.get("model", ""),
                                  "cwd": msg.get("cwd", ""), "mode": msg.get("permissionMode", "")})
        elif sub == "status":
            if msg.get("permissionMode"):
                self.sink("session", {"mode": msg["permissionMode"]})
            if msg.get("status") == "requesting" and self.state != "waiting":
                self.set_state("running")
            if msg.get("status") == "compacting":
                self.sink("item", new_item("compact%d" % self.turn, "notice", text="compacting context"))
        elif sub == "permission_denied":
            iid = self._tools.get(msg.get("tool_use_id", ""))
            if iid:
                self._denied.add(iid)
                self.sink("item_patch", {"id": iid, "status": "denied",
                                         "detail": msg.get("message", "")})
        elif sub == "compact_boundary":
            self.sink("item", new_item("compacted%d" % self.turn, "notice", text="context compacted"))

    def _on_stream_event(self, msg):
        ev = msg.get("event") or {}
        et = ev.get("type")
        if msg.get("parent_tool_use_id"):
            return      # a subagent's stream; its final messages arrive whole
        if et == "message_start":
            self._msg = (ev.get("message") or {}).get("id", "")
            self._open.setdefault(self._msg, [])
            self._usage((ev.get("message") or {}).get("usage"))
        elif et == "content_block_start":
            block = ev.get("content_block") or {}
            idx = ev.get("index", 0)
            bt = block.get("type")
            iid = "%s:%s" % (self._msg, idx)
            self._blocks[(self._msg, idx)] = iid
            self._open.setdefault(self._msg, []).append((bt, iid))
            if bt == "text":
                self.sink("item", new_item(iid, "assistant", status="running"))
            elif bt == "thinking":
                self.sink("item", new_item(iid, "reasoning", status="running"))
            elif bt in ("tool_use", "server_tool_use"):
                name = block.get("name", "tool")
                self._tools[block.get("id", "")] = iid
                self.sink("item", new_item(iid, "tool", title=name, status="running",
                                           meta={"name": name, "tool_use_id": block.get("id", "")}))
        elif et == "content_block_delta":
            iid = self._blocks.get((self._msg, ev.get("index", 0)))
            d = ev.get("delta") or {}
            if not iid:
                return
            if d.get("type") == "text_delta":
                self.sink("delta", {"id": iid, "field": "text", "text": d.get("text", "")})
            elif d.get("type") == "thinking_delta" and d.get("thinking"):
                self.sink("delta", {"id": iid, "field": "text", "text": d.get("thinking", "")})
            elif d.get("type") == "input_json_delta":
                self._json[iid] = self._json.get(iid, "") + d.get("partial_json", "")
        elif et == "message_delta":
            self._usage(ev.get("usage"))

    def _usage(self, u):
        if not isinstance(u, dict):
            return
        used = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                 "cache_creation_input_tokens"))
        if used:
            self.sink("usage", {"used": used, "window": self._window})

    def _on_assistant(self, msg):
        if msg.get("parent_tool_use_id"):
            return
        m = msg.get("message") or {}
        mid = m.get("id", "")
        opened = self._open.get(mid, [])
        for block in m.get("content") or []:
            bt = block.get("type")
            iid = None
            for t, cand in opened:
                if t == bt and cand not in self._final:
                    iid = cand
                    break
            if iid is None:
                iid = "%s:x%d" % (mid, len(self._final))
            self._final.add(iid)
            if bt == "text":
                self.sink("item", new_item(iid, "assistant", text=block.get("text", ""),
                                           status="completed"))
            elif bt == "thinking":
                txt = block.get("thinking", "")
                self.sink("item", new_item(iid, "reasoning", text=txt, status="completed",
                                           meta={"redacted": not txt}))
            elif bt in ("tool_use", "server_tool_use"):
                name = block.get("name", "tool")
                inp = block.get("input") or {}
                self._tools[block.get("id", "")] = iid
                kind = "plan" if name == "ExitPlanMode" else "tool"
                self.sink("item", new_item(
                    iid, kind, title=tool_title(name, inp),
                    text=inp.get("plan", "") if kind == "plan" else "",
                    detail=json.dumps(inp, indent=1, ensure_ascii=False)[:4000],
                    status="running", meta={"name": name, "input": inp,
                                            "tool_use_id": block.get("id", "")}))
                if name == "TodoWrite":
                    todos = inp.get("todos") or []
                    self.sink("item", new_item("todo", "plan", title="tasks", text="\n".join(
                        "- %s %s" % ({"completed": "[x]", "in_progress": "[>]"}.get(t.get("status"), "[ ]"),
                                   t.get("content", "")) for t in todos)))

    def _on_user(self, msg):
        if msg.get("parent_tool_use_id"):
            return
        m = msg.get("message") or {}
        content = m.get("content")
        if isinstance(content, str):
            return      # our own prompt echoed (--replay-user-messages)
        for c in content or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_result":
                iid = self._tools.get(c.get("tool_use_id", ""))
                if not iid:
                    continue
                out = _text_of(c.get("content"))
                patch = {"id": iid, "text": out[-20000:],
                         "status": "denied" if iid in self._denied else
                         "failed" if c.get("is_error") else "completed"}
                tur = msg.get("tool_use_result")
                if isinstance(tur, dict) and tur.get("structuredPatch"):
                    patch["meta_patch"] = {"patch": tur.get("structuredPatch"),
                                           "path": tur.get("filePath", "")}
                self.sink("item_patch", patch)
            elif c.get("type") == "text" and "[Request interrupted" in c.get("text", ""):
                self.sink("item", new_item("int%d" % self.turn, "notice", text="interrupted"))

    def _on_control_request(self, msg):
        req = msg.get("request") or {}
        rid = msg.get("request_id", "")
        if req.get("subtype") != "can_use_tool":
            # Unknown host requests must still be answered or the CLI waits.
            self._send({"type": "control_response", "response": {
                "subtype": "error", "request_id": rid,
                "error": "coder does not handle %s" % req.get("subtype")}})
            return
        name = req.get("tool_name", "tool")
        inp = req.get("input") or {}
        iid = "ap:" + rid
        suggestions = req.get("permission_suggestions") or []
        meta = {"request_id": rid, "tool": name, "input": inp,
                "tool_use_id": req.get("tool_use_id", ""),
                "suggestions": [s for s in suggestions if s.get("type") == "addRules"],
                "can_always": any(s.get("type") == "addRules" for s in suggestions),
                "questions": inp.get("questions") if name == "AskUserQuestion" else None}
        self._approval_meta[rid] = meta
        item = new_item(iid, "approval", title=tool_title(req.get("display_name") or name, inp),
                        text=inp.get("plan", "") if name == "ExitPlanMode" else
                        (req.get("description") or ""),
                        detail=json.dumps(inp, indent=1, ensure_ascii=False)[:4000],
                        status="waiting", meta={k: v for k, v in meta.items() if k != "suggestions"})
        self._approvals[rid] = iid
        self._approval_items[iid] = item
        self.sink("item", item)
        self.set_state("waiting")

    def _on_result(self, msg):
        status = "completed"
        if msg.get("is_error") or msg.get("subtype") != "success":
            status = "interrupted" if self._interrupting else "failed"
        self._interrupting = False
        mu = msg.get("modelUsage") or {}
        for v in mu.values():
            if isinstance(v, dict) and v.get("contextWindow"):
                self._window = int(v["contextWindow"])
        self.sink("usage", {"window": self._window, "cost": msg.get("total_cost_usd")})
        err = ""
        if status == "failed":
            err = str(msg.get("result") or msg.get("api_error_status") or msg.get("subtype") or "")
        self.sink("turn", {"status": status, "error": err})
        self.set_state("idle")

    def _on_rate_limit_event(self, msg):
        info = msg.get("rate_limit_info") or {}
        wins = info.get("unifiedWindows") or {}
        for key, label in (("five_hour", "5h"),):
            w = wins.get(key)
            if isinstance(w, dict) and w.get("utilization") is not None:
                self.sink("limits", {"label": label, "used_percent": round(float(w["utilization"]) * 100),
                                     "resets_at": w.get("resetsAt")})
