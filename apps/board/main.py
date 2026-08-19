#!/usr/bin/env python3
"""board — what needs you, what is moving, what landed.

The eighth vendored app. It is a GUI over ONE markdown file,
`~/nix/docs/board.<hostname>.md`, which already existed and is not replaced:
agents read and write it as text, it lives in the private `docs/` repo, and he
can edit it by hand in any editor. board parses it, draws it, and writes his
answers back into the same lines.

ONE BOARD PER MACHINE since 2026-07-30 — `board.top.md` and `board.book.md`.
Both files sync, so each machine keeps a copy of the other's, but every reader
and writer on a host touches only its own and nothing merges them: an overnight
agent on `top` must not overwrite what he types on `book`. The path comes from
`boardparse.board_path()` / `ensure_board()`, never from a literal.

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
  * `boardagents.py` — the one section of this window that is NOT the store:
    who is working right now (the stashes `boardmove` already keeps, `/proc`,
    and one systemctl query) and the box he types into to reach them. An
    agent's stdin is closed, so a message is a FILE that is never in two places
    and never in none; its docstring is the authority on what the box can and
    cannot honestly promise.
  * `boardwork.py` — the fan-out. The box at the TOP of this window is his
    control surface: he types a sentence, it lands in the same inbox, and
    board-watch spawns an ORCHESTRATOR that splits it into worker agents or
    asks him a question. This module owns the dispatch, the concurrency cap and
    what happens to work above it, and the order the cards are drawn in — one
    flat list, oldest first, so a card never moves once it is on screen.
  * `boardphase.py` — what an agent SAYS it is doing and what it is OBSERVED
    doing, kept apart on purpose (*"i want both"*). The claim is the agent's own
    words; the observation is derived from the tool calls in its live
    transcript and cannot be faked. The card's second sentence is the OBSERVED
    one, always, and a disagreement between the two is drawn rather than
    resolved.
  * `boardusage.py` — the two bars under the model chooser: how much of the
    5-hour and the 7-day limit is gone. Read from Claude Code's own cached
    `/usage` figures, never derived from tokens against a guessed ceiling, and
    never broken out per model — its docstring says why on all three counts.
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
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QObject, Slot, Signal, Property, QUrl, Qt,
                            QByteArray, QFileSystemWatcher, QProcess, QTimer)
from PySide6.QtGui import QGuiApplication, QColor, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (the desktop-wide font setting)
from kdetheme import theme_source  # noqa: E402  (pylib; the KDE global theme in a Plasma session)
from glyphs import px  # noqa: E402  (§2.3 — map at INGEST, like boardparse does)

import boardparse  # noqa: E402  (beside this file)
import boardmove  # noqa: E402  (beside this file)
import boardagents  # noqa: E402  (beside this file)
import boardwork  # noqa: E402  (beside this file)
import boardusage  # noqa: E402  (beside this file)
import boardspend  # noqa: E402  (beside this file — the spend section's data layer)
import boardundo  # noqa: E402  (beside this file)
import boardphase  # noqa: E402  (beside this file — the card drawer tails its transcript)

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


#: Where a report goes now that the titlebar cannot carry one. Appended to, one
#: stamped line per message, and never rotated by the app — it is a handful of
#: lines a day. `$XDG_CACHE_HOME` so it is machine-local on both `top` and
#: `book` and nothing syncs it.
STATUS_LOG = (Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
              / "goetia-status.log")


def _record_status(text):
    """A report goes to the log and to stderr — never to the titlebar.

    §10 says a failure is REPORTED, not swallowed, so the choke point below
    cannot simply drop the string: everything the app would once have flashed in
    the inner bar lands here instead, with a stamp, and is still on `win.status`
    for any in-window surface goetia grows later.
    """
    text = str(text).strip()
    if not text:
        return
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + text
    print("goetia: " + text, file=sys.stderr)
    try:
        STATUS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_LOG, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass          # stderr already has it; a log that cannot be written is
                      # not worth taking the report down with it


class _MuteFooterVtbClient(VtbClient):
    """goetia's `VtbClient`, with the `FOOTER` verb removed.

    THE choke point, and it is at the client rather than at the `Slot` on
    purpose — [his, 2026-07-30] *"why are you unable to simply stop ANY text
    from appearing in the inner titlebar of goetia?"*, after a pass that removed
    one emitter and left the others. Removing call sites one at a time is
    whack-a-mole; this makes the string UNSENDABLE from this app, so a future
    caller — a new failure report, a new phase line, `Titlebar.setFooter`
    itself, anything that reaches `self._client` directly — cannot reintroduce
    it without deleting this class.

    The inner (left) bar draws exactly two things: the app's button cells and
    the footer (`pylib/vtbclient.py`'s docstring; `home/prog/hyprvtb/vtbIpc.hpp`
    is the server side). The cells are 1-2 char glyphs and are the app's
    navigation chrome, which he uses; the footer is the only free-text slot
    there, so overriding `set_footer` closes the bar completely.

    `_footer` therefore stays `""` for this app's whole life, which also keeps
    `_flag_lines_locked()` from replaying a `FOOTER` line on every reconnect —
    the path that used to survive a plugin hot-swap. **Not a change to
    `pylib/vtbclient.py`**: eight other apps use that footer and are unaffected.
    """

    def set_footer(self, text):
        _record_status(text)


class Titlebar(QObject):
    """hyprvtb app-button bridge — board's chrome (the three section jumps and
    `md`) is drawn by the compositor in the titlebar's inner column, not in QML
    (docs/DESIGN.md §12, §7.4). The vtb callbacks fire on the client's I/O
    thread; the Signal hops them onto the GUI thread.

    **Its inner bar carries NO text.** See `_MuteFooterVtbClient`."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = _MuteFooterVtbClient(on_click=self.clicked.emit)

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
        # Kept so `Main.qml` needs no change, and deliberately NOT a route to
        # the bar: the client refuses it anyway (`_MuteFooterVtbClient`), and
        # going straight to the log means one hop instead of two.
        _record_status(text)

    @Slot(bool)
    def setTitleText(self, on):
        self._client.set_title_text(on)


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
    #: a removed TO DO bullet is now recoverable, or is no longer
    undoChanged = Signal()

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        # PER-HOST store (`boardparse.board_path()`): this app shows and writes
        # THIS machine's board and never the other's. `ensure_board` brings it
        # into existence, so a first run on a host that has never had one draws
        # an empty board rather than a `cannot read` footer.
        self._path = os.path.abspath(os.path.expanduser(
            path or boardparse.ensure_board()))
        self._doc = {}
        self._landedFile = []
        self._err = ""
        self._undo = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)      # an atomic save replaces the inode
        # A write lands as several inotify events; coalesce them, and let our
        # OWN write settle before re-reading it. `boardparse.write` is already
        # atomic (temp file, fsync, `os.replace`), so nothing here waits for
        # the CONTENT to be safe to read — only for the burst of events one
        # atomic replace fires (a create and a rename, back to back) to finish
        # arriving. Measured offscreen (`/tmp/latency_probe.py`-style harness,
        # `boardmove.note()` to a scratch board): those land within a couple of
        # ms of each other, so 120 ms was almost entirely dead wait on his
        # screen — a worker's `ENACTED:`/LANDED bullet sat unread for it every
        # time. 30 ms is still generous coalescing headroom and cut the
        # measured write-to-redraw time from ~125-135 ms to ~30-40 ms.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(30)
        self._settle.timeout.connect(self._reload)
        # LANDED IS READ OUT OF GIT, HERE, every time the section is built —
        # `boardmove.landed_view()`, a pure read. Nothing sweeps, nothing
        # appends, nothing has to have remembered: what he is looking at is the
        # commit log, so the section cannot be stale unless git is.
        #
        # That is his verdict and it is also what fixes the way the two previous
        # fixes could not reach him: both of them made something WRITE the
        # missing rows, and a writer has to be deployed. This window is live
        # source with no hot reload, so the one he had open never ran either
        # fix; the watcher is a home-manager unit, so on `top` the second one
        # needed a rebuild before it existed. A derived view has no deployment
        # at all — whichever build of this file is running reads git at the
        # moment of the read.
        #
        # The timer is only for the case where NOTHING ELSE moves: no file
        # event, no window activation, and a commit made in another terminal.
        # It asks `git rev-parse` (about a millisecond) and rebuilds only if a
        # ref actually moved, so it never writes and never wakes the parser.
        self._tips = ""
        self._poll = QTimer(self)
        self._poll.setInterval(10000)
        self._poll.timeout.connect(self._poll_git)
        self._poll.start()
        self._load()

    # ---- reading ----

    def _derives(self):
        """Only a board that lives INSIDE the repo it is a record of. A harness
        (or `--board`) points this app at a throwaway file, and handing that one
        ~/nix's real history would be inventing a hundred rows it never had."""
        return os.path.abspath(self._path).startswith(
            os.path.abspath(boardmove.LANDED_REPO) + os.sep)

    def _landed(self):
        """The LANDED section as it should be DRAWN: the file's rows are the
        cache and the wording, git is the record of what exists. Never fatal —
        §10 — so a repo that cannot be read leaves the file's own rows."""
        if not self._derives():
            return self._landedFile
        try:
            self._tips = boardmove.landed_tips()
            return boardmove.landed_view({"landed": self._landedFile})
        except (OSError, ValueError, subprocess.SubprocessError):
            return self._landedFile

    def _poll_git(self):
        if not self._derives():
            return
        try:
            tips = boardmove.landed_tips()
        except (OSError, ValueError, subprocess.SubprocessError):
            return
        if tips == self._tips:
            return
        self._doc["landed"] = self._landed()
        self.docChanged.emit()

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
            self._landedFile = []
            self._doc = {"needs": [], "todo": [], "flight": [], "landed": [],
                         "intro": {}, "lines": [], "digest": ""}
            self.docChanged.emit()
            return False
        self._err = ""
        self._doc = boardparse.parse(src)
        # The file's rows are kept APART from what is drawn: `landed_view` reads
        # them as its cache, so feeding it its own output would let the derived
        # half accumulate as if it had been written down.
        self._landedFile = self._doc["landed"]
        self._doc["landed"] = self._landed()
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

    def _stamp(self, lines, key):
        """Record WHICH MACHINE he just answered on, in the same write.

        board-watch runs on `top` AND on `book`. Since the per-host split
        (2026-07-30) each watcher only ever sees its own machine's board, so
        this is a backstop rather than the mechanism — it still records the
        host an answer was typed on, which is the host that works it.
        `boardparse.set_answer_host()` owns the line; this only decides which host, and that no answer means no stamp.

        Re-parsed from the lines the caller has ALREADY computed, because
        `set_answer` can change how many lines the `>` block occupies and every
        index below it with it.
        """
        try:
            doc = boardparse.parse("".join(lines))
        except Exception:                       # a parse must never cost a write
            return lines
        for it in doc["needs"]:
            if it["key"] == key:
                return boardparse.set_answer_host(
                    doc["lines"], it, os.uname().nodename if it["answered"] else "")
        return lines

    def _commit(self, lines):
        """Write `lines`, but only if the file on disk is still the one they
        were computed from. A stale line index would land his answer in the
        middle of someone else's paragraph — the one failure this app must never
        have — so a race REFUSES, reloads and says so."""
        try:
            src = boardparse.read(self._path)
        except OSError as e:
            self.status.emit("cannot read the board - " + (e.strerror or "?"))
            return False
        if boardparse.digest(src) != self._doc.get("digest"):
            self._load()
            self.reloaded.emit()
            self.status.emit("the board changed on disk - reloaded, nothing written")
            return False
        try:
            boardparse.write(self._path, "".join(lines))
        except OSError as e:
            self.status.emit("could not write the board - " + (e.strerror or "?"))
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
        ok = self._commit(self._stamp(
            boardparse.toggle_option(self._doc["lines"], it, index, checked), key))
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
        ok = self._commit(self._stamp(
            boardparse.set_answer(self._doc["lines"], it, text), key))
        if ok:
            self.status.emit("saved" if text.strip() else "answer cleared")
        return ok

    @Slot(str, result=str)
    def answerOf(self, key):
        it = self._item(key)
        return it["answer"] if it else ""

    # ---- clearing a chore off WAITING ON YOU TO DO ----
    # *"i should be able to clear the 'to do' stuff if i
    # wish. currently i cannot remove it via board program"*. Agents put bullets
    # there and nothing ever took one away.
    #
    # Two deliberate acts (docs/DESIGN.md §10.3), and NO confirmation dialog —
    # the same reading `ProcMenu`'s `force quit` settled: the right-click that
    # opens the menu is the first act, the entry (last, behind a separator) is
    # the second. What this has instead is an UNDO, because unlike a signal to a
    # process a deleted line can be put back byte-for-byte, and offering the
    # thing that actually repairs the mistake beats asking him to predict one.
    # One level, this session only: the older removals are in `docs/`'s git
    # history, which a timer commits every five minutes, and the risk this
    # guards is the misclick he notices immediately.

    def _todo(self, line):
        for t in self._doc.get("todo", []):
            if t.get("line") == line:
                return t
        return None

    @Slot(int, result=bool)
    def removeTodo(self, line):
        it = self._todo(line)
        if it is None:
            self.status.emit("that line is no longer there - reloaded")
            self._load()
            return False
        lines = self._doc["lines"]
        try:
            a, b = boardparse.todo_span(lines, it)
            out = boardparse.remove_todo(lines, it)
        except boardparse.BoardError as e:
            self.status.emit(str(e) + " - reloaded")
            self._load()
            return False
        block = list(lines[a:b])
        after = lines[b] if b < len(lines) else ""
        if not self._commit(out):
            return False
        self._undo = {"kind": "todo", "block": block, "before": after,
                      "text": it.get("text", "")}
        self.undoChanged.emit()
        self.status.emit("removed - `put it back` is in the right-click menu")
        return True

    @Slot(str, result=bool)
    def removeDecision(self, key):
        """Remove a whole multi-choice question (heading + options) from NEEDS
        YOU. The question-block analog of `removeTodo`, and the same one-level
        undo: the block's raw lines are kept and `put it back` restores it
        byte-for-byte -- the misclick you notice immediately, covered the same
        way a removed chore is.

        NOT the same act as `boardmove.start`: that one is for an ANSWERED
        decision moving out to be worked. This is for a question he no longer
        wants asked at all, so it does not consult the stash and does not care
        whether anything is answered.
        """
        it = self._item(key)
        if it is None:
            self.status.emit("that question is no longer there - reloaded")
            self._load()
            return False
        lines = self._doc["lines"]
        try:
            a, b = boardparse.item_span(lines, it)
            out, block = boardparse.cut_item(lines, it)
        except boardparse.BoardError as e:
            self.status.emit(str(e) + " - reloaded")
            self._load()
            return False
        after = lines[b].rstrip("\n") if b < len(lines) else ""
        before = after if after.startswith("###") else ""
        if not self._commit(out):
            return False
        title = boardparse.raw_title(lines, it) or it.get("title", "")
        self._undo = {"kind": "needs", "block": block, "before": before,
                      "text": title}
        self.undoChanged.emit()
        self.status.emit("question removed - `put it back` is in the right-click menu")
        return True

    @Slot(result=bool)
    def undoRemove(self):
        u = self._undo
        if not u:
            return False
        try:
            if u.get("kind") == "needs":
                out = boardparse.add_needs_item(self._doc["lines"], u["block"],
                                                u.get("before"))
            else:
                out = boardparse.add_todo_block(self._doc["lines"], self._doc,
                                                u["block"], u.get("before"))
        except boardparse.BoardError as e:
            self.status.emit(str(e))
            return False
        if not self._commit(out):
            return False
        self._undo = None
        self.undoChanged.emit()
        self.status.emit("put back")
        return True

    @Property(str, notify=undoChanged)
    def undoText(self):
        """What `put it back` would put back, or "" when there is nothing. The
        menu entry is ABSENT rather than greyed when this is empty (§10): an
        undo with nothing behind it is not a control."""
        return (self._undo or {}).get("text", "")

    # ---- drag-to-reorder: rewriting the STORE'S OWN ORDER ----
    # [his ask, 2026-08-01] drag a section heading or a subheading to move it,
    # and the new order is WRITTEN TO THE FILE so it survives a reload. This is
    # the one genuinely structural write the app makes — a reorder is not a
    # line edit, and that is fine: a reorder is precisely the thing he asked
    # to change. Every block that moves travels whole (`boardparse`'s reorders),
    # the reload that follows is the ordinary one (`_commit` re-reads, applies
    # the digest check and re-lists), and the page redraws in the new order.
    # Nothing that failed reports as a success (§10): a refused reorder (no
    # section, a stale file) reloads and says so.
    def _reorder(self, fn):
        try:
            out = fn(self._doc["lines"])
        except boardparse.BoardError as e:
            self._load()
            self.status.emit(str(e) + " - reloaded")
            return False
        if out == self._doc["lines"] or not out:
            return True                    # already in that order: nothing to do
        return self._commit(out)

    @Slot("QVariantList", result=bool)
    def reorderSections(self, order):
        """Reorder the store's `## ` sections into `order` (section names,
        top-to-bottom). Only store sections are reorderable here — the page's
        summoner and triangle bands are the machine, not the store, so they are
        left out and stay put."""
        names = [str(x) for x in (order or [])]
        return self._reorder(lambda lines: boardparse.reorder_sections(lines, names))

    @Slot("QVariantList", result=bool)
    def reorderNeeds(self, order):
        """Reorder the decisions of NEEDS YOU into `order` (decision `key`s) and
        renumber their `### n.` prefixes to match."""
        keys = [str(x) for x in (order or [])]
        return self._reorder(lambda lines: boardparse.reorder_needs(lines, keys))

    @Slot("QVariantList", result=bool)
    def reorderLanded(self, order):
        """Reorder LANDED's `### <date>` groups into `order` (their date
        headings, e.g. `2026-08-01`). Dates are identifiers, so nothing is
        renumbered."""
        dates = [str(x) for x in (order or [])]
        return self._reorder(lambda lines: boardparse.reorder_landed(lines, dates))

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


