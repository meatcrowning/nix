#!/usr/bin/env python3
"""kitty ↔ hyprvtb titlebar buttons.

Launched inside every kitty instance by the startup session
(~/.config/kitty/vtb.session: `launch --type=background`). kitty normally
hands us KITTY_LISTEN_ON — the per-instance remote-control socket from
kitty.conf's `listen_on unix:/run/user/1000/kitty-{kitty_pid}` — but
compositor-spawned kitties have been seen NOT injecting it into session
children, so we fall back to deriving the socket from our parent PID (a
background launch is a direct child of its kitty) and wait for the socket
file to appear. Every click maps to `kitten @ --to <socket>` against this
instance's active window.

Logs to ~/.local/state/vtb/kitty-vtb.log (tiny, self-truncating) so a
silently-missing button column is diagnosable the morning after.

Runs from the live repo (~/nix/pylib), stdlib only — edits apply to the next
kitty you open, no rebuild.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vtbclient import VtbClient  # noqa: E402

LOG = os.path.expanduser("~/.local/state/vtb/kitty-vtb.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 65536:
            os.truncate(LOG, 0)
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


def find_listen():
    listen = os.environ.get("KITTY_LISTEN_ON", "")
    if listen:
        return listen, "env"
    # fallback: our parent is the kitty that background-launched us
    ppid = os.getppid()
    return f"unix:/run/user/{os.getuid()}/kitty-{ppid}", f"ppid {ppid}"


LISTEN, HOW = find_listen()
try:
    KITTY_PID = int(LISTEN.rsplit("-", 1)[1])
except (ValueError, IndexError):
    log(f"cannot parse kitty pid from {LISTEN!r} ({HOW}) — exiting")
    sys.exit(0)


def k(*args):
    """Fire a remote-control command at our kitty; failures are non-fatal
    (e.g. a split command while an overlay is up just does nothing)."""
    try:
        subprocess.run(["kitten", "@", "--to", LISTEN, *args],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


# id -> (label, tooltip, action). Splits force the `splits` layout first so
# --location always means what the button says, whatever layout was active.
ACTIONS = {
    "vsplit": ("|",  "split right", lambda: (k("goto-layout", "splits"),
                                             k("launch", "--location=vsplit", "--cwd=current"))),
    "hsplit": ("-",  "split down",  lambda: (k("goto-layout", "splits"),
                                             k("launch", "--location=hsplit", "--cwd=current"))),
    "zoom":   ("z",  "zoom split (stack layout)", lambda: k("action", "toggle_layout", "stack")),
    "closew": ("xw", "close split", lambda: k("close-window")),
    "copy":   ("cp", "copy selection", lambda: k("action", "copy_to_clipboard")),
    "paste":  ("p",  "paste clipboard", lambda: k("action", "paste_from_clipboard")),
    "newtab": ("+t", "new tab",     lambda: k("launch", "--type=tab", "--cwd=current")),
    "nexttab": (">t", "next tab",   lambda: k("action", "next_tab")),
    "scroll": ("sb", "scrollback pager", lambda: k("action", "show_scrollback")),
}

# titlebar order: splits/zoom/close · copy/paste · tabs · scrollback.
# One uniform column, no group spacers (the grid reads cleaner without them).
LAYOUT = ["vsplit", "hsplit", "zoom", "closew",
          "copy", "paste",
          "newtab", "nexttab",
          "scroll"]


def on_click(bid):
    act = ACTIONS.get(bid)
    if act:
        act[2]()


def main():
    # kitty creates the listen socket shortly after startup; a session
    # background child can win that race, so wait for it (30s cap)
    sock_path = LISTEN.split("unix:", 1)[-1]
    for _ in range(60):
        if os.path.exists(sock_path):
            break
        if not os.path.exists(f"/proc/{KITTY_PID}"):
            log(f"kitty {KITTY_PID} died before its socket appeared — exiting")
            sys.exit(0)
        time.sleep(0.5)
    else:
        log(f"socket {sock_path} never appeared ({HOW}) — exiting")
        sys.exit(0)

    log(f"registering for kitty {KITTY_PID} (listen via {HOW})")
    client = VtbClient(on_click=on_click, pid=KITTY_PID)
    client.set_buttons([b if b == "-" else (b, ACTIONS[b][0], 0, ACTIONS[b][1]) for b in LAYOUT])

    # The VtbClient reader runs on a daemon thread; this thread just watches
    # for our kitty to die and exits with it — otherwise one of us would leak
    # per kitty launch and hold a stale registration open.
    while os.path.exists(f"/proc/{KITTY_PID}"):
        time.sleep(10)
    log(f"kitty {KITTY_PID} gone — exiting")


if __name__ == "__main__":
    main()
