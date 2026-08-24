#!/usr/bin/env python3
"""His generation shorthand: what parses, what does not, and what it becomes.

Pure parsing — no backend, no window, no model. The point of the module under
test is that the NUMBERS are not a model's guess, so this is where the numbers
are pinned.

    python3 tools/shorthand-test.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import genshort  # noqa: E402

FAILED = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILED.append(label)


IMG = "/tmp/a.png"
IMG2 = "/tmp/b.png"

print("\nthe shorthand")
g = genshort.parse("anima. 2:3 x1 1girl, solo, looking at viewer")
check("a model word picks the model", g and g["args"].get("model") == "anima", str(g))
check("W:H is the aspect", g and g["args"].get("aspect") == "2:3", str(g))
check("xN is the megapixel budget", g and g["args"].get("megapixels") == 1.0, str(g))
check("the rest is his prompt, verbatim",
      g and g["args"]["prompt"] == "1girl, solo, looking at viewer", str(g))
check("...as an image job", g and g["tool"] == "make_image", str(g))

g = genshort.parse("krea. 16:9 3x 2.5mp a lighthouse in fog")
check("Nx is a count", g and g["args"].get("count") == 3, str(g))
check("Nmp is also the budget", g and g["args"].get("megapixels") == 2.5, str(g))
check("krea means krea", g and g["args"].get("model") == "krea", str(g))

g = genshort.parse("anima. seed:42 steps:30 1girl")
check("seed and steps come through", g and g["args"].get("seed") == 42
      and g["args"].get("steps") == 30, str(g))

print("\nvideo")
g = genshort.parse("video. first frame: [pasted image]. 6s i2v. she turns to camera",
                   [IMG])
check("a clip is make_video", g and g["tool"] == "make_video", str(g))
check("the attachment becomes the first frame",
      g and g["args"].get("first_frame") == IMG, str(g))
check("Ns is the duration", g and g["args"].get("seconds") == 6.0, str(g))
check("the frame label is not part of the prompt",
      g and g["args"]["prompt"] == "she turns to camera", str(g))

g = genshort.parse("video. 4s clouds moving over a city")
check("text-to-video needs no frame",
      g and g["tool"] == "make_video" and "first_frame" not in g["args"], str(g))

g = genshort.parse("video. fl2v 5s a slow pan", [IMG, IMG2])
check("fl2v takes both ends",
      g and g["args"].get("first_frame") == IMG
      and g["args"].get("last_frame") == IMG2, str(g))

g = genshort.parse("video. she turns", [IMG])
check("a picture on a clip is its first frame with no keyword",
      g and g["args"].get("first_frame") == IMG, str(g))

print("\nediting")
g = genshort.parse("klein. make it night", [IMG])
check("klein plus a picture is an edit",
      g and g["tool"] == "make_image" and g["args"].get("input_images") == [IMG],
      str(g))
check("...on the edit model", g and g["args"].get("model") == "klein", str(g))
check("an edit takes no aspect", g and "aspect" not in g["args"], str(g))
check("edit with nothing to edit is not a job",
      genshort.parse("edit. make it night") is None,
      str(genshort.parse("edit. make it night")))
g = genshort.parse("anima. 1girl, solo", [IMG])
check("a picture attached to an image job edits it too",
      g and g["args"].get("input_images") == [IMG], str(g))

print("\nwhat must NOT fire")
for text in ["how are you today?",
             "can you make an image of a cat",
             "hello. how is the weather",
             "python. is a language",
             "3:2 is the aspect I want",
             ""]:
    check("not shorthand: %r" % text[:34], genshort.parse(text) is None,
          str(genshort.parse(text)))

print("\nthe hint")
h = genshort.hint("anima. 2:3 x1 1girl, solo", [])
check("the hint names the tool", "make_image" in h, h[:120])
check("...and carries the parsed arguments", '"aspect": "2:3"' in h, h[:200])
check("no shorthand, no hint", genshort.hint("hello there") == "")

print()
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("all good")