class Agents(QObject):
    """Who is working right now, and the one way he can reach them.

    `boardagents.py` is the whole mechanism and its docstring is authoritative:
    the liveness rule is `boardmove`'s (pid + kernel start time, so a recycled
    pid cannot fake life) and a message is a FILE, because an agent's stdin is
    closed and there is nothing to type into. This class is only the Qt skin on
    it — a poll, a systemctl query that does not block the GUI thread, and the
    strings the section draws.

    IT WRITES NOTHING TO THE BOARD. Everything here lives under
    `~/.local/state/board/`; the store's only writers stay `boardparse.edit()`'s
    three (the app's answers, boardctl, board-watch).
    """

    changed = Signal()
    #: for the titlebar footer, the same channel Board uses
    status = Signal(str)
    #: A LIFECYCLE transition and nothing else: an agent appeared, or one of
    #: them changed state (finished, was killed, failed, was reclaimed).
    #: Deliberately NOT `changed`, which also fires for the churn every poll
    #: brings — a worked-for line ticking over a minute, a context tally, a new
    #: unread note — and anything hung off that would be a 2.5s poll of
    #: whatever it drives. See `Usage.follow()`, its one consumer.
    lives = Signal()
    #: THE LIVE SHELLS of the spirits bound in the triangle. A per-spirit
    #: little tail of the agent's own literal output, rebuilt on the ordinary
    #: poll — `shells` is the list, this is when it changed. Deliberately a
    #: SEPARATE signal from `changed`: a running agent's output moves every poll,
    #: and hanging the whole window off that would make `changed` fire near-
    #: continuously. The section binds to this and nothing else does.
    shellsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._cards = []
        self._queued = []
        self._undo = False
        self._watcher = ""
        self._armed = None
        self._lives = None
        self._shells = []
        #: id -> session uuid, refilled on every poll. The output drawer needs
        #: it to find the agent's live transcript, and the session is not on the
        #: card: it is machine business, so it stops here rather than in QML.
        self._sessions = {}
        # The registry, the stashes and the inboxes are all files, so watch
        # them — but /proc is not, so poll as well. 2.5s is well under "prompt"
        # for a finished agent leaving the list and costs one /proc walk.
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _p: self.refresh())
        self._poll = QTimer(self)
        self._poll.setInterval(2500)
        self._poll.timeout.connect(self.refresh)
        self._poll.start()
        # systemctl is a fork; it does not happen on the GUI thread's clock.
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_systemctl)
        self._unit = QTimer(self)
        self._unit.setInterval(10000)
        self._unit.timeout.connect(self._ask_systemd)
        self._unit.start()
        self._ask_systemd()
        self.refresh()

    # ---- reading ----
    def _rewatch(self):
        want = [boardagents.inbox_dir("queue"), boardagents.agents_dir(),
                boardagents.bm.stash_dir(), boardwork.work_dir("pending")]
        for d in want:
            if os.path.isdir(d) and d not in self._watch.directories():
                self._watch.addPath(d)

    #: `systemctl` is not on this app's wrapped PATH on every machine, and a
    #: QProcess that cannot start reports nothing at all — which would read as
    #: "the watcher is fine" instead of "we could not ask" (§10). Find it.
    #:
    #: `$BOARD_SYSTEMCTL` overrides it, for the harness alone and in the spirit
    #: of `BOARD_USAGE_OFFLINE`: the window's own suite asserts the sentence a
    #: typed note gets back, which names the summoner only while the watcher is
    #: ARMED — so without this a green suite depends on whether board-watch
    #: happens to be running on the machine under it, and stopping the units for
    #: an unrelated reason turns a check red that has nothing to do with them.
    #: (`top`, 2026-07-31.) Never set in production; the fallbacks below are.
    SYSTEMCTL = os.environ.get("BOARD_SYSTEMCTL") or \
        next((p for p in ("/run/current-system/sw/bin/systemctl",
                          "/usr/bin/systemctl", "/bin/systemctl")
              if os.path.exists(p)), "systemctl")

    def _ask_systemd(self):
        if self._proc.state() != QProcess.NotRunning:
            return
        # BOTH units, service first — `watcher_state` reads them positionally.
        # The service alone cannot answer "armed": it is `inactive` between
        # ticks whether or not the path unit that starts it is running.
        self._proc.start(Agents.SYSTEMCTL,
                         ["--user", "show", "board-watch.service",
                          "board-watch.path",
                          "-p", "ActiveState", "-p", "SubState", "-p", "Result",
                          # ...and LoadState, which is the ONLY thing that tells
                          # a stopped watcher from one that was never deployed
                          # on this host at all. See `watcher_state`.
                          "-p", "LoadState"])

    def _on_systemctl(self, *_a):
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        st = boardagents.watcher_state(raw)
        if st["text"] != self._watcher or st["armed"] != self._armed:
            self._watcher = st["text"]
            self._armed = st["armed"]
            self.changed.emit()

    def _row(self, a):
        return {
            # The id is what a message is ADDRESSED to and what the unit, the
            # log and the sidecar are named; `name` is what he READS. Both cross
            # over, and the card draws only the second.
            "id": a["id"], "name": a.get("name", ""),
            # The readable model tier — *"sonnet 5 medium"* — already resolved by
            # `boardagents.agents()`. It rides the name on the card's leading
            # sentence (built in `boardphase`) and the name CELL when a stopped
            # card has no sentence to carry it (`AgentRow` `titleFirst`). "" for
            # an agent with no chosen model (a session, a pre-tiering record).
            "model": a.get("model", ""),
            "kind": a["kind"], "title": a["title"],
            "where": a["where"], "state": a["state"],
            "running": a["state"] == "running",
            # ...and whether a STOPPED one had reported its result first. The
            # card draws it as finished rather than abandoned — words and
            # accent gutter both. `boardagents` derives it from
            # `boardwork.reported`, the same fact `reap()` files it by.
            "finished": bool(a.get("finished")),
            "phase": a.get("phase", ""),
            # THE TWO STATEMENTS, and they cross into QML as two fields. Never
            # merged here and never defaulted from each other: `boardphase.py`
            # has already decided what each of them honestly says, including
            # when one of them is nothing at all.
            "says": a.get("says", ""),
            "actually": a.get("actually", ""),
            # ...and the same two as the sentences the card draws, built once
            # in `boardphase.py` (`says_line`/`doing_line`) because the joining
            # is a judgement about the real strings: a stopped agent is
            # described in the PAST tense, and a claim with no phase word is
            # quoted rather than forced after "is".
            "saysLine": a.get("saysLine", ""),
            # ...and the claim's own second line: the words it gave for what it
            # is doing, which used to follow a hyphen on the line above.
            "saysDetail": a.get("saysDetail", ""),
            "doingLine": a.get("doingLine", ""),
            # ...and whether this card is the bare *"<name> awakens..."* one: an
            # agent that is running and has neither claimed nor been seen doing
            # anything yet. True makes the rising line the WHOLE card
            # (`AgentRow` drops the title row and the trailing metadata off it);
            # `boardagents` carries why it is drawn rather than withheld.
            # Absent defaults to False, which is what keeps `boardwork`'s own
            # synthetic cards (a queued task, Solomon's standing row) whole.
            "arising": a.get("arising", False),
            "observed": a.get("observed", "unlinked"),
            # How much context it is standing in, against what it can hold —
            # already formatted, and "" when nothing could be measured.
            "contextLine": a.get("contextLine", ""),
            # ...and HOW LONG it has been working, drawn beside that tally —
            # `boardphase.worked_line`, the one elapsed time this app draws,
            # his own exception to the no-pressure rule. Formatted in Python
            # and recomputed on every poll; the raw `born` epoch still does
            # NOT cross, so QML cannot grow a second counter of its own.
            "workedLine": a.get("workedLine", ""),
            "detail": boardagents.describe(a),
            "waiting": [m["text"] for m in boardagents.for_agent(a["id"])]
                       if a["id"] else [],
            # A DEEPSEEK SUBSPIRIT's card, drawn INSET under its parent
            # spirit's card (§9.1's subordinate block — `AgentRow.subspirit`).
            # `kind`, `parent` and `parentName` are `boardagents`' (Botis' seam:
            # `register(parent=...)` + the dict `agents()` appends); the card is
            # otherwise an ordinary agent card. `boardwork.cards()` leaves a
            # subspirit OUT of the flat list, so `workers` below is the one
            # place it is interleaved back under its parent.
            "subspirit": a.get("kind") == "subspirit",
            "parentId": a.get("parent", ""),
            "parentName": a.get("parentName", ""),
        }

    # ---- WHAT IT IS ACTUALLY SAYING: the tail of the worker's own log ----
    # [his, 2026-07-30] a card opens a drawer showing *"the last couple of
    # lines"* of that spirit's output. The card's three lines are this app's
    # account of the agent; this is the agent's own voice, unedited.
    #
    # THE LIVE SOURCE IS THE TRANSCRIPT, NOT THE `.log`. [his, 2026-07-30]
    # *"the drop down log in agent cards should be the last couple lines of
    # their REAL LIVE OUTPUT... agent card logs should really never read as
    # 'nothing logged yet' which they do now pretty much all the time"*.
    #
    # The `.log` is the file `boardwork` gives the worker its stdout in
    # (`~/.cache/board-work/<id>.log`, through its own `_log_path` so the
    # `XDG_CACHE_HOME` a harness sets is honoured — a test must never read his
    # real cache, which is the reason that helper exists). It is real, and it is
    # EMPTY FOR THE WHOLE RUN: `claude -p` with no tty writes its result once, at
    # the end. Measured on top 2026-07-30 while two workers were live — both
    # their logs were 0 bytes, and of ~200 finished ones every single non-empty
    # file was written at exit. So the drawer said "nothing logged yet" for
    # exactly as long as there was anything to watch, which is the complaint.
    # (Since 2026-07-30 the file is not literally empty: `boardwork` writes a
    # `- [board ...]` header at spawn and a post-mortem at reap, so a worker
    # killed mid-run still points at its transcript. Those are board's lines,
    # not the agent's — the transcript is still the live source.)
    #
    # The agent's transcript is appended to as it works, and `boardphase` already
    # reads it for the observed line and the context tally — so it is the same
    # file, no new pipe, and each entry becomes one line: what the agent SAID, or
    # `describe_call` on the tool it reached for, which is the same vocabulary
    # the card's own observed line uses. The `.log` is the fallback, and it is
    # the right one after the run: a dead worker has no more transcript but its
    # final output is on disk.
    #
    # Read here rather than in QML because QML cannot read a file at all, and
    # cleaned here rather than there because §2.3 says to map glyphs at INGEST:
    # this is somebody else's text, so it goes through `px()` exactly as the
    # store's prose does. Only the WIDTH-dependent elide is the drawer's, the
    # font being monospace (§2.7).
    #
    # An EMPTY list means "nothing logged", and the drawer says that in words
    # rather than opening empty (§10). It is never a guess: a missing file, an
    # unreadable one and one holding nothing but control junk are all the same
    # honest answer, and none of them is an error worth a colour.
    #: How many of its own lines a card shows. His *"couple"*, read as the 2-3
    #: the drawer can carry without becoming the transcript §5.2 rules out.
    OUTPUT_LINES = 3
    #: ...and how much of the tail is read to find them. A worker's log runs to
    #: megabytes; only the end of it is ever drawn.
    OUTPUT_TAIL = 64 * 1024
    #: ANSI escapes (CSI and OSC) plus every other C0/C1 control. `claude -p`
    #: has no tty here, but its output carries other programs' output.
    _ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
                       r"|\x1b[@-Z\\-_]")
    _CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

    #: How far back into the transcript one poll reads. Entries are large (a
    #: tool result can be tens of kB), so this is generous where the log's tail
    #: is not — and it is still only the end of the file.
    TRANSCRIPT_TAIL = 256 * 1024

    #: How wide one line of the drawer may be before it is cut. The drawer
    #: elides to the card's width itself; this only stops a 40kB tool result
    #: from arriving as one line and being carried around as one.
    OUTPUT_WIDTH = 400

    #: How many of its own lines one row of the triangle's SHELLS tail shows.
    #: [his ask, 2026-08-01] *\"the last couple of lines\"* — two, read for the
    #: same reason the drawer is cut at three: several spirits side by side
    #: must not become the transcript §5.2 rules out.
    SHELL_LINES = 2

    #: How long a BACKGROUNDED process line may be before it is cut — a worker
    #: argv can be pathological, and its job here is to say WHAT is running, not
    #: to become a second transcript (§5.2 keeps a banner from growing one).
    SHELL_BG_WIDTH = 200

    @staticmethod
    def _tool_use_lines(name, inp):
        """A tool CALL as its literal arguments, not as a description of it.

        [his, 2026-07-30] *"you are saying we cannot actually see its real live
        log i.e. not what its saying its doing but its literal actual thinking /
        tool call / coding output?"* — so a `Bash` is the command it ran, an
        `Edit` is the replacement text, a `Write` is what was written. The
        one-line-per-event summary `boardphase.describe_call` builds is still
        right for the card's OBSERVED line, which is a summary by design; it is
        the wrong thing in a drawer that is supposed to be the running log.

        A header naming the tool, then whichever of its inputs is the payload —
        by key, so a tool this does not know about still shows its arguments
        rather than nothing.
        """
        inp = inp or {}
        head = str(name or "tool")
        # The one argument that IS the call, per tool, in the order it reads.
        lead = ("command", "file_path", "path", "pattern", "url", "query",
                "prompt", "description")
        first = next((str(inp[k]) for k in lead if inp.get(k)), "")
        out = ["$ " + " ".join(first.split()) if head == "Bash" and first
               else (head + " " + first).rstrip()]
        # ...and the BODY, which is the part he is actually asking to see.
        for k in ("old_string", "new_string", "content", "replace_all"):
            v = inp.get(k)
            if isinstance(v, str) and v.strip():
                out.append(k + ":")
                out.extend(v.split("\n"))
        return out

    @staticmethod
    def _result_lines(part):
        """A tool RESULT as its own text — the output of the command, the error
        the compiler printed. The transcript carries it as a string or as a list
        of content blocks; both shapes are the same lines."""
        body = part.get("content")
        if isinstance(body, str):
            return body.split("\n")
        out = []
        for b in body if isinstance(body, list) else []:
            if isinstance(b, dict) and b.get("type") == "text":
                out.extend(str(b.get("text") or "").split("\n"))
        return out

    @staticmethod
    def _transcript_lines(session, tools_only=False):
        """THE AGENT'S LITERAL OUTPUT, live, newest at the tail.

        With `tools_only`, the tool invocations the agent runs AND their own
        output — its commands, its tool calls and what each printed back — but
        none of its prose or reasoning. [his, 2026-08-01] the workings band
        under a card shows the tools the agents use, not the agent's narration;
        [his, 2026-08-03] and it must show the ACTUAL OUTPUT of those tools, a
        trailing log of what the command/script printed, not only the command
        line. The DRAWER (`output`, `tools_only=False`) keeps everything,
        prose included.

        Not a summary of it: his words are *"its literal actual thinking / tool
        call / coding output"*. So every line of every assistant `text` and
        `thinking` block, every tool call's own arguments
        (`_tool_use_lines`) and every tool result's own text
        (`_result_lines`), flattened in the order the file has them. The
        drawer then shows the last few, which is `tail` on a running log.

        The only entries skipped are his own turns — a user message is his
        prompt read back at him, and it is not the agent's output.

        Reads only the tail, and only whole lines: the file is being appended to
        while this runs, so a final fragment is skipped rather than parsed as a
        truncated object (the same rule `boardphase._tool_calls` follows).
        """
        path = boardphase.transcript(session)
        if not path:
            return []
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                start = max(0, f.tell() - Agents.TRANSCRIPT_TAIL)
                f.seek(start)
                raw = f.read()
        except OSError:
            return []
        rows = raw.decode("utf-8", "replace").split("\n")
        if start:
            rows = rows[1:]          # a partial first line, cut by the seek
        out = []
        for row in rows:
            row = row.strip()
            if not row:
                continue
            try:
                o = json.loads(row)
            except ValueError:
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else None
            if not msg:
                continue
            role = msg.get("role")
            body = msg.get("content")
            if isinstance(body, str):
                body = [{"type": "text", "text": body}]
            if not isinstance(body, list):
                continue
            for part in body:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "tool_use" and role == "assistant":
                    out.extend(Agents._tool_use_lines(part.get("name"),
                                                      part.get("input")))
                elif kind == "tool_result":
                    # The command's OWN OUTPUT — the stdout/text of the tool it
                    # answers. Carried on a `user` entry by the platform, but it
                    # is the TOOL's output and not his words, so it belongs in the
                    # log — and, since [his, 2026-08-03], in the workings band
                    # too: *"the tools section SHOULD NOT just be `ls | grep`... it
                    # should be a trailing log of the ACTUAL OUTPUT"*. So it is
                    # kept for BOTH readers, ahead of the `tools_only` skip below;
                    # what that skip still drops is the spirit's prose and
                    # reasoning, never a command's result.
                    out.extend(Agents._result_lines(part))
                elif tools_only:
                    # The workings band is the calls and their OUTPUT — but not
                    # the spirit's own prose or reasoning.
                    continue
                elif role != "assistant":
                    continue
                elif kind == "text":
                    out.extend(str(part.get("text") or "").split("\n"))
                elif kind == "thinking":
                    out.extend(str(part.get("thinking") or "").split("\n"))
        # Blank lines are structure in prose and noise in three lines of tail.
        return [x.rstrip()[:Agents.OUTPUT_WIDTH] for x in out if x.strip()]

    @Slot(str, result="QVariantList")
    def output(self, agent_id):
        if not (agent_id or "").strip():
            return []
        rec = boardagents.record(agent_id) or {}
        # A spirit on the hermes runtime has no transcript FILE; its history is
        # rows in `~/.hermes/state.db`, bound to this agent by the query it was
        # spawned with. Same drawer, same three lines, same rule about whose
        # words belong in it — only the reader differs (`boardhermes.lines`).
        hsession = boardphase.hermes_session(agent_id)
        if hsession:
            import boardhermes
            live = boardhermes.lines(hsession)
        else:
            live = Agents._transcript_lines(rec.get("session"))
        if live:
            return [px(x) for x in live[-Agents.OUTPUT_LINES:]]
        try:
            path = boardwork._log_path(agent_id)
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - Agents.OUTPUT_TAIL))
                raw = f.read()
        except OSError:
            return []
        out = []
        # Split on \n ALONE: `splitlines()` also breaks on \r, which would turn
        # every progress rewrite into as many lines as it had frames — and the
        # last of those frames is the only one that was ever a line.
        for line in raw.decode("utf-8", "replace").split("\n"):
            # A progress line rewrites itself with \r; what it settled on is the
            # last chunk, and the rewrites before it were never lines.
            line = Agents._CTRL.sub("", Agents._ANSI.sub("", line.split("\r")[-1]))
            if line.strip():
                out.append(px(line.rstrip()))
        return out[-Agents.OUTPUT_LINES:]

    @Slot()
    def refresh(self):
        self._rewatch()
        try:
            live = boardagents.agents()
            rows = [self._row(a) for a in live]
            # ONE FLAT LIST, oldest first — `boardwork.cards()` is the one place
            # that decides the order, and it is birth and nothing else, so a
            # card does not move under his cursor when the agent changes phase
            # or stops. Queued tasks come after the live ones; they have no
            # birth yet.
            drawn = boardwork.cards()
            cards = [self._row(a) for a in drawn]
            # The one place both lists are in hand, so the one place the
            # id -> session map is built. `cards` is the superset (it pins
            # Solomon and the queued rows), and a queued row has no session,
            # which is exactly what the drawer should find for it.
            self._sessions = {a["id"]: a.get("session") or ""
                              for a in list(live) + list(drawn) if a.get("id")}
            # id AND text: the row he right-clicks has to name the message it
            # is acting on, and its text is not a name (two identical sentences
            # are two messages) while its position is not one either — the next
            # drain shifts every index.
            queued = [{"id": boardagents.msg_id(m), "text": m["text"]}
                      for m in boardagents.pending()]
            # CAN CTRL+Z DO ANYTHING RIGHT NOW? A bool, polled with everything
            # else, and the shortcut is enabled off it — so the key is only his
            # while there is an order to take back, and Ctrl+Z means ordinary
            # text undo the rest of the time. `boardundo.undoable()` reads and
            # changes nothing; the act itself is `undoSend()` below.
            undo = boardundo.undoable() is not None
        except OSError:
            return
        # Who exists and what state each one is in — the only thing `lives` is
        # about. Built off `cards`, which is the superset (`boardwork.cards()`
        # pins the orchestrator and the queued tasks as well), and sorted so a
        # reordering is not a transition.
        lives = tuple(sorted((c["id"], c["state"]) for c in cards))
        if (rows != self._rows or queued != self._queued or cards != self._cards
                or undo != self._undo):
            self._rows, self._queued, self._cards = rows, queued, cards
            self._undo = undo
            self.changed.emit()
        if lives != self._lives:
            was, self._lives = self._lives, lives
            if was is not None:      # the first read is not a transition
                self.lives.emit()
        # ---- the live shells of the bound spirits ----
        # Rebuilt off `cards` — the SAME drawn list the triangle shows — and
        # only for running, non-orchestrator rows, so the shells section can
        # never disagree with the triangle about who is bound. Each is the
        # worker's tool-and-output trace (`_shell_lines`, the transcript's
        # tool_use entries AND their results — not its prose, its reasoning or
        # its `.log`), cut to two lines. Emitted on its own signal so a moving
        # tail does not
        # re-broadcast `changed` to the whole window.
        shells = self._shells_build(cards)
        if shells != self._shells:
            self._shells = shells
            self.shellsChanged.emit()

    @Property("QVariantList", notify=changed)
    def list(self):
        return self._rows

    @Property("QVariantList", notify=changed)
    def cards(self):
        return self._cards

    # SOLOMON IS HIS OWN SECTION, above the workers — [his, 2026-07-29, asked
    # twice] *"solmon should be in his own \"summoner\" section above the agents
    # section"*. He was a row pinned to the top of the agents list until then.
    #
    # The SPLIT is here rather than in `boardwork.cards()`: that function still
    # owns the whole ordering — the pin, the birth order under it, the standing
    # row when nothing is running — and two views of one ordered list cannot
    # disagree about who is where. Two overlapping orchestrators are both his,
    # and both land in his section.
    @Property("QVariantList", notify=changed)
    def summoner(self):
        return [c for c in self._cards
                if c.get("kind") == boardagents.ORCHESTRATOR_KIND]

    @Property("QVariantList", notify=changed)
    def workers(self):
        # The flat, birth-ordered worker cards `boardwork.cards()` owns — minus
        # the orchestrator, who has his own section (`summoner`).
        cards = [c for c in self._cards
                 if c.get("kind") != boardagents.ORCHESTRATOR_KIND]
        # ...with each deepseek subspirit slotted back in DIRECTLY UNDER its
        # parent spirit, drawn inset (`AgentRow.subspirit`, §9.1). A
        # subspirit is a real registered agent, so it is in the `agents()`
        # walk (`self._rows`) — but `boardwork.cards()` deliberately keeps it
        # out of the flat list, so this is where the hierarchy is rebuilt for
        # the one surface that draws it. Ordered under its parent by id, which
        # is stable across polls so a card never jumps.
        subs = {}
        for r in self._rows:
            if r.get("subspirit"):
                subs.setdefault(r.get("parentId") or "", []).append(r)
        for lst in subs.values():
            lst.sort(key=lambda r: r.get("id") or "")
        out = []
        for c in cards:
            out.append(c)
            for s in subs.pop(c["id"], []):
                out.append(dict(s, orphan=False))
        # A subspirit whose parent card is gone still draws — but with no
        # card above it to be subordinate to, it drops the inset and reads as an
        # ordinary top-level card (`orphan`, killing `AgentRow.subspirit`).
        for lst in subs.values():
            for s in lst:
                out.append(dict(s, orphan=True))
        return out

    @Property(int, notify=changed)
    def boundSpirits(self):
        """How many spirits the triangle is BINDING right now — the running,
        non-orchestrator cards it draws. [his, 2026-07-31] the triangle header
        says it in words; this is the number behind the sentence.

        Derived from `_cards`, which is exactly what `boardwork.cards()` built
        — the sessions the user started are already filtered out of there, so
        this cannot disagree with what is on screen (an anonymous session of
        his is never counted). Queued tasks have no process yet and exited
        cards are unbound, so only `running` counts.
        """
        return sum(1 for c in self._cards
                   if c.get("kind") != boardagents.ORCHESTRATOR_KIND
                   and c.get("state") == "running")

    # ---- the SHELLS: a live tail per bound spirit -------------------------
    # [his ask, 2026-08-01] under the triangle, a small live tail per running
    # spirit — theirs, not this app's account of them. It is the SAME source
    # the card drawer tails (`output`, i.e. the transcript — a running worker's
    # `~/.cache/board-work/<id>.log` is buffered and empty until it exits), and
    # it reads the running set the way the app already knows it: off `cards`,
    # the very list the triangle draws, so a shell can never belong to an agent
    # the triangle is not showing. A row with nothing logged yet is ABSENT — an
    # empty shell slot is the §5.2 shape this board refuses; the card above it
    # still says `nothing logged yet` if he opens its drawer.
    #
    # THE CLARIFIED ASK, 2026-08-01: *"leave triangle how it is, do the
    # background processes in the other section labeled 'shells'"*. The
    # transcript tail shows the FOREGROUND activity — what each spirit is
    # doing right now, which is what the triangle already says. The backgrounded
    # long-runners it started and left running are a separate fact, visible for
    # free from each worker's own systemd unit cgroup, so they get their own
    # lines under the foreground tail — same band, same row, nothing in the
    # triangle changes. A spirit with foreground lines and no runners shows
    # just the tail; one that is silent but left a runner going shows the runner
    # (the row exists on the strength of the running process, not the words).
    # Only a worker — a card with a `board-worker-<id>` unit — can have
    # background processes; sessions and Solomon have no unit, so they read none
    # rather than guessing.
    def _shell_lines(self, agent_id):
        """The workings band's lines: the tool invocations a worker runs AND
        their OUTPUT — its commands, its tool calls and what each printed —
        never its prose, its reasoning, or its `.log`. [his, 2026-08-01] the
        band shows the tools the agents use, not the agent's narration;
        [his, 2026-08-03] and the ACTUAL OUTPUT of those tools, a trailing log
        of what the command/script printed, not just `ls | grep`. The DRAWER
        (`output`) is the opposite request and shows the literal everything,
        prose included, with a `.log` fallback; this band is the compact
        tool-and-output trace under a card, so it drops the prose and that
        fallback (the `.log` is the agent's own stdout — a log)."""
        if not (agent_id or "").strip():
            return []
        rec = boardagents.record(agent_id) or {}
        hsession = boardphase.hermes_session(agent_id)
        if hsession:
            import boardhermes
            live = boardhermes.lines(hsession, tools_only=True)
        else:
            live = Agents._transcript_lines(rec.get("session"), tools_only=True)
        return [px(x) for x in live[-Agents.OUTPUT_LINES:]]

    def _shells_build(self, cards):
        out = []
        for c in cards:
            if c.get("kind") == boardagents.ORCHESTRATOR_KIND:
                continue
            if c.get("state") != "running":
                continue
            lines = self._shell_lines(c.get("id", ""))
            bg = self._bg_processes(c.get("id", ""))
            if not lines and not bg:
                continue
            out.append({"id": c["id"], "name": c.get("name", ""),
                        "lines": lines[-Agents.SHELL_LINES:], "bg": bg})
        return out

    #: The cgroup path of `pid`'s unit, only when that unit is a worker's own
    #: (`board-worker-*.service`). Sessions, Solomon and this app itself live in
    #: other units, and a bogus read must never invent background processes for
    #: them — so the guard is the unit NAME inside the cgroup path, not just
    #: "a process that has children".
    def _worker_cgroup(self, pid):
        if not pid:
            return None
        try:
            with open("/proc/%d/cgroup" % pid) as f:
                text = f.read()
        except OSError:
            return None
        for line in text.splitlines():
            ctrl, _, path = line.partition(":")
            if ctrl == "0" and path.startswith("/") and "board-worker-" in path:
                return "/sys/fs/cgroup" + path
        return None

    def _bg_processes(self, agent_id):
        """The long-runners a bound worker started and left running, read from
        its own systemd unit cgroup: every process still in the unit besides
        the spirit itself. Empty for anything with no worker unit. Pure /proc
        reads — never a fork, so it is safe on the poll clock like the rest of
        the section."""
        rec = boardagents.record(agent_id) or {}
        main = rec.get("pid") or 0
        cg = self._worker_cgroup(main)
        if not cg:
            return []
        try:
            with open(cg + "/cgroup.procs") as f:
                pids = [int(p) for p in f.read().split() if p.strip().isdigit()]
        except OSError:
            return []
        out = []
        for pid in pids:
            if pid == main:
                continue
            label = self._proc_label(pid)
            if label:
                out.append(label)
        return out

    def _proc_label(self, pid):
        """One short line for a backgrounded process: its command name plus the
        arguments that say what it is (`quickshell -p /tmp/qs-x/qml`...), glyph
        mapped (§2.3), trimmed here so a pathological argv cannot pad the band."""
        try:
            with open("/proc/%d/comm" % pid) as f:
                comm = f.read().strip()
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                raw = f.read().split(b"\x00")
        except OSError:
            return ""
        args = [a.decode("utf-8", "replace") for a in raw if a]
        parts = args or [comm]
        # fold store paths to their basename: the /nix/store hash is noise
        line = " ".join(p.rsplit("/", 1)[-1] if "/" in p else p for p in parts)
        line = (comm + ": " + line) if comm and comm != parts[0] else line
        return px(line)[:Agents.SHELL_BG_WIDTH]

    @Property("QVariantList", notify=shellsChanged)
    def shells(self):
        """`[{id, name, lines, bg}]` for each bound spirit with something to
        show — `lines` the foreground tail, `bg` the backgrounded long-runners
        it left running (empty when it has none). Top-to-bottom the same order
        the triangle draws its cards in, so a shell never appears above or
        below the wrong card."""
        return self._shells

    @Property(int, notify=changed)
    def cap(self):
        return boardwork.cap()

    # ---- how many of them may run at once -----------------------------------
    # The second dropdown, between the model chooser and the meters. [his,
    # 2026-07-29] *"between the model selector and the indicators, add another
    # drop down for the max number of agents available."* Thin for the same
    # reason `models` is: `boardwork.cap()`/`set_cap()` are the ONE store —
    # the same file `boardctl.py cap` writes and every spawner reads — and
    # `CAP_CHOICES` is the one list.
    capChanged = Signal()

    @Property("QVariantList", notify=capChanged)
    def caps(self):
        """`[{n, label, current}]`, in the order the menu draws them. A cap of
        his that is off the list is appended rather than hidden: the control
        must not draw a tick beside a number that is not the live one."""
        cur = boardwork.cap()
        ns = list(boardwork.CAP_CHOICES)
        if cur not in ns:
            ns = sorted(ns + [cur])
        return [{"n": n, "label": self._capLabel(n), "current": n == cur}
                for n in ns]

    @staticmethod
    def _capLabel(n):
        return "%d spirit%s" % (n, "" if n == 1 else "s")

    @Property(str, notify=capChanged)
    def capLabel(self):
        """What the closed control reads."""
        return Agents._capLabel(boardwork.cap())

    @Slot(int, result=bool)
    def chooseCap(self, n):
        """Write it. Nothing is restarted and nothing is killed: `promote()`
        reads the file at the top of every board-watch tick, so a bigger cap
        starts queued work on the next one and a smaller cap simply stops
        starting more — the same "it takes effect for the next tick" mechanism
        the model chooser has, and for the same reason."""
        try:
            boardwork.set_cap(n)
        except (ValueError, OSError):
            return False
        self.capChanged.emit()
        self.changed.emit()
        return True

    # ---- how many SUMMONERS may plan at once ---------------------------------
    # The top dropdown of his four. [his, 2026-07-29] *"1. number of summoners 2.
    # summoner model 3. number of spirits 4. spirit model"*. Thin for the
    # reason the other three are: `boardwork.summoners()`/`set_summoners()` are
    # the ONE store — the file `boardctl.py summoners` writes and
    # `board-watch.work_the_queue` reads at the top of every tick — and
    # `SUMMONER_CHOICES` is the one list.
    summonersChanged = Signal()

    @Property("QVariantList", notify=summonersChanged)
    def summonerCounts(self):
        """`[{n, label, current}]`. A number of his that is off the list is
        appended rather than hidden, same as `caps`."""
        cur = boardwork.summoners()
        ns = list(boardwork.SUMMONER_CHOICES)
        if cur not in ns:
            ns = sorted(ns + [cur])
        return [{"n": n, "label": self._summonerLabel(n), "current": n == cur}
                for n in ns]

    @staticmethod
    def _summonerLabel(n):
        return "%d summoner%s" % (n, "" if n == 1 else "s")

    @Property(str, notify=summonersChanged)
    def summonerLabel(self):
        return Agents._summonerLabel(boardwork.summoners())

    @Slot(int, result=bool)
    def chooseSummoners(self, n):
        """Write it. Nothing is restarted: the next tick with something in the
        queue splits what he typed across up to this many runs."""
        try:
            boardwork.set_summoners(n)
        except (ValueError, OSError):
            return False
        self.summonersChanged.emit()
        return True

    # ---- which model orchestrates -------------------------------------------
    # The dropdown beside the box. Both halves are thin on purpose: the list and
    # the choice live in `boardwork`, because `boardctl.py model` and the
    # spawners read the same two functions and a second copy of the list here
    # would be a second answer to "what may he pick".
    modelChanged = Signal()

    @Property("QVariantList", notify=modelChanged)
    def models(self):
        """`[{name, label, current}]`, in the order the menu draws them. `name`
        is the `<flag> <effort>` pair `resolve_model` takes: the summoner chooser
        carries a thinking budget as well as a model now."""
        cur = boardwork.orch_model()
        return [{"name": "%s %s" % (f, e), "label": lab, "current": (f, e) == cur}
                for f, e, lab in boardwork.ORCH_MODELS]

    @Property(str, notify=modelChanged)
    def modelLabel(self):
        """What the closed control reads. Never the raw pair: `claude-opus-5` is
        a wire value and this is a line of his desktop's prose (§2)."""
        return boardwork.orch_label()

    @Slot(str, result=bool)
    def chooseModel(self, name):
        """Write his choice — model AND effort, one pick. It reaches the NEXT
        orchestrator and no other: a session already running keeps what it
        started with, which is his rule for a change made mid-run stated as the
        mechanism rather than enforced on top of one."""
        try:
            boardwork.set_orch_model(name)
        except (ValueError, OSError):
            return False
        self.modelChanged.emit()
        return True

    # ---- ...and what the SPIRITS run on ------------------------------------
    # The fourth dropdown, under the cap. [his, 2026-07-29] *"do not allow
    # spirits to be anything higher than opus 5 medium thinking."* This half
    # cannot OFFER more than that, because the list is `boardwork.SPIRIT_MODELS`
    # and there is no other list; `role_flags()` cannot SPAWN more than that,
    # whatever the file ends up saying. Two independent halves of one rule, on
    # purpose — a control that is the only guard is a guard a hand-edited file
    # walks past.
    spiritChanged = Signal()

    @Property("QVariantList", notify=spiritChanged)
    def spirits(self):
        """`[{name, label, current}]`, in the order the menu draws them, ceiling
        first. `name` is the `<flag> <effort>` pair `resolve_spirit` takes."""
        cur = boardwork.spirit_model()
        return [{"name": "%s %s" % (f, e), "label": lab, "current": (f, e) == cur}
                for f, e, lab in boardwork.SPIRIT_MODELS]

    @Property(str, notify=spiritChanged)
    def spiritLabel(self):
        """What the closed control reads. Prose, never the wire pair (§2)."""
        return boardwork.spirit_label()

    @Slot(str, result=bool)
    def chooseSpirit(self, name):
        """Write his choice. It reaches the next spirit dispatched and no
        other — a worker already running keeps what it started with, the same
        mechanism the summoner's chooser has."""
        try:
            boardwork.set_spirit_model(name)
        except (ValueError, OSError):
            return False
        self.spiritChanged.emit()
        return True

    @Property("QVariantList", notify=changed)
    def queued(self):
        return self._queued

    @Property(str, notify=changed)
    def watcher(self):
        return self._watcher

    #: Is anything going to pick his answers up? THREE-valued, and QML reads it
    #: as `=== true` / `=== false`: `undefined` is "we could not ask systemctl",
    #: which §10 does not let the triangle's empty state turn into a claim
    #: either way. Refreshed on the ten-second unit poll with the rest — never
    #: on a repaint, and nothing here forks.
    @Property("QVariant", notify=changed)
    def armed(self):
        return self._armed

    # ---- writing ----
    @Slot(str, str, str, str, result=str)
    def send(self, agent_id, title, kind, text):
        """His words to an agent. The return value is what the UI SAYS happened,
        and the two cases are kept apart on purpose (§10): `delivered` means the
        message is in a running agent's inbox, not that it has read it — the row
        goes on saying `unread` until the agent actually takes it, and if it
        never does, `sweep()` moves it to the queue for the next one.
        """
        try:
            msg = boardagents.send(text, to=agent_id or None, to_title=title,
                                   to_kind=kind)
        except OSError as e:
            return "could not save that note - " + (e.strerror or "?")
        if msg is None:
            return ""
        # WHAT CTRL+Z WOULD TAKE BACK. Only an order from the top box — a note
        # addressed to a running spirit is a different act, with its own row
        # and its own menu, and there is no summon of it to cancel.
        boardundo.remember(msg)
        self.refresh()
        # ...and it says WHO, when the agent has a name. `left in Marbas's inbox`
        # is the same promise as before — in its inbox, not read by it — made
        # about somebody he can point at.
        who = boardagents.name_of(agent_id) if agent_id else ""
        if msg["state"] == "delivered":
            return ("left in %s's inbox - %s reads that between steps"
                    % (who, who)) if who else \
                   "left in its inbox - it reads that between steps"
        if agent_id:
            return ("%s is not running - put in the inbox instead" % who) \
                if who else "it is not running - put in the inbox instead"
        # The top box. It says where the sentence WENT, never what will come of
        # it: an orchestrator has to read it first, and it only runs while he is
        # at the machine. Promising anything more would be the dishonest kind of
        # feedback §10 is about.
        # ...and, since ctrl+z, that it is still HIS. Saying so here is the one
        # honest place for it: the key is live exactly now, and the hint inside
        # the box cannot say it (with his caret in there Ctrl+Z is text undo).
        #
        # AND IT SAYS SO WHEN NOTHING WILL ACT — §10, the rule that a control
        # must not promise what it cannot do. The inbox is machine-local by
        # design, so a sentence typed here is worked HERE or not at all; with no
        # armed watcher on this host it sits in `inbox/queue/` unread and
        # unreported, and the old wording ("until a summoner acts") reads as a
        # promise that one will. 2026-07-30: an order typed on book did exactly
        # that and he had no way to see it. `armed` is three-valued and only a
        # definite False earns this — an unknown is not a no.
        if self._armed is False:
            return "in the inbox on %s, but NOT being worked - %s" % (
                boardwork.HOST, self._watcher)
        return "in the inbox - ctrl+z takes it back until a summoner acts"

    # ---- force-stopping ONE bound spirit from its card's menu ----
    # Same shape as `send`: the returned string IS what the footer says, and it
    # is the VERIFIED outcome, never the intent (§10, §10.3). `force_stop`
    # SIGKILLs the spirit's own transient unit and then re-reads liveness
    # before it answers, so the footer can never claim a kill that did not
    # happen — and the poll below redraws the card off the same read.
    @Slot(str, result=str)
    def forceStop(self, agent_id):
        try:
            res = boardwork.force_stop(agent_id)
        except OSError as e:
            res = {"msg": "could not stop it - " + (e.strerror or "?")}
        self.refresh()
        return res.get("msg", "")

    # ---- his second thoughts about something already queued ----
    # Same shape as `send`: the string IS what the footer says, and the failure
    # case has its own sentence rather than an empty one (§10.2 — refuse
    # visibly). Both can honestly fail: `board-watch` may have drained the
    # queue between the menu opening and the click, and then the run working
    # that sentence already exists and neither a removal nor an edit can reach
    # it. Saying "gone" is the only true thing left to say.

    @Slot(str, result=str)
    def removeQueued(self, msg_id):
        try:
            msg = boardagents.remove_queued(msg_id)
        except OSError as e:
            return "could not remove that - " + (e.strerror or "?")
        self.refresh()
        if msg is None:
            return ("that one has already gone to a summoner - "
                    "nothing removed")
        return "taken off the pending orders - the text is kept, not deleted"

    @Slot(str, str, result=str)
    def editQueued(self, msg_id, text):
        if not (text or "").strip():
            return ""
        try:
            msg = boardagents.edit_queued(msg_id, text)
        except OSError as e:
            return "could not save that edit - " + (e.strerror or "?")
        self.refresh()
        if msg is None:
            return ("that one has already gone to a summoner - "
                    "it got the old wording")
        return "that order is rewritten - the next summoner reads this"

    # ---- ctrl+z: take the last order back ----
    @Slot()
    def notAnOrder(self):
        """What was just sent was a REPLY to a chore, not an order from the box.

        Both take `send()` — one path, deliberately — but ctrl+z is about *"the
        last prompt"* he typed into the prompt box, and a reply also cleared a
        bullet off his list. Undoing half of that pair (the send, not the
        removal) and handing the words back in the WRONG box is not an undo, so
        the key simply does not claim it; `put it back` in the row menu is that
        act's own undo.
        """
        boardundo.forget()
        self.refresh()

    #: WHETHER THE KEY IS HIS AT ALL. False means Ctrl+Z is ordinary text undo,
    #: which is what the QML shortcut binds it to — an offered undo that cannot
    #: undo anything is exactly the §10 no-op this app is not allowed to draw.
    @Property(bool, notify=changed)
    def canUndo(self):
        return self._undo

    @Slot(result="QVariantMap")
    def undoSend(self):
        """Ctrl+Z. `boardundo.cancel()` is the mechanism and the two cases he
        named are one call into it; this is the sentence for each answer.

        `text` is his own words, and it is non-empty ONLY when something really
        was cancelled — the window puts it back into the prompt box, so a box
        refilled after a cancel that did not happen would be this app telling
        him the one lie it cannot tell.
        """
        rec = boardundo.last() or {}
        if not rec.get("id"):
            return {"said": "nothing to take back - no order has been sent yet",
                    "text": ""}
        try:
            out = boardundo.cancel(rec["id"])
        except OSError as e:
            return {"said": "could not take that back - " + (e.strerror or "?"),
                    "text": ""}
        self.refresh()
        state, others = out["state"], out.get("others") or 0
        if state == "queued":
            said = "taken off the pending orders - it is back in the box"
        elif state == "stopped":
            said = "the summoner is stopped - nothing was dispatched"
        elif state == "shared":
            said = ("a summoner has it with %d other order(s) - nothing "
                    "cancelled" % others)
        elif state == "summoned":
            said = "too late - a spirit has already been summoned for it"
        else:
            said = "that order has already gone - nothing cancelled"
        return {"said": said, "text": out.get("text") or ""}


