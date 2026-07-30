#!/usr/bin/env python3
"""Regression harness for `pylib/spellcheck.py` and `qmlcommon/SpellMarks.qml`.

Three layers, cheapest failure first:

  1. THE TOKENISER (pure Python, no dictionary). What is a word and — more
     importantly — what is deliberately NOT one: acronyms, identifiers, paths,
     versions, two-letter tokens. Those four rules are the difference between a
     usable marker and one that underlines a third of a code comment.
  2. THE ENGINE. Real hunspell over the pipe: a miss, a hit, an affixed form
     the word list alone would reject, suggestions, and the personal
     dictionary. Then the DEGRADED path — binary pointed at nothing — which
     must report unavailable and mark NOTHING (docs/DESIGN.md §10: an input with
     no dictionary behaves exactly as it does today).
  3. THE MARKER. `SpellMarks.qml` over a real `TextEdit`, offscreen, pixels
     sampled: a 1px dashed run under the misspelled word, none under the
     correct one, inside the line box, and the correction actually replacing the
     word in the document.

Run it with any app's Qt env (layer 3 needs PySide6 + QtQuick.Shapes):

    W=$(readlink -f "$(which editor)"); sed '$d' "$W" > /tmp/edenv.sh
    ( . /tmp/edenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/pylib/tools/spellcheck-test.py )

Layer 2's live half needs a dictionary: it takes `SPELL_HUNSPELL` /
`SPELL_DICPATH` from the environment exactly as the app wrappers set them, and
reports SKIP (not PASS) when there is none, because a green run on a machine
with no dictionary would say nothing at all.
"""
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIB = os.path.dirname(HERE)
APPS = os.path.dirname(PYLIB)
sys.path.insert(0, PYLIB)

FAILS = []
SKIPS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print("SKIP  " + name + "  " + why)
    SKIPS.append(name)


# ---------------------------------------------------------------- 1. tokeniser
def test_tokeniser():
    import spellcheck as sc

    def toks(t):
        return [w for _, _, w in sc.words(t)]

    check("tokeniser: plain prose",
          toks("the quick brown fox") == ["the", "quick", "brown", "fox"])
    check("tokeniser: apostrophe is inside the word",
          toks("doesn't matter") == ["doesn't", "matter"])
    check("tokeniser: two-letter tokens are skipped", toks("it is an ox") == [])
    check("tokeniser: acronyms are skipped", toks("the QML and NIXOS bits")
          == ["the", "and", "bits"])
    check("tokeniser: identifiers are skipped",
          toks("call positionAt then PromptBox") == ["call", "then"])
    check("tokeniser: dotted paths are skipped",
          toks("import os.path here") == ["import", "here"])
    check("tokeniser: a sentence's last word is NOT skipped",
          toks("this ends here.") == ["this", "ends", "here"])
    check("tokeniser: digits break a token",
          toks("the mp3 and utf8 files") == ["the", "and", "files"])
    check("tokeniser: slashes and underscores are skipped",
          toks("/usr/share/hunspell and en_US") == ["and"])
    check("tokeniser: ranges are the caller's slice",
          [w for _, _, w in sc.words("alpha beta gamma", 6, 10)] == ["beta"])
    # offsets must point at the real characters
    got = list(sc.words("aa misspeled bb"))
    check("tokeniser: offsets",
          got and "misspeled" == "aa misspeled bb"[got[0][0]:got[0][1]], got)


