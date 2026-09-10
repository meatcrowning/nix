#!/usr/bin/env python3
"""Offscreen release/related metadata UI probe with scratch fake services.

This deliberately loads only NowInfoPane.qml. It never starts the player,
opens a window, touches the library, or sends audio/input to the desktop.
"""

import os
import re
import shutil
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector
from PySide6.QtQuick import QQuickItem


APP = Path(__file__).resolve().parents[1]


class FakeLibrary(QObject):
    nowInfoChanged = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []
        self.state = {
            "trackId": 7,
            "status": "ready",
            "stale": False,
            "albumError": "",
            "similarError": "",
            "album": {
                "title": "Quiet Shapes", "artist": "A Band",
                "firstReleaseDate": "1999-02-01", "releaseDate": "2000-03-02",
                "country": "US", "barcode": "123",
                "labels": [{"id": "lbl-1", "name": "Small Label", "catalogNumber": "SL-2", "url": "https://label.example/release"}],
                "media": [{"position": 1, "format": "CD", "trackCount": 8}, {"position": 2, "format": "CD", "trackCount": 7}],
                "credits": [
                    {"id": "artist-1", "name": "A Producer", "role": "producer", "scope": "album"},
                    {"id": "artist-2", "name": "A Mixer", "role": "mixer", "scope": "track", "trackTitle": "Opening", "disc": 2},
                ],
                "url": "https://music.example/release", "description": "A short description.",
                "descriptionUrl": "https://en.wikipedia.org/wiki/Quiet_Shapes",
            },
            "similar": [{"trackId": 8, "title": "Near", "artist": "A Band", "album": "Elsewhere", "reason": "shared artist", "owned": True}],
            "discoveries": [{"trackId": 0, "title": "Far", "artist": "Other", "album": "Away", "reason": "last.fm", "url": "https://music.example/track", "owned": False}],
            "candidates": [{"id": "r1", "title": "Quiet Shapes", "artist": "A Band", "date": "2000-03-02", "country": "US", "format": "CD"}],
        }

    def _get(self):
        return self.state

    nowInfo = Property("QVariantMap", _get, notify=nowInfoChanged)

    @Slot("QVariant", result="QVariantList")
    def albumTrackInfo(self, _album_id):
        return [{"trackId": 7, "track": 1, "title": "Opening"}]

    @Slot(result=bool)
    def refreshNowInfo(self):
        self.calls.append("refresh")
        return True

    @Slot(result=bool)
    def clearNowInfo(self):
        self.calls.append("clear")
        return True

    @Slot(str, result=bool)
    def chooseNowInfoMatch(self, value):
        self.calls.append(("choose", value))
        return value == "r1"

    @Slot(str, "QVariantMap", result=bool)
    def editNowInfo(self, kind, values):
        self.calls.append(("edit", kind, dict(values)))
        return True

    @Slot(str, result=bool)
    def revertNowInfo(self, kind):
        self.calls.append(("revert", kind))
        return True

    @Slot(str, result=bool)
    def openInfoUrl(self, value):
        self.calls.append(("url", value))
        return value.startswith("https://")

    @Slot(str, str, str, result=bool)
    def browseInfoConnection(self, kind, entity_id, name):
        self.calls.append(("browse", kind, entity_id, name))
        return kind in ("artist", "label") and bool(entity_id or name)


class FakePlayer(QObject):
    positionChanged = Signal()
    current = Property("QVariantMap", lambda self: {"title": "Opening"})

    def __init__(self):
        super().__init__()
        self.played = []

    @Slot("QVariant", int)
    def playTracks(self, ids, start):
        self.played.append((list(ids), start))


def qml_object(engine, body):
    c = QQmlComponent(engine)
    c.setData(("import QtQuick\nQtObject {" + body + "}").encode(), QUrl())
    obj = c.create()
    if obj is None:
        raise RuntimeError(c.errorString())
    return c, obj


def visual_items(item):
    result = []
    for child in item.childItems():
        result.append(child)
        result.extend(visual_items(child))
    return result


def text_items(item):
    return [str(x.property("text")) for x in item.findChildren(QQuickItem)
            if x.property("text") is not None]


