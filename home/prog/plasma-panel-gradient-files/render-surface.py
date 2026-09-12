#!/usr/bin/env python3
"""Render the KDE style's window background as one screen-sized PNG.

The panels crop this image at their global coordinates.  Rendering a real,
never-shown QWidget is the same mechanism apps/pylib/kdeshell.py uses for the
pixel-exact background behind our Plasma QML apps; it does not map a window or
interact with the desktop.

The field is rendered at the size of a MAXIMISED window, not of the screen,
and placed at the work area's origin.  Oxygen's background is a vertical
falloff plus a radial splash anchored to the window's own top-left, so a
maximised window restarts it 22px below a screen-anchored panel crop: measured
here, (67,25,21) under the panel against (71,26,22) at the window's first row,
which is exactly the seam along a maximised window's edge.  Painting the panel
strips with the field's edge row and column instead makes the panel the
clamped continuation of that window, and the two meet with equal pixels.
"""

from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import time

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPalette, QRegion
from PySide6.QtWidgets import QApplication, QWidget


def plasma_screen_size() -> tuple[int, int] | None:
    """Read the live logical primary-output size before Qt goes offscreen."""
    probe_env = os.environ.copy()
    # The renderer itself must stay offscreen, but kscreen-doctor must connect
    # to the real session or it reports Qt's synthetic 800x800 output.
    probe_env.pop("QT_QPA_PLATFORM", None)
    try:
        result = subprocess.run(
            ["kscreen-doctor", "-o"], capture_output=True, text=True,
            timeout=3, check=False, env=probe_env,
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

def panel_struts() -> dict[str, int]:
    """Measure what the panels reserve, from their own declarative config.

    Qt cannot answer this: an offscreen platform plugin has no outputs, and
    Wayland does not report another client's exclusive zone.  Plasma's own two
    files do — the containment carries the edge, its view carries the
    thickness — and they are the same files the panel layout is generated from.
    """
    edges = {3: "top", 4: "bottom", 5: "left", 6: "right"}
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    panels: dict[str, str] = {}
    group = None
    try:
        applets = (config / "plasma-org.kde.plasma.desktop-appletsrc").read_text()
    except OSError:
        return {}
    for line in applets.splitlines():
        if line.startswith("["):
            group = line
            continue
        containment = re.fullmatch(r"\[Containments\]\[(\d+)\]", group or "")
        if containment is None:
            continue
        if line.startswith("location="):
            panels.setdefault(containment.group(1), "")
            panels[containment.group(1)] = edges.get(int(line[9:]), "")
        elif line == "plugin=org.kde.panel":
            panels.setdefault(containment.group(1), "")

    struts: dict[str, int] = {}
    try:
        views = (config / "plasmashellrc").read_text()
    except OSError:
        return {}
    group = None
    for line in views.splitlines():
        if line.startswith("["):
            group = line
            continue
        view = re.fullmatch(r"\[PlasmaViews\]\[Panel (\d+)\]\[Defaults\]", group or "")
        if view is None or not line.startswith("thickness="):
            continue
        edge = panels.get(view.group(1))
        if edge:
            struts[edge] = max(struts.get(edge, 0), int(line[10:]))
    return struts


def clamp_into_screen(field: QImage, width: int, height: int,
                      struts: dict[str, int]) -> QImage:
    """Place the maximised-window field, extending its edges under the panels."""
    left, top = struts.get("left", 0), struts.get("top", 0)
    canvas = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(0)
    painter = QPainter(canvas)
    fw, fh = field.width(), field.height()
    # Corners first; each strip then overwrites the part it owns.
    for x, sx in ((0, 0), (left + fw, fw - 1)):
        for y, sy in ((0, 0), (top + fh, fh - 1)):
            painter.drawImage(QRect(x, y, width, height), field, QRect(sx, sy, 1, 1))
    painter.drawImage(QRect(left, 0, fw, top), field, QRect(0, 0, fw, 1))
    painter.drawImage(QRect(left, top + fh, fw, height), field,
                      QRect(0, fh - 1, fw, 1))
    painter.drawImage(QRect(0, top, left, fh), field, QRect(0, 0, 1, fh))
    painter.drawImage(QRect(left + fw, top, width, fh), field,
                      QRect(fw - 1, 0, 1, fh))
    painter.drawImage(QPoint(left, top), field)
    painter.end()
    return canvas


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
    if live_size is None:
        # Activation can run without a desktop connection. Never replace the
        # shared browser/panel canvas with Qt offscreen's synthetic 800x800.
        print("no live Plasma output; retaining the previous surface", file=sys.stderr)
        return 1
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if app.style().objectName().lower() != "oxygen":
        print(f"refusing non-Oxygen style: {app.style().objectName()}", file=sys.stderr)
        return 1
    width, height = live_size

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
    struts = panel_struts()
    field = render_surface(
        max(1, width - struts.get("left", 0) - struts.get("right", 0)),
        max(1, height - struts.get("top", 0) - struts.get("bottom", 0)),
        palette)
    image = clamp_into_screen(field, width, height, struts)

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
