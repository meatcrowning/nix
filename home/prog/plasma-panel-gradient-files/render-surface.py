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
import re
import subprocess
import sys
import time

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPalette, QRegion
from PySide6.QtWidgets import QApplication, QWidget


def plasma_screen_size() -> tuple[int, int] | None:
    """Read the live logical primary-output size before Qt goes offscreen."""
    try:
        result = subprocess.run(
            ["kscreen-doctor", "-o"], capture_output=True, text=True,
            timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    outputs = []
    for block in re.split(r"(?=^Output: )", plain, flags=re.MULTILINE):
        if "\n\tenabled" not in block:
            continue
        geometry = re.search(r"Geometry:\s*-?\d+,-?\d+\s+(\d+)x(\d+)", block)
        if geometry is None:
            continue
        priority = re.search(r"priority\s+(\d+)", block)
        outputs.append((int(priority.group(1)) if priority else 999,
                        int(geometry.group(1)), int(geometry.group(2))))
    if not outputs:
        return None
    _, width, height = min(outputs)
    return width, height

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
    serial = state / f"plasma-panel-surface.{time.time_ns()}.{digest}.serial"
    # FolderListModel does not reliably emit dataChanged for one fixed file,
    # and it can coalesce a create+delete pair into no net model change.  Keep
    # each tiny token: one direct creation is one durable inserted row, so the
    # running panel's count changes exactly once for every changed render.
    serial.write_text(digest + "\n")
    # Retire the fixed-name token used by the broken metadata-only watcher.
    legacy = state / "plasma-panel-surface.serial"
    if legacy.exists():
        legacy.unlink()


def main() -> int:
    live_size = plasma_screen_size()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if app.style().objectName().lower() != "oxygen":
        print(f"refusing non-Oxygen style: {app.style().objectName()}", file=sys.stderr)
        return 1
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1
    rect = screen.geometry()
    width, height = live_size or (max(1, rect.width()), max(1, rect.height()))

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
