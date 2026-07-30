#!/usr/bin/env python3
"""editor's regression harness — offscreen, no window on anyone's screen.

Four layers, in the order a failure is cheapest to read:

  1. THE LANGUAGE TABLE (pure Python). Detection by name/extension/shebang, and
     that every language this repo is written in is actually covered.
  2. THE EDITING ALGORITHMS (`textops.py`, a bare `QTextDocument`, no view).
     Every Kate line command, the cases that are easy to get wrong silently — a
     selection ending on a line boundary, an empty line inside an indented run,
     an uncomment that must not eat a character, a move at the ends of the file
     — and that each is ONE undo step.
  3. THE HIGHLIGHTER. That a `#` inside a Python docstring stays a docstring,
     that no token class resolves to a literal colour, and that the find query's
     all-matches highlight rides in the same pass.
  4. THE WINDOW. The real `qml/Main.qml` under QT_QPA_PLATFORM=offscreen: open,
     edit, dirty, save, reload-from-disk, the gutter's numbers against the
     document's own layout, Ctrl+F through `QTest.keyClick`, find/replace, and
     that a QML warning (a binding loop, a missing property) fails the run.

Run it with editor's own Qt env, not the bare system python:

    W=$(readlink -f "$(which editor)"); sed '$d' "$W" > /tmp/edenv.sh
    ( . /tmp/edenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/editor/tools/editor-test.py )

`XDG_STATE_HOME` is redirected into a scratch dir: a harness must never rewrite
which files the user's own editor reopens. The Titlebar is stubbed, because the
real one registers buttons against this process's pid in the LIVE compositor.
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

EDITOR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(EDITOR)
sys.path.insert(0, EDITOR)
sys.path.insert(0, os.path.join(APPS, "pylib"))

FAILS = []
WARNINGS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def prop(obj, name):
    """A QML property, with a `var` unwrapped — a `property var` reaches PySide
    as a QJSValue, which has no length and compares equal to nothing."""
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def spin(ms=120):
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


# ------------------------------------------------------- 1. the language table
def test_languages():
    from highlight import LANGS, detect

    # The set the task named: every language this repo is actually written in.
    want = {".nix": "nix", ".py": "python", ".qml": "qml", ".js": "qml",
            ".lua": "lua", ".cpp": "cpp", ".hpp": "cpp", ".md": "md",
            ".sh": "sh", ".json": "json"}
    for ext, key in want.items():
        check("%s is %s" % (ext, key), detect("x" + ext) == key, detect("x" + ext))

    check("flake.lock is json by NAME, not by extension",
          detect("/x/flake.lock") == "json", detect("/x/flake.lock"))
    check("a shebang identifies an extensionless script",
          detect("/x/wal-set", "#!/usr/bin/env bash") == "sh",
          detect("/x/wal-set", "#!/usr/bin/env bash"))
    check("...including python", detect("/x/tool", "#!/usr/bin/python3") == "python")
    check("an unknown file is `text`, never a guess", detect("/x/thing.zzz") == "text")

    # Every language must answer the three questions the editor asks of it, or a
    # command silently does nothing for that language.
    for key, lg in LANGS.items():
        check("%s declares indent/comment/rules" % key,
              isinstance(lg["indent"], int) and "line" in lg
              and isinstance(lg["crules"], list), key)
    check("json declares NO line comment (so comment refuses)",
          LANGS["json"]["line"] == "")
    check("markdown has a block pair instead", LANGS["md"]["block"] == ("<!--", "-->"))
    check("nix and lua default to 2 columns, python and c++ to 4",
          (LANGS["nix"]["indent"], LANGS["lua"]["indent"],
           LANGS["python"]["indent"], LANGS["cpp"]["indent"]) == (2, 2, 4, 4))


# --------------------------------------------------- 2. the editing algorithms
def doc(text):
    from PySide6.QtGui import QTextDocument
    d = QTextDocument()
    d.setPlainText(text)
    d.setUndoRedoEnabled(True)
    d.setModified(False)
    return d


def pos_of(d, line, col=0):
    return d.findBlockByNumber(line).position() + col


def test_textops():
    import textops as T

    # ---- indent / unindent ----
    d = doc("a\nb\nc\n")
    s, e = T.indent(d, pos_of(d, 0), pos_of(d, 2) + 1, False, 4)
    check("indent puts one unit on every selected line",
          d.toPlainText() == "    a\n    b\n    c\n", repr(d.toPlainText()))
    check("...and the selection still covers the same lines",
          d.findBlock(s).blockNumber() == 0 and d.findBlock(e).blockNumber() == 2,
          (s, e))
    T.unindent(d, s, e, False, 4)
    check("unindent takes it back off", d.toPlainText() == "a\nb\nc\n",
          repr(d.toPlainText()))

    # The classic off-by-one: a selection ending exactly at a line start must
    # NOT include that line.
    d = doc("a\nb\nc\n")
    T.indent(d, pos_of(d, 0), pos_of(d, 2), False, 2)
    check("a selection ending at a line START does not indent that line",
          d.toPlainText() == "  a\n  b\nc\n", repr(d.toPlainText()))

    d = doc("a\n\nb\n")
    T.indent(d, pos_of(d, 0), pos_of(d, 2) + 1, False, 4)
    check("an empty line inside the run is left alone",
          d.toPlainText() == "    a\n\n    b\n", repr(d.toPlainText()))

    # Tab with no selection goes to the next tab STOP, not a whole unit.
    d = doc("ab\n")
    T.indent(d, 2, 2, False, 4)
    check("Tab at column 2 with width 4 inserts TWO spaces",
          d.toPlainText() == "ab  \n", repr(d.toPlainText()))

    d = doc("\ta\n")
    T.unindent(d, 0, 0, True, 4)
    check("unindent removes a hard tab as one unit", d.toPlainText() == "a\n",
          repr(d.toPlainText()))
    d = doc("a\n")
    T.unindent(d, 0, 0, False, 4)
    check("unindent on a line with no indent eats NOTHING",
          d.toPlainText() == "a\n", repr(d.toPlainText()))

    # ---- one undo step ----
    d = doc("a\nb\nc\n")
    T.indent(d, pos_of(d, 0), pos_of(d, 2) + 1, False, 4)
    d.undo()
    check("indenting three lines is ONE undo step", d.toPlainText() == "a\nb\nc\n",
          repr(d.toPlainText()))

    # ---- comment / uncomment ----
    d = doc("let\n  x = 1;\nin\n")
    T.toggle_comment(d, 0, d.characterCount() - 1, "nix")
    check("comment uses the language's own prefix",
          d.toPlainText() == "# let\n#   x = 1;\n# in\n", repr(d.toPlainText()))
    T.toggle_comment(d, 0, d.characterCount() - 1, "nix")
    check("...and toggling back removes exactly the prefix and its space",
          d.toPlainText() == "let\n  x = 1;\nin\n", repr(d.toPlainText()))

    d = doc("  a\n    b\n")
    T.toggle_comment(d, 0, d.characterCount() - 1, "python")
    # The whole run is commented at ONE column — the shallowest indent in it — so
    # the relative shape of the block survives, and uncommenting restores it
    # exactly. Commenting each line at its own indent does not round-trip.
    check("comment goes in at the SHALLOWEST common indent, keeping the shape",
          d.toPlainText() == "  # a\n  #   b\n", repr(d.toPlainText()))
    T.toggle_comment(d, 0, d.characterCount() - 1, "python")
    check("...and uncommenting restores the original exactly",
          d.toPlainText() == "  a\n    b\n", repr(d.toPlainText()))

    d = doc("// x\n")
    T.toggle_comment(d, 0, 3, "qml")
    check("a fully-commented run uncomments", d.toPlainText() == "x\n",
          repr(d.toPlainText()))

    d = doc('{"a": 1}\n')
    check("json REFUSES to comment (no syntax to invent)",
          T.toggle_comment(d, 0, 4, "json") is None)
    check("...and the document is untouched", d.toPlainText() == '{"a": 1}\n')

    d = doc("text here\n")
    r = T.toggle_comment(d, 0, 4, "md")
    check("markdown uses its BLOCK pair", r is not None
          and d.toPlainText().startswith("<!--"), repr(d.toPlainText()))

    # ---- duplicate / delete / move ----
    d = doc("one\ntwo\n")
    T.duplicate_lines(d, 0, 0)
    check("duplicate copies the current line below",
          d.toPlainText() == "one\none\ntwo\n", repr(d.toPlainText()))
    d = doc("one\ntwo\nthree\n")
    T.delete_lines(d, pos_of(d, 1), pos_of(d, 1))
    check("delete line takes the newline with it",
          d.toPlainText() == "one\nthree\n", repr(d.toPlainText()))
    d = doc("a\n")
    T.delete_lines(d, 0, 0)
    check("...and deleting the only line leaves an empty document",
          d.toPlainText() in ("", "\n"), repr(d.toPlainText()))

    d = doc("one\ntwo\nthree\n")
    s, e = T.move_lines(d, pos_of(d, 1), pos_of(d, 1), -1)
    check("move up swaps with the line above",
          d.toPlainText() == "two\none\nthree\n", repr(d.toPlainText()))
    check("...and the caret travels with the line",
          d.findBlock(s).blockNumber() == 0, s)
    s, e = T.move_lines(d, pos_of(d, 0), pos_of(d, 0), 1)
    check("move down swaps with the line below",
          d.toPlainText() == "one\ntwo\nthree\n", repr(d.toPlainText()))
    before = d.toPlainText()
    T.move_lines(d, pos_of(d, 0), pos_of(d, 0), -1)
    check("move up at the TOP refuses instead of destroying a line",
          d.toPlainText() == before, repr(d.toPlainText()))

    d = doc("a\nb\nc\n")
    T.move_lines(d, pos_of(d, 0), pos_of(d, 1) + 1, 1)
    check("a multi-line selection moves as a block",
          d.toPlainText() == "c\na\nb\n", repr(d.toPlainText()))

    # ---- auto-indent ----
    d = doc("def f():\n")
    p, _ = T.newline(d, pos_of(d, 0) + 8, False, 4, "python")
    check("Return after a python `:` indents one level deeper",
          d.toPlainText() == "def f():\n    \n", repr(d.toPlainText()))
    d.undo()
    check("...as ONE undo step, newline and indent together",
          d.toPlainText() == "def f():\n", repr(d.toPlainText()))

    d = doc("    x = 1\n")
    T.newline(d, pos_of(d, 0) + 9, False, 4, "python")
    check("Return on an ordinary line carries the same indent",
          d.toPlainText() == "    x = 1\n    \n", repr(d.toPlainText()))

    d = doc("{\n")
    T.newline(d, 1, False, 2, "nix")
    check("nix indents after an opening brace",
          d.toPlainText() == "{\n  \n", repr(d.toPlainText()))

    d = doc("    x\n")
    r = T.backspace_indent(d, pos_of(d, 0) + 4, False, 4)
    check("Backspace in leading whitespace eats a whole indent unit",
          r is not None and d.toPlainText() == "x\n", repr(d.toPlainText()))
    d = doc("    x\n")
    check("...and does nothing special once past it",
          T.backspace_indent(d, pos_of(d, 0) + 5, False, 4) is None)

    # ---- find / replace ----
    d = doc("alpha\nBeta\nalpha beta\n")
    hit = T.find(d, "alpha", 0)
    check("find returns the first match", hit == (0, 5), hit)
    hit2 = T.find(d, "alpha", 5)
    check("...and the next one from a position", hit2 and hit2[0] > 5, hit2)
    check("find WRAPS rather than stopping at the end",
          T.find(d, "alpha", d.characterCount() - 1) == (0, 5))
    check("case-insensitive by default", T.find(d, "BETA", 0) is not None)
    check("...and honours case when asked",
          T.find(d, "beta", 0, case=True)[0] > 10,
          T.find(d, "beta", 0, case=True))
    check("whole-words does not match inside a word",
          T.find(d, "alph", 0, whole=True) is None)
    check("a regex matches", T.find(d, r"al\w+a", 0, regex=True) == (0, 5))
    check("an invalid regex is None, not an exception",
          T.find(d, "(unclosed", 0, regex=True) is None)

    check("match_count counts every one", len(T.match_count(d, "alpha")) == 2)
    n = T.replace_all(d, "alpha", "gamma")
    check("replace_all replaces all and REPORTS the count", n == 2, n)
    check("...and the text is right", d.toPlainText() == "gamma\nBeta\ngamma beta\n",
          repr(d.toPlainText()))
    d.undo()
    check("...in ONE undo step", d.toPlainText() == "alpha\nBeta\nalpha beta\n",
          repr(d.toPlainText()))

    d = doc("foo123bar\n")
    n = T.replace_all(d, r"(\d+)", r"[\1]", regex=True)
    check("a regex replacement expands backreferences",
          n == 1 and d.toPlainText() == "foo[123]bar\n", repr(d.toPlainText()))


# ------------------------------------------------------------ 3. the highlighter
class FakePalette:
    """The palette's `color()` contract, with distinguishable values — enough to
    assert WHICH class was applied without a wallpaper."""
    SLOTS = {"accent": "#111111", "ok": "#222222", "info": "#333333",
             "dim": "#444444", "warn": "#555555", "textDim": "#666666",
             "text": "#777777", "highlight": "#888888"}

    def __init__(self):
        from PySide6.QtCore import QObject, Signal
        self.changed = None

    def color(self, slot):
        return self.SLOTS.get(slot, "#777777")


def fmt_at(d, line, col):
    """The (foreground, background) colour NAMES applied at one character.

    Names, not the `QTextCharFormat`: the wrapper shiboken hands back for a
    `FormatRange.format` dies as soon as the range list goes out of scope
    ("Internal C++ object already deleted"), so anything read off it has to be
    read here, inside the loop that owns it."""
    blk = d.findBlockByNumber(line)
    for f in blk.layout().formats():
        if f.start <= col < f.start + f.length:
            return (f.format.foreground().color().name(),
                    f.format.background().color().name())
    return None


def test_highlighter():
    from highlight import Highlighter, ROLE, LANGS
    from PySide6.QtGui import QTextDocument

    # No token class may name a literal colour: every one is a palette SLOT.
    check("every token class resolves to a named palette slot",
          all(v in FakePalette.SLOTS for v in ROLE.values()), ROLE)

    pal = FakePalette()
    d = QTextDocument()
    d.setPlainText('def f():\n    """a # docstring"""\n    x = "s"  # c\n')
    hl = Highlighter(d, pal, "python")
    hl.rehighlight()

    f = fmt_at(d, 0, 0)
    check("a keyword takes the keyword slot",
          f is not None and f[0] == FakePalette.SLOTS["accent"], f)

    f = fmt_at(d, 1, 9)      # the `#` inside the docstring
    check("a `#` inside a docstring stays a STRING, not a comment",
          f is not None and f[0] == FakePalette.SLOTS["ok"], f)

    f = fmt_at(d, 2, 13)     # the real comment
    check("a real comment takes the comment slot",
          f is not None and f[0] == FakePalette.SLOTS["dim"], f)

    # The find highlight rides the same pass, as a BACKGROUND.
    hl.set_query("x")
    f = fmt_at(d, 2, 4)
    check("the find query lights its matches in the same pass",
          f is not None and f[1] == FakePalette.SLOTS["highlight"], f)
    hl.set_query("")
    f = fmt_at(d, 2, 4)
    check("...and clearing the query unlights them",
          f is None or f[1] != FakePalette.SLOTS["highlight"], f)
    hl.set_query("(unclosed", regex=True)
    check("a half-typed regex unlights rather than raising", True)

    # Every language must survive its own file shape without an exception.
    samples = {
        "nix": "{ pkgs, ... }:\nlet x = ''str'';\nin { y = 1; } # c\n",
        "qml": "import QtQuick\nItem { /* c */ property int x: 1 }\n",
        "lua": "local x = 1 -- c\n--[[ block ]]\n",
        "cpp": "#include <x>\nint main() { /* c\nstill */ return 0; }\n",
        "sh": "for f in *; do echo \"$f\" # c\ndone\n",
        "json": '{"k": [1, true, null]}\n',
        "md": "# H\n\n```sh\ncode\n```\n\n**b** `c`\n",
        "conf": "[s]\nk = v  # c\n",
    }
    for key, text in samples.items():
        dd = QTextDocument()
        dd.setPlainText(text)
        h = Highlighter(dd, pal, key)
        h.rehighlight()
        blk, n = dd.firstBlock(), 0
        while blk.isValid():
            n += len(blk.layout().formats())
            blk = blk.next()
        check("%s highlights something and does not throw" % key, n > 0, n)


