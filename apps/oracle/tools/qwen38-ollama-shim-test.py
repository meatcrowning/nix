#!/usr/bin/env python3
"""Protocol regression test for qwen38-ollama-shim.py; no real daemon/GPU."""

import importlib.util
import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "qwen38_shim", HERE / "qwen38-ollama-shim.py")
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)


class Quiet(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class Upstream(Quiet):
    seen = []

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", "0")))

    def do_GET(self):  # noqa: N802
        if self.path == "/api/ps":
            body = {"models": [{"name": "ordinary:latest", "context_length": 4096}]}
        else:
            body = {"models": [{"name": "ordinary:latest"}, {"name": shim.MODEL}]}
        raw = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        raw = self._body()
        self.seen.append((self.path, json.loads(raw or b"{}")))
        reply = (b'{"model":"ordinary:latest","message":{"role":"assistant",'
                 b'"content":"ordinary"},"done":true}\n')
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(reply))); self.end_headers()
        self.wfile.write(reply)


class Llama(Quiet):
    seen = []

    def do_GET(self):  # noqa: N802
        raw = b'{"status":"ok"}'
        self.send_response(200); self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.seen.append(body)
        if body.get("stream"):
            events = [
                {"choices": [{"delta": {"reasoning_content": "think "}}]},
                {"choices": [{"delta": {"content": "answer "}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0,
                    "id": "call_x", "function": {"name": "read_", "arguments": "{\"pa"}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0,
                    "function": {"name": "file", "arguments": "th\":\"x\"}"}}]},
                    "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                 "timings": {"predicted_ms": 250}},
            ]
            raw = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n"
                           for event in events) + b"data: [DONE]\n\n"
            ctype = "text/event-stream"
        else:
            raw = json.dumps({
                "choices": [{"message": {"content": "done",
                    "reasoning_content": "thought",
                    "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "clock", "arguments": "{}"}}]},
                    "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                "timings": {"predicted_ms": 150},
            }).encode()
            ctype = "application/json"
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)


class Alive:
    def poll(self):
        return None


class FakeEngines:
    def __init__(self):
        self.llama = Alive()
        self.starts = 0
        self.stops = 0

    def start_llama(self):
        self.starts += 1

    def stop_llama(self):
        self.stops += 1


def server(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.read()


def main():
    upstream, llama, router = server(Upstream), server(Llama), None
    try:
        shim.UPSTREAM = "http://127.0.0.1:%d" % upstream.server_port
        shim.LLAMA = "http://127.0.0.1:%d" % llama.server_port
        shim.ENGINES = FakeEngines()
        router = server(shim.Handler)
        base = "http://127.0.0.1:%d" % router.server_port

        ordinary = post(base + "/api/chat", {
            "model": "ordinary:latest", "messages": [{"role": "user", "content": "x"}],
            "stream": True})
        assert b'"content":"ordinary"' in ordinary
        assert Upstream.seen[-1][1]["model"] == "ordinary:latest"
        assert shim.ENGINES.stops == 1

        show = json.loads(post(base + "/api/show", {"model": shim.MODEL}))
        assert show["details"]["quantization_level"] == "Q2_0"
        assert show["capabilities"] == ["completion", "tools", "thinking"]

        with urllib.request.urlopen(base + "/api/ps", timeout=5) as response:
            models = json.loads(response.read())["models"]
        assert {m["name"] for m in models} == {"ordinary:latest", shim.MODEL}
        assert next(m for m in models if m["name"] == shim.MODEL)["context_length"] == shim.CTX

        streamed = post(base + "/api/chat", {
            "model": shim.MODEL, "stream": True,
            "messages": [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "read_file", "arguments": {"path": "old"}}}]},
                {"role": "tool", "tool_name": "read_file", "content": "old result"},
                {"role": "user", "content": "next"},
            ],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
            "options": {"temperature": 0.3, "num_ctx": 32768},
        })
        frames = [json.loads(line) for line in streamed.splitlines()]
        assert frames[0]["message"]["thinking"] == "think "
        assert frames[1]["message"]["content"] == "answer "
        call = frames[2]["message"]["tool_calls"][0]
        assert call["function"] == {"name": "read_file", "arguments": {"path": "x"}}
        assert frames[-1]["done"] and frames[-1]["prompt_eval_count"] == 10
        sent = Llama.seen[-1]
        assert sent["messages"][1]["tool_call_id"] == "call_0_0"
        assert sent["messages"][1]["name"] == "read_file"
        assert sent["temperature"] == 0.3 and "num_ctx" not in sent
        assert sent["stream_options"] == {"include_usage": True}

        result = json.loads(post(base + "/api/chat", {
            "model": shim.MODEL, "stream": False,
            "messages": [{"role": "user", "content": "x"}],
        }))
        assert result["message"]["thinking"] == "thought"
        assert result["message"]["tool_calls"][0]["function"]["arguments"] == {}
        assert result["eval_count"] == 3 and result["eval_duration"] == 150_000_000
        assert shim.ENGINES.starts == 2
    finally:
        for srv in (router, llama, upstream):
            if srv is not None:
                srv.shutdown(); srv.server_close()
    print("qwen38 shim: 18 checks passed")


if __name__ == "__main__":
    # Nothing in this harness inherits a display or reaches a real daemon.
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("DISPLAY", None)
    main()
