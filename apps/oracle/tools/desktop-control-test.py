#!/usr/bin/env python3
"""Hermetic desktop-control broker protocol test; never touches a real desktop."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path(__file__).resolve().parent


def call(sock, req):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock)); s.sendall(json.dumps(req).encode())
        return json.loads(s.recv(65536))


with tempfile.TemporaryDirectory(prefix="desktop-control-test-") as tmp:
    root = Path(tmp); apps = root / "apps"; apps.mkdir()
    (apps / "dummy.desktop").write_text("[Desktop Entry]\nType=Application\nExec=/bin/sleep 30\n")
    sock = root / "broker.sock"
    proc = subprocess.Popen([sys.executable, str(APP / "desktop-control-service.py"),
                             "--socket", str(sock), "--state", str(root / "state.json"),
                             "--desktop-dir", str(apps), "--no-window-probe"])
    child = None
    try:
        for _ in range(50):
            if sock.exists(): break
            time.sleep(.02)
        assert sock.exists(), "broker did not create its socket"
        launched = call(sock, {"action": "launch", "app": "dummy", "wait": 0})
        assert launched["ok"] and launched["state"] == "process_running_no_window", launched
        child = int(launched["pid"])
        inspect = call(sock, {"action": "inspect", "handle": launched["handle"]})
        assert inspect["owned"] and inspect["pid"] == child, inspect
        refused = call(sock, {"action": "close", "handle": launched["handle"]})
        assert not refused["ok"] and "unsaved work" in refused["error"], refused
        print("ok: persistent process is never misreported as a window")
    finally:
        if child:
            try: os.killpg(child, signal.SIGTERM)
            except OSError: pass
        proc.terminate(); proc.wait(timeout=3)
