"""Replays recorded CLI exchanges in place of a real process (Qt-free).

A fixture is the JSONL ``tools/record-fixture.py`` writes: one
``{"t", "dir": "in"|"out"|"exit", "msg"}`` per line, ``in`` meaning CLI to
host. The replayer answers the host's requests with the recorded replies
(ids remapped), plays each recorded turn when the host starts one, and stops
at every recorded permission request until the host answers it. It never
runs a CLI and never reaches the network.

``kind`` is "claude" or "codex"; ``emit(line)`` receives each CLI line.
"""

import json


def load(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _is_turn(kind, msg):
    if kind == "claude":
        return msg.get("type") == "user"
    return msg.get("method") == "turn/start"


def _req_key(kind, msg):
    """(key, id) for a host request that expects a reply, else None."""
    if kind == "claude":
        if msg.get("type") == "control_request":
            return (msg.get("request") or {}).get("subtype"), msg.get("request_id")
        return None
    if "method" in msg and "id" in msg:
        return msg["method"], msg["id"]
    return None


def _reply_id(kind, msg):
    if kind == "claude":
        if msg.get("type") == "control_response":
            return (msg.get("response") or {}).get("request_id")
        return None
    if "id" in msg and "method" not in msg:
        return msg["id"]
    return None


def _server_request_id(kind, msg):
    if kind == "claude":
        if msg.get("type") == "control_request":
            return msg.get("request_id")
        return None
    if "method" in msg and "id" in msg:
        return msg["id"]
    return None


class Replayer:
    def __init__(self, records, kind, emit, on_exit=None):
        self.kind = kind
        self.emit = emit
        self.on_exit = on_exit or (lambda code: None)
        self.replies = {}        # request key -> [reply msg, ...]
        self.turns = []          # [[msg, ...], ...] CLI lines per recorded turn
        self.lead = []           # CLI lines before any turn
        self.exit_code = 0
        self._parse(records)
        self._turn = 0
        self._queue = []         # lines of the current turn not yet emitted
        self._waiting = None     # server request id we are paused on
        self.unexpected = []     # host lines nothing in the fixture matched

    def _parse(self, records):
        asked = {}               # recorded request id -> key
        block = None
        for r in records:
            d, msg = r.get("dir"), r.get("msg")
            if d == "exit":
                self.exit_code = (msg or {}).get("code") or 0
                continue
            if not isinstance(msg, dict):
                continue
            if d == "out":
                rk = _req_key(self.kind, msg)
                if rk is not None:
                    asked[rk[1]] = rk[0]
                if _is_turn(self.kind, msg):
                    block = []
                    self.turns.append(block)
                continue
            rid = _reply_id(self.kind, msg)
            if rid is not None and rid in asked:
                self.replies.setdefault(asked.pop(rid), []).append(msg)
                continue
            (block if block is not None else self.lead).append(msg)

    def start(self):
        for msg in self.lead:
            self.emit(json.dumps(msg))

    def write(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            self.unexpected.append(line)
            return
        rk = _req_key(self.kind, msg)
        if rk is not None:
            key, rid = rk
            queue = self.replies.get(key) or []
            if queue:
                reply = json.loads(json.dumps(queue.pop(0)))
                if self.kind == "claude":
                    reply["response"]["request_id"] = rid
                else:
                    reply["id"] = rid
                self.emit(json.dumps(reply))
            elif self.kind == "codex":
                self.emit(json.dumps({"id": rid, "error": {"code": -32603,
                                                           "message": "fixture has no %s" % key}}))
            else:
                self.emit(json.dumps({"type": "control_response", "response": {
                    "subtype": "success", "request_id": rid, "response": {}}}))
        if _is_turn(self.kind, msg):
            if self._turn < len(self.turns):
                self._queue = list(self.turns[self._turn])
                self._turn += 1
                self._pump()
            else:
                self.unexpected.append(line)
            return
        answered = _reply_id(self.kind, msg) if self.kind == "codex" else (
            (msg.get("response") or {}).get("request_id") if msg.get("type") == "control_response" else None)
        if answered is not None and answered == self._waiting:
            self._waiting = None
            self._pump()
        elif rk is None and answered is None:
            if not (self.kind == "codex" and msg.get("method") == "initialized"):
                self.unexpected.append(line)

    def _pump(self):
        while self._queue and self._waiting is None:
            msg = self._queue.pop(0)
            sid = _server_request_id(self.kind, msg)
            self.emit(json.dumps(msg))
            if sid is not None:
                self._waiting = sid

    def close(self):
        self.on_exit(self.exit_code)