def main():
    app = QGuiApplication([])
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run outside offscreen")
    engine = QQmlApplicationEngine()
    selector = QQmlFileSelector(engine)
    selector.setExtraSelectors(["plasma"])
    wrapper = shutil.which("player")
    if wrapper:
        for path in set(re.findall(r"/nix/store/[^'\"\s]+/lib/qt-6/qml", Path(wrapper).read_text())):
            engine.addImportPath(path)

    keep = []
    style_c, style = qml_object(engine, 'property bool plasma: true; property int fontSize: 15; property string font: "monospace"; property bool fontSmooth: false; property bool reduceMotion: true; property real animSpeed: 1')
    palette_c, palette = qml_object(engine, 'property color bg: "#202020"; property color bgAlt: "#282828"; property color border: "#666666"; property color accent: "#ffffff"; property color dim: "#777777"; property color text: "#ffffff"; property color textDim: "#bbbbbb"; property color highlight: "#404040"; property color ok: "#55ff55"; property color warn: "#ffff55"; property color crit: "#ff5555"; property color info: "#55ffff"')
    lyrics_c, lyrics = qml_object(engine, 'signal ready(var value)')
    desk_c, desk = qml_object(engine, 'property bool plasma: true; property int lineHeight: 15; property int borderWidth: 2; property int rounding: 0')
    lib, player = FakeLibrary(), FakePlayer()
    for name, value in (("DeskStyle", desk), ("WalPalette", palette), ("Library", lib), ("Player", player), ("Lyrics", lyrics), ("OnAir", False)):
        engine.rootContext().setContextProperty(name, value)
    keep.extend([selector, style_c, style, palette_c, palette, lyrics_c, lyrics, desk_c, desk, lib, player])

    theme_c, theme = qml_object(engine, 'property int fontSize: 15; property int lineHeight: 15; property string font: "monospace"; property bool fontSmooth: false; property font editorFont: Qt.font({family: "monospace", pixelSize: 15}); property color bg: "#202020"; property color bgAlt: "#282828"; property color border: "#666666"; property color accent: "#ffffff"; property color dim: "#777777"; property color text: "#ffffff"; property color textDim: "#bbbbbb"; property color highlight: "#404040"; property color ok: "#55ff55"; property color warn: "#ffff55"; property color crit: "#ff5555"; property color info: "#55ffff"; property int ctrlBorder: 1; property int rounding: 0')
    engine.rootContext().setContextProperty("Theme", theme)
    pane_c = QQmlComponent(engine, QUrl.fromLocalFile(str(APP / "qml/NowInfoPane.qml")))
    pane = pane_c.create(engine.rootContext(), {"width": 480, "height": 520, "trackId": 7, "track": {"title": "Opening", "artist": "A Band", "album": "Quiet Shapes", "albumId": 1, "duration": 120, "playCount": 2}})
    if pane is None:
        raise RuntimeError(pane_c.errorString())
    keep.extend([theme_c, theme, pane_c, pane])
    for _ in range(8):
        app.processEvents()

    pane.setProperty("editing", True)
    pane.setProperty("trackId", 8)
    assert not pane.property("editing"), "track change left an editor targeting another song"
    pane.setProperty("trackId", 7)
    pane.setProperty("tab", "album")
    for _ in range(8):
        app.processEvents()
    strings = text_items(pane)
    joined = "\n".join(strings)
    for required in ("original 1999-02-01", "this release 2000-03-02", "US", "Small Label  SL-2", "2 discs", "album credits", "track credits", "disc 2", "producer  A Producer", "mixer  A Mixer"):
        if required not in joined:
            raise AssertionError("album UI missing " + required)
    if "A short description." not in joined:
        raise AssertionError("album prose missing")

    credit_rows = [x for x in visual_items(pane)
                   if x.objectName() in ("releaseCreditRow", "trackCreditRow")]
    assert len(credit_rows) == 2, "credits instantiated for the wrong scope"
    lib.state["status"] = "loading"
    lib.nowInfoChanged.emit()
    app.processEvents()
    assert all(x in visual_items(pane) for x in credit_rows), "status rebuilt credits"
    lib.state["status"] = "ready"
    lib.nowInfoChanged.emit()

    pane.setProperty("tab", "lyrics")
    lib.state["album"]["credits"] = [
        {"id": str(i), "name": "Person " + str(i), "role": "producer",
         "scope": "track", "trackTitle": "Opening"} for i in range(200)]
    lib.nowInfoChanged.emit()
    app.processEvents()
    assert not any(x.objectName() in ("releaseCreditRow", "trackCreditRow")
                   for x in visual_items(pane)), "hidden tab built 200 credits"

    pane.setProperty("tab", "similar")
    app.processEvents()
    if not any("owned tracks and discoveries" == s for s in text_items(pane)):
        raise AssertionError("related sections missing")
    if any("%" in s for s in text_items(pane)):
        raise AssertionError("confidence percentage leaked into UI")
    source = (APP / "qml/NowInfoPane.qml").read_text()
    for required in ("Player.playTracks", "root.openUrl(modelData.url)", "candidateLabel", 'root.browse("artist", modelData)', "enabled: !!modelData.id", "descriptionUrl"):
        if required not in source:
            raise AssertionError("related action wiring missing " + required)
    if lib.browseInfoConnection("person", "artist-1", "A Producer"):
        raise AssertionError("fake accepted the wrong browse kind")
    if not lib.browseInfoConnection("artist", "artist-1", "A Producer"):
        raise AssertionError("fake rejected artist browse kind")

    theme.setProperty("lineHeight", 24)
    app.processEvents()
    tab_bar = pane.findChild(QQuickItem, "tabBar")
    if tab_bar is None or tab_bar.height() < 32:
        raise AssertionError("large font header has no room")
    pane.setProperty("width", 240)
    app.processEvents()
    actions = pane.findChild(QQuickItem, "actions")
    if actions is None or actions.y() < 0 or actions.y() + actions.height() > tab_bar.height():
        raise AssertionError("narrow wrapped actions escape the tab bar")
    print("album-info-ui-test: offscreen release, credits, candidates, and related rows loaded")


if __name__ == "__main__":
    main()
