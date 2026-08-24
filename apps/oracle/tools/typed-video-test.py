#!/usr/bin/env python3
"""A video the reply NAMED but never called for is drawn anyway.

Offscreen, no network: `_show_video` is stubbed, so nothing reaches YouTube and
no resolver runs. This covers the gap he hit on 2026-08-23 — the model wrote
`{{show_video|https://…}}` into its prose instead of calling the tool, and the
window drew nothing: *"it seems something happaned to where the video was not
shown inline like how it should"*.

  * a `{{show_video|url}}` marker draws the card AND leaves the bare URL in the
    prose, through `replyBodyFixed`
  * a video URL the model merely mentioned is drawn too, prose untouched
  * a video the TOOL already drew this turn is not drawn twice
  * the cap holds, and an ordinary reply is left completely alone
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

from PySide6.QtGui import QGuiApplication               # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                   # noqa: E402

app = QGuiApplication([])
o = oracle.Ollama()

fails = []
SHOWN = []
FIXED = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# The one thing that would reach the network, stubbed — it still registers the
# URL exactly as the real one does, which is what the "not twice" check needs.
def fake_show_video(url, alt, idx, remaining, calls):
    SHOWN.append(url)
    o._videos_shown.add(url)


o._show_video = fake_show_video
o.replyBodyFixed.connect(FIXED.append)


def run(text):
    SHOWN.clear()
    FIXED.clear()
    o._videos_shown = set()
    o._md_videos = {"n": 0}
    o._acc_content = text
    return o._attach_typed_videos()


# ---- the marker he actually got ------------------------------------------
body = ("Based on your love of OPN, this is one of the most striking things "
        "out there:\n\n{{show_video|https://www.youtube.com/watch?v=2XxgCn8JjU4}}"
        "\n\nIt is a direct influence on everything you like.")
took = run(body)
check("a typed {{show_video|…}} marker draws the card", took
      and SHOWN == ["https://www.youtube.com/watch?v=2XxgCn8JjU4"], str(SHOWN))
check("and the marker is gone from the prose",
      len(FIXED) == 1 and "{{" not in FIXED[0], repr(FIXED[:1])[:120])
check("…replaced by the URL itself, not by nothing",
      len(FIXED) == 1 and "https://www.youtube.com/watch?v=2XxgCn8JjU4" in FIXED[0])
check("the rest of the reply is untouched",
      len(FIXED) == 1 and FIXED[0].startswith("Based on your love of OPN"))

# other shapes a model invents for the same thing
for marker in ("{{show_video: https://youtu.be/abc12345}}",
               "{{video(https://youtu.be/abc12345)}}",
               "{{play_video=https://youtu.be/abc12345}}"):
    check("…and so does %s" % marker[:22],
          run("here: " + marker) and SHOWN == ["https://youtu.be/abc12345"],
          str(SHOWN))

# ---- a URL it merely mentioned -------------------------------------------
took = run("Try [Gantz Graf](https://www.youtube.com/watch?v=ZXQ2p_9dTA0) — it "
           "is worth it.")
check("a mentioned video URL is drawn too", took
      and SHOWN == ["https://www.youtube.com/watch?v=ZXQ2p_9dTA0"], str(SHOWN))
check("with the prose left exactly as written", not FIXED, str(FIXED))

check("vimeo counts", run("https://vimeo.com/123456 is the one")
      and SHOWN == ["https://vimeo.com/123456"], str(SHOWN))

# ---- what must NOT happen -------------------------------------------------
check("an ordinary reply draws nothing",
      not run("I would start with the 1994 album, then the EPs.") and not SHOWN)
check("a non-video link is left alone",
      not run("see https://example.com/watch?v=nope") and not SHOWN, str(SHOWN))

o._videos_shown = set()
o._md_videos = {"n": 0}
o._acc_content = "look: https://youtu.be/dup12345"
o._videos_shown.add("https://youtu.be/dup12345")     # as the TOOL would have
SHOWN.clear()
check("a video the tool already drew is not drawn twice",
      not o._attach_typed_videos() and not SHOWN, str(SHOWN))

many = " ".join("https://youtu.be/vid%05d" % i for i in range(6))
run(many)
check("and the cap holds", len(SHOWN) == oracle.Ollama.MD_VIDEO_MAX,
      "%d of 6" % len(SHOWN))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
