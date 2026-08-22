"""kdeshell — the Plasma face: a REAL QtWidgets window, painted by the KDE style.

The Hyprland session is this desktop's own: hyprvtb draws the chrome, the panel
owns the palette, `docs/DESIGN.md` owns everything else. Plasma 6 is a real
alternative session here, and in it an app of ours has to be an ordinary KDE
program — `kdetheme.py` already moves the palette, the font and the motion over
to `kdeglobals`, and `DeskMenuBar.qml` already turns the titlebar button column
into a menubar. This module is the rest of it, and it is a different KIND of
answer to the same question:

**Under Plasma we do not imitate the system theme. We let the system theme
paint.**

That distinction is the whole design. Oxygen's window background — the single
gradient surface that runs from the titlebar down across the menubar, the
toolbar and the sides of the window, which is what makes a KDE program read as
one object — is not a colour we could copy out of `kdeglobals`. It is
`Helper::renderWindowBackground()`, a vertical gradient plus a radial splash
whose stops come out of KColorScheme's HCY shading, drawn by the *decoration*
over the titlebar and by the *style* over the client area with a matching
23px y-shift so the two line up seamlessly. Reimplementing that in QML would be
a copy that drifts every time KDE touches it.

We do not have to. Two facts out of Oxygen's own source (6.7.4) decide the
architecture:

- `kstyle/oxygenstyle.cpp:4595` — `Style::drawWidgetPrimitive()` paints that
  background only for a real **QWidget window** (`WA_StyledBackground`,
  `isWindow()`, `Qt::Window|Qt::Dialog`). A bare `QQuickWindow` can never
  receive it, whatever style is set: there is no QStyle entry point that will
  hand it to one.
- `kstyle/oxygenstyle.cpp:8274` — `Style::isQtQuickControl()` registers any
  `QQuickItem` style object it is asked to draw for with Oxygen's own
  `WindowManager`, which is the drag-windows-from-any-empty-area behaviour
  (`WindowDragMode` defaults to `WD_FULL`). It ends in
  `QWindow::startSystemMove()`. So the "you can move the window by dragging
  below the titlebar" part comes free with the real style too — including from
  inside the QML — and is not ours to reimplement either.

So the Plasma face of an app is shaped exactly like Dolphin: a `QMainWindow`
with a real `QMenuBar`, `QToolBar` and `QStatusBar`, and the app's existing QML
tree hosted in a `QQuickWidget` as the central widget with a **transparent
clear colour**, so the styled window background shows through behind it and the
whole window is one continuous surface. Every pixel of chrome is drawn by
whatever KStyle is configured — Oxygen today, Breeze or anything else tomorrow,
correctly, with no work here.

**One source, two roofs** (docs/DESIGN.md §7.6) is unchanged and is why this
module reads the app rather than the app reconfiguring itself: the menubar, the
toolbar and the statusbar are all built from the SAME `tbButtons` array the
hyprvtb titlebar column is built from, and they call the same `tbAction(id)`
handler. An app adds two optional keys per entry for this face — `icon:`, a
freedesktop icon name, and `bar: true` to put the entry on the toolbar — and
the vtb wire protocol ignores both (`vtbclient.py` reads id/label/state/tip/
bottom).

Nothing here runs in the Hyprland session. `is_plasma()` is the single switch,
and an app that never calls this module behaves exactly as it did.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, QMetaObject, Q_ARG
from PySide6.QtGui import QAction, QIcon

from kdetheme import is_plasma, read_ini

# The button `state` vocabulary shared with the hyprvtb titlebar and
# DeskMenuBar.qml: 0 normal, 1 lit (a toggle that is on / the page you are on),
# 2 disabled. docs/DESIGN.md §12.1.
STATE_NORMAL = 0
STATE_LIT = 1
STATE_DISABLED = 2


def controls_style() -> str:
    """The Qt Quick Controls style an app should pin at startup.

    `org.kde.desktop` is qqc2-desktop-style, which does not imitate the desktop
    style either: it renders each control through the live `QStyle`, so a
    `Button` inside our QML is painted by Oxygen's own `drawControl()`. It
    needs a `QApplication` (QStyle lives in QtWidgets) — see `make_app()` — and
    it needs the KDE Frameworks QML modules on the import path, which is why
    `home/prog/painter.nix` puts them there.

    Outside Plasma the answer stays `Basic`: the system default resolves to
    Breeze, whose ToolTip pulls in kirigami and fails to load in a session that
    has none of it.
    """
    return "org.kde.desktop" if is_plasma() else "Basic"


def pin_controls_style() -> None:
    """Set `QT_QUICK_CONTROLS_STYLE` before the app object exists, which is the
    only point at which Qt reads it."""
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", controls_style())


def make_app(argv, name: str):
    """The application object: a `QApplication` under Plasma, the
    `QGuiApplication` we have always used otherwise.

    QtWidgets is not a nicety in that session — `QStyle` is a QtWidgets class,
    so without it there is no Oxygen to paint with, no styled window background
    and no window manager to drag from. Under Hyprland we keep the lighter
    object: nothing in that session's face needs a widget.
    """
    if is_plasma():
        from PySide6.QtWidgets import QApplication
        app = QApplication(argv)
    else:
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication(argv)
    app.setApplicationName(name)
    app.setDesktopFileName(name)   # stable Wayland app_id (KWin identity)
    app.setOrganizationName(name)
    if is_plasma():
        apply_icon_theme()
        apply_widget_style(app)
    return app


def apply_widget_style(app) -> None:
    """Make sure the app is wearing the desktop's KStyle — `[KDE] widgetStyle`
    in `kdeglobals`, `oxygen` here.

    Normally the KDE platform theme plugin does this, and where it is loaded
    this function finds the style already correct and does nothing. But an app
    of ours runs out of its own nix wrapper, and a missing `plasma-integration`
    in that environment does not fail loudly — it silently leaves the window in
    Fusion, which is the exact "one odd window" this whole face exists to
    prevent, and which cost a full offscreen render to notice. So we ask for the
    style by name and only fall back to whatever Qt chose if it cannot be made.
    """
    from PySide6.QtWidgets import QStyleFactory
    want = ((read_ini().get("KDE", {}) or {}).get("widgetStyle", "") or "").strip()
    if not want:
        return
    if (app.style().objectName() or "").lower() == want.lower():
        return
    style = QStyleFactory.create(want)
    if style is not None:
        app.setStyle(style)


def icon_theme_name() -> str:
    """The KDE icon theme, from `kdeglobals` — `[Icons] Theme`, and failing that
    whatever the look-and-feel package implies.

    A KDE program's toolbar and menus are drawn with icons from the desktop's
    own set; a `QIcon.fromTheme()` that resolves to nothing gives text-only rows
    that read as a toolkit demo rather than an application. Qt normally learns
    the name from the KDE platform theme, but that plugin is not always in an
    app's environment (and never in an offscreen harness), so we name it
    ourselves rather than rely on it.
    """
    ini = read_ini()
    name = (ini.get("Icons", {}) or {}).get("Theme", "").strip()
    if name:
        return name
    lnf = (ini.get("KDE", {}) or {}).get("LookAndFeelPackage", "").lower()
    return "oxygen" if "oxygen" in lnf else "breeze"


def icon_search_paths() -> list:
    """Every `…/icons` directory the XDG data dirs name.

    Qt fills this in from the platform theme, and on a headless/offscreen run
    there is none — measured: `QIcon.themeSearchPaths()` comes back as just
    `[':/icons']`, so every `fromTheme()` returns a null icon and a toolbar
    renders text-only. That is also the shape of the failure if an app's
    wrapper is ever missing the KDE QPA plugin, so it is worth not depending on
    it: the paths are derivable from the environment we are already given.
    """
    dirs = []
    home_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.append(home_data)
    dirs += (os.environ.get("XDG_DATA_DIRS")
             or "/usr/local/share:/usr/share").split(":")
    out = []
    for d in dirs:
        d = (d or "").strip()
        if not d:
            continue
        p = os.path.join(d, "icons")
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def apply_icon_theme() -> None:
    """Pin the icon theme if nothing else has. Never overrides a name the
    platform theme already set — that one is authoritative."""
    have = list(QIcon.themeSearchPaths())
    for p in icon_search_paths():
        if p not in have:
            have.append(p)
    QIcon.setThemeSearchPaths(have)
    if not QIcon.themeName():
        QIcon.setThemeName(icon_theme_name())
    if not QIcon.fallbackThemeName():
        QIcon.setFallbackThemeName("breeze")


class KdeShell:
    """A `QMainWindow` hosting an app's QML tree, chromed like a KDE program.

    Deliberately NOT a QMainWindow subclass: apps hold it in a variable and the
    Qt object graph is an implementation detail. `window` is the QMainWindow,
    `view` the QQuickWidget, `handle` the QWindow every app already passes to
    `winstate` and uses to ask whether the user is looking at it.

    Built lazily by `shell()` — see the note on `_build_shell_class()`.
    """


def _build_shell_class():
    from PySide6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QLabel
    from PySide6.QtQuickWidgets import QQuickWidget

    class _KdeShell:
        __doc__ = KdeShell.__doc__

        def __init__(self, title: str, size=(1280, 900), min_size=(720, 560)):
            self.window = QMainWindow()
            self.window.setWindowTitle(title)
            self.window.resize(*size)
            self.window.setMinimumSize(*min_size)

            self.view = QQuickWidget()
            self.view.setResizeMode(QQuickWidget.SizeRootObjectToView)
            # THE POINT OF THE WHOLE FILE. A QQuickWidget clears to white by
            # default and would cover the styled window background with a flat
            # rectangle — the exact "one odd window" this face exists to avoid.
            # Transparent, and the Oxygen gradient shows through behind every
            # part of the QML that does not paint itself.
            self.view.setClearColor(Qt.transparent)
            self.view.setAttribute(Qt.WA_TranslucentBackground)
            self.window.setCentralWidget(self.view)

            self._toolbar = None
            self._status = None
            self._status_label = None
            self._progress = None
            self._status_timer = None
            self._line_prop = "statusLine"
            self._progress_prop = "statusProgress"
            self._actions = {}      # id -> QAction
            self._root = None

        # ---------------------------------------------------------- engine
        def engine(self):
            return self.view.engine()

        def context(self):
            return self.view.rootContext()

        def add_image_provider(self, name, provider):
            self.view.engine().addImageProvider(name, provider)

        def load(self, path) -> bool:
            self.view.setSource(QUrl.fromLocalFile(str(path)))
            return self.view.status() == QQuickWidget.Ready

        def errors(self):
            return [e.toString() for e in self.view.errors()]

        @property
        def root(self):
            return self.view.rootObject()

        @property
        def handle(self):
            """The QWindow — `winstate` and every "is he looking at it?" check
            take one. Only valid once the window has been shown, which is why
            `show()` returns it."""
            return self.window.windowHandle()

        def show(self):
            self.window.show()
            return self.window.windowHandle()

        # ---------------------------------------------------------- chrome
        def bind_chrome(self, titlebar=None, menu_order=None):
            """Build the menubar, toolbar and statusbar out of the QML root's
            own `tbButtons`, and keep them in step with it.

            `titlebar` is the app's vtb bridge object: in this session its
            socket is dead, but every state change in the app still runs
            `pushButtons()` through it, so its signals are exactly the "the
            chrome changed" notification this face needs — no second source and
            no polling.
            """
            root = self.root
            if root is None:
                return
            self._root = root
            if menu_order is None:
                menu_order = root.property("menuOrder") or []
            self._menu_order = [str(m) for m in menu_order]
            self._rebuild()

            if titlebar is not None:
                for sig in ("buttonsChanged", "footerChanged", "loadingChanged"):
                    s = getattr(titlebar, sig, None)
                    if s is None:
                        continue
                    if sig == "buttonsChanged":
                        s.connect(lambda *_: self._refresh())
                    elif sig == "footerChanged":
                        s.connect(self.set_status)
                    else:
                        s.connect(self.set_busy)

        def _entries(self):
            # A QML `property var` arrives as a QJSValue, which is not iterable
            # in Python — `.toVariant()` is what turns it into the list of dicts
            # and "-" strings the array actually is.
            raw = self._root.property("tbButtons")
            if hasattr(raw, "toVariant"):
                raw = raw.toVariant()
            raw = raw or []
            out = []
            for b in raw:
                if isinstance(b, str):
                    out.append(None)          # separator
                elif isinstance(b, dict):
                    out.append(b)
            return out

        def _rebuild(self):
            from PySide6.QtWidgets import QToolBar, QStatusBar, QLabel

            entries = self._entries()
            bar = self.window.menuBar()
            bar.clear()
            self._actions.clear()

            groups = {}
            order = list(self._menu_order)
            for e in entries:
                if e is None:
                    continue
                g = str(e.get("menu", "") or "")
                if not g:
                    continue
                groups.setdefault(g, []).append(e)
                if g not in order:
                    order.append(g)

            for g in order:
                items = groups.get(g)
                if not items:
                    continue
                menu = bar.addMenu("&" + g.capitalize())
                for e in items:
                    menu.addAction(self._action_for(e))

            # The toolbar: the app's own choice, `bar: true` per entry. A KDE
            # program's toolbar is its primary verbs, not everything it can do —
            # the menus are the complete set.
            tb = self._toolbar
            if tb is None:
                tb = QToolBar("main", self.window)
                tb.setMovable(False)
                self.window.addToolBar(tb)
                self._toolbar = tb
            tb.clear()
            prev_sep = True
            for e in entries:
                if e is None:
                    if not prev_sep:
                        tb.addSeparator()
                        prev_sep = True
                    continue
                if not e.get("bar"):
                    continue
                tb.addAction(self._action_for(e))
                prev_sep = False
            tb.setVisible(not tb.actions() == [])

            if self._status is None:
                from PySide6.QtWidgets import QProgressBar
                self._status = QStatusBar(self.window)
                self._status_label = QLabel("")
                self._progress = QProgressBar()
                self._progress.setMaximumWidth(160)
                self._progress.setTextVisible(False)
                self._progress.setVisible(False)
                self._status.addPermanentWidget(self._progress)
                self._status.addPermanentWidget(self._status_label)
                self.window.setStatusBar(self._status)

        def _action_for(self, e):
            """One QAction per button id, reused across rebuilds so a menu and a
            toolbar row are the same object — check state, enabled state and
            icon can then never disagree between the two."""
            bid = str(e.get("id", ""))
            act = self._actions.get(bid)
            if act is None:
                act = QAction(self.window)
                act.triggered.connect(lambda _=False, i=bid: self._invoke(i))
                self._actions[bid] = act
            # A row's label is the button's TOOLTIP, not its two-character
            # titlebar glyph — docs/DESIGN.md §7.6.
            act.setText(str(e.get("tip") or e.get("label") or bid))
            act.setToolTip(str(e.get("tip") or ""))
            icon = str(e.get("icon") or "")
            if icon:
                act.setIcon(QIcon.fromTheme(icon))
            state = int(e.get("state", STATE_NORMAL) or 0)
            act.setEnabled(state != STATE_DISABLED)
            act.setCheckable(state == STATE_LIT or act.isCheckable())
            if act.isCheckable():
                act.setChecked(state == STATE_LIT)
            return act

        def _refresh(self):
            """A state flip: update the actions in place. Rebuilding the
            menubar here instead would close a menu the user has open."""
            if self._root is None:
                return
            for e in self._entries():
                if e is not None:
                    self._action_for(e)

        def _invoke(self, bid):
            QMetaObject.invokeMethod(self._root, "tbAction", Q_ARG("QVariant", bid))

        # --------------------------------------------------------- statusbar
        def bind_status(self, line_prop="statusLine", progress_prop="statusProgress"):
            """Drive the status bar from two properties on the QML root.

            The app already computes what its state SAYS — this face just needs
            it in a KDE status bar instead of a strip drawn inside the content.
            Bound by signal where QML gives us one (`<prop>Changed`, which every
            QML property has), and only where that lookup fails does it fall
            back to a slow poll, so a missing signal degrades to late rather
            than to nothing.
            """
            self._line_prop = line_prop
            self._progress_prop = progress_prop
            root = self._root
            if root is None:
                return
            bound = 0
            for prop in (line_prop, progress_prop):
                sig = getattr(root, prop + "Changed", None)
                if sig is not None and hasattr(sig, "connect"):
                    sig.connect(self._pull_status)
                    bound += 1
            if bound < 2:
                from PySide6.QtCore import QTimer
                self._status_timer = QTimer(self.window)
                self._status_timer.setInterval(400)
                self._status_timer.timeout.connect(self._pull_status)
                self._status_timer.start()
            self._pull_status()

        def _pull_status(self):
            root = self._root
            if root is None:
                return
            self.set_status(root.property(self._line_prop))
            self.set_progress(root.property(self._progress_prop))

        def set_status(self, text):
            if self._status_label is not None:
                self._status_label.setText(str(text or ""))

        def set_progress(self, value):
            """`value` in 0..1, or negative for "nothing is running" — which
            hides the bar rather than showing an empty one."""
            if self._progress is None:
                return
            try:
                v = float(value)
            except (TypeError, ValueError):
                v = -1.0
            if v < 0:
                self._progress.setVisible(False)
                return
            self._progress.setVisible(True)
            self._progress.setRange(0, 100)
            self._progress.setValue(int(round(max(0.0, min(1.0, v)) * 100)))

        def set_busy(self, on):
            # The statusbar's own transient message; the progress bar above is
            # the measured half.
            if self._status is None:
                return
            if on:
                self._status.showMessage("Working…")
            else:
                self._status.clearMessage()

    return _KdeShell


def shell(title: str, size=(1280, 900), min_size=(720, 560)):
    """Make the Plasma shell. Call only under `is_plasma()`."""
    cls = _build_shell_class()
    return cls(title, size=size, min_size=min_size)
