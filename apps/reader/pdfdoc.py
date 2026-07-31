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

    @Slot(str)
    def close(self, key):
        with self._lock:
            doc = self._docs.pop(key, None)
            self._paths.pop(key, None)
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
            out = []
            for i in range(min(doc.pageCount(), MAX_SEARCH_PAGES)):
                sel = doc.getAllText(i)
                if sel is not None and q in (sel.text() or "").lower():
                    out.append(i)
        return out

    # ---- rendering ---------------------------------------------------------

    def render(self, key, gen, page, size):
        """One page as a QImage at `size` pixels. Called by the image provider
        only; the lock is what makes it safe from Qt's loader thread."""
        with self._lock:
            doc = self._docs.get(key)
            if doc is None or gen != self._gen.get(key, 0):
                return None
            if page < 0 or page >= doc.pageCount():
                return None
            w = max(1, min(int(size.width()), MAX_RENDER_PX))
            h = max(1, min(int(size.height()), MAX_RENDER_PX))
            return doc.render(page, QSize(w, h))


class PageProvider(QQuickImageProvider):
    """`image://pdfpage/<key>/<gen>/<page>` -> that page, rasterized at the
    `sourceSize` the delegate asked for.

    An image provider and not a rendered-to-a-temp-file scheme because the URL
    is then a pure function of (document, generation, page, zoom) and Qt's own
    pixmap cache does the caching a page view needs — scrolling back up a
    document re-uses what it drew on the way down.
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
