#!/usr/bin/env python3
"""Protocol regression test for qwen38-ollama-shim.py; no real daemon/GPU."""

import importlib.util
import json
import os
import hashlib
import io
import tempfile
import threading
import urllib.error
import urllib.request
from unittest.mock import patch
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
    mode = "normal"
    entered = threading.Event()
    release = threading.Event()

    def do_GET(self):  # noqa: N802
        raw = b'{"status":"ok"}'
        self.send_response(200); self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.seen.append(body)
        if self.mode == "blocked":
            self.entered.set()
            assert self.release.wait(5)
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
            if self.mode == "error":
                raw = b'data: {"error":{"message":"fake failure"}}\n\n'
            elif self.mode == "eof":
                raw = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            elif self.mode == "length":
                raw = b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'
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
        self.route = shim.QWEN
        self.starts = 0
        self.stops = 0

    def start_llama(self, route=shim.QWEN):
        self.starts += 1
        self.route = route
        self.llama = Alive()

    def stop_llama(self, route=None):
        if route is not None and self.route is not route:
            return
        self.stops += 1
        self.route = None
        self.llama = None


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
    history = shim.ollama_messages_to_openai([
        {"role": "assistant", "tool_calls": [
            {"id": "a", "function": {"name": "first", "arguments": {}}},
            {"id": "b", "function": {"name": "second", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "b", "content": "second result"},
        {"role": "tool", "tool_name": "first", "content": "first result"},
    ])
    assert [(m["tool_call_id"], m["name"]) for m in history[1:]] == [("b", "second"), ("a", "first")]
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

        # A resident routed model for the metadata checks below.
        shim.ENGINES.llama, shim.ENGINES.route = Alive(), shim.QWEN

        show = json.loads(post(base + "/api/show", {"model": shim.MODEL}))
        assert show["details"]["quantization_level"] == "Q2_0"
        assert show["capabilities"] == ["completion", "tools", "thinking"]

        with urllib.request.urlopen(base + "/api/ps", timeout=5) as response:
            models = json.loads(response.read())["models"]
        assert {m["name"] for m in models} == {"ordinary:latest", shim.MODEL}
        assert next(m for m in models if m["name"] == shim.MODEL)["context_length"] == shim.CTX

        with urllib.request.urlopen(base + "/api/tags", timeout=5) as response:
            models = json.loads(response.read())["models"]
        assert {m["name"] for m in models} == {"ordinary:latest", shim.MODEL}
        assert sum(m["name"] == shim.MODEL for m in models) == 1
        assert next(m for m in models if m["name"] == shim.MODEL)["size"] == shim.MODEL_SIZE

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

        for mode in ("error", "eof", "length"):
            Llama.mode = mode
            frames = [json.loads(line) for line in post(base + "/api/chat", {
                "model": shim.MODEL, "messages": [], "stream": True}).splitlines()]
            if mode == "length":
                assert frames[-1]["done_reason"] == "length"
            else:
                assert "error" in frames[-1] and not any(f.get("done") for f in frames)
        Llama.mode = "normal"

        with tempfile.TemporaryDirectory() as tmp:
            weights = Path(tmp) / "model.gguf"
            weights.write_bytes(b"fake model")
            route = shim.Route("bonsai-test", str(weights), 10,
                               hashlib.sha256(b"fake model").hexdigest(),
                               "prism-server", 32768, "PQ2_0", shim.BONSAI.args)
            shim.ROUTES.append(route)
            with urllib.request.urlopen(base + "/api/tags") as response:
                assert sum(m["name"] == route.name for m in json.load(response)["models"]) == 1
            result = json.loads(post(base + "/api/chat", {
                "model": route.name, "stream": False, "messages": []}))
            assert result["model"] == route.name and Llama.seen[-1]["model"] == route.name
            assert shim.ENGINES.route is route
            post(base + "/api/generate", {"model": shim.MODEL, "keep_alive": 0})
            assert shim.ENGINES.route is route  # unload is targeted
            post(base + "/api/generate", {"model": route.name, "keep_alive": 0})
            assert shim.ENGINES.route is None

            # Hold a real fake HTTP generation open; another client cannot
            # switch engines or unload it during the streaming lifetime.
            Llama.mode = "blocked"
            worker = threading.Thread(target=post, args=(base + "/api/chat", {
                "model": route.name, "messages": [], "stream": True}))
            worker.start()
            assert Llama.entered.wait(3)
            try:
                for model in (route.name, shim.MODEL, "ordinary:latest"):
                    try:
                        post(base + "/api/generate", {"model": model, "keep_alive": 0})
                    except urllib.error.HTTPError as error:
                        assert error.code == 409
                    else:
                        raise AssertionError("concurrent unload was accepted")
                assert shim.ENGINES.route is route
            finally:
                Llama.release.set()
                worker.join(3)
                Llama.mode = "normal"
            assert not worker.is_alive() and not shim.REQUEST_LOCK.locked()

            # Real engine lifecycle against fake processes/network only.
            events = []
            class Process:
                pid, returncode = 123, None
                def __init__(self, argv):
                    events.append(("start", argv))
                def poll(self):
                    return self.returncode
                def terminate(self):
                    events.append(("stop",))
                    self.returncode = 0
                def wait(self, timeout):
                    return 0
            class Health(io.BytesIO):
                status = 200
            engines = shim.Engines()
            route2 = shim.Route("second", str(weights), 10, route.digest,
                                "stock-server", 16384, "Q2_0", shim.QWEN.args)
            with patch.object(shim.subprocess, "Popen", Process), \
                 patch.object(shim.urllib.request, "urlopen", lambda *a, **k: Health(b'{"models":[]}')):
                engines.start_llama(route)
                first_argv = events[-1][1]
                assert first_argv[0] == "prism-server" and "--spec-type" not in first_argv
                assert first_argv[first_argv.index("--parallel") + 1] == "1"
                engines.start_llama(route2)
                assert [e[0] for e in events] == ["start", "stop", "start"]
                assert events[-1][1][0] == "stock-server" and "--spec-type" in events[-1][1]
                engines.stop_llama(route)
                assert engines.route is route2
                engines.stop_llama()
                assert engines.llama is None
            with patch.object(shim.urllib.request, "urlopen", side_effect=OSError("fake unload failure")), \
                 patch.object(shim.subprocess, "Popen") as launch:
                try:
                    engines.start_llama(route)
                except OSError:
                    pass
                else:
                    raise AssertionError("failed unload did not block load")
                launch.assert_not_called()
            weights.write_bytes(b"wrong data")
            try:
                route.verify()
            except RuntimeError:
                pass
            else:
                raise AssertionError("corrupt model accepted")
            weights.unlink()
            with urllib.request.urlopen(base + "/api/tags") as response:
                assert route.name not in [m["name"] for m in json.load(response)["models"]]
            assert b'"ordinary"' in post(base + "/api/chat", {"model": "ordinary:latest"})
            shim.ROUTES.remove(route)
    finally:
        for srv in (router, llama, upstream):
            if srv is not None:
                srv.shutdown(); srv.server_close()
    print("router: original protocol, two routes, lifecycle, concurrency, corrupt/missing weights and stream failures passed")


if __name__ == "__main__":
    # Nothing in this harness inherits a display or reaches a real daemon.
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("DISPLAY", None)
    main()
