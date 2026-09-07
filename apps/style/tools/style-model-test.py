#!/usr/bin/env python3
"""Qt-free regression for Style's draft/active wallpaper contract."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
spec = importlib.util.spec_from_file_location("style_main", ROOT / "apps" / "style" / "main.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("ok -", message)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary) / "wall"
    root.mkdir()
    first = root / "a blue.jpg"
    second = root / "b green.png"
    first.write_bytes(b"not decoded by this model test")
    second.write_bytes(b"not decoded by this model test")
    (root / "not wallpaper.txt").write_text("no", encoding="utf-8")
    profile = Path(temporary) / "active-profile.json"
    profile.write_text(json.dumps({"wallpaper": {"path": str(first)}}), encoding="utf-8")

    model = module.Appearance(root=root, profile=profile)
    check([item["name"] for item in model.wallpapers] == ["a blue", "b green"],
          "lists only supported wallpapers in stable name order")
    check(model.activePath == str(first.resolve()) and not model.hasDraft,
          "starts with controller profile as active, not an implicit write")
    model.select(str(second))
    check(model.draftPath == str(second.resolve()) and model.hasDraft,
          "selection is a reversible draft")
    model.cancel()
    check(model.draftPath == model.activePath and not model.hasDraft,
          "cancel discards only the draft")
    model.select(str(root / "not wallpaper.txt"))
    check(model.draftPath == model.activePath, "refuses a path outside the offered wallpaper model")

    profile.unlink()
    (root / ".current-wallpaper").write_text(first.name + "\n", encoding="utf-8")
    legacy = module.Appearance(root=root, profile=profile)
    check(legacy.activePath == str(first.resolve()),
          "uses the panel selection until the controller has an active profile")

print("style model tests passed")
