#!/usr/bin/env python3
"""Offscreen search control geometry; fake metadata and no player/audio."""
import os
from pathlib import Path
import re
import runpy
import shutil
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_CONTROLS_STYLE'] = 'Basic'
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ.pop('DISPLAY', None)
scratch = tempfile.TemporaryDirectory(prefix='player-search-ui-')
for key in ('XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME'):
    os.environ[key] = str(Path(scratch.name) / key)
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector

appdir = Path(__file__).resolve().parents[1]
app = QGuiApplication([])
assert app.platformName() == 'offscreen'
# Reuse scratch-safe theme stubs; this module's main() is never called.
fixtures = runpy.run_path(str(appdir / 'tools/systheme-toast-test.py'), run_name='search_fixture')
wrapper = Path(shutil.which('player')).read_text()
keep = []
for plasma in (False, True):
    engine = QQmlApplicationEngine()
    for path in set(re.findall(r"/nix/store/[^'\"\s]+/lib/qt-6/qml", wrapper)):
        engine.addImportPath(path)
    if plasma:
        selector = QQmlFileSelector(engine)
        selector.setExtraSelectors(['plasma'])
        keep.append(selector)
    ctx = engine.rootContext()
    def qml_object(body):
        component = QQmlComponent(engine)
        component.setData(('import QtQuick\nQtObject {' + body + '}').encode(), QUrl())
        obj = component.create(ctx)
        assert obj is not None, component.errorString()
        keep.extend([component, obj])
        return obj
    style = qml_object('property string fontFamily: "monospace"; property int fontSize: 15; property bool reduceMotion: true; property real animSpeed: 1; property bool plasma: ' + str(plasma).lower())
    palette = fixtures['StubPalette']()
    lib = qml_object('property int searchTotal: 901; property int searchOffset: 0; function searchPage(d) { searchOffset += d*400 } function playSearchAll() {} function playSearch(i) {}')
    model = qml_object('property int count: 400; function get(i) { return {} }')
    player = qml_object('property var current: ({})')
    for name, obj in [('DeskStyle', style), ('WalPalette', palette), ('Library', lib), ('SearchModel', model), ('Player', player), ('OnAir', False)]:
        ctx.setContextProperty(name, obj)
    keep.append(palette)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(appdir / 'qml/theme/Theme.qml')))
    theme = comp.create(ctx)
    assert theme is not None, comp.errorString()
    ctx.setContextProperty('Theme', theme)
    comp = QQmlComponent(engine)
    comp.setData(b'import QtQuick\nSearchOverlay { width:480; height:600; query: "a very long query repeated a very long query repeated a very long query" }', QUrl.fromLocalFile(str(appdir / 'qml/search-ui-fixture.qml')))
    root = comp.create(ctx)
    assert root is not None, comp.errorString()
    keep.extend([engine, theme, comp, root])
    for _ in range(10): app.processEvents()
    rows = [child for child in root.childItems() if child.metaObject().className().startswith('QQuickRow')]
    head, pages = rows
    print('plasma', plasma, 'head', head.width(), head.height(), 'pages', pages.height(), 'buttons', [(c.width(), c.height()) for c in pages.childItems()])
    assert head.x() + head.width() <= root.width(), 'header exceeds window'
    for row in (head, pages):
        for child in row.childItems():
            assert child.x() + child.width() <= root.width() - row.x(), 'control exceeds window'
            assert child.y() + child.height() <= row.height(), 'control exceeds row height'
    if plasma:
        assert any(c.property('face') == 'plasma' for c in pages.childItems()), 'Plasma selector inactive'
    previous, count, following = pages.childItems()
    assert not previous.isEnabled() and following.isEnabled()
    assert QMetaObject.invokeMethod(following, 'clicked')
    for _ in range(4): app.processEvents()
    assert lib.property('searchOffset') == 400 and previous.isEnabled()
    lib.setProperty('searchOffset', 800)
    model.setProperty('count', 101)
    for _ in range(4): app.processEvents()
    assert count.property('text') == '801–901 of 901'
    assert not following.isEnabled()
    lib.setProperty('searchOffset', 0)
    lib.setProperty('searchTotal', 101)
    for _ in range(4): app.processEvents()
    assert not pages.isVisible() and pages.height() == 0
print('search UI: both variants fit at 480px')
