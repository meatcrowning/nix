#!/usr/bin/env python3
"""Headless check of surfer's split view — `apps/surfer/tools/split-test.py`.

Runs surfer offscreen in a scratch HOME with a scratch XDG_RUNTIME_DIR, and
plays the part of the hyprvtb button server: we read its REGISTER lines (the
whole button set, with per-tab tooltips that name each pane) and send CLICK
lines back. No screen, no network, no second panel — tabs are about:blank and
nothing touches the user's own session.

The tooltips are the assertion surface: they say which pane a tab is in and
whether that pane has the chrome, so pane assignment, focus, the close-fold and
the toggle are all checkable without a screen. Appearance (divider, focus frame,
page layout) is the user's visual check, not this script's.

Run it after touching the split-view block in qml/Main.qml. It launches the
PACKAGED wrapper, so QtWebEngine gets its Qt env; needs no rebuild.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

# the packaged wrapper, so QtWebEngine gets the Qt env it needs (it execs the
# same live main.py)
SURFER = shutil.which("surfer") or "/home/lam/nix/apps/surfer/main.py"

root = Path(tempfile.mkdtemp(prefix="surfer-split-"))
home = root / "home"
rt = root / "run"
state = home / ".local" / "state"
for p in (home, rt, state / "surfer", home / "Downloads", home / ".cache"):
    p.mkdir(parents=True, exist_ok=True)
rt.chmod(0o700)

(state / "surfer" / "session.json").write_text(json.dumps({
    "tabs": ["about:blank#a", "about:blank#b", "about:blank#c"],
    "current": 0,
}))

sockpath = rt / "hyprvtb-buttons.sock"
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(str(sockpath))
srv.listen(1)

env = dict(os.environ)
env.update(HOME=str(home), XDG_RUNTIME_DIR=str(rt), XDG_STATE_HOME=str(state),
           XDG_CACHE_HOME=str(home / ".cache"), XDG_DATA_HOME=str(home / ".local/share"),
           XDG_CONFIG_HOME=str(home / ".config"),
           QT_QPA_PLATFORM="offscreen", SURFER_NO_SINGLETON="1", SURFER_NO_SYNC="1",
           QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --disable-dev-shm-usage")
env.pop("SURFER_SOCKET", None)

log = open(root / "surfer.log", "wb")
proc = subprocess.Popen([SURFER], env=env, stdout=log, stderr=log)

srv.settimeout(60)
try:
    conn, _ = srv.accept()
except socket.timeout:
    proc.kill()
    log.close()
    sys.stdout.write((root / "surfer.log").read_text(errors="replace")[-3000:])
    raise SystemExit("surfer never connected to the button socket")
conn.settimeout(0.5)

buf = b""
last = {"buttons": None, "seq": 0}
lock = threading.Lock()


def decode(s):
    return urllib.parse.unquote(s)


def parse(line):
    body = line.split(" ", 2)[2] if line.count(" ") >= 2 else ""
    out = []
    for part in body.split("|"):
        f = part.split(":")
        if f[0] == "-":
            out.append({"id": "-"})
            continue
        out.append({"id": decode(f[0]), "label": decode(f[1]), "state": int(f[2]),
                    "tip": decode(f[3]) if len(f) > 3 else ""})
    return out


def reader():
    global buf
    while proc.poll() is None:
        try:
            data = conn.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            return
        if not data:
            return
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("utf-8", "replace")
            if text.startswith("REGISTER "):
                with lock:
                    last["buttons"] = parse(text)
                    last["seq"] += 1


threading.Thread(target=reader, daemon=True).start()


def buttons(timeout=20.0, settle=0.8):
    """The SETTLED button set: the latest REGISTER, once no newer one has
    arrived for `settle` seconds (the set is re-pushed several times as the
    tabs and their titles come up)."""
    end = time.time() + timeout
    seen = None
    quiet = 0.0
    while time.time() < end:
        with lock:
            cur = last["seq"]
            bs = last["buttons"]
        if bs is not None and cur == seen:
            quiet += 0.1
            if quiet >= settle:
                return bs, cur
        else:
            seen, quiet = cur, 0.0
        time.sleep(0.1)
    raise SystemExit("timed out waiting for a REGISTER (surfer log: %s)" % (root / "surfer.log"))


def click(bid):
    conn.sendall(("CLICK %s\n" % bid).encode())
    time.sleep(0.3)
    return buttons()[0]


def tabs(bs):
    return [b for b in bs if b["id"].startswith("tab:")]


fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)


try:
    bs, _ = buttons()
    ids = [b["id"] for b in bs]
    print("buttons:", ids)
    check("split button exists, unlit", ("split" in ids) and
          [b for b in bs if b["id"] == "split"][0]["state"] == 0)
    t = tabs(bs)
    check("3 tabs restored", len(t) == 3, str(len(t)))
    check("only tab0 lit before split",
          [b["state"] for b in t] == [1, 0, 0], str([b["state"] for b in t]))
    check("tab0 tip is the plain close tip", t[0]["tip"].startswith("close · "), t[0]["tip"])
    tid = [b["id"] for b in t]

    # --- open the split ---
    bs = click("split")
    t = tabs(bs)
    check("split lit", [b for b in bs if b["id"] == "split"][0]["state"] == 1)
    check("two tabs on screen", [b["state"] for b in t] == [1, 1, 0], str([b["state"] for b in t]))
    check("tab0 is the left pane, unfocused", t[0]["tip"].startswith("focus · left · "), t[0]["tip"])
    check("tab1 is the right pane, focused", t[1]["tip"].startswith("close · right · "), t[1]["tip"])

    # --- click the left pane's tab: focus moves, nothing swaps ---
    bs = click(tid[0])
    t = tabs(bs)
    check("clicking the other pane's tab focuses it, no swap",
          t[0]["tip"].startswith("close · left · ") and t[1]["tip"].startswith("focus · right · "),
          t[0]["tip"] + " / " + t[1]["tip"])

    # --- click an off-screen tab: it lands in the FOCUSED (left) pane ---
    bs = click(tid[2])
    t = tabs(bs)
    check("a hidden tab opens in the focused pane",
          t[2]["tip"].startswith("close · left · ") and t[0]["state"] == 0
          and t[1]["tip"].startswith("focus · right · "),
          str([(b["state"], b["tip"][:24]) for b in t]))

    # --- new tab goes to the focused pane, and the right pane is untouched ---
    bs = click("newtab")
    t = tabs(bs)
    check("newtab lands in the focused pane", len(t) == 4 and t[3]["tip"].startswith("close · left · "),
          str([(b["state"], b["tip"][:22]) for b in t]))
    check("right pane still tab1", t[1]["tip"].startswith("focus · right · "), t[1]["tip"])

    # --- close the right pane's tab: the split survives on another tab ---
    tid = [b["id"] for b in t]
    bs = click(tid[1])            # focus it
    t = tabs(bs)
    check("right pane focused before closing", t[1]["tip"].startswith("close · right · "), t[1]["tip"])
    bs = click(tid[1])            # close it
    t = tabs(bs)
    lit = [b for b in t if b["state"] == 1]
    check("closing a pane's tab keeps the split", len(t) == 3 and len(lit) == 2,
          str([(b["id"], b["state"], b["tip"][:22]) for b in t]))
    check("split still lit", [b for b in bs if b["id"] == "split"][0]["state"] == 1)

    # --- close down to one tab: the split folds by itself ---
    tid = [b["id"] for b in t]
    right = [b for b in t if "right · " in b["tip"]][0]
    bs = click(right["id"])       # focus the right pane
    bs = click(right["id"])       # close it -> 2 tabs, still split
    t = tabs(bs)
    right = [b for b in t if "right · " in b["tip"]][0]
    bs = click(right["id"])
    bs = click(right["id"])       # close it -> 1 tab left, nothing to split with
    t = tabs(bs)
    check("split folds when only one tab is left",
          len(t) == 1 and [b for b in bs if b["id"] == "split"][0]["state"] == 0,
          str([(b["id"], b["tip"]) for b in t]) + " split=" +
          str([b for b in bs if b["id"] == "split"][0]["state"]))

    # --- re-open with a single tab: it must make one to split with ---
    bs = click("split")
    t = tabs(bs)
    check("split with one tab creates the second", len(t) == 2 and
          [b["state"] for b in t] == [1, 1], str([(b["state"], b["tip"][:22]) for b in t]))

    # --- toggle off ---
    bs = click("split")
    t = tabs(bs)
    check("split off leaves one pane",
          [b for b in bs if b["id"] == "split"][0]["state"] == 0 and
          sum(1 for b in t if b["state"] == 1) == 1,
          str([(b["state"], b["tip"][:22]) for b in t]))
    check("tips lose the pane names", all("left · " not in b["tip"] and "right · " not in b["tip"]
                                          for b in t), str([b["tip"] for b in t]))

    # (the session/prefs round trip is checked separately — saveSession only
    #  runs from Window.onClosing, which a SIGTERM never reaches)
finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    log.close()
    if fails:
        print("\n--- surfer stderr tail ---")
        sys.stdout.write((root / "surfer.log").read_text(errors="replace")[-3000:])
    print("\nscratch:", root)

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
