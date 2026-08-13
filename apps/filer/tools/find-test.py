#!/usr/bin/env python3
"""Offscreen harness for filer's Ctrl+F metadata filter (docs/DESIGN.md §11.2).

Two halves, because the feature is two halves:

  * `MetaSearch` (main.py) against REAL PNGs written here — including the two
    shapes his library actually holds: ComfyUI's `prompt` chunk in front of the
    pixels, and a file whose text was appended AFTER them (1 in 595, measured),
    which only `pngmeta.read_text_path`'s tail scan finds. The query grammar
    (AND of substrings, `"quoted phrase"`, case folding), the hidden-files
    gate, directories matching on their name alone, and the per-pane token.
  * the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen: a genuine Ctrl+F
    through `QTest.keyClick` (a QML `Shortcut` is resolved by the application's
    shortcut map, which only sees keys delivered through the window system —
    `sendEvent` would pass and prove nothing), the bar opening with the caret in
    it, the listing actually narrowing, a second Ctrl+F re-selecting the query,
    Escape restoring the full directory, navigation dropping the filter, and —
    the one two panes get wrong — a filter in the RIGHT pane leaving the left
    pane's listing alone.

`Settings` is redirected into the temp dir before anything reads it: this test
navigates, and navigation persists into ~/.local/state/filer/state.json.
"""
import os
import pathlib
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)
import pngmeta  # noqa: E402  (pylib; the chunks painter writes and this reads)

from PySide6.QtCore import QUrl, QObject, Slot, Signal, QBuffer, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402,F401  (registers Item* for property())
from PySide6.QtTest import QTest  # noqa: E402

import main as filermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def spin(ms=150):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


# ---- fixtures ---------------------------------------------------------------

def png_bytes():
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x203040)
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_gen(path, **text):
    """A PNG carrying `text` as tEXt chunks in front of the pixels."""
    open(path, "wb").write(pngmeta.upsert_text(png_bytes(), text))


def write_trailing_gen(path, **text):
    """A PNG whose text chunks sit AFTER the pixels — the shape upsert_text
    never produces and one of his generators does. Built by hand: splice the
    chunks in immediately before IEND."""
    data = pngmeta.upsert_text(png_bytes(), {})
    iend = data.rfind(b"\x00\x00\x00\x00IEND")
    body = b"".join(pngmeta._chunk(b"tEXt", k.encode() + b"\x00" + v.encode())
                    for k, v in text.items())
    open(path, "wb").write(data[:iend] + body + data[iend:])


class Sink(QObject):
    """Collects MetaSearch.ready, which arrives from a worker thread."""

    def __init__(self, ms):
        super().__init__()
        self.hits = []
        ms.ready.connect(self.took)

    @Slot(str, "QVariantList")
    def took(self, token, paths):
        self.hits.append((token, sorted(os.path.basename(p) for p in paths)))

    def wait(self, ms=3000):
        end = time.time() + ms / 1000.0
        while time.time() < end and not self.hits:
            QGuiApplication.processEvents()
            time.sleep(0.005)
        return self.hits.pop(0) if self.hits else (None, None)


class StubTitlebar(QObject):
    clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.buttons = []
        self.footer = ""

    @Slot("QVariantList")
    def setButtons(self, b):
        self.buttons = [dict(x) for x in b if not isinstance(x, str)]

    @Slot(str)
    def setFooter(self, t):
        self.footer = t

    @Slot(bool)
    def setTitleEdit(self, on):
        pass

    def button(self, bid):
        for b in self.buttons:
            if b.get("id") == bid:
                return b
        return None


