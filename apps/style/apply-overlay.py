#!/usr/bin/env python3
"""A generation-scoped native progress overlay for a DeskStyle apply.

The Style window starts this as a separate process immediately after
``org.lam.DeskStyle1.Apply`` returns its generation.  It waits 120ms before it
maps, so prepared switches remain invisible; once visible it renders the
already-cached Gaussian backdrop for the selected wallpaper and reads only the
controller's progress record.  It never estimates work or sleeps waiting for a
component: terminal controller state closes it.

Usage::

    apply-overlay.py --generation 12 --wallpaper /absolute/path/to/paper.png

``--status`` and ``--threshold-ms`` exist for an offscreen/private-state
harness.  They are not user-facing controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "pylib"))

from overlay_state import progress, should_show, status_for_generation  # noqa: E402
from chansource import panel_palette  # noqa: E402

from PySide6.QtCore import QFileSystemWatcher, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


DEFAULT_COLORS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216",
    "accent": "#cc4400", "text": "#ffffff", "textDim": "#8c5438",
}


def default_status_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state / "deskstyle" / "status.json"


def blur_path(wallpaper: Path) -> Path:
    key = hashlib.md5(str(wallpaper.resolve()).encode("utf-8")).hexdigest()
    return Path.home() / ".cache" / "wal" / f"blur-{key}.png"


def read_status(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class ApplyOverlay(QWidget):
    """A non-interactive full-screen client, independent of the Style window."""

    def __init__(self, generation: int, wallpaper: Path, status_path: Path,
                 threshold_ms: int) -> None:
        super().__init__(None)
        self.generation = generation
        self.status_path = status_path
        self.colors = DEFAULT_COLORS | panel_palette()
        self.backdrop = QPixmap(str(blur_path(wallpaper)))
        self.status: dict = read_status(status_path)
        self.started_at = time.monotonic()
        self.elapsed_ms = 0
        self.presented = False

        # A normal top-level Qt client deliberately outlives the settings
        # window and any Quickshell QML reload.  Tool keeps it out of task lists;
        # the no-focus flag avoids changing focus while the user waits.
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle("Applying appearance")

        self.watch = QFileSystemWatcher(self)
        self.watch.fileChanged.connect(self._changed)
        self.watch.directoryChanged.connect(self._changed)
        self._watch_status()
        self.poll = QTimer(self)
        self.poll.setInterval(33)
        self.poll.timeout.connect(self._tick)
        self.poll.start()
        self._tick()

    def _watch_status(self) -> None:
        for candidate in (self.status_path.parent, self.status_path):
            text = str(candidate)
            if candidate.exists() and text not in set(self.watch.files()) | set(self.watch.directories()):
                self.watch.addPath(text)

    def _changed(self, _path: str) -> None:
        self._watch_status()  # atomic replacement removes a file-only watch
        self._refresh()

    def _refresh(self) -> None:
        self.status = read_status(self.status_path)
        state = status_for_generation(self.status, self.generation)
        if state in ("complete", "failed", "superseded"):
            self.close()
            return
        if not self.presented and should_show(self.elapsed_ms, self.status, self.generation):
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                self.setGeometry(screen.geometry())
            self.presented = True
            self.show()
        if self.presented:
            self.colors = DEFAULT_COLORS | panel_palette()
            self.update()

    def _tick(self) -> None:
        self.elapsed_ms = round((time.monotonic() - self.started_at) * 1000)
        self._refresh()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt spelling)
        painter = QPainter(self)
        rect = self.rect()
        if not self.backdrop.isNull():
            source = self.backdrop.size()
            # Cover, not stretch: the cached image is an actual Gaussian blur,
            # so scaling it for this brief backdrop cannot reveal an alias.
            scaled = self.backdrop.scaled(rect.size(), Qt.KeepAspectRatioByExpanding,
                                          Qt.SmoothTransformation)
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        painter.fillRect(rect, QColor(0, 0, 0, 150))

        width = min(max(280, rect.width() - 32), 520)
        height = 96
        card = QRect((rect.width() - width) // 2, (rect.height() - height) // 2, width, height)
        painter.fillRect(card, QColor(self.colors["bg"]))
        painter.setPen(QColor(self.colors["accent"]))
        painter.drawRect(card.adjusted(0, 0, -1, -1))

        fraction, detail = progress(self.status, self.generation)
        phase = status_for_generation(self.status, self.generation)
        label = detail or {"queued": "Waiting to apply appearance",
                           "applying": "Updating desktop colors",
                           "waiting-for-apps": "Refreshing applications"}.get(phase, "Applying appearance")
        text_font = QFont(self.font())
        text_font.setPixelSize(15)
        painter.setFont(text_font)
        painter.setPen(QColor(self.colors["text"]))
        painter.drawText(card.adjusted(12, 10, -12, -42), Qt.AlignLeft | Qt.AlignVCenter,
                         "applying appearance")
        painter.setPen(QColor(self.colors["textDim"]))
        painter.drawText(card.adjusted(12, 32, -12, -20), Qt.AlignLeft | Qt.AlignVCenter, label)
        bar = card.adjusted(12, height - 18, -12, -10)
        painter.setPen(QColor(self.colors["border"]))
        painter.drawRect(bar.adjusted(0, 0, -1, -1))
        if fraction > 0:
            fill = QRect(bar.x() + 1, bar.y() + 1,
                         round((bar.width() - 2) * fraction), max(0, bar.height() - 2))
            painter.fillRect(fill, QColor(self.colors["accent"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show live DeskStyle apply progress")
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--wallpaper", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=default_status_path())
    parser.add_argument("--threshold-ms", type=int, default=120)
    args = parser.parse_args(argv)
    if args.generation < 1 or args.threshold_ms < 0:
        parser.error("generation must be positive and threshold must not be negative")
    app = QApplication([sys.argv[0]])
    app.setApplicationName("style-apply-overlay")
    overlay = ApplyOverlay(args.generation, args.wallpaper, args.status, args.threshold_ms)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
