"""winstate — remember a top-level window's position and size between sessions.

One helper, wired identically into every app's `main.py` right after the root
window is created (`win = engine.rootObjects()[0]`):

    from winstate import WinState
    winstate = WinState(win, "filer")   # keep the Python ref alive

It writes the window's frame geometry to a per-app state file
(`$XDG_STATE_HOME/<app>/window.json`, default `~/.local/state/<app>/…`) on
close and — debounced — whenever the user moves or resizes it, and restores it
when the app next starts. Maximized / fullscreen survives too.

**What actually persists, per session type — this is deliberate, not a bug:**

- **Size** is client-controlled at surface creation on every windowing system,
  so it is restored everywhere: Hyprland, KWin/Plasma (Wayland), and X11.
- **Position** cannot be set by a Wayland client itself — the protocol has no
  request for it (KWin and Hyprland both). So `setPosition` here is honoured on
  X11 and is a harmless no-op on Wayland. On the Hyprland session the plugin
  already remembers each window's geometry across a logout (hyprvtb closes
  gracefully); on KWin the durable path is a window rule keyed on the app's
  stable identity (`app_id`, set from the desktop-file name in each `main.py`).
  Either way the position is *recorded* here, so nothing is lost and a
  compositor that does honour it gets the right value.

Guards, because a restore that lands off-screen or at zero size is worse than
none: a saved rect with a non-positive width/height is dropped, and a position
that would put the window (almost) entirely off every connected screen is
clamped back so a chunk of it stays grabbable. Restoring is skipped entirely
for a fixed-size window (min == max on both axes) except for its position.
"""

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QWindow

# Below this the saved size is treated as garbage rather than restored.
_MIN_DIM = 80
# Keep at least this many pixels of the window on some screen when clamping.
_KEEP_VISIBLE = 64
# Coalesce a burst of move/resize events into one write.
_SAVE_DEBOUNCE_MS = 500


def _state_path(app_name):
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / app_name / "window.json"


class WinState(QObject):
    def __init__(self, window, app_name, parent=None):
        super().__init__(parent or window)
        self._win = window
        self._path = _state_path(app_name)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._timer.timeout.connect(self._save)

        self._restore()

        for sig in (window.xChanged, window.yChanged,
                    window.widthChanged, window.heightChanged,
                    window.visibilityChanged):
            sig.connect(self._touch)
        # A close is the one moment we must not miss, and it can beat the
        # debounce timer, so save straight through.
        app = QGuiApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._save)

    # --- saving -----------------------------------------------------------
    def _touch(self, *args):
        # Ignore the transient 0/1px states Qt reports mid-map.
        self._timer.start()

    def _save(self):
        win = self._win
        try:
            vis = win.visibility()
        except Exception:
            return
        maximized = vis == QWindow.Maximized
        fullscreen = vis == QWindow.FullScreen
        data = {
            "x": int(win.x()),
            "y": int(win.y()),
            "width": int(win.width()),
            "height": int(win.height()),
            "maximized": maximized,
            "fullscreen": fullscreen,
        }
        # When maximized/fullscreen, x/y/width/height are the screen's, not the
        # window's own resting geometry — don't let them overwrite it.
        if maximized or fullscreen:
            prev = self._load()
            if prev:
                for k in ("x", "y", "width", "height"):
                    if isinstance(prev.get(k), int):
                        data[k] = prev[k]
        if data["width"] < _MIN_DIM or data["height"] < _MIN_DIM:
            if not (maximized or fullscreen):
                return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self._path)
        except OSError:
            pass

    # --- restoring --------------------------------------------------------
    def _load(self):
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return None

    def _restore(self):
        data = self._load()
        if not data:
            return
        win = self._win
        w = data.get("width")
        h = data.get("height")
        size_ok = (isinstance(w, int) and isinstance(h, int)
                   and w >= _MIN_DIM and h >= _MIN_DIM)

        fixed_w = win.minimumWidth() == win.maximumWidth() and win.maximumWidth() > 0
        fixed_h = win.minimumHeight() == win.maximumHeight() and win.maximumHeight() > 0

        if size_ok and not (fixed_w and fixed_h):
            if not fixed_w:
                win.setWidth(w)
            if not fixed_h:
                win.setHeight(h)

        x = data.get("x")
        y = data.get("y")
        if isinstance(x, int) and isinstance(y, int):
            cw = win.width() if not size_ok else w
            ch = win.height() if not size_ok else h
            x, y = self._clamp_onscreen(x, y, cw, ch)
            if x is not None:
                # Honoured on X11; a no-op on Wayland, where the compositor
                # places the window (see module docstring).
                win.setX(x)
                win.setY(y)

        if data.get("fullscreen"):
            win.setVisibility(QWindow.FullScreen)
        elif data.get("maximized"):
            win.setVisibility(QWindow.Maximized)

    def _clamp_onscreen(self, x, y, w, h):
        screens = QGuiApplication.screens()
        if not screens:
            return x, y
        # Already sufficiently visible on some screen? Leave it.
        for scr in screens:
            g = scr.availableGeometry()
            ix = max(x, g.left())
            iy = max(y, g.top())
            ax = min(x + w, g.right())
            ay = min(y + h, g.bottom())
            if (ax - ix) >= _KEEP_VISIBLE and (ay - iy) >= _KEEP_VISIBLE:
                return x, y
        # Otherwise pull it onto the nearest screen (default: primary).
        prim = QGuiApplication.primaryScreen() or screens[0]
        g = prim.availableGeometry()
        nx = min(max(x, g.left()), max(g.left(), g.right() - w))
        ny = min(max(y, g.top()), max(g.top(), g.bottom() - h))
        return int(nx), int(ny)
