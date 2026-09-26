#!/usr/bin/env python3
"""Real UI -> Bridge -> scratch SQLite -> current track/models, without mpv."""
import importlib.util
import os
from pathlib import Path
import sys

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fixture', HERE/'now-allinone-test.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
sys.path.insert(0, str(HERE.parent))
import visualizer

app = QGuiApplication([])
assert app.platformName() == 'offscreen'
visualizer.register()
f.seed_db()
# Never instantiate the real audio player or tag/network writers.
lib = f.P.Library(None)
player = f.P.Player.__new__(f.P.Player)
QObject.__init__(player)
player._library = lib
player._queue = lib.tracks_by_ids([1, 1, 2])
player._orig_queue = list(player._queue)
player._index = 0
player._playing = False
player._position = player._duration = 0.0
f.P.Bridge._request_now_info = lambda self: None
bridge = f.P.Bridge(lib, player, None)
models = [bridge.albumTracksModel, bridge.browseTracksModel, bridge.playlistModel,
          bridge.searchModel, bridge.queueModel]
for model in models:
    model.set_rows([f.P.track_row(t) for t in player._queue])
prefs = f.P.Prefs()
visual = visualizer.Visualizer('isolated-ratings')
visual.closed = True
keep = [lib, player, bridge, prefs, visual]

def settle():
    for _ in range(200):
        QTest.qWait(10)
        if not lib._pending_metadata:
            return
    raise AssertionError('metadata write did not complete')

def verify(rating, favorite):
    settle()
    assert player.current['favorite'] is favorite, player.current
    assert player.current['rating'] == rating
    row = lib._con.execute('SELECT rating,favorite FROM tracks WHERE id=1').fetchone()
    assert tuple(row) == (rating, int(favorite))
    for model in models:
        for i in (0, 1):
            row = model.get(i)
            assert row['favorite'] is favorite and row['rating'] == (-1 if rating is None else rating)
    assert all(t['favorite'] == int(favorite) for t in player._orig_queue if t['id'] == 1)

try:
    for plasma in (False, True):
        engine = QQmlApplicationEngine()
        keep.append(engine)
        if plasma:
            selector = QQmlFileSelector(engine, engine)
            selector.setExtraSelectors(['plasma'])
            keep.append(selector)
        ctx = engine.rootContext()
        for name, obj in {'Prefs': prefs, 'Library': bridge, 'Player': player,
                          'Visualizer': visual, 'DeskStyle': f.StubStyle(),
                          'WalPalette': f.StubPalette(), 'Lyrics': f.StubLyrics(),
                          'QueueModel': bridge.queueModel}.items():
            keep.append(obj)
            ctx.setContextProperty(name, obj)
        ctx.setContextProperty('OnAir', False)
        tc = QQmlComponent(engine, QUrl.fromLocalFile(str(f.QML/'theme/Theme.qml')))
        theme = tc.create()
        assert theme, tc.errorString()
        keep.extend([tc, theme])
        ctx.setContextProperty('Theme', theme)
        comp = QQmlComponent(engine, QUrl.fromLocalFile(str(f.QML/'VisualizerPage.qml')))
        page = comp.create()
        assert page, comp.errorString()
        scene = QQuickWindow()
        keep.extend([comp, page, scene])
        page.setParentItem(scene.contentItem())
        page.setProperty('plasma', plasma)
        page.setWidth(960)
        page.setHeight(700)
        scene.resize(960, 700)
        scene.show()
        QTest.qWait(50)
        stars = page.findChild(QObject, 'visualizerStars')
        heart = page.findChild(QObject, 'visualizerFavorite')
        def click(item, x=None):
            point = item.mapToScene(QPointF(item.width()/2 if x is None else x, item.height()/2)).toPoint()
            QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, point)
            settle()
        bridge.setRating(1, -1)
        bridge.setFavorite(1, False)
        verify(None, False)
        assert not heart.property('lit')
        click(heart)
        verify(None, True)
        assert heart.property('lit'), 'saved heart remains visually empty'
        click(heart)
        verify(None, False)
        assert not heart.property('lit')
        for n in range(1, 6):
            click(stars, stars.width()*(n-.5)/5)
            verify(n/5, False)
            assert stars.property('rating') == n/5
            click(stars, stars.width()*(n-.5)/5)
            verify(None, False)
            assert stars.property('rating') == -1
        # Imported FMPS values such as 0.79 display four stars too.
        bridge.setRating(1, .79)
        verify(.79, False)
        click(stars, stars.width()*3.5/5)
        verify(None, False)
        bridge.setFavorite(1, True)
        bridge.setFavorite(1, False)
        bridge.setFavorite(1, True)
        verify(None, True)
        assert heart.property('lit')
        scene.hide()
        print('PASS actual heart/star clicks, five ratings, clearing, duplicate rows and rapid toggles:',
              'Plasma' if plasma else 'Hyprland')
    # Read committed values from a new connection, as on the next launch.
    con = f.P.open_db()
    assert tuple(con.execute('SELECT rating,favorite FROM tracks WHERE id=1').fetchone()) == (None, 1)
    con.close()
finally:
    visual.shutdown()
    lib.close()
    for obj in reversed(keep):
        if isinstance(obj, QQmlApplicationEngine): obj.deleteLater()
    QTest.qWait(10)
