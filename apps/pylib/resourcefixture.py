"""Tiny retained-fixture protocol for offscreen resource measurements.

Applications register narrow state callbacks; this module only owns newline
control, settling, READY reports, and orderly quit.  It is deliberately not an
input automation layer.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QSocketNotifier, QTimer


class ResourceFixture(QObject):
    """Read state names from a private fd and report readiness on another."""

    def __init__(self, app, states, *, initial="normal", settle_ms=250,
                 control_fd=None, ready_fd=None, parent=None):
        super().__init__(parent)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            raise RuntimeError("resource fixture requires QT_QPA_PLATFORM=offscreen")
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
            raise RuntimeError("resource fixture refuses inherited display sockets")
        self._app = app
        self._states = dict(states)
        self._settle_ms = settle_ms
        self._control_fd = int(control_fd if control_fd is not None else
                               os.environ.get("RESOURCE_CONTROL_FD", "0"))
        self._ready_fd = int(ready_fd if ready_fd is not None else
                             os.environ.get("RESOURCE_READY_FD", "1"))
        self._pending = bytearray()
        self._notifier = QSocketNotifier(self._control_fd,
                                         QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read)
        QTimer.singleShot(0, lambda: self.transition(initial))

    def _report(self, state):
        os.write(self._ready_fd,
                 f"READY {state} pid={os.getpid()}\n".encode("ascii"))

    def transition(self, state):
        if state == "quit":
            self._notifier.setEnabled(False)
            if hasattr(self._app, "closeAllWindows"):
                self._app.closeAllWindows()
            else:
                self._app.quit()
            QTimer.singleShot(1000, self._app.quit)
            return
        callback = self._states.get(state)
        if callback is None:
            os.write(self._ready_fd, f"ERROR unknown-state {state}\n".encode())
            return
        callback()
        QTimer.singleShot(self._settle_ms, lambda: self._report(state))

    def _read(self):
        chunk = os.read(self._control_fd, 4096)
        if not chunk:
            self.transition("quit")
            return
        self._pending.extend(chunk)
        while b"\n" in self._pending:
            raw, _, rest = self._pending.partition(b"\n")
            self._pending = bytearray(rest)
            state = raw.decode("ascii", "replace").strip()
            if state:
                self.transition(state)
