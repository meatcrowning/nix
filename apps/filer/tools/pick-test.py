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


def pane_of(w):
    """The BrowserPane — the child carrying the `rows` model."""
    return qrows(w)[0]


def qml(engine, obj, js):
    """Evaluate JS in `obj`'s own QML scope (phone-test.py's helper): a QML
    `function` is not a slot, and a component's ids are reachable no other way."""
    from PySide6.QtQml import QQmlExpression
    expr = QQmlExpression(engine.contextForObject(obj), obj, js)
    val = expr.evaluate()
    if expr.hasError():
        raise SystemExit("QML expression %r: %s" % (js, expr.error().toString()))
    return val[0] if isinstance(val, tuple) else val


def typein(w, engine, pane, text):
    """Put the keyboard in the name box and TYPE — real key events, so
    `onTextEdited` runs and the bar learns the answer was typed rather than
    picked. Setting `.text` from here would skip exactly that."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    qml(engine, pane, "pickerBar.nameText = ''")
    qml(engine, pane, "pickerBar.focusName()")
    # keyClicks is a QWidget API; a QQuickWindow takes one keyClick at a time.
    for ch in text:
        QTest.keyClick(w, ch)
    spin(60)


def spin(ms=80):
    import time
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def build(app, spec, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    picker = Picker(spec)
    ops = filermain.FileOps()
    palette = filermain.Palette(filermain.PANEL_THEME)
    settings = filermain.Settings()
    ctx.setContextProperty("FileOps", ops)
    # EVERY context-property object needs a Python reference to outlive this
    # function: the engine does not own them, and a collected one reads back as
    # null in QML — which showed up here as `go()` dying on
    # "Cannot call method 'setDirs' of null" the first time a test navigated.
    extra = (filermain.DirWatch(), filermain.WinCtl(), StubTitlebar(),
             filermain.VideoConv(), filermain.Phone(), filermain.Remote(),
             filermain.ImgConv())
    ctx.setContextProperty("DirWatch", extra[0])
    # Ctrl+F's backend (BrowserPane binds Connections to it, so it must exist
    # even in a harness that never types a query).
    _metasearch = filermain.MetaSearch(parent=engine)
    ctx.setContextProperty("MetaSearch", _metasearch)
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", palette)
    # Theme.qml binds font/fontSize to DeskStyle (pylib/deskstyle.py), so the
    # harness must install it too or the theme loads with an empty font.
    ctx.setContextProperty("DeskStyle", _deskstyle)
    ctx.setContextProperty("WinCtl", extra[1])
    ctx.setContextProperty("Titlebar", extra[2])
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("VideoConv", extra[3])
    ctx.setContextProperty("Phone", extra[4])
    ctx.setContextProperty("Remote", extra[5])
    ctx.setContextProperty("ImgConv", extra[6])
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
    return engine, roots, (picker, ops, palette, settings, theme) + extra


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

    # ---- 8. the name box is EDITABLE ----------------------------------------
    # A path from somewhere else (typed, or pasted out of a terminal) is the
    # whole reason a file dialog has a name box. Driven through the real QML:
    # real key events into the real TextInput, then the bar's own answer.
    r5 = os.path.join(tmp, "r5.json")
    spec5 = {"mode": "open", "multiple": False, "title": "Attach a file",
             "current_folder": tmp, "result": r5}
    eng, roots, keep = build(app, spec5, tmp)
    w = roots[0]
    pane = pane_of(w)
    spin(150)
    check("the box starts empty, showing the prompt",
          qml(eng, pane, "pickerBar.nameText") == "", qml(eng, pane, "pickerBar.nameText"))

    # selecting in the view writes the name into the box
    qml(eng, pane, "selectSingle('%s/a.txt', false)" % tmp)
    spin(80)
    check("clicking a file puts its NAME in the box",
          qml(eng, pane, "pickerBar.nameText") == "a.txt",
          qml(eng, pane, "pickerBar.nameText"))
    check("...and that is still the answer",
          qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "a.txt"))

    # a typed name, relative to the folder on screen
    typein(w, eng, pane, "b.png")
    check("a typed name resolves against the folder on screen",
          qml(eng, pane, "pickerBar.typed") is True
          and qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "b.png"),
          (qml(eng, pane, "pickerBar.typed"), qml(eng, pane, "pickerBar.answer")))
    check("...and it overrides the selection, which is still a.txt",
          qml(eng, pane, "selection[0]") == os.path.join(tmp, "a.txt"))

    # a name that is not there cannot be an answer — accept greys rather than
    # writing a result the app cannot open (docs/DESIGN.md 10)
    typein(w, eng, pane, "nope.txt")
    check("a name that does not exist refuses to be an answer",
          qml(eng, pane, "pickerBar.canAccept") is False
          and qml(eng, pane, "pickerBar.answer.length") == 0,
          qml(eng, pane, "pickerBar.answer"))

    # an absolute path, and ~
    typein(w, eng, pane, os.path.join(tmp, "sub", "..", "c.jpg"))
    check("an absolute path is taken as it stands (and normalised)",
          qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "c.jpg"),
          qml(eng, pane, "pickerBar.answer"))
    check("~ expands", Picker({"mode": "open", "result": "/dev/null"})
          .resolvePath("~/x", tmp) == os.path.join(os.path.expanduser("~"), "x"))

    # a typed FOLDER is somewhere to go, not the answer
    typein(w, eng, pane, "sub")
    check("a typed folder is travel, not an answer",
          qml(eng, pane, "pickerBar.typedIsTravel") is True
          and qml(eng, pane, "pickerBar.answer.length") == 0)
    check("...but the button is live, because Enter does something",
          qml(eng, pane, "pickerBar.canAccept") is True)
    qml(eng, pane, "pickerBar.submit()")
    spin(120)
    check("...and submitting goes there",
          qml(eng, pane, "path") == os.path.join(tmp, "sub"),
          qml(eng, pane, "path"))
    check("...leaving the box empty for the new folder",
          qml(eng, pane, "pickerBar.nameText") == ""
          and qml(eng, pane, "pickerBar.typed") is False,
          qml(eng, pane, "pickerBar.nameText"))
    check("no result was written by travelling", not os.path.exists(r5))

    # and a typed name really is what gets returned
    qml(eng, pane, "go('%s')" % tmp)
    spin(120)
    typein(w, eng, pane, "d.log")
    qml(eng, pane, "pickerBar.submit()")
    spin(120)
    check("a typed name is what the app receives",
          os.path.exists(r5)
          and json.load(open(r5))["uris"] == ["file://" + os.path.join(tmp, "d.log")],
          json.load(open(r5)) if os.path.exists(r5) else None)
    del eng, roots, keep

    # ---- 8b. dir mode: a typed folder IS the answer -------------------------
    r6 = os.path.join(tmp, "r6.json")
    eng, roots, keep = build(app, {"mode": "dir", "current_folder": tmp,
                                   "result": r6}, tmp)
    w = roots[0]
    pane = pane_of(w)
    spin(150)
    typein(w, eng, pane, "sub")
    check("dir mode: a typed folder is the answer, not travel",
          qml(eng, pane, "pickerBar.typedIsTravel") is False
          and qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "sub"),
          qml(eng, pane, "pickerBar.answer"))
    typein(w, eng, pane, "a.txt")
    check("dir mode: a typed FILE is refused",
          qml(eng, pane, "pickerBar.canAccept") is False)
    del eng, roots, keep

    # ---- 8c. the app's suggested name seeds the box -------------------------
    eng, roots, keep = build(app, {"mode": "open", "current_folder": tmp,
                                   "current_name": "a.txt",
                                   "result": os.path.join(tmp, "r7.json")}, tmp)
    pane = pane_of(roots[0])
    spin(150)
    check("current_name seeds the box",
          qml(eng, pane, "pickerBar.nameText") == "a.txt"
          and qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "a.txt"),
          qml(eng, pane, "pickerBar.nameText"))
    del eng, roots, keep

    # ---- 8d. resolvePath / kindOf, without a window -------------------------
    pk = Picker({"mode": "open", "result": "/dev/null"})
    check("resolvePath: empty text is nothing", pk.resolvePath("  ", tmp) == "")
    check("resolvePath: relative joins the folder",
          pk.resolvePath("a.txt", tmp) == os.path.join(tmp, "a.txt"))
    check("kindOf tells the three cases apart",
          [pk.kindOf(os.path.join(tmp, "sub")), pk.kindOf(os.path.join(tmp, "a.txt")),
           pk.kindOf(os.path.join(tmp, "nope"))] == ["dir", "file", "missing"])

    # ---- 8e. SAVE mode: the name box IS the answer --------------------------
    # surfer's <input type=file> asks for this (Chromium's FileModeSave); the
    # portal backend never does. The file must NOT have to exist.
    r8 = os.path.join(tmp, "r8.json")
    eng, roots, keep = build(app, {"mode": "save", "current_folder": tmp,
                                   "current_name": "note.txt", "result": r8}, tmp)
    w = roots[0]
    pane = pane_of(w)
    spin(150)
    check("save: the suggested name is in the box",
          qml(eng, pane, "pickerBar.nameText") == "note.txt")
    check("save: a file that does not exist yet IS the answer",
          qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "note.txt")
          and qml(eng, pane, "pickerBar.canAccept") is True,
          qml(eng, pane, "pickerBar.answer"))
    check("save: the accept button says save",
          keep[0].acceptLabel == "save", keep[0].acceptLabel)

    # a name whose FOLDER is not there cannot be written
    typein(w, eng, pane, "nowhere/note.txt")
    check("save: a name in a folder that does not exist is refused",
          qml(eng, pane, "pickerBar.canAccept") is False)

    # a folder still navigates, in save mode too
    typein(w, eng, pane, "sub")
    check("save: a typed folder is still travel",
          qml(eng, pane, "pickerBar.typedIsTravel") is True)
    qml(eng, pane, "pickerBar.submit()")
    spin(120)
    check("save: ...and going there leaves the box empty",
          qml(eng, pane, "path") == os.path.join(tmp, "sub"))
    qml(eng, pane, "go('%s')" % tmp)
    spin(120)

    # clicking a file fills the name — that is how you overwrite by pointing
    qml(eng, pane, "selectSingle('%s/a.txt', false)" % tmp)
    spin(80)
    check("save: clicking a file fills the name",
          qml(eng, pane, "pickerBar.nameText") == "a.txt"
          and qml(eng, pane, "pickerBar.answer[0]") == os.path.join(tmp, "a.txt"),
          qml(eng, pane, "pickerBar.nameText"))
    check("save: ...and that is flagged as an overwrite",
          qml(eng, pane, "pickerBar.willOverwrite") is True)
    qml(eng, pane, "pickerBar.submit()")
    spin(120)
    check("save: submitting onto an existing file ASKS, and writes nothing yet",
          not os.path.exists(r8))
    qml(eng, pane, "pickerBar.doAccept()")     # what the confirm's OK calls
    spin(120)
    check("save: confirming writes the result",
          os.path.exists(r8)
          and json.load(open(r8))["uris"] == ["file://" + os.path.join(tmp, "a.txt")],
          json.load(open(r8)) if os.path.exists(r8) else None)
    del eng, roots, keep

    # and a brand-new name goes through with no dialog at all
    r9 = os.path.join(tmp, "r9.json")
    eng, roots, keep = build(app, {"mode": "save", "current_folder": tmp,
                                   "current_name": "fresh.txt", "result": r9}, tmp)
    pane = pane_of(roots[0])
    spin(150)
    check("save: a new name does not read as an overwrite",
          qml(eng, pane, "pickerBar.willOverwrite") is False)
    qml(eng, pane, "pickerBar.submit()")
    spin(120)
    check("save: ...and is written straight out",
          os.path.exists(r9)
          and json.load(open(r9))["uris"] == ["file://" + os.path.join(tmp, "fresh.txt")],
          json.load(open(r9)) if os.path.exists(r9) else None)
    check("save: writable() is the folder test",
          keep[0].writable(os.path.join(tmp, "x.txt"))
          and not keep[0].writable(os.path.join(tmp, "nope", "x.txt")))
    del eng, roots, keep

    # ---- 9. glob case-sensitivity per the spec ----
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
