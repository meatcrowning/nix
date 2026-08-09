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

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

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

    # An HTML COMMENT is drawn by NOTHING. `docs/board.md` carries one —
    # `boardparse`'s `<!-- answered-on: <host> -->` stamp, which says which
    # machine an answer was typed on so board-watch, running on both machines,
    # cannot work it twice — and reader opens that file from board's `md` cell.
    # It used to be drawn as an ordinary paragraph, in the middle of his prose.
    cm = mdparse.parse("before\n\n<!-- answered-on: top -->\n\nafter\n")
    check("an HTML comment is not drawn at all",
          [b["text"] for b in cm] == ["before", "after"], cm)
    cm2 = mdparse.parse("a\n\n<!-- one\ntwo -->\n\nb\n")
    check("...including a multi-line one, as a block",
          [b["text"] for b in cm2] == ["a", "b"], cm2)
    cm3 = mdparse.parse("a\n\n<!-- never closed\n\nb\n")
    check("...and an unterminated one swallows the rest, like every renderer",
          [b["text"] for b in cm3] == ["a"], cm3)

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

    # The canary: a character the font really does lack, so a `missing()` that
    # has silently started returning nothing cannot pass this layer vacuously.
    # It used to be the em dash — `ffeb2d6` merged 526 codepoints in, that one
    # included, and this assertion was left behind failing. CJK is the honest
    # replacement: `glyphs.is_mappable()` leaves it alone on purpose, so no
    # future merge will quietly cover it.
    check("the audit itself works (an unmapped CJK glyph IS missing)",
          "中" in missing("a中b"))

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
    pdf = rdr.PdfLibrary()
    keep = (rdr.Palette(rdr.PANEL_THEME), DeskStyle(parent=engine), StubTitlebar(),
            rdr.Docs(pdf), rdr.Library(), rdr.Settings(), pdf)
    # The PDF mode's whole drawing path (pdfdoc.py). Registered before Main.qml
    # loads, exactly as `main()` does it, or the first page delegate's source
    # resolves to nothing and the check would pass against a blank sheet.
    engine.addImageProvider("pdfpage", rdr.PageProvider(pdf))
    ctx.setContextProperty("Pdf", pdf)
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


def test_focus_steady(win, pane, theme):
    """An unfocused reader stays on its focused tones (docs/DESIGN.md §3.1.1,
    app-side fade retired 2026-08-09).

    The window pins `renderActive` to `true`, so the native
    decoration:dim_inactive scrim is the one dimming mechanism and the pane is
    never handed an inactive state. Reader used to wire `winActive` all the way
    to `DocPane` and then hardcode `fg: Theme.text` on the block delegate — the
    titlebar greyed and the document, the only thing he was actually reading,
    stayed lit; under the retirement, a document that stays on `Theme.text` is
    the designed behaviour, so the assertion is that the window really does pin
    it and the document really does stay lit."""
    text = theme.property("text")

    def block_fg():
        for it in descendants(pane):
            fg = it.property("fg")
            if fg is not None and it.property("btype") is not None:
                return fg
        return None

    check("the window pins the pane on its focused tones (renderActive is true)",
          pane.property("winActive") is True, pane.property("winActive"))
    check("the document draws its body text in Theme.text, focused or not",
          block_fg() == text, (block_fg(), text))
    check("its secondary tone and its accent rules stay on the focused tones",
          pane.property("fgDim") == theme.property("textDim")
          and pane.property("fgAccent") == theme.property("accent"),
          (pane.property("fgDim"), pane.property("fgAccent")))


def find_bands(img, theme, x0, x1):
    """Contiguous y-ranges of the grab whose x-strip is mostly ONE palette fill.

    Pixels, because the palette is one hue and "surely that reads" has been
    wrong twice (docs/DESIGN.md §3.6). A band shorter than 4px is chrome — an
    h1's accent rule, a table's header hairline — not a row fill."""
    import collections
    want = {theme.property(k).name(): k for k in ("dim", "accent", "highlight")}
    out, run = [], None
    for y in range(img.height()):
        cnt = collections.Counter(img.pixelColor(x, y).name() for x in range(x0, x1))
        name, n = cnt.most_common(1)[0]
        kind = want.get(name) if n > (x1 - x0) * 0.6 else None
        if run and run[0] == kind:
            run[2] = y
        else:
            if run and run[0] and run[2] - run[1] >= 3:
                out.append(tuple(run))
            run = [kind, y, y]
    if run and run[0] and run[2] - run[1] >= 3:
        out.append(tuple(run))
    return out


