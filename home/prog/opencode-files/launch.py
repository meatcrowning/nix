"""OpenCode's native Ollama adapter, with Chatter's backend/turn leases.

Book enters through ollama-tunnel.sh; top uses the same loopback services.
The per-process relay preserves NDJSON and tool calls without translating them.
"""
import contextlib
import http.client
import http.server
import json
import os
import select
import socket
import subprocess
import sys
import threading
import urllib.request
import uuid

MODEL = "thinkingmachines/Inkling-2-Mini:UD-Q4_K_XL"


def warden(path, **fields):
    body = json.dumps({"backend": "ollama", **fields}).encode()
    try:
        request = urllib.request.Request("http://127.0.0.1:8199/" + path,
                                         body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
    except OSError:
        # Match Chatter: a missing warden must not disable inference.
        return
    if not result.get("ok"):
        raise RuntimeError(result.get("reason", "ai-warden refused the request"))


@contextlib.contextmanager
def lease(acquire, renew, release, **fields):
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(5):
            try:
                warden(renew, **fields)
            except RuntimeError as error:
                print("opencode: " + str(error), file=sys.stderr)
    try:
        warden(acquire, **fields)
        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        yield
    finally:
        stopped.set()
        with contextlib.suppress(RuntimeError):
            warden(release, **fields)


class Relay(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        started = False
        upstream = http.client.HTTPConnection("127.0.0.1", 11434, timeout=3600)
        finished = threading.Event()
        # Closing OpenCode mid-prefill must release top's active generation.
        def watch_disconnect():
            while not finished.wait(0.25):
                try:
                    ready, _, _ = select.select([self.connection], [], [], 0)
                    if ready and not self.connection.recv(1, socket.MSG_PEEK):
                        if upstream.sock:
                            upstream.sock.shutdown(socket.SHUT_RDWR)
                        return
                except OSError:
                    return
        try:
            payload = json.loads(body)
            if payload.get("model") != MODEL:
                raise ValueError("This provider serves Inkling 2 Mini only")
            # Top allocates 32K, despite the model's advertised 1M context.
            payload.setdefault("options", {})["num_ctx"] = 32768
            with lease("reserve-owned", "renew-owned", "done-owned",
                       token=uuid.uuid4().hex, model=MODEL, lease=60):
                threading.Thread(target=watch_disconnect, daemon=True).start()
                upstream.request("POST", "/api/chat", json.dumps(payload),
                                 {"Content-Type": "application/json"})
                response = upstream.getresponse()
                self.send_response(response.status)
                self.send_header("Content-Type", response.getheader("Content-Type", "application/x-ndjson"))
                self.send_header("Connection", "close")
                self.end_headers()
                started = True
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, ValueError, RuntimeError, http.client.HTTPException) as error:
            if not started:
                with contextlib.suppress(OSError):
                    self.send_error(503, str(error))
        finally:
            finished.set()
            upstream.close()


def config(port):
    model = "top/" + MODEL
    return {
        "model": model, "small_model": model,
        "provider": {"top": {
            "name": "Inkling on top",
            "npm": "ollama-ai-provider-v2@3.6.0",
            "options": {"baseURL": f"http://127.0.0.1:{port}/api"},
            "models": {MODEL: {
                "name": "Inkling 2 Mini (top)", "tool_call": True,
                "limit": {"context": 32768, "output": 8192},
            }},
        }},
    }


def main():
    with lease("client/acquire", "client/renew", "client/release",
               client="opencode-" + uuid.uuid4().hex):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Relay)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            env = dict(os.environ, OPENCODE_CONFIG_CONTENT=json.dumps(config(server.server_port)))
            return subprocess.call(sys.argv[1:], env=env)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyboardInterrupt) as error:
        print("opencode: " + str(error), file=sys.stderr)
        sys.exit(1)