class Usage(QObject):
    """The two usage bars under the model chooser — the Qt skin on `boardusage`.

    That module's docstring is authoritative for where the numbers come from,
    why the short window is labelled `5h` rather than "daily", and why no Fable
    figure is drawn. This class only re-reads and notifies.

    A poll, not a `QFileSystemWatcher`: both caches are rewritten by replace,
    which drops a file watch on the spot, and `~/.claude.json` lives in `$HOME`
    where watching the directory would wake this app for every stray download.
    The figures change on the order of minutes, so 60s is well inside "prompt"
    and the read is mtime-gated on top of that.

    **Two clocks, because reading is cheap and fetching is not.**

    - The 60s tick RE-READS the caches: two `stat`s and a small JSON parse.
    - A FETCH — `boardusage.fetch()`, one ~350ms HTTPS GET — happens at most
      every `FETCH_SEC`, on a daemon thread so the window never waits for the
      network, and its result comes back over `_fetched` as an ordinary queued
      signal. Exactly one is ever in flight.

    The fetch is the whole answer to [his, 2026-07-29] *"why did it take me
    opening an instance of claude-code for the usage indicators to update? they
    should always be up to date"*: `~/.claude.json` only advances while a session
    runs, so no polling interval here could have helped. See `boardusage`.

    **The clocks are the FALLBACK, not the trigger** [his, 2026-07-29]: *"ensure
    the usage indicators update every time an agent is killed / finishes their
    job / etc."* — so `follow()` hangs `kick()` on every agent LIFECYCLE
    transition, which now genuinely re-reads the number rather than re-reading a
    file nobody wrote. It is `Agents.lives`, not `Agents.changed`, because the
    latter fires for ordinary per-poll churn and that would make this a 2.5s
    fetch; `KICK_SEC` is the floor under it either way.

    **And a CLICK on a meter is the third trigger** [his, 2026-07-30]:
    `refreshNow()` is the same fetch with the gap set to zero, `busy` says it is
    happening and `refreshed` says how it went. A clickable readout that cannot
    report its own failure would be §10's inert control with a cursor over it.
    """

    changed = Signal()
    #: A fetch finished, with its reason word. Emitted from the worker thread —
    #: a queued connection is what carries it back to the GUI one.
    _fetched = Signal(str)
    #: A fetch is or is not in flight. The meters are clickable (below), so this
    #: is what lets a click look like it did something while the network is out.
    busyChanged = Signal()
    #: A fetch HE asked for has settled, with its reason word (`ok` when it
    #: worked). Only ever emitted for a hand-driven refresh: the clocks must not
    #: put a report in the footer he did not ask for.
    refreshed = Signal(str)

    #: Seconds between fetches on the idle clock, and the floor under a
    #: lifecycle-triggered one. A percentage moves by single digits in five
    #: minutes; twenty seconds is short enough that a finished agent shows up
    #: while he is still looking at the card.
    FETCH_SEC = 300.0
    KICK_SEC = 20.0
    #: And how often `nudge()` may be spent on an expired token.
    NUDGE_SEC = 900.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._hrows = []
        self._hprox = {}
        self._htopup = {}
        self._stamp = None
        self._busy = False
        self._fetched_at = 0.0
        self._nudged_at = 0.0
        self._why = "ok"
        self._by_hand = False
        self._fetched.connect(self._settled)
        self._poll = QTimer(self)
        self._poll.setInterval(60000)
        self._poll.timeout.connect(self.poll)
        self._poll.start()
        self.refresh()
        self._start(0.0)

    def follow(self, agents):
        """Re-read AND re-fetch whenever an agent starts, finishes or dies.

        Called wherever these two objects are built — `main()` and the harness's
        `build()`. One line, and it is here rather than in `Agents` so that
        class keeps knowing nothing about what watches it.
        """
        agents.lives.connect(self.kick)

    @Slot()
    def poll(self):
        """The 60s tick: always re-read, and top the reading up when it is due."""
        self._start(self.FETCH_SEC)
        self.refresh()

    @Slot()
    def kick(self):
        """An agent's life changed, so the number just moved. Go and look."""
        self._start(self.KICK_SEC)
        self.refresh()

    @Slot()
    def refreshNow(self):
        """He CLICKED a meter: fetch now, with both clocks ignored.

        [his, 2026-07-30] the meters must refresh on a click. The clocks stay
        exactly as they were — this is the same fetch path, with the gap set to
        zero, so there is one place where a reading comes from and one place
        where a failure is worded.

        It reports either way (docs/DESIGN.md §10): `busy` goes true for as long
        as the round trip lasts, and `refreshed` carries the outcome — including
        `off`, `expired` and `offline`, the three ways a click here can honestly
        achieve nothing. A fetch already in flight IS his refresh: `_start`
        declines to open a second one, and marking it by hand means its result
        still reaches the footer.
        """
        self._by_hand = True
        self._start(0.0)
        self.refresh()

    def _start(self, min_gap):
        """Fetch on a worker thread, unless one is running or it is too soon."""
        now = time.time()
        if self._busy or now - self._fetched_at < min_gap:
            return
        self._busy, self._fetched_at = True, now
        self.busyChanged.emit()
        threading.Thread(target=self._work, daemon=True,
                         name="board-usage").start()

    def _work(self):
        """Off the GUI thread: fetch, and heal an expired token if that is why.

        Nothing here touches Qt state except the signal — `_settled` does the
        rest back on the GUI thread.
        """
        why = boardusage.fetch()
        if why in ("expired", "unauthorized") \
                and time.time() - self._nudged_at > self.NUDGE_SEC:
            self._nudged_at = time.time()
            if boardusage.nudge():
                why = boardusage.fetch()
        # The hermes balance is its own fetch, with its own cache and its own
        # token (hermes' nous oauth, not the CLI's) — read on the same worker
        # so a clock/click/lifecycle kick refreshes both at once. Best effort:
        # a failure keeps the last nous reading and honesty is `hermes_proximity`'s.
        boardusage.fetch_nous()
        self._fetched.emit(why)

    @Slot(str)
    def _settled(self, why):
        # Logged only when it CHANGES: a machine with no network would otherwise
        # write a line a minute for as long as goetia is open.
        if why != self._why:
            self._why = why
            if why not in ("ok", "off"):
                print("usage: no live reading (%s) - drawing the last one, with "
                      "its age" % why, file=sys.stderr)
        self._busy = False
        self.busyChanged.emit()
        # Only for a refresh HE drove: the 60s and 300s clocks must not put a
        # sentence in the footer he did not ask for (§10.4 — a report is about
        # something that just happened at his hand).
        if self._by_hand:
            self._by_hand = False
            self.refreshed.emit(why)
        self.refresh()

    @Property(bool, notify=busyChanged)
    def busy(self):
        """A fetch is in flight. The meters draw it, so a click is never silent."""
        return self._busy

    @Slot()
    def refresh(self):
        stamps = []
        for p in (boardusage.CLAUDE_JSON, boardusage.LIVE_PATH):
            try:
                stamps.append(os.path.getmtime(p))
            except OSError:
                stamps.append(0)
        # The AGE moves even when the files do not, and a stale reading is
        # supposed to say so — so a re-read is skipped only while the rows come
        # out identical, never merely because the mtimes held still.
        rows = boardusage.readings()
        # The hermes spirit readout rides the same clocks (not a fetch — it is
        # a read of Hermes' own ledger, so there is nothing to fetch).
        hrows = boardusage.hermes_readings()
        # ...and so does the REAL-balance proximity — the one hermes "left"
        # figure that counts down from the nous account balance
        # (`boardusage.hermes_proximity`, itself a read of the nous.json cache
        # that `_work`'s `fetch_nous()` keeps fresh).
        hprox = boardusage.hermes_proximity()
        # ...and the TOP-UP balance beside it — the purchased pay-as-you-go pool
        # (`boardusage.hermes_topup`), read from the same nous.json cache.
        htopup = boardusage.hermes_topup()
        if (rows == self._rows and stamps == self._stamp
                and hrows == self._hrows and hprox == self._hprox
                and htopup == self._htopup):
            return
        rows_changed = rows != self._rows or stamps != self._stamp
        hrows_changed = hrows != self._hrows
        hprox_changed = hprox != self._hprox
        htopup_changed = htopup != self._htopup
        self._rows, self._stamp = rows, stamps
        self._hrows = hrows
        self._hprox = hprox
        self._htopup = htopup
        # Emit only the row kind that actually moved, so a nous-only change
        # never forces the Anthropic bars to redraw (and vice versa).
        if rows_changed:
            self.changed.emit()
        if hrows_changed:
            self.hchanged.emit()
        if hprox_changed:
            self.hproxChanged.emit()
        if htopup_changed:
            self.htopupChanged.emit()

    @Property("QVariantList", notify=changed)
    def rows(self):
        return self._rows

    #: The hermes spirit readout (one row per `boardusage.HERMES_WINDOWS`),
    #: real token/cost figures — see `boardusage.hermes_readings`.
    hchanged = Signal()

    @Property("QVariantList", notify=hchanged)
    def hrows(self):
        return self._hrows

    #: The hermes "how much I have left" signal — one dict
    #: (`boardusage.hermes_proximity`): the real nous account balance the
    #: readout counts down FROM, the % used when the portal publishes a monthly
    #: cap, and the honest unknown fallback when it has not been read yet.
    hproxChanged = Signal()

    @Property("QVariantMap", notify=hproxChanged)
    def hprox(self):
        return self._hprox

    #: The hermes TOP-UP signal — one dict (`boardusage.hermes_topup`): the
    #: purchased pay-as-you-go credit left (`purchased_credits_remaining`), the
    #: pool separate from the monthly subscription `hprox` counts down, and the
    #: honest unknown when the account has not been read on this host yet.
    htopupChanged = Signal()

    @Property("QVariantMap", notify=htopupChanged)
    def htopup(self):
        return self._htopup


