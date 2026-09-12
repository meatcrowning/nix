#!/usr/bin/env python3
"""Regression test for the album gallery's MULTI-SELECTION
(apps/player/qml/AlbumGrid.qml).

Ctrl-click picks covers one at a time and Shift-click takes the run from the
last one clicked; right-clicking inside that set offers play / play shuffled /
play next / add to queue for the whole set, which is how a discography or a
filtered result reaches the queue in one action. A plain click still just opens
a cover and drops the set, so browsing is unchanged.

The scene is the REAL Main.qml at 480x826 against the Bridge-shaped stubs in
album-playnext-test.py (imported, not copied — one stub set, one contract).
Nothing here opens a socket, a database, libmpv or the audio device.

Behind the QML sit Player.playAlbums / queueAlbums / playAlbumsNext, whose queue
arithmetic is guarded by queue-ops-test.py.

Run with player's own Qt env, offscreen (never the bare system python):

    QT_QPA_PLATFORM=offscreen $(tail -1 wr | grep -o '/nix/store/[^"]*/bin/python3') \
        apps/player/tools/album-multiselect-test.py
"""
import importlib.util
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYER = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(PLAYER), "pylib"))

_spec = importlib.util.spec_from_file_location(
    "album_playnext_test", os.path.join(HERE, "album-playnext-test.py"))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)          # defines the stubs; main() only runs as __main__

from PySide6.QtCore import QPoint, QPointF, QUrl, Qt      # noqa: E402
from PySide6.QtGui import QGuiApplication                 # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402
from PySide6.QtQuick import QQuickItem                    # noqa: E402
from PySide6.QtTest import QTest                          # noqa: E402

WIDTH, HEIGHT = H.WAIT, H.HEIGHT
FAILS = []
KEEP = []

