#!/usr/bin/env python3
"""Cover-art attachment binding stays local and never guesses among images."""
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

import main as oracle  # noqa: E402

fails = []


def check(name, condition):
    print(("ok   " if condition else "FAIL ") + name)
    if not condition:
        fails.append(name)


plain = {"op": "art", "album": "Interplanetary Radio"}
bound, error = oracle.Ollama._bind_attached_art(
    "music_tag", plain, ("/tmp/full-size.jpg",))
check("one attached image is bound to an otherwise-unspecified art dry run",
      not error and bound["art"]["file"] == "/tmp/full-size.jpg")
check("binding does not mutate the model's original arguments", "art" not in plain)

explicit, error = oracle.Ollama._bind_attached_art(
    "music_tag", {"op": "art", "art": {"source": "auto"}},
    ("/tmp/full-size.jpg",))
check("an explicit art source is left alone", not error and explicit["art"] == {"source": "auto"})

multiple, error = oracle.Ollama._bind_attached_art(
    "music_tag", plain, ("/tmp/one.jpg", "/tmp/two.jpg"))
check("multiple attachments are refused instead of guessed",
      multiple == plain and error and "multiple attached images" in error)

apply, error = oracle.Ollama._bind_attached_art(
    "music_tag", {"op": "art", "apply": True, "plan_token": "plan"},
    ("/tmp/full-size.jpg",))
check("a token apply is not altered", not error and "art" not in apply)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
