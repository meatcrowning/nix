#!/usr/bin/env python3
"""Grey a kitty terminal's foreground when its Hyprland window loses focus, so an
unfocused terminal matches the inactive tone filer and the hyprvtb titlebar fade
to (#595959).

kitty can't self-detect OS-window focus under Hyprland here — its
on_focus_change watcher never fires — so instead we listen to Hyprland's event
socket (socket2) and drive `kitty @ set-colors` on the terminal that lost or
gained focus. kitty must have remote control enabled with a pid-derived socket
(see kitty.conf: `allow_remote_control socket-only` + `listen_on
unix:$XDG_RUNTIME_DIR/kitty-{kitty_pid}`). Started from Hyprland's autostart so
it inherits the CURRENT session's HYPRLAND_INSTANCE_SIGNATURE (stale instances
leave sockets behind, so globbing would pick the wrong one)."""

import json
import os
import socket
import subprocess

INACTIVE = "#595959"  # == filer Theme.inactive / hyprvtb col.inactive
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")


def kitty_sock(pid):
    return f"unix:{RUNTIME}/kitty-{pid}"


def kitty_pid_at(addr):
    """pid of the kitty window at Hyprland address `addr`, else None."""
    if not addr:
        return None
    try:
        r = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=2)
        for w in json.loads(r.stdout):
            if w.get("address") == addr and w.get("class") == "kitty":
                return w.get("pid")
    except Exception:
        pass
    return None


def recolor(pid, focused):
    if not pid:
        return
    args = ["kitty", "@", "--to", kitty_sock(pid), "set-colors"]
    args += ["--reset"] if focused else [f"foreground={INACTIVE}"]
    try:
        subprocess.run(args, capture_output=True, timeout=2)
    except Exception:
        pass


def main():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise SystemExit("HYPRLAND_INSTANCE_SIGNATURE not set")
    path = f"{RUNTIME}/hypr/{sig}/.socket2.sock"

    s = socket.socket(socket.AF_UNIX)
    s.connect(path)

    prev = None  # pid of the kitty that currently holds focus (or None)
    buf = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode("utf-8", "replace")
            if not line.startswith("activewindowv2>>"):
                continue
            addr = line.split(">>", 1)[1].strip()
            if addr and not addr.startswith("0x"):
                addr = "0x" + addr
            new = kitty_pid_at(addr)
            if prev is not None and prev != new:
                recolor(prev, focused=False)  # the one losing focus greys
            if new is not None:
                recolor(new, focused=True)  # the one gaining focus restores
            prev = new


if __name__ == "__main__":
    main()
