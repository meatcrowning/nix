#!/usr/bin/env python3
"""board — what needs you, what is moving, what landed.

The eighth vendored app. It is a GUI over ONE markdown file,
`~/nix/docs/board.md`, which already existed and is not replaced: agents read
and write it as text, it lives in the private `docs/` repo and syncs between
`top` and `book` every five minutes, and he can edit it by hand in any editor.
board parses it, draws it, and writes his answers back into the same lines.

WHY IT EXISTS, in his words:

    "i kind of want an easier way to parse through your 'this is for [me] to
     decide/do' stuff vs what's happened vs what's ongoing -- and i want to be
     able to easily choose between options or give you my own. but with it all
     right now in a terminal window chat log i feel that some stuff can get lost
     and i feel pressured to act quickly when really i dont need to."

**The emotional requirement is a design constraint, not flavour text.** Nothing
in this app counts down, badges, nags, ages an item, or draws anything in the
`warn`/`crit` ramp. There is no "N open" tally anywhere — a count is a debt.
Every decision draws its own *if unanswered* line, from the file, because that
sentence is what makes it safe to walk away. A question may sit here for a week.

The pieces, and where the rules come from:

  * `boardparse.py` — parse and TARGETED LINE EDITS. A write never
    re-serialises the document; it replaces the lines it names and returns the
    rest of the file unchanged, byte for byte. Its docstring is the store's
    format and the round-trip contract.
  * QML draws it: pixel font at the desktop's size through `DeskStyle`, the wal
    palette parsed and watched out of the panel's `Theme.qml`, motion from
    `qmlcommon/Motion.qml`, `Kinetic*` views, `VScroll`, and the chrome in the
    hyprvtb titlebar through `pylib/vtbclient.py`.

NEVER CLOBBER HIM (docs/DESIGN.md §10.2, and the reason this file has a digest
at all). Three defences, because the store is edited by agents and by a sync
timer while this window is open:

  1. The file is WATCHED and re-read in place; the QML keeps its scroll
     position, so a reload is invisible (§6.1).
  2. A write re-reads the file first and REFUSES if it changed since the parse
     it was computed from — reloading and saying so, rather than writing a stale
     line number over somebody else's paragraph.
  3. Unsaved free text is never discarded: a draft answer is persisted to
     `~/.local/state/board/state.json` on a settle timer and survives a reload,
     a relaunch and a crash. An external edit to that item's answer is reported;
     the draft stays until he commits or cancels it himself.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import (QObject, Slot, Signal, Property, QUrl,
                            QFileSystemWatcher, QProcess, QTimer)
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (the desktop-wide font setting)

import boardparse  # noqa: E402  (beside this file)

STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "board" / "state.json"

# ---- the wallpaper palette (identical to reader's, viewer's and filer's) -----
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
    sync via a filesystem watch (identical to reader's and filer's)."""

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
    """hyprvtb app-button bridge — board's chrome (the three section jumps and
    `md`) is drawn by the compositor in the titlebar's inner column, not in QML
    (docs/DESIGN.md §12, §7.4). The vtb callbacks fire on the client's I/O
    thread; the Signal hops them onto the GUI thread."""

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