class Spend(QObject):
    """The spend section — the Qt skin on `boardspend`.

    That module's docstring is authoritative for where the numbers come from and
    why the Claude dollar is a compute-WEIGHT (tokens x public rates), not a bill,
    while the hermes dollar is the provider's own estimate. This class only
    re-reads and notifies.

    A poll, not a watcher: the sources are session transcripts and Hermes'
    ledger, both rewritten by other programs on the order of minutes. `refresh()`
    re-runs `boardspend.snapshot()` and emits only on a real diff, so a poll that
    reads the same numbers is silent. The same lifecycle kick `Usage` takes moves
    it the moment an agent starts, finishes or dies (`follow`), with the 60s
    clock as the floor under it.

    OFF THE GUI THREAD, exactly like `Usage`, and for the same reason it was
    always true there: the read is over every session transcript on the machine
    and it is on a clock. It was synchronous here until 2026-08-02, and measured
    at **1,134 ms** — so goetia froze solid for over a second on every 60s poll,
    on every agent lifecycle change, AND once in the constructor before the
    window could be created at all, which is most of what made it slow to start.
    `boardspend._summary` cut the steady-state read to ~5 ms; this makes the
    FIRST one — and any pathological one — cost him nothing either.
    """

    changed = Signal()

    #: Private, emitted from the worker thread when a snapshot is ready; the
    #: result is applied by `_settled` back on the GUI thread. Nothing in the
    #: worker touches Qt state except this emit.
    _done = Signal()

    #: The idle re-read cadence. The figures move slowly; 60s is well inside
    #: "prompt" and each read is a snapshot over transcripts + one sqlite query.
    POLL_MS = 60000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = []
        self._totals = {}
        self._daily = []
        self._known = False
        self._estimated = False
        self._busy = False
        self._snap = None
        self._done.connect(self._settled)
        self._poll = QTimer(self)
        self._poll.setInterval(self.POLL_MS)
        self._poll.timeout.connect(self.refresh)
        self._poll.start()
        self.refresh()

    def follow(self, agents):
        """Re-read whenever an agent starts, finishes or dies — the same kick
        `Usage.follow` takes, so a completed dispatch shows up in the spend
        section while he is still looking at the card."""
        agents.lives.connect(self.refresh)

    @Slot()
    def refresh(self):
        """Kick a read, unless one is already in flight.

        A read in flight IS this refresh: the poll and the lifecycle kick can
        both land inside one snapshot, and starting a second worker would only
        read the same files twice. Returns immediately either way — the window
        never waits on this.
        """
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True,
                         name="board-spend").start()

    def _work(self):
        try:
            self._snap = boardspend.snapshot()
        except Exception as e:  # a read of other programs' files; never fatal
            print("spend: snapshot failed (%s)" % e, file=sys.stderr)
            self._snap = None
        self._done.emit()

    @Slot()
    def _settled(self):
        self._busy = False
        snap, self._snap = self._snap, None
        if snap is None:
            return
        models = snap.get("models", [])
        totals = snap.get("totals", {})
        daily = snap.get("daily", [])
        known = bool(snap.get("known"))
        estimated = bool(snap.get("estimated"))
        if (models == self._models and totals == self._totals
                and daily == self._daily
                and known == self._known and estimated == self._estimated):
            return
        self._models = models
        self._totals = totals
        self._daily = daily
        self._known = known
        self._estimated = estimated
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def models(self):
        return self._models

    @Property("QVariantList", notify=changed)
    def daily(self):
        """The trailing month, one entry per day (oldest -> newest): each a
        `{date,label,total,models}` — the token-per-day chart, and per day the
        per-family token breakdown the ranked bars rebind to on hover."""
        return self._daily

    @Property("QVariantMap", notify=changed)
    def totals(self):
        return self._totals

    @Property(bool, notify=changed)
    def known(self):
        return self._known

    @Property(bool, notify=changed)
    def estimated(self):
        return self._estimated

    @Slot(float, result=str)
    def fmtTokens(self, n):
        """`boardspend.fmt_tokens` for the QML side — 1.2M / 48k, one place.

        A QML `undefined` reaches a `float` slot as NaN, and that is an ORDINARY
        state here, not a bug to raise on: `totals` is an empty map until the
        first snapshot lands, and `{}["in"]` is undefined. Since that read moved
        off the GUI thread the window draws before the numbers exist, so every
        one of these six bindings evaluated once against nothing and `int(nan)`
        raised — six tracebacks per launch, all of them harmless and none of them
        legible. What the section SAYS in that gap is not this figure anyway:
        its `!Spend.known` row is already on screen saying so in words.
        """
        return boardspend.fmt_tokens(n if -1e18 < n < 1e18 else 0)


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


