#!/usr/bin/env python3
"""album-guest-ui-test.py — guest credits in the open album section, offscreen.

An album listing repeats its own artist on every row and says nothing by it;
the rows worth naming are the ones somebody ELSE is on. This builds the real
`Library`/`Bridge` over a scratch library.db, opens the real `AlbumPanel`, and
reads what the rows actually drew — so "the feature is wired but the panel
still passes showArtist: false" fails here rather than in front of him.

Offscreen, hard: no window on his screen, no contact with the live player, its
socket, its database or its audio device (nothing here builds a `Player`).

    apps/player/tools/album-guest-ui-test.py
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
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_tmp = tempfile.TemporaryDirectory(prefix="album-guest-ui-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())


def _relaunch_under_player_python():
    """See alias-ui-test.py — read the `player` wrapper for its python env,
    never source it (sourcing runs the wrapper's body, i.e. launches the app)."""
    if os.environ.get("GUEST_TEST_RELAUNCHED"):
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
    os.environ["GUEST_TEST_RELAUNCHED"] = "1"
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

from PySide6.QtCore import (Property, QObject, QUrl, QtMsgType, Signal, Slot,
                            qInstallMessageHandler)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem

sys.path.insert(0, str(APP))
import main as P  # noqa: E402

QML = APP / "qml"
KEEP = []
QML_MSGS = []
FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name
          + (("  " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


# Environment noise this harness cannot avoid and that says nothing about the
# panel: the desktop's generated icon theme is not installed under a scratch
# XDG_DATA_HOME, and Qt registers one type per file of the implicitly imported
# qml/ and qmlcommon/ directories when the root component comes from setData.
# Everything else — a binding to a missing property, a slot QML calls that the
# Bridge does not forward — still fails the run.
NOISE = ("Icon theme ", "qmlRegisterType requires absolute URLs")


def on_qml_message(mtype, ctx, msg):
    if (mtype in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            and not str(msg).startswith(NOISE)):
        QML_MSGS.append(msg)


# The shape of the real case: one album, most of it by the album's own artist,
# two tracks with a guest, and one whole other credit.
FIXTURE = [
    ("Intro (Like Velvet)", "NAO"),
    ("Adore You", "NAO feat. Abhi Dijon"),
    ("Trophy", "NAO feat. A. K. Paul"),
    ("Bad Blood", "NAO"),
    ("Girlfriend", "Mura Masa"),
]


def seed_db():
    con = P.open_db()
    now = time.time()
    # Real (empty) files in the scratch dir: a listing stats its rows and
    # prunes the ones whose file is gone, so a fake path lists nothing.
    audio = Path(_tmp.name) / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    for i, (title, artist) in enumerate(FIXTURE):
        path = audio / ("%d.flac" % i)
        path.write_bytes(b"")
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album,"
            " album_artist, track, disc, year, orig_year, duration, codec,"
            " play_count, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(path), 1.0, 100, title, artist, "For All We Know",
             "NAO", i + 1, 1, 2016, 2016, 200.0, "flac", 0, now - i))
    con.commit()
    P.rebuild_albums(con)
    con.commit()
    con.close()


class StubPlayer(QObject):
    """The members TrackList touches on Player. Deliberately not the real one:
    it owns mpv, the MPRIS name and the queue socket."""
    queueChanged = Signal()
    currentChanged = Signal()

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {}

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return 0

    @Slot(int, int)
    def playAlbum(self, album_id, index):
        pass

    @Slot(int)
    def queueAlbum(self, album_id):
        pass

    @Slot(list, int)
    def playTracks(self, ids, start):
        pass


class StubStyle(QObject):
    changed = Signal()

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
    """A flat palette with a saturated accent, so a tone that picked up the
    wallpaper hue is distinguishable from one that did not."""
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
    width: 1100; height: 700; visible: true
    AlbumPanel { id: panel; objectName: "albumPanel"; anchors.fill: parent }
}
"""


def visual_items(item):
    """Walk the VISUAL tree: a view's row delegates are children of its
    contentItem visually, but hang off no QObject parent inside the panel, so
    findChildren() returns not one of them."""
    out = []
    for child in item.childItems():
        out.append(child)
        out.extend(visual_items(child))
    return out


def items(item, name):
    return [x for x in visual_items(item) if x.objectName() == name]


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
    ctx = engine.rootContext()
    style, palette = StubStyle(), StubPalette()
    KEEP.extend([style, palette])
    ctx.setContextProperty("OnAir", False)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Library", bridge)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("AlbumTracksModel", bridge.albumTracksModel)

    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.append(theme)
    ctx.setContextProperty("Theme", theme)

    bridge.refreshAlbums()
    spin(app, 100)
    if bridge.albumsModel.count == 0:
        print("FAIL  the scratch album did not reach the gallery")
        return 1
    album_id = bridge.albumsModel.get(0)["albumId"]

    wrap = QQmlComponent(engine)
    wrap.setData(HARNESS_QML, QUrl.fromLocalFile(str(QML / "guest-harness.qml")))
    win = wrap.create(ctx)
    if win is None:
        print("FAIL  the harness window did not build:", wrap.errorString())
        return 1
    KEEP.extend([wrap, win])
    panel = win.findChild(QObject, "albumPanel")
    panel.setProperty("albumId", album_id)
    spin(app, 300)
    # A row delegate is built by the scene graph, not by the event loop: an
    # offscreen window is never exposed, so without a grab the list stays empty
    # and every assertion below passes on nothing.
    win.grabWindow()
    spin(app, 300)

    check("no QML warnings", not QML_MSGS, " | ".join(QML_MSGS))

    drawn = [(str(x.property("text")), x.property("color"), x.property("visible"))
             for x in items(panel, "trackArtist")]
    if not drawn:
        print("FAIL  no track rows were built")
        return 1
    shown = sorted(text for text, _, visible in drawn if visible and text)
    check("the guests are named beside their tracks",
          shown == ["Mura Masa", "feat. A. K. Paul", "feat. Abhi Dijon"], str(shown))
    check("the album's own artist is not repeated on any row",
          not any(t.strip().lower() == "nao" for t, _, _ in drawn), str(drawn))

    guest = next(c for t, c, v in drawn if t == "feat. A. K. Paul")
    titles = [x for x in visual_items(panel)
              if x.property("text") is not None and str(x.property("text")) == "Trophy"]
    check("the title is drawn too", titles, "no title item for Trophy")
    title_colour = titles[0].property("color") if titles else None
    check("the credit is not the title's colour", guest != title_colour,
          "%s == %s" % (guest.name() if guest else guest, title_colour))
    check("…nor the plain secondary grey", guest != QColor("#a0a0a0"), guest.name())
    check("…and it carries the theme's hue", guest.hue() == QColor("#3ad0ff").hue(),
          "%s hue %d" % (guest.name(), guest.hue()))
    # Subtle, not loud: a wash over the dim tone, never the accent itself.
    check("…subtly, not as the accent", guest != QColor("#3ad0ff"), guest.name())

    print(("album-guest-ui-test: ok" if not FAILS
           else "album-guest-ui-test: %d failed" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
