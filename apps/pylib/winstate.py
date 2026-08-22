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

**KWin window rules: X11 only, and NEVER under Wayland.** On an X11 session we
write a per-app rule into `~/.config/kwinrulesrc` carrying the recorded resting
position (`positionrule` = *Apply Initially*, keyed on `wmclass` = `app_id`,
`types` = normal windows only). We only ever touch groups we own — named
`winstate-<app>` — so a hand-made rule of yours is never disturbed, and the
read-modify-write is locked and atomic so two apps writing at once cannot
corrupt the file.

**Under KWin's Wayland session that rule is a trap, and writing one is a bug we
already shipped.** Two independent halves, both fatal:

- A Wayland client is never told where it is, so `QWindow.x()/y()` read 0 for
  the whole life of the window. The rule we wrote therefore carried
  `position=0,0` — and *Apply Initially* faithfully forced every window of the
  app into the top-left corner at every launch. Recording a position we cannot
  know and then feeding it back is worse than not remembering at all.
- A KWin rule matches on `wmclass`, and every toplevel of one app shares its
  `app_id` — main window, About box, any dialog. `types` cannot separate them
  here either: KWin gives every xdg-shell toplevel `WindowType::Normal`
  (`XdgToplevelWindow`; the NET types are an X11 notion), so a dialog is a
  normal window as far as the rule is concerned. That is why the About box
  spawned in the corner too.

So on Wayland we write no rule, and on first run we DELETE the `winstate-<app>`
group we left behind, then ask KWin to reconfigure so the removal takes effect
without a relog. The cost is stated plainly: on KWin/Wayland a window's
position is not restored at all, because no client-side mechanism exists to do
it honestly. Size still is (client-controlled), and the position is still
recorded, so X11 and Hyprland lose nothing.

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

# KWin SetRule value for "Apply Initially": set our value when the window maps,
# then let the user move it freely (it is re-applied only on the next open).
_KWIN_APPLY = 3
# KWin match type for wmclass: 1 == exact match.
_KWIN_EXACT = 1
# NET::NormalMask — the `types` mask that keeps the rule off dialogs and
# utility windows. Meaningful on X11 only; see the docstring.
_KWIN_NORMAL_ONLY = 1


def _state_path(app_name):
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / app_name / "window.json"


