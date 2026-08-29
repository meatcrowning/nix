#!/usr/bin/env python3
"""Exact failed/one-shot tool calls are reused; ordinary reads still rerun.

Pure in-process/offscreen: no server, subprocess, filesystem mutation or live
session. It drives the real main-agent round seam with a stub dispatcher.
"""
import json
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))
sys.argv = [sys.argv[0], "--selftest"]

from PySide6.QtGui import QGuiApplication  # noqa: E402
import main as oracle                      # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


o = oracle.Ollama()
o._set_busy(True)
o._messages = []
posts = []
o._post_chat = lambda: posts.append(True)
ran = []


def dispatch(name, args, idx, remaining, calls):
    ran.append((name, args))
    result = ({"error": "no such path"} if args.get("fail")
              else {"ok": True, "value": len(ran)})
    remaining["sink"][idx] = {
        "role": "tool", "tool_name": name, "content": json.dumps(result)}
    o._tool_done(remaining, calls)


o._dispatch_tool = dispatch


def call(name, args):
    o._run_tool_calls([{"function": {"name": name, "arguments": args}}])
    return json.loads(o._messages[-1]["content"])


call("read_file", {"path": "/missing", "fail": True})
again = call("read_file", {"path": "/missing", "fail": True})
check("an identical failed call runs once", len(ran) == 1)
check("the reused failure tells the model to change its arguments",
      again.get("reused") is True and "change the arguments" in again.get("note", ""))

call("read_file", {"path": "/changing"})
call("read_file", {"path": "/changing"})
check("a successful read still reruns for verification", len(ran) == 3)

call("edit_file", {"path": "/x", "old": "a", "new": "b"})
edited = call("edit_file", {"path": "/x", "old": "a", "new": "b"})
check("an identical successful mutation runs once", len(ran) == 4)
check("the mutation's completed result is reused", edited.get("reused") is True)
check("every completed round still advances the chat loop", len(posts) == 6)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
