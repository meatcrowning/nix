#!/usr/bin/env python3
"""Harness for the track-favourite surfaces that are NOT the playbar heart.

    /usr/bin/python3 apps/player/tools/favourite-surfaces-test.py    # on book
    <player interp>  apps/player/tools/favourite-surfaces-test.py    # on top

(On book the deps — PySide6, mutagen, mpv — live in Fedora's /usr/bin/python3,
the same interpreter air-launch.sh runs the player under; bare `python3` here is
a nix build without PySide6.)

OFFSCREEN and against fakes — it never starts mpv, never touches MPRIS or D-Bus
and never speaks to the running player (~/nix/AGENTS.md: "never drive the
running player; he listens on it live").

Every favourite surface must call the SAME Library.setFavorite(id, on) write so
they stay in sync off the one trackChanged signal. This covers the two the last
spirit's transport-test.py does not:

  * the track context menu (qml/TrackMenu.qml) — the right-click entry labels
    itself by the current flag and flips it through Library.setFavorite; and
  * the MPRIS Metadata rating (main._mpris_user_rating) — xesam:userRating
    carries the real 0..1 STAR rating, not the favourite bool, and omits the
    key when the track is unrated.

The in-app hearts (transport bar/now-playing/row) and the L shortcut all issue the
identical Library.setFavorite call by inspection; the menu is the one with
branching logic worth exercising.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

from PySide6.QtCore import QObject, Property, Signal, Slot, QMetaObject, Qt, Q_RETURN_ARG, Q_ARG  # noqa: E402
from PySide6.QtGui import QGuiApplication, QColor  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import main  # noqa: E402  (module-level helpers only; main() is __main__-guarded)

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


# --------------------------------------------------------------------------
# MPRIS: xesam:userRating is the STAR rating, and absent when unrated.
# --------------------------------------------------------------------------
print("MPRIS userRating maps the star rating, not the favourite")
check("a rated track exposes its rating", main._mpris_user_rating({"rating": 0.8}) == 0.8)
check("zero is a real rating, kept", main._mpris_user_rating({"rating": 0.0}) == 0.0)
check("an unrated track omits the key", main._mpris_user_rating({"rating": None}) is None)
check("a track with no rating field omits the key", main._mpris_user_rating({}) is None)
check("favourite does NOT leak into userRating",
      main._mpris_user_rating({"rating": None, "favorite": 1}) is None)


# --------------------------------------------------------------------------
# The track context menu favourite toggle.
# --------------------------------------------------------------------------
class FakeTheme(QObject):
    def _c(value):  # noqa: N805
        return Property(QColor, lambda self: QColor(value), constant=True)
    bg = _c("#101010"); bgAlt = _c("#181818"); border = _c("#404040")
    accent = _c("#70dbf6"); text = _c("#f0f0f0"); textDim = _c("#a0a0a0")
    dim = _c("#808080"); highlight = _c("#303030"); inactive = _c("#595959")
    crit = _c("#e05050")

    @Property(str, constant=True)
    def font(self): return "More Perfect DOS VGA"

    @Property(int, constant=True)
    def fontSize(self): return 15

    @Property(bool, constant=True)
    def fontSmooth(self): return False

    @Property(int, constant=True)
    def lineHeight(self): return 15

    @Property(int, constant=True)
    def rounding(self): return 3

    @Property(int, constant=True)
    def ctrlBorder(self): return 1


class FakeStyle(QObject):
    @Property(bool, constant=True)
    def plasma(self): return True


class FakePlayer(QObject):
    changed = Signal()

    @Property(int, notify=changed)
    def queueLength(self): return 3


class FakeLibrary(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.favs = []

    @Property(bool, notify=changed)
    def canReveal(self): return False

    @Slot(int, bool)
    def setFavorite(self, tid, on):
        self.favs.append((int(tid), bool(on)))

    @Slot(int)
    def revealTrack(self, tid): pass


PROBE = """
import QtQuick
import "%s"

Item {
    width: 400
    height: 300

    // Read the labels of the built menu (skipping separators), so the test can
    // assert the favourite entry exists and reads right for the flag.
    function labelsFor(fav) {
        tm.openForTrack(10, 10, { trackId: 7, artist: "A", albumId: 0,
                                  available: true, favorite: fav,
                                  playNow: function () {} });
        var out = [];
        for (var i = 0; i < tm.items.length; i++)
            if (!tm.items[i].separator) out.push(tm.items[i].label);
        tm.close();
        return out;
    }

    // Fire the trigger of the entry with this label, so the test can assert it
    // reaches Library.setFavorite with the flip.
    function triggerLabel(fav, lbl) {
        tm.openForTrack(10, 10, { trackId: 7, artist: "A", albumId: 0,
                                  available: true, favorite: fav,
                                  playNow: function () {} });
        for (var i = 0; i < tm.items.length; i++)
            if (tm.items[i].label === lbl) { tm.items[i].trigger(); break; }
        tm.close();
    }

    TrackMenu { id: tm }
}
""" % (APP / "qml").as_uri()

app = QGuiApplication([])

tmp = Path(tempfile.mkdtemp(prefix="fav-surfaces-")) / "Probe.qml"
tmp.write_text(PROBE)
view = QQuickView()
theme, style, player, lib = FakeTheme(), FakeStyle(), FakePlayer(), FakeLibrary()
for nm, obj in (("Theme", theme), ("DeskStyle", style), ("Player", player), ("Library", lib)):
    view.rootContext().setContextProperty(nm, obj)
view.setSource(tmp.as_uri())
if view.status() == QQuickView.Error:
    for e in view.errors():
        print("   ", e.toString())
    raise SystemExit("Probe.qml did not load")
view.resize(400, 300)
view.show()
QTest.qWait(60)
root = view.rootObject()


def call_labels(fav):
    ret = QMetaObject.invokeMethod(root, "labelsFor", Qt.DirectConnection,
                                   Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", fav))
    if hasattr(ret, "toVariant"):
        ret = ret.toVariant()
    return list(ret) if ret else []


def call_trigger(fav, lbl):
    QMetaObject.invokeMethod(root, "triggerLabel", Qt.DirectConnection,
                             Q_ARG("QVariant", fav), Q_ARG("QVariant", lbl))


print("\nthe context menu carries the favourite toggle")
un = call_labels(False)
faved = call_labels(True)
check("an unfavourited track offers 'favourite'", "favourite" in un, str(un))
check("a favourited track offers 'unfavourite'", "unfavourite" in faved, str(faved))
check("only one of the two labels is ever present",
      ("favourite" in un) != ("unfavourite" in un))

lib.favs.clear()
call_trigger(False, "favourite")
check("liking an unfavourited track calls setFavorite(id, true)",
      lib.favs == [(7, True)], str(lib.favs))

lib.favs.clear()
call_trigger(True, "unfavourite")
check("unliking a favourited track calls setFavorite(id, false)",
      lib.favs == [(7, False)], str(lib.favs))

view.close()

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