def _is_kwin_session():
    """True on a KDE Plasma (KWin) session, where a client cannot place itself
    and the only client-side route to a restored position is a window rule."""
    desk = (os.environ.get("XDG_CURRENT_DESKTOP", "")
            + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")).upper()
    return "KDE" in desk or "PLASMA" in desk or bool(os.environ.get("KDE_FULL_SESSION"))


def _is_wayland():
    """True when the app is a Wayland client — i.e. when it can never learn its
    own position, so anything we record for it is a fiction."""
    try:
        return (QGuiApplication.platformName() or "").startswith("wayland")
    except Exception:
        return False


def _kwinrules_path():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "kwinrulesrc"


def _parse_kconfig(text):
    """kwinrulesrc is a flat KConfig INI: a list of ``[group]`` sections, each a
    list of ``key=value`` lines. Parse to ``[(name, [(key, value), ...]), ...]``
    preserving order and the raw key/value text — so groups we do not own are
    re-emitted byte-for-byte."""
    groups = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = (s[1:-1], [])
            groups.append(cur)
        elif "=" in s and cur is not None:
            k, _, v = s.partition("=")
            cur[1].append((k, v))
    return groups


def _emit_kconfig(groups):
    out = []
    for name, kvs in groups:
        out.append("[%s]" % name)
        out.extend("%s=%s" % (k, v) for k, v in kvs)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _kv_set(kvs, key, value):
    for i, (k, _) in enumerate(kvs):
        if k == key:
            kvs[i] = (key, value)
            return
    kvs.append((key, value))


def _rules_rmw(mutate):
    """Read `kwinrulesrc`, hand the parsed group list to `mutate`, and write it
    back atomically under a lock — never a partial file, and never two apps
    interleaving. `mutate` returns True if it changed anything; if it did not,
    nothing is written at all (so a no-op start-up check cannot churn the file
    KWin itself owns). Returns what `mutate` returned."""
    import fcntl

    path = _kwinrules_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_name(path.name + ".winstate.lock")
        with open(lock, "w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX)
            except OSError:
                pass
            try:
                text = path.read_text()
            except OSError:
                text = ""
            groups = _parse_kconfig(text)
            if not mutate(groups):
                return False
            tmp = path.with_suffix(".winstate.tmp")
            tmp.write_text(_emit_kconfig(groups))
            tmp.replace(path)
            return True
    except OSError:
        return False


def _general(groups):
    """The `[General]` group's key/value list, created if the file has none."""
    gen = next((kvs for n, kvs in groups if n == "General"), None)
    if gen is None:
        gen = []
        groups.insert(0, ("General", gen))
    return gen


def _listed(gen):
    return [r for r in dict(gen).get("rules", "").split(",") if r]


def _write_kwin_rule(app_name, x, y):
    """Ensure a KWin rule ``winstate-<app>`` that applies ``x,y`` to the window
    whose ``wmclass`` (X11 resource name) is ``app_name``. X11 ONLY — see the
    module docstring for why this must never run on Wayland."""
    group = "winstate-" + app_name

    def mutate(groups):
        gen = _general(groups)
        listed = _listed(gen)
        if group not in listed:
            listed.append(group)
        _kv_set(gen, "rules", ",".join(listed))
        _kv_set(gen, "count", str(len(listed)))

        kvs = next((kv for n, kv in groups if n == group), None)
        if kvs is None:
            kvs = []
            groups.append((group, kvs))
        _kv_set(kvs, "Description", "winstate: %s position" % app_name)
        _kv_set(kvs, "wmclass", app_name)
        _kv_set(kvs, "wmclasscomplete", "false")
        _kv_set(kvs, "wmclassmatch", str(_KWIN_EXACT))
        # Normal windows only: a rule keyed on the app's class otherwise moves
        # its dialogs too, and an About box does not want the main window's
        # resting place.
        _kv_set(kvs, "types", str(_KWIN_NORMAL_ONLY))
        _kv_set(kvs, "position", "%d,%d" % (int(x), int(y)))
        _kv_set(kvs, "positionrule", str(_KWIN_APPLY))
        return True

    _rules_rmw(mutate)


def _drop_kwin_rule(app_name):
    """Delete the ``winstate-<app>`` group and delist it. Returns True if the
    file actually changed — the caller only reconfigures KWin then."""
    group = "winstate-" + app_name

    def mutate(groups):
        gen = _general(groups)
        listed = _listed(gen)
        present = any(n == group for n, _ in groups)
        if group not in listed and not present:
            return False
        groups[:] = [(n, kv) for n, kv in groups if n != group]
        listed = [r for r in listed if r != group]
        _kv_set(gen, "rules", ",".join(listed))
        _kv_set(gen, "count", str(len(listed)))
        return True

    return _rules_rmw(mutate)


def _kwin_reconfigure():
    """Ask the running KWin to re-read its rules. Without this a removed rule
    keeps applying until the next login — and the whole point of removing it is
    that windows stop landing in the corner NOW."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        bus.call(QDBusMessage.createMethodCall(
            "org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure"),
            timeout=2000)
    except Exception:
        pass


class WinState(QObject):
    def __init__(self, window, app_name, parent=None):
        super().__init__(parent or window)
        self._win = window
        self._app_name = app_name
        self._path = _state_path(app_name)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._timer.timeout.connect(self._save)

        self._restore()

        # One-time repair: a Wayland session must have no winstate rule of ours
        # (it could only ever carry position=0,0 — see the module docstring), so
        # delete the one older versions wrote and make KWin forget it now.
        if _is_wayland() and _is_kwin_session() and _drop_kwin_rule(app_name):
            _kwin_reconfigure()

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
        # window's own resting geometry — don't let them overwrite it. On
        # Wayland x/y are not the window's either: the client is never told
        # where it is and reads 0 forever, so keeping whatever an X11 (or
        # earlier) session recorded is strictly better than writing that 0 down.
        stale = ["x", "y"] if _is_wayland() else []
        if maximized or fullscreen:
            stale = ["x", "y", "width", "height"]
        if stale:
            prev = self._load()
            if prev:
                for k in stale:
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
        # On an X11 KWin session, mirror the resting position into a window
        # rule — the only client-side way to get position restored there. Skip
        # while maximized/fullscreen (x/y are the screen's, not the resting
        # rect), and NEVER on Wayland, where the position we hold is a fiction
        # and the rule would pin every window of this app to the corner.
        if not (maximized or fullscreen) and _is_kwin_session() and not _is_wayland():
            _write_kwin_rule(self._app_name, data["x"], data["y"])

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
