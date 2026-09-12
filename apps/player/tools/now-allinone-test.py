#!/usr/bin/env python3
"""now-allinone-test.py — the maximized now-playing page, offscreen.

Given a whole screen the Plasma now-playing page drops the release pane's
lyrics TAB, gives lyrics a section of their own under it, and puts an album
browser (with its own search) beside the queue. Compact, it must stay exactly
the page it was. This builds the real `Library`/`Bridge` over a scratch
library.db, loads the real `+plasma/NowPlaying.qml` at both sizes and reads
what was actually built.

Offscreen, hard: no window on his screen, no contact with the live player, its
socket, its database or its audio device (nothing here builds a `Player`).

    apps/player/tools/now-allinone-test.py
"""
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_tmp = tempfile.TemporaryDirectory(prefix="now-allinone-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())


def _relaunch_under_player_python():
    """See alias-ui-test.py — read the `player` wrapper for its python env,
    never source it (sourcing runs the wrapper's body, i.e. launches the app)."""
    if os.environ.get("ALLINONE_TEST_RELAUNCHED"):
        return
    wrapper = shutil.which("player")
    text = ""
    if wrapper:
        try:
            text = open(wrapper, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    found = re.search(r"/nix/store/[^\" ]+-env/bin/python3[0-9.]*", text)
    # On book the wrapper is air-launch.sh and PySide6 is Fedora's, exactly as
    # the launcher's own PLAYER_PYTHON default says.
    python = found.group(0) if found else "/usr/bin/python3"
    if not os.access(python, os.X_OK):
        sys.exit("no PySide6, and no python with it to relaunch under")
    os.environ["ALLINONE_TEST_RELAUNCHED"] = "1"
    os.execv(python, [python, str(Path(__file__).resolve())] + sys.argv[1:])


# BOOK: the session exports a nix `QT_PLUGIN_PATH`, and Fedora's PySide6 links
# Fedora's Qt — loading the nix platform plugin into it aborts the process
# before a single message is printed. An offscreen harness wants the
# interpreter's own plugins, whichever host this is.
if "/nix/store" in os.environ.get("QT_PLUGIN_PATH", "") and not sys.executable.startswith("/nix/store"):
    os.environ.pop("QT_PLUGIN_PATH", None)
    os.environ.pop("QT_STYLE_OVERRIDE", None)

try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    _relaunch_under_player_python()

from PySide6.QtCore import (Property, QMetaObject, QObject, Q_ARG, QUrl, QtMsgType,
                            Signal, Slot, qInstallMessageHandler)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector
from PySide6.QtQuick import QQuickItem

sys.path.insert(0, str(APP))
import main as P  # noqa: E402

QML = APP / "qml"
KEEP = []
QML_MSGS = []
FAILS = []

# Environment noise this harness cannot avoid and that says nothing about the
# page: the desktop's generated icon theme is not installed under a scratch
# XDG_DATA_HOME, and Qt registers one type per file of the implicitly imported
# qml/ and qmlcommon/ directories when the root component comes from setData.
NOISE = ("Icon theme ", "qmlRegisterType requires absolute URLs")
# A Controls Menu is its own window. Popping one up in an offscreen harness
# says so once per row and means nothing about the menu the app builds.
NOISE_IN = ("Created graphical object was not placed in the graphics scene",)


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name
          + (("  " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def on_qml_message(mtype, ctx, msg):
    if (mtype in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            and not str(msg).startswith(NOISE)
            and not any(x in str(msg) for x in NOISE_IN)):
        QML_MSGS.append(msg)


FIXTURE = [
    ("Trophy", "NAO feat. A. K. Paul", "For All We Know", "NAO", 2016),
    ("Bad Blood", "NAO", "For All We Know", "NAO", 2016),
    ("Roygbiv", "Boards of Canada", "Music Has the Right", "Boards of Canada", 1998),
    ("Olson", "Boards of Canada", "Music Has the Right", "Boards of Canada", 1998),
]


def seed_db():
    con = P.open_db()
    now = time.time()
    audio = Path(_tmp.name) / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    for i, (title, artist, album, album_artist, year) in enumerate(FIXTURE):
        path = audio / ("%d.flac" % i)
        path.write_bytes(b"")
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album,"
            " album_artist, track, disc, year, orig_year, duration, codec,"
            " play_count, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(path), 1.0, 100, title, artist, album, album_artist,
             i + 1, 1, year, year, 200.0, "flac", 0, now - i))
    con.commit()
    P.rebuild_albums(con)
    con.commit()
    con.close()


class StubPlayer(QObject):
    """What the now-playing page touches on Player. Deliberately not the real
    one: it owns mpv, the MPRIS name and the queue socket."""
    queueChanged = Signal()
    currentChanged = Signal()
    playingChanged = Signal()

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {}

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return 0

    @Property(int, notify=queueChanged)
    def index(self):
        return -1

    @Property(float, notify=currentChanged)
    def position(self):
        return 0.0

    @Slot(int, int)
    def playAlbum(self, album_id, index):
        pass

    @Slot(int)
    def queueAlbum(self, album_id):
        pass

    @Slot(int)
    def jumpTo(self, index):
        pass

    @Slot(list, int)
    def playTracks(self, ids, start):
        pass


class StubLyrics(QObject):
    """LyricsProvider's one signal. The real one owns a worker thread and the
    LRCLIB requests; a lyric never arrives in this harness."""
    ready = Signal("QVariant")


class StubStyle(QObject):
    changed = Signal()

    @Property(bool, notify=changed)
    def plasma(self): return True
    @Property(str, notify=changed)
    def fontFamily(self): return "monospace"
    @Property(int, notify=changed)
    def fontSize(self): return 15
    @Property(bool, notify=changed)
    def topFontTreatment(self): return False
    @Property(bool, notify=changed)
    def airFontTreatment(self): return False
    @Property(bool, notify=changed)
    def smooth(self): return False
    @Property(bool, notify=changed)
    def terminalCell(self): return False
    @Property(bool, notify=changed)
    def reduceMotion(self): return True
    @Property(float, notify=changed)
    def animSpeed(self): return 1.0


class StubPalette(QObject):
    changed = Signal()

    @Property(QColor, notify=changed)
    def bg(self): return QColor("#101010")
    @Property(QColor, notify=changed)
    def bgAlt(self): return QColor("#202020")
    @Property(QColor, notify=changed)
    def border(self): return QColor("#303030")
    @Property(QColor, notify=changed)
    def accent(self): return QColor("#3ad0ff")
    @Property(QColor, notify=changed)
    def dim(self): return QColor("#404040")
    @Property(QColor, notify=changed)
    def text(self): return QColor("#e0e0e0")
    @Property(QColor, notify=changed)
    def textDim(self): return QColor("#a0a0a0")
    @Property(QColor, notify=changed)
    def highlight(self): return QColor("#0080ff")
    @Property(QColor, notify=changed)
    def ok(self): return QColor("#00ff00")
    @Property(QColor, notify=changed)
    def warn(self): return QColor("#ffff00")
    @Property(QColor, notify=changed)
    def crit(self): return QColor("#ff8000")
    @Property(QColor, notify=changed)
    def info(self): return QColor("#8000ff")


def spin(app, ms=200):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()


HARNESS_QML = b"""
import QtQuick
import QtQuick.Window
Window {
    width: 1406; height: 1006; visible: true
    NowPlaying { id: page; objectName: "nowPlaying"; anchors.fill: parent }
}
"""


def visual_items(item):
    """Walk the VISUAL tree: a view's row delegates are children of its
    contentItem visually, but hang off no QObject parent inside the page."""
    out = []
    for child in item.childItems():
        out.append(child)
        out.extend(visual_items(child))
    return out


def click(win, item, button, modifiers=Qt.NoModifier):
    """A real press/release on the centre of `item`, so the handler under test
    is the one the pointer would reach."""
    centre = item.mapToItem(win.contentItem(),
                            item.property("width") / 2, item.property("height") / 2)
    QTest.mouseClick(win, button, modifiers, centre.toPoint())


def menu_labels(menu):
    """The menu's own `items` array. The Plasma face builds real MenuItems in a
    native popup window, so nothing it draws is in this item tree."""
    value = menu.property("items")
    rows = list(value.toVariant() if hasattr(value, "toVariant") else value)
    return [str(r.get("label", "")) for r in rows if isinstance(r, dict)]


def tabs_of(pane):
    value = pane.property("tabs")
    return list(value.toVariant() if hasattr(value, "toVariant") else value)


def named(item, name):
    return [x for x in visual_items(item) if x.objectName() == name]


def texts(item):
    return [str(x.property("text")) for x in visual_items(item)
            if x.property("text") is not None and x.property("visible")]


def main():
    seed_db()
    qInstallMessageHandler(on_qml_message)
    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

    prefs = P.Prefs()
    library = P.Library(P.TagWriter(prefs))
    player = StubPlayer()
    bridge = P.Bridge(library, player, None)
    KEEP.extend([prefs, library, player, bridge])

    engine = QQmlApplicationEngine()
    # The +plasma face is the one this page belongs to.
    selector = QQmlFileSelector(engine, engine)
    selector.setExtraSelectors(["plasma"])
    ctx = engine.rootContext()
    style, palette = StubStyle(), StubPalette()
    KEEP.extend([style, palette])
    ctx.setContextProperty("OnAir", False)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Library", bridge)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Prefs", prefs)
    lyrics = StubLyrics()
    KEEP.append(lyrics)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("AlbumsModel", bridge.albumsModel)
    ctx.setContextProperty("AlbumTracksModel", bridge.albumTracksModel)
    ctx.setContextProperty("BrowseAlbumsModel", bridge.browseModel)
    ctx.setContextProperty("BrowseTracksModel", bridge.browseTracksModel)
    ctx.setContextProperty("QueueModel", bridge.queueModel)

    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.extend([comp, theme])
    ctx.setContextProperty("Theme", theme)

    bridge.refreshAlbums()
    spin(app, 100)

    wrap = QQmlComponent(engine)
    wrap.setData(HARNESS_QML, QUrl.fromLocalFile(str(QML / "allinone-harness.qml")))
    win = wrap.create(ctx)
    if win is None:
        print("FAIL  the harness window did not build:", wrap.errorString())
        return 1
    KEEP.extend([wrap, win])
    page = win.findChild(QObject, "nowPlaying")
    check("the Plasma face loaded", page is not None
          and page.property("face") == "plasma", page and page.property("face"))
    if page is None:
        return 1
    spin(app, 300)
    # Row delegates are built by the scene graph, not by the event loop.
    win.grabWindow()
    spin(app, 300)

    check("no QML warnings", not QML_MSGS, " | ".join(QML_MSGS))

    # ---------------------------------------------------------- maximized
    check("the page is expanded at 1406x1006", page.property("expanded") is True)
    pane = named(page, "nowInfoPane")
    check("the release pane is there", len(pane) == 1, len(pane))
    check("…with no lyrics tab", pane and tabs_of(pane[0]) == ["album", "similar"],
          pane and tabs_of(pane[0]))
    check("…and it is not showing lyrics", pane and pane[0].property("tab") != "lyrics",
          pane and pane[0].property("tab"))
    section = named(page, "lyricsSection")
    check("lyrics have a section of their own",
          section and section[0].property("visible") is True
          and section[0].property("height") > 60,
          section and section[0].property("height"))
    check("…in the lower half of the column",
          section and section[0].property("y") >= pane[0].property("height"),
          section and (section[0].property("y"), pane[0].property("height")))

    well = named(page, "browseWell")
    check("the album browser sits beside the queue",
          well and well[0].property("visible") is True and well[0].property("width") >= 280,
          well and well[0].property("width"))
    queue_well_right = None
    for x in visual_items(page):
        if x.objectName() == "browseWell":
            queue_well_right = x.property("x")
    check("…to the RIGHT of it", queue_well_right and queue_well_right > page.property("width") / 2,
          queue_well_right)
    check("…with its own search field", len(named(page, "browseSearch")) == 1)
    check("…and its own album rows", bridge.browseModel.count == 2, bridge.browseModel.count)
    # The tiles carry their album's name on hover, exactly like the gallery's,
    # so what proves they were drawn is the covers themselves.
    tiles = [x for x in named(page, "browseTile") if x.property("visible")]
    check("the browser drew a cover per album", len(tiles) == 2, len(tiles))

    # Clicking a cover drills into that album INSIDE the pane.
    browser = named(page, "albumBrowser")
    check("the browser was built", len(browser) == 1, len(browser))
    if browser:
        first = bridge.browseModel.get(0)["albumId"]
        QMetaObject.invokeMethod(browser[0], "openAlbum", Q_ARG("QVariant", first))
        spin(app, 200)
        win.grabWindow()
        spin(app, 200)
        check("…opening one shows its tracks in the pane",
              browser[0].property("openId") == first
              and bridge.browseTracksModel.count == 2,
              (browser[0].property("openId"), bridge.browseTracksModel.count))
        art = named(page, "openArt")
        rows = 3 * (theme.property("lineHeight") + 2) + 2 * 2
        check("…the cover no taller than the three lines beside it",
              art and abs(art[0].property("height") - rows) <= 1
              and abs(art[0].property("width") - art[0].property("height")) < 0.6,
              art and (art[0].property("height"), art[0].property("width"), rows))
        drilled = "\n".join(texts(page))
        check("…with the album's identity and a way back",
              "back" in drilled and "play" in drilled, drilled)
        QMetaObject.invokeMethod(browser[0], "openAlbum", Q_ARG("QVariant", 0))
        spin(app, 100)
        check("…and back returns to the covers",
              browser[0].property("openId") == 0 and bridge.browseTracksModel.count == 0,
              (browser[0].property("openId"), bridge.browseTracksModel.count))

    # Right-click and multi-selection, driven as real clicks on the covers so
    # the ctx the pane builds is the one under test — not one the harness made
    # up. The browser's covers get the same menu the gallery's do.
    menu = [x for x in visual_items(win.contentItem()) if x.objectName() == "browseAlbumMenu"]
    check("the browser has an album menu", len(menu) == 1, len(menu))
    tiles = [x for x in named(page, "browseTile") if x.property("visible")]
    if browser and menu and len(tiles) == 2:
        click(win, tiles[0], Qt.RightButton)
        spin(app, 150)
        labels = menu_labels(menu[0])
        for wanted in ("play", "play shuffled", "play next", "add to queue",
                       "open album", "search artist", "same person as...",
                       "create systheme", "move album to trash"):
            check("…the one-album menu offers " + wanted, wanted in labels, labels)
        QMetaObject.invokeMethod(menu[0], "close")
        spin(app, 100)

        # ctrl-click then shift-click picks a run, exactly like the gallery.
        click(win, tiles[0], Qt.LeftButton, Qt.ControlModifier)
        click(win, tiles[1], Qt.LeftButton, Qt.ShiftModifier)
        spin(app, 150)
        picked = browser[0].property("selectedIds")
        picked = list(picked.toVariant() if hasattr(picked, "toVariant") else picked)
        check("…ctrl and shift pick the run between two covers", len(picked) == 2, picked)
        click(win, tiles[1], Qt.RightButton)
        spin(app, 150)
        labels = menu_labels(menu[0])
        check("…and the set gets the mass menu",
              "play 2 albums" in labels and "play 2 albums shuffled" in labels
              and "add 2 albums to queue" in labels and "clear selection" in labels,
              labels)
        QMetaObject.invokeMethod(menu[0], "close")
        spin(app, 100)
        # A plain click is still a plain click: it drops the pick and opens.
        click(win, tiles[0], Qt.LeftButton)
        spin(app, 150)
        picked = browser[0].property("selectedIds")
        picked = list(picked.toVariant() if hasattr(picked, "toVariant") else picked)
        check("…a plain click drops the selection", picked == [], picked)
        QMetaObject.invokeMethod(browser[0], "openAlbum", Q_ARG("QVariant", 0))
        spin(app, 100)

    # The browser reads its own rows: opening an album here must not move the
    # gallery's open section.
    bridge.openAlbum(bridge.albumsModel.get(0)["albumId"])
    gallery_rows = [bridge.albumTracksModel.get(i)["title"]
                    for i in range(bridge.albumTracksModel.count)]
    other = bridge.albumsModel.get(1)["albumId"]
    bridge.openBrowseAlbum(other)
    spin(app, 100)
    check("opening an album in the browser fills ITS rows",
          bridge.browseTracksModel.count == 2, bridge.browseTracksModel.count)
    check("…and leaves the gallery's alone",
          [bridge.albumTracksModel.get(i)["title"]
           for i in range(bridge.albumTracksModel.count)] == gallery_rows,
          gallery_rows)

    # A filter here is the browser's own, not the gallery's.
    bridge.setBrowseFilter("boards")
    spin(app, 100)
    check("the browser's search filters only the browser",
          bridge.browseModel.count == 1 and bridge.albumsModel.count == 2,
          (bridge.browseModel.count, bridge.albumsModel.count))
    bridge.setBrowseFilter("")
    spin(app, 100)

    # ------------------------------------------------------------ compact
    win.setProperty("width", 480)
    win.setProperty("height", 826)
    spin(app, 200)
    win.grabWindow()
    spin(app, 200)
    check("the compact page is not expanded", page.property("expanded") is False)
    pane = named(page, "nowInfoPane")
    check("…and the lyrics tab is back",
          pane and tabs_of(pane[0]) == ["lyrics", "album", "similar"],
          pane and tabs_of(pane[0]))
    section = named(page, "lyricsSection")
    check("…with no separate lyrics section",
          not section or section[0].property("visible") is False)
    well = named(page, "browseWell")
    check("…and no album browser", not well or well[0].property("visible") is False)
    check("no QML warnings after resizing", not QML_MSGS, " | ".join(QML_MSGS))

    print("now-allinone-test: ok" if not FAILS
          else "now-allinone-test: %d failed" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
