#!/usr/bin/env python3
"""Benchmark Chatter models without executing any real tool.

The real system prompt and real offered schemas go to the configured Ollama
endpoint.  Tool calls receive small canned results in-process: no file, web,
media, model-management or generation operation is performed.  Output contains
only aggregate timings and tool names, never generated prose.
"""
import argparse
import json
import os
import socket
import statistics
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))


CASES = [
    {"name": "plain", "prompt": "Reply with exactly: ready", "want": []},
    {"name": "inspect-file",
     "prompt": "Read /tmp/example.conf and tell me which colour it sets.",
     "want": ["read_file"]},
    {"name": "edit-file",
     "prompt": ("Change alpha to beta in /tmp/example.conf. Inspect it first, "
                "make the targeted edit, verify it, then report completion."),
     "want": ["read_file", "edit_file"]},
    {"name": "current-fact",
     "prompt": "What is the current stable release of ExampleOS? Check first.",
     "want_any": ["web_search", "wikipedia", "fetch_url"]},
    {"name": "music",
     "prompt": "Find the album Example Record in my music library and queue it.",
     "want": ["music_library", "control_media"]},
    {"name": "image-prompt",
     "prompt": "Write a Krea image prompt for a rainy neon street.",
     "want": ["use_skill"], "forbid": ["make_image"]},
    {"name": "image-generation",
     "prompt": "Generate an image of a rainy neon street with Krea.",
     "want": ["use_skill", "make_image"], "ordered": True},
    {"name": "delegate",
     "prompt": ("Delegate a filesystem survey to an explorer subagent and "
                "summarize its answer."),
     "want": ["spawn_agent"]},
    {"name": "long-followup",
     "history": True,
     "prompt": "What was the agreed marker? Reply with only the marker.",
     "want": [], "answer_contains": "cobalt-lantern"},
]