# --------------------------------------------------------------- 4. the window
def build(app, start_paths, start_line=0):
    from PySide6.QtCore import QUrl, QObject, Signal, Slot
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter,
    #                        without which win.property("view") raises)
    from deskstyle import DeskStyle
    import main as ed

    class StubTitlebar(QObject):
        # The signals matter as much as the slots: a `Connections` element whose
        # target lacks the signal it handles emits a QML warning, and this harness
        # FAILS on warnings — so a stub without them would fail the real Main.qml
        # for the stub's own omission.
        clicked = Signal(str)
        reordered = Signal(str, str)

        @Slot("QVariantList")
        def setButtons(self, b): pass
        @Slot(str)
        def setFooter(self, t): pass

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    pal = ed.Palette(ed.PANEL_THEME)
    keep = (pal, DeskStyle(parent=engine), StubTitlebar(), ed.Files(),
            ed.Buffers(pal), ed.Settings(), ed.SpellCheck())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Files", keep[3])
    ctx.setContextProperty("Buffers", keep[4])
    ctx.setContextProperty("Settings", keep[5])
    ctx.setContextProperty("Spell", keep[6])
    ctx.setContextProperty("startArgs", {"paths": start_paths, "line": start_line,
                                         "restored": False})
    # Every QML warning is collected: a binding loop or a missing property here is
    # a real defect that shows as nothing at all on screen.
    engine.warnings.connect(lambda ws: WARNINGS.extend(w.toString() for w in ws))

    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(EDITOR, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(EDITOR, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def test_window(app, tmp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    os.makedirs(tmp, exist_ok=True)
    a = os.path.join(tmp, "a.py")
    b = os.path.join(tmp, "b.nix")
    open(a, "w").write("def one():\n    return 1\n\n\ndef two():\n    return 2\n")
    open(b, "w").write("{ pkgs, ... }:\n{\n  x = 1;\n}\n")

    engine, win, keep = build(app, [a, b])
    spin(400)
    buffers = keep[4]

    view = win.property("view")
    print("      (%d documents open, showing %r)"
          % (win.property("tabCount"), win.property("docName")))
    check("there is a focused view", view is not None)
    if view is None:
        return
    check("the SECOND file is the one showing (last opened)",
          win.property("docName") == "b.nix", win.property("docName"))
    check("its language came from the extension",
          view.property("lang") == "nix", view.property("lang"))
    check("the line count is the document's", view.property("lines") == 5,
          view.property("lines"))
    check("a monospace advance was MEASURED, not assumed",
          2 < win.property("cellW") < 40, win.property("cellW"))

    # ---- the gutter is the DOCUMENT's layout, not n * lineH ----
    tid = 2
    rows = buffers.gutter(tid, 0.0, 200.0)
    check("the gutter numbers the visible lines from 1",
          len(rows) >= 4 and rows[0]["n"] == 1, rows[:2])
    check("...at strictly increasing y from the document layout",
          all(rows[i]["y"] < rows[i + 1]["y"] for i in range(len(rows) - 1)),
          [r["y"] for r in rows[:4]])
    check("...and every row has a real height",
          all(r["h"] > 0 for r in rows), [r["h"] for r in rows[:4]])

    # ---- editing marks it dirty, and the tab says so ----
    check("a freshly opened document is clean", win.property("dirty") is False)
    # A real KEYSTROKE. Assigning the whole text goes through
    # `QTextDocument::setPlainText`, which clears the modified flag and the undo
    # stack — so it can never test dirtiness, and an earlier version of this
    # harness "proved" the dirty flag broken that way.
    view.focusEditor()
    view.selectAll()
    # keyClick per key, not keyClicks: the string overload is QWidget-only and a
    # QQuickWindow is not one.
    for k in (Qt.Key.Key_X, Qt.Key.Key_Y):
        QTest.keyClick(win, k)
    spin(200)
    check("an edit marks the document dirty", win.property("dirty") is True,
          win.property("dirty"))

    # ---- save writes it, and clears dirty ----
    check("save reports success", win.saveTab(win.property("current"), "") is True)
    spin(150)
    check("...the file on disk changed", open(b).read().startswith("xy"),
          open(b).read()[:20])
    check("...and the document is clean again", win.property("dirty") is False)

    # ---- reload from disk, in place (S6.1) ----
    open(b, "w").write("{ y = 2; }\n")
    win.reloadTab(win.property("current"), True)
    spin(200)
    check("reload picks the new content up",
          "y = 2" in view.property("content"),
          view.property("content")[:30])
    check("...and the document is not dirty afterwards",
          win.property("dirty") is False)

    # ---- go to line ----
    open(b, "w").write("1\n2\n3\n4\n5\n6\n")
    win.reloadTab(win.property("current"), True)
    spin(200)
    view.goToLine(4)
    spin(80)
    check("go to line lands on that line", view.property("line") == 4,
          view.property("line"))

    # ---- Ctrl+F opens and focuses the find bar (docs/DESIGN.md S11.2) ----
    # keyClick, not sendEvent: a QML Shortcut is resolved by the application's
    # shortcut map, which only sees a key delivered through the window system.
    QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    spin(150)
    bar = None
    for it in descendants(win):
        if it.property("countLabel") is not None:
            bar = it
            break
    check("Ctrl+F reached a find bar", bar is not None)
    if bar is not None:
        check("...and it is shown", bar.property("shown") is True)
        check("...with the keyboard in its field", bar.property("fieldFocused") is True)

        open(b, "w").write("aa\nbb\naa\n")
        win.reloadTab(win.property("current"), True)
        spin(150)
        bar.setProperty("query", "aa")
        win.refreshFind()
        spin(150)
        check("the count is every match in the document",
              bar.property("matches") == 2, bar.property("matches"))
        check("...and it is reported as valid", bar.property("valid") is True)
        check("stepping selects a match", view.stepMatch(False) is True)
        spin(80)
        check("...and the selection IS one", view.selectionIsMatch() is True)

        bar.setProperty("useRegex", True)
        bar.setProperty("query", "(unclosed")
        win.refreshFind()
        spin(120)
        check("a bad regex says `bad regex`, not `no matches`",
              bar.property("valid") is False
              and bar.property("countLabel") == "bad regex",
              bar.property("countLabel"))
        bar.setProperty("useRegex", False)
        bar.setProperty("query", "aa")
        win.refreshFind()
        spin(120)

        # replace all, with its count
        win.setProperty("status", "")
        bar.setProperty("replacement", "zz")
        win.doReplaceAll()
        spin(150)
        check("replace all replaced every match",
              view.property("content").count("zz") == 2,
              view.property("content"))
        check("...and REPORTED how many", "2" in win.property("status"),
              win.property("status"))
        view.undo()
        spin(120)
        check("...undoably, in one step",
              view.property("content").count("aa") == 2,
              view.property("content"))

    # ---- the unsaved guard ----
    view.focusEditor()
    QTest.keyClick(win, Qt.Key.Key_Z)
    spin(200)
    check("the document is dirty again before the guard is tested",
          win.property("dirty") is True)
    n_before = None
    for it in descendants(win):
        if it.property("acceptLabel") is not None:
            n_before = it
            break
    win.closeTab(win.property("current"))
    spin(150)
    check("closing a dirty document ASKS instead of dropping it",
          n_before is not None and n_before.property("visible") is True,
          n_before.property("visible") if n_before else None)
    if n_before is not None:
        n_before.chooseDiscard()
        spin(200)
        check("...and `discard` closes it", win.property("docName") == "a.py",
              win.property("docName"))

    # ---- a comment refusal is REPORTED, not silent ----
    j = os.path.join(tmp, "c.json")
    open(j, "w").write('{"a": 1}\n')
    win.openPath(j, 0)
    spin(250)
    win.setProperty("status", "")
    v2 = win.property("view")
    v2.cmdComment()
    spin(150)
    check("commenting json refuses VISIBLY",
          "no comment" in win.property("status"), win.property("status"))

    # ---- indent guessing ----
    g = buffers.guessIndent(1)      # a.py, indented four
    check("a python file's indent is GUESSED as 4, not assumed",
          g["width"] == 4 and g["guessed"] is True, g)
    two = os.path.join(tmp, "two.nix")
    open(two, "w").write("{\n  a = {\n    b = 1;\n  };\n}\n")
    win.openPath(two, 0)
    spin(300)
    g2 = buffers.guessIndent(win.property("view").property("tid"))
    check("...and a 2-space nix file as 2 (the GCD of the widths present)",
          g2["width"] == 2 and g2["guessed"] is True, g2)

    # ---- spelling: prose is checked, code is not ----
    # The dictionary is the app wrapper's (`SPELL_HUNSPELL`/`SPELL_DICPATH`);
    # with none, `Spell.available` is false and every count below is 0, so this
    # section SKIPS rather than failing on a machine with no dictionary.
    md = os.path.join(tmp, "note.md")
    open(md, "w").write("a paragraph with one sentance that is wrong in it\n")
    win.openPath(md, 0)
    spin(600)
    v3 = win.property("view")
    if not keep[6].available:
        print("SKIP  spelling: no dictionary (SPELL_HUNSPELL=%r)"
              % os.environ.get("SPELL_HUNSPELL"))
    else:
        check("a markdown document is prose, so it IS spellchecked",
              v3.property("prose") is True, v3.property("prose"))
        check("...and the one misspelling is the one thing marked",
              v3.property("spellCount") == 1, v3.property("spellCount"))
        win.openPath(a, 0)          # a.py, from the top of this function
        spin(600)
        v4 = win.property("view")
        check("a source file is NOT spellchecked",
              v4.property("prose") is False and v4.property("spellCount") == 0,
              (v4.property("prose"), v4.property("spellCount")))

    check("no QML warnings anywhere in the run", not WARNINGS, WARNINGS[:4])


def descendants(item):
    out = []
    stack = list(item.childItems()) if hasattr(item, "childItems") else []
    if hasattr(item, "contentItem"):
        try:
            ci = item.contentItem()
            if ci is not None:
                stack = list(ci.childItems())
        except TypeError:
            pass
    while stack:
        it = stack.pop()
        out.append(it)
        stack.extend(it.childItems())
    return out


def main():
    from PySide6.QtGui import QGuiApplication
    with tempfile.TemporaryDirectory() as tmp:
        # never rewrite which files the user's own editor reopens
        os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
        test_languages()
        app = QGuiApplication(sys.argv)
        test_textops()
        test_highlighter()
        test_window(app, os.path.join(tmp, "win"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