# ------------------------------------------------------------------- 2. engine
def test_engine():
    import spellcheck as sc

    if not sc.engine().available:
        skip("engine: live dictionary",
             "no hunspell/dictionary (SPELL_HUNSPELL=%r SPELL_DICPATH=%r)"
             % (os.environ.get("SPELL_HUNSPELL"), os.environ.get("SPELL_DICPATH")))
    else:
        e = sc.engine()
        check("engine: a correct word is correct", e.check("receive"))
        check("engine: a misspelling is caught", not e.check("recieve"))
        # The affix engine, which is the whole reason this is hunspell and not
        # a word-list membership test.
        check("engine: affixed forms are accepted",
              e.check("walked") and e.check("walking") and e.check("kindness"))
        sug = e.suggest("recieve")
        check("engine: suggestions are ranked and contain the fix",
              "receive" in sug, sug[:4])
        sp = sc.spans("this sentance has one bad word")
        check("engine: spans point at the bad word only",
              len(sp) == 1 and "this sentance has one bad word"[sp[0][0]:sp[0][1]]
              == "sentance", sp)
        w = sc.word_at("this sentance has", 9)
        check("engine: word_at finds the word under a caret", w[2] == "sentance", w)
        w = sc.word_at("this sentance has", 5)   # left edge
        check("engine: word_at works at a word's edge", w[2] == "sentance", w)

        # the personal dictionary, in a scratch state dir
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = d
            try:
                eng = sc._Hunspell()
                check("personal: unknown before learning", not eng.check("hyprvtb"))
                eng.learn("hyprvtb")
                check("personal: known after learning", eng.check("hyprvtb"))
                check("personal: persisted to disk",
                      "hyprvtb" in (open(os.path.join(d, "spellcheck", "personal.dic"))
                                    .read()))
                eng2 = sc._Hunspell()
                check("personal: a second app reads the same file",
                      eng2.check("hyprvtb"))
            finally:
                if old is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old

    # DEGRADED: no binary at all. In a child process, because the module-level
    # engine caches its verdict for the life of the process on purpose.
    prog = (
        "import sys; sys.path.insert(0, %r)\n"
        "import spellcheck as sc\n"
        "print('avail', sc.engine().available)\n"
        "print('spans', sc.spans('this sentance has one bad word'))\n"
        "print('wordat', sc.SpellCheck().wordAt('this sentance', 9))\n"
        "print('suggest', sc.SpellCheck().suggest('recieve'))\n"
    ) % PYLIB
    env = dict(os.environ)
    env["SPELL_HUNSPELL"] = "/nonexistent/hunspell"
    env["SPELL_DICPATH"] = "/nonexistent"
    env["XDG_DATA_DIRS"] = ""
    out = subprocess.run([sys.executable, "-c", prog], env=env,
                         capture_output=True, text=True, timeout=60)
    check("degraded: reports unavailable", "avail False" in out.stdout, out.stdout.strip())
    check("degraded: marks nothing", "spans []" in out.stdout, out.stdout.strip())
    check("degraded: offers nothing", "suggest []" in out.stdout, out.stdout.strip())
    check("degraded: wordAt says nothing is bad",
          "'bad': False" in out.stdout, out.stdout.strip())
    check("degraded: no traceback", out.returncode == 0 and not out.stderr.strip(),
          out.stderr.strip()[:300])


# ------------------------------------------------------------------- 3. marker
QML = """
import QtQuick
import "file:%s/qmlcommon"

// Everything the harness needs goes through functions on the ROOT object:
// PySide6 wraps no QML component type ("Can't find converter for
// 'SpellMarks_QMLTYPE_0*'"), so a test that reaches for the item itself cannot
// even get a reference to it.
Rectangle {
    id: root
    width: 320; height: 90; color: "black"

    function setText(t) { input.text = t; }
    function textNow() { return input.text; }
    function rebuild() { m.rebuild(); }
    function spanCount() { return m.spans.length; }
    function spanAt(i) { return [m.spans[i][0], m.spans[i][1]]; }
    function correctFirst(w) { m.correct(m.spans[0][0], m.spans[0][1], w); }
    function menuLabels(pos) {
        var it = m.menuItems(pos), out = [];
        for (var i = 0; i < it.length; i++)
            out.push(it[i].separator === true ? "|" : it[i].label);
        return out.join(",");   // a JS array reaches Python as an opaque QJSValue
    }

    TextEdit {
        id: input
        anchors.fill: parent
        anchors.margins: 4
        color: "#303030"
        font.family: "monospace"
        font.pixelSize: 16
        wrapMode: TextEdit.Wrap
        text: "this sentance is here"
    }
    SpellMarks {
        id: m
        target: input
        anchors.fill: input
    }
}
""" % APPS


