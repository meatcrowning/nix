#!/usr/bin/env python3
"""Offscreen harness for viewer's two video-audio behaviours:

  1. **Nothing plays until the window has finished appearing.** hyprvtb fades
     its titlebar in and then rolls the window out; a clip that autoplayed at
     map time was already most of a second in, with its audio, behind a window
     still unrolling.
  2. **The `mu` titlebar toggle**, and that it is remembered across sessions.

**The clip it generates has NO AUDIO TRACK**, deliberately: this run must not
be able to make a sound on his speakers even if a decoder starts, and asserting
mute means asserting the `AudioOutput.muted` property rather than listening.
Nothing is on screen either — offscreen platform, no Wayland display.

    python3 apps/viewer/tools/video-test.py
"""
import importlib.util
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# split-test hardens the environment at import (offscreen, no WAYLAND_DISPLAY,
# a scratch XDG_CONFIG_HOME) and owns build().
_spec = importlib.util.spec_from_file_location("splittest", os.path.join(HERE, "split-test.py"))
splittest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(splittest)

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlExpression  # noqa: E402

import main as viewermain  # noqa: E402

build, check, spin, png = (splittest.build, splittest.check, splittest.spin, splittest.png)
SCRATCH = splittest.SCRATCH


def silent_clip(path, seconds=3):
    """A real video with no audio stream. Skips the whole run out loud if
    ffmpeg is missing rather than quietly asserting less."""
    argv = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:d=%d" % seconds,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", path]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print("SKIP: cannot build a test clip (%s)" % e)
        return None
    return path


def ask(engine, win, js):
    """Evaluate JS in the WINDOW's own QML scope and bring back a primitive.

    The pane is `win.current`, a QQuickItem* that PySide has no converter for,
    and a Repeater's delegates are not QObject-children of the window either —
    so the pane is read through the same bindings the chrome reads it through.
    (phone-test.py in filer does the same thing for a menu.)"""
    expr = QQmlExpression(engine.contextForObject(win), win, js)
    val = expr.evaluate()
    if expr.hasError():
        raise SystemExit("QML expression %r: %s" % (js, expr.error().toString()))
    return val[0] if isinstance(val, tuple) else val


def wait_for(fn, ms=4000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if fn():
            return True
        spin(50)
    return False


def buttons(win, ids=False):
    v = win.property("tbButtons")
    v = v.toVariant() if hasattr(v, "toVariant") else v
    return [(b.get("id"), b.get("label"), b.get("state"), b.get("tip")) for b in (v or [])]


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

    d = os.path.join(SCRATCH, "media")
    os.makedirs(d, exist_ok=True)
    clip = silent_clip(os.path.join(d, "clip.mp4"))
    if clip is None:
        return 0
    still = png(os.path.join(d, "a.png"), (20, 20, 20))
    entries = [{"name": "clip.mp4", "path": clip}, {"name": "a.png", "path": still}]

    engine, win, keep = build(app, entries, 0, 1)
    win.show()
    spin(150)
    pane = lambda js: ask(engine, win, "current." + js)

    print("\n== the opening reveal ==")
    check("the gate is shut when the window comes up",
          win.property("revealed") is False)
    check("...timed off the compositor's own reveal, not a literal",
          180 <= win.property("revealMs") <= 4160, win.property("revealMs"))
    check("the pane knows the video is one", pane("isVideo") is True)
    check("...and it is NOT playing yet", pane("videoPlaying") is False)

    # Well past the point a broken gate would have started it, and still short
    # of the real one, so this cannot pass by being too quick to look.
    spin(int(win.property("revealMs") * 0.6))
    check("still not playing partway through the reveal",
          pane("videoPlaying") is False)

    check("it starts once the window is out",
          wait_for(lambda: pane("videoPlaying") is True),
          (win.property("revealed"), pane("videoPlaying")))
    check("...and the gate says so", win.property("revealed") is True)

    print("\n== the mute toggle ==")
    check("a lone focused pane is audible to start with", pane("silent") is False)
    ids = [b[0] for b in buttons(win)]
    check("the titlebar offers `mute` on a video", "mute" in ids, ids)
    btn = [b for b in buttons(win) if b[0] == "mute"][0]
    check("...labelled `mu`, unlit, saying what a press does",
          btn[1] == "mu" and btn[2] == 0 and btn[3] == "mute", btn)

    # Pressed the way the compositor presses it — through the Titlebar bridge,
    # so Main.qml's own Connections are what run.
    keep[1].clicked.emit("mute")
    spin(120)
    check("pressing it silences the pane", pane("silent") is True)
    check("...and the window says it is muted", win.property("muted") is True)
    btn = [b for b in buttons(win) if b[0] == "mute"][0]
    check("...and the cell is LIT, offering the way back",
          btn[2] == 1 and btn[3] == "unmute", btn)
    check("muting does not pause it", pane("videoPlaying") is True)

    print("\n== remembered across sessions ==")
    check("it reached the prefs file", viewermain.Prefs().property("muted") is True)
    engine2, win2, keep2 = build(app, entries, 0, 1)
    win2.show()
    spin(250)
    check("a NEW window comes up muted", win2.property("muted") is True)
    check("...and so does its pane", ask(engine2, win2, "current.silent") is True)
    b2 = [b for b in buttons(win2) if b[0] == "mute"]
    check("...with the titlebar cell already lit", bool(b2) and b2[0][2] == 1, b2)

    keep2[1].clicked.emit("mute")
    spin(120)
    check("unmuting is remembered too",
          win2.property("muted") is False
          and viewermain.Prefs().property("muted") is False)

    print("\n== a still has nothing to mute ==")
    win.next()          # flip the pane to the png
    spin(150)
    ids = [b[0] for b in buttons(win)]
    check("no mute cell on an image", "mute" not in ids, ids)
    check("...and the zoom controls are back", "fit" in ids, ids)

    print("")
    if splittest.FAILS:
        print("%d failed: %s" % (len(splittest.FAILS), ", ".join(splittest.FAILS)))
        return 1
    print("video: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
