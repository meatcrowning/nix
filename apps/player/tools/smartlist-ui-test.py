#!/usr/bin/env python3
"""smartlist-ui-test.py — the smart-playlist EDITOR, offscreen.

`smartlist-test.py` covers the rules; this covers the view that writes them.
It builds the real `Library`/`Bridge` over a scratch library.db and a scratch
smartlists.json, loads the real `PlaylistsView` (and with it `SmartEditor`,
`SelectButton` and `CtxMenu`), and drives the editor's own functions — so a
binding that resolves to nothing, a slot QML calls that the Bridge does not
forward, or a rule the editor writes that the SQL builder will not accept all
fail here rather than in front of him.

Offscreen, hard: no window on his screen, no contact with the live player, its
socket, its database or its audio device (nothing here builds a `Player` — the
view's Player is a stub with the two members it touches).

    apps/player/tools/smartlist-ui-test.py

Two things it asserts that are easy to lose:

  * EVERY QML warning is a failure. The whole class of bug this file exists for
    ("the control is drawn, clicking it does nothing") shows up as a
    TypeError in `qs log`-shaped output and nowhere else.
  * The store never sees a keystroke that was cancelled.
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
_tmp = tempfile.TemporaryDirectory(prefix="smartlist-ui-")
for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = str(Path(_tmp.name) / var.lower())


def _relaunch_under_player_python():
    """See smartlist-test.py — read the `player` wrapper for its python env,
    never source it (sourcing runs the wrapper's body, i.e. launches the app)."""
    if os.environ.get("SMARTLIST_TEST_RELAUNCHED"):
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
    os.environ["SMARTLIST_TEST_RELAUNCHED"] = "1"
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
    # title, artist, album, rating, favorite, plays
    ("Alpha", "Boards of Canada", "Geogaddi", 1.0, 0, 40),
    ("Beta", "Boards of Canada", "Geogaddi", 0.79, 1, 12),
    ("Gamma", "Autechre", "Tri Repetae", 0.8, 0, 5),
    ("Delta", "Autechre", "Tri Repetae", 0.6, 1, 0),
    ("Epsilon", "Wu-Lu", "LOGGERHEAD", None, 1, 3),
    ("Zeta", "Wu-Lu", "LOGGERHEAD", 0.2, 0, 0),
]


