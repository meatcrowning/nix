#!/usr/bin/env python3
"""Offscreen smoke test: oracle loads its QML and queries the live ollama daemon.

Never touches his screen — hard offscreen, nothing to fall back to.
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # and nothing to fall back TO
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

from PySide6.QtCore import QTimer, QUrl                     # noqa: E402
from PySide6.QtGui import QGuiApplication                   # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402

import main as oracle                                        # noqa: E402

app = QGuiApplication(sys.argv)
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

engine = QQmlApplicationEngine()
ctx = engine.rootContext()

palette = oracle.Palette(oracle.PANEL_THEME)
style = None
from deskstyle import DeskStyle                              # noqa: E402
style = DeskStyle()
titlebar = oracle.Titlebar()
ollama = oracle.Ollama()

ctx.setContextProperty("WalPalette", palette)
ctx.setContextProperty("DeskStyle", style)
ctx.setContextProperty("Titlebar", titlebar)
ctx.setContextProperty("Ollama", ollama)
ctx.setContextProperty("ollamaHost", oracle.OLLAMA)

theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(APP / "qml" / "theme" / "Theme.qml")))
theme = theme_comp.create()
if theme is None:
    raise SystemExit("Theme.qml failed:\n" + theme_comp.errorString())
theme.setParent(app)
ctx.setContextProperty("Theme", theme)

engine.load(QUrl.fromLocalFile(str(APP / "qml" / "Main.qml")))
if not engine.rootObjects():
    raise SystemExit("Main.qml failed to load")
print("QML loaded OK")

got = {"models": None, "err": None}
ollama.modelsChanged.connect(lambda: got.update(models=list(ollama.models)))
ollama.modelsError.connect(lambda e: got.update(err=e))
ollama.refreshModels()

QTimer.singleShot(6000, app.quit)
app.exec()

if got["err"]:
    raise SystemExit("tags query error: " + got["err"])
if got["models"] is None:
    raise SystemExit("no modelsChanged fired (daemon down?)")
print("models (%d): %s" % (len(got["models"]), ", ".join(got["models"])))
if not got["models"]:
    raise SystemExit("model list is empty")
print("OK")
