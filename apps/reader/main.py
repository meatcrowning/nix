#!/usr/bin/env python3
"""reader — the desktop's markdown reader (browse `.md` files, and read them).

The seventh vendored app, and the first one written after `~/nix/docs/DESIGN.md`
existed: everything it draws is taken from that file rather than chosen here.
Pixel font at the desktop's own size through `DeskStyle`, wal palette parsed and
watched out of the panel's `Theme.qml`, motion from `qmlcommon/Motion.qml`
(which reads the compositor's own roll duration), `Kinetic*` views, chrome in the
hyprvtb titlebar through `pylib/vtbclient.py`, and the mouse's side buttons on
document history through `qmlcommon/NavButtons.qml`.

Two jobs, and the split between Python and QML follows them:

  * READ — `mdparse.py` turns a file into a flat list of blocks, with every
    drawable string mapped through `pylib/glyphs.px()` at ingest (docs/DESIGN.md
    §2.3, and see that module for why a markdown reader cannot skip it). QML
    lays the blocks out; Qt's own `Text.MarkdownText` is not used, and
    `mdparse.py`'s docstring says why.
  * BROWSE — `Library` indexes the markdown files around the open document
    (its git root, or its directory) for the files pane and for cross-document
    search. The heading OUTLINE comes from the parse and is the other half of
    browsing: a 2300-line file with 23 sections wants an outline, a directory of
    fifteen wants a list, and this repo has both.

State (`~/.local/state/reader/state.json`) is the app's own, per docs/DESIGN.md §14:
the two panes' documents, the scroll position, the sidebar mode and width, and
the split. Nothing here writes another app's file.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QUrl, QFileSystemWatcher, QProcess
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from kdetheme import theme_source  # noqa: E402  (pylib; the KDE global theme in a Plasma session)

import mdparse  # noqa: E402  (beside this file)
from mdparse import DOC_EXTS  # noqa: E402
import pdfdoc  # noqa: E402  (beside this file — the PDF document mode)
from pdfdoc import PDF_EXTS, PdfLibrary, PageProvider, is_pdf  # noqa: E402

#: Everything reader opens. Two pipelines behind it: markdown goes through
#: `mdparse` to blocks, a PDF through `pdfdoc` to rendered pages — but ONE set
#: of extensions, because the files pane, the drop target, a directory argument
#: and the last-document memory must all agree about what this app reads.
OPEN_EXTS = DOC_EXTS | PDF_EXTS

STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "reader" / "state.json"

# Directories never walked when indexing. A markdown reader that opens a repo
# root must not spend a minute in `.git` or `node_modules` before it draws.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".cache", ".venv", "venv",
             "result", "target", ".mypy_cache", ".pytest_cache"}
MAX_INDEX = 2000        # files listed in the browse pane
MAX_SEARCH_BYTES = 4 << 20   # per file, for cross-document search
MAX_RESULT_FILES = 200

# Where reader looks when it is launched with no path and has never run.
FALLBACKS = ["~/nix/docs/DESIGN.md", "~/nix/AGENTS.md", "~/README.md"]


def is_doc(name):
    return os.path.splitext(name)[1].lower() in OPEN_EXTS


def natkey(name):
    """Natural sort: `10` after `2`, case-insensitively. docs/DESIGN.md §19.2 item 7
    records that no list on this desktop sorts numerically; a new one may as
    well start right."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def index_root(path):
    """The directory a document's siblings are looked for in: the nearest
    ancestor holding a `.git` (so opening one file in a repo browses the whole
    repo — which is the case this app was written for), else its own directory."""
    d = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    cur = d
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur or cur == str(Path.home()):
            return d
        cur = parent


