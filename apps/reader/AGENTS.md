# `reader` — the document reader (markdown, and PDFs)

Vendored source of the standalone document reader: `main.py`, `mdparse.py`,
`pdfdoc.py` and `qml/`. Built and installed by `home/prog/reader.nix`, which mirrors
`viewer.nix` exactly (including the `air` system-python split) and runs the
**live** source at `/home/lam/nix/apps/reader/main.py`, so `.py`/`.qml` edits
need no rebuild. See [`../AGENTS.md`](../AGENTS.md) for the rules shared by all
seven apps, and `~/nix/docs/DESIGN.md` before you draw anything.

Two jobs, and the code splits along them: **read** a document (`mdparse.py` →
blocks → `qml/Block.qml`) and **browse** the documents around it (`Library` →
`qml/Sidebar.qml`). It was written for this repo's own corpus — a 2300-line
`docs/DESIGN.md`, nine `AGENTS.md`/`CLAUDE.md` files and fifteen under `docs/`
— and every layout decision below was made against that, not against markdown
in the abstract.

```bash
reader ~/nix/docs/DESIGN.md     # a file
reader ~/some.pdf               # a PDF: the page mode, below
reader ~/nix                    # a directory: opens its README, else its first document
reader                          # the document you had open last, whichever kind
```

## Two DOCUMENT modes, and `doc.kind` is the only place that picks

A PDF is a rendered-page pipeline, not a block pipeline, so it is a **second
mode beside** the markdown one rather than a widening of `mdparse.py`:

| | markdown | PDF |
|---|---|---|
| parse | `mdparse.parse()` -> blocks | — the file is already laid out |
| model | a flat list of blocks | a page count and each page's size **in points** |
| view | `KineticListView` of `Block.qml` | `KineticListView` of `Image`s, `qml/PdfView.qml` |
| an *index* is | a block | a page |
| the outline pane holds | headings | bookmarks, else a page list |

`Docs.load(path, paneKey)` returns one map either way, and everything else in
the app is written against the fields both modes fill in — `ok`, `path`,
`name`, `error`, `outline`, plus the pane's `topIndex` and `matches`. That is
why history, the sidebar, the footer, the split, the drop target, the
last-document memory and the reload-in-place watch needed **no second version
of themselves**, and why a change to any of them must stay in those terms. The
branch itself is `DocPane.qml`'s `isPdf`, and it is one `Loader`.

- **`pdfdoc.py` is `PySide6.QtPdf`, and that is deliberate.** `QPdfDocument`
  renders a page straight to a `QImage` and is in this nixpkgs' PySide6
  already, so a whole document format cost no dependency — verified against the
  interpreter `reader.nix` wraps, `python3 -c "from PySide6 import QtPdf"`.
  **`QtPdfQuick` is NOT there**: there is no `PdfMultiPageView`/`PdfScrollablePageView`
  QML type on this machine, which is why the continuous view is the app's own
  `KineticListView` — which it would have to be anyway (§9.2: momentum belongs
  to the compositor, and no view adds its own).
- **Pages reach QML through an image provider**, `image://pdfpage/<paneKey>/<gen>/<page>`,
  with `sourceSize` carrying the zoom. The URL is a pure function of what is
  drawn, so Qt's pixmap cache *is* the page cache and scrolling back up
  redraws nothing — and `gen`, bumped on every open, is what makes a file that
  changed on disk actually re-rasterize instead of redrawing the old pages
  (§6.1).
- **One `QPdfDocument` per PANE**, keyed the way `Docs.watch` is keyed, so a
  split can hold two PDFs. `PdfLibrary.render` takes a lock: Qt may call the
  provider off the GUI thread, and one PDFium document is not two callers' to
  share.