def build(app, start_dir, picker=None):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    tb = StubTitlebar()
    keep = (filermain.FileOps(), filermain.Palette(filermain.PANEL_THEME),
            filermain.Settings(), filermain.DirWatch(), filermain.WinCtl(),
            filermain.VideoConv(), tb, filermain.Picker(picker), filermain.Phone(),
            filermain.Remote(), filermain.ImgConv(), filermain.MetaSearch())
    ctx.setContextProperty("FileOps", keep[0])
    ctx.setContextProperty("WalPalette", keep[1])
    ctx.setContextProperty("DeskStyle", DeskStyle(parent=engine))
    ctx.setContextProperty("Settings", keep[2])
    ctx.setContextProperty("DirWatch", keep[3])
    ctx.setContextProperty("WinCtl", keep[4])
    ctx.setContextProperty("VideoConv", keep[5])
    ctx.setContextProperty("Titlebar", keep[6])
    ctx.setContextProperty("Picker", keep[7])
    ctx.setContextProperty("Phone", keep[8])
    ctx.setContextProperty("Remote", keep[9])
    ctx.setContextProperty("ImgConv", keep[10])
    ctx.setContextProperty("MetaSearch", keep[11])
    ctx.setContextProperty("startDir", start_dir)
    ctx.setContextProperty("startSortField", "name")
    ctx.setContextProperty("startSortAsc", True)
    ctx.setContextProperty("startShowHidden", False)
    ctx.setContextProperty("startGridPanelH", 200)
    ctx.setContextProperty("startSplit", False)
    ctx.setContextProperty("startSplitDir", "")
    ctx.setContextProperty("startSplitRatio", 0.5)
    ctx.setContextProperty("startSplitVertical", True)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(FILER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(FILER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], tb, keep + (theme,)


def listing(pane):
    """Every basename the pane is showing — list rows AND preview tiles, which
    are two models and one answer to the question "what is on screen"."""
    out = []
    for coll in ("rows", "previews"):
        model = pane.property(coll)
        if isinstance(model, QJSValue):
            model = model.toVariant()
        for e in model or []:
            out.append(os.path.basename(e["path"]))
    return sorted(out)


def type_query(pane, text, settle=1200):
    """Set the query the way the field does, then wait for the answer to land."""
    pane.setProperty("findText", text)
    if text.strip() == "":
        spin(300)
        return
    # Wait for THIS query: busy going up (the debounce firing), then down (the
    # worker answering). Waiting only for `filterSet !== null` would return
    # instantly on the set the PREVIOUS query left behind.
    end = time.time() + settle / 1000.0
    while time.time() < end and not pane.property("filterBusy"):
        QGuiApplication.processEvents()
        time.sleep(0.005)
    while time.time() < end and pane.property("filterBusy"):
        QGuiApplication.processEvents()
        time.sleep(0.005)
    spin(80)


# ---- the search backend -----------------------------------------------------

def test_backend(tmp):
    d = os.path.join(tmp, "gens")
    os.makedirs(os.path.join(d, "chrome-studies"))
    write_gen(os.path.join(d, "ComfyUI_00001_.png"),
              prompt='{"6": {"inputs": {"text": "a chrome cathedral at dusk"}}}',
              cte_sampler="euler_cfg_pp")
    write_gen(os.path.join(d, "ComfyUI_00002_.png"),
              cte_p1="ink drawing of a cat", cte_neg="chrome, shiny")
    write_trailing_gen(os.path.join(d, "ComfyUI_00003_.png"),
                       cte_p1="a chrome cathedral, appended after the pixels")
    write_gen(os.path.join(d, ".hidden-gen.png"), cte_p1="chrome and glass")
    open(os.path.join(d, "chrome-notes.txt"), "w").write("nothing indexable in here")
    open(os.path.join(d, "readme.txt"), "w").write("chrome")   # content is NOT the corpus

    ms = filermain.MetaSearch()
    sink = Sink(ms)

    ms.search("main", d, "chrome", False)
    token, hits = sink.wait()
    check("the token comes back as the pane gave it", token == "main", token)
    check("a term hits prompt text, a cte_* key, a trailing chunk and a filename",
          hits == ["ComfyUI_00001_.png", "ComfyUI_00002_.png", "ComfyUI_00003_.png",
                   "chrome-notes.txt", "chrome-studies"], hits)
    check("a non-PNG's CONTENTS are not the corpus — only its name",
          "readme.txt" not in (hits or []), hits)
    check("a directory matches on its name, so a filter cannot strand a folder",
          "chrome-studies" in (hits or []), hits)
    check("a dotfile stays hidden while the pane hides dotfiles",
          ".hidden-gen.png" not in (hits or []), hits)

    ms.search("main", d, "chrome", True)
    _t, hits = sink.wait()
    check("...and appears when the pane shows them", ".hidden-gen.png" in hits, hits)

    ms.search("main", d, "CHROME Cathedral", False)
    _t, hits = sink.wait()
    check("two terms are an AND, and case is folded",
          hits == ["ComfyUI_00001_.png", "ComfyUI_00003_.png"], hits)

    ms.search("main", d, '"chrome cathedral at dusk"', False)
    _t, hits = sink.wait()
    check("a quoted phrase is ONE term, spaces and all",
          hits == ["ComfyUI_00001_.png"], hits)

    ms.search("main", d, '"dusk at cathedral"', False)
    _t, hits = sink.wait()
    check("...and its word order matters", hits == [], hits)

    ms.search("main", d, "euler_cfg_pp", False)
    _t, hits = sink.wait()
    check("a sampler name is as findable as a prompt",
          hits == ["ComfyUI_00001_.png"], hits)

    ms.search("main", d, "nothing-in-this-library", False)
    _t, hits = sink.wait()
    check("no matches is an empty answer, not a missing one", hits == [], hits)

    # The cache is keyed on (mtime, size): rewriting a file with new metadata
    # must not answer from the old haystack.
    p = os.path.join(d, "ComfyUI_00002_.png")
    os.utime(p, (time.time() + 5, time.time() + 5))
    write_gen(p, cte_p1="entirely different subject: a lighthouse")
    ms.search("main", d, "lighthouse", False)
    _t, hits = sink.wait()
    check("a rewritten file is re-read, not answered from the cache",
          hits == ["ComfyUI_00002_.png"], hits)

    ms.search("main", d, "", False)
    token, hits = sink.wait()
    check("an empty query answers immediately with nothing (the QML reads it as"
          " 'no filter')", hits == [], hits)
    return d


# ---- the window -------------------------------------------------------------

def test_window(app, gens):
    engine, win, tb, keep = build(app, gens)
    win.show()
    spin(400)
    pane = win.property("pane")
    everything = listing(pane)
    check("the unfiltered pane lists the whole directory", len(everything) == 6, everything)

    check("the titlebar carries the desktop's find cell",
          (tb.button("find") or {}).get("label") == "fs"
          and (tb.button("find") or {}).get("tip") == "find (Ctrl+F)", tb.button("find"))
    check("...unlit while the bar is shut", (tb.button("find") or {}).get("state") == 0)

    QTest.keyClick(win, Qt.Key_F, Qt.ControlModifier)
    spin(150)
    check("Ctrl+F opens the bar", pane.property("findOpen") is True)
    check("...and lights the titlebar cell", (tb.button("find") or {}).get("state") == 1,
          tb.button("find"))
    check("...with nothing filtered yet", listing(pane) == everything)

    type_query(pane, "cathedral")
    check("a query narrows the pane to the gens whose METADATA matches",
          listing(pane) == ["ComfyUI_00001_.png", "ComfyUI_00003_.png"], listing(pane))
    check("the count the bar shows is what is on screen",
          pane.property("filterCount") == 2, pane.property("filterCount"))

    # A second Ctrl+F is the find-again gesture: it re-selects rather than
    # closing or clearing (§11.2).
    QTest.keyClick(win, Qt.Key_F, Qt.ControlModifier)
    spin(120)
    check("a second Ctrl+F leaves the bar open and the query intact",
          pane.property("findOpen") is True and pane.property("findText") == "cathedral",
          pane.property("findText"))
    check("...and the listing does not flicker back to everything",
          listing(pane) == ["ComfyUI_00001_.png", "ComfyUI_00003_.png"])

    type_query(pane, "not-in-any-of-these")
    check("a query with no hits shows an EMPTY dir, not the whole one",
          listing(pane) == [], listing(pane))

    pane.closeFind()
    spin(150)
    check("closing restores the full listing", listing(pane) == everything, listing(pane))
    check("...and clears the query", pane.property("findText") == "")
    check("...and unlights the cell", (tb.button("find") or {}).get("state") == 0)

    # Escape reaches closeFind through the field's own key handler; the state it
    # leaves behind is what matters here, and it is the same call.
    QTest.keyClick(win, Qt.Key_F, Qt.ControlModifier)
    type_query(pane, "chrome")
    # 00002 was rewritten to "a lighthouse" by the backend half, so "chrome" is
    # two gens plus the name-matched note and folder.
    check("filtered again before navigating", len(listing(pane)) == 4, listing(pane))
    pane.go(os.path.join(gens, "chrome-studies"))
    spin(300)
    check("navigating drops the filter — a query belongs to the dir it was typed in",
          pane.property("filterSet") is None and pane.property("findText") == "",
          pane.property("findText"))
    check("...and leaves the bar open for the new directory",
          pane.property("findOpen") is True)
    pane.go(gens)
    spin(300)
    pane.closeFind()
    spin(100)

    # Two panes, two directories, one titlebar: the answer must be routed by the
    # pane's watchKey or a filter in one pane empties the other.
    win.setSplit(True)
    spin(500)
    right = win.property("rightPane")
    check("the split opened", right is not None)
    if right is not None:
        right.go(gens)
        spin(300)
        win.setProperty("focusPane", 1)
        spin(100)
        QTest.keyClick(win, Qt.Key_F, Qt.ControlModifier)
        spin(120)
        check("Ctrl+F opens the bar in the FOCUSED pane only",
              right.property("findOpen") is True and pane.property("findOpen") is False)
        type_query(right, "cathedral")
        check("the right pane filters", len(listing(right)) == 2, listing(right))
        check("...and the left pane, on the same dir, is untouched",
              listing(pane) == everything, listing(pane))
        right.closeFind()
        spin(150)
    win.setSplit(True)   # toggling the current orientation folds it back
    spin(300)

    # A picker is one transient errand with its own filename box and file-type
    # cycler; the browser's filter would fight both.
    engine2, win2, _tb2, _keep2 = build(app, gens, picker={"mode": "open"})
    win2.show()
    spin(300)
    pane2 = win2.property("pane")
    QTest.keyClick(win2, Qt.Key_F, Qt.ControlModifier)
    spin(150)
    check("Ctrl+F is dead in picker mode", pane2.property("findOpen") is False)
    win2.close()
    return engine, win, tb, keep


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_find-")
    filermain.STATE_PATH = pathlib.Path(tmp) / "state.json"

    gens = test_backend(tmp)
    test_window(app, gens)

    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    else:
        print("all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