def band_ink(img, y0, y1, x0, x1):
    """The glyph colour inside a filled band.

    Sampled only BETWEEN the fill's own left and right edge on each row, and out
    to the whole window width rather than the sniffing strip: the matched line is
    short, so a strip taken from 45% of the window can sit entirely past the last
    word and report whatever happens to be beside the bar instead of the ink."""
    import collections
    cnt = collections.Counter()
    for y in range(y0, y1 + 1):
        row = [img.pixelColor(x, y).name() for x in range(img.width())]
        fill = collections.Counter(row[x0:x1]).most_common(1)[0][0]
        if fill not in row:
            continue
        for x in range(row.index(fill), len(row) - row[::-1].index(fill)):
            cnt[row[x]] += 1
    order = [c for c, _ in cnt.most_common()]
    return (order[0], order[1] if len(order) > 1 else None)


def test_find_marks(win, pane, theme):
    """The find marks, in RENDERED PIXELS (docs/DESIGN.md §3.6).

    Every match is `dim` with the body accent on it; the one you are ON is
    `accent` with `bg` ink. It was `Theme.highlight` for all of them — the
    SELECTION fill, `#0f1521` against a pure-black page, 1.15:1 — plus a 2px
    accent gutter for the current one that drew nothing at all, being at
    `x: -6` on a delegate that sits at x=0 inside a `clip: true` viewport. All
    three match rows came back identical to the pixel and find-next read as a
    scroll, which is exactly what he reported."""
    x0, x1 = int(win.width() * 0.45), int(win.width() - 20)
    dim = theme.property("dim").name()
    acc = theme.property("accent").name()
    bg = theme.property("bg").name()

    pane.setProperty("query", "found me")
    spin(200)
    img = win.grabWindow()
    bands = find_bands(img, theme, x0, x1)
    kinds = [b[0] for b in bands]
    check("a find mark is never painted in the near-invisible selection fill",
          "highlight" not in kinds, bands)
    check("every match is marked, and exactly one of them is the current",
          kinds.count("accent") == 1 and kinds.count("dim") >= 1, bands)
    cur = [b for b in bands if b[0] == "accent"]
    rest = [b for b in bands if b[0] == "dim"]
    if cur:
        fill, ink = band_ink(img, cur[0][1], cur[0][2], x0, x1)
        check("the CURRENT match is an accent bar with bg ink",
              (fill, ink) == (acc, bg), (fill, ink, acc, bg))
    if rest:
        fill, ink = band_ink(img, rest[0][1], rest[0][2], x0, x1)
        check("another match is a dim bar with the body accent still on it",
              (fill, ink) == (dim, acc), (fill, ink, dim, acc))
    # stepping moves the accent bar, and leaves the one it came from lit
    before = [b[1] for b in bands if b[0] == "accent"]
    pane.stepMatch(1)
    spin(250)
    bands2 = find_bands(img := win.grabWindow(), theme, x0, x1)
    after = [b[1] for b in bands2 if b[0] == "accent"]
    check("find-next MOVES the accent bar", after and after != before,
          (before, after, bands2))
    check("...and the match it left is still marked",
          [b[0] for b in bands2].count("dim") >= 1, bands2)
    # A match inside a TABLE gets a mark like any other. Its `hit` used to be
    # computed by handing a ROW to a function that takes a CELL, which joined the
    # word "undefined" once per column — so a table row lit up for that query and
    # for nothing else, and a real hit in a table was marked nowhere.
    pane.setProperty("query", "widget")
    spin(200)
    tb = find_bands(win.grabWindow(), theme, x0, x1)
    check("a match inside a table row is marked, and is the current one",
          [b[0] for b in tb] == ["accent"], tb)
    pane.setProperty("query", "undefined")
    spin(200)
    check("...and a word the document does not contain marks nothing",
          not find_bands(win.grabWindow(), theme, x0, x1))
    pane.setProperty("query", "")
    spin(150)
    check("clearing the query drops every mark",
          not find_bands(win.grabWindow(), theme, x0, x1))