class Board(QObject):
    """The store, live: parse, watch, and write his answers back.

    `doc` is the whole parsed file as one QVariantMap — small enough (a few
    dozen items) that handing QML a fresh one per load is cheaper than any
    incremental model, and it makes the reload path a single assignment rather
    than a diff nobody can test.
    """

    docChanged = Signal()
    #: the file changed underneath us and has been re-read. QML restores its
    #: scroll position around this, so a sync or an agent's edit is invisible.
    reloaded = Signal()
    #: something worth saying in the titlebar footer. Never an exception dialog:
    #: §10's rule is that a failure is REPORTED, not swallowed and not fatal.
    status = Signal(str)

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self._path = os.path.abspath(os.path.expanduser(path or boardparse.BOARD_PATH))
        self._doc = {}
        self._err = ""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)      # an atomic save replaces the inode
        # A write lands as several inotify events; coalesce them, and let our
        # OWN write settle before re-reading it.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self._reload)
        self._load()

    # ---- reading ----

    def _rewatch(self):
        if os.path.isfile(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _path):
        self._rewatch()
        self._settle.start()

    def _load(self):
        self._rewatch()
        try:
            src = boardparse.read(self._path)
        except OSError as e:
            self._err = e.strerror or "cannot read"
            self._doc = {"needs": [], "todo": [], "flight": [], "landed": [],
                         "intro": {}, "lines": [], "digest": ""}
            self.docChanged.emit()
            return False
        self._err = ""
        self._doc = boardparse.parse(src)
        self.docChanged.emit()
        return True

    def _reload(self):
        before = self._doc.get("digest")
        if self._load() and self._doc.get("digest") != before:
            self.reloaded.emit()

    @Property("QVariantMap", notify=docChanged)
    def doc(self):
        # `lines` is the raw file and has no business crossing into QML: it
        # would be copied per binding evaluation and it is not drawable.
        return {k: v for k, v in self._doc.items() if k != "lines"}

    @Property(str, constant=True)
    def path(self):
        return self._path

    @Property(str, notify=docChanged)
    def error(self):
        return self._err

    # ---- writing ----

    def _item(self, key):
        for it in self._doc.get("needs", []):
            if it["key"] == key:
                return it
        return None

    def _commit(self, lines):
        """Write `lines`, but only if the file on disk is still the one they
        were computed from. A stale line index would land his answer in the
        middle of someone else's paragraph — the one failure this app must never
        have — so a race REFUSES, reloads and says so."""
        try:
            src = boardparse.read(self._path)
        except OSError as e:
            self.status.emit("cannot read board.md - " + (e.strerror or "?"))
            return False
        if boardparse.digest(src) != self._doc.get("digest"):
            self._load()
            self.reloaded.emit()
            self.status.emit("board.md changed on disk - reloaded, nothing written")
            return False
        try:
            boardparse.write(self._path, "".join(lines))
        except OSError as e:
            self.status.emit("could not write board.md - " + (e.strerror or "?"))
            return False
        self._load()
        return True

    @Slot(str, int, bool, result=bool)
    def choose(self, key, index, checked):
        """Tick an option, or untick it. The options of one decision are
        alternatives, so this is a radio: `boardparse.toggle_option` clears the
        others and clicking the chosen one clears it."""
        it = self._item(key)
        if it is None or index < 0 or index >= len(it["options"]):
            self.status.emit("that option is no longer there - reloaded")
            self._load()
            return False
        ok = self._commit(boardparse.toggle_option(self._doc["lines"], it, index, checked))
        if ok:
            self.status.emit("saved")
        return ok

    @Slot(str, str, result=bool)
    def answer(self, key, text):
        """His own words, into the item's `>` line. Free text always beats the
        options, so this never clears them — the file shows both, and the next
        agent to read it reads the sentence first."""
        it = self._item(key)
        if it is None:
            self.status.emit("that item is no longer there - reloaded")
            self._load()
            return False
        if it["answerFrom"] < 0:
            # §10: never offer an action that cannot work. The QML hides the
            # editor in this case; this is the belt to that pair of braces.
            self.status.emit("this item has no answer line to write to")
            return False
        ok = self._commit(boardparse.set_answer(self._doc["lines"], it, text))
        if ok:
            self.status.emit("saved" if text.strip() else "answer cleared")
        return ok

    @Slot(str, result=str)
    def answerOf(self, key):
        it = self._item(key)
        return it["answer"] if it else ""

    # ---- things that are not this file ----

    @Slot(result=bool)
    def openInReader(self):
        return QProcess.startDetached("reader", [self._path])

    @Slot(result=bool)
    def openFolder(self):
        return QProcess.startDetached("filer", [os.path.dirname(self._path)])

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)


class Settings(QObject):
    """board's own persisted UI state, `~/.local/state/board/state.json`.

    docs/DESIGN.md §14: anything he changes by USING the app goes here — which
    sections are collapsed, and (the important one) **any answer he has typed
    and not yet committed**. A draft is his words; losing it to a crash or a
    stray Escape would be exactly the "some stuff can get lost" this app exists
    to end.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self._data = d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            self._data = {}

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, "QVariant")
    def set(self, key, val):
        # A QML `var` object arrives as a QJSValue, which json cannot serialise
        # — and the failure is a traceback at write time, i.e. his drafts
        # silently never persisting. Unwrap at the boundary.
        if hasattr(val, "toVariant"):
            val = val.toVariant()
        self._data[key] = val
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("board")
    app.setDesktopFileName("board")

    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    settings = Settings()
    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    board = Board(args[0] if args else None)

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Board", board)
    ctx.setContextProperty("Settings", settings)

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
