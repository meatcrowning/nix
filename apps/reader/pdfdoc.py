#!/usr/bin/env python3
"""reader's SECOND document mode: a PDF is rendered pages, not parsed blocks.

`mdparse.py` turns markdown into a flat list of blocks that QML lays out; a PDF
has no such thing to hand out — its pages are already laid out, and the app's
job is to rasterize them at the zoom the user asked for. So this is a parallel
pipeline beside the markdown one rather than a widening of it, and `DocPane.qml`
picks between the two on `doc.kind`.

**Renderer: `PySide6.QtPdf`** — `QPdfDocument.render()` straight to a `QImage`,
served to QML through a `QQuickImageProvider`. It is in this nixpkgs' PySide6
already (checked with the interpreter `home/prog/reader.nix` wraps), so reader
gains a document format and no dependency. `QtPdfQuick` is NOT — there is no
`PdfMultiPageView` QML type to be had here, which is why the continuous view is
built out of a `KineticListView` of `Image`s in `qml/PdfView.qml` like every
other scrollable view in this app (docs/DESIGN.md §9.2).

One `QPdfDocument` per PANE, keyed the way `Docs.watch` is keyed ("left" /
"right"), plus a per-key generation counter: an image URL carries the generation
so that reloading a file the user is looking at busts Qt's pixmap cache instead
of redrawing the old pages (§6.1 — reload in place, and actually reload).
"""
import os
import threading
import time
from collections import OrderedDict

from PySide6.QtCore import QObject, Slot, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument, QPdfBookmarkModel
from PySide6.QtQuick import QQuickImageProvider

# A bookmark title is text this app did not author, so it is glyph-mapped at
# ingest exactly as markdown is — docs/DESIGN.md §2.3, and see `mdparse.py` for
# why a reader cannot skip it.
from mdparse import px

PDF_EXTS = {".pdf"}

#: Nothing is ever rasterized wider than this. A page at 8x zoom on a 4K-wide
#: sheet is a hundred-megabyte QImage that the compositor never sees, and one
#: allocation failure inside a render takes the app with it.
MAX_RENDER_PX = 5000

#: Pages scanned for a find. A find that walks a 4000-page scan on every
#: keystroke is not a find, and the footer reports the truncation (§10.6).
MAX_SEARCH_PAGES = 3000

#: How much rasterized page to keep, in bytes. **Qt's pixmap cache cannot do
#: this job**: `QQuickPixmapStore`'s limit for unreferenced pixmaps is a
#: hardcoded 2 MB with no env knob (checked in this Qt, 6.11.1), and ONE
#: fit-width page in a 1000px pane is 980x1270 RGB32 ~ 5 MB. So every page that
#: scrolled out of the delegate range was evicted the moment it was released,
#: and scrolling back up re-rasterized it — measured 2026-07-31 on `top`,
#: scrolling a 340-page novel down and back: 20 provider calls for 13 distinct
#: pages, 7 of them redraws at 0.3-29 ms each. 96 MB is ~19 fit-width pages, which
#: covers a scroll-and-come-back without holding a book.
CACHE_BYTES = int(os.environ.get("READER_PDF_CACHE_BYTES", 96 * 1024 * 1024))


def is_pdf(path):
    return os.path.splitext(str(path))[1].lower() in PDF_EXTS