- **Zoom is `fit` (a MODE) plus `zoom` (a number).** `width` and `page` survive
  a window resize and are what the `fw`/`fp` cells light for; stepping in or
  out drops to `none`, because that is the only honest reading of "fit"
  (§10.1). Fit-width measures the **widest** page, so one landscape plate in a
  portrait document does not make that page scroll sideways. A zoom re-pins the
  page you were on afterwards — never the pixel offset, which at page 40 of 400
  lands you at page 3.
- **Find inside a PDF is `Pdf.search`**, page text out of PDFium, filling the
  same `matches` list the markdown mode fills with block indices — so Ctrl+F,
  Enter/Shift+Enter and the `n/m` footer are one mechanism. The hit is **not**
  marked inside the page (its geometry would have to come out of PDFium too);
  the page holding the current match takes the `accent` hairline instead of the
  `border` one. **Cross-document search skips PDFs** — matching a query against
  a PDF's bytes finds nothing a reader would recognise — and that is the one
  place the two modes are not equal.
- **Chrome: `−` `+` `fw` `fp` `gp`**, inserted between the find cell and the
  splits and present only in this mode. `−` is U+2212, never a hyphen: a bare
  `-` is the SPACER token in the vtb button-array protocol. Keys are viewer's
  (`+` `−` `0`), plus `w` for fit-width, PageUp/PageDown, Home/End and
  **Ctrl+G**, which slides out a page-number chip beside the find chip. A page
  outside the document is refused **in the footer**, never silently (§10.2).
- The footer reads `<page>/<count>  <zoom>%  <name>`.

## The parse is ours, and Qt's `Text.MarkdownText` is not used

The full argument is `mdparse.py`'s module docstring; the short version is four
rules it would break: it is not `Text.PlainText` (§2.6 — and it renders embedded
HTML, in a program whose entire input is files someone else wrote), it draws
headings **bold and larger** (§2.2, §2.1), `lineHeight`/`FixedHeight` cannot pack
a mixed-leading document like kitty (§2.1), and there would be no block, run or
heading to hang document history, a copy action, an outline or a search
highlight on. The cost is inline images and bold — both already accepted losses
on this desktop.

**An HTML comment is drawn by nothing** - it used to come out as an ordinary
paragraph, which showed up when `docs/board.md` grew one: `boardparse`'s
`<!-- answered-on: <host> -->` stamp, saying which machine an answer was typed
on so that board-watch, which now runs on both, cannot work it twice
(`apps/board/AGENTS.md`). `mdparse` skips a comment as a BLOCK, since one may
span lines, and an unterminated one to the end of the file - what every renderer
does. Regression: `tools/reader-test.py`.

**Blocks in, rows out.** `mdparse.parse()` returns a flat list of dicts
(`h`, `p`, `li`, `quote`, `code`, `table`, `hr`), each carrying inline **runs**
(`plain | code | link`). `qml/RichText.qml` wraps runs into terminal rows: the
font is monospace, so a row of N characters is exactly `N * cellW` wide whatever
it is made of, and that is what lets a line be broken at a word boundary and
re-assembled out of several `PixelText`s with no drift. `cellW` is **measured**
once in `Main.qml` (a `TextMetrics` over ten `M`s — 8.4px at 15, not §2.7's
rounded 8), so it stays right if the desktop font family is ever changed.

- **A segment of prose is ONE item.** A `DelegateChooser` on the run's kind
  gives a plain word a bare `PixelText`, and builds a background or a hit target
  only for code and links. It used to be an `Item`, two `Rectangle`s, a
  `PixelText` and a `MouseArea` around every segment — half the cost of building
  a delegate, to draw nothing on almost every one of them. The wrap also returns
  nothing until a width arrives, because `cols` floors to 8 before layout
  reaches a delegate and wrapping there builds ~10x the rows it keeps. Both are
  measured by `docs/agents/perf-harness/h3.py` and asserted by
  `tools/reader-test.py`; the findings are in `docs/perf-cpu-hotspots.md`.
