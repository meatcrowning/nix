#!/usr/bin/env python3
"""Ollama-compatible router for chatter's Qwen QAT and Bonsai models.

Ordinary requests are relayed byte-for-byte to the Ollama daemon on the
private upstream port.  The registered tags Ollama cannot parse are translated to
llama.cpp's OpenAI-compatible chat endpoint.  The shim owns the public Ollama
port, so chatter keeps one backend contract for its picker, tool loop,
streaming, model stats, lifecycle controls, book tunnel and ai-warden.

The process also supervises the private Ollama daemon.  llama-server is lazy:
it starts only for a routed model and is stopped by Ollama's existing
``keep_alive: 0`` unload request.  Switching between engines unloads the old
one first, preserving the one-model invariant of OLLAMA_MAX_LOADED_MODELS=1.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODEL = os.environ.get(
    "QWEN38_Q2_MODEL",
    "hf.co/sdkyuan/qwen3.8-27B-qat-q2_0-gguf:latest",
)
MODEL_PATH = os.environ.get(
    "QWEN38_Q2_MODEL_PATH",
    "/home/lam/.ollama/models/blobs/"
    "sha256-cadd809e691c5fa2cc33a75020930fc404db84528bff9a06177bf77bedc0a877",
)
MODEL_SIZE = int(os.environ.get("QWEN38_Q2_MODEL_SIZE", "8759266208"))
CTX = int(os.environ.get("QWEN38_Q2_CTX", "32768"))
LISTEN_HOST = os.environ.get("OLLAMA_SHIM_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("OLLAMA_SHIM_PORT", "11434"))
UPSTREAM = os.environ.get("OLLAMA_SHIM_UPSTREAM", "http://127.0.0.1:11436")
LLAMA = os.environ.get("OLLAMA_SHIM_LLAMA", "http://127.0.0.1:11437")
OLLAMA_BIN = os.environ.get("OLLAMA_SHIM_OLLAMA_BIN", "ollama")
LLAMA_BIN = os.environ.get("OLLAMA_SHIM_LLAMA_BIN", "llama-server")
START_TIMEOUT = int(os.environ.get("QWEN38_Q2_START_TIMEOUT", "900"))


class Route:
    def __init__(self, name, path, size, digest, binary, ctx, quant, args=()):
        self.name, self.path, self.size, self.digest = name, path, size, digest
        self.binary, self.ctx, self.quant, self.args = binary, ctx, quant, args
        self.verified_stat = None

    def installed(self):
        try:
            return os.path.getsize(self.path) == self.size
        except OSError:
            return False

    def verify(self):
        stat = os.stat(self.path)
        identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if identity != self.verified_stat:
            with open(self.path, "rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if stat.st_size != self.size or digest != self.digest:
                raise RuntimeError(f"{self.name}: model size/SHA-256 mismatch")
            self.verified_stat = identity

    def details(self):
        return {"format": "gguf", "family": "qwen35",
                "parameter_size": "26.9B", "quantization_level": self.quant}

    def tag(self):
        return {"name": self.name, "model": self.name, "size": self.size,
                "digest": "sha256:" + self.digest, "details": self.details()}


QWEN = Route(MODEL, MODEL_PATH, MODEL_SIZE,
             "cadd809e691c5fa2cc33a75020930fc404db84528bff9a06177bf77bedc0a877",
             LLAMA_BIN, CTX, "Q2_0",
             ("--spec-type", "ngram-mod", "--spec-ngram-mod-n-match", "24",
              "--spec-ngram-mod-n-min", "48", "--spec-ngram-mod-n-max", "64"))
BONSAI_DIGEST = "3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1"
BONSAI = Route("prism-ml/Ternary-Bonsai-2-27B-PQ2_0",
               os.environ.get("BONSAI_MODEL_PATH", "/home/lam/.local/share/bonsai/" + BONSAI_DIGEST + ".gguf"),
               7206168928, BONSAI_DIGEST, os.environ.get("BONSAI_LLAMA_BIN", ""),
               32768, "PQ2_0", ("--parallel", "1", "--cache-type-k", "f16", "--cache-type-v", "f16"))
ROUTES = [QWEN] + ([BONSAI] if BONSAI.binary else [])
# Covers the whole generation, not just Popen: concurrent clients must never
# switch/unload an engine while another request is still using it.
REQUEST_LOCK = threading.Lock()


def route_for(name):
    name = str(name or "")
    return next((r for r in ROUTES if name == r.name or
                 (r.name.endswith(":latest") and name == r.name[:-7])), None)


def log(message: str) -> None:
    print("qwen38-shim: " + message, file=sys.stderr, flush=True)


def _json(data: bytes) -> dict:
    try:
        obj = json.loads(data or b"{}")
        return obj if isinstance(obj, dict) else {}
    except (TypeError, ValueError):
        return {}


def _tool_arguments(value: object) -> object:
    if not isinstance(value, str):
        return value if isinstance(value, dict) else {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except ValueError:
        return {"raw": value}


def ollama_messages_to_openai(messages: object) -> list[dict]:
    """Add the call ids OpenAI requires to Ollama's id-less tool history."""
    out: list[dict] = []
    pending: list[tuple[str, str]] = []
    for mi, raw in enumerate(messages if isinstance(messages, list) else []):
        if not isinstance(raw, dict):
            continue
        msg = dict(raw)
        role = str(msg.get("role") or "")
        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            calls = []
            for ci, original in enumerate(msg["tool_calls"]):
                call = original if isinstance(original, dict) else {}
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                call_id = str(call.get("id") or f"call_{mi}_{ci}")
                name = str(fn.get("name") or call.get("name") or "tool")
                args = fn.get("arguments", call.get("arguments", {}))
                if not isinstance(args, str):
                    args = json.dumps(args if isinstance(args, dict) else {})
                calls.append({"id": call_id, "type": "function",
                              "function": {"name": name, "arguments": args}})
                pending.append((call_id, name))
            msg["tool_calls"] = calls
        elif role == "tool":
            result_id = msg.get("tool_call_id")
            result_name = msg.get("name") or msg.get("tool_name")
            match = next((i for i, (cid, name) in enumerate(pending)
                          if (cid == result_id if result_id else name == result_name)), 0)
            call_id, name = pending.pop(match) if pending else (
                f"call_orphan_{mi}", str(msg.get("tool_name") or "tool"))
            msg["tool_call_id"] = str(msg.get("tool_call_id") or call_id)
            msg["name"] = str(msg.get("name") or msg.get("tool_name") or name)
            msg.pop("tool_name", None)
        # This model is text-only in the tailored server (--no-mmproj).  The
        # synthetic /api/show response keeps chatter from sending media here.
        msg.pop("images", None)
        out.append(msg)
    return out