class PdfLibrary(QObject):
    """The open PDFs, one per pane, and everything QML asks about them.

    Every method takes the pane `key`, so the two panes of a split can hold two
    different PDFs — the same shape `Docs.watch` already uses.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._docs = {}         # key -> QPdfDocument
        self._gen = {}          # key -> int, bumped on every (re)load
        self._paths = {}        # key -> str
        # `render` is reached from the image provider, which Qt may call on its
        # own texture thread; one PDFium document is not two callers' to share.
        self._lock = threading.Lock()
        #: (key, gen, page, w, h) -> QImage, in use order. THE page cache — see
        #: CACHE_BYTES for why Qt's own one cannot be it.
        self._raster = OrderedDict()
        self._raster_bytes = 0
        #: (key, gen, page) -> lowercased page text. A find re-ran `getAllText`
        #: over the whole document on EVERY KEYSTROKE: 500 ms per key on a
        #: 340-page novel, 235 ms on a 153-page one, all of it on the GUI
        #: thread (measured 2026-07-31 on `top`). The text of a page cannot
        #: change without a reload, and a reload bumps `gen`.
        self._text = {}
        #: rasters actually drawn vs served from the cache — what
        #: `tools/pdf-profile.py` reports, and the only way to tell a page that
        #: was re-REQUESTED from one that was re-RASTERIZED.
        self.rastered = 0
        self.cached = 0

    # ---- loading -----------------------------------------------------------

    @Slot(str, str, result="QVariantMap")
    def open(self, key, path):
        """{ok, kind, path, name, pageCount, pages:[{w,h}], outline, error}.

        `pages` is in POINTS, as the file states them — QML multiplies by the
        zoom to get pixels, so the layout is right before a single page has been
        rasterized and the view never resizes under the reader once the images
        arrive.
        """
        p = os.path.abspath(os.path.expanduser(str(path)))
        base = {"ok": False, "kind": "pdf", "path": p, "name": os.path.basename(p),
                "pageCount": 0, "pages": [], "outline": [], "error": ""}
        doc = QPdfDocument(self)
        err = doc.load(p)
        if err != QPdfDocument.Error.None_ or doc.status() != QPdfDocument.Status.Ready:
            base["error"] = {
                QPdfDocument.Error.FileNotFound: "no such file",
                QPdfDocument.Error.InvalidFileFormat: "not a readable PDF",
                QPdfDocument.Error.IncorrectPassword: "password protected",
                QPdfDocument.Error.UnsupportedSecurityScheme: "unsupported encryption",
                QPdfDocument.Error.DataNotYetAvailable: "incomplete file",
            }.get(err, "cannot read")
            return base

        with self._lock:
            old = self._docs.get(key)
            self._docs[key] = doc
            self._gen[key] = self._gen.get(key, 0) + 1
            self._paths[key] = p
            self._forget(key)
        if old is not None:
            old.close()
            old.deleteLater()

        n = doc.pageCount()
        pages = []
        for i in range(n):
            s = doc.pagePointSize(i)
            w, h = s.width(), s.height()
            # A degenerate page size becomes a zero-size Image, and reader feeds
            # the vtb socket — hyprvtb's renderRect aborts the compositor on a
            # zero-size box (docs/DESIGN.md §12). Floor it here, once.
            pages.append({"w": w if w > 1 else 612.0, "h": h if h > 1 else 792.0})

        # Warm the find index in the background — see `_warm_text`. A timer
        # rather than a thread started here, so the first screenful of pages
        # rasterizes before anything else touches PDFium.
        t = threading.Timer(1.5, self._warm_text, args=(key, self._gen[key]))
        t.daemon = True
        t.start()

        base.update({"ok": True, "pageCount": n, "pages": pages,
                     "gen": self._gen[key], "key": key,
                     "outline": self._outline(doc, n),
                     "title": str(doc.metaData(QPdfDocument.MetaDataField.Title) or "")})
        return base

    def _outline(self, doc, pageCount):
        """The document's bookmarks, in the shape `Sidebar.qml`'s outline mode
        already draws: `{text, index, level, anchor}` — with `index` a PAGE
        rather than a block, which is exactly what `DocPane.jumpIndex` means in
        this mode. A PDF with no bookmarks falls back to its page list, so the
        outline pane is never an empty strip next to a 400-page document."""
        model = QPdfBookmarkModel()
        model.setDocument(doc)
        out = []

        def walk(parent, level):
            for r in range(model.rowCount(parent)):
                idx = model.index(r, 0, parent)
                title = str(model.data(idx, QPdfBookmarkModel.Role.Title.value) or "")
                page = model.data(idx, QPdfBookmarkModel.Role.Page.value)
                out.append({"text": px(title), "index": int(page or 0),
                            "level": level, "anchor": ""})
                walk(idx, level + 1)

        walk(model.index(-1, -1), 1)
        model.setDocument(None)
        if out:
            return out
        return [{"text": "page " + str(i + 1), "index": i, "level": 1, "anchor": ""}
                for i in range(pageCount)]

    # ---- the caches --------------------------------------------------------

    def _forget(self, key):
        """Drop everything remembered about one pane. Caller holds the lock.

        Called on every (re)open as well as on close: the generation in the key
        already keeps a stale raster from being SERVED, but nothing would ever
        evict it, so a document reloaded ten times would hold ten copies."""
        for k in [k for k in self._raster if k[0] == key]:
            self._raster_bytes -= self._raster.pop(k).sizeInBytes()
        for k in [k for k in self._text if k[0] == key]:
            del self._text[k]

    def _warm_text(self, key, gen):
        """Extract the document's text in the background, a page at a time.

        The find bar calls `search` on EVERY KEYSTROKE, and the first call is
        the one that pays for the whole document — 508 ms on a 340-page novel,
        on the GUI thread. Caching made every keystroke after the first free
        (0.1-0.5 ms); this is what makes the first one free too.

        It starts a beat after the open, so it is never competing with the
        first screenful of pages, and it takes the lock **per page** rather
        than for the sweep, so a page the reader is actually waiting for is
        never behind more than one extraction (~1.5 ms)."""
        i = 0
        while True:
            with self._lock:
                doc = self._docs.get(key)
                if doc is None or gen != self._gen.get(key, 0):
                    return
                if i >= min(doc.pageCount(), MAX_SEARCH_PAGES):
                    return
                self._page_text(key, gen, doc, i)
            i += 1
            time.sleep(0.002)   # stay out of the renderer's way

    def _page_text(self, key, gen, doc, page):
        """One page's text, lowercased, remembered. Caller holds the lock."""
        ck = (key, gen, page)
        hit = self._text.get(ck)
        if hit is None:
            sel = doc.getAllText(page)
            hit = (sel.text() or "").lower() if sel is not None else ""
            self._text[ck] = hit
        return hit

    @Slot(str)
    def close(self, key):
        with self._lock:
            doc = self._docs.pop(key, None)
            self._paths.pop(key, None)
            self._forget(key)
        if doc is not None:
            doc.close()
            doc.deleteLater()

    # ---- finding -----------------------------------------------------------

    @Slot(str, str, result="QVariantList")
    def search(self, key, query):
        """The PAGES holding `query`, in order — the same list of jump targets
        `DocPane`'s `matches` already holds for markdown blocks, so Ctrl+F,
        Enter/Shift+Enter and the `n/m` footer work in this mode with no second
        mechanism. The match is not drawn inside the page: the geometry of a hit
        would have to come out of PDFium as well, and a page that is not marked
        at all beats a mark that is a few points off the word."""
        q = (query or "").strip().lower()
        if len(q) < 2:
            return []
        with self._lock:
            doc = self._docs.get(key)
            if doc is None:
                return []
            gen = self._gen.get(key, 0)
            out = []
            for i in range(min(doc.pageCount(), MAX_SEARCH_PAGES)):
                if q in self._page_text(key, gen, doc, i):
                    out.append(i)
        return out

    # ---- rendering ---------------------------------------------------------

    def render(self, key, gen, page, size):
        """One page as a QImage at `size` pixels, from the cache if it is there.

        Called by the image provider only; the lock is what makes it safe from
        Qt's loader thread. A hit costs a dict lookup instead of the 3-50 ms
        PDFium raster — and the raster does not release the GIL, so it is not
        only the reader thread it costs (measured: Python on the GUI thread
        runs at 15% of its rate while a page is rasterizing)."""
        w = max(1, min(int(size.width()), MAX_RENDER_PX))
        h = max(1, min(int(size.height()), MAX_RENDER_PX))
        ck = (key, gen, page, w, h)
        with self._lock:
            hit = self._raster.get(ck)
            if hit is not None:
                self._raster.move_to_end(ck)
                self.cached += 1
                return hit

            doc = self._docs.get(key)
            if doc is None or gen != self._gen.get(key, 0):
                return None
            if page < 0 or page >= doc.pageCount():
                return None
            img = doc.render(page, QSize(w, h))
            self.rastered += 1
            if img is None or img.isNull():
                return img

            self._raster[ck] = img
            self._raster_bytes += img.sizeInBytes()
            # Evict oldest-first, but never the page just rendered: a single
            # page larger than the whole budget must still be served.
            while self._raster_bytes > CACHE_BYTES and len(self._raster) > 1:
                self._raster_bytes -= self._raster.popitem(last=False)[1].sizeInBytes()
            return img


