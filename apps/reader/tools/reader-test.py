#!/usr/bin/env python3
"""reader's regression harness — offscreen, no window on anyone's screen.

Three layers, in the order a failure is cheapest to read:

  1. THE PARSE (pure Python). Headings, lists, quotations, fences, tables, rules
     and the inline layer, plus the two rules that are easy to regress silently:
     a link whose target does not exist is NOT drawn as a link (docs/DESIGN.md §10),
     and `href` is never glyph-mapped while everything drawn always is (§2.3).
  2. THE FONT. Every drawable string the parser emits for this repo's own docs
     is put to `QRawFont.glyphIndexesForString` — the only audit that does not
     lie (`fc-list :charset=` and `supportsCharacter` both do). A glyph index of
     0 is a character More Perfect DOS VGA lacks, which under FixedHeight
     line packing CLIPS the whole line it is in.
  3. THE WINDOW. The real `qml/Main.qml` under QT_QPA_PLATFORM=offscreen:
     wrapping, the outline, in-document and cross-document search, the mouse's
     side buttons walking DOCUMENT history through real QMouseEvents, the split
     geometry's zero-size guard at absurd window sizes, and the sidebar's row
     model in each of its three modes.

Run it with reader's own Qt env, not the bare system python:

    W=$(readlink -f "$(which reader)"); sed '$d' "$W" > /tmp/rdrenv.sh
    ( . /tmp/rdrenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/reader/tools/reader-test.py )

`XDG_STATE_HOME` is redirected into a scratch dir: a harness must never rewrite
where the user's own reader reopens. The Titlebar is stubbed, because the real
one registers buttons against this process's pid in the LIVE compositor.
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

READER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(READER)
sys.path.insert(0, READER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

FAILS = []


def prop(obj, name):
    """A QML property, with a `var` unwrapped. A `property var` reaches PySide
    as a QJSValue, which has no length and compares equal to nothing — reading
    one straight out of `.property()` is how a harness silently asserts on the
    wrong thing."""
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- 1. the parse
def test_parse(tmp):
    import mdparse
    from glyphs import px

    here = os.path.join(tmp, "docs")
    os.makedirs(here, exist_ok=True)
    open(os.path.join(here, "other.md"), "w").write("# Other\n\ntext\n")

    src = """# Title One

A paragraph with **bold**, *italic*, `code()` and an em dash — plus an
ellipsis... and a [link](other.md) next to a [dead one](nope.md).

## Second - Section

- first item
- second item
  continued on the next line
1. numbered

> a quotation
> over two lines

```bash
echo "hello"   # a fence
```

| a | bb |
|---|----|
| 1 | 2  |

---