def openai_tools_to_ollama(calls: object) -> list[dict]:
    out = []
    for raw in calls if isinstance(calls, list) else []:
        if not isinstance(raw, dict):
            continue
        fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        out.append({
            "id": str(raw.get("id") or ""),
            "type": "function",
            "function": {
                "name": str(fn.get("name") or ""),
                "arguments": _tool_arguments(fn.get("arguments", {})),
            },
        })
    return out


def ollama_chat_to_openai(body: dict, route=QWEN) -> dict:
    opts = body.get("options") if isinstance(body.get("options"), dict) else {}
    payload = {
        "model": route.name,
        "messages": ollama_messages_to_openai(body.get("messages")),
        "stream": bool(body.get("stream", True)),
        "cache_prompt": True,
        "reasoning_format": "deepseek",
        "parallel_tool_calls": True,
    }
    if isinstance(body.get("tools"), list):
        payload["tools"] = body["tools"]
    mapping = {
        "temperature": "temperature", "top_p": "top_p", "top_k": "top_k",
        "min_p": "min_p", "repeat_penalty": "repeat_penalty",
        "presence_penalty": "presence_penalty", "frequency_penalty": "frequency_penalty",
        "seed": "seed", "stop": "stop", "num_predict": "max_tokens",
    }
    for source, target in mapping.items():
        if source in opts:
            payload[target] = opts[source]
    if payload["stream"]:
        payload["stream_options"] = {"include_usage": True}
    return payload


