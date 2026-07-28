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
import select
import socket
import subprocess
import time

INACTIVE = "#595959"  # == filer Theme.inactive / hyprvtb col.inactive

# How long "focus is on NOTHING" has to last before we believe it.
#
# On this desktop that state is almost always a 3 ms pothole, not a
# destination: whenever a layer surface hands the keyboard back — the task
# manager's filter box being the only thing that takes it — Hyprland's
# `refocusLastWindow` clears the focus and *then* re-focuses the window, so the
# socket carries `activewindowv2>>` (empty) immediately followed by the same
# window it had before.
#
# Acting on the empty one turns those 3 ms into a visible flash, because our
# reaction is not free: `kitty @ set-colors` is a subprocess, and resolving the
# next event costs an `hyprctl -j clients` on top. Measured end to end in a
# nested Hyprland — a 3.5 ms gap on the wire became **38 ms of grey text** in
# kitty and back. That is the flash, and it is ours, not the compositor's:
# hyprvtb's titlebar and Hyprland's border flip on the same 3.5 ms boundary and
# cannot produce a frame.
#
# So wait this long before greying anything. If a real window turns up first
# the pothole never happened; if it doesn't, focus genuinely has settled on
# nothing and the dim lands a sixth of a second late, which nobody can see.
NOTHING_GRACE = 0.15
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
THEME_CONF = os.path.expanduser("~/.config/kitty/theme.conf")  # written by wal-set.sh


def kitty_sock(pid):
    return f"unix:{RUNTIME}/kitty-{pid}"


def focused_fg():
    """The focused foreground = theme.conf's `foreground` (the wallpaper accent,
    rewritten by wal-set.sh on every theme switch). We restore focus by setting
    this explicitly rather than `set-colors --reset`: --reset implies
    --configured, which rewrites kitty's *configured* defaults to the values
    they had at STARTUP — after that a live config reload (wal-set.sh's SIGUSR1)
    can no longer change kitty's colors, so a theme switch would leave the text
    stuck on the old palette. A plain foreground= override touches only the live
    window and IS superseded by the next reload, so themes keep working."""
    try:
        with open(THEME_CONF) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "foreground":
                    return parts[1]
    except OSError:
        pass
    return None


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
    if focused:
        fg = focused_fg()
        # fall back to --reset only if theme.conf is unreadable (better a
        # possibly-stale colour than leaving the window greyed)
        color = f"foreground={fg}" if fg else "--reset"
    else:
        color = f"foreground={INACTIVE}"
    args = ["kitty", "@", "--to", kitty_sock(pid), "set-colors", color]
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
    # Set when the socket says focus is on NOTHING; cleared by the next event
    # that names a window. Only if it survives NOTHING_GRACE do we act on it.
    pending_nothing = None
    buf = b""
    while True:
        timeout = None
        if pending_nothing is not None:
            timeout = max(0.0, NOTHING_GRACE - (time.monotonic() - pending_nothing))
        if not select.select([s], [], [], timeout)[0]:
            # The grace ran out with no window turning up: focus really has
            # settled on nothing, so do what the empty event asked for.
            if prev is not None:
                recolor(prev, focused=False)
            prev = None
            pending_nothing = None
            continue
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
            if not addr:
                # Focus on nothing. Distinguished from "focused a window that
                # isn't kitty" — which still resolves to a None pid below and
                # must still grey immediately — because only this one is the
                # transient. Start the clock and say nothing yet.
                if pending_nothing is None:
                    pending_nothing = time.monotonic()
                continue
            pending_nothing = None
            if not addr.startswith("0x"):
                addr = "0x" + addr
            new = kitty_pid_at(addr)
            if prev is not None and prev != new:
                recolor(prev, focused=False)  # the one losing focus greys
            if new is not None:
                recolor(new, focused=True)  # the one gaining focus restores
            prev = new


if __name__ == "__main__":
    main()
