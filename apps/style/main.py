#!/usr/bin/env python3
"""style — the live desktop appearance control centre.

The program deliberately owns only a *draft*.  The session ``deskstyle``
service is the one authority that changes a wallpaper, installs its prepared
colour scheme, and waits for applications to repaint.  Keeping that split
means the UI can never claim that a click has completed a theme change merely
because it wrote a settings file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFile, QFileSystemWatcher, QObject, Property, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent


HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
sys.path.insert(0, str(HERE.parent / "pylib"))

from deskstyle import DeskStyle  # noqa: E402
from kdetheme import is_plasma, theme_source  # noqa: E402
import kdeshell  # noqa: E402


SERVICE = "org.lam.DeskStyle1"
OBJECT_PATH = "/org/lam/DeskStyle1"
INTERFACE = "org.lam.DeskStyle1"
IMAGE_SUFFIXES = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


def wallpaper_dir() -> Path:
    """The same writable collection used by the panel's wallpaper picker."""
    return Path(os.environ.get("DESKSTYLE_WALLPAPER_DIR") or (Path.home() / "Pictures" / "Wallpapers"))


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "deskstyle"


def active_profile_path() -> Path:
    return Path(os.environ.get("DESKSTYLE_PROFILE") or (state_dir() / "active-profile.json"))


def _thumbnail(path: Path) -> Path:
    key = hashlib.md5(str(path.resolve()).encode("utf-8")).hexdigest()
    thumbnail = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "wal" / "thumbs" / f"{key}.jpg"
    return thumbnail if thumbnail.is_file() else path


def _free_destination(root: Path, source: Path) -> Path:
    """Return a collision-free local filename without overwriting anything."""
    candidate = root / source.name
    number = 2
    while candidate.exists():
        candidate = root / f"{source.stem}-{number}{source.suffix.lower()}"
        number += 1
    return candidate


def _active_wallpaper(profile: Path) -> str:
    """Read only the controller's atomically-written active identity."""
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
        value = data["wallpaper"]["path"]
        return str(Path(value).resolve()) if isinstance(value, str) else ""
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _active_scheme(profile: Path) -> str:
    reader = shutil.which("kreadconfig6")
    if reader:
        try:
            result = subprocess.run([reader, "--file", "kdeglobals", "--group", "General",
                                     "--key", "ColorScheme"], text=True, capture_output=True,
                                    timeout=5, check=False)
            value = result.stdout.strip()
            if value in {"OxygenDarkFlat", "OxygenLightFlat", "OxygenMixed"}:
                return value
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
        value = data["colorScheme"]["name"]
        return value if value in {"OxygenDarkFlat", "OxygenLightFlat", "OxygenMixed"} else "OxygenDarkFlat"
    except (OSError, ValueError, KeyError, TypeError):
        return "OxygenDarkFlat"


def _picker_active_wallpaper(root: Path) -> str:
    """Compatibility read for the panel's pre-controller active selection."""
    try:
        selected = (root / ".current-wallpaper").read_text(encoding="utf-8").strip()
        candidate = (root / selected).resolve()
        return str(candidate) if candidate.is_file() else ""
    except OSError:
        return ""


from nativepalette import session_palette


