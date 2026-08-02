#!/usr/bin/env python3
"""editor — the desktop's text editor, with Kate's core editing.

The ninth vendored app. Everything it draws is taken from `~/nix/docs/DESIGN.md`
rather than chosen here: pixel font at the desktop's own size through
`DeskStyle`, wal palette parsed and watched out of the panel's `Theme.qml`,
motion from `qmlcommon/Motion.qml`, `Kinetic*` views and the one `VScroll`,
square corners, and its whole chrome — including the open documents, which are
buttons in the inner column exactly like surfer's tabs — in the hyprvtb titlebar
through `pylib/vtbclient.py`.

The split of work is the interesting part, and it is deliberate:

  * **QML owns the VIEW and the CURSOR.** One `TextEdit` per open document
    (`CodeView.qml`), so each gets Qt's own undo stack, its own selection and
    its own caret for free, and switching documents is showing a different item
    rather than swapping text into one.
  * **Python owns the DOCUMENT.** `Buffers` holds each view's `QTextDocument`
    (reached through the `QQuickTextDocument` the `TextEdit` exposes) and does
    every multi-line edit on it with a `QTextCursor` inside
    `beginEditBlock()`/`endEditBlock()`, which is the only way an indent or a
    replace-all is ONE undo step. The algorithms are in `textops.py`; nothing
    there knows a view exists, so all of it tests offscreen.
  * **Python owns the COLOUR.** `highlight.py` is a `QSyntaxHighlighter` per
    document, painting both syntax and the find bar's all-matches highlight in
    one pass, with every token class resolved to a named slot of the LIVE wal
    palette (docs/DESIGN.md §3.1 — nothing here picks a colour).

State (`~/.local/state/editor/state.json`) is the app's own, per §14: which
files were open and where the caret was in each, the indent settings, the line
numbers / whitespace toggles. Nothing here writes another app's file.

Deliberately NOT here, and not to be started without him asking: LSP or
completion, split views, an embedded terminal, a project sidebar, sessions, a
plugin system, vi mode. See `AGENTS.md` in this directory.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import (QFileSystemWatcher, QObject, Property, Signal, Slot,
                            QUrl)
from PySide6.QtGui import QGuiApplication, QColor, QTextCursor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickTextDocument

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (the desktop-wide font setting)
from spellcheck import SpellCheck  # noqa: E402  (as-you-type spelling)

import textops  # noqa: E402  (beside this file)
from highlight import LANGS, Highlighter, detect  # noqa: E402

STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "editor" / "state.json"

#: A file this editor refuses to open, because opening it would be worse than
#: saying no: past this size the highlighter's per-block pass and Qt's own text
#: layout stop being interactive, and a text editor that hangs on a click is not
#: a text editor. docs/DESIGN.md §10.2 — refuse visibly, never no-op.
MAX_OPEN_BYTES = 16 << 20

#: Directories never walked by the open prompt's completion.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".cache", "result"}


# ---- the wallpaper palette (mirrors reader/filer/viewer — see reader/main.py) -
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
    sync via a filesystem watch (identical to reader's, filer's and viewer's).

    `color()` is the one addition: the syntax highlighter is Python, not QML, so
    it cannot bind — it asks by slot NAME and re-asks on `changed`."""

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

    def color(self, slot):
        """The raw string for a slot — what the highlighter asks for."""
        return self._colors.get(slot, PALETTE_DEFAULTS.get(slot, "#cc4400"))

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
    """hyprvtb app-button bridge — editor's whole chrome (the open documents, new
    / open / save, find, replace, go-to-line, the view toggles) is drawn by the
    compositor in the titlebar's inner column, not in QML (docs/DESIGN.md §12,
    §7.4). The vtb callbacks fire on the client's I/O thread; the Signals hop
    them onto the GUI thread.

    `reordered` is here for the same reason it is in surfer: the documents are
    draggable buttons, so their order is the user's."""

    clicked = Signal(str)
    reordered = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit,
                                 on_reorder=lambda s, d: self.reordered.emit(s, d))

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")   # spacer
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), bool(b.get("drag", False)),
                            bool(b.get("bottom", False))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Files(QObject):
    """The filesystem: reading, writing, and the open prompt's completion.

    Reading and writing are deliberately one place, because the two halves have
    to agree about three things a naive editor silently destroys — the encoding,
    the line endings and whether the file ended in a newline. Each is DETECTED
    on read, carried on the buffer, and reproduced on write."""

    @Slot(str, result="QVariantMap")
    def read(self, path):
        p = os.path.abspath(os.path.expanduser(path or ""))
        if not p:
            return {"ok": False, "error": "no path"}
        if os.path.isdir(p):
            return {"ok": False, "path": p, "error": "that is a directory"}
        if not os.path.exists(p):
            # A path that is not there yet is a NEW file, not an error: `editor
            # newfile.py` has to work, and Kate opens it empty.
            return {"ok": True, "path": p, "text": "", "isnew": True,
                    "eol": "\n", "encoding": "utf-8", "final": True,
                    "error": "", "mtime": 0.0}
        try:
            size = os.path.getsize(p)
            if size > MAX_OPEN_BYTES:
                return {"ok": False, "path": p,
                        "error": "too big to edit (%d MB)" % (size >> 20)}
            raw = open(p, "rb").read()
        except OSError as e:
            return {"ok": False, "path": p, "error": e.strerror or "cannot read"}
        if b"\x00" in raw[:8192]:
            return {"ok": False, "path": p, "error": "binary file"}
        try:
            text = raw.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            # latin-1 always decodes and always round-trips byte-for-byte, so a
            # file this editor cannot identify is still SAFE to save — which
            # `utf-8, errors="replace"` is not: that silently turns every byte it
            # did not understand into U+FFFD and writes the damage back.
            text = raw.decode("latin-1")
            enc = "latin-1"
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol == "\r\n":
            text = text.replace("\r\n", "\n")
        final = text.endswith("\n")
        return {"ok": True, "path": p, "text": text, "isnew": False,
                "eol": eol, "encoding": enc, "final": final, "error": "",
                "mtime": os.path.getmtime(p)}

    @Slot(str, str, str, str, bool, result="QVariantMap")
    def write(self, path, text, eol="\n", encoding="utf-8", final=True):
        """Write, atomically-ish: a temp file beside the target, then a rename.

        The rename is what makes a crash mid-save cost nothing, and it is also
        why every watcher of this file has to re-add the path afterwards (the
        inode changed) — `Buffers._on_disk` does."""
        p = os.path.abspath(os.path.expanduser(path or ""))
        if not p:
            return {"ok": False, "error": "no path"}
        body = text
        if final and not body.endswith("\n"):
            body += "\n"
        if eol == "\r\n":
            body = body.replace("\n", "\r\n")
        tmp = p + ".editor-tmp"
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(body.encode(encoding, "surrogateescape"))
                f.flush()
                os.fsync(f.fileno())
            # keep the existing mode: a rename would otherwise make an
            # executable script non-executable, silently
            if os.path.exists(p):
                os.chmod(tmp, os.stat(p).st_mode & 0o7777)
            os.replace(tmp, p)
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return {"ok": False, "error": e.strerror or "cannot write"}
        return {"ok": True, "path": p, "mtime": os.path.getmtime(p)}

    @Slot(str, result="QVariantList")
    def complete(self, prefix):
        """Path completion for the open/save-as prompt: the entries in the
        directory the prefix names, filtered by its tail. Directories first and
        marked with a trailing `/`, so one list answers both halves.

        This exists instead of a Qt `FileDialog` because a stock dialog is the
        one thing on this desktop that would look like nothing else on it
        (docs/DESIGN.md §7.2, "menus are ours")."""
        raw = os.path.expanduser(prefix or "")
        if not raw:
            raw = str(Path.home()) + "/"
        d, tail = (raw, "") if raw.endswith("/") else os.path.split(raw)
        d = d or "."
        try:
            names = os.listdir(d)
        except OSError:
            return []
        low = tail.lower()
        out = []
        for n in names:
            if low and not n.lower().startswith(low):
                continue
            if not low and n.startswith("."):
                continue          # a bare directory listing hides dotfiles
            full = os.path.join(d, n)
            isdir = os.path.isdir(full)
            out.append({"name": n + ("/" if isdir else ""), "path": full,
                        "dir": isdir})
        out.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return out[:400]

    @Slot(str, result=bool)
    def exists(self, path):
        p = os.path.abspath(os.path.expanduser(path or ""))
        return bool(p) and os.path.exists(p)

    @Slot(str)
    def copy(self, text):
        """One clipboard channel, in Python, like reader's `Docs.copy` — the QML
        side has no `Clipboard` type and every app here does it this way."""
        QGuiApplication.clipboard().setText(text)

    @Slot("QVariantList", result="QVariantList")
    def localPaths(self, urls):
        """The local file paths in a drop's URLs, in order. QUrl owns the
        decoding, in Python, exactly as in filer, viewer and reader:
        `encodeURI`/`decodeURI` in QML leave `#` and `?` mangled."""
        out, seen = [], set()
        for u in urls:
            p = (u if isinstance(u, QUrl) else QUrl(str(u))).toLocalFile()
            if not p:
                continue
            p = os.path.normpath(p)
            if p in seen or os.path.isdir(p):
                continue
            seen.add(p)
            out.append(p)
        return out