class WardenGuard:
    """Hold the same client and generation leases as an open Chatter turn."""

    def __init__(self, model, url="http://127.0.0.1:8199"):
        self.model, self.url = model, url.rstrip("/")
        self.client = "agent-bench:%s:%d:%s" % (
            socket.gethostname(), os.getpid(), uuid.uuid4().hex)
        self.stop = threading.Event()
        self.thread = None

    def post(self, path, body, strict=False):
        req = urllib.request.Request(
            self.url + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.load(response)
        except (OSError, ValueError):
            if strict:
                raise
            return {}
        if strict and not result.get("ok"):
            raise RuntimeError("ai-warden refused benchmark: %s" %
                               (result.get("reason") or result))
        return result

    def __enter__(self):
        self.post("/client/acquire", {"backend": "ollama",
                                      "client": self.client}, strict=True)
        self.post("/reserve", {"backend": "ollama", "model": self.model},
                  strict=True)

        def heartbeat():
            while not self.stop.wait(5):
                self.post("/client/renew", {"backend": "ollama",
                                            "client": self.client})
                self.post("/renew", {"backend": "ollama"})

        self.thread = threading.Thread(target=heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=6)
        self.post("/done", {"backend": "ollama"})
        self.post("/client/release", {"backend": "ollama",
                                      "client": self.client})


def attach_tools(oracle, instance, args):
    raw = args.get("names", "") or args.get("name", "") or ""
    if isinstance(raw, list):
        parts = [str(p).strip() for p in raw if str(p).strip()]
    else:
        parts = [p.strip() for p in str(raw).replace(",", " ").split()
                 if p.strip()]
    registry = instance._main_registry()
    wanted, unknown = [], []
    for part in parts:
        low = part.lower()
        if low in oracle.EXTRA_TOOL_GROUPS:
            wanted.extend(oracle.EXTRA_TOOL_GROUPS[low])
        elif low in oracle.AGENT_TOOL_GROUPS:
            wanted.extend(oracle.AGENT_TOOL_GROUPS[low])
        elif low == "all":
            wanted.extend(registry)
        elif part in registry:
            wanted.append(part)
        else:
            unknown.append(part)
    attached = list(dict.fromkeys(n for n in wanted if n in registry))
    instance._extra_tools.update(attached)
    result = {"attached": attached, "schemas": [registry[n] for n in attached]}
    if unknown:
        result["not_found"] = unknown
    return result


def fake_result(oracle, instance, state, name, args):
    if name in {"edit_file", "write_file"}:
        state["edited"] = True
    values = {
        "read_file": {"path": args.get("path"),
                      "content": ("colour=blue\nbeta\n" if state.get("edited")
                                  else "colour=blue\nalpha\n"),
                      "truncated": False},
        "edit_file": {"ok": True, "changed": True},
        "write_file": {"ok": True},
        "search_text": {"matches": []},
        "web_search": {"answer": "ExampleOS 7 is current.", "results": [
            {"title": "ExampleOS releases", "url": "https://example.invalid/releases"}]},
        "wikipedia": {"title": "ExampleOS", "extract": "Version 7 is current."},
        "fetch_url": {"url": args.get("url", ""), "text": "Version 7 is current."},
        "music_library": {"ok": True, "count": 2, "total": 2,
                          "tracks": [
                              {"artist": "Example", "album": "Example Record",
                               "title": "One", "path": "/music/example/01.flac"},
                              {"artist": "Example", "album": "Example Record",
                               "title": "Two", "path": "/music/example/02.flac"}]},
        "control_media": {"ok": True, "did": "queue_these", "sent": 2,
                          "queue_length": 2},
        "use_skill": {"name": args.get("name", "krea-prompt"),
                      "instructions": ("For a prompt-only request, return a positive and "
                                       "negative prompt. For generation, prepare those "
                                       "arguments and continue to make_image.")},
        "make_image": {"ok": True, "path": "/tmp/fake-image.png"},
        "spawn_agent": {"agent": args.get("agent", "explorer"),
                        "task": args.get("task", "filesystem survey"),
                        "rounds": 2, "tool_calls": 1,
                        "result": "The survey found three directories."},
        "get_current_time": {"local": "2026-09-05 17:00:00"},
    }
    if name == "get_tools":
        return attach_tools(oracle, instance, args)
    return values.get(name, {"ok": True})


def post_stream(url, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    first = None
    content, thinking, calls, done = [], [], [], {}
    with urllib.request.urlopen(req, timeout=900) as response:
        for raw in response:
            obj = json.loads(raw)
            msg = obj.get("message") or {}
            if first is None and (msg.get("content") or msg.get("thinking")
                                  or msg.get("tool_calls")):
                first = time.perf_counter()
            content.append(str(msg.get("content") or ""))
            thinking.append(str(msg.get("thinking") or ""))
            calls.extend(msg.get("tool_calls") or [])
            if obj.get("done"):
                done = obj
    ended = time.perf_counter()
    return {"content": "".join(content), "thinking": "".join(thinking),
            "calls": calls, "done": done,
            "wall_ms": (ended - started) * 1000,
            "first_ms": ((first or ended) - started) * 1000,
            "request_bytes": len(body)}


def call_parts(call):
    fn = call.get("function") or {}
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return str(fn.get("name") or ""), args if isinstance(args, dict) else {}


def run_case(oracle, model, case, url, num_ctx, num_predict):
    o = oracle.Ollama()
    o._model = model
    o._num_ctx = num_ctx
    o._extra_tools = set(oracle.request_tools(case["prompt"]))
    messages = [{"role": "system", "content": o._system_prompt("")}]
    if case.get("history"):
        messages.extend([
            {"role": "user", "content": "Keep these notes for later: "
             + ("ordinary project detail. " * 700)},
            {"role": "assistant", "content":
             "Understood. The agreed marker is cobalt-lantern."}])
    messages.append({"role": "user", "content": case["prompt"]})
    called, totals, final = [], {"wall_ms": 0, "prompt_ms": 0,
                                 "decode_ms": 0, "load_ms": 0,
                                 "prompt_tokens": 0, "decode_tokens": 0,
                                 "request_bytes": 0}, ""
    first_ms, requests, state = None, 0, {}
    for _round in range(6):
        payload = {"model": model, "messages": messages, "stream": True,
                   "options": dict(oracle.sampler_for(model), num_ctx=num_ctx,
                                   num_predict=num_predict),
                   "tools": o._offered_tools()}
        result = post_stream(url, payload)
        requests += 1
        if first_ms is None:
            first_ms = result["first_ms"]
        done = result["done"]
        for key, source, scale in (
                ("prompt_ms", "prompt_eval_duration", 1e-6),
                ("decode_ms", "eval_duration", 1e-6),
                ("load_ms", "load_duration", 1e-6),
                ("prompt_tokens", "prompt_eval_count", 1),
                ("decode_tokens", "eval_count", 1)):
            totals[key] += (done.get(source) or 0) * scale
        totals["wall_ms"] += result["wall_ms"]
        totals["request_bytes"] += result["request_bytes"]
        if not result["calls"]:
            final = result["content"].strip()
            break
        messages.append({"role": "assistant", "content": result["content"],
                         "tool_calls": result["calls"]})
        for call in result["calls"]:
            name, args = call_parts(call)
            called.append(name)
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(
                                 fake_result(oracle, o, state, name, args))})
            if name in o._main_registry():
                o._extra_tools.add(name)
            for companion in oracle.TOOL_COMPANIONS.get(name, ()):
                o._extra_tools.add(companion)

    want = case.get("want", [])
    passed = all(n in called for n in want)
    if case.get("want_any"):
        passed = passed and any(n in called for n in case["want_any"])
    passed = passed and not any(n in called for n in case.get("forbid", []))
    if case.get("ordered") and all(n in called for n in want):
        passed = passed and [called.index(n) for n in want] == sorted(
            called.index(n) for n in want)
    passed = passed and bool(final)
    if case.get("answer_contains"):
        passed = passed and case["answer_contains"].lower() in final.lower()
    return dict(case=case["name"], passed=passed, tools=called,
                requests=requests,
                first_ms=round(first_ms or 0, 1),
                wall_ms=round(totals["wall_ms"], 1),
                prompt_ms=round(totals["prompt_ms"], 1),
                decode_ms=round(totals["decode_ms"], 1),
                load_ms=round(totals["load_ms"], 1),
                prompt_tokens=int(totals["prompt_tokens"]),
                decode_tokens=int(totals["decode_tokens"]),
                request_bytes=int(totals["request_bytes"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--url", default=os.environ.get("OLLAMA_HOST",
                                                     "http://127.0.0.1:11434"))
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--num-predict", type=int, default=768,
                    help="hard ceiling per round, including hidden reasoning")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--case", action="append", dest="cases",
                    help="run only this named case (repeatable)")
    args = ap.parse_args()

    import main as oracle
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    all_rows = []
    for model in args.model:
        rows = []
        cases = [c for c in CASES if not args.cases or c["name"] in args.cases]
        if args.cases and len(cases) != len(set(args.cases)):
            raise SystemExit("unknown case name")
        with WardenGuard(model):
            for _ in range(args.repeats):
                for case in cases:
                    row = run_case(oracle, model, case, args.url, args.num_ctx,
                                   args.num_predict)
                    rows.append(row)
                    print(json.dumps(dict(model=model, **row), sort_keys=True),
                          flush=True)
        all_rows += [dict(model=model, **r) for r in rows]
        print(json.dumps({"summary": model,
                          "passed": sum(r["passed"] for r in rows),
                          "cases": len(rows),
                          "median_first_ms": round(statistics.median(
                              r["first_ms"] for r in rows), 1),
                          "median_wall_ms": round(statistics.median(
                              r["wall_ms"] for r in rows), 1)}), flush=True)
    del app


if __name__ == "__main__":
    main()
