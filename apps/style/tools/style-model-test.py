#!/usr/bin/env python3
"""Qt-free regression for Style's draft/active wallpaper contract."""

from __future__ import annotations

import importlib.util
import inspect
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

qml = (ROOT / "apps" / "style" / "qml" / "Root.qml").read_text(encoding="utf-8")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("ok -", message)


check("import QtQuick.Controls.Basic" not in qml and "import QtQuick.Controls\n" in qml,
      "uses the desktop controls style instead of the Basic face")
check("kdeshell.pin_controls_style()" in inspect.getsource(module.main),
      "pins the Plasma QStyle before constructing the application")
check('kdeshell.shell("style"' in inspect.getsource(module.main)
      and "StyledBackground" in qml,
      "extends the native Plasma window surface through the program body")
apply_source = inspect.getsource(module.Appearance.apply)
check("asyncCallWithArgumentList" in apply_source and '"Apply", [self._draft]' in apply_source,
      "sends the wallpaper as a QtDBus argument list without blocking the UI")
scheme_source = inspect.getsource(module.Appearance.selectScheme)
check('"SetScheme", [scheme]' in scheme_source,
      "switches live Plasma schemes through the same controller transaction")
check('Popup {' in qml and 'visible: Appearance.applying' in qml,
      "keeps apply progress inside the Style window")
check("class ApplyProgressDialog" in inspect.getsource(module)
      and "appearance.use_native_progress()" in inspect.getsource(module.main),
      "uses a native KDE dialog for Plasma apply progress")
check('apply-overlay.py' not in inspect.getsource(module.Appearance._apply_reply),
      "does not start a fullscreen apply overlay")
check('"Pictures" / "Wallpapers"' in inspect.getsource(module.wallpaper_dir),
      "uses the canonical Wallpapers library by default")
check("self._applying = False" in apply_source,
      "a client-side D-Bus failure releases the applying state")


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

    incoming = Path(temporary) / "incoming"
    incoming.mkdir()
    imported = incoming / "new paper.png"
    imported.write_bytes(b"first")
    model.importFiles([module.QUrl.fromLocalFile(str(imported))])
    model.importFiles([module.QUrl.fromLocalFile(str(imported))])
    check((root / "new paper.png").read_bytes() == b"first"
          and (root / "new paper-2.png").read_bytes() == b"first",
          "imports without overwriting a same-named wallpaper")

    trashed = []
    model._trash = lambda path: (trashed.append(path) or "")
    model.select(str(root / "new paper.png"))
    model.removeWallpaper(str(root / "new paper.png"))
    check(trashed == [root / "new paper.png"] and model.draftPath == model.activePath,
          "moves an inactive wallpaper to trash and restores the active selection")

    model.removeWallpapers([str(root / "new paper-2.png"), str(second)])
    check(trashed[-2:] == [root / "new paper-2.png", second],
          "moves an arbitrary wallpaper selection to trash")

    submitted = []
    model.apply = lambda: submitted.append(model.draftPath)
    model.removeWallpaper(model.activePath)
    check(model._pending_delete == [str(first.resolve())] and submitted
          and submitted[0] != str(first.resolve()),
          "selects a replacement before trashing the active wallpaper")

    profile.unlink()
    (root / ".current-wallpaper").write_text(first.name + "\n", encoding="utf-8")
    legacy = module.Appearance(root=root, profile=profile)
    check(legacy.activePath == str(first.resolve()),
          "uses the panel selection until the controller has an active profile")

print("style model tests passed")
