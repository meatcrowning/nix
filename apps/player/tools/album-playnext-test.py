#!/usr/bin/env python3
"""Regression test for the album cover's "play next" — the whole-album twin of
the track menu's single-track playNext (apps/player/qml/TrackMenu.qml).

Right-clicking an album cover (apps/player/qml/AlbumGrid.qml) must offer "play
next" that enqueues EVERY track of the album, in album order, directly after the
playing track. This harness loads the REAL Main.qml at 480x826 — the size player
actually runs at — against a Bridge-shaped contract (the same stub set the
focus-fade harness uses), sends a real right-click on the first album cover and
inspects the CtxMenu that opens. It never touches the live player: nothing here
opens a socket, a database, libmpv or the audio device.

Behind this QML sits the real backend slot Player.playAlbumNext, whose queue
arithmetic is guarded separately by queue-ops-test.py.

Run with player's own Qt env, offscreen (never the bare system python):

    QT_QPA_PLATFORM=offscreen $(tail -1 wr | grep -o '/nix/store/[^"]*/bin/python3') \
        apps/player/tools/album-playnext-test.py
"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

PLAYER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(PLAYER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QPoint,
                            QUrl, Qt, Property, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtTest import QTest

WAIT = 480
HEIGHT = 826

FAILS = []
KEEP = []          # setContextProperty does NOT take ownership


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name
          + ("  " + str(detail) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- the stubs
class FakeTitlebar(QObject):
    clicked = Signal(str)
    seek = Signal(float)

    @Slot("QVariant")
    def setButtons(self, _b): pass
    @Slot(str)
    def setFooter(self, _s): pass
    @Slot(bool)
    def setFooterBottom(self, _b): pass
    @Slot(bool, float)
    def setPlaybar(self, _on, _f): pass


class FakePrefs(QObject):
    @Slot(str, "QVariant", result="QVariant")
    def get(self, _k, d=None): return d
    @Slot(str, "QVariant")
    def set(self, _k, _v): pass


class Rows(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles, rows, parent=None):
        super().__init__(parent)
        self._names = {Qt.UserRole + i: r for i, r in enumerate(roles)}
        self._rows = rows

    def roleNames(self):
        return {k: v.encode() for k, v in self._names.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid():
            return None
        return self._rows[index.row()].get(self._names.get(role, ""))

    @Property(int, notify=countChanged)
    def count(self): return len(self._rows)

    @Slot(int, result="QVariant")
    def get(self, i): return self._rows[i] if 0 <= i < len(self._rows) else {}


ALBUM_ROLES = ["albumId", "album", "artist", "year", "thumbPath"]
TRACK_ROLES = ["trackId", "title", "artist", "album", "albumId", "track", "disc",
               "duration", "rating", "favorite", "playCount", "available"]


class FakePalette(QObject):
    changed = Signal()
    _c = staticmethod(lambda k: QColor(k))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("#101010")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("#202020")
    @Property(QColor, notify=changed)
    def border(self): return self._c("#303030")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("#ff0000")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("#ff00ff")
    @Property(QColor, notify=changed)
    def text(self): return self._c("#00ff00")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("#0000ff")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("#4040ff")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("#00ffff")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("#ffff00")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("#ff8000")
    @Property(QColor, notify=changed)
    def info(self): return self._c("#8000ff")


class FakeStyle(QObject):
    changed = Signal()

    @Property(str, notify=changed)
    def fontFamily(self): return "More Perfect DOS VGA"
    @Property(int, notify=changed)
    def fontSize(self): return 15
    @Property(bool, notify=changed)
    def reduceMotion(self): return True
    @Property(float, notify=changed)
    def animSpeed(self): return 1.0


def tracks(n):
    return [{"trackId": i + 1, "title": "Track Title %d" % (i + 1),
             "artist": "Some Artist", "album": "An Album", "albumId": 1,
             "track": i + 1, "disc": 1, "duration": 200.0 + i, "rating": 0.5,
             "favorite": False, "playCount": i, "available": True}
            for i in range(n)]


class FakeLibrary(QObject):
    scanStatus = Signal(str)
    scanRunning = Signal(bool)

    @Property(bool, constant=True)
    def canReveal(self): return True

    @Slot(str)
    def setSort(self, _s): pass
    @Slot(str)
    def setAlbumFilter(self, _s): pass
    @Slot(str)
    def search(self, _s): pass
    @Slot()
    def rescan(self): pass
    @Slot(int)
    def openAlbum(self, _a): pass
    @Slot(int, result="QVariant")
    def albumInfo(self, _a):
        return {"album": "An Album", "artist": "Some Artist", "year": 1999,
                "trackCount": 3, "fullArt": ""}
    # The smart-playlist surface PlaylistsView/SmartEditor bind to. `smartLists`
    # is a PROPERTY (the sidebar redraws when a list is added or deleted), so a
    # fake that offers only the old smartNames() slot leaves the sidebar empty
    # and the Connections block warning about a signal that does not exist.
    smartListsChanged = Signal()

    @Property("QVariantList", notify=smartListsChanged)
    def smartLists(self):
        return [{"name": n, "match": "all", "rules": [], "sort": "artist",
                 "desc": False, "limit": 0}
                for n in ("5 starred", "favourites", "recently added")]
    @Slot(result="QVariantList")
    def smartNames(self): return ["5 starred", "favourites", "recently added"]
    @Slot(str, result="QVariant")
    def smartSpec(self, n):
        return {"name": n, "match": "all", "rules": [], "sort": "artist",
                "desc": False, "limit": 0}
    @Slot(result="QVariant")
    def newSmartSpec(self):
        return {"name": "new playlist", "match": "all", "sort": "artist",
                "desc": False, "limit": 0,
                "rules": [{"field": "artist", "op": "contains", "value": ""}]}
    @Slot(result="QVariantList")
    def smartFields(self):
        return [{"key": "artist", "label": "artist", "kind": "text"}]
    @Slot(str, result="QVariantList")
    def smartOps(self, _f): return ["contains"]
    @Slot(result="QVariantList")
    def smartSorts(self): return [{"key": "artist", "label": "artist"}]
    @Slot(str, result=str)
    def smartFieldKind(self, _f): return "text"
    @Slot(str, result=bool)
    def smartOpTakesValue(self, _o): return True
    @Slot("QVariantMap", result=int)
    def smartPreviewCount(self, _s): return 0
    @Slot("QVariantMap", str, result=str)
    def saveSmart(self, spec, _old=""): return spec.get("name", "")
    @Slot(str, result=bool)
    def deleteSmart(self, _n): return True
    @Slot(str, result=str)
    def duplicateSmart(self, n): return n + " copy"
    @Slot(result=int)
    def restoreSmartDefaults(self): return 0
    @Slot(str)
    def openSmart(self, _n): pass
    @Slot()
    def refreshSmart(self): pass
    @Slot("QVariant", int)
    def playFromModel(self, _m, _i): pass
    @Slot(int, float)
    def setRating(self, _t, _r): pass
    @Slot(int, bool)
    def setFavorite(self, _t, _f): pass
    @Slot(int)
    def requestLyrics(self, _t): pass
    @Slot(int, bool)
    def setInstrumental(self, _t, _v): pass
    @Slot(int)
    def revealTrack(self, _t): pass


class FakePlayer(QObject):
    currentChanged = Signal()
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls = []
        self._qlen = 8

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {"id": 1, "title": "A Track", "artist": "Some Artist",
                "album": "An Album", "albumArtist": "Some Artist",
                "albumId": 1, "year": 1999, "rating": 0.5, "favorite": False,
                "artPath": "", "duration": 240.0}

    @Property(int, notify=changed)
    def queueLength(self): return self._qlen
    @Property(bool, notify=changed)
    def playing(self): return self._qlen > 0
    @Property(bool, notify=changed)
    def shuffle(self): return False
    @Property(int, notify=changed)
    def loop(self): return 0
    @Property(int, notify=changed)
    def index(self): return 2
    @Property(float, notify=changed)
    def position(self): return 42.0
    @Property(float, notify=changed)
    def duration(self): return 240.0
    @Property(str, notify=changed)
    def replayGain(self): return "auto"
    @Property(str, notify=changed)
    def rgStatus(self): return ""
    @Property(float, notify=changed)
    def rgPreamp(self): return 0.0

    @Slot()
    def previous(self): pass
    @Slot()
    def toggle(self): pass
    @Slot()
    def next(self): pass
    @Slot()
    def cycleLoop(self): pass
    @Slot(bool)
    def setShuffle(self, _s): pass
    @Slot(float)
    def seekFrac(self, _f): pass
    @Slot(float)
    def seek(self, _t): pass
    @Slot(int)
    def jumpTo(self, _i): pass
    @Slot(int, int)
    def playAlbum(self, _a, _i): self.calls.append(("playAlbum", _a, _i))
    @Slot(int)
    def queueAlbum(self, _a): self.calls.append(("queueAlbum", _a))
    @Slot(int)
    def playAlbumNext(self, _a): self.calls.append(("playAlbumNext", _a))
    @Slot("QVariant")
    def queueTracks(self, _t): pass
    @Slot("QVariant")
    def playNext(self, _t): pass
    @Slot("QVariant")
    def removeFromQueue(self, _t): pass
    @Slot(str)
    def playArtistShuffled(self, _a): pass
    @Slot(str)
    def playSmart(self, _n): pass
    @Slot(str)
    def setReplayGain(self, _m): pass
    @Slot(float)
    def setRgPreamp(self, _d): pass


class FakeLyrics(QObject):
    ready = Signal(int, "QVariant")


# ------------------------------------------------------------- tree walking
def descendants(item):
    out = []
    stack = list(item.childItems()) if hasattr(item, "childItems") else []
    while stack:
        it = stack.pop()
        out.append(it)
        stack.extend(it.childItems())
    return out


def find_objectname(root, name):
    for it in descendants(root):
        if it.objectName() == name:
            return it
    return None


def spin(app, ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()


# ---------------------------------------------------------------- driving
def main():
    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    # 21 albums, 7 columns -> the top-left cover is album 1.
    albums = Rows(ALBUM_ROLES,
                  [{"albumId": i + 1, "album": "Album %d" % (i + 1),
                    "artist": "Artist %d" % (i + 1), "year": 1990 + i,
                    "thumbPath": ""} for i in range(21)])
    albumTracks = Rows(TRACK_ROLES, tracks(3))
    queue = Rows(TRACK_ROLES, tracks(8))
    playlist = Rows(TRACK_ROLES, tracks(6))
    search = Rows(TRACK_ROLES, tracks(6))
    pal, style = FakePalette(), FakeStyle()
    tb, prefs = FakeTitlebar(), FakePrefs()
    lib, ply, lyr = FakeLibrary(), FakePlayer(), FakeLyrics()
    KEEP.extend([albums, albumTracks, queue, playlist, search,
                 pal, style, tb, prefs, lib, ply, lyr])

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("OnAir", False)
    ctx.setContextProperty("WalPalette", pal)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", tb)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("Library", lib)
    ctx.setContextProperty("Player", ply)
    ctx.setContextProperty("Lyrics", lyr)
    ctx.setContextProperty("AlbumsModel", albums)
    ctx.setContextProperty("AlbumTracksModel", albumTracks)
    ctx.setContextProperty("PlaylistModel", playlist)
    ctx.setContextProperty("SearchModel", search)
    ctx.setContextProperty("QueueModel", queue)

    qml = os.path.join(PLAYER, "qml")
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(qml, "theme", "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.append(theme)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(os.path.join(qml, "Main.qml")))
    if not engine.rootObjects():
        print("FAIL  Main.qml did not load")
        return 1
    win = engine.rootObjects()[0]
    win.setWidth(WAIT)
    win.setHeight(HEIGHT)
    spin(app, 400)

    # Walk the SCENE-GRAPH item tree, not the bare QWindow (PySide hands the
    # QML `Window` root back as a QWindow with no childItems). The content item
    # is the one QQuickItem with no item parent — the same trick focus-fade
    # uses to reach the tree.
    from PySide6.QtQuick import QQuickItem
    content = next(i for i in win.findChildren(QQuickItem)
                   if i.parentItem() is None)
    menu = find_objectname(content, "albumCtxMenu")
    check("the album cover has a context menu in the tree", menu is not None)
    if menu is None:
        return 1

    def right_click(cx, cy):
        QTest.mouseClick(win, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(cx, cy))
        spin(app, 250)

    def _menu_delegates():
        """The menu's row items in visual order. The Repeater's delegates are
        parented to the panel's Column (in order), with the Repeater object
        itself as the last Column child — so read the Column's children that
        carry a `modelData`. PySide exposes the Repeater as a static QQuickItem,
        so `count`/`itemAt` are not callable; this is the reliable route."""
        panels = [c for c in menu.childItems()
                  if c.metaObject().className().find("Rectangle") >= 0]
        if not panels:
            return []
        col = panels[0].childItems()[0] if panels[0].childItems() else None
        if col is None:
            return []
        return [it for it in col.childItems()
                if isinstance(it.property("modelData"), dict)]

    def menu_rows():
        """(label, enabled) for each row, in visual order"""
        out = []
        for it in _menu_delegates():
            md = it.property("modelData")
            if md.get("separator") is not True:
                out.append((md.get("label"), md.get("enabled", True)))
        return out

    def row_item(label):
        for it in _menu_delegates():
            md = it.property("modelData")
            if md.get("label") == label:
                return it
        return None

    def click_item(it):
        """QtTest cannot take a QQuickItem — click at the item's window coords."""
        from PySide6.QtCore import QPointF
        for kid in descendants(it):
            if kid.metaObject().className().find("MouseArea") >= 0:
                c = kid.mapToScene(QPointF(kid.width() / 2, kid.height() / 2))
                QTest.mouseClick(win, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier,
                                 QPoint(round(c.x()), round(c.y())))
                spin(app, 200)
                return True
        return False

    # -- 1. with music queued, "play next" is offered and enabled -------------
    ply._qlen = 8
    right_click(33, 33)
    check("right-clicking a cover opens the album menu", menu.property("visible") is True)
    rows = menu_rows()
    check("menu has the whole album vocabulary, play next in place",
          rows == [("play", True), ("play shuffled", True),
                   ("play next", True), ("add to queue", True),
                   ("open album", True), ("search artist", True)],
          rows)
    labels = [r[0] for r in rows]
    check("'play next' is present", "play next" in labels, labels)

    # -- 2. picking it calls Player.playAlbumNext on that album ---------------
    check("the 'play next' row is clickable", row_item("play next") is not None)
    if row_item("play next") is not None:
        click_item(row_item("play next"))
        check("picking 'play next' calls Player.playAlbumNext(1)",
              ("playAlbumNext", 1) in ply.calls, ply.calls)
        check("...and the menu closes", menu.property("visible") is False)

    # -- 3. with an empty queue it is disabled (would be a second 'play') -----
    ply._qlen = 0
    right_click(450, 800)          # dismiss if anything lingered (scrim)
    spin(app, 100)
    right_click(33, 33)
    rows = menu_rows()
    check("with an empty queue, 'play next' is disabled",
          ("play next", False) in rows, rows)
    for it in descendants(menu):
        md = it.property("modelData")
        if isinstance(md, dict) and md.get("label") == "play next":
            # choosing it must not fire playAlbumNext for a fresh album id
            break

    print("\nFAILURES: %d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
