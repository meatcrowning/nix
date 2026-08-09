#!/usr/bin/env python3
"""player's focus-fade harness — docs/DESIGN.md §3.1.1, offscreen, no window on
anyone's screen and no contact with the live player.

The rule, since his board call of 2026-08-09: **the app-side §3.1.1 fade is
RETIRED.** An unfocused window used to grey every foreground to
`Theme.inactive` (the exact grey hyprvtb fades the titlebar's text and glyphs
to) while the native `decoration:dim_inactive` scrim dimmed the whole surface
— the double-dim — and he chose the single mechanism: **the native scrim is the
ONE dimmer, and the app always renders its focused tones.** So this harness's
job inverted: instead of asserting that focus loss greys everything, it asserts
that focus changes NOTHING — an unfocused player must be pixel-identical to its
focused self, because any app-drawn inactive state would double-dim it again.

Two layers:

  1. THE DERIVATION. `Main.qml`'s `fgText`/`fgDim`/`fgAccent` and `fgArt` must
     not move with the real `Window.active`, driven by really activating and
     deactivating the window — the offscreen platform honours
     `requestActivate()` and deactivates a window when another one is
     activated, so this does NOT have to fake the signal the way a `winActive`
     assignment would.
  2. THE PIXELS. The window is rendered at 480x826 (the size player actually
     runs at, not the 1080 default) in each view, focused and unfocused, and
     the two frames are histogrammed. Every theme slot is given a UNIQUE
     primary colour by the harness's fake palette, so a pixel count is an
     unambiguous answer to "is this slot still on screen" — and the assertion
     is that the two frames are IDENTICAL slot for slot, cover art included.
     If the app ever draws an inactive state of its own again, the frames
     differ and the test fails. (The old propagation walk is gone with the
     fade: a leaf hardcoding `Theme.text` was the §3.1.1 bug; under the
     retirement that is the designed behaviour.)

Run it with player's own Qt env, not the bare system python — and never through
the packaged `player` binary, which takes no arguments and would open a real
window:

    W=$(readlink -f "$(which player)"); sed '$d' "$W" > /tmp/plyenv.sh
    ( . /tmp/plyenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/player/tools/focus-fade-test.py )

  --png DIR   also write every grab, so the frames can be looked at directly
              (a histogram that compares two blank images passes everything).
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
# The harness draws its own palette; it must never read (or watch) the user's.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

PLAYER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(PLAYER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QUrl, Qt,
                            Property, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication, QImage, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

FAILS = []
KEEP = []          # setContextProperty does NOT take ownership — anything handed
                   # to QML and then collected comes back as black.


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name
          + ("  " + str(detail) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- the palette
# One unique, saturated colour per slot, so counting pixels of an exact RGB
# answers "is this slot still being drawn" with no blending ambiguity. The real
# wal palette is monochromatic (docs/DESIGN.md §3.2) and would make every count
# meaningless.
SLOTS = {
    "bg":        "#101010",
    "bgAlt":     "#202020",
    "border":    "#303030",
    # NOT a grey. `Theme.inactive` is 0x59 at alpha 0xaa, so faded text over the
    # `bg` grey composites to exactly ((0x59*0xaa) + 0x10*0x55) / 0xff = 0x40 —
    # which is what this slot used to be, and every greyed glyph then counted as
    # a highlight pixel that had "appeared" when the window lost focus.
    "highlight": "#0080ff",
    "accent":    "#ff0000",
    "text":      "#00ff00",
    "textDim":   "#0000ff",
    "dim":       "#ff00ff",
    "ok":        "#00ffff",
    "warn":      "#ffff00",
    "crit":      "#ff8000",
    "info":      "#8000ff",
}
ART_RGB = "#00ff80"        # the fake cover art: one flat, unique colour


class FakePalette(QObject):
    changed = Signal()

    def _c(self, k):
        return QColor(SLOTS[k])

    for _k in SLOTS:
        pass

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class FakeStyle(QObject):
    changed = Signal()

    @Property(str, notify=changed)
    def fontFamily(self): return "More Perfect DOS VGA"
    @Property(int, notify=changed)
    def fontSize(self): return 15
    @Property(bool, notify=changed)
    def reduceMotion(self): return True     # no animation to wait out
    @Property(float, notify=changed)
    def animSpeed(self): return 1.0


# ------------------------------------------------------------------ the stubs
class FakeTitlebar(QObject):
    """The real one registers buttons against this pid in the LIVE compositor."""
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


def tracks(n, art=""):
    return [{"trackId": i + 1, "title": "Track Title %d" % (i + 1),
             "artist": "Some Artist" if i % 2 else "Another Name",
             "album": "An Album", "albumId": 1, "track": i + 1, "disc": 1,
             "duration": 200.0 + i, "rating": 0.6, "favorite": bool(i % 3),
             "playCount": i, "available": True} for i in range(n)]


class FakeLibrary(QObject):
    scanStatus = Signal(str)
    scanRunning = Signal(bool)

    def __init__(self, art, parent=None):
        super().__init__(parent)
        self._art = art

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
                "trackCount": 8, "fullArt": self._art}
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

    def __init__(self, art, parent=None):
        super().__init__(parent)
        self._art = art

    @Property("QVariant", notify=currentChanged)
    def current(self):
        return {"id": 1, "title": "A Playing Track", "artist": "Some Artist",
                "album": "An Album", "albumArtist": "Some Artist", "albumId": 1,
                "year": 1999, "rating": 0.8, "favorite": True,
                "artPath": self._art, "duration": 240.0}

    @Property(int, notify=changed)
    def queueLength(self): return 8
    @Property(bool, notify=changed)
    def playing(self): return True
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
    def rgStatus(self): return "album gain, -7.2 dB"
    @Property(float, notify=changed)
    def rgPreamp(self): return 0.0

    for _n in ("previous", "toggle", "next", "cycleLoop"):
        pass

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
    def playAlbum(self, _a, _i): pass
    @Slot(int)
    def queueAlbum(self, _a): pass
    @Slot(int)
    def playAlbumNext(self, _a): pass
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


# --------------------------------------------------------------------- driving
def spin(app, ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()


def histogram(img, names):
    """Exact-RGB pixel counts for the named slots (plus the art colour)."""
    counts = {n: 0 for n in names}
    want = {QColor(SLOTS[n]).rgb() if n in SLOTS else QColor(ART_RGB).rgb(): n
            for n in names}
    for y in range(img.height()):
        for x in range(img.width()):
            n = want.get(img.pixel(x, y) | 0xff000000)
            if n:
                counts[n] += 1
    return counts


def main():
    argv = sys.argv[1:]
    pngdir = None
    if "--png" in argv:
        pngdir = argv[argv.index("--png") + 1]
        os.makedirs(pngdir, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="player-focus-")
    art = os.path.join(tmp, "art.png")
    a = QImage(256, 256, QImage.Format_RGB32)
    a.fill(QColor(ART_RGB))
    a.save(art)

    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    albums = Rows(ALBUM_ROLES,
                  [{"albumId": i + 1, "album": "Album %d" % (i + 1),
                    "artist": "Artist %d" % (i + 1), "year": 1990 + i,
                    "thumbPath": art} for i in range(21)])
    queue = Rows(TRACK_ROLES, tracks(8))
    albumTracks = Rows(TRACK_ROLES, tracks(8))
    playlist = Rows(TRACK_ROLES, tracks(6))
    search = Rows(TRACK_ROLES, tracks(6))
    pal, style = FakePalette(), FakeStyle()
    tb, prefs = FakeTitlebar(), FakePrefs()
    lib, ply, lyr = FakeLibrary(art), FakePlayer(art), FakeLyrics()
    KEEP.extend([albums, queue, albumTracks, playlist, search, pal, style,
                 tb, prefs, lib, ply, lyr])

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
    # The size player actually runs at. The 1080 default is not a layout this
    # app is ever judged in (player/AGENTS.md).
    win.setWidth(480)
    win.setHeight(826)
    spin(app, 400)

    lit = {"Theme.text": theme.property("text"),
           "Theme.textDim": theme.property("textDim"),
           "Theme.accent": theme.property("accent")}

    # A second window is what takes focus AWAY: the offscreen platform tracks
    # activation properly, so this exercises the real `Window.active` rather
    # than assigning a `winActive` flag the app would never set itself.
    thief = QWindow()
    thief.resize(64, 64)
    thief.show()

    def focus(on):
        if on:
            win.requestActivate()
        else:
            thief.requestActivate()
        spin(app, 250)

    # ------------------------------------------------ 1. the derivation
    focus(True)
    check("the window reports itself ACTIVE offscreen (the harness can drive focus)",
          win.property("active") is True)
    check("a focused window draws its foregrounds in the live tones",
          win.property("fgText") == lit["Theme.text"]
          and win.property("fgDim") == lit["Theme.textDim"]
          and win.property("fgAccent") == lit["Theme.accent"])
    check("a focused window draws its ARTWORK at full opacity",
          win.property("fgArt") == 1.0, win.property("fgArt"))
    focus(False)
    check("the window reports itself INACTIVE once another window takes focus",
          win.property("active") is False)
    # §3.1.1's app-side fade is RETIRED (his board call, 2026-08-09): the
    # native decoration:dim_inactive scrim is the ONE dimming mechanism, so an
    # unfocused window must stay on its focused tones — artwork included, which
    # the scrim dims as part of the surface.
    check("an UNFOCUSED window KEEPS all three foreground tones (the app-side fade is retired)",
          win.property("fgText") == lit["Theme.text"]
          and win.property("fgDim") == lit["Theme.textDim"]
          and win.property("fgAccent") == lit["Theme.accent"],
          (win.property("fgText"), win.property("fgDim"), win.property("fgAccent")))
    check("an UNFOCUSED window keeps the ARTWORK at full opacity",
          win.property("fgArt") == 1.0, win.property("fgArt"))

    # ------------------------------------------------ 2. the pixels
    # Focus must change NOTHING on screen: the app draws no inactive state of
    # its own (the §3.1.1 fade is retired), so an unfocused frame has to be
    # identical to its focused self, slot for slot, cover art included. The
    # grab covers the whole visible window, which is why the old per-item
    # propagation walk is gone with the fade — a leaf that hardcodes
    # `Theme.text` is now the designed behaviour, not a bug.
    # PySide hands a QML `Window` root back as a bare QWindow: no
    # `contentItem()`, no `grabWindow()`, and re-wrapping the pointer does not
    # help (the wrapper is cached per pointer). Reach the scene graph through
    # the item tree — the content item is the one QQuickItem with no item
    # parent — and render through QQuickItem.grabToImage, which is what is
    # actually reachable from here.
    from PySide6.QtQuick import QQuickItem
    root = next(i for i in win.findChildren(QQuickItem) if i.parentItem() is None)

    def grab():
        """One frame of the whole window, as a QImage. grabToImage is
        asynchronous — the result is empty until `ready` fires."""
        res = root.grabToImage()
        assert res is not None, "grabToImage refused (no render target?)"
        done = []
        res.ready.connect(lambda: done.append(True))
        end = time.time() + 5
        while not done and time.time() < end:
            app.processEvents()
        assert done, "grabToImage never became ready"
        return res.image()
    views = [("albums", {}), ("now", {}), ("playlists", {}),
             ("albums", {"settingsOpen": True}), ("albums", {"searching": True})]
    slots = list(SLOTS) + ["art"]
    for view, extra in views:
        win.setProperty("view", view)
        for k, v in extra.items():
            win.setProperty(k, v)
        label = view + ("+" + "+".join(extra) if extra else "")
        # Settle the NEW view before the first grab, not between the two: a view
        # whose delegates were still being created would make the focused frame
        # differ from the unfocused one for reasons that have nothing to do with
        # focus (it read 4530 highlight pixels short, once).
        spin(app, 600)

        focus(True)
        spin(app, 300)
        on = grab()
        focus(False)
        spin(app, 300)
        off = grab()
        if pngdir:
            on.save(os.path.join(pngdir, "%s-focused.png" % label))
            off.save(os.path.join(pngdir, "%s-unfocused.png" % label))

        h_on = histogram(on, slots)
        h_off = histogram(off, slots)
        check("%s: the focused frame is not blank (foreground pixels exist)" % label,
              h_on["text"] + h_on["textDim"] + h_on["accent"] > 200, h_on)
        diff = {k: (h_on[k], h_off[k]) for k in slots if h_on[k] != h_off[k]}
        check("%s: the unfocused frame is IDENTICAL — the app draws no inactive state" % label,
              not diff, str(diff) if diff else "")
        for k in extra:
            win.setProperty(k, False)

    print()
    print(("FAILED: " + ", ".join(FAILS)) if FAILS else "all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