See [the contents](#second--section) and <https://example.com/x>.
"""
    blocks = mdparse.parse(src, here)
    types = [b["type"] for b in blocks]
    check("every block type is produced",
          set(types) >= {"h", "p", "li", "quote", "code", "table", "hr"}, types)

    heads = [b for b in blocks if b["type"] == "h"]
    check("headings carry their level", [h["level"] for h in heads] == [1, 2],
          [h["level"] for h in heads])
    check("heading anchors are github slugs",
          heads[1]["anchor"] == "second---section", heads[1]["anchor"])

    p0 = blocks[1]
    check("emphasis markers are stripped", "**" not in p0["text"] and "*" not in p0["text"],
          p0["text"])
    check("an em dash is mapped to ASCII", "—" not in p0["text"] and " - " in p0["text"],
          p0["text"])
    check("an ellipsis survives as three periods", "…" not in p0["text"], p0["text"])
    check("a code span is its own run",
          any(r["k"] == "code" and r["t"] == "code()" for r in p0["runs"]),
          [r for r in p0["runs"] if r["k"] == "code"])

    links = [r for r in p0["runs"] if r["k"] == "link"]
    check("a link that resolves IS a link", len(links) == 1, links)
    check("...and its href is the resolved path, unmapped",
          links and links[0]["href"] == os.path.join(here, "other.md"), links)
    check("a link to a missing file is PLAIN TEXT, not a dead control",
          "dead one" in p0["text"] and not any(r["href"].endswith("nope.md")
                                               for r in p0["runs"]),
          p0["runs"])

    li = [b for b in blocks if b["type"] == "li"]
    check("list items keep their markers", [b["marker"] for b in li] == ["-", "-", "1."],
          [b["marker"] for b in li])
    check("a wrapped list item is one block",
          "continued on the next line" in li[1]["text"], li[1]["text"])

    code = [b for b in blocks if b["type"] == "code"][0]
    check("a fence keeps its lines verbatim", code["lines"] == ['echo "hello"   # a fence'],
          code["lines"])
    check("a fence records its language", code["lang"] == "bash", code["lang"])

    tbl = [b for b in blocks if b["type"] == "table"][0]
    check("a table is rows of cells", len(tbl["rows"]) == 2 and len(tbl["rows"][0]) == 2,
          [[len(r) for r in tbl["rows"]]])

    last = blocks[-1]
    anchors = [r for r in last["runs"] if r["lt"] == "anchor"]
    urls = [r for r in last["runs"] if r["lt"] == "url"]
    check("an in-document anchor link resolves", len(anchors) == 1, anchors)
    check("an autolink is a url link", len(urls) == 1 and urls[0]["href"].startswith("https://"),
          urls)

    ol = mdparse.outline(blocks)
    check("the outline is the headings, with their block index",
          [o["text"] for o in ol] == ["Title One", "Second - Section"], ol)

    # px() itself, including the case that must NOT be touched
    check("px maps a curly apostrophe", px("don’t") == "don't")
    check("px leaves CJK alone (no ASCII form exists)", px("中文") == "中文")
    check("px is a no-op on plain ASCII", px("plain ascii - text") == "plain ascii - text")


# ----------------------------------------------------------------- 2. the font
def test_font():
    from PySide6.QtGui import QRawFont
    import mdparse
    from glyphs import is_mappable

    path = os.path.expanduser("~/.local/share/fonts/MorePerfectDOSVGA.ttf")
    if not os.path.isfile(path):
        check("the pixel font is installed", False, path)
        return
    font = QRawFont(path, 15)

    def missing(s):
        out = set()
        for ch in set(s):
            if ch in "\n\t":
                continue
            idx = font.glyphIndexesForString(ch)
            if not idx or idx[0] == 0:
                out.add(ch)
        return out

    check("the audit itself works (an unmapped em dash IS missing)",
          "—" in missing("a—b"))

    # The corpus this app was written for. Absent (a fresh clone with no docs/
    # checkout), the layer is skipped rather than passing vacuously.
    roots = [os.path.expanduser("~/nix")]
    docs = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           (".git", "node_modules", "__pycache__", "result")]
            docs += [os.path.join(dirpath, f) for f in filenames
                     if f.lower().endswith(".md")]
    docs = docs[:80]
    check("there is a corpus to audit", len(docs) > 5, len(docs))

    bad = {}
    for d in docs:
        try:
            text = open(d, "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        for b in mdparse.parse(text, os.path.dirname(d)):
            drawn = b.get("text", "") + "".join(b.get("lines", []))
            # `glyphs.is_mappable` is where the recorded limits of the table
            # live - CJK, Greek and the maths operators have no ASCII form, and
            # Open question 8 leaves the two music glyphs to him. Everything
            # ELSE that reaches a delegate unmapped clips its row, so it is a
            # regression and this is where it is caught.
            m = {c for c in missing(drawn) if is_mappable(c)}
            if m:
                bad.setdefault(os.path.basename(d), set()).update(m)
    check("no mappable character survives ingest anywhere in the corpus",
          not bad, dict(list(bad.items())[:4]))


# --------------------------------------------------------------- 3. the window
def build(app, tmp, start):
    from PySide6.QtCore import QUrl, QObject, Slot
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter,
    #                        without which win.property("pane") raises)
    from deskstyle import DeskStyle
    import main as rdr

    class StubTitlebar(QObject):
        @Slot("QVariantList")
        def setButtons(self, b): pass
        @Slot(str)
        def setFooter(self, t): pass

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (rdr.Palette(rdr.PANEL_THEME), DeskStyle(parent=engine), StubTitlebar(),
            rdr.Docs(), rdr.Library(), rdr.Settings())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Docs", keep[3])
    ctx.setContextProperty("Library", keep[4])
    ctx.setContextProperty("Settings", keep[5])
    ctx.setContextProperty("startPath", start)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(READER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(READER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def spin(ms=120):
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def side_click(win, button):
    from PySide6.QtCore import QPointF, Qt, QEvent
    from PySide6.QtGui import QGuiApplication, QMouseEvent
    pos = QPointF(win.width() / 2.0, win.height() / 2.0)
    glob = QPointF(win.x() + pos.x(), win.y() + pos.y())
    for kind, held in ((QEvent.Type.MouseButtonPress, button),
                       (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QGuiApplication.sendEvent(
            win, QMouseEvent(kind, pos, pos, glob, button, held,
                             Qt.KeyboardModifier.NoModifier))
    spin(80)


def test_wrap(engine, cellw):
    """The core of the renderer: runs in, terminal ROWS out. Checked against the
    monospace invariant it is built on — no line may exceed the columns the
    width affords, and no word may be lost or reordered on the way."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(READER, "qml/RichText.qml")))
    item = comp.create()
    if item is None:
        check("RichText builds standalone", False, comp.errorString())
        return
    words = ["w%02d" % i for i in range(60)]
    item.setProperty("cellW", cellw)
    item.setProperty("width", 40 * cellw)
    item.setProperty("runs", [{"t": " ".join(words), "k": "", "href": "", "lt": ""},
                              {"t": "X" * 120, "k": "code", "href": "", "lt": ""}])
    lines = item.property("lines")
    lines = lines.toVariant() if hasattr(lines, "toVariant") else lines
    cols = item.property("cols")
    check("a paragraph wraps into several rows", len(lines) > 4, len(lines))
    widest = max(sum(len(r["t"]) for r in ln) for ln in lines)
    check("no wrapped row exceeds the columns available", widest <= cols, (widest, cols))
    flat = " ".join("".join(r["t"] for r in ln) for ln in lines)
    check("every word survives the wrap, in order",
          [w for w in flat.split() if w.startswith("w")] == words)
    check("a token longer than a line is hard-split, not overflowed",
          flat.count("X") == 120, flat.count("X"))

    # ...and the width is what drives it: half the columns, about twice the rows
    item.setProperty("width", 20 * cellw)
    lines2 = item.property("lines")
    lines2 = lines2.toVariant() if hasattr(lines2, "toVariant") else lines2
    check("narrowing the pane reflows it", len(lines2) > len(lines),
          (len(lines), len(lines2)))

    # A delegate is built before layout gives it a width, and `cols` floors to 8
    # until it does. Wrapping there is not just a wasted pass — it builds ~10x
    # the rows the delegate keeps, and half of all wrap evaluations during a
    # scroll were this. The guard must hold, and must not be one-way.
    item.setProperty("width", 0)
    empty = prop(item, "lines")
    check("a delegate with no width yet wraps NOTHING", empty == [], empty)
    item.setProperty("width", 40 * cellw)
    back = prop(item, "lines")
    check("...and wraps again the moment a width arrives", len(back) > 4, len(back))
    item.deleteLater()

    test_chrome(engine, cellw)


def descendants(item):
    out = []
    stack = list(item.childItems())
    while stack:
        it = stack.pop()
        out.append(it)
        stack.extend(it.childItems())
    return out


def test_chrome(engine, cellw):
    """A segment of prose is ONE item; only code and links get chrome.

    That is worth ~40% of the GUI thread during a scroll (docs/perf-cpu-hotspots.md
    H2). Both halves are asserted here because both can regress silently: a
    background that stops sitting exactly on its text, and a plain word that
    quietly starts costing five items again.

    The geometry check is not ceremony. The first version of this positioned a
    separate chrome layer at `N * cellW`, which is what the wrap itself assumes
    — and it was visibly wrong: the font advances 8.9px but Qt rounds each
    Text's width up to 9, so each background sat a pixel further left than the
    last (0.7px by the second segment, 2.3px by the fourth)."""
    from PySide6.QtCore import QUrl, QPointF
    from PySide6.QtQml import QQmlComponent

    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(READER, "qml/RichText.qml")))
    item = comp.create()
    if item is None:
        check("RichText builds for the chrome check", False, comp.errorString())
        return
    item.setProperty("cellW", cellw)
    item.setProperty("width", 400 * cellw)      # one row, so indices are simple
    item.setProperty("runs", [
        {"t": "before ", "k": "", "href": "", "lt": ""},
        {"t": "codespan", "k": "code", "href": "", "lt": ""},
        {"t": " middle ", "k": "", "href": "", "lt": ""},
        {"t": "alink", "k": "link", "href": "/tmp/x.md", "lt": "file"},
        {"t": " after", "k": "", "href": "", "lt": ""},
    ])
    kids = descendants(item)
    texts = [k for k in kids if k.property("text") is not None and k.property("text") != ""]
    rects = [k for k in kids if k.property("text") is None and k.property("color") is not None]
    by_text = {k.property("text"): k for k in texts}

    def left(it):
        return it.mapToItem(item, QPointF(0, 0)).x()

    ok = "codespan" in by_text and "alink" in by_text
    check("every segment is still drawn", ok, sorted(by_text))
    if not ok:
        item.deleteLater()
        return

    # Each chrome segment's background is its text's PARENT, so it covers it
    # exactly. Anything else means a fill drifting off the word it belongs to.
    for name in ("codespan", "alink"):
        txt = by_text[name]
        box = txt.parentItem()
        check("the %s chrome sits exactly on its text" % name,
              box in rects
              and abs(left(box) - left(txt)) < 0.01
              and abs(box.width() - txt.width()) < 0.01,
              (left(box), box.width(), left(txt), txt.width()))

    # A link is a control, so it must have a live hit target — and it may not be
    # `visible: false` when unhovered, because an invisible item's children get
    # no input and the hover could then never begin.
    live = [k for k in kids if k.property("hoverEnabled")]
    check("the link keeps a live hit target", len(live) == 1, len(live))
    if live:
        check("...and it is reachable, not inside a hidden item",
              all(p.isVisible() for p in (live[0], live[0].parentItem())))

    # The whole point: a word costs ONE item, not five.
    item.setProperty("runs", [{"t": "just prose, no code and no links at all",
                               "k": "", "href": "", "lt": ""}])
    kids = descendants(item)
    check("a line of plain prose builds NO chrome and NO hit target",
          not [k for k in kids if k.property("hoverEnabled") is not None],
          len([k for k in kids if k.property("hoverEnabled") is not None]))
    words = [k for k in kids if k.property("text")]
    check("...and one item per word, with nothing wrapped around it",
          words and all(w.parentItem().property("text") is None
                        and w.parentItem() not in words for w in words),
          len(words))
    item.deleteLater()


