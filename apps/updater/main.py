#!/usr/bin/env python3
"""updater — the desktop's GUI for this flake's package updates.

The eleventh vendored app. "Packages" on this machine are really flake
*inputs*: `nixpkgs` tracks nixos-unstable and rolls, while `hyprland`,
`hyprland-air` and `nixpkgs-quickshell` are deliberately PINNED to exact
revisions (flake.nix says why at length) and a pin bump is on his ask-first
list. So this app treats the three pins as guarded and never bumps one as part
of "update everything".

Three jobs, matching what he asked for:

  * CHECK — run the existing read-only preview `tools/nix-upgradable.sh`, which
    hardlink-copies the tree, `nix flake update`s the COPY (the real flake.lock
    is sha256'd and never touched) and diffs the resulting closures. Its output
    is streamed into the log pane verbatim; this app reinvents none of it.
  * UPDATE EVERYTHING — `nix flake update <every non-pinned input>` followed by
    this host's rebuild wrapper. The pinned three are excluded by construction,
    because a bare `nix flake update` would move them too.
  * UPDATE ONE — `nix flake update <input>` + rebuild, for a single input. A
    pinned input is allowed here but behind a second, explicit confirmation
    that says it is ask-first and what it costs.

Applying is `nix flake update` (which rewrites the real flake.lock) then the
wrapper — `sudo rebuild-top` on top, `rebuild-air` on book — both of which own
preflight and the shared rebuild lock. The app is honest about the cost before
it runs: a hyprland/quickshell move means a from-source build on book and no
live plugin hot-swap (next login).

Look and behaviour come from docs/DESIGN.md: pixel font at the desktop size
through DeskStyle, wal palette watched out of the panel's Theme.qml, motion and
kinetic scrolling from qmlcommon, chrome in the hyprvtb titlebar through
pylib/vtbclient.py. Nothing here draws its own titlebar strip.

State (`~/.local/state/updater/state.json`) is the app's own (docs/DESIGN.md
§14). It never commits flake.lock — that stays his to review and push.
"""
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import (QObject, Slot, Signal, Property, QProcess,
                            QFileSystemWatcher)
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtCore import QUrl

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402
from deskstyle import DeskStyle  # noqa: E402
from kdetheme import theme_source  # noqa: E402  (pylib; the KDE global theme in a Plasma session)

REPO = Path(os.environ.get("NIX_UPGRADABLE_REPO", str(Path.home() / "nix")))

#: The three inputs frozen on purpose (flake.nix). Bumping one is on his
#: ask-first list, so they are never part of "update everything" and a
#: single-input bump of one asks a second time.
PINNED = {"hyprland", "hyprland-air", "nixpkgs-quickshell"}

STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) \
    / "updater" / "state.json"


def is_book():
    return platform.machine().lower().startswith("aarch64")


def rebuild_cmd():
    """This host's rebuild wrapper — both own preflight and the shared lock."""
    if is_book():
        return ["rebuild-air"]
    return ["sudo", "rebuild-top"]