@session_palette
class Palette(QObject):
    """The app's live palette reader, matching the other Qt applications."""

    changed = Signal()
    _defaults = {"bg": "#000000", "bgAlt": "#120b08", "border": "#382216",
                 "accent": "#cc4400", "dim": "#54382a", "text": "#ffffff",
                 "textDim": "#8c5438", "highlight": "#21140d", "ok": "#e08e65",
                 "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457"}

    def __init__(self, _path: Path, parent=None):
        # The style controller's job is authoritative; the main app needs the
        # same bindings as every other app, but no separate palette writer.
        from PySide6.QtCore import QFileSystemWatcher
        super().__init__(parent)
        self._path = Path(_path)
        self._colors = dict(self._defaults)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._reload)
        self._watcher.directoryChanged.connect(self._reload)
        self._watch()
        self._reload()

    def _watch(self):
        known = set(self._watcher.files()) | set(self._watcher.directories())
        for candidate in (self._path.parent, self._path):
            if candidate.exists() and str(candidate) not in known:
                self._watcher.addPath(str(candidate))

    def _reload(self, *_unused):
        self._watch()
        try:
            import re
            text = self._path.read_text(encoding="utf-8")
            colors = dict(self._defaults)
            for name, value in re.findall(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', text):
                if name in colors:
                    colors[name] = value
        except OSError:
            return
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _color(self, name):
        return QColor(self._colors[name])

    bg = Property(QColor, lambda self: self._color("bg"), notify=changed)
    bgAlt = Property(QColor, lambda self: self._color("bgAlt"), notify=changed)
    border = Property(QColor, lambda self: self._color("border"), notify=changed)
    accent = Property(QColor, lambda self: self._color("accent"), notify=changed)
    dim = Property(QColor, lambda self: self._color("dim"), notify=changed)
    text = Property(QColor, lambda self: self._color("text"), notify=changed)
    textDim = Property(QColor, lambda self: self._color("textDim"), notify=changed)
    highlight = Property(QColor, lambda self: self._color("highlight"), notify=changed)
    ok = Property(QColor, lambda self: self._color("ok"), notify=changed)
    warn = Property(QColor, lambda self: self._color("warn"), notify=changed)
    crit = Property(QColor, lambda self: self._color("crit"), notify=changed)
    info = Property(QColor, lambda self: self._color("info"), notify=changed)


class Appearance(QObject):
    """Wallpaper draft plus the asynchronous D-Bus controller state."""

    wallpapersChanged = Signal()
    selectionChanged = Signal()
    activeChanged = Signal()
    statusChanged = Signal()
    applyingChanged = Signal()
    errorChanged = Signal()

    def __init__(self, root: Path | None = None, profile: Path | None = None, parent=None):
        super().__init__(parent)
        self._root = root or wallpaper_dir()
        self._profile = profile or active_profile_path()
        self._items: list[dict[str, str]] = []
        self._active = _active_wallpaper(self._profile) or _picker_active_wallpaper(self._root)
        self._scheme = _active_scheme(self._profile)
        self._draft = self._active
        self._status = "ready" if self._active else "choose a wallpaper"
        self._error = ""
        self._applying = False
        self._generation = 0
        self._pending_reply = None
        self._pending_delete: list[str] = []
        self._native_progress = False
        self._status_path = state_dir() / "status.json"
        self._status_watcher = QFileSystemWatcher(self)
        self._status_watcher.fileChanged.connect(self._status_file_changed)
        self._status_watcher.directoryChanged.connect(self._status_file_changed)
        self._watch_status()
        self.refresh()

    @Property("QVariantList", notify=wallpapersChanged)
    def wallpapers(self):
        return self._items

    @Property(str, notify=selectionChanged)
    def draftPath(self):
        return self._draft

    @Property(str, notify=activeChanged)
    def activePath(self):
        return self._active

    @Property(str, notify=activeChanged)
    def activeScheme(self):
        return self._scheme

    @Property(bool, notify=selectionChanged)
    def hasDraft(self):
        return bool(self._draft) and self._draft != self._active

    @Property(bool, notify=applyingChanged)
    def applying(self):
        return self._applying

    @Property(bool, notify=applyingChanged)
    def nativeProgress(self):
        return self._native_progress

    def use_native_progress(self) -> None:
        self._native_progress = True


    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @Slot()
    def refresh(self):
        items = []
        try:
            files = sorted(self._root.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            files = []
        for path in files:
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                resolved = str(path.resolve())
                items.append({"path": resolved, "thumbnail": str(_thumbnail(path)), "name": path.stem})
        if items != self._items:
            self._items = items
            self.wallpapersChanged.emit()

    @Slot("QVariantList")
    def importFiles(self, urls):
        if self._applying:
            return
        added = 0
        errors = []
        self._root.mkdir(parents=True, exist_ok=True)
        for value in urls:
            source = Path(value.toLocalFile() if hasattr(value, "toLocalFile") else str(value)).resolve()
            if source.parent == self._root.resolve():
                continue
            if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
                errors.append(source.name or "unsupported file")
                continue
            try:
                shutil.copy2(source, _free_destination(self._root, source))
                added += 1
            except OSError as exc:
                errors.append(f"{source.name}: {exc}")
        self.refresh()
        self._error = ", ".join(errors)
        self._status = f"added {added}" if added else ("not added" if errors else "ready")
        self.errorChanged.emit()
        self.statusChanged.emit()

    def _trash(self, path: Path) -> str:
        try:
            return "" if QFile.moveToTrash(str(path)) else f"not removed: {path.name}"
        except OSError as exc:
            return f"not removed: {path.name}: {exc}"

    @Slot(str)
    def removeWallpaper(self, path):
        self.removeWallpapers([path])

    @Slot("QVariantList")
    def removeWallpapers(self, paths):
        if self._applying:
            return
        offered = [item["path"] for item in self._items]
        selected = []
        for path in paths:
            resolved = str(Path(path).resolve())
            if resolved in offered and resolved not in selected:
                selected.append(resolved)
        if not selected:
            return
        if self._active in selected:
            replacements = [candidate for candidate in offered if candidate not in selected]
            if not replacements:
                self._error = "add another wallpaper first"
                self.errorChanged.emit()
                return
            index = offered.index(self._active)
            replacement = min(replacements, key=lambda candidate: abs(offered.index(candidate) - index))
            self._pending_delete = selected
            self._draft = replacement
            self.selectionChanged.emit()
            self.apply()
            return
        errors = [error for path in selected if (error := self._trash(Path(path)))]
        self._error = ", ".join(errors)
        if self._draft in selected:
            self._draft = self._active
            self.selectionChanged.emit()
        removed = len(selected) - len(errors)
        self._status = f"moved {removed} to trash" if len(selected) > 1 else "moved to trash"
        self.errorChanged.emit()
        self.statusChanged.emit()
        self.refresh()

    @Slot(str)
    def select(self, path):
        if self._applying:
            return
        resolved = str(Path(path).resolve())
        if any(item["path"] == resolved for item in self._items) and resolved != self._draft:
            self._draft = resolved
            self._error = ""
            self.selectionChanged.emit()
            self.errorChanged.emit()

    @Slot()
    def cancel(self):
        if self._applying:
            return
        if self._draft != self._active:
            self._draft = self._active
            self._status = "ready" if self._active else "choose a wallpaper"
            self.selectionChanged.emit()
            self.statusChanged.emit()

    @Slot()
    def apply(self):
        if self._applying or not self.hasDraft:
            return
        try:
            from PySide6.QtDBus import QDBusInterface, QDBusPendingCallWatcher
            interface = QDBusInterface(SERVICE, OBJECT_PATH, INTERFACE)
            if not interface.isValid():
                raise RuntimeError("appearance service is unavailable")
            self._applying = True
            self._error = ""
            self._status = "submitting"
            self.applyingChanged.emit()
            self.errorChanged.emit()
            self.statusChanged.emit()
            pending = interface.asyncCallWithArgumentList("Apply", [self._draft])
            self._pending_reply = QDBusPendingCallWatcher(pending, self)
            self._pending_reply.finished.connect(self._apply_reply)
        except Exception as exc:
            self._applying = False
            self._error = str(exc)
            self._status = "not applied"
            self.applyingChanged.emit()
            self.errorChanged.emit()
            self.statusChanged.emit()

    @Slot(str)
    def selectScheme(self, scheme):
        if self._applying or scheme == self._scheme:
            return
        if scheme not in {"OxygenDarkFlat", "OxygenLightFlat", "OxygenMixed"}:
            return
        try:
            from PySide6.QtDBus import QDBusInterface, QDBusPendingCallWatcher
            interface = QDBusInterface(SERVICE, OBJECT_PATH, INTERFACE)
            if not interface.isValid():
                raise RuntimeError("appearance service is unavailable")
            self._applying = True
            self._error = ""
            self._status = "submitting"
            self.applyingChanged.emit()
            self.errorChanged.emit()
            self.statusChanged.emit()
            pending = interface.asyncCallWithArgumentList("SetScheme", [scheme])
            self._pending_reply = QDBusPendingCallWatcher(pending, self)
            self._pending_reply.finished.connect(self._apply_reply)
        except Exception as exc:
            self._applying = False
            self._error = str(exc)
            self._status = "not applied"
            self.applyingChanged.emit()
            self.errorChanged.emit()
            self.statusChanged.emit()

    @Slot(object)
    def _apply_reply(self, watcher):
        reply = watcher.reply()
        watcher.deleteLater()
        self._pending_reply = None
        if reply.type().name != "ReplyMessage" or not reply.arguments():
            self._applying = False
            self._error = reply.errorMessage() or "appearance service rejected the request"
            self._status = "not applied"
            self.applyingChanged.emit()
            self.errorChanged.emit()
            self.statusChanged.emit()
            return
        self._generation = int(reply.arguments()[0])
        self._status = "queued"
        self.statusChanged.emit()
        self._read_status()

    def _watch_status(self):
        known = set(self._status_watcher.files()) | set(self._status_watcher.directories())
        for candidate in (self._status_path.parent, self._status_path):
            if candidate.exists() and str(candidate) not in known:
                self._status_watcher.addPath(str(candidate))

    @Slot(str)
    def _status_file_changed(self, _path):
        self._watch_status()
        self._read_status()

    def _read_status(self):
        try:
            status = json.loads(self._status_path.read_text(encoding="utf-8"))
            if int(status.get("generation", 0)) != self._generation:
                return
        except (OSError, ValueError, TypeError):
            return
        state = str(status.get("state", ""))
        if state == "complete":
            self._completed(self._generation, str(status.get("profileHash", "")),
                            bool(status.get("allLive", False)))
        elif state == "failed":
            self._failed(self._generation, str(status.get("detail", "apply failed")))
        elif state:
            self._status = str(status.get("detail") or state.replace("-", " "))
            self.statusChanged.emit()

    @Slot(int, str, float, str)
    def _progress(self, generation, phase, _fraction, detail):
        if generation != self._generation:
            return
        self._status = detail or phase.replace("-", " ")
        self.statusChanged.emit()

    @Slot(int, str, bool)
    def _completed(self, generation, _digest, all_live):
        if generation != self._generation:
            return
        self._active = _active_wallpaper(self._profile) or self._draft
        self._scheme = _active_scheme(self._profile)
        self._draft = self._active
        self._applying = False
        removed = self._pending_delete
        self._pending_delete = []
        remove_errors = [error for path in removed if (error := self._trash(Path(path)))]
        self._error = ", ".join(remove_errors)
        removed_count = len(removed) - len(remove_errors)
        removed_status = (f"moved {removed_count} to trash" if len(removed) > 1 else "moved to trash")
        self._status = (removed_status if removed and not remove_errors
                        else ("live" if all_live else "live; apps deferred"))
        self.refresh()
        self.activeChanged.emit()
        self.selectionChanged.emit()
        self.applyingChanged.emit()
        self.statusChanged.emit()
        self.errorChanged.emit()

    @Slot(int, int)
    def _superseded(self, generation, by_generation):
        if generation != self._generation:
            return
        self._generation = by_generation
        self._status = "replaced by the newest selection"
        self.statusChanged.emit()

    @Slot(int, str)
    def _failed(self, generation, message):
        if generation != self._generation:
            return
        self._applying = False
        if self._pending_delete:
            self._pending_delete = []
            self._draft = self._active
            self.selectionChanged.emit()
        self._status = "not applied"
        self._error = message
        self.applyingChanged.emit()
        self.statusChanged.emit()
        self.errorChanged.emit()


class ApplyProgressDialog:
    """A small real KDE-styled dialog for Plasma's appearance transaction."""

    def __init__(self, parent, appearance: Appearance) -> None:
        from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

        self._appearance = appearance
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("applying")
        self.dialog.setWindowModality(Qt.WindowModal)
        self.dialog.setModal(True)
        self.dialog.setMinimumWidth(320)
        self.dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        self.label = QLabel(self.dialog)
        self.label.setWordWrap(True)
        self.progress = QProgressBar(self.dialog)
        self.progress.setRange(0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        appearance.applyingChanged.connect(self.sync)
        appearance.statusChanged.connect(self.sync)
        self.sync()

    def sync(self) -> None:
        self.label.setText(self._appearance.status)
        if self._appearance.applying:
            self.dialog.show()
            self.dialog.raise_()
        else:
            self.dialog.hide()


def main() -> int:
    kdeshell.pin_controls_style()
    app = kdeshell.make_app(sys.argv, "style")
    plasma = is_plasma()
    shell = kdeshell.shell("style", size=(980, 700),
                           min_size=(560, 420)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        kdeshell.select_plasma_files(engine)
    context = engine.rootContext()
    palette = Palette(theme_source(Path.home() / ".config" / "quickshell" / "Theme.qml"), app)
    style = DeskStyle(parent=app)
    appearance = Appearance(parent=app)
    if plasma:
        appearance.use_native_progress()
    context.setContextProperty("WalPalette", palette)
    context.setContextProperty("DeskStyle", style)
    context.setContextProperty("Appearance", appearance)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = component.create()
    if theme is None:
        print("Theme.qml failed:\n" + component.errorString(), file=sys.stderr)
        return 1
    theme.setParent(app)
    context.setContextProperty("Theme", theme)
    if plasma:
        if not shell.load(QML / "Root.qml"):
            print("Root.qml failed:\n" + "\n".join(shell.errors()), file=sys.stderr)
            return 1
        shell.show(return_handle=False)
        shell.apply_progress = ApplyProgressDialog(shell.window, appearance)
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