#: 7 columns across 480px minus the 16px scrollbar -> 66px cells, so the first
#: three covers of the top row are centred here.
COVER_X = (33, 99, 165)
COVER_Y = 33


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name
          + ("  " + str(detail) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def main():
    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    albums = H.Rows(H.ALBUM_ROLES,
                    [{"albumId": i + 1, "album": "Album %d" % (i + 1),
                      "artist": "Artist %d" % (i + 1), "year": 1990 + i,
                      "thumbPath": ""} for i in range(21)])
    albumTracks = H.Rows(H.TRACK_ROLES, H.tracks(3))
    queue = H.Rows(H.TRACK_ROLES, H.tracks(8))
    playlist = H.Rows(H.TRACK_ROLES, H.tracks(6))
    search = H.Rows(H.TRACK_ROLES, H.tracks(6))
    pal, style = H.FakePalette(), H.FakeStyle()
    tb, prefs = H.FakeTitlebar(), H.FakePrefs()
    lib, ply, lyr = H.FakeLibrary(), H.FakePlayer(), H.FakeLyrics()
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
    win.setWidth(WIDTH)
    win.setHeight(HEIGHT)
    H.spin(app, 400)

    content = next(i for i in win.findChildren(QQuickItem) if i.parentItem() is None)
    grid = H.find_objectname(content, "albumList")
    menu = H.find_objectname(content, "albumCtxMenu")
    check("the gallery and its menu are in the tree", grid is not None and menu is not None)
    if grid is None or menu is None:
        return 1
    # `albumList` is the ListView; the selection lives on the AlbumGrid above it.
    gridRoot = grid.parentItem()

    def click(x, y, mods=Qt.KeyboardModifier.NoModifier, button=Qt.MouseButton.LeftButton):
        QTest.mouseClick(win, button, mods, QPoint(x, y))
        H.spin(app, 200)

    def selection():
        # A `var` property comes back as a QJSValue, not a list.
        v = gridRoot.property("selectedIds")
        v = v.toVariant() if hasattr(v, "toVariant") else v
        return [int(x) for x in (v or [])]

    def menu_delegates():
        """The menu rows in VISUAL order — the delegates are the panel Column's
        children (album-playnext-test.py's route; a descendants() walk comes
        back reversed, which would hide a wrong menu order)."""
        panels = [c for c in menu.childItems()
                  if c.metaObject().className().find("Rectangle") >= 0]
        if not panels or not panels[0].childItems():
            return []
        return [it for it in panels[0].childItems()[0].childItems()
                if isinstance(it.property("modelData"), dict)]

    def menu_rows():
        out = []
        for it in menu_delegates():
            md = it.property("modelData")
            if md.get("separator") is not True and md.get("label"):
                out.append((md.get("label"), md.get("enabled", True)))
        return out

    def click_row(label):
        for it in menu_delegates():
            md = it.property("modelData")
            if md.get("label") == label:
                for kid in H.descendants(it):
                    if kid.metaObject().className().find("MouseArea") >= 0:
                        c = kid.mapToScene(QPointF(kid.width() / 2, kid.height() / 2))
                        QTest.mouseClick(win, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier,
                                         QPoint(round(c.x()), round(c.y())))
                        H.spin(app, 200)
                        return True
        return False

    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier

    # -- 1. ctrl-click picks covers without opening them ---------------------
    click(COVER_X[0], COVER_Y, ctrl)
    click(COVER_X[1], COVER_Y, ctrl)
    check("ctrl-click picks two covers", selection() == [1, 2], selection())
    check("...and opens neither", gridRoot.property("expandedAlbumId") == 0,
          gridRoot.property("expandedAlbumId"))
    check("ctrl-clicking a picked cover unpicks it",
          (click(COVER_X[1], COVER_Y, ctrl), selection())[1] == [1], selection())
    click(COVER_X[1], COVER_Y, ctrl)

    # -- 2. the menu inside the set acts on the set --------------------------
    ply.calls = []
    ply._qlen = 8
    click(COVER_X[1], COVER_Y, button=Qt.MouseButton.RightButton)
    rows = menu_rows()
    check("right-clicking inside the set offers the set's actions",
          rows == [("play 2 albums", True), ("play 2 albums shuffled", True),
                   ("play 2 albums next", True), ("add 2 albums to queue", True),
                   ("clear selection", True)], rows)
    check("'add 2 albums to queue' is clickable", click_row("add 2 albums to queue"))
    check("...and queues both albums, in gallery order",
          ("queueAlbums", [1, 2]) in ply.calls, ply.calls)
    check("...and the set survives the action", selection() == [1, 2], selection())

    # -- 3. with an empty queue 'play next' is disabled, as for one album ----
    ply._qlen = 0
    click(COVER_X[1], COVER_Y, button=Qt.MouseButton.RightButton)
    check("with an empty queue, 'play 2 albums next' is disabled",
          ("play 2 albums next", False) in menu_rows(), menu_rows())
    click(400, 700)                       # dismiss, and clear the set
    ply._qlen = 8

    # -- 4. shift-click takes the run from the last cover clicked ------------
    click(COVER_X[0], COVER_Y)            # plain: anchors here, opens album 1
    click(COVER_X[2], COVER_Y, shift)
    check("shift-click selects the run", selection() == [1, 2, 3], selection())
    click(COVER_X[1], COVER_Y, shift)
    check("a second shift-click re-aims the run from the same anchor",
          selection() == [1, 2], selection())

    # -- 5. a plain click drops the set; a menu outside it is the one-album one
    click(COVER_X[2], COVER_Y)
    check("a plain click clears the set", selection() == [], selection())
    click(COVER_X[0], COVER_Y, ctrl)
    click(COVER_X[1], COVER_Y, ctrl)
    click(COVER_X[2], COVER_Y, button=Qt.MouseButton.RightButton)
    rows = [r[0] for r in menu_rows()]
    check("right-clicking OUTSIDE the set keeps the one-album menu",
          rows[:4] == ["play", "play shuffled", "play next", "add to queue"], rows)
    check("...and leaves the set alone", selection() == [1, 2], selection())

    print("\nFAILURES: %d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