# ------------------------------------------------------------- the docs sync
# The store syncs on a five-minute timer (`home/srvs/nix-docs.nix`), which is
# the right cadence for an unattended writer and the wrong one for HIM: he
# answers something on `top`, closes the window, and it is up to five minutes
# before `book` can see it — and book's answers are just as stale here when he
# opens it. [his, 2026-07-29] *"i'd like the board to also sync after the
# program has been closed by the user."*
#
# So two kicks, at the two moments that are actually about him rather than about
# a clock: one on START, which PULLS what the other machine wrote before he
# reads a word of it, and one on QUIT, which PUSHES what he just answered. The
# timer stays exactly as it was and remains the guarantee; these only remove the
# wait either side of a session at the window.
#
# It is `systemctl --user start` of the unit that ALREADY EXISTS — not a second
# sync path, no git in this process, and nothing to unwind if the unit is not
# installed (a `book` mid-setup, a harness, a checkout somebody cloned to look
# at). `--no-block` is not a detail on the quit side: that unit fetches, merges
# and pushes over the network, and the window must not sit on screen waiting for
# it. Failure is silent BY DESIGN — this is an optimisation of when the timer
# would have run anyway, so the honest report for "it did not fire" is the one
# the timer already gives, not a dialog over a board he just closed.
SYNC_UNIT = "nix-docs-sync.service"


