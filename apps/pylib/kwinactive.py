"""Whether KWin considers this process's window the active one.

**Qt's answer and the titlebar's answer are not the same answer.** Qt derives
`isActiveWindow()` from wl_keyboard focus; KWin's decoration draws from the
window it made active. A screenshot tool splits the two — it takes the keyboard
without becoming the active window — and the window then renders in two colour
groups at once. Measured on `top` 2026-08-24 off a Spectacle capture of a
FOCUSED chatter: the client painted Oxygen's background in the INACTIVE group
(44,62,97 at the top of the menubar) while the decoration painted the ACTIVE
one (54,63,84 at the bottom of the titlebar), meeting at a hard seam through
the middle of what is meant to be one gradient.

**The app cannot go and ask.** KWin publishes per-window state on
`org_kde_plasma_window_management`, which is the protocol its own taskbar
reads — and it does not advertise that global to ordinary clients. Checked on
`top` 2026-08-24: 48 globals in the registry a normal app sees, and neither
that one nor any foreign-toplevel protocol among them.

So the compositor pushes instead. `home/prog/kwin-winactive.nix` installs a
KWin script that watches `workspace.windowActivated` and `callDBus`es the
window's own process at a name derived from its pid. This module is that name:
own it, and `active()` starts answering with the decoration's opinion instead
of Qt's.

**It fails soft, into Qt's answer.** No QtDBus, no session bus, the script not
installed or not enabled: `active()` returns None and the caller keeps using
`isActiveWindow()`, which is right in every case except the one this exists
for. Hyprland sessions never construct it — hyprvtb draws the titlebar there,
so both halves already read one focus state.
"""

from __future__ import annotations

import os

SERVICE = "org.kde.lam.winactive.p{pid}"
PATH = "/WinActive"
IFACE = "org.kde.lam.WinActive"


def watcher(parent=None):
    """A QObject with `changed(bool)` and `active()`, or None if unavailable.

    `active()` is None until KWin has said something — which the caller treats
    exactly like "unavailable" and falls back to Qt for.
    """
    try:
        from PySide6.QtCore import QObject, Signal, Slot
        from PySide6.QtDBus import QDBusConnection
    except Exception:
        return None

    class _KWinActive(QObject):
        changed = Signal(bool)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._active = None
            bus = QDBusConnection.sessionBus()
            self.ok = (bus.isConnected()
                       and bus.registerService(SERVICE.format(pid=os.getpid()))
                       # ExportAllSlots: the one @Slot below is the interface.
                       and bus.registerObject(
                           PATH, IFACE, self,
                           QDBusConnection.ExportAllSlots))

        @Slot(bool)
        def setActive(self, active):
            active = bool(active)
            if active != self._active:
                self._active = active
                self.changed.emit(active)

        def active(self):
            """True/False once KWin has said, else None."""
            return self._active

    w = _KWinActive(parent)
    return w if w.ok else None
