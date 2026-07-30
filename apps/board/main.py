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
import boardmove  # noqa: E402  (beside this file)
import boardagents  # noqa: E402  (beside this file)
import boardwork  # noqa: E402  (beside this file)
import boardusage  # noqa: E402  (beside this file)

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
        self._path = os.path.abspath(os.path.expanduser(path or boardparse.BOARD_PATH))
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
        # OWN write settle before re-reading it.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
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

        board-watch runs on `top` AND on `book` now and `docs/board.md` syncs
        both ways every five minutes, so an unstamped answer is read by two
        watchers and worked by two agents on two checkouts of the same repos.
        The stamp is what makes the host an answer was typed on the host that
        works it. `boardparse.set_answer_host()` owns the line; this only
        decides which host, and that no answer means no stamp.

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
    # *"i should be able to clear the 'to do, when you feel like it' stuff if i
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
        self._undo = {"block": block, "before": after, "text": it.get("text", "")}
        self.undoChanged.emit()
        self.status.emit("removed - `put it back` is in the right-click menu")
        return True

    @Slot(result=bool)
    def undoRemove(self):
        u = self._undo
        if not u:
            return False
        try:
            out = boardparse.add_todo_block(self._doc["lines"], self._doc,
                                            u["block"], u["before"])
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

    IT WRITES NOTHING TO `board.md`. Everything here lives under
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._cards = []
        self._queued = []
        self._watcher = ""
        self._lives = None
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
    SYSTEMCTL = next((p for p in ("/run/current-system/sw/bin/systemctl",
                                  "/usr/bin/systemctl", "/bin/systemctl")
                      if os.path.exists(p)), "systemctl")

    def _ask_systemd(self):
        if self._proc.state() != QProcess.NotRunning:
            return
        self._proc.start(Agents.SYSTEMCTL,
                         ["--user", "show", "board-watch.service",
                          "-p", "ActiveState", "-p", "SubState", "-p", "Result"])

    def _on_systemctl(self, *_a):
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        text = boardagents.watcher_state(raw)["text"]
        if text != self._watcher:
            self._watcher = text
            self.changed.emit()

    def _row(self, a):
        return {
            # The id is what a message is ADDRESSED to and what the unit, the
            # log and the sidecar are named; `name` is what he READS. Both cross
            # over, and the card draws only the second.
            "id": a["id"], "name": a.get("name", ""),
            "kind": a["kind"], "title": a["title"],
            "where": a["where"], "state": a["state"],
            "running": a["state"] == "running",
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
        }

    @Slot()
    def refresh(self):
        self._rewatch()
        try:
            rows = [self._row(a) for a in boardagents.agents()]
            # ONE FLAT LIST, oldest first — `boardwork.cards()` is the one place
            # that decides the order, and it is birth and nothing else, so a
            # card does not move under his cursor when the agent changes phase
            # or stops. Queued tasks come after the live ones; they have no
            # birth yet.
            cards = [self._row(a) for a in boardwork.cards()]
            # id AND text: the row he right-clicks has to name the message it
            # is acting on, and its text is not a name (two identical sentences
            # are two messages) while its position is not one either — the next
            # drain shifts every index.
            queued = [{"id": boardagents.msg_id(m), "text": m["text"]}
                      for m in boardagents.pending()]
        except OSError:
            return
        # Who exists and what state each one is in — the only thing `lives` is
        # about. Built off `cards`, which is the superset (`boardwork.cards()`
        # pins the orchestrator and the queued tasks as well), and sorted so a
        # reordering is not a transition.
        lives = tuple(sorted((c["id"], c["state"]) for c in cards))
        if rows != self._rows or queued != self._queued or cards != self._cards:
            self._rows, self._queued, self._cards = rows, queued, cards
            self.changed.emit()
        if lives != self._lives:
            was, self._lives = self._lives, lives
            if was is not None:      # the first read is not a transition
                self.lives.emit()

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
        return [c for c in self._cards
                if c.get("kind") != boardagents.ORCHESTRATOR_KIND]

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
        return "%d minister%s" % (n, "" if n == 1 else "s")

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

    # ---- which model orchestrates -------------------------------------------
    # The dropdown beside the box. Both halves are thin on purpose: the list and
    # the choice live in `boardwork`, because `boardctl.py model` and the
    # spawners read the same two functions and a second copy of the list here
    # would be a second answer to "what may he pick".
    modelChanged = Signal()

    @Property("QVariantList", notify=modelChanged)
    def models(self):
        """`[{flag, label, current}]`, in the order the menu draws them."""
        cur = boardwork.orch_model()
        return [{"flag": f, "label": lab, "current": f == cur}
                for f, lab in boardwork.ORCH_MODELS]

    @Property(str, notify=modelChanged)
    def modelLabel(self):
        """What the closed control reads. Never the raw flag: `claude-opus-5` is
        a wire value and this is a line of his desktop's prose (§2)."""
        cur = boardwork.orch_model()
        return next((lab for f, lab in boardwork.ORCH_MODELS if f == cur), cur)

    @Slot(str, result=bool)
    def chooseModel(self, flag):
        """Write his choice. It reaches the NEXT orchestrator and no other: a
        session already running keeps the model it started with, which is his
        rule for a change made mid-run stated as the mechanism rather than
        enforced on top of one."""
        try:
            boardwork.set_orch_model(flag)
        except (ValueError, OSError):
            return False
        self.modelChanged.emit()
        return True

    @Property("QVariantList", notify=changed)
    def queued(self):
        return self._queued

    @Property(str, notify=changed)
    def watcher(self):
        return self._watcher

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
        return "in the inbox - an orchestrator works out who does what"

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
            return ("that one has already gone to an agent - "
                    "nothing removed")
        return "taken off the queue - the text is kept, not deleted"

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
            return ("that one has already gone to an agent - "
                    "it got the old wording")
        return "queued note rewritten - the next minister reads this"


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
    """

    changed = Signal()
    #: A fetch finished, with its reason word. Emitted from the worker thread —
    #: a queued connection is what carries it back to the GUI one.
    _fetched = Signal(str)

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
        self._stamp = None
        self._busy = False
        self._fetched_at = 0.0
        self._nudged_at = 0.0
        self._why = "ok"
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

    def _start(self, min_gap):
        """Fetch on a worker thread, unless one is running or it is too soon."""
        now = time.time()
        if self._busy or now - self._fetched_at < min_gap:
            return
        self._busy, self._fetched_at = True, now
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
        self.refresh()

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
        if rows == self._rows and stamps == self._stamp:
            return
        self._rows, self._stamp = rows, stamps
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def rows(self):
        return self._rows


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
    agents = Agents()
    usage = Usage()
    # The bars move when the agent list does, not only on their own 60s clock.
    usage.follow(agents)

    ctx.setContextProperty("Agents", agents)
    ctx.setContextProperty("Usage", usage)
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