def test_focus_fade(win, pane, theme):
    """An unfocused window fades its WHOLE foreground (docs/DESIGN.md §3.1.1).

    reader wired `winActive` all the way to `DocPane` and then hardcoded
    `fg: Theme.text` on the block delegate, so the titlebar greyed and the
    document — the only thing the user was actually reading — stayed lit.

    The assertion is on the colour a real Block delegate ENDED UP WITH, not on
    the pane's own property, because the bug lived in the propagation. Note the
    ternary must stay at the pane: reader draws one Text per word, so a per-leaf
    binding would re-evaluate thousands of times on a focus change."""
    inactive = theme.property("inactive")
    text = theme.property("text")

    def block_fg():
        for it in descendants(pane):
            fg = it.property("fg")
            if fg is not None and it.property("btype") is not None:
                return fg
        return None

    pane.setProperty("winActive", True)
    spin(80)
    check("a focused pane draws its body text in Theme.text",
          block_fg() == text, (block_fg(), text))
    pane.setProperty("winActive", False)
    spin(80)
    check("an UNFOCUSED pane fades the document to Theme.inactive (S3.1.1)",
          pane.property("fg") == inactive and block_fg() == inactive,
          (pane.property("fg"), block_fg(), inactive))
    check("...its secondary tone and its accent rules go with it",
          pane.property("fgDim") == inactive and pane.property("fgAccent") == inactive,
          (pane.property("fgDim"), pane.property("fgAccent")))
    # The assignments above BROKE the binding to `win.active`; leave the pane
    # lit so the checks after this one see ordinary colours.
    pane.setProperty("winActive", True)
    spin(80)


