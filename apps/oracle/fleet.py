"""The fleet: what chatter has spawned, what is still working, and on what.

WHY THIS IS A REAL WIDGET AND NOT QML
-------------------------------------
Everything else in chatter's Plasma face is QtQuick.Controls rendered through
the real QStyle by qqc2-desktop-style, so Oxygen's own code paints it. Measured
offscreen under Oxygen on 2026-08-25, one control is the exception: `ProgressBar`
paints ZERO pixels inside a `QQuickWidget`, in both determinate and busy modes,
while Button, Frame, Label, CheckBox, Slider, ScrollBar, TextField, ComboBox,
ItemDelegate and ToolButton all paint correctly. (`Meter.qml` had already
recorded the symptom for the context meter; this is the same hole.)

A busy indicator is the whole point of this pane — Oxygen's own statement of
"working, duration unknown" is the indeterminate progress bar, driven by its
busy-indicator animation engine at `ProgressBarBusyStepDuration`. So the pane is
a `QTreeView` in a `QDockWidget`, and the indicator is drawn by asking the style
itself for `CE_ProgressBar`. That also buys Oxygen's real tree: triangular
expanders at `ViewTriangularExpanderSize`, branch lines at
`ViewDrawTreeBranchLines`, alternating view rows, its header view and its
scrollbar — none of which a hand-built QML tree reproduces.

WHAT IT SHOWS
-------------
One tree, three levels, because a subagent is not a peer of the thing that
spawned it — it is a child of it:

    subagents · 7 spawned, 3 working
      ├─ librarian — find every album with no year tag        working
      │    ├─ read_file   aud/AGENTS.md
      │    └─ run_shell   find /run/media/lam/SSD/aud -name …
      └─ scribe — summarise the findings                      done
    background jobs · 1 working
      └─ ffmpeg remux                                          working

The counts he asked for are on the group rows, and they are two numbers rather
than one: SPAWNED is a claim (chatter emitted `agentStarted`), WORKING is an
observation (no `agentDone` yet). What each one is DOING is the activity child —
the tool it called and the thing it called it on, which is what makes a file a
subagent touched visible rather than merely "run_shell" over and over.
"""
import os

from PySide6.QtCore import QObject, Qt, QTimer, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QStyle,
                               QStyledItemDelegate, QStyleOptionProgressBar,
                               QTreeView)

#: Row state, on the row's first item. `RUNNING` is what earns a busy bar.
STATE_ROLE = Qt.UserRole + 1
RUNNING, DONE, FAILED, PLAIN = "working", "done", "failed", ""

#: Which column carries the indicator. Kept apart from the label column so a
#: long task never squeezes the bar to nothing.
COL_WHAT, COL_STATE, COL_ACTIVITY = 0, 1, 2

#: Tool-argument keys that name a THING, most specific first. A subagent's
#: `read_file {"path": "notes.md"}` should read as `notes.md`, not as
#: `read_file` for the fourth time.
_TARGET_KEYS = ("path", "file", "filename", "file_path", "target",
                "url", "query", "command", "cmd", "prompt", "name")


def tool_target(args, limit=60):
    """The thing a tool call is about, in one short string.

    Never the whole argument blob: a `run_shell` payload is a program and a
    `make_image` prompt is a paragraph, and this sits in a table column. A path
    keeps its last two segments — the basename alone is ambiguous the moment two
    directories hold a `main.py`, and the full path pushes everything else off
    the row.
    """
    if not isinstance(args, dict):
        return ""
    for key in _TARGET_KEYS:
        raw = args.get(key)
        if raw in (None, "", [], {}):
            continue
        text = " ".join(str(raw).split())
        if key in ("path", "file", "filename", "file_path") and "/" in text:
            parts = [p for p in text.split("/") if p]
            text = "/".join(parts[-2:])
        return text if len(text) <= limit else text[:limit - 1] + "…"
    return ""