# ---- the wallpaper palette (mirrors reader/viewer/filer verbatim) -----------
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """Live wallpaper palette, parsed from the panel's Theme.qml and watched."""

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
            self._watcher.addPath(d)
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
    """hyprvtb app-button bridge — updater's chrome (check, full check, update
    all, stop) is drawn by the compositor in the titlebar, not in QML."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit)

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", ""))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Inputs(QObject):
    """The flake's inputs, read from flake.lock — the fast, always-accurate
    picture of what is locked right now. Watched, so an external `nix flake
    update` (or this app's own apply) refreshes the list in place."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._lock = str(REPO / "flake.lock")
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        if os.path.isdir(str(REPO)):
            self._watcher.addPath(str(REPO))
        self._rewatch()
        self._reload()

    def _rewatch(self):
        if os.path.exists(self._lock) and self._lock not in self._watcher.files():
            self._watcher.addPath(self._lock)

    def _on_change(self, _):
        self._rewatch()
        self._reload()

    def _reload(self):
        items = []
        try:
            lock = json.loads(Path(self._lock).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._items = items
            self.changed.emit()
            return
        now = time.time()
        nodes = lock.get("nodes", {})
        roots = nodes.get("root", {}).get("inputs", {})
        for name in sorted(roots):
            key = roots[name]
            if isinstance(key, list):
                items.append({"name": name, "rev": "", "date": "",
                              "age": -1, "follows": key[0] if key else "",
                              "pinned": name in PINNED, "updatable": False})
                continue
            locked = nodes.get(key, {}).get("locked") or {}
            rev = (locked.get("rev") or locked.get("ref") or "")
            lm = locked.get("lastModified") or 0
            date = time.strftime("%Y-%m-%d", time.gmtime(lm)) if lm else ""
            age = int((now - lm) / 86400) if lm else -1
            items.append({"name": name, "rev": rev[:10], "date": date,
                          "age": age, "follows": "",
                          "pinned": name in PINNED, "updatable": bool(rev)})
        self._items = items
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def items(self):
        return self._items

    @Slot(result="QStringList")
    def nonPinnedNames(self):
        return [i["name"] for i in self._items
                if not i["pinned"] and i.get("updatable")]

    @Slot()
    def refresh(self):
        self._reload()


class Runner(QObject):
    """One command queue, run one QProcess at a time, streaming merged output.

    A "job" is a label plus a list of steps (each an argv list). Steps run in
    order and stop on the first non-zero exit. `busy` gates every action in QML
    so two jobs can never overlap and the pinned confirm cannot be raced."""

    output = Signal(str)          # a chunk of text for the log pane
    started = Signal(str)         # job label
    finished = Signal(str, bool)  # job label, ok
    busyChanged = Signal()
    #: parsed per-input package delta ready: input name, list of
    #: {name, old, new} rows from `nix store diff-closures`.
    packagesReady = Signal(str, "QVariantList")

    #: A diff-closures/drv-closure-diff line: "<pkg>: <old> -> <new>[, ±size]".
    _DIFF_RE = re.compile(r"^\s*(\S.*?):\s+(.+?)\s+->\s+(.+?)\s*$")
    _DIFF_MARK = "== drv-closure diff"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._steps = []
        self._label = ""
        self._ok = True
        self._capture_name = ""   # input name when this job is a per-row preview
        self._capture_buf = ""

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._proc is not None

    # ---- the three public actions ----

    @Slot(bool)
    def check(self, full):
        args = [str(REPO / "tools" / "nix-upgradable.sh")]
        if not full:
            args.append("--no-build")
        label = "check" + (" (full)" if full else "")
        self._run(label, [args])

    @Slot("QStringList")
    def updateInputs(self, names):
        """Update the named inputs (all non-pinned for 'update everything', or a
        single one), then rebuild through this host's wrapper."""
        names = [n for n in names if n]
        if not names:
            return
        upd = ["nix", "flake", "update"] + names
        label = "update " + (", ".join(names) if len(names) <= 3
                             else "%d inputs" % len(names))
        self._run(label, [upd, rebuild_cmd()])

    @Slot(str)
    def previewInput(self, name):
        """Per-input package delta: `nix-upgradable.sh --input <name>` diffs the
        two toplevel drv CLOSURES by evaluation alone (docs/agents/
        updater-per-input-diff.md) — forcing a drvPath writes .drv files but
        builds nothing, so this costs ~15s and no download, and it still answers
        when the new system does not build. Still on-demand only (never on list
        load) so the run and its cost stay visible in the log. The parsed result
        is emitted on packagesReady(name, rows)."""
        name = (name or "").strip()
        if not name:
            return
        args = [str(REPO / "tools" / "nix-upgradable.sh"), "--input", name]
        self._run("diff " + name, [args], capture_name=name)

    @Slot()
    def stop(self):
        if self._proc is not None:
            self._steps = []
            self.output.emit("\n-- stop requested --\n")
            self._proc.terminate()

    # ---- the machinery ----

    def _run(self, label, steps, capture_name=""):
        if self._proc is not None:
            return
        self._label = label
        self._steps = list(steps)
        self._ok = True
        self._capture_name = capture_name
        self._capture_buf = ""
        self.output.emit("\n===== %s =====\n$ cd %s\n" % (label, REPO))
        self.started.emit(label)
        self._next()

    def _next(self):
        if not self._steps:
            self._done(True)
            return
        step = self._steps.pop(0)
        self.output.emit("$ " + " ".join(step) + "\n")
        p = QProcess(self)
        p.setWorkingDirectory(str(REPO))
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(self._step_finished)
        p.errorOccurred.connect(self._error)
        self._proc = p
        self.busyChanged.emit()
        p.start(step[0], step[1:])

    def _read(self):
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            if self._capture_name:
                self._capture_buf += data
            self.output.emit(data)

    def _parse_diff(self, text):
        """Pull the `pkg: old -> new` rows out of the diff-closures section."""
        rows = []
        seen = False
        for line in text.splitlines():
            if self._DIFF_MARK in line:
                seen = True
                continue
            if not seen:
                continue
            if line.startswith("=====") or line.startswith("read-only"):
                break
            m = self._DIFF_RE.match(line)
            if not m:
                continue
            new = m.group(3).split(",")[0].strip()  # drop the ", ±size" suffix
            rows.append({"name": m.group(1).strip(),
                         "old": m.group(2).strip(), "new": new})
        return rows

    def _error(self, _):
        # start failed (binary missing etc.) — finished may not fire.
        if self._proc is not None:
            self.output.emit("\n-- could not start: %s --\n"
                             % self._proc.errorString())

    def _step_finished(self, code, _status):
        self._read()
        self._proc = None
        self.busyChanged.emit()
        if code != 0:
            self.output.emit("\n-- exit %d --\n" % code)
            self._done(False)
            return
        if self._steps:
            self._next()
        else:
            self._done(True)

    def _done(self, ok):
        self._ok = ok
        if self._capture_name:
            rows = self._parse_diff(self._capture_buf) if ok else []
            self.packagesReady.emit(self._capture_name, rows)
            self._capture_name = ""
            self._capture_buf = ""
        self.output.emit("\n===== %s: %s =====\n"
                         % (self._label, "done" if ok else "failed"))
        self.finished.emit(self._label, ok)


class Settings(QObject):
    """updater's own persisted UI state (docs/DESIGN.md §14)."""

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
        self._data[key] = val
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass


class Host(QObject):
    """A couple of host facts QML shows in the cost warning."""

    @Property(bool, constant=True)
    def isBook(self):
        return is_book()

    @Property(str, constant=True)
    def rebuild(self):
        return " ".join(rebuild_cmd())


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("updater")
    app.setDesktopFileName("updater")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()
    titlebar = Titlebar()
    inputs = Inputs()
    runner = Runner()
    settings = Settings()
    host = Host()

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Inputs", inputs)
    ctx.setContextProperty("Runner", runner)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Host", host)

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
