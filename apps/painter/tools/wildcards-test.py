#!/usr/bin/env python3
"""Headless checks for Painter's prompt wildcard expansion."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wildcards as W  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "colour.txt").write_text("# ignored\nred\n\nblue\n", encoding="utf-8")
    (root / "pose.txt").write_text("standing\nsitting\n", encoding="utf-8")

    first = W.expand("a __colour__ cube", 4242, root)
    check("a fixed seed is repeatable", first == W.expand("a __colour__ cube", 4242, root))
    check("the token is replaced", "__colour__" not in first)
    check("comments and blanks are ignored", first in {"a red cube", "a blue cube"})
    check("unknown names remain visible", W.expand("__missing__", 1, root) == "__missing__")

    pos, neg = W.expand_prompts("__pose__, __colour__", "not __colour__", 99, root)
    check("both prompt boxes expand", "__" not in pos and "__" not in neg)
    check("one name has one pick across both boxes", pos.split(", ")[1] == neg[4:])

print("wildcards: all checks passed")
