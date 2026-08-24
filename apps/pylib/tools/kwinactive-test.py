#!/usr/bin/env python3
"""Both halves of the KWin activation relay, without a window on his screen.

1. The RECEIVER owns `org.kde.lam.winactive.p<pid>` and turns a `setActive`
   call into `changed`/`active()`.
2. The KWin SCRIPT actually fires: it is (re)loaded and the `setActive` call it
   makes for whatever window is active at that moment is watched for on the
   bus. Nothing is activated, focused or clicked to provoke it — the script
   pushes the current state at load, which is the one beat that needs no
   interaction.

Run: `QT_QPA_PLATFORM=offscreen oracle-qtenv python3 kwinactive-test.py`
Needs a running KWin (a Plasma session); skips with 0 if there is none.
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kwinactive  # noqa: E402

SCRIPT = os.path.expanduser(
    "~/.local/share/kwin/scripts/winactive/contents/code/main.js")


def kwin(method, *args):
    cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin",
           "/Scripting", f"org.kde.kwin.Scripting.{method}"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def receiver_half():
    from PySide6.QtCore import QCoreApplication, QTimer
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    w = kwinactive.watcher()
    assert w is not None, "watcher() returned None — no session bus?"
    assert w.active() is None, "active() must start as None, not False"

    seen = []
    w.changed.connect(seen.append)
    name = kwinactive.SERVICE.format(pid=os.getpid())
    for value in ("true", "false", "false"):     # the repeat must not re-emit
        subprocess.run(["dbus-send", "--session", f"--dest={name}",
                        "--type=method_call", f"{kwinactive.PATH}",
                        f"{kwinactive.IFACE}.setActive", f"boolean:{value}"],
                       check=True, capture_output=True)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
            if seen and str(seen[-1]).lower() == value:
                break
    assert seen == [True, False], f"expected [True, False], got {seen}"
    assert w.active() is False
    print("receiver: ok")


def script_half():
    if not os.path.exists(SCRIPT):
        print("script: SKIP — not deployed (rebuild first)")
        return
    if kwin("isScriptLoaded", "string:winactive").returncode != 0:
        print("script: SKIP — no KWin on the session bus")
        return
    mon = subprocess.Popen(
        ["dbus-monitor", "--session", "interface='org.kde.lam.WinActive'"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        time.sleep(1)
        kwin("unloadScript", "string:winactive")
        kwin("loadScript", f"string:{SCRIPT}", "string:winactive")
        kwin("start")
        time.sleep(3)
    finally:
        mon.terminate()
    out = mon.stdout.read() if mon.stdout else ""
    assert "member=setActive" in out, (
        "the KWin script made no setActive call at load — is it enabled "
        "(kwinrc [Plugins] winactiveEnabled) and does `window.pid` still exist?")
    assert "org.kde.lam.winactive.p" in out, "call went to the wrong name"
    print("script: ok")


if __name__ == "__main__":
    if not shutil.which("dbus-send"):
        print("SKIP — no dbus-send")
        sys.exit(0)
    receiver_half()
    script_half()
    print("kwinactive: ok")