- **Do not position the code/link backgrounds by character arithmetic.** The
  font advances 8.9px but Qt rounds each `Text`'s width up to 9, so a separate
  chrome layer at `N * cellW` drifts off its text a pixel at a time. The `Row`
  lays chrome and prose out together, which is what makes it exact.
- **Emphasis markers are stripped and carry nothing.** §2.2's "bold emphasis is
  a deliberately accepted loss", applied.
- **No block reads a foreground colour off `Theme`.** `DocPane` derives
  `fg`/`fgDim`/`fgAccent` once from `winActive` and hands them down; `Block`
  passes them into `RichText`, which already gives each word a single
  `color: root.color` binding. §3.1.1 — an unfocused window fades its whole
  foreground, and the delegate is drawn per *word*, so the ternary lives at the
  pane and not at the leaf. `Block.qml` hardcoding `Theme.text` here is what
  left the document lit under a greyed titlebar.
- **Inline code takes `Theme.bgAlt`**, the inset background every other inset
  surface on this desktop takes. A fenced block is that fill inside the 1px
  `Theme.border` hairline. No radius, no new colour (§4, §3.1).
- **A link is UNDERLINED and fills `Theme.highlight` on hover.** Body text *is*
  the accent (§3.1), so there is no brighter colour to promote a link to; the
  underline is a property of the type rather than an invented token, and the
  hover fill is the same one every menu row and list row uses (§7.2).
- **A heading is told apart by a RULE and by spacing, never by size or weight** —
  accent for `h1`, the border hairline for `h2`, indentation below that. The
  outline pane is the real navigation.
- **A code block WRAPS; it never scrolls sideways and never elides.** The
  content has to stay complete because it is meant to be read and copied, and
  this desktop has no nested scroll regions (§9.2). A continuation carries a
  two-cell hanging indent.
- **Tables are free with a monospace font**: a column is as wide as its widest
  cell, and the set is scaled down proportionally (never below four characters,
  cells eliding) when the row will not fit.

## Foreign text is glyph-mapped at INGEST — `pylib/glyphs.py`

A markdown document is nothing but text this app did not author, so §2.3 is not
optional here: a character More Perfect DOS VGA lacks takes a taller fallback
ascent and, under `FixedHeight` packing, **clips the whole line it is in**.

`apps/pylib/glyphs.py` is the apps-side twin of the panel's
`quickshell-files/Glyphs.qml` — same table, two roofs, retune both — and
`mdparse.py` maps every drawable string through it as the file is parsed, once,
rather than per delegate per scroll. **`href` is never mapped**: it is a path or
a URL that gets opened, and §2.3's display-only rule is a safety rule.

**Writing this app found 330 `§` in this repo's own documents, and the font has
no `§`.** Twenty-odd more characters were in the same state (`⇒ ↔ ✓ ✗ ▲ ▼ ● ‖ ≠
¹ ³ ⁰ ⁻ ₀ ✕ ▶ ⚠ ↩ ≫ ★ ⚑ …`), every one of them clipping a row in the panel as
well. Both tables gained them. `§` is the one entry with no exact ASCII
equivalent — `S` is what the glyph is drawn from, and `S2.3` beats a clipped
row. `glyphs.is_mappable()` records what is deliberately left alone (CJK, Greek,
the maths operators, and the two music glyphs DESIGN.md's Open question 8 leaves
to him) so the harness can tell a known limit from a new regression.

## Browsing: an outline AND a file list, in one strip

`qml/Sidebar.qml` is one pane with three modes, and the titlebar cell that is
lit says which:

| cell | mode |
|---|---|
| `ol` | this document's headings, indented by level, **with the section the viewport is inside marked** — so it doubles as a position readout |
| `fl` | every document under the document's git root (else its own directory) — `.md` **and `.pdf`**, by relative path, naturally sorted |
| — | search results, while a query is live |

