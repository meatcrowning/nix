#!/usr/bin/env python3
"""Retain real Slsk states against a private fake slskd, entirely offscreen."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import unquote, urlsplit


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "normal"
        self.searches = {}
        self.next_id = 0

    def search(self, query):
        with self.lock:
            self.mode = "stress" if query == "fixture-stress" else "normal"
            self.next_id += 1
            sid = f"fixture-{self.next_id}"
            self.searches[sid] = self.mode
            return sid


STATE = State()


def search_responses(mode):
    peers = 80 if mode == "stress" else 8
    files = 20 if mode == "stress" else 6
    return [
        {
            "username": f"fixture-user-{peer:03d}",
            "hasFreeUploadSlot": peer % 3 == 0,
            "files": [
                {
                    "filename": rf"collection-{peer:03d}\album-{item // 10:02d}\track-{item:03d}.flac",
                    "size": 18_000_000 + peer * 4096 + item * 1024,
                    "bitRate": 1000 + item,
                    "length": 180 + item,
                    "queueState": "None",
                }
                for item in range(files)
            ],
        }
        for peer in range(peers)
    ]


def transfers(mode):
    users = 30 if mode == "stress" else 4
    files = 12 if mode == "stress" else 5
    return [
        {
            "username": f"download-user-{user:03d}",
            "directories": [
                {
                    "directory": rf"library\album-{user:03d}",
                    "files": [
                        {
                            "id": f"transfer-{user:03d}-{item:03d}",
                            "filename": rf"library\album-{user:03d}\song-{item:03d}.flac",
                            "size": 24_000_000,
                            "bytesTransferred": (item * 1_700_000) % 24_000_000,
                            "state": "InProgress",
                            "averageSpeed": 1_200_000 + item * 4096,
                        }
                        for item in range(files)
                    ],
                }
            ],
        }
        for user in range(users)
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "fixture-slskd"

    def log_message(self, _format, *_args):
        pass

    def body(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"null")

    def reply(self, value=None, status=200):
        raw = b"" if value is None else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authenticated(self):
        if self.headers.get("X-API-Key") != "fixture-key":
            self.reply({"error": "bad fixture key"}, 403)
            return False
        return True

    def do_GET(self):
        if not self.authenticated():
            return
        path = urlsplit(self.path).path
        if path == "/api/v0/application":
            self.reply({"server": {"isLoggedIn": True, "state": "Connected"},
                        "user": {"username": "fixture"},
                        "version": {"full": "fixture"}})
        elif path == "/api/v0/transfers/downloads":
            with STATE.lock:
                mode = STATE.mode
            self.reply(transfers(mode))
        elif path.startswith("/api/v0/searches/") and path.endswith("/responses"):
            sid = path.split("/")[-2]
            with STATE.lock:
                mode = STATE.searches.get(sid, "normal")
            self.reply(search_responses(mode))
        elif path.startswith("/api/v0/searches/"):
            self.reply({"state": "Completed"})
        else:
            self.reply({"error": "unknown fixture route"}, 404)

    def do_POST(self):
        if not self.authenticated():
            return
        path = urlsplit(self.path).path
        if path == "/api/v0/searches":
            body = self.body()
            self.reply({"id": STATE.search(str((body or {}).get("searchText", "")))})
        elif path.startswith("/api/v0/transfers/downloads/"):
            unquote(path.rsplit("/", 1)[-1])
            self.body()
            self.reply(None, 204)
        else:
            self.reply({"error": "unknown fixture route"}, 404)

    def do_DELETE(self):
        if not self.authenticated():
            return
        self.reply(None, 204)


def clean_qt_env(env):
    if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
            env.pop(key, None)
        env["QT_QPA_PLATFORMTHEME"] = ""
        env["QT_STYLE_OVERRIDE"] = ""


def main():
    repo = Path(__file__).resolve().parents[3]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="slsk-resource-") as tmp:
            root = Path(tmp)
            for name in ("runtime", "home"):
                (root / name).mkdir(mode=0o700)
            key = root / "api-key"
            key.write_text("fixture-key")
            env = os.environ.copy()
            env.update({
                "QT_QPA_PLATFORM": "offscreen",
                "SLSK_RESOURCE_FIXTURE": "1",
                "SLSK_API_URL": f"http://127.0.0.1:{server.server_port}",
                "SLSK_API_KEY_FILE": str(key),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_RUNTIME_DIR": str(root / "runtime"),
                "HOME": str(root / "home"),
            })
            for name in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
                env.pop(name, None)
            clean_qt_env(env)
            subprocess.run(
                ["bash", "-c", f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'],
                check=True, env=env,
            )
            child = subprocess.Popen([sys.executable, str(repo / "apps/slsk/main.py")], env=env)
            rc = child.wait()
            if child.poll() is None:
                raise RuntimeError("slsk resource child survived teardown")
            return rc
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
