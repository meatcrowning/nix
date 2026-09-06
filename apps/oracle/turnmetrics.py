"""Content-free performance telemetry for Chatter turns.

One JSON object is appended after each completed/cancelled request.  It records
timings, counts and tool names, never prompt, reply, tool arguments or results.
The default lives in local state and is not part of the synced session store.
"""
import json
import os
import time
from collections import Counter
from pathlib import Path


class TurnMetrics:
    def __init__(self, selftest=False):
        configured = os.environ.get("ORACLE_METRICS")
        self.path = Path(os.path.expanduser(
            configured or "~/.local/state/oracle/turn-metrics.jsonl"))
        self.enabled = configured != "0" and (not selftest or bool(configured))
        self._turn = None
        self._started = 0.0
        self._tool_started = 0.0

    def begin(self, *, model, kind, num_ctx, warm, history_messages,
              input_chars, attachments):
        if not self.enabled:
            return
        self._started = time.monotonic()
        self._tool_started = 0.0
        self._turn = {
            "version": 1,
            "started": int(time.time()),
            "model": str(model),
            "kind": str(kind),
            "num_ctx": int(num_ctx),
            "warm": bool(warm),
            "history_messages": int(history_messages),
            "input_chars": int(input_chars),
            "attachments": int(attachments),
            "requests": 0,
            "request_bytes": 0,
            "tool_rounds": 0,
            "tool_calls": 0,
            "tool_names": {},
            "tool_wait_ms": 0.0,
            "prompt_tokens": 0,
            "prompt_ms": 0.0,
            "decode_tokens": 0,
            "decode_ms": 0.0,
            "load_ms": 0.0,
            "first_output_ms": None,
        }

    def request(self, body_bytes):
        if self._turn is None:
            return
        self._turn["requests"] += 1
        self._turn["request_bytes"] += int(body_bytes)

    def first_output(self):
        if self._turn is not None and self._turn["first_output_ms"] is None:
            self._turn["first_output_ms"] = round(
                (time.monotonic() - self._started) * 1000, 3)

    def tool_round(self, names):
        if self._turn is None:
            return
        self._turn["tool_rounds"] += 1
        self._turn["tool_calls"] += len(names)
        counts = Counter(self._turn["tool_names"])
        counts.update(str(n or "tool") for n in names)
        self._turn["tool_names"] = dict(sorted(counts.items()))
        self._tool_started = time.monotonic()

    def tools_finished(self):
        if self._turn is None or not self._tool_started:
            return
        self._turn["tool_wait_ms"] += (
            time.monotonic() - self._tool_started) * 1000
        self._tool_started = 0.0

    def server_done(self, obj):
        if self._turn is None:
            return
        pairs = (("prompt_eval_count", "prompt_tokens", 1),
                 ("prompt_eval_duration", "prompt_ms", 1e-6),
                 ("eval_count", "decode_tokens", 1),
                 ("eval_duration", "decode_ms", 1e-6),
                 ("load_duration", "load_ms", 1e-6))
        for source, target, scale in pairs:
            value = obj.get(source)
            if isinstance(value, (int, float)) and value >= 0:
                self._turn[target] += value * scale

    def note_server_error(self):
        if self._turn is not None:
            self._turn["server_error"] = True

    def finish(self, status, reason=""):
        if self._turn is None:
            return
        row, self._turn = self._turn, None
        row["elapsed_ms"] = round((time.monotonic() - self._started) * 1000, 3)
        row["tool_wait_ms"] = round(row["tool_wait_ms"], 3)
        for key in ("prompt_ms", "decode_ms", "load_ms"):
            row[key] = round(row[key], 3)
        row["status"] = str(status)
        if reason:
            row["reason"] = str(reason)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
                fh.write("\n")
        except OSError:
            pass  # telemetry may never break a conversation
