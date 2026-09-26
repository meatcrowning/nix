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
from PySide6.QtCore import QObject, QPointF, Qt, QUrl, Property
from PySide6.QtGui import QGuiApplication, QImage, QColor, QPainter
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
sys.path.insert(0, str(HERE.parent))
import visualizer

class AnimatedStyle(f.StubStyle):
    @Property(bool, constant=True)
    def reduceMotion(self): return False


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
                          'Visualizer': visual, 'DeskStyle': AnimatedStyle(),
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
        notice = page.findChild(QObject, 'visualizerTrackNotice')
        timer = page.findChild(QObject, 'visualizerTrackNoticeTimer')
        assert not timer.property('running'), 'startup must not announce the track'
        QTest.mouseMove(scene, QPointF(-10, -10).toPoint())
        page.setProperty('bottomCollapsed', True)
        player.currentChanged.emit()
        assert not timer.property('running'), 'same-track metadata must not announce'
        player._index = 2
        player.currentChanged.emit()
        QTest.qWait(150)
        fade_in = notice.opacity()
        assert 0 < fade_in < 1, fade_in
        QTest.qWait(200)
        assert fade_in < notice.opacity() < 1, notice.opacity()
        QTest.qWait(550)
        assert notice.opacity() == 1
        assert timer.property('running') and notice.isVisible()
        assert notice.x() == 8 and notice.y() >= 0
        cover = page.findChild(QObject, 'visualizerNoticeArt')
        assert cover.x() == 0
        metadata = page.findChild(QObject, 'visualizerNoticeText')
        assert abs(metadata.y()+metadata.height()/2-cover.y()-cover.height()/2) < 1
        assert abs(notice.y()+cover.y()+cover.height()-notice.parentItem().height()+8) < 1
        assert notice.x()+notice.width() <= notice.parentItem().width()
        QTest.qWait(3600)
        player.currentChanged.emit()
        for _ in range(100):
            if not timer.property('running'): break
            QTest.qWait(10)
        assert not timer.property('running'), 'metadata restarted dwell'
        QTest.qWait(150)
        fade_out = notice.opacity()
        assert 0 < fade_out < 1 and notice.isVisible(), fade_out
        QTest.qWait(200)
        assert 0 < notice.opacity() < fade_out, notice.opacity()
        QTest.qWait(550)
        assert not notice.isVisible() and notice.opacity() == 0
        surface = page.findChild(QObject, 'visualizerSurface')
        QTest.mouseMove(scene, surface.mapToScene(QPointF(surface.width()/2, surface.height()/2)).toPoint())
        QTest.qWait(150)
        assert 0 < notice.opacity() < 1 and not timer.property('running')
        toggle = page.findChild(QObject, 'visualizerSidebarButton')
        assert abs(toggle.opacity()-notice.opacity()) < .03
        QTest.qWait(750)
        assert notice.opacity() == 1
        # Source rows are inverted on screen: white at the source top lies
        # behind the bottom-right label, while the screen top stays black.
        frame = QImage(64, 64, QImage.Format.Format_RGB32)
        frame.fill(QColor('white'))
        painter = QPainter(frame)
        painter.fillRect(0, 32, 64, 32, QColor('black'))
        painter.end()
        surface.receive(frame)
        label = page.findChild(QObject, 'visualizerSidebarText')
        assert surface.backgroundLight and label.property('color') == QColor('black')
        QTest.qWait(270)
        frame.fill(QColor('black'))
        surface.receive(frame)
        assert not surface.backgroundLight and label.property('color') == QColor('white')
        QTest.mouseMove(scene, QPointF(-10, -10).toPoint())
        QTest.qWait(150)
        assert 0 < notice.opacity() < 1
        assert abs(toggle.opacity()-notice.opacity()) < .03
        assert surface.contrastRect.isEmpty(), 'hidden labels must not sample frames'
        QTest.qWait(750)
        assert not notice.isVisible()
        player._index = 0
        player.currentChanged.emit()
        assert timer.property('running')
        page.setProperty('bottomCollapsed', False)
        assert not timer.property('running') and not notice.isVisible()
        player._index = 2
        player.currentChanged.emit()
        assert not timer.property('running'), 'expanded pane must not announce'
        player._index = 0
        player.currentChanged.emit()
        print('PASS collapsed track notice, dwell, metadata filtering and expansion:', plasma)
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