class FleetModel(QStandardItemModel):
    """The tree behind the pane. Fed by signals; it polls nothing.

    Two group rows exist from the start and are never removed — a pane whose
    headings appear and vanish makes the whole tree jump every time a subagent
    is spawned, and an empty group saying "0 spawned" is information.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["what", "state", "doing"])
        self._agents = {}        # name -> its QStandardItem row anchor
        self.agents_group = self._group("subagents")
        self.jobs_group = self._group("background jobs")
        self._retune()

    # ------------------------------------------------------------- structure
    def _group(self, title):
        row = self._row(title, "", "")
        row[0].setData(PLAIN, STATE_ROLE)
        self.invisibleRootItem().appendRow(row)
        return row[0]

    @staticmethod
    def _row(what, state, activity):
        items = [QStandardItem(what), QStandardItem(state), QStandardItem(activity)]
        for it in items:
            it.setEditable(False)
        items[0].setData(PLAIN, STATE_ROLE)
        return items

    def _retune(self):
        """Restate both group headings from what is actually under them."""
        for group, noun in ((self.agents_group, "spawned"),
                            (self.jobs_group, "started")):
            total = group.rowCount()
            working = sum(1 for i in range(total)
                          if group.child(i, 0).data(STATE_ROLE) == RUNNING)
            base = group.text().split(" · ")[0]
            group.setText("%s · %d %s, %d working" % (base, total, noun, working))

    # ----------------------------------------------------------- subagents
    def agent_started(self, name, task, model):
        label = name if not task else "%s — %s" % (name, task)
        row = self._row(label, RUNNING, "")
        row[0].setData(RUNNING, STATE_ROLE)
        self.agents_group.appendRow(row)
        # LAST spawn wins the name. Two subagents of one definition are two
        # rows, and progress belongs to the one still running.
        self._agents[name] = row[0]
        self._retune()

    def agent_progress(self, name, round_, tool, target):
        anchor = self._agents.get(name)
        if anchor is None:
            return
        child = self._row("%d" % round_, "", "")
        child[1].setText(tool or "tool")
        child[2].setText(target or "")
        anchor.appendRow(child)
        # The parent's own activity column is the LATEST thing it did, so a
        # collapsed row still says what is happening.
        parent_row = anchor.row()
        self.agents_group.child(parent_row, COL_ACTIVITY).setText(
            ("%s  %s" % (tool or "tool", target or "")).strip())

    def agent_done(self, name, ok):
        anchor = self._agents.pop(name, None)
        if anchor is None:
            return
        state = DONE if ok else FAILED
        anchor.setData(state, STATE_ROLE)
        self.agents_group.child(anchor.row(), COL_STATE).setText(state)
        self._retune()

    # ---------------------------------------------------------------- jobs
    def set_jobs(self, rows):
        """Rebuild the jobs group from `Jobs.rows`, which is the whole list.

        A rebuild rather than a diff: the list is short, it arrives whole, and
        a diff here would be a second definition of what a job is.
        """
        self.jobs_group.removeRows(0, self.jobs_group.rowCount())
        for job in rows or []:
            state = str(job.get("state") or "")
            running = state in ("running", "starting")
            row = self._row(str(job.get("label") or "job"),
                            RUNNING if running else state, "")
            row[0].setData(RUNNING if running else
                           (FAILED if state in ("failed", "timeout") else DONE),
                           STATE_ROLE)
            self.jobs_group.appendRow(row)
        self._retune()

    def any_running(self):
        for group in (self.agents_group, self.jobs_group):
            for i in range(group.rowCount()):
                if group.child(i, 0).data(STATE_ROLE) == RUNNING:
                    return True
        return False


class BusyDelegate(QStyledItemDelegate):
    """Draws the state column of a running row as Oxygen's own busy bar.

    `QStyle.CE_ProgressBar` with `minimum == maximum` is what a busy
    `QProgressBar` is; asking the style to draw it here means Oxygen's own
    painting code runs, rather than an imitation of it in a delegate. The step
    comes from `ProgressBarBusyStepDuration` in the user's `oxygenrc`, which is
    the same clock Oxygen's busy-indicator engine runs on.
    """

    def __init__(self, parent=None, step_ms=50):
        super().__init__(parent)
        self.step = 0
        self.step_ms = max(10, int(step_ms))

    def paint(self, painter, option, index):
        state = index.sibling(index.row(), COL_STATE)
        first = index.sibling(index.row(), COL_WHAT)
        if index.column() != COL_STATE or first.data(STATE_ROLE) != RUNNING:
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, state)
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(2, 3, -2, -3)
        bar.palette = option.palette
        bar.state = option.state
        bar.minimum = 0
        bar.maximum = 0          # == minimum: this IS Qt's busy bar
        bar.progress = self.step
        bar.textVisible = False
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.CE_ProgressBar, bar, painter, option.widget)


class FleetPane(QObject):
    """The dock, its view, and the wiring from chatter's own signals.

    Nothing here polls and nothing here reads a transcript off disk: chatter
    already emits `agentStarted` / `agentProgress` / `agentDone` for every
    subagent it spawns, and `Jobs` emits `rowsChanged`. This pane is a second
    reader of signals that already existed.
    """

    def __init__(self, shell, ollama, jobs, oxygen_cfg=None, parent=None):
        super().__init__(parent)
        cfg = oxygen_cfg or {}
        self.model = FleetModel(self)
        self.view = QTreeView()
        self.view.setModel(self.model)
        self.view.setObjectName("fleetView")
        # Oxygen's own item view, asked for by name rather than imitated:
        # alternating rows, branch lines and the triangular expander are the
        # style's, and the focus rectangle is off because `ViewDrawFocusIndicator`
        # is off (kstyle/oxygen.kcfg).
        self.view.setAlternatingRowColors(True)
        self.view.setRootIsDecorated(True)
        self.view.setUniformRowHeights(True)
        self.view.setAllColumnsShowFocus(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.view.header().setStretchLastSection(True)
        self.view.expandAll()

        self.delegate = BusyDelegate(
            self.view, cfg.get("ProgressBarBusyStepDuration", 50))
        self.view.setItemDelegate(self.delegate)

        # The busy bars advance on Oxygen's own step, and ONLY while something
        # is actually running — a timer ticking against an idle tree is a
        # repaint of the whole pane fifty times a second for nothing.
        self._tick = QTimer(self)
        self._tick.setInterval(self.delegate.step_ms)
        self._tick.timeout.connect(self._advance)

        self.dock = shell.widget_dock("fleet", "Fleet", self.view,
                                      shortcut="Ctrl+Shift+F", sizes=(280, 0))

        ollama.agentStarted.connect(self._started)
        ollama.agentDone.connect(self._done)
        if hasattr(ollama, "agentProgressAt"):
            ollama.agentProgressAt.connect(self._progress)
        jobs.rowsChanged.connect(self._jobs_changed)
        self._jobs = jobs
        self._jobs_changed()

    # ------------------------------------------------------------- plumbing
    def _sync_timer(self):
        if self.model.any_running():
            if not self._tick.isActive():
                self._tick.start()
        elif self._tick.isActive():
            self._tick.stop()
            self.view.viewport().update()

    def _advance(self):
        # Oxygen's busy bar reads `progress` as a position, so any monotonic
        # counter animates it; the modulus keeps it from growing without bound
        # over a long render.
        self.delegate.step = (self.delegate.step + 1) % 1000
        self.view.viewport().update()

    @Slot(str, str, str)
    def _started(self, name, task, model):
        self.model.agent_started(name, task, model)
        self.view.expandAll()
        self._sync_timer()

    @Slot(str, int, str, str)
    def _progress(self, name, round_, tool, target):
        self.model.agent_progress(name, round_, tool, target)

    @Slot(str, bool, str)
    def _done(self, name, ok, block):
        self.model.agent_done(name, ok)
        self._sync_timer()

    @Slot()
    def _jobs_changed(self):
        self.model.set_jobs(self._jobs.rows)
        self._sync_timer()

    # ------------------------------------------------------------ harness
    def dump(self):
        """What the pane holds, as plain text — the offscreen harness's readout.

        The pane is never checked by looking at it (his screen is his), so a
        test asserts against this.
        """
        out = []
        for group in (self.model.agents_group, self.model.jobs_group):
            out.append(group.text())
            for i in range(group.rowCount()):
                out.append("  %s [%s] %s"
                           % (group.child(i, COL_WHAT).text(),
                              group.child(i, COL_STATE).text(),
                              group.child(i, COL_ACTIVITY).text()))
                anchor = group.child(i, 0)
                for j in range(anchor.rowCount()):
                    out.append("      %s %s %s"
                               % (anchor.child(j, COL_WHAT).text(),
                                  anchor.child(j, COL_STATE).text(),
                                  anchor.child(j, COL_ACTIVITY).text()))
        return "\n".join(out)