# ---- the wallpaper palette (mirrors viewer/filer — see viewer/main.py) -------
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (identical to filer's and viewer's)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)   # dir watch catches atomic replaces
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge — reader's chrome (history, the two browse
    panes, search, the two split buttons) is drawn by the compositor in the
    titlebar's inner column, not in QML (docs/DESIGN.md §12, §7.4). The vtb callbacks
    fire on the client's I/O thread; the Signals hop them onto the GUI thread."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit)

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")   # spacer
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", ""))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Docs(QObject):
    """Loading, watching and opening documents.

    `load` is the whole seam between the parser and the view: QML never sees
    markdown source, only blocks. A file that cannot be read comes back
    `ok: false` with the reason, because "an app that cannot do its job says so
    instead of opening broken" (docs/DESIGN.md §10.2) — reader draws that reason.
    """

    #: a watched document changed on disk; the QML reloads it in place.
    fileChanged = Signal(str)          # key (which pane)

    def __init__(self, pdf=None, parent=None):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file)
        self._watched = {}             # key -> path
        self._pdf = pdf                # the PDF pipeline, by pane key

    # ---- reading ----

    @Slot(str, result="QVariantMap")
    @Slot(str, str, result="QVariantMap")
    def load(self, path, key="left"):
        """The one seam between a file and a pane, both modes.

        `kind` is what the pane branches on: `"md"` carries `blocks`, `"pdf"`
        carries `pageCount`/`pages` and is drawn by rasterizing pages instead
        (see `pdfdoc.py`). Everything else in the map — `ok`, `path`, `name`,
        `error`, `outline` — means the same thing in both, which is why the
        sidebar, the history, the footer and the persisted position needed no
        second version of themselves."""
        p = os.path.abspath(os.path.expanduser(path))
        if is_pdf(p) and self._pdf is not None:
            got = self._pdf.open(key, p)
            got["dir"] = os.path.dirname(p)
            got["blocks"] = []
            return got
        try:
            raw = open(p, "rb").read()
        except OSError as e:
            return {"ok": False, "kind": "md", "path": p, "name": os.path.basename(p),
                    "error": e.strerror or "cannot read", "blocks": [],
                    "outline": [], "dir": os.path.dirname(p)}
        text = raw.decode("utf-8", "replace")
        blocks = mdparse.parse(text, os.path.dirname(p))
        return {"ok": True, "kind": "md", "path": p, "name": os.path.basename(p),
                "error": "", "blocks": blocks, "outline": mdparse.outline(blocks),
                "dir": os.path.dirname(p), "lines": text.count("\n") + 1}

    @Slot(str, result=bool)
    def exists(self, path):
        p = os.path.abspath(os.path.expanduser(path or ""))
        return bool(p) and os.path.isfile(p)

    # ---- watching: a document edited underneath the reader reloads in place --
    # docs/DESIGN.md §6.1 — the maintenance mechanism must never be visible, so the
    # QML restores its scroll position around the reload rather than jumping to
    # the top. QFileSystemWatcher drops a path whose inode is replaced (every
    # editor that writes atomically), hence the re-add.

    @Slot(str, str)
    def watch(self, key, path):
        old = self._watched.get(key)
        if old and old not in [v for k, v in self._watched.items() if k != key]:
            self._watcher.removePath(old)
        self._watched[key] = path
        if path and os.path.isfile(path):
            self._watcher.addPath(path)

    def _on_file(self, path):
        if os.path.isfile(path) and path not in self._watcher.files():
            self._watcher.addPath(path)
        for key, p in self._watched.items():
            if p == path:
                self.fileChanged.emit(key)

    # ---- opening things that are not documents ----

    @Slot(str, result=bool)
    def openExternal(self, href):
        """A `url:` link, or a file this app does not render. Returns whether the
        launch STARTED — §10's rule that an action which cannot be reported on
        must not be offered, so the caller says so when this is false rather
        than silently doing nothing."""
        if not href:
            return False
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
            return QProcess.startDetached("xdg-open", [href])
        return QProcess.startDetached("xdg-open", [os.path.abspath(href)])

    @Slot(str, result=bool)
    def openFolder(self, path):
        d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        return QProcess.startDetached("filer", [d])

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)

    @Slot("QVariantList", result="QVariantList")
    def docPaths(self, urls):
        """The local markdown paths in a drop's URLs, in order.

        QUrl owns the decoding, in Python, exactly as in filer and viewer:
        `encodeURI`/`decodeURI` in QML leave `#` and `?` mangled, which was a
        real filer bug. A drop carrying nothing this app can render yields an
        empty list, and the pane declines it rather than doing nothing."""
        out, seen = [], set()
        for u in urls:
            p = (u if isinstance(u, QUrl) else QUrl(str(u))).toLocalFile()
            if not p:
                continue
            p = os.path.normpath(p)
            if p in seen or not os.path.isfile(p) or not is_doc(p):
                continue
            seen.add(p)
            out.append(p)
        return out


