#!/usr/bin/env python3
"""`continue` is a state of the SEND BUTTON, in both faces.

It belongs on the button beside the prompt box, not under the bubble [his,
2026-08-23], so this drives the real window offscreen (`--selftest ORACLE_FAKE`,
whose demo log ends on a finished assistant turn) and reads the button's label
back in each face:

  * nothing typed, a finished reply at the bottom  -> `continue`
  * something typed                                -> `send` (a prompt he wrote
    outranks carrying the last answer on)

Nothing reaches his screen (QT_QPA_PLATFORM=offscreen, set by --selftest's own
harness path), no model is loaded and no session is written.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


def run(face):
    """One offscreen selftest run in `face`, as its printed compose lines."""
    env = dict(os.environ)
    env["ORACLE_FAKE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    if face == "plasma":
        env["XDG_CURRENT_DESKTOP"] = "KDE"
        env["QT_QPA_PLATFORMTHEME"] = "kde"
        env["DESK_SESSION"] = "plasma"
    else:
        env["XDG_CURRENT_DESKTOP"] = "Hyprland"
        env.pop("QT_QPA_PLATFORMTHEME", None)
        env.pop("DESK_SESSION", None)
    out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                         env=env, capture_output=True, text=True, timeout=180)
    return out.stdout + out.stderr


for face, cont, send in (("hypr", "continue", "send"),
                         ("plasma", "Continue", "Send")):
    txt = run(face)
    got_face = re.search(r"compose face: (\S+)", txt)
    idle = re.search(r"compose: canContinue=(\w+) label='([^']*)'", txt)
    typed = re.search(r"compose typed: canSend=(\w+) label='([^']*)'", txt)
    check("%s: the face under test is the right one" % face,
          got_face is not None and got_face.group(1) == face,
          got_face.group(1) if got_face else txt[-300:])
    check("%s: a finished reply makes the button offer continue" % face,
          idle is not None and idle.group(1) == "True" and idle.group(2) == cont,
          idle.group(0) if idle else txt[-300:])
    check("%s: a typed prompt takes the button back to send" % face,
          typed is not None and typed.group(1) == "True" and typed.group(2) == send,
          typed.group(0) if typed else txt[-300:])
    check("%s: and the window still loads clean" % face,
          "0 QML warning(s)" in txt, txt[-200:])

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