def seed_db():
    con = P.open_db()
    now = time.time()
    for i, (title, artist, album, rating, fav, plays) in enumerate(FIXTURE):
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album,"
            " album_artist, track, disc, year, orig_year, duration, codec,"
            " rating, favorite, play_count, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"/scratch/{i}.flac", 1.0, 100, title, artist, album, artist,
             i + 1, 1, 2002, 2002, 200.0, "flac", rating, fav, plays, now - i))
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
    PlaylistsView { id: pv; objectName: "playlistsView"; anchors.fill: parent }
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
    ctx.setContextProperty("PlaylistModel", bridge.playlistModel)

    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = comp.create(ctx)
    if theme is None:
        print("FAIL  Theme.qml did not build:", comp.errorString())
        return 1
    theme.setParent(app)
    KEEP.append(theme)
    ctx.setContextProperty("Theme", theme)

    # setData with a URL INSIDE qml/ so the relative imports resolve, rather
    # than writing a scratch .qml into the source tree: Qt caches a directory's
    # file listing on first load, and a file written afterwards comes back as
    # "File name case mismatch" (player/AGENTS.md).
    wrap = QQmlComponent(engine)
    wrap.setData(HARNESS_QML, QUrl.fromLocalFile(str(QML / "smartlist-harness.qml")))
    win = wrap.create(ctx)
    if win is None:
        print("FAIL  the harness window did not build:", wrap.errorString())
        return 1
    KEEP.append(win)
    spin(app, 300)

    # findChild rather than a `property alias`: an alias would come back typed
    # as the QML type, which PySide has no converter for ("Can't find converter
    # for 'PlaylistsView_QMLTYPE_1*'"). A QObject found by name takes its
    # properties and its QML functions perfectly well.
    view = win.findChild(QObject, "playlistsView")
    check("PlaylistsView built", view is not None)
    if view is None:
        return 1
    no_qml_warnings("on load")

    # ---------------------------------------------------------------- listing
    names = [s["name"] for s in bridge.smartLists]
    check("the sidebar model carries the built-ins",
          names == [d["name"] for d in P.DEFAULT_SMART_LISTS], str(names))
    check("…including his 4+ starred & liked", "4+ starred & liked" in names)

    view.select("4+ starred & liked")
    spin(app)
    got = {bridge.playlistModel.get(i)["title"]
           for i in range(bridge.playlistModel.count)}
    check("selecting a list fills the track model",
          got == {"Alpha", "Beta", "Gamma", "Delta", "Epsilon"}, str(sorted(got)))
    check("…and which list is open outlives the process (docs/DESIGN.md §14)",
          prefs.get("smartList") == "4+ starred & liked", prefs.get("smartList"))
    no_qml_warnings("after selecting a list")

    # ----------------------------------------------------------- the editor
    editor = win.findChild(QObject, "smartEditor")
    check("the editor is in the view", editor is not None)
    if editor is None:
        return 1

    def rules():
        return editor.property("rules").toVariant()

    check("the modal is down to begin with", view.property("modal") is False)

    editor.edit("4+ starred & liked")
    spin(app)
    check("edit() opens on the selected list", editor.property("visible") is True)
    check("…with its name loaded", editor.property("listName") == "4+ starred & liked")
    check("…and its match mode", editor.property("matchMode") == "any")
    check("…and both rules", len(rules()) == 2)
    check("the window's Space/Escape stand down while it is up",
          view.property("modal") is True)
    spin(app, 250)     # let the debounced count land
    check("the live count is the list's real size",
          editor.property("matchCount") == 5, editor.property("matchCount"))
    no_qml_warnings("with the editor open")

    # cancel must leave nothing behind
    editor.setValue(0, 1, True)          # 1 star — would be a very different list
    spin(app, 250)
    check("editing recounts live", editor.property("matchCount") == 6,
          editor.property("matchCount"))
    editor.cancel()
    spin(app)
    check("cancel closes", editor.property("visible") is False)
    check("…and writes nothing",
          library.smart.get("4+ starred & liked")["rules"][0]["value"] == 4)
    no_qml_warnings("after cancel")

    # ------------------------------------------------------- a new list, saved
    editor.createNew()
    spin(app)
    check("+ new opens an unnamed list", editor.property("origName") == "")
    check("…starting from one rule", len(rules()) == 1)

    editor.setField(0, "artist")
    editor.setOp(0, "contains")
    editor.setValue(0, "autechre", False)
    editor.addRule()
    editor.setField(1, "favorite")
    editor.setOp(1, "is")
    editor.setValue(1, True, True)
    editor.setProperty("matchMode", "any")
    editor.setProperty("listName", "autechre or liked")
    editor.setProperty("sortKey", "title")
    editor.recount()
    spin(app, 300)
    check("a hand-built spec counts",
          editor.property("matchCount") == 4, editor.property("matchCount"))
    editor.save()
    spin(app)
    check("save closes the editor", editor.property("visible") is False)
    saved = library.smart.get("autechre or liked")
    check("…and the list is in the store", saved is not None)
    check("…with both rules and the match mode",
          saved and len(saved["rules"]) == 2 and saved["match"] == "any", str(saved))
    check("…and the view selected it", view.property("current") == "autechre or liked")
    titles = [bridge.playlistModel.get(i)["title"]
              for i in range(bridge.playlistModel.count)]
    check("…and it is showing its tracks, in the chosen order",
          titles == ["Beta", "Delta", "Epsilon", "Gamma"], str(titles))
    no_qml_warnings("after saving a new list")

    # ------------------------------------------------------ rename in place
    editor.edit("autechre or liked")
    spin(app)
    editor.setProperty("listName", "renamed")
    editor.save()
    spin(app)
    check("renaming replaces rather than duplicating",
          library.smart.get("autechre or liked") is None
          and library.smart.get("renamed") is not None)
    check("…and the open list follows the rename",
          view.property("current") == "renamed", view.property("current"))
    check("…and its tracks are still there", bridge.playlistModel.count == 4)
    no_qml_warnings("after a rename")

    # ------------------------------------------------- duplicate and delete
    made = bridge.duplicateSmart("renamed")
    spin(app)
    check("duplicate names itself", made == "renamed copy", made)
    check("deleting returns True", bridge.deleteSmart("renamed copy") is True)
    spin(app)

    view.select("renamed")
    spin(app)
    bridge.deleteSmart("renamed")
    spin(app)
    check("deleting the OPEN list lands the view on another one",
          view.property("current") in [d["name"] for d in P.DEFAULT_SMART_LISTS],
          view.property("current"))
    check("…and the track list is not left showing a deleted list's tracks",
          bridge.playlistModel.count > 0)
    no_qml_warnings("after deleting the open list")

    # -------------------------------------------------------- restore + play
    bridge.deleteSmart("unrated")
    spin(app)
    check("restore brings back exactly the deleted one",
          bridge.restoreSmartDefaults() == 1)
    check("…and a second restore does nothing", bridge.restoreSmartDefaults() == 0)
    spin(app)

    view.select("5 starred")
    spin(app)
    view.openListMenu(10, 10, "5 starred")
    spin(app)
    no_qml_warnings("with the list context menu open")

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
