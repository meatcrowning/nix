#!/usr/bin/env python3
"""Keep Window-backed browser exports separate from native View content.

No browser, Qt application, or live profile is opened. Distinct Window/View
colours catch the contract regression introduced by the mixed-theme refactor.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import chansource
import kdetheme
import vivaldichrome

spec = importlib.util.spec_from_file_location("writer", HERE / "vivaldi-theme.py")
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)

with tempfile.TemporaryDirectory(prefix="browser-palette-") as directory:
    root = Path(directory)
    os.environ.update(DESK_SESSION="plasma", DESK_KDEGLOBALS=str(root / "kdeglobals"),
                      XDG_STATE_HOME=str(root / "state"))
    for name, window, view, ink, view_ink in (
        ("dark", "56,28,25", "49,18,15", "240,230,220", "255,255,255"),
        ("light", "239,240,241", "255,255,255", "35,38,41", "0,0,0"),
        ("mixed", "56,28,25", "239,240,241", "240,230,220", "35,38,41"),
    ):
        (root / "kdeglobals").write_text(
            f"[Colors:Window]\nBackgroundNormal={window}\nForegroundNormal={ink}\n"
            f"[Colors:View]\nBackgroundNormal={view}\nForegroundNormal={view_ink}\n"
            "[KDE]\nwidgetStyle=oxygen\n")
        native = kdetheme.kde_palette()
        assert native["bg"] == tuple(map(int, view.split(",")))
        assert native["text"] == tuple(map(int, view_ink.split(",")))
        expected = kdetheme._hex(tuple(map(int, window.split(","))))
        expected_ink = kdetheme._hex(tuple(map(int, ink.split(","))))
        palette, _ = chansource.palette("plasma")
        assert palette["bg"] == expected and palette["text"] == expected_ink
        css, _ = vivaldichrome.build("plasma")
        assert f"--colorBg: {expected}" in css
        assert f"--colorFg: {expected_ink}" in css
        prefs = root / name / "Preferences"
        prefs.parent.mkdir()
        prefs.write_text("{}")
        writer.write_prefs("plasma", prefs=prefs, ui_dir=root / "css")
        theme = json.loads(prefs.read_text())["vivaldi"]["themes"]["user"][0]
        assert theme["colorBg"] == expected and theme["colorFg"] == expected_ink
        print(f"ok - {name}: browser chrome, saved theme and sites use Window; native content retains View")