`main.py`'s `OPEN_EXTS` is `mdparse.DOC_EXTS | pdfdoc.PDF_EXTS` and is the ONE
answer to "does reader open this?" — the files pane, the drop target, a
directory argument and the last-document memory all read it, and they have to
agree.

The two buttons behave exactly like filer's two split buttons: the lit one
closes the pane, the other re-modes it in place. Both are toggles; neither
opens a second thing.

`docs/DESIGN.md` gaining a Contents table is the argument for the outline
existing at all — an outline pane makes that table redundant, and it is
generated rather than maintained.

## Search: in the document, and across the corpus, at once

`fs`, or **`Ctrl+F` and only `Ctrl+F`** (docs/DESIGN.md §11.2 — the bare `/` was
dropped 2026-07-29), slides a chip out of the right edge — the canonical reveal,
§6.2.1, at `motion.slideMs`. It never reflows the text underneath.

- The key is a **window-scoped `Shortcut`**, not a case in `stage`'s
  `Keys.onPressed` where it used to live: find has to work while the focus is in
  a pane, the sidebar or the chip itself, and a `Keys` handler only fires while
  its own item holds the keyboard. Pressing it again re-selects the query
  (`openSearch()`), which is the find-again gesture.

- **In-document** matching is live per keystroke and free: matching ROWS take
  **`Theme.dim`, and the row you are ON takes `Theme.accent` with `Theme.bg`
  ink** (docs/DESIGN.md §3.6). Enter / Shift+Enter step; the chip and the
  titlebar footer both read `n/m`.
  - Those two used to be `Theme.highlight` for every match plus a 2px accent
    gutter for the current one, and **he could barely see either**. `highlight`
    is the selection fill: `#0f1521` on a pure-black page, **1.15:1**. And the
    gutter drew *nothing* — at `x: -6` on a delegate that sits at x=0 in the
    list's content item, `clip: true` ate all of it, so all three match rows
    came back pixel-identical and find-next read as a scroll. Both measured
    offscreen; the marks are drawn in QML here, by `RichText.qml` per wrapped
    LINE and by `Block.qml` per code line and per table row.
  - The current match's ink is **one binding per line**, not a ternary per word
    (`lineItem.ink`) — this delegate is one `Text` per word and §3.1.1's fade
    already pays that cost once. Inline code gives its `bgAlt` chrome up on the
    accent bar, because `bgAlt` inside accent is a hole and `bg` ink on `bgAlt`
    cannot be read.
- **Across documents** is a filesystem walk, so it runs when the typing settles
  (220 ms) and puts its hits in the browse pane, file by file with line numbers.
  Clicking one opens that file at its first match.
- A row highlight rather than a per-character one is deliberate: a match can
  straddle two runs and two `Text` items, and highlighting characters would
  mean re-implementing the layout it is drawn over.
- **A table row's text is its CELLS' text.** `Block.qml`'s `cellText()` takes a
  cell (a list of runs) and the row delegate's `modelData` is a row (a list of
  cells), so handing it one joined the word `undefined` once per column: a table
  row lit up for the query `undefined` and for nothing else, and a real hit
  inside a table was the one match with no mark at all. Both directions are
  asserted in `tools/reader-test.py`.

## Split view — two documents, filer's geometry

`|` splits right, `_` splits down, each a toggle, the other re-orienting in
place; `win.pane` is the FOCUSED pane and the chrome reads nothing else. It is
filer's `Main.qml` shape almost line for line, and it earns its place here for
the reason it does there: these documents refer to each other constantly, and
reading `docs/DESIGN.md` beside the `AGENTS.md` it governs is the case the app
was written for. `paneTrailSize` keeps filer's `Math.max(1, …)` floor —
reader feeds the vtb socket, and hyprvtb's `renderRect` aborts the compositor on
a zero-size box.