def sync_now(path):
    """Kick the docs sync, but only for a board that the docs sync carries.

    Same reading as `Board._derives`: a harness board, or a `board /tmp/x.md`,
    is not in that repo, and starting a unit that would commit and push an
    unrelated tree on its behalf is not this app's business.
    """
    inside = os.path.abspath(path).startswith(
        os.path.abspath(boardmove.LANDED_DOCS_REPO) + os.sep)
    if not inside or os.environ.get("BOARD_NO_SYNC"):
        return False
    return QProcess.startDetached(
        "systemctl", ["--user", "start", "--no-block", SYNC_UNIT])


# ---- the window icon ---------------------------------------------------------
# goetia's icon is the seal of Bael, first spirit of the Ars Goetia, redrawn as
# clean vector SVG in home/prog/board-files/ and installed into the hicolor
# theme by home/prog/board.nix (the desktop entry's `Icon=goetia` resolves the
# same file). ONE transparent variant, drawn in `currentColor` — the sigil IS
# the theme's foreground (body text = the accent, docs/DESIGN.md §3.1), not a
# baked light/dark hue, so it tracks the live palette instead of flipping
# between two files. QSvgRenderer has no API for the CSS current colour, so the
# token is substituted textually with the live `text` colour before the SVG is
# rendered onto a transparent pixmap; re-run on every theme change. A missing
# file or a Qt without SVG support degrades to the platform default icon.
ICON_FILE = (Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
             / "icons" / "hicolor" / "scalable" / "apps" / "goetia.svg")


