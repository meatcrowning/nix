#!/usr/bin/env python3
"""Render the KDE style's window background as one screen-sized PNG.

The panels crop this image at their global coordinates.  Rendering a real,
never-shown QWidget is the same mechanism apps/pylib/kdeshell.py uses for the
pixel-exact background behind our Plasma QML apps; it does not map a window or
interact with the desktop.
"""

from pathlib import Path
import hashlib
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPalette, QRegion
from PySide6.QtWidgets import QApplication, QWidget

def render_surface(width: int, height: int, palette: QPalette) -> QImage:
    """Render an actual Oxygen styled top-level widget, never mapping it."""
    proxy = QWidget()
    proxy.setAttribute(Qt.WA_StyledBackground, True)
    proxy.setPalette(palette)
    proxy.resize(width, height)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    proxy.render(image, QPoint(), QRegion(0, 0, width, height),
                 QWidget.DrawWindowBackground)
    return image


def publish_generation(state: Path, target: Path) -> None:
    """Publish the image token as a directory-model row replacement."""
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    serial = state / f"plasma-panel-surface.{digest}.serial"
    if serial.exists():
        return
    # FolderListModel does not reliably emit dataChanged when only metadata on
    # one fixed filename moves.  Removing the prior generation and adding this
    # content-named row forces count/fileName to change in the running panel.
    # The name is already content-unique and Panel.qml never reads its body,
    # so create it directly.  QFileSystemWatcher missed the previous hidden
    # temporary -> matching-name rename; a matching file creation is the event
    # FolderListModel reliably turns into an inserted row.
    serial.write_text(digest + "\n")
    for old in state.glob("plasma-panel-surface.*.serial"):
        if old != serial:
            old.unlink()
    # Retire the fixed-name token used by the broken metadata-only watcher.
    legacy = state / "plasma-panel-surface.serial"
    if legacy.exists():
        legacy.unlink()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if app.style().objectName().lower() != "oxygen":
        print(f"refusing non-Oxygen style: {app.style().objectName()}", file=sys.stderr)
        return 1
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1
    rect = screen.geometry()
    width, height = max(1, rect.width()), max(1, rect.height())

    # Oxygen only draws this primitive for a real top-level QWidget.  It also
    # treats an unseen window as inactive unless every colour group is pinned;
    # copy Active into every group, exactly as kdeshell's pixel-exact provider
    # does for the application surfaces this must match.
    palette = QPalette(app.palette())
    for role in QPalette.ColorRole:
        if role == QPalette.NColorRoles:
            continue
        colour = app.palette().color(QPalette.Active, role)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            palette.setColor(group, role, colour)
    image = render_surface(width, height, palette)

    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    state.mkdir(parents=True, exist_ok=True)
    target = state / "plasma-panel-surface.png"
    temporary = target.with_suffix(".new.png")
    if not image.save(str(temporary), "PNG"):
        return 1
    # Do not replace identical pixels.  The content hash is also the panel's
    # live update token: after the PNG is atomically replaced, publish it to a
    # one-line serial file which the already-mapped Panel.qml watches.  The
    # query-string change makes QML reload the Image in place, so this path
    # needs neither a plasmashell restart nor an arbitrary settling delay.
    if target.exists() and temporary.read_bytes() == target.read_bytes():
        temporary.unlink()
        # An older activation may have created the image before generations
        # existed.  Backfill its token so the live watcher starts in sync.
        publish_generation(state, target)
        return 0
    temporary.replace(target)
    publish_generation(state, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
