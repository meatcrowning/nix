#!/usr/bin/env python3
"""Offscreen harness for filer's picker mode.

Loads the REAL qml/Main.qml with the real Picker (apps/filer/pick.py) under
QT_QPA_PLATFORM=offscreen, so nothing is ever shown. Verifies: the QML compiles
with the picker branches live, filtering narrows the tree, accept writes a
correct result file, and an ordinary (non-picking) window still builds.

Titlebar is stubbed — the real one talks to the hyprvtb socket, which would
register buttons against this harness's pid in the live compositor.
"""
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QUrl, QObject, Slot, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402

import main as filermain  # noqa: E402
from pick import Picker, load_spec  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class StubTitlebar(QObject):
    @Slot("QVariantList")
    def setButtons(self, b): pass
    @Slot(str)
    def setFooter(self, t): pass
    @Slot(bool)
    def setTitleEdit(self, on): pass



def qrows(w):
    """The `view` item's `rows` model, unwrapped from QJSValue to plain data."""
    from PySide6.QtQml import QJSValue
    for ch in w.children():
        r = ch.property("rows")
        if r is not None:
            if isinstance(r, QJSValue):
                r = r.toVariant()
            return ch, (r or [])
    return None, []


def build(app, spec, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    picker = Picker(spec)
    ops = filermain.FileOps()
    palette = filermain.Palette(filermain.PANEL_THEME)
    settings = filermain.Settings()
    ctx.setContextProperty("FileOps", ops)
    ctx.setContextProperty("DirWatch", filermain.DirWatch())
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", palette)
    # Theme.qml binds font/fontSize to DeskStyle (pylib/deskstyle.py), so the
    # harness must install it too or the theme loads with an empty font.
    ctx.setContextProperty("DeskStyle", _deskstyle)
    ctx.setContextProperty("WinCtl", filermain.WinCtl())
    ctx.setContextProperty("Titlebar", StubTitlebar())
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("VideoConv", filermain.VideoConv())
    ctx.setContextProperty("Phone", filermain.Phone())
    ctx.setContextProperty("Remote", filermain.Remote())
    ctx.setContextProperty("ImgConv", filermain.ImgConv())
    ctx.setContextProperty("Picker", picker)
    ctx.setContextProperty("startDir", start_dir)
    ctx.setContextProperty("startSortField", "name")
    ctx.setContextProperty("startSortAsc", True)
    ctx.setContextProperty("startShowHidden", True)
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
    # keep refs alive (context-property objects are not owned by the engine)
    return engine, roots, (picker, ops, palette, settings, theme)


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_pick-")

    # a small tree with a predictable mix of types
    os.makedirs(os.path.join(tmp, "sub/deep"), exist_ok=True)
    for n in ("a.txt", "b.png", "c.jpg", "d.log", "READ.ME"):
        open(os.path.join(tmp, n), "w").write("x")

    # ---- 1. ordinary window (no picker) still builds ----
    eng, roots, keep = build(app, None, tmp)
    check("non-picking Main.qml loads", len(roots) == 1)
    if roots:
        w = roots[0]
        check("non-picking: win.picking is false", w.property("picking") is False,
              w.property("picking"))
        _, rows = qrows(w)
        names = sorted(r["name"] for r in rows)
        check("non-picking: lists dirs + non-image files",
              names == ["READ.ME", "a.txt", "d.log", "sub"], names)
    del eng, roots, keep

    # ---- 2. open-mode picker, filtered to *.txt ----
    result = os.path.join(tmp, "r.json")
    spec = {"mode": "open", "multiple": False, "title": "Attach a file",
            "accept_label": "_Attach", "current_folder": tmp, "result": result,
            "filters": [{"name": "Text", "patterns": ["*.txt"], "mimes": []},
                        {"name": "Images", "patterns": [], "mimes": ["image/*"]}],
            "current_filter": {"name": "Text", "patterns": ["*.txt"], "mimes": []}}
    eng, roots, keep = build(app, spec, tmp)
    picker = keep[0]
    check("picker Main.qml loads", len(roots) == 1)
    w = roots[0]
    check("picker: win.picking is true", w.property("picking") is True)
    _, rows = qrows(w)
    names = sorted(r["name"] for r in rows)
    check("picker: *.txt filter hides other files", names == ["a.txt", "sub"], names)

    # accept label / title reached the bar
    check("picker: accept_label mnemonic stripped", picker.acceptLabel == "Attach",
          picker.acceptLabel)
    check("picker: title exposed", picker.title == "Attach a file")

    # filter switching re-narrows the listing
    picker.setFilter("Images")
    check("picker: switching to an image/* MIME filter is honoured",
          picker.accepts("b.png", False) and picker.accepts("c.jpg", False)
          and not picker.accepts("a.txt", False))
    picker.setFilter("Text")

    # ---- 3. accept writes a correct result file ----
    picker.accept([os.path.join(tmp, "a.txt")])
    check("accept wrote a result file", os.path.exists(result))
    out = json.load(open(result))
    check("result uris are file:// URIs", out["uris"] == ["file://" + tmp + "/a.txt"], out)
    check("result echoes the current filter", out.get("current_filter") == "Text", out)
    del eng, roots, keep

    # ---- 4. single-selection requests get exactly one uri ----
    r2 = os.path.join(tmp, "r2.json")
    p = Picker({"mode": "open", "multiple": False, "result": r2})
    p.accept([os.path.join(tmp, "a.txt"), os.path.join(tmp, "d.log")])
    check("multiple=false returns one uri", len(json.load(open(r2))["uris"]) == 1)
    r3 = os.path.join(tmp, "r3.json")
    p = Picker({"mode": "open", "multiple": True, "result": r3})
    p.accept([os.path.join(tmp, "a.txt"), os.path.join(tmp, "d.log")])
    check("multiple=true returns both uris", len(json.load(open(r3))["uris"]) == 2)

    # ---- 5. dir mode lists no files and only accepts directories ----
    p = Picker({"mode": "dir", "result": "/dev/null"})
    check("dir mode: files are not listed", not p.accepts("a.txt", False))
    check("dir mode: directories are listed", p.accepts("sub", True))
    check("dir mode: a file is not selectable", not p.selectable(os.path.join(tmp, "a.txt")))
    check("dir mode: a directory is selectable", p.selectable(os.path.join(tmp, "sub")))
    po = Picker({"mode": "open", "result": "/dev/null"})
    check("open mode: a directory is not selectable", not po.selectable(os.path.join(tmp, "sub")))

    # ---- 6. accept never writes twice, and never on an empty/bogus set ----
    r4 = os.path.join(tmp, "r4.json")
    p = Picker({"mode": "open", "multiple": True, "result": r4})
    p.accept([])
    check("accept([]) writes nothing (reads as cancel)", not os.path.exists(r4))
    p.accept(["/nonexistent/nope"])
    check("accept(missing path) writes nothing", not os.path.exists(r4))

    # ---- 7. a spec with no result path is refused ----
    bad = os.path.join(tmp, "bad.json")
    json.dump({"mode": "open"}, open(bad, "w"))
    check("spec without a result path is rejected", load_spec(bad) is None)
    check("unreadable spec is rejected", load_spec(os.path.join(tmp, "nope.json")) is None)

    # ---- 8. glob case-sensitivity per the spec ----
    p = Picker({"mode": "open", "result": "/dev/null",
                "filters": [{"name": "I", "patterns": ["*.ico"], "mimes": []}],
                "current_filter": {"name": "I", "patterns": ["*.ico"], "mimes": []}})
    check("glob patterns are case-SENSITIVE",
          p.accepts("x.ico", False) and not p.accepts("x.ICO", False))

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all picker checks passed")


QTimer.singleShot(0, lambda: None)
main()
