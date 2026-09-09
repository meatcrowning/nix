#!/usr/bin/env python3
"""Offscreen native-role and all-app wiring audit; never opens an app."""
import ast
import os
from pathlib import Path
import sys
import tempfile

assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
assert not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/pylib"))
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QColor, QPalette
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtWidgets import QApplication

with tempfile.TemporaryDirectory(prefix="native-palette-test-") as temporary:
    os.environ["DESK_SESSION"] = "plasma"
    os.environ["DESK_KDEGLOBALS"] = temporary + "/kdeglobals"
    os.environ["DESK_SETTINGS"] = temporary + "/settings.json"
    os.environ["DESK_OXYGENRC"] = temporary + "/oxygenrc"
    os.environ["XDG_CACHE_HOME"] = temporary + "/cache"
    Path(os.environ["DESK_KDEGLOBALS"]).write_text(
        "[Colors:View]\nForegroundNegative=170,20,30\n")
    from nativepalette import NativePalette, session_palette
    from deskstyle import DeskStyle
    import kdetheme
    app = QApplication([])
    assert app.platformName() == "offscreen"
    palette = QPalette()
    for role, color in ((QPalette.Window, "#351c19"), (QPalette.WindowText, "#ffffff"),
                        (QPalette.Base, "#e0c9c4"), (QPalette.AlternateBase, "#d8bdb7"),
                        (QPalette.Text, "#201514"), (QPalette.Button, "#50352f"),
                        (QPalette.ButtonText, "#fffafa"), (QPalette.Highlight, "#733020"),
                        (QPalette.HighlightedText, "#ffffff")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#776655"))
    app.setPalette(palette)

    @session_palette
    class Wallpaper(QObject):
        def __init__(self, *args):
            raise AssertionError("Plasma constructed a wallpaper reader")

    native = Wallpaper("/must-not-be-read")
    assert isinstance(native, NativePalette)
    assert native.bg == app.palette().base().color()
    assert native.text == app.palette().text().color()
    assert native.windowText == app.palette().windowText().color()
    assert native.highlightedText == app.palette().highlightedText().color()
    assert native.inactive == app.palette().color(QPalette.Inactive, QPalette.Text)
    assert native.disabledText == app.palette().color(QPalette.Disabled, QPalette.Text)
    assert native.crit.name() == "#aa141e"
    assert kdetheme.theme_source("/no-generated-file") == "/no-generated-file"
    assert not Path(temporary, "cache/deskstyle/kde-Theme.qml").exists()

    style = DeskStyle()
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("DeskStyle", style)
    engine.rootContext().setContextProperty("WalPalette", native)
    themes = []
    for path in sorted((ROOT / "apps").glob("*/qml/theme/Theme.qml")):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        theme = component.create()
        assert theme is not None, (path, component.errorString())
        theme.setParent(engine)
        assert theme.property("plasmaPalette"), path
        assert theme.property("text") == native.text, path
        assert theme.property("bg") == native.bg, path
        assert theme.property("windowText") == native.windowText, path
        assert theme.property("selectionText") == native.highlightedText, path
        themes.append(theme)
        main = path.parents[2] / "main.py"
        tree = ast.parse(main.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Palette")
        assert any(isinstance(d, ast.Name) and d.id == "session_palette" for d in cls.decorator_list), main
        print("ok - native roles and factory:", main.parent.name)
    assert len(themes) == 13

    # Update only the View text; window colour staying equal must not suppress it.
    palette.setColor(QPalette.Text, QColor("#102030"))
    app.setPalette(palette)
    app.processEvents()
    for theme in themes:
        assert theme.property("text").name() == "#102030"
        assert theme.property("windowText").name() == "#ffffff"
    from kdeshell import content_palette, _group_palette
    assert _group_palette(QPalette.Inactive).color(QPalette.Disabled, QPalette.Text) == palette.color(QPalette.Disabled, QPalette.Text)
    content = content_palette()
    assert content.window().color() == palette.base().color()
    assert content.windowText().color() == palette.text().color()
    assert content.button().color() == palette.button().color()
    assert content.color(QPalette.Disabled, QPalette.Text) == palette.color(QPalette.Disabled, QPalette.Text)
    Path(os.environ["DESK_KDEGLOBALS"]).write_text(
        "[Colors:View]\nForegroundNormal=80,60,40\n")
    assert native._load() is False, "must not acknowledge before Qt adopts the scheme"
    palette.setColor(QPalette.Text, QColor(80, 60, 40))
    app.setPalette(palette)
    app.processEvents()
    assert native._load() is True
    print("ok - live native changes and content/chrome separation")
    for theme in themes:
        theme.setParent(engine)