class Library(QObject):
    """The markdown files around the open document — the browse pane's model and
    the corpus cross-document search runs over."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = ""
        self._files = []

    @Slot(str, result="QVariantMap")
    def index(self, path):
        """{root, files: [{name, path, rel, dir}]} for the document at `path`.

        Sorted by relative path, naturally, so a repo's `docs/agents/*` land
        together under `docs/*` and `AGENTS.md` sorts where it reads. `rel` is
        what the pane DRAWS, so it is glyph-mapped; `path` is what gets opened,
        so it is not."""
        root = index_root(path or str(Path.home()))
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted((d for d in dirnames
                                  if d not in SKIP_DIRS and not d.startswith(".")),
                                 key=natkey)
            for fn in filenames:
                if not is_doc(fn):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                out.append({"name": fn, "path": full, "rel": rel,
                            "dir": os.path.relpath(dirpath, root)})
                if len(out) >= MAX_INDEX:
                    break
            if len(out) >= MAX_INDEX:
                break
        out.sort(key=lambda e: natkey(e["rel"]))
        self._root, self._files = root, out
        return {"root": root, "files": out, "count": len(out)}

    @Slot(str, str, result="QVariantList")
    def search(self, path, query):
        """Cross-document search: [{path, name, rel, hits, lines:[{n, text}]}].

        The query is matched against the file's own bytes (NOT a glyph-mapped
        copy), so it finds what is on disk; the snippet returned for display IS
        mapped, because it is drawn in the pixel font."""
        q = (query or "").strip()
        if len(q) < 2:
            return []
        if not self._files or index_root(path or "") != self._root:
            self.index(path)
        needle = q.lower()
        results = []
        for e in self._files:
            # A PDF is listed in the files pane and opened like anything else,
            # but it is not TEXT: matching a query against its bytes finds
            # nothing a reader would recognise and occasionally finds a hit
            # inside a compressed stream. Cross-document search is markdown's;
            # find WITHIN an open PDF is `Pdf.search` (pdfdoc.py) and works.
            if is_pdf(e["path"]):
                continue
            try:
                if os.path.getsize(e["path"]) > MAX_SEARCH_BYTES:
                    continue
                text = open(e["path"], "rb").read().decode("utf-8", "replace")
            except OSError:
                continue
            hits, snippets = 0, []
            for n, line in enumerate(text.split("\n"), 1):
                if needle in line.lower():
                    hits += 1
                    if len(snippets) < 8:
                        snippets.append({"n": n, "text": mdparse.px(line.strip()[:160])})
            if hits:
                results.append({"path": e["path"], "name": e["name"],
                                "rel": mdparse.px(e["rel"]), "hits": hits,
                                "lines": snippets})
            if len(results) >= MAX_RESULT_FILES:
                break
        # The document you are reading first, then most hits — the answer you
        # are most likely to want is the one you can already see.
        cur = os.path.abspath(path or "")
        results.sort(key=lambda r: (r["path"] != cur, -r["hits"], natkey(r["rel"])))
        return results


class Settings(QObject):
    """reader's own persisted UI state, `~/.local/state/reader/state.json`.

    docs/DESIGN.md §14: anything the user changes by USING the app goes here — both
    panes' documents, where they were scrolled to, the sidebar's mode and width,
    the split and its ratio. The transient things (a query being typed, the
    hovered row) deliberately stay in QML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self._data = d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, "QVariant")
    def set(self, key, val):
        self._data[key] = val
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass


def start_path(argv, settings):
    """The document to open: the argument, else the one left open last time,
    else the first fallback that exists. Anything that is a DIRECTORY opens its
    README (or its first document), so `reader ~/nix` is a sensible thing to
    type and so a directory dropped on the window works."""
    for a in argv:
        if a.startswith("-"):
            continue
        p = os.path.abspath(os.path.expanduser(a))
        if os.path.isdir(p):
            names = sorted((n for n in os.listdir(p) if is_doc(n)), key=natkey)
            pref = [n for n in names if n.lower().startswith("readme")]
            if pref or names:
                return os.path.join(p, (pref or names)[0])
            return ""
        if os.path.exists(p):
            return p
        return ""       # named a file that is not there: draw the honest error
    last = settings.value("path", "")
    if last and os.path.isfile(last):
        return last
    for f in FALLBACKS:
        p = os.path.expanduser(f)
        if os.path.isfile(p):
            return p
    return ""


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("reader")
    app.setDesktopFileName("reader")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    settings = Settings()
    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()
    titlebar = Titlebar()
    pdf = PdfLibrary()
    docs = Docs(pdf)
    library = Library()

    # `image://pdfpage/<key>/<gen>/<page>` — the whole PDF drawing path
    # (pdfdoc.py). Registered before Main.qml loads, or the first delegate's
    # source resolves to nothing.
    engine.addImageProvider("pdfpage", PageProvider(pdf))

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Docs", docs)
    ctx.setContextProperty("Pdf", pdf)
    ctx.setContextProperty("Library", library)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("startPath", start_path(sys.argv[1:], settings))

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    fixture = None
    if os.environ.get("READER_RESOURCE_FIXTURE") == "1":
        from resourcefixture import ResourceFixture
        from PySide6.QtCore import QMetaObject, Q_ARG
        win = engine.rootObjects()[0]
        normal_path = os.environ["READER_RESOURCE_NORMAL_PATH"]
        stress_path = os.environ["READER_RESOURCE_STRESS_PATH"]

        def _load(path):
            pane = win.property("pane")
            QMetaObject.invokeMethod(pane, "load", Q_ARG(str, path),
                                     Q_ARG(str, "start"))

        def normal():
            if bool(win.property("splitOn")):
                QMetaObject.invokeMethod(win, "setSplit",
                                         Q_ARG(bool, bool(win.property("splitVertical"))))
            _load(normal_path)

        def stress():
            _load(stress_path)
            if not bool(win.property("splitOn")):
                QMetaObject.invokeMethod(win, "setSplit", Q_ARG(bool, True))

        fixture = ResourceFixture(app, {"normal": normal, "stress": stress,
                                        "clear": normal}, settle_ms=600,
                                  parent=app)

    from winstate import WinState
    win_state = WinState(engine.rootObjects()[0], "reader")  # keep ref: geometry

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