def test_marker():
    from PySide6.QtCore import QUrl, QObject, Property
    from PySide6.QtGui import QGuiApplication, QColor
    from PySide6.QtQuick import QQuickView
    import spellcheck as sc

    if not sc.engine().available:
        skip("marker", "no dictionary; the drawing test needs real spans")
        return

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    warnings = []

    tmp = tempfile.mkdtemp()
    qml = os.path.join(tmp, "V.qml")
    with open(qml, "w") as fh:
        fh.write(QML)

    class ThemeStub(QObject):
        """The component must resolve `Theme.crit` the way it does inside a real
        app, and must not care that this one is a stub."""

        @Property(QColor, constant=True)
        def crit(self):
            return QColor("#ff0000")

    view = QQuickView()
    view.engine().warnings.connect(
        lambda errs: warnings.extend(e.toString() for e in errs))
    spell = sc.SpellCheck()
    theme = ThemeStub()
    view.rootContext().setContextProperty("Spell", spell)
    view.rootContext().setContextProperty("Theme", theme)
    view.setSource(QUrl.fromLocalFile(qml))
    if view.status() != QQuickView.Status.Ready:
        check("marker: component loads", False,
              [e.toString() for e in view.errors()])
        return
    check("marker: component loads", True)
    view.show()
    root = view.rootObject()

    def settle(n=6):
        for _ in range(n):
            app.processEvents()

    def redrows(img):
        rows = {}
        for y in range(img.height()):
            xs = [x for x in range(img.width())
                  if img.pixelColor(x, y).red() > 120
                  and img.pixelColor(x, y).green() < 90
                  and img.pixelColor(x, y).blue() < 90]
            if xs:
                rows[y] = xs
        return rows

    settle()
    root.rebuild()
    settle()

    check("marker: one span, on the misspelling", root.spanCount() == 1,
          root.spanCount())

    img = view.grabWindow()
    rows = redrows(img)
    check("marker: drawn on exactly one pixel row", len(rows) == 1, sorted(rows))
    if rows:
        y = list(rows)[0]
        xs = rows[y]
        gaps = sorted(set(xs[i + 1] - xs[i] for i in range(len(xs) - 1)))
        check("marker: it is a 1-on-1-off dash pattern", gaps == [2], gaps)
        # Under the WORD, not the line: "this " is five cells of a 16px
        # monospace font, so the run starts well right of the text's left edge
        # and ends well left of its right edge.
        check("marker: under the word, not the line",
              min(xs) > 20 and max(xs) < img.width() - 60, (min(xs), max(xs)))
        # Inside the line box: the text starts at the 4px margin and one line of
        # a 16px font is ~20px tall.
        check("marker: inside the first line box", 4 < y < 30, y)

    # the correction, end to end
    root.correctFirst("sentence")
    settle()
    check("marker: a correction replaces the word in place",
          root.textNow() == "this sentence is here", root.textNow())
    root.rebuild()
    settle()
    check("marker: nothing marked once it is spelled right",
          root.spanCount() == 0, root.spanCount())

    # a correctly spelled document draws nothing at all
    root.setText("the quick brown fox")
    settle()
    root.rebuild()
    settle()
    check("marker: a correctly spelled line is unmarked",
          not redrows(view.grabWindow()), sorted(redrows(view.grabWindow())))

    # the right-click offer
    check("marker: no offer where nothing is wrong", root.menuLabels(5) == "",
          root.menuLabels(5))
    root.setText("this sentance is here")
    settle()
    root.rebuild()
    settle()
    labels = root.menuLabels(9).split(",")
    check("marker: the menu offers suggestions and a learn item",
          "sentence" in labels and "add to dictionary" in labels, labels)
    check("marker: the offer ends with a separator",
          labels and labels[-1] == "|", labels)

    check("marker: no QML warnings", not warnings, warnings[:4])
    view.close()


test_tokeniser()
test_engine()
test_marker()

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
if SKIPS:
    print("SKIPPED: " + ", ".join(SKIPS))
print("done" if not FAILS else "FAILURES")
sys.exit(1 if FAILS else 0)