def _ollama_tool_calls_from_parts(parts: dict[int, dict]) -> list[dict]:
    calls = []
    for idx in sorted(parts):
        part = parts[idx]
        calls.append(openai_tools_to_ollama([{
            "id": part.get("id", ""), "type": "function",
            "function": {"name": part.get("name", ""),
                         "arguments": part.get("arguments", "")},
        }])[0])
    return calls


def openai_response_to_ollama(obj: dict, route=QWEN) -> dict:
    choices = obj.get("choices") if isinstance(obj.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    if obj.get("error") or not choice.get("finish_reason"):
        raise RuntimeError(str(obj.get("error") or "Incomplete llama-server response"))
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    timings = obj.get("timings") if isinstance(obj.get("timings"), dict) else {}
    out_msg = {"role": "assistant", "content": str(message.get("content") or "")}
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if reasoning:
        out_msg["thinking"] = str(reasoning)
    calls = openai_tools_to_ollama(message.get("tool_calls"))
    if calls:
        out_msg["tool_calls"] = calls
    predicted_ms = float(timings.get("predicted_ms") or 0)
    return {
        "model": route.name,
        "message": out_msg,
        "done": True,
        "done_reason": "length" if choice.get("finish_reason") == "length" else "stop",
        "prompt_eval_count": int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0),
        "eval_count": int(usage.get("completion_tokens") or timings.get("predicted_n") or 0),
        "eval_duration": int(predicted_ms * 1_000_000),
    }


class Engines:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.ollama: subprocess.Popen | None = None
        self.llama: subprocess.Popen | None = None
        self.route: Route | None = None

    def start_ollama(self) -> None:
        env = os.environ.copy()
        parsed = urllib.parse.urlsplit(UPSTREAM)
        env["OLLAMA_HOST"] = f"{parsed.hostname}:{parsed.port}"
        self.ollama = subprocess.Popen([OLLAMA_BIN, "serve"], env=env)
        log(f"ollama on {parsed.hostname}:{parsed.port} (pid {self.ollama.pid})")

    def unload_ollama(self) -> None:
        deadline = time.monotonic() + 30
        while True:
            with urllib.request.urlopen(UPSTREAM + "/api/ps", timeout=5) as response:
                models = json.loads(response.read()).get("models")
            if not isinstance(models, list):
                raise RuntimeError("Cannot confirm private Ollama's loaded models")
            if not models:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Private Ollama did not unload; refusing to load another model")
            for item in models:
                name = item.get("name") or item.get("model")
                if name:
                    result = request_json(UPSTREAM + "/api/generate",
                                          {"model": name, "keep_alive": 0}, timeout=30)
                    if result.get("error"):
                        raise RuntimeError(str(result["error"]))
            time.sleep(0.1)

    def start_llama(self, route=QWEN) -> None:
        with self.lock:
            if self.llama is not None and self.llama.poll() is None:
                if self.route is route:
                    return
            route.verify()
            self.stop_llama()
            self.unload_ollama()
            parsed = urllib.parse.urlsplit(LLAMA)
            argv = [
                route.binary, "--model", route.path, "--alias", route.name,
                "--jinja", "--reasoning-budget", "-1",
                "--ctx-size", str(route.ctx), "--host", str(parsed.hostname),
                "--port", str(parsed.port), "-ngl", "99",
                "--temp", "1.0", "--top-p", "0.95", "--top-k", "20",
                "--min-p", "0.0", "--presence-penalty", "0.0",
                "--repeat-penalty", "1.0", "--flash-attn", "on",
                "--no-mmproj", "--slots", "--metrics",
            ] + list(route.args)
            self.llama = subprocess.Popen(argv)
            self.route = route
            log(f"llama.cpp loading {route.name} (pid {self.llama.pid})")
            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                if self.llama.poll() is not None:
                    raise RuntimeError(f"{route.name} server exited {self.llama.returncode} while loading")
                try:
                    with urllib.request.urlopen(LLAMA + "/health", timeout=2) as response:
                        if response.status == 200:
                            log(f"{route.name} server ready")
                            return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(1)
            self.stop_llama()
            raise RuntimeError(f"{route.name} server did not load within {START_TIMEOUT}s")

    def stop_llama(self, route=None) -> None:
        with self.lock:
            if route is not None and self.route is not route:
                return
            proc = self.llama
            if proc is None or proc.poll() is not None:
                self.llama, self.route = None, None
                return
            log(f"unloading {self.route.name}")
            proc.terminate()
            try:
                proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            self.llama, self.route = None, None

    def stop(self) -> None:
        self.stop_llama()
        proc, self.ollama = self.ollama, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                proc.kill()