Each pane owns its document, its scroll position, its `NavHistory` and its drop
target. Only the left pane's document and scroll position persist; the right
pane persists its path, which with `split`/`splitVertical`/`splitRatio` is
enough to restore the split as it was — filer's arrangement, and for the same
reason (one `state.json` cannot hold two panes' positions).

## History is DOCUMENT history, and the side buttons walk it

§11.1, desktop-global. `qmlcommon/NavButtons.qml` + `NavHistory.qml`, on the
focused pane, plus `<` and `>` cells that grey themselves from `canBack` /
`canForward` (bound, not polled — `NavHistory` reassigns its stacks so they
notify) and `Alt+Left`/`Alt+Right`. A history entry is `{path, index}`, so
following a link and going back returns you to the *paragraph* you left, not to
the top of the file. Anchor jumps record too.

**A link whose target does not exist is drawn as ordinary text**, decided at
ingest in `mdparse._resolve` — §10, at the only point where it is cheap. A
`#section` that resolves to no heading says so in the footer rather than doing
nothing.

## Persistence, and what is deliberately NOT persisted

`~/.local/state/reader/state.json` (§14): both panes' documents, the scroll
position, the browse pane's mode and width, the split and its ratio. Written on
a settle timer, because the scroll position changes on every wheel notch.

**Window geometry is not in there and must not be**: hyprvtb remembers a
window's geometry per class, so writing it here would be two sources for one
value. The query being typed and the hovered row stay local, as §14 says
transient state should.

A document edited underneath the reader **reloads in place, keeping the scroll
position** — `QFileSystemWatcher` per pane, re-added after each change because
an atomic save replaces the inode. §6.1: the maintenance mechanism must not be
visible.

## Integration

- **`text/markdown` and `application/pdf` → `reader.desktop`**, set centrally in
  `home/prog/mime-defaults.nix`. Nothing claimed `application/pdf` on this
  desktop before, so that is a gap filled and not a preference overridden. That is also the whole of filer's integration:
  filer opens a non-image with `xdg-open`, so a `.md` lands here with no change
  to filer at all.
- The `.desktop` entry uses **`%f`**, not `%F`: reader shows one document per
  window (its split is two documents the user chose, not a queue), so several
  files means several windows. It also accepts a directory.
- It is in the runner for free, being a `.desktop` entry like the other six.

## Verify

```bash
W=$(readlink -f "$(which reader)"); sed '$d' "$W" > /tmp/rdrenv.sh
( . /tmp/rdrenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/reader/tools/reader-test.py )
```

`tools/reader-test.py`, 110 checks, offscreen, four layers: the parse (pure
Python), **the font** (every drawable string this repo's markdown produces, put
to `QRawFont.glyphIndexesForString` — the only audit that does not lie), and the
real `qml/Main.qml` under `QT_QPA_PLATFORM=offscreen` — wrapping, the outline,
both searches, real `QMouseEvent`s for buttons 275/276 walking document history,
the split's toggle/re-orient semantics, the zero-size guard, the reload keeping
its place, and the body text fading to `Theme.inactive` with the window
(§3.1.1 — asserted on a real Block delegate, since the bug was in the
propagation and not in the pane's own property). It redirects `XDG_STATE_HOME` into a scratch dir, which any
harness here **must** do or it rewrites where the user's own reader reopens, and
it stubs the Titlebar, because the real one registers buttons against the
harness's pid in the live compositor.

The fourth layer is **the PDF mode**, on a document the harness WRITES with
`QPdfWriter` — no fixture file in the repo, and real extractable text: the mode
switch, the page count, the bookmark fallback, PDFs listed beside `.md` in the
files pane, all four zoom controls, a jump and the history it records, a
go-to-page refused in words, find-by-page, the titlebar's extra cells, and the
page actually rasterizing — asserted twice, once on the provider's `QImage`
(ink on the sheet) and once on a `grabWindow()` PNG of the whole window (a
sheet drawn in the view at all).

The *appearance* is the user's check, as always.
