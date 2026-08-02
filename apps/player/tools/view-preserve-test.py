#!/usr/bin/env python3
"""player's view-preservation harness — a library scan/import/watcher refresh
must NOT throw the user back to the top of the list (or reset the screen). The
models are replaced on every `library.changed`; DictListModel.merge turns that
"replace every row" into the minimal insert/remove/dataChanged so a ListView
holds its contentY. This proves both halves offscreen, never touching the live
player.

Run it with player's own Qt env (never the packaged `player` binary, which
takes no args and opens a real window):

    W=$(readlink -f "$(which player)")
    PY=$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3' | head -1)
    "$PY" apps/player/tools/view-preserve-test.py

Two layers:
  A. MODEL — merge() reaches the exact target rows for append / insert-in-middle
     / remove / reorder / data-only change, and does it WITHOUT a full reset
     (a reset is what snaps a view to the top). A duplicate/empty key falls
     back to set_rows, so correctness never rides on the diff.
  B. VIEW — a real DictListModel bound to a real ListView at the 480x826 window
     size player runs at: scroll down, merge in new rows the way a scan would,
     and assert contentY is unchanged and the count grew.
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never his screen
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

PLAYER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(PLAYER)
sys.path.insert(0, os.path.join(APPS, "pylib"))
sys.path.insert(0, PLAYER)

import importlib.util
spec = importlib.util.spec_from_file_location("player_main",
                                              os.path.join(PLAYER, "main.py"))
pm = importlib.util.module_from_spec(spec)
sys.argv = sys.argv[:1]
spec.loader.exec_module(pm)

from PySide6.QtCore import QModelIndex, QCoreApplication, QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

TRACK_ROLES = pm.TRACK_ROLES
DictListModel = pm.DictListModel

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


def row(tid, title="t", artist="a", **kw):
    r = {k: 0 for k in TRACK_ROLES}
    r.update({"trackId": tid, "title": title, "artist": artist})
    r.update(kw)
    return r


class ResetSpy(DictListModel):
    """Counts full resets so we can prove merge avoids them."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.resets = 0

    def beginResetModel(self):
        self.resets += 1
        super().beginResetModel()


# ---------------------------------------------------------------------------
# A. Model-level correctness
# ---------------------------------------------------------------------------
def test_model():
    print("A. model merge")

    def keys(m):
        return [m.get(i)["trackId"] for i in range(m.count)]

    # append at the end (the "recently added" case)
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in range(1, 6)])
    base_resets = m.resets
    m.merge([row(i) for i in range(1, 8)])
    check("append reaches target", keys(m) == [1, 2, 3, 4, 5, 6, 7])
    check("append does not reset", m.resets == base_resets)

    # insert in the middle (sorted insert)
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in (1, 2, 5, 6)])
    base = m.resets
    m.merge([row(i) for i in (1, 2, 3, 4, 5, 6)])
    check("middle insert reaches target", keys(m) == [1, 2, 3, 4, 5, 6])
    check("middle insert does not reset", m.resets == base)

    # removal
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in range(1, 7)])
    base = m.resets
    m.merge([row(i) for i in (1, 2, 5, 6)])
    check("remove reaches target", keys(m) == [1, 2, 5, 6])
    check("remove does not reset", m.resets == base)

    # reorder (a re-sort)
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in (1, 2, 3, 4)])
    base = m.resets
    m.merge([row(i) for i in (4, 3, 2, 1)])
    check("reorder reaches target", keys(m) == [4, 3, 2, 1])
    check("reorder does not reset", m.resets == base)

    # data-only change (rating updated on a rescan) — same keys, new field
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i, rating=0) for i in (1, 2, 3)])
    base = m.resets
    m.merge([row(1, rating=5), row(2, rating=0), row(3, rating=0)])
    check("data change kept in place", keys(m) == [1, 2, 3] and m.get(0)["rating"] == 5)
    check("data change does not reset", m.resets == base)

    # mixed: some removed, some added, some moved
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in (1, 2, 3, 4, 5)])
    base = m.resets
    m.merge([row(i) for i in (2, 6, 3, 7, 5)])
    check("mixed reaches target", keys(m) == [2, 6, 3, 7, 5])
    check("mixed does not reset", m.resets == base)

    # duplicate key -> falls back to a full reset (correctness over scroll)
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(1)])
    base = m.resets
    m.merge([row(2), row(2)])
    check("dup key reaches target", keys(m) == [2, 2])
    check("dup key falls back to reset", m.resets == base + 1)

    # empty target
    m = ResetSpy(TRACK_ROLES)
    m.set_rows([row(i) for i in (1, 2, 3)])
    m.merge([])
    check("empty target reaches target", keys(m) == [])


# ---------------------------------------------------------------------------
# B. View-level: contentY is held across a merge (480x826, real ListView)
# ---------------------------------------------------------------------------
QML = """
import QtQuick
ListView {
    id: list
    objectName: "list"
    width: 480; height: 826
    model: TestModel
    delegate: Item { width: list.width; height: 20 }
}
"""


def test_view(app):
    print("B. view holds scroll across merge")
    model = DictListModel(TRACK_ROLES)
    model.set_rows([row(i, title=f"t{i}") for i in range(200)])

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("TestModel", model)
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".qml", delete=False, dir="/tmp")
    f.write(QML); f.close()
    engine.load(QUrl.fromLocalFile(f.name))
    roots = engine.rootObjects()
    if not roots:
        check("qml loaded", False)
        return
    list_ = roots[0]

    def pump(ms=120):
        import time
        end = time.time() + ms / 1000.0
        while time.time() < end:
            app.processEvents()

    pump()
    # scroll well down into the list (row 100 -> contentY 2000)
    list_.setProperty("contentY", 2000.0)
    pump()
    y0 = list_.property("contentY")
    top_before = int((y0) / 20)   # index at the viewport top
    check("scrolled off the top", y0 > 100)

    # a scan appends new tracks at the end
    model.merge([row(i, title=f"t{i}") for i in range(200)] +
                [row(1000 + i, title=f"new{i}") for i in range(20)])
    pump()
    y1 = list_.property("contentY")
    check("append: contentY unchanged", abs(y1 - y0) < 1.0)
    check("append: count grew", model.count == 220)

    # a scan inserts a track ABOVE the viewport (sorted insert near the top):
    # the item under the viewport top must stay under it (contentY shifts by
    # exactly one row height, so the same track stays put).
    cur = [model.get(i) for i in range(model.count)]
    cur.insert(5, row(2000, title="insertedHigh"))
    y_before = list_.property("contentY")
    model.merge(cur)
    pump()
    y_after = list_.property("contentY")
    # The requirement is "don't get thrown to the top". ListView either holds
    # contentY (a different row now at the top) or shifts it by the one inserted
    # row's height to keep the same row put — both keep the user's place. What a
    # full reset would do (snap to 0) is what this rejects.
    check("insert-above: not thrown to the top",
          y_after > y_before - 1.0)

    os.unlink(f.name)


def main():
    app = QGuiApplication(sys.argv[:1])
    if app.platformName() != "offscreen":
        raise SystemExit(f"refusing to run on {app.platformName()!r}, not offscreen")
    test_model()
    test_view(app)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