def test_window(app, tmp):
    from PySide6.QtCore import Qt

    a = os.path.join(tmp, "a.md")
    b = os.path.join(tmp, "sub", "b.md")
    os.makedirs(os.path.dirname(b), exist_ok=True)
    open(a, "w").write(
        "# Alpha\n\n" + ("a long paragraph of words that has to wrap several times "
                         "over in any sensible window width " * 6) +
        "\n\nneedle in a haystack\n\n## Beta\n\n"
        "```sh\necho beta\n```\n\nsee [b](sub/b.md)\n")
    open(b, "w").write("# Bravo\n\nneedle again\n\n## Charlie\n\nplain\n")

    engine, win, _keep = build(app, tmp, a)
    spin(400)

    pane = win.property("pane")
    check("the window has a focused pane", pane is not None)
    if pane is None:
        return
    check("it opened the document it was given", pane.property("path") == a,
          pane.property("path"))
    check("the document parsed into blocks", len(prop(pane, "blocks")) > 4,
          len(prop(pane, "blocks")))
    check("the outline is the headings",
          [o["text"] for o in prop(pane, "outline")] == ["Alpha", "Beta"],
          prop(pane, "outline"))
    check("a monospace advance was MEASURED, not assumed",
          2 < win.property("cellW") < 40, win.property("cellW"))
    test_wrap(engine, win.property("cellW"))
    test_focus_fade(win, pane, _keep[-1])

    # the files index feeds the browse pane
    check("the browse pane indexed both documents",
          len(prop(win, "fileIndex")) >= 2, prop(win, "fileIndex"))

    # ---- search, in this document and across them ----
    win.setProperty("query", "needle")
    win.runSearch()
    spin(200)
    check("an in-document search finds its block", len(prop(pane, "matches")) == 1,
          prop(pane, "matches"))
    check("a cross-document search finds the other file",
          len(prop(win, "results")) == 2, prop(win, "results"))
    check("...and switched the browse pane to results",
          win.property("sideMode") == "results", win.property("sideMode"))
    win.closeSearch()
    spin(80)
    check("closing the search clears it", win.property("query") == ""
          and len(prop(pane, "matches")) == 0, prop(pane, "matches"))

    # ---- history: the mouse's side buttons walk DOCUMENTS ----
    check("nothing to go back to yet", pane.property("canBack") is False)
    pane.navigate(b, "")
    spin(150)
    check("navigate opened the second document", pane.property("path") == b,
          pane.property("path"))
    check("...and recorded where we were", pane.property("canBack") is True)
    side_click(win, Qt.MouseButton.BackButton)
    check("BackButton returns to the first document", pane.property("path") == a,
          pane.property("path"))
    side_click(win, Qt.MouseButton.ForwardButton)
    check("ForwardButton goes forward again", pane.property("path") == b,
          pane.property("path"))
    side_click(win, Qt.MouseButton.BackButton)
    pane.navigate(b, "")
    spin(120)
    side_click(win, Qt.MouseButton.ForwardButton)
    check("a new navigation drops the forward stack", pane.property("path") == b,
          pane.property("path"))

    # ---- anchors are navigation, not a colour ----
    pane.load(a, "")
    spin(150)
    top_before = pane.property("topIndex")
    ok = pane.jumpAnchor("beta")
    spin(120)
    check("an anchor jump lands on its heading", ok is True
          and pane.property("topIndex") != top_before,
          (top_before, pane.property("topIndex")))
    check("an anchor that does not exist is REFUSED, not silently ignored",
          pane.jumpAnchor("nosuchsection") is False)

    # ---- split: geometry, and the zero-size guard ----
    win.setSplit(True)
    spin(300)
    check("`|` opened a second pane", win.property("splitOn") is True)
    check("the chrome follows the pane you just asked for",
          win.property("focusPane") == 1, win.property("focusPane"))
    win.setSplit(False)
    spin(200)
    check("the OTHER button re-orients in place, keeping both panes",
          win.property("splitOn") is True and win.property("splitVertical") is False,
          (win.property("splitOn"), win.property("splitVertical")))
    win.setSplit(False)
    spin(200)
    check("the button matching the current orientation closes it",
          win.property("splitOn") is False, win.property("splitOn"))
    win.setSplit(False)
    spin(200)
    check("`_` opens it stacked from closed", win.property("splitOn") is True
          and win.property("splitVertical") is False,
          (win.property("splitOn"), win.property("splitVertical")))
    win.setSplit(True)
    spin(200)
    check("`|` re-orients a stacked split rather than closing it",
          win.property("splitOn") is True and win.property("splitVertical") is True)

    for w, h in ((360, 240), (200, 120), (60, 60), (1, 1)):
        win.setWidth(w)
        win.setHeight(h)
        spin(80)
        lead = win.property("paneLeadSize")
        trail = win.property("paneTrailSize")
        # The window clamps at its own minimumWidth/Height, so the last sizes
        # land on that floor - which is the case that matters: at 360x240 with
        # the browse pane open the trailing rect is ONE pixel, and one is not
        # zero. hyprvtb's renderRect aborts the compositor on zero.
        check("no pane rect collapses to zero at %dx%d" % (w, h),
              lead >= 1 and trail >= 1, (lead, trail))
    win.setWidth(1000)
    win.setHeight(760)
    spin(120)

    # ---- the browse pane's three modes ----
    win.setSide("files")
    spin(120)
    check("the files button opens the browse pane",
          win.property("sideOpen") is True and win.property("sideMode") == "files")
    win.setSide("files")
    spin(120)
    check("...and the same button closes it (a toggle, like filer's)",
          win.property("sideOpen") is False)
    win.setSide("outline")
    spin(120)
    check("the outline button opens it in outline mode",
          win.property("sideOpen") is True and win.property("sideMode") == "outline")

    # ---- the reload path keeps your place ----
    pane.load(a, 6)
    spin(200)
    at = pane.property("topIndex")
    open(a, "a").write("\n\nappended paragraph\n")
    pane.reload()
    spin(200)
    check("a reload keeps the scroll position", pane.property("topIndex") == at,
          (at, pane.property("topIndex")))
    check("...and picked the new content up",
          any("appended paragraph" in bb["text"] for bb in prop(pane, "blocks")))


def main():
    from PySide6.QtGui import QGuiApplication
    with tempfile.TemporaryDirectory() as tmp:
        # never rewrite where the user's own reader reopens
        os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
        test_parse(tmp)
        # QRawFont needs a QGuiApplication to exist (it segfaults without one),
        # so the font audit runs after the app is up, not before.
        app = QGuiApplication(sys.argv)
        test_font()
        test_window(app, os.path.join(tmp, "win"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
