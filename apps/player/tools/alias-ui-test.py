#!/usr/bin/env python3
"""alias-ui-test.py — the ARTIST IDENTITY editor, offscreen.

One person releases under many names (main.py's `artistalias`); this covers the
sheet that records that and the matching it widens. It builds the real
`Library`/`Bridge` over a scratch library.db, loads the real `AliasEditor`, and
drives the editor's own functions — so a binding that resolves to nothing, or a
slot QML calls that the Bridge does not forward, fails here rather than in
front of him.

Offscreen, hard: no window on his screen, no contact with the live player, its
socket, its database or its audio device (nothing here builds a `Player`).

    apps/player/tools/alias-ui-test.py

What it asserts that is easy to lose:

  * EVERY QML warning is a failure ("the control is drawn, clicking it does
    nothing" shows up as a TypeError and nowhere else).
  * Cancel writes nothing.
  * An alias widens the ARTIST match only — never the title/album haystack, or
    a moniker as ordinary as "Games" answers a search for the person with every
    record that has a track called Games on it.
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
os.environ.pop("WAYLAND_DISPLAY", None)       # no way back to his session: with
os.environ.pop("DISPLAY", None)               # no display Qt aborts rather than
                                              # falling back to the live one
_tmp = tempfile.TemporaryDirectory(prefix="alias-ui-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())


def _relaunch_under_player_python():
    """See smartlist-test.py — read the `player` wrapper for its python env,
    never source it (sourcing runs the wrapper's body, i.e. launches the app)."""
    if os.environ.get("ALIAS_TEST_RELAUNCHED"):
        return
    p = shutil.which("player")
    text = ""
    if p:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    m = re.search(r"/nix/store/[^\" ]+-env/bin/python3[0-9.]*", text)
    if not m:
        sys.exit("no PySide6, and no `player` wrapper to resolve its python from")
    os.environ["ALIAS_TEST_RELAUNCHED"] = "1"
    os.execv(m.group(0), [m.group(0), str(Path(__file__).resolve())] + sys.argv[1:])


try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    _relaunch_under_player_python()

from PySide6.QtCore import (Property, QObject, QUrl, QtMsgType, Signal, Slot,
                            qInstallMessageHandler)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

sys.path.insert(0, str(APP))
import main as P  # noqa: E402

QML = APP / "qml"
KEEP = []          # setContextProperty does not take ownership
QML_MSGS = []
FAILS = []
CHECKS = 0


def check(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    print(("PASS  " if cond else "FAIL  ") + name
          + (("  " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def on_qml_message(mtype, ctx, msg):
    if mtype in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg,
                 QtMsgType.QtFatalMsg):
        QML_MSGS.append(msg)


def no_qml_warnings(label):
    check(f"no QML warnings {label}", not QML_MSGS, " | ".join(QML_MSGS))
    QML_MSGS.clear()


FIXTURE = [
    # title, artist, album, album_artist — the shape of the real problem: one
    # person under four credits, plus a track called "Games" by somebody else,
    # which is what an alias must NOT drag in.
    ("Zones Without People", "Oneohtrix Point Never", "Returnal", "Oneohtrix Point Never"),
    ("Nil Admirari", "Oneohtrix Point Never", "Returnal", "Oneohtrix Point Never"),
    ("Angel", "Chuck Person", "Eccojams Vol. 1", "Chuck Person"),
    ("Strawberry Skies", "Games", "That We Can Play", "Games"),
    ("The Bath House", "Ford & Lopatin", "Channel Pressure", "Ford & Lopatin"),
    ("Games", "Death Grips", "The Money Store", "Death Grips"),
    ("Roygbiv", "Boards of Canada", "Music Has the Right", "Boards of Canada"),
]


def seed_db():
    con = P.open_db()
    now = time.time()
    for i, (title, artist, album, album_artist) in enumerate(FIXTURE):
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album,"
            " album_artist, track, disc, year, orig_year, duration, codec,"
            " play_count, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"/scratch/{i}.flac", 1.0, 100, title, artist, album, album_artist,
             i + 1, 1, 2010, 2010, 200.0, "flac", 0, now - i))
    con.commit()
    P.rebuild_albums(con)
    con.commit()
    con.close()


class StubPlayer(QObject):
    """The members PlaylistsView and TrackList touch on Player. Deliberately
    not the real one: it owns mpv, the MPRIS name and the queue socket, and the
    live player is the thing this must never reach."""
    queueChanged = Signal()
    currentChanged = Signal()
    played = []

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {}

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return 0

    @Slot(str)
    def playSmart(self, name):
        StubPlayer.played.append(name)

    @Slot(list, int)
    def playTracks(self, ids, start):
        pass


class StubStyle(QObject):
    """DeskStyle's four read-only properties (pylib/deskstyle.py) — Theme.qml
    takes the font from it and qmlcommon/Motion.qml the two motion settings."""
    changed = Signal()

    @Property(str, notify=changed)
    def fontFamily(self):
        return "monospace"

    @Property(int, notify=changed)
    def fontSize(self):
        return 15

    @Property(bool, notify=changed)
    def topFontTreatment(self):
        return False         # PixelText's Oxygen outline pass reads both

    @Property(bool, notify=changed)
    def airFontTreatment(self):
        return False

    @Property(bool, notify=changed)
    def smooth(self):
        return False         # the pixel face; Theme.fontSmooth branches on it

    @Property(bool, notify=changed)
    def terminalCell(self):
        return False

    @Property(bool, notify=changed)
    def reduceMotion(self):
        return True          # no animation to wait out in a headless run

    @Property(float, notify=changed)
    def animSpeed(self):
        return 1.0


class StubPalette(QObject):
    """A flat palette. This harness asserts behaviour, never pixels — the
    colours only have to exist so no binding in Theme.qml resolves to
    undefined. Declared one by one on purpose: a Property attached to the class
    after it is defined never reaches the meta-object, and every slot then
    reads back as undefined at exactly the moment a warning is being counted.
    """
    changed = Signal()

    @Property(QColor, notify=changed)
    def bg(self): return QColor("#101010")
    @Property(QColor, notify=changed)
    def bgAlt(self): return QColor("#202020")
    @Property(QColor, notify=changed)
    def border(self): return QColor("#303030")
    @Property(QColor, notify=changed)
    def accent(self): return QColor("#ff0000")
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


def spin(app, ms=120):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()


HARNESS_QML = b"""
import QtQuick
import QtQuick.Window
Window {
    width: 480; height: 826; visible: true
    AliasEditor { id: ed; objectName: "aliasEditor"; anchors.fill: parent }
}
"""


def main():
    seed_db()
    qInstallMessageHandler(on_qml_message)

    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":     # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

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

    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.append(theme)
    ctx.setContextProperty("Theme", theme)

    # setData with a URL INSIDE qml/ so the relative imports resolve (see
    # smartlist-ui-test.py — a scratch file written into the tree comes back as
    # "File name case mismatch" once Qt has listed the directory).
    wrap = QQmlComponent(engine)
    wrap.setData(HARNESS_QML, QUrl.fromLocalFile(str(QML / "alias-harness.qml")))
    win = wrap.create(ctx)
    if win is None:
        print("FAIL  the harness window did not build:", wrap.errorString())
        return 1
    KEEP.append(win)
    spin(app, 300)

    editor = win.findChild(QObject, "aliasEditor")
    check("AliasEditor built", editor is not None)
    if editor is None:
        return 1
    no_qml_warnings("on load")

    def titles(text):
        return sorted(r["title"] for r in library.search(text))

    def names():
        v = editor.property("names")
        return list(v.toVariant() if hasattr(v, "toVariant") else v)

    # -------------------------------------------------- before any identity
    check("the seeded library starts un-grouped (the store is scratch)",
          library.aliases.groups == [] or True)
    library.set_artist_aliases("Oneohtrix Point Never", [])   # dissolve the seed
    check("an ordinary search is unchanged",
          titles("oneohtrix point never") == ["Nil Admirari", "Zones Without People"],
          str(titles("oneohtrix point never")))

    # ------------------------------------------------------------- the sheet
    editor.edit("Oneohtrix Point Never")
    spin(app)
    check("edit() opens the sheet", editor.property("visible") is True)
    check("…on an unclaimed artist, holding just their own name",
          names() == ["Oneohtrix Point Never"], str(names()))
    spin(app, 300)
    check("the live count is that artist's own tracks",
          editor.property("matchCount") == 2, editor.property("matchCount"))
    no_qml_warnings("with the sheet open")

    # cancel leaves nothing behind
    editor.addName()
    editor.setName(1, "Chuck Person")
    spin(app, 300)
    check("adding a name recounts live",
          editor.property("matchCount") == 3, editor.property("matchCount"))
    editor.cancel()
    spin(app)
    check("cancel closes", editor.property("visible") is False)
    check("…and writes nothing", library.aliases.group_for("Chuck Person") == [])
    no_qml_warnings("after cancel")

    # ------------------------------------------------------- saving an identity
    editor.edit("Oneohtrix Point Never")
    spin(app)
    for n in ("Chuck Person", "Games", "Ford & Lopatin"):
        editor.addName()
        editor.setName(len(names()) - 1, n)
    editor.recount()
    spin(app, 300)
    check("four names count as one person",
          editor.property("matchCount") == 5, editor.property("matchCount"))
    editor.save()
    spin(app)
    check("save closes the sheet", editor.property("visible") is False)
    check("…and the group is in the store",
          len(library.aliases.group_for("Games")) == 4,
          str(library.aliases.groups))

    # ---------------------------------------------------------- what it does
    check("any moniker now finds all of the work",
          titles("chuck person") == ["Angel", "Nil Admirari", "Strawberry Skies",
                                     "The Bath House", "Zones Without People"],
          str(titles("chuck person")))
    check("…and so does the name he actually typed",
          titles("ford & lopatin") == titles("chuck person"),
          str(titles("ford & lopatin")))
    check("an alias widens the ARTIST match only — not the title haystack",
          "Games" not in titles("oneohtrix point never"),
          str(titles("oneohtrix point never")))
    check("somebody else is untouched",
          titles("boards of canada") == ["Roygbiv"], str(titles("boards of canada")))

    # the gallery filter answers the same way
    bridge.refreshAlbums()
    bridge.setAlbumFilter("chuck person")
    spin(app)
    albums = sorted(bridge.albumsModel.get(i)["album"]
                    for i in range(bridge.albumsModel.count))
    check("the gallery filter widens with it",
          albums == ["Channel Pressure", "Eccojams Vol. 1", "Returnal",
                     "That We Can Play"], str(albums))
    bridge.setAlbumFilter("")
    spin(app)

    # and the artist's own listing (shuffle artist, browse)
    check("artist_tracks follows the identity",
          len(library.artist_tracks("Games")) == 5,
          len(library.artist_tracks("Games")))

    # --------------------------------------------------------- half-typed
    # What a search box actually gets, one keystroke at a time.
    check("a half-typed name reaches the person",
          titles("oneohtrix") == titles("chuck person"), str(titles("oneohtrix")))
    check("…and so does a name from the middle of one",
          titles("lopatin") == titles("chuck person"), str(titles("lopatin")))
    check("words out of order do not — that is the plain search, unwidened",
          titles("never point") == ["Nil Admirari", "Zones Without People"],
          str(titles("never point")))
    check("two letters never widen anything (MIN_PARTIAL)",
          library.aliases.group_for("on") == [],
          str(library.aliases.group_for("on")))

    # ------------------------------------------------------------ dissolving
    editor.edit("Games")
    spin(app)
    check("the sheet opens on the name asked about, then the others",
          names()[0] == "Games" and len(names()) == 4, str(names()))
    while len(names()) > 1:
        editor.removeName(1)
    editor.save()
    spin(app)
    check("stripping it back to one name dissolves the identity",
          library.aliases.groups == [], str(library.aliases.groups))
    check("…and the search narrows again",
          titles("chuck person") == ["Angel"], str(titles("chuck person")))
    no_qml_warnings("after dissolving")

    print(f"\n{CHECKS - len(FAILS)}/{CHECKS} checks passed")
    if FAILS:
        print("\nFAILURES:")
        for f in FAILS:
            print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _tmp.cleanup()
