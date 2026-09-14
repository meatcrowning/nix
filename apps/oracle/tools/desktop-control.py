#!/usr/bin/env python3
"""One JSON request on stdin to chatter's session desktop-control broker."""
import json, os, socket, sys

sock_path = os.environ.get("ORACLE_DESKTOP_CONTROL_SOCKET", "/run/user/%d/oracle-desktop-control.sock" % os.getuid())
try:
    request = json.load(sys.stdin)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(8)
        sock.connect(sock_path)
        sock.sendall(json.dumps(request).encode())
        data = sock.recv(65536)
    print(data.decode().strip())
except Exception as exc:
    print(json.dumps({"ok": False, "error": "desktop-control broker unavailable: " + str(exc)}))