class Buffers(QObject):
    """Every open document's `QTextDocument`, its highlighter and its watch.

    Keyed by the `tid` QML allocates for a tab, so the two halves never have to
    agree about ordering — QML may reorder or close tabs freely and the key
    stays valid.

    **A `QQuickTextDocument` reference is kept, never the `QTextDocument`.** The
    `TextEdit` owns the inner document, and holding a Python wrapper for it
    outlives nothing safely: measured here, the wrapper reports "Internal C++
    object already deleted" while the document itself is perfectly alive. So
    `_doc()` re-asks the `QQuickTextDocument` every time. That is one virtual
    call, and it is the difference between this working and this crashing.
    """

    #: the document's modified flag flipped — the tab's `*` and the save cell
    dirtyChanged = Signal(int, bool)
    #: the file changed on disk while we had it open (`Buffers.conflict()` says
    #: whether the buffer had unsaved edits, which decides reload vs ask)
    diskChanged = Signal(int)
    #: something worth putting in the footer happened, e.g. a refused action
    reported = Signal(str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._bufs = {}                 # tid -> dict
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_disk)
        palette.changed.connect(self._recolour)

    # ---- lifecycle -------------------------------------------------------

    @Slot(int, QQuickTextDocument, str, str)
    def attach(self, tid, qtd, path, lang=""):
        """Bind a freshly-created `CodeView`'s document to this tid.

        Called from `Component.onCompleted` AFTER the view's text has been set,
        so the highlighter's first pass sees the real content and the undo stack
        is cleared over it — an editor whose first Ctrl+Z empties the file is a
        classic, and it is what `clearUndoRedoStacks` prevents."""
        doc = qtd.textDocument()
        key = lang if lang in LANGS else detect(path, doc.firstBlock().text())
        hl = Highlighter(doc, self._palette, key)
        doc.setModified(False)
        doc.clearUndoRedoStacks()
        # A document with no undo limit grows without bound on a long session.
        doc.setMaximumBlockCount(0)
        doc.setUndoRedoEnabled(True)
        buf = {"qtd": qtd, "hl": hl, "path": path, "lang": key,
               "eol": "\n", "encoding": "utf-8", "final": True, "mtime": 0.0}
        self._bufs[tid] = buf
        doc.modificationChanged.connect(
            lambda on, t=tid: self.dirtyChanged.emit(t, bool(on)))
        self._watch(tid, path)

    @Slot(int)
    def detach(self, tid):
        buf = self._bufs.pop(tid, None)
        if buf is None:
            return
        self._rewatch_all()

    @Slot(int, str, str, float, str, bool)
    def setMeta(self, tid, eol, encoding, mtime, path, final):
        """The encoding/EOL/final-newline facts `Files.read` detected, carried
        onto the buffer so the eventual write reproduces them."""
        buf = self._bufs.get(tid)
        if buf is None:
            return
        buf.update({"eol": eol or "\n", "encoding": encoding or "utf-8",
                    "mtime": float(mtime), "final": bool(final)})
        if path and path != buf["path"]:
            buf["path"] = path
            self._watch(tid, path)

    def _doc(self, tid):
        buf = self._bufs.get(tid)
        if buf is None:
            return None
        try:
            return buf["qtd"].textDocument()
        except RuntimeError:
            return None

    # ---- language --------------------------------------------------------

    @Slot(int, result=str)
    def language(self, tid):
        buf = self._bufs.get(tid)
        return buf["lang"] if buf else "text"

    @Slot(int, str)
    def setLanguage(self, tid, lang):
        buf = self._bufs.get(tid)
        if buf is None or lang not in LANGS:
            return
        buf["lang"] = lang
        buf["hl"].set_language(lang)

    @Slot(result="QVariantList")
    def languages(self):
        return [{"key": k, "name": v["name"], "indent": v["indent"],
                 "tabs": v["tabs"]}
                for k, v in sorted(LANGS.items(), key=lambda kv: kv[1]["name"])]

    @Slot(str, str, result=str)
    def detectLanguage(self, path, firstLine):
        return detect(path, firstLine)

    def _recolour(self):
        for buf in self._bufs.values():
            buf["hl"].refresh()

    # ---- the disk watch: reload in place ---------------------------------

    def _watch(self, tid, path):
        buf = self._bufs.get(tid)
        if buf is None:
            return
        buf["path"] = path
        self._rewatch_all()

    def _rewatch_all(self):
        want = {b["path"] for b in self._bufs.values()
                if b["path"] and os.path.isfile(b["path"])}
        have = set(self._watcher.files())
        for gone in have - want:
            self._watcher.removePath(gone)
        for new in want - have:
            self._watcher.addPath(new)

    def _on_disk(self, path):
        # Every editor on this machine (this one included) writes atomically, so
        # the watched inode is REPLACED and QFileSystemWatcher drops the path.
        # Re-adding is what makes the second external change fire at all.
        if os.path.isfile(path) and path not in self._watcher.files():
            self._watcher.addPath(path)
        for tid, buf in self._bufs.items():
            if buf["path"] != path:
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            if mtime and abs(mtime - buf["mtime"]) < 1e-6:
                continue          # our own save
            buf["mtime"] = mtime
            self.diskChanged.emit(tid)

    @Slot(int, result=bool)
    def dirty(self, tid):
        doc = self._doc(tid)
        return bool(doc and doc.isModified())

    # ---- saving ----------------------------------------------------------

    @Slot(int, result=str)
    def text(self, tid):
        doc = self._doc(tid)
        return doc.toPlainText() if doc else ""

    @Slot(int, result="QVariantMap")
    def meta(self, tid):
        buf = self._bufs.get(tid)
        if buf is None:
            return {}
        return {"path": buf["path"], "eol": buf["eol"],
                "encoding": buf["encoding"], "final": buf["final"],
                "lang": buf["lang"]}

    @Slot(int, float)
    def markSaved(self, tid, mtime):
        buf = self._bufs.get(tid)
        doc = self._doc(tid)
        if buf is None or doc is None:
            return
        buf["mtime"] = float(mtime)
        doc.setModified(False)
        self._rewatch_all()

    @Slot(int, str)
    def replaceAllText(self, tid, text):
        """Swap a buffer's whole content — the reload-from-disk path, and the
        only place that is legitimate. One edit block, so a reload is one Ctrl+Z
        away; the caller restores the caret, because §6.1 says a reload must not
        move the user."""
        doc = self._doc(tid)
        if doc is None:
            return
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(text)
        cur.endEditBlock()

    # ---- geometry the gutter needs ---------------------------------------

    @Slot(int, result=int)
    def lineCount(self, tid):
        doc = self._doc(tid)
        return doc.blockCount() if doc else 0

    @Slot(int, int, result="QVariantMap")
    def lineCol(self, tid, pos):
        """1-based line and column for a character position — the footer's
        `12:34`. `findBlock` is a tree walk, not a scan of the text, so this is
        cheap enough to call on every cursor move; counting newlines in QML is
        not (it was, briefly, and a 3000-line file felt it)."""
        doc = self._doc(tid)
        if doc is None:
            return {"line": 1, "col": 1, "blockPos": 0}
        blk = doc.findBlock(max(0, min(pos, doc.characterCount() - 1)))
        return {"line": blk.blockNumber() + 1,
                "col": pos - blk.position() + 1,
                "blockPos": blk.position()}

    @Slot(int, int, result=int)
    def lineStart(self, tid, line):
        """The character position of a 1-based line — go-to-line's whole job."""
        doc = self._doc(tid)
        if doc is None:
            return 0
        blk = doc.findBlockByNumber(max(0, int(line) - 1))
        return blk.position() if blk.isValid() else 0

    @Slot(int, float, float, result="QVariantList")
    def gutter(self, tid, y0, y1):
        """The line numbers visible in content rows `y0..y1`, each with the y and
        height its DOCUMENT line actually occupies: `[{n, y, h}]`.

        Asked of the document's own layout rather than computed as `n * lineH`,
        because with wrap on a document line is several visual rows tall and an
        arithmetic gutter silently drifts a line per wrapped paragraph. With wrap
        off every block is the same height and the walk starts at the right block
        immediately, so the uniform case costs nothing extra."""
        doc = self._doc(tid)
        if doc is None:
            return []
        layout = doc.documentLayout()
        blk = doc.firstBlock()
        # Fast start for the uniform (no-wrap) case: jump straight to the first
        # block that can be visible instead of walking from line 1.
        if blk.isValid():
            h = layout.blockBoundingRect(blk).height()
            if h > 0:
                guess = int(max(0, y0) // h)
                if guess:
                    cand = doc.findBlockByNumber(min(guess, doc.blockCount() - 1))
                    if cand.isValid() and layout.blockBoundingRect(cand).y() <= y0:
                        blk = cand
        out = []
        while blk.isValid():
            r = layout.blockBoundingRect(blk)
            if r.y() + r.height() < y0:
                blk = blk.next()
                continue
            if r.y() > y1:
                break
            out.append({"n": blk.blockNumber() + 1, "y": r.y(), "h": r.height()})
            if len(out) > 4000:        # a pathological wrap; the view is 60 rows
                break
            blk = blk.next()
        return out

    @Slot(int, int, result="QVariantMap")
    def blockRect(self, tid, pos):
        """Where the line holding `pos` is, in content coordinates — the
        current-line highlight's geometry, and the only honest source for it
        once wrapping is on."""
        doc = self._doc(tid)
        if doc is None:
            return {"y": 0.0, "h": 0.0}
        blk = doc.findBlock(max(0, min(pos, doc.characterCount() - 1)))
        r = doc.documentLayout().blockBoundingRect(blk)
        return {"y": r.y(), "h": r.height()}

    # ---- the editing commands (textops does the work) --------------------

    def _op(self, tid, fn, *a, **kw):
        doc = self._doc(tid)
        if doc is None:
            return {"ok": False, "start": 0, "end": 0}
        res = fn(doc, *a, **kw)
        if res is None:
            return {"ok": False, "start": 0, "end": 0}
        return {"ok": True, "start": int(res[0]), "end": int(res[1])}

    @Slot(int, int, int, bool, int, result="QVariantMap")
    def indent(self, tid, s, e, useTabs, width):
        return self._op(tid, textops.indent, s, e, useTabs, width)

    @Slot(int, int, int, bool, int, result="QVariantMap")
    def unindent(self, tid, s, e, useTabs, width):
        return self._op(tid, textops.unindent, s, e, useTabs, width)

    @Slot(int, int, int, result="QVariantMap")
    def toggleComment(self, tid, s, e):
        buf = self._bufs.get(tid)
        lang = buf["lang"] if buf else "text"
        out = self._op(tid, textops.toggle_comment, s, e, lang)
        if not out["ok"]:
            self.reported.emit("no comment syntax for " + LANGS[lang]["name"])
        return out

    @Slot(int, int, int, result="QVariantMap")
    def duplicateLines(self, tid, s, e):
        return self._op(tid, textops.duplicate_lines, s, e)

    @Slot(int, int, int, result="QVariantMap")
    def deleteLines(self, tid, s, e):
        return self._op(tid, textops.delete_lines, s, e)

    @Slot(int, int, int, int, result="QVariantMap")
    def moveLines(self, tid, s, e, delta):
        return self._op(tid, textops.move_lines, s, e, delta)

    @Slot(int, int, bool, int, result="QVariantMap")
    def newline(self, tid, pos, useTabs, width):
        buf = self._bufs.get(tid)
        lang = buf["lang"] if buf else "text"
        return self._op(tid, textops.newline, pos, useTabs, width, lang)

    @Slot(int, int, bool, int, result="QVariantMap")
    def backspaceIndent(self, tid, pos, useTabs, width):
        return self._op(tid, textops.backspace_indent, pos, useTabs, width)

    # ---- find and replace ------------------------------------------------

    @Slot(int, str, bool, bool, result=bool)
    def setQuery(self, tid, query, regex, case):
        """Light every match in the buffer, through the highlighter's own pass.

        Returns whether the pattern is USABLE, so the bar can say `bad regex`
        rather than `no matches` — those are different answers and conflating
        them is exactly the silent failure §10.2 forbids."""
        buf = self._bufs.get(tid)
        if buf is None:
            return False
        buf["hl"].set_query(query, regex, case)
        if not query or not regex:
            return True
        try:
            re.compile(query)
            return True
        except re.error:
            return False

    @Slot(int, str, int, bool, bool, bool, bool, result="QVariantMap")
    def find(self, tid, query, fromPos, backward, regex, case, whole):
        doc = self._doc(tid)
        if doc is None:
            return {"ok": False}
        hit = textops.find(doc, query, fromPos, backward, regex, case, whole)
        if hit is None:
            return {"ok": False}
        return {"ok": True, "start": hit[0], "end": hit[1]}

    @Slot(int, str, bool, bool, bool, result="QVariantList")
    def matches(self, tid, query, regex, case, whole):
        doc = self._doc(tid)
        if doc is None:
            return []
        return [{"start": s, "end": e}
                for s, e in textops.match_count(doc, query, regex, case, whole)]

    @Slot(int, int, int, str, result="QVariantMap")
    def replaceOne(self, tid, s, e, text):
        return self._op(tid, textops.replace_one, s, e, text)

    @Slot(int, str, str, bool, bool, bool, result=int)
    def replaceAll(self, tid, query, text, regex, case, whole):
        doc = self._doc(tid)
        if doc is None:
            return 0
        return textops.replace_all(doc, query, text, regex, case, whole)

    # ---- indentation facts QML asks about --------------------------------

    @Slot(int, result="QVariantMap")
    def guessIndent(self, tid):
        """What this file already uses, so opening it does not fight it.

        Kate does this and it matters here specifically: this repo is nix at two
        spaces, python at four, lua at two and C++ at four, and an editor that
        applies one global setting to all of them corrupts the shape of whatever
        it touches. Only the FILE is consulted — the first 200 indented lines —
        with the language's own default as the tie-break; it is a guess, it is
        shown in the footer, and the user can override it."""
        doc = self._doc(tid)
        buf = self._bufs.get(tid)
        lang = buf["lang"] if buf else "text"
        default = {"tabs": LANGS[lang]["tabs"], "width": LANGS[lang]["indent"],
                   "guessed": False}
        if doc is None:
            return default
        tabs, widths, seen = 0, {}, 0
        blk = doc.firstBlock()
        while blk.isValid() and seen < 200:
            t = blk.text()
            lead = len(t) - len(t.lstrip())
            if lead and t.strip():
                seen += 1
                if t[0] == "\t":
                    tabs += 1
                else:
                    widths[lead] = widths.get(lead, 0) + 1
            blk = blk.next()
        if not seen:
            return default
        if tabs > seen / 2:
            return {"tabs": True, "width": LANGS[lang]["indent"], "guessed": True}
        # The indent width is the greatest common divisor of the leading widths
        # that actually occur — 2 for nix, 4 for python — which is robust against
        # continuation lines a modal count is not.
        from math import gcd
        g = 0
        for w, n in widths.items():
            if n >= 2:
                g = gcd(g, w)
        if g in (2, 3, 4, 8):
            return {"tabs": False, "width": g, "guessed": True}
        return default


class Settings(QObject):
    """editor's own persisted UI state, `~/.local/state/editor/state.json`.

    docs/DESIGN.md §14: anything the user changes by USING the app goes here —
    the open files and the caret in each, the indent settings, and the line
    numbers / whitespace toggles. What is being typed into the find bar
    right now deliberately stays in QML."""

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
        # A JS array or object arrives as a QJSValue, which `json.dumps` cannot
        # serialize — and the TypeError propagates back out through the QML call
        # that made it, ABORTING whatever QML was in the middle of. That is not a
        # hypothetical: storing the list of open files this way silently stopped
        # `Component.onCompleted` after the first file, so editor opened one
        # document out of two with no error anywhere.
        if hasattr(val, "toVariant"):
            val = val.toVariant()
        self._data[key] = val
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            # A value that will not serialize must never take the caller down
            # with it; the setting is simply not persisted.
            pass


def start_paths(argv, settings):
    """The files to open: every non-flag argument, else the ones left open last
    time, else nothing (an empty untitled buffer, like every editor).

    `+N` as an argument is honoured — `editor +42 file.py` is the convention
    every editor on a unix box shares, and it is what `git`, `less` and a
    compiler error message hand you."""
    paths, line = [], 0
    for a in argv:
        if re.fullmatch(r"\+\d+", a):
            line = int(a[1:])
            continue
        if a.startswith("-"):
            continue
        paths.append(os.path.abspath(os.path.expanduser(a)))
    if paths:
        return {"paths": paths, "line": line, "restored": False}
    last = settings.value("open", [])
    if isinstance(last, list):
        keep = [str(p) for p in last if p and os.path.isfile(str(p))]
        if keep:
            return {"paths": keep, "line": 0, "restored": True}
    return {"paths": [], "line": 0, "restored": False}


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("editor")
    app.setDesktopFileName("editor")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    settings = Settings()
    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    files = Files()
    buffers = Buffers(palette)
    # The spelling marks under prose (`qmlcommon/SpellMarks.qml`). Like
    # DeskStyle, it must be a context property the whole tree can see, and the
    # Python reference must outlive this function.
    spell = SpellCheck()

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Files", files)
    ctx.setContextProperty("Buffers", buffers)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Spell", spell)
    ctx.setContextProperty("startArgs", start_paths(sys.argv[1:], settings))

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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