def test_window(app, tmp):
    from PySide6.QtCore import Qt

    a = os.path.join(tmp, "a.md")
    b = os.path.join(tmp, "sub", "b.md")
    os.makedirs(os.path.dirname(b), exist_ok=True)
    open(a, "w").write(
        "# Alpha\n\n" + ("a long paragraph of words that has to wrap several times "
                         "over in any sensible window width " * 6) +
        "\n\nneedle in a haystack\n\n"
        # two blocks holding one word, for the find marks' pixel check
        "found me once\n\nfound me twice\n\n"
        "| widget | col |\n|---|----|\n| x | y |\n\n## Beta\n\n"
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
    test_focus_steady(win, pane, _keep[-1])
    test_find_marks(win, pane, _keep[-1])

    # the files index feeds the browse pane
    check("the browse pane indexed both documents",
          len(prop(win, "fileIndex")) >= 2, prop(win, "fileIndex"))

    # ---- Ctrl+F opens and focuses the find bar (docs/DESIGN.md §11.2) ----
    # keyClick, not sendEvent: a QML Shortcut is resolved by the application's
    # shortcut map, which only sees a key delivered through the window system.
    from PySide6.QtTest import QTest
    check("the find bar starts closed", win.property("searchOpen") is False)
    QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    spin(120)
    check("Ctrl+F opens the find bar", win.property("searchOpen") is True)
    win.closeSearch()
    spin(80)

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


# ------------------------------------------------------- 4. the PDF page mode
def make_pdf(path, pages=3):
    """A PDF with real, extractable text, written by Qt itself — so the harness
    needs no fixture file in the repo and no second library."""
    from PySide6.QtGui import QPdfWriter, QPainter, QFont, QPageSize
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setTitle("Harness Document")
    p = QPainter(w)
    f = QFont("Helvetica")
    f.setPointSize(24)
    p.setFont(f)
    for i in range(pages):
        if i:
            w.newPage()
        p.drawText(400, 800, "page %d needle%d here" % (i + 1, i + 1))
    p.end()


def test_pdf(app, tmp):
    """reader's second document mode, end to end: open, page geometry, zoom,
    jump, find, and a real grab of the rendered page — offscreen throughout."""
    from PySide6.QtCore import Qt, QSize
    from PySide6.QtGui import QImage

    os.makedirs(tmp, exist_ok=True)
    doc = os.path.join(tmp, "book.pdf")
    make_pdf(doc, 3)
    open(os.path.join(tmp, "notes.md"), "w").write("# Notes\n\nbeside the pdf\n")

    engine, win, keep = build(app, tmp, doc)
    spin(500)
    pane = win.property("pane")
    if pane is None:
        check("the pdf window has a focused pane", False)
        return

    check("a .pdf argument opens in the PDF mode", pane.property("isPdf") is True)
    check("...and the window knows it", win.property("pdfMode") is True)
    check("the page count is the document's", pane.property("pageCount") == 3,
          pane.property("pageCount"))
    check("a PDF with no bookmarks falls back to a page outline",
          len(prop(pane, "outline")) == 3, prop(pane, "outline"))

    # The files pane lists a PDF beside the .md files it already listed.
    rels = [f["rel"] for f in prop(win, "fileIndex")]
    check("the files pane lists PDFs next to markdown",
          "book.pdf" in rels and "notes.md" in rels, rels)

    # ---- zoom. fit-width is the default, a step drops out of it (§10.1) ----
    check("it opens fit to width", pane.property("fit") == "width", pane.property("fit"))
    wide = pane.property("zoomPct")
    pane.zoomIn()
    spin(200)
    check("zoom in enlarges the page and leaves the fit mode",
          pane.property("zoomPct") > wide and pane.property("fit") == "none",
          (wide, pane.property("zoomPct"), pane.property("fit")))
    pane.zoomOut()
    spin(200)
    check("zoom out is its inverse", abs(pane.property("zoomPct") - wide) < 0.51,
          (wide, pane.property("zoomPct")))
    pane.fitPage()
    spin(200)
    check("fit page fits the whole page", pane.property("fit") == "page"
          and pane.property("zoomPct") <= wide + 0.01,
          (pane.property("fit"), pane.property("zoomPct")))
    pane.fitWidth()
    spin(200)

    # ---- jumping, and the history it records (§11.1) ----
    pane.jumpTo(2)
    spin(300)
    check("jump to a page lands on it", pane.property("topIndex") == 2,
          pane.property("topIndex"))
    check("...and it is walkable with the side buttons", pane.property("canBack") is True)
    pane.goBack()
    spin(300)
    check("back returns to the page you left", pane.property("topIndex") == 0,
          pane.property("topIndex"))

    # ---- go to page: out of range REFUSES VISIBLY, never a no-op (§10.2) ----
    win.gotoPage("2")
    spin(300)
    check("the go-to-page field jumps", pane.property("topIndex") == 1,
          pane.property("topIndex"))
    win.setProperty("status", "")
    win.gotoPage("99")
    spin(120)
    check("a page outside the document is refused in words",
          "no page 99" in str(win.property("status")), win.property("status"))

    # ---- find, inside the PDF ----
    # The refusal above is still in the footer — it is a REPORT and clears
    # itself after four seconds (§10.4). Clear it rather than wait for it.
    win.setProperty("status", "")
    win.setProperty("query", "needle3")
    win.runSearch()
    spin(400)
    check("find inside a PDF matches the page holding the text",
          list(prop(pane, "matches")) == [2], prop(pane, "matches"))
    check("...and the footer reports it",
          "1/1" in str(win.property("footerStr")), win.property("footerStr"))
    win.closeSearch()
    spin(120)
    check("the footer says the page and the zoom",
          "/3" in str(win.property("footerStr"))
          and "%" in str(win.property("footerStr")), win.property("footerStr"))

    # ---- the titlebar carries the mode's own cells, and only in this mode ----
    ids = [b["id"] for b in prop(win, "tbButtons") if not isinstance(b, str)]
    check("the PDF cells are in the titlebar",
          all(i in ids for i in ("zoomout", "zoomin", "fitw", "fitp", "goto")), ids)

    # ---- the page actually RASTERIZED. Two ways, because an Image that never
    # loaded and a page provider that returns white are different failures ----
    img = keep[6].render(pane.property("watchKey"), prop(pane, "doc")["gen"],
                         0, QSize(300, 424))
    check("the provider rasterizes a page", img is not None and not img.isNull()
          and img.size() == QSize(300, 424), img.size() if img else None)
    inked = 0
    if img is not None and not img.isNull():
        rgb = img.convertToFormat(QImage.Format.Format_RGB32)
        for y in range(0, rgb.height(), 3):
            for x in range(0, rgb.width(), 3):
                if rgb.pixelColor(x, y).lightness() < 200:
                    inked += 1
    check("...with ink on it, not a blank sheet", inked > 0, inked)

    # The whole window, grabbed offscreen — never a screenshot of his screen.
    shot = os.path.join(tmp, "pdfview.png")
    grab = win.grabWindow()
    check("the window grabs at its real size",
          not grab.isNull() and grab.width() > 100, grab.size())
    if not grab.isNull():
        grab.save(shot)
        g = grab.convertToFormat(QImage.Format.Format_RGB32)
        # A rendered page is a light sheet on this desktop's near-black page
        # background; if none of the window is light, no page was drawn.
        light = 0
        for y in range(0, g.height(), 5):
            for x in range(0, g.width(), 5):
                if g.pixelColor(x, y).lightness() > 180:
                    light += 1
        check("a page sheet is actually drawn in the window", light > 50, light)

    win.close()
    spin(80)
    del engine, keep


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
        if app.platformName() != "offscreen":   # a mapped window would be HIS screen
            raise SystemExit("refusing to run on platform %r, not offscreen"
                             % app.platformName())
        test_font()
        test_window(app, os.path.join(tmp, "win"))
        test_pdf(app, os.path.join(tmp, "pdf"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
