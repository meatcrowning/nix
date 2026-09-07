#!/usr/bin/env python3
"""Temp-only wire test for the DeskStyle custom-app participant protocol."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from styleparticipant import (PROTOCOL_VERSION, encode_record, runtime_dir,
                              send_record, socket_path)  # noqa: E402

fails = []


def check(name, condition):
    print(("  ok   " if condition else "  FAIL ") + name)
    if not condition:
        fails.append(name)


register = encode_record("register", participant="player", pid=42)
parsed = json.loads(register)
check("register carries the protocol version", parsed["version"] == PROTOCOL_VERSION)
check("records are newline framed", register.endswith(b"\n"))
check("register carries an explicit pid", parsed["pid"] == 42)

ack = encode_record("acknowledge", participant="chatter", generation=9,
                    profileHash="a" * 64)
check("ack carries exact profile identity", json.loads(ack)["profileHash"] == "a" * 64)

with tempfile.TemporaryDirectory(prefix="styleparticipant-test-") as temporary:
    runtime = Path(temporary) / "runtime"
    runtime.mkdir()
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    endpoint = socket_path()
    endpoint.parent.mkdir(mode=0o700)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(endpoint))
    server.listen(1)
    received = []

    def accept_one():
        connection, _ = server.accept()
        with connection:
            received.append(connection.recv(4096))

    worker = threading.Thread(target=accept_one)
    worker.start()
    check("socket path is beneath the per-login runtime directory", endpoint.parent == runtime_dir() / "deskstyle")
    check("best-effort send reaches a listening controller", send_record(ack))
    worker.join(timeout=1)
    server.close()
    check("controller receives the exact one-line acknowledgement", received == [ack])

check("absent controller is harmless", not send_record(register, Path("/nonexistent/deskstyle.sock")))

if fails:
    print(f"styleparticipant-test: {len(fails)} failure(s)", file=sys.stderr)
    raise SystemExit(1)
print("styleparticipant-test: all checks passed")