def _window_icon(fg):
    try:
        data = ICON_FILE.read_bytes()
    except OSError:
        return QIcon()
    data = data.replace(b"currentColor", fg.name().encode("ascii"))
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return QIcon()
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("board")
    app.setDesktopFileName("board")

    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    settings = Settings()
    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()
    titlebar = Titlebar()
    board = Board(args[0] if args else None)
    agents = Agents()
    usage = Usage()
    # The bars move when the agent list does, not only on their own 60s clock.
    usage.follow(agents)
    spend = Spend()
    spend.follow(agents)

    # The window icon is the sigil recoloured to the live foreground, re-tinted
    # on every theme change. Set before the window is created so the first map
    # carries it.
    app.setWindowIcon(_window_icon(palette.text))
    palette.changed.connect(lambda: app.setWindowIcon(_window_icon(palette.text)))

    ctx.setContextProperty("Agents", agents)
    ctx.setContextProperty("Usage", usage)
    ctx.setContextProperty("Spend", spend)
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

    # Pull first, push last. The pull races the window coming up on purpose:
    # `Board` already watches the file and reloads on an atomic replace (§6.1,
    # invisibly), so whatever the sync brings in lands in the view by itself a
    # second or two later rather than delaying the window until the network
    # answers.
    sync_now(board.path)
    app.aboutToQuit.connect(lambda: sync_now(board.path))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
