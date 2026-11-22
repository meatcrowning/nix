"""Isolated relay checks: no SSH, warden, model, or desktop access."""
import contextlib
import http.client
import http.server
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("launch", Path(__file__).with_name("launch.py"))
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
HTTPConnection = http.client.HTTPConnection


class Backend(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.server.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.server.entered.set()
        self.server.unblock.wait(5)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(self.server.reply)


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        self.backend.requests = []
        self.backend.entered = threading.Event()
        self.backend.unblock = threading.Event()
        self.backend.unblock.set()
        self.backend.reply = b'{"message":{"tool_calls":[{"function":{"name":"read","arguments":{"path":"a"}}}]},"done":false}\n{"done":true}\n'
        self.relay = http.server.ThreadingHTTPServer(("127.0.0.1", 0), launch.Relay)
        for server in (self.backend, self.relay):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.calls = []
        self.refuse = False
        def warden(path, **fields):
            self.calls.append((path, fields))
            if self.refuse and path == "reserve-owned":
                raise RuntimeError("painter is busy")
        self.warden = patch.object(launch, "warden", warden)
        self.connection = patch.object(launch.http.client, "HTTPConnection",
            lambda *_args, **_kw: HTTPConnection("127.0.0.1", self.backend.server_port))
        self.warden.start()
        self.connection.start()

    def tearDown(self):
        self.connection.stop()
        self.warden.stop()
        for server in (self.relay, self.backend):
            server.shutdown()
            server.server_close()

    def request(self, model=launch.MODEL):
        with contextlib.closing(HTTPConnection("127.0.0.1", self.relay.server_port, timeout=5)) as connection:
            connection.request("POST", "/api/chat", json.dumps({
                "model": model, "messages": [{"role": "user", "content": "test"}],
                "tools": [{"type": "function", "function": {"name": "read"}}],
                "stream": True,
            }))
            response = connection.getresponse()
            return response.status, response.read()

    def test_stream_tools_and_owned_reservation(self):
        status, data = self.request()
        self.assertEqual((status, data), (200, self.backend.reply))
        self.assertEqual(self.backend.requests[0]["options"]["num_ctx"], 32768)
        self.assertEqual(self.backend.requests[0]["tools"][0]["function"]["name"], "read")
        self.assertEqual([x[0] for x in self.calls], ["reserve-owned", "done-owned"])
        self.assertEqual(self.calls[0][1]["token"], self.calls[1][1]["token"])

    def test_refusal_never_reaches_backend(self):
        self.refuse = True
        status, data = self.request()
        self.assertEqual(status, 503)
        self.assertIn(b"painter is busy", data)
        self.assertEqual(self.backend.requests, [])

    def test_unknown_model_never_reaches_backend(self):
        self.assertEqual(self.request("other")[0], 503)
        self.assertEqual(self.backend.requests, [])
        self.assertEqual(self.calls, [])

    def test_parallel_title_and_main_are_serialized(self):
        self.backend.unblock.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request)
            self.assertTrue(self.backend.entered.wait(3))
            second = pool.submit(self.request)
            # A second request must not reach inference or reserve resources
            # while the first still owns the stream.
            self.assertFalse(threading.Event().wait(0.4))
            try:
                self.assertEqual(len(self.backend.requests), 1)
                self.assertEqual([x[0] for x in self.calls], ["reserve-owned"])
            finally:
                self.backend.unblock.set()
            self.assertEqual(first.result(timeout=3)[0], 200)
            self.assertEqual(second.result(timeout=3)[0], 200)
        self.assertEqual([x[0] for x in self.calls],
                         ["reserve-owned", "done-owned", "reserve-owned", "done-owned"])

    def test_cancelled_queue_entry_never_acquires_lease(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(ConnectionAbortedError):
            with launch.request_slot(cancelled):
                self.fail("Cancelled request was admitted")
        self.assertFalse(launch.REQUEST_SLOT.locked())


if __name__ == "__main__":
    unittest.main()