class PageProvider(QQuickImageProvider):
    """`image://pdfpage/<key>/<gen>/<page>` -> that page, rasterized at the
    `sourceSize` the delegate asked for.

    An image provider and not a rendered-to-a-temp-file scheme because the URL
    is then a pure function of (document, generation, page, zoom). The CACHING
    is `PdfLibrary`'s, not Qt's: `QQuickPixmapStore` drops an unreferenced
    pixmap past 2 MB and a page is ~5 MB, so scrolling back up used to
    re-rasterize every page. See CACHE_BYTES.
    """

    def __init__(self, lib):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lib = lib

    def requestImage(self, iid, size, requestedSize):
        try:
            key, gen, page = str(iid).split("/")[:3]
            want = QSize(requestedSize.width(), requestedSize.height())
            if want.width() <= 0 or want.height() <= 0:
                want = QSize(612, 792)
            img = self._lib.render(key, int(gen), int(page), want)
        except (ValueError, TypeError):
            img = None
        if img is None or img.isNull():
            # Never hand QML a null image: an Image with a broken source draws
            # nothing at all and says nothing either (§10.2). A blank page of
            # the right size at least keeps the scroll geometry honest.
            img = QImage(max(1, requestedSize.width() or 612),
                         max(1, requestedSize.height() or 792),
                         QImage.Format.Format_RGB32)
            img.fill(Qt.GlobalColor.white)
        return img