# urllib.parse is kept late so importing the pure conversion helpers is cheap.
import urllib.parse  # noqa: E402


ENGINES = Engines()


def request_json(url: str, obj: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return _json(response.read())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        log(fmt % args)

    def _read_body(self) -> bytes:
        try:
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))
        except (TypeError, ValueError):
            return b""

    def _send_json(self, status: int, obj: dict, ndjson: bool = False) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode() + (b"\n" if ndjson else b"")
        self.send_response(status)
        self.send_header("Content-Type", "application/x-ndjson" if ndjson else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, body: bytes) -> None:
        url = UPSTREAM + self.path
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        req = urllib.request.Request(url, data=body if self.command != "GET" else None,
                                     headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=None)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, urllib.error.URLError) as error:
            self._send_json(503, {"error": "ollama is unavailable: " + str(error.reason if hasattr(error, "reason") else error)})
            return
        with response:
            self.send_response(response.status)
            ctype = response.headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", ctype)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/tags":
            self._merged_tags()
        elif path == "/api/ps":
            self._merged_ps()
        else:
            self._proxy(b"")

    def do_DELETE(self) -> None:  # noqa: N802
        body = self._read_body()
        if route_for(_json(body).get("model") or _json(body).get("name")):
            self._send_json(400, {"error": "Routed weights are managed outside Ollama; unload instead"})
            return
        if not REQUEST_LOCK.acquire(blocking=False):
            self._send_json(409, {"error": "A model request is active; retry when it finishes"})
            return
        try:
            self._proxy(body)
        finally:
            REQUEST_LOCK.release()

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_body()
        obj = _json(body)
        path = self.path.split("?", 1)[0]
        model = obj.get("model") or obj.get("name")
        route = route_for(model)
        if path == "/api/show" and route:
            self._show(route)
            return
        if path not in ("/api/chat", "/api/generate", "/api/embed", "/api/embeddings",
                        "/v1/chat/completions", "/v1/completions", "/v1/embeddings"):
            self._proxy(body)
            return
        if not REQUEST_LOCK.acquire(blocking=False):
            self._send_json(409, {"error": "A model request is active; retry when it finishes"})
            return
        try:
            if route and obj.get("keep_alive") == 0 and not obj.get("messages") and not obj.get("prompt"):
                ENGINES.stop_llama(route)
                self._send_json(200, {"model": route.name, "done": True, "done_reason": "unload"})
            elif route and path == "/api/chat":
                self._chat(obj, route)
            elif route:
                self._send_json(400, {"error": "Use /api/chat for routed model generation"})
            else:
                # An unload for an ordinary model must not evict another route.
                if model and not (obj.get("keep_alive") == 0 and not obj.get("prompt") and not obj.get("messages")):
                    ENGINES.stop_llama()
                self._proxy(body)
        except Exception as error:
            self._send_json(503, {"error": str(error)})
        finally:
            REQUEST_LOCK.release()

    def _show(self, route=QWEN) -> None:
        self._send_json(200, {
            "details": route.details(),
            "model_info": {"general.architecture": "qwen35",
                           "qwen35.context_length": 262144},
            "capabilities": ["completion", "tools", "thinking"],
        })

    def _merged_ps(self) -> None:
        try:
            with urllib.request.urlopen(UPSTREAM + "/api/ps", timeout=5) as response:
                doc = _json(response.read())
        except (OSError, urllib.error.URLError):
            doc = {"models": []}
        models = doc.get("models") if isinstance(doc.get("models"), list) else []
        proc = ENGINES.llama
        route = ENGINES.route
        if proc is not None and proc.poll() is None and route is not None:
            models = [m for m in models if not route_for(m.get("name"))]
            models.append(dict(route.tag(), context_length=route.ctx))
        self._send_json(200, {"models": models})

    def _merged_tags(self) -> None:
        try:
            with urllib.request.urlopen(UPSTREAM + "/api/tags", timeout=5) as response:
                doc = _json(response.read())
        except (OSError, urllib.error.URLError):
            doc = {"models": []}
        models = doc.get("models") if isinstance(doc.get("models"), list) else []
        models = [m for m in models if not route_for(m.get("name") or m.get("model"))]
        models.extend(r.tag() for r in ROUTES if r is QWEN or r.installed())
        self._send_json(200, {"models": models})

    def _chat(self, body: dict, route=QWEN) -> None:
        try:
            ENGINES.start_llama(route)
            payload = ollama_chat_to_openai(body, route)
            if payload["stream"]:
                self._chat_stream(payload)
            else:
                obj = request_json(LLAMA + "/v1/chat/completions", payload, timeout=3600)
                self._send_json(200, openai_response_to_ollama(obj, route))
        except urllib.error.HTTPError as error:
            reason = error.read().decode("utf-8", "replace") or str(error)
            self._send_json(error.code, {"error": reason[:4000]})
        except Exception as error:  # surfaced to chatter, never a blank failure
            self._send_json(503, {"error": str(error)})

    def _chat_stream(self, payload: dict) -> None:
        req = urllib.request.Request(
            LLAMA + "/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        response = urllib.request.urlopen(req, timeout=None)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
        self.end_headers()
        parts: dict[int, dict] = {}
        usage: dict = {}
        timings: dict = {}
        finish = None
        try:
            with response:
                for raw in response:
                    line = raw.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise RuntimeError(str(event["error"]))
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    if isinstance(event.get("timings"), dict):
                        timings = event["timings"]
                    choices = event.get("choices") if isinstance(event.get("choices"), list) else []
                    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                    message = {"role": "assistant", "content": str(delta.get("content") or "")}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        message["thinking"] = str(reasoning)
                    if message["content"] or message.get("thinking"):
                        self.wfile.write(json.dumps({"model": payload["model"], "message": message,
                                                     "done": False}, separators=(",", ":")).encode() + b"\n")
                        self.wfile.flush()
                    for call in delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else []:
                        if not isinstance(call, dict):
                            continue
                        idx = int(call.get("index") or 0)
                        part = parts.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if call.get("id"):
                            part["id"] = str(call["id"])
                        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                        part["name"] += str(fn.get("name") or "")
                        args = fn.get("arguments")
                        part["arguments"] += (args if isinstance(args, str) else
                                              json.dumps(args) if args is not None else "")
                    if choice.get("finish_reason"):
                        finish = str(choice["finish_reason"])
            if finish is None:
                raise RuntimeError("llama-server stream ended without a finish reason")
            if parts:
                self.wfile.write(json.dumps({"model": payload["model"],
                    "message": {"role": "assistant", "content": "",
                                "tool_calls": _ollama_tool_calls_from_parts(parts)},
                    "done": False}, separators=(",", ":")).encode() + b"\n")
            predicted_ms = float(timings.get("predicted_ms") or 0)
            done = {"model": payload["model"], "message": {"role": "assistant", "content": ""},
                    "done": True, "done_reason": "length" if finish == "length" else "stop",
                    "prompt_eval_count": int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0),
                    "eval_count": int(usage.get("completion_tokens") or timings.get("predicted_n") or 0),
                    "eval_duration": int(predicted_ms * 1_000_000)}
            self.wfile.write(json.dumps(done, separators=(",", ":")).encode() + b"\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            # Headers are already sent: an NDJSON error, never a second HTTP
            # response or a successful final frame for an incomplete answer.
            try:
                self.wfile.write(json.dumps({"error": str(error)[:4000]}).encode() + b"\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass


def main() -> int:
    ENGINES.start_ollama()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    server.daemon_threads = True

    def stop(_sig: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def watch_ollama() -> None:
        while ENGINES.ollama is not None and ENGINES.ollama.poll() is None:
            time.sleep(1)
        log("private ollama daemon exited")
        server.shutdown()

    threading.Thread(target=watch_ollama, daemon=True).start()
    log(f"listening on {LISTEN_HOST}:{LISTEN_PORT}")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        ENGINES.stop()
    return 0 if ENGINES.ollama is None else int(ENGINES.ollama.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
