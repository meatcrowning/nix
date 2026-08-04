#!/usr/bin/env python3
"""Stream Hyprland's client list to the panel — one line per CHANGE.

WHY THIS EXISTS. WinState reads `hyprctl clients` once a second, which sets the
pace of everything the panel draws against a window. That is too slow for the
notch's seam, and the reason is not tuning: hyprvtb's maximize is a plain
resize+move on a floating window (vtbDeco.cpp's toggleMaximize), and HYPRLAND
EMITS NO EVENT FOR A GEOMETRY CHANGE — so the one transition the seam exists for
was invisible to the event socket and waited on the poll tick. [his] "it seems
only sometimes does it happen as quick as it needs to."

Polling five times a second is the answer; three process spawns five times a
second is not. This asks Hyprland's own request socket, which costs a connect
and a read, and prints the reply ONLY when it differs from the last one — so a
still desktop is silent and the panel parses nothing. Quickshell's own Socket
type would do the request in QML, but Hyprland closes the connection after every
reply and that logs a PeerClosedError warning each time: five lines a second
into the log the panel is diagnosed from.

The instance is resolved the way `hypr-session-env.sh` does it — the environment
variable if its socket is really there, otherwise the live lock file — because a
user unit's inherited HYPRLAND_INSTANCE_SIGNATURE can name a compositor that
exited an hour ago (see home/srvs/hypr-env.nix).
"""

import glob
import hashlib
import os
import socket
import sys
import time

# 120ms: measured at 0.3% of a core at 200ms, and the seam wants to land
# inside the 260ms maximize animation rather than after it.
INTERVAL = float(os.environ.get("WIN_WATCH_INTERVAL", "0.12"))


def socket_path():
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if sig:
        p = f"{rt}/hypr/{sig}/.socket.sock"
        if os.path.exists(p):
            return p
    for lock in sorted(glob.glob(f"{rt}/hypr/*/hyprland.lock")):
        p = os.path.join(os.path.dirname(lock), ".socket.sock")
        if os.path.exists(p):
            return p
    return None


def ask(path, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        s.connect(path)
        s.sendall(command.encode())
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    return b"".join(chunks)


def main():
    last = None
    while True:
        path = socket_path()
        if not path:
            time.sleep(1.0)
            continue
        try:
            out = ask(path, "j/clients")
        except OSError:
            # The compositor went away or is mid-restart: back off rather than
            # spin, and re-resolve the instance on the next pass.
            time.sleep(1.0)
            continue
        digest = hashlib.blake2b(out, digest_size=8).digest()
        if digest != last:
            last = digest
            # One line, so the reader can split on newlines.
            sys.stdout.write(out.decode("utf-8", "replace").replace("\n", " ") + "\n")
            sys.stdout.flush()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
