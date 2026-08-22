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
tree hosted in a `QQuickWidget` as the central widget. Every pixel of chrome is
drawn by whatever KStyle is configured — Oxygen today, Breeze or anything else
tomorrow, correctly, with no work here.

**The view is OPAQUE and draws the styled background itself.** Making the
QQuickWidget transparent so the parent shows through is the obvious way to
continue that one surface behind the content, and on this stack it punches a
hole in the window: the region stops being repainted, so windows dragged over
it leave trails inside it and it is missing from screenshots altogether. Both
spellings fail (`WA_TranslucentBackground`, and the transparent clearColor on
its own), and **no offscreen harness can catch it** — `QWidget.grab()`
re-renders through a fresh backing store while the fault is in the live one.
So the QML paints the background instead, from an image the style renders
(`_build_background_classes` → the `kdebg` provider, `qmlcommon/StyledBackground.qml`):
a proxy top-level QWidget with `WA_StyledBackground`, rendered into a QImage
and cropped to the view's rectangle in the window. Verified pixel-exact against
a real window's own background, 0 differing samples, and continuous across the
toolbar seam. 0.76 ms a render, re-requested only when the geometry, the
palette or the style changes.

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


def qt_version() -> str:
    from PySide6.QtCore import qVersion
    return qVersion()

# The button `state` vocabulary shared with the hyprvtb titlebar and
# DeskMenuBar.qml: 0 normal, 1 lit (a toggle that is on / the page you are on),
# 2 disabled. docs/DESIGN.md §12.1.
STATE_NORMAL = 0
STATE_LIT = 1
STATE_DISABLED = 2

# THE MENU VOCABULARY EVERY KDE PROGRAM SHARES.
#
# Kate, Konsole, Dolphin, Gwenview and Okular do not merely have menus with
# these names — they have them in this ORDER, with Settings second-to-last and
# Help last, whatever else is between. That ordering is most of what makes an
# unfamiliar KDE program navigable, so it is enforced here rather than left to
# the order an app happens to list its actions in. A group an app invents is
# kept, inserted before `settings` so the tail stays where hands expect it.
MENU_ORDER = ["file", "edit", "view", "go", "bookmarks", "tools", "settings", "help"]
MENU_TITLE = {
    "file": "&File", "edit": "&Edit", "view": "&View", "go": "&Go",
    "bookmarks": "&Bookmarks", "tools": "&Tools", "settings": "Se&ttings",
    "help": "&Help",
}


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
        apply_palette(app)
    return app


def apply_palette(app) -> None:
    """Put the KDE colour scheme into the widget palette, if it is not there.

    The two halves of this window take their colours from different places: the
    QML content resolves ours through `kdetheme.py`, and QQC2 controls resolve
    theirs through Kirigami — both of which read `kdeglobals` — while the
    menubar, toolbar and statusbar are QWidgets taking `QApplication.palette()`,
    which comes from the KDE platform theme. Where that plugin is missing the
    widgets fall back to Qt's default light palette while everything else stays
    on his dark scheme, and the result is not subtly wrong: it is white text on
    white, a toolbar that looks empty. Caught by rendering it offscreen, which
    is precisely the environment where no platform theme exists.

    So: compare the live window colour with what `kdeglobals` says, and only if
    they disagree build the palette ourselves. When the plugin IS loaded this
    function measures one colour and returns.
    """
    from PySide6.QtGui import QPalette, QColor
    ini = read_ini()

    def col(group, key, fallback=None):
        spec = (ini.get(group, {}) or {}).get(key)
        if not isinstance(spec, str):
            return QColor(fallback) if fallback else None
        parts = [p.strip() for p in spec.split(",")]
        try:
            vals = [int(float(p)) for p in parts[:3]]
        except ValueError:
            return QColor(fallback) if fallback else None
        if len(vals) < 3:
            return QColor(fallback) if fallback else None
        return QColor(*vals)

    window = col("Colors:Window", "BackgroundNormal")
    if window is None:
        return
    if app.palette().window().color() == window:
        return   # the platform theme already did this properly

    pal = QPalette(app.palette())
    text = col("Colors:Window", "ForegroundNormal", "#000000")
    view_bg = col("Colors:View", "BackgroundNormal", window.name())
    view_fg = col("Colors:View", "ForegroundNormal", text.name())
    btn_bg = col("Colors:Button", "BackgroundNormal", window.name())
    btn_fg = col("Colors:Button", "ForegroundNormal", text.name())
    sel_bg = col("Colors:Selection", "BackgroundNormal", "#3daee9")
    sel_fg = col("Colors:Selection", "ForegroundNormal", "#ffffff")
    tip_bg = col("Colors:Tooltip", "BackgroundNormal", view_bg.name())
    tip_fg = col("Colors:Tooltip", "ForegroundNormal", view_fg.name())
    dis_fg = col("Colors:Window", "ForegroundInactive", text.name())
    link = col("Colors:View", "ForegroundLink", "#2980b9")

    for role, colour in ((QPalette.Window, window), (QPalette.WindowText, text),
                         (QPalette.Base, view_bg), (QPalette.Text, view_fg),
                         (QPalette.AlternateBase, view_bg.darker(105)),
                         (QPalette.Button, btn_bg), (QPalette.ButtonText, btn_fg),
                         (QPalette.Highlight, sel_bg), (QPalette.HighlightedText, sel_fg),
                         (QPalette.ToolTipBase, tip_bg), (QPalette.ToolTipText, tip_fg),
                         (QPalette.Link, link),
                         (QPalette.PlaceholderText, dis_fg)):
        pal.setColor(QPalette.Active, role, colour)
        pal.setColor(QPalette.Inactive, role, colour)
        pal.setColor(QPalette.Disabled, role, colour)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, dis_fg)
    app.setPalette(pal)


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


def select_plasma_files(engine) -> None:
    """Turn on the `+plasma` file selector for an engine.

    Qt resolves `dir/+plasma/Foo.qml` in place of `dir/Foo.qml` whenever the
    selector is active, so an app ships a second implementation of a component
    beside the first and every call site picks the right one with no branch.
    That is what lets painter keep one `Root.qml` while its controls are ours in
    one session and the system style's in the other.
    """
    from PySide6.QtQml import QQmlFileSelector
    # PARENTED TO THE ENGINE, deliberately: the constructor's first argument is
    # the engine it selects for and the SECOND is the QObject parent. Leaving
    # that out gives the selector no owner, Python collects it moments later,
    # and every component then loads its unselected file — silently, with no
    # error and no warning. Measured: `QQmlFileSelector.get(engine)` came back
    # None immediately after constructing one.
    sel = QQmlFileSelector(engine, engine)
    sel.setExtraSelectors(["plasma"])


class KdeShell:
    """A `QMainWindow` hosting an app's QML tree, chromed like a KDE program.

    Deliberately NOT a QMainWindow subclass: apps hold it in a variable and the
    Qt object graph is an implementation detail. `window` is the QMainWindow,
    `view` the QQuickWidget, `handle` the QWindow every app already passes to
    `winstate` and uses to ask whether the user is looking at it.

    Built lazily by `shell()` — see the note on `_build_shell_class()`.
    """


def _build_background_classes():
    """The style's window background, as something QML can draw.

    Two objects: a `QQuickImageProvider` that renders it, and a small QObject
    the QML binds to for the current image URL. Split that way because the URL
    has to CHANGE for QML to re-request the image — the size, the view's offset
    inside the window and a serial are all in the path, so a resize or a palette
    change produces a new URL and the old one is never served from cache.
    """
    from PySide6.QtCore import QObject, QPoint, QRect, Property, Signal, QEvent
    from PySide6.QtGui import QImage, QRegion
    from PySide6.QtQuick import QQuickImageProvider
    from PySide6.QtWidgets import QWidget

    class _BgProvider(QQuickImageProvider):
        def __init__(self):
            super().__init__(QQuickImageProvider.Image)

        def requestImage(self, path, size, requested):
            # "winW,winH,offX,offY,viewW,viewH,dpr#serial"
            try:
                head = str(path).split("#")[0]
                win_w, win_h, off_x, off_y, vw, vh, dpr = (
                    float(p) for p in head.split(",")[:7])
            except (ValueError, IndexError):
                return QImage()
            win_w, win_h = max(1, int(win_w)), max(1, int(win_h))
            vw, vh = max(1, int(vw)), max(1, int(vh))
            dpr = dpr if dpr > 0 else 1.0

            # A top-level widget, never shown: Oxygen paints the window
            # background only for a real window (isWindow(), WA_StyledBackground,
            # Qt::Window) — which this is, whether or not it is on screen.
            proxy = QWidget()
            proxy.setAttribute(Qt.WA_StyledBackground, True)
            proxy.resize(win_w, win_h)

            img = QImage(int(win_w * dpr), int(win_h * dpr),
                         QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(0)
            proxy.render(img, QPoint(), QRegion(0, 0, win_w, win_h),
                         QWidget.DrawWindowBackground)

            crop = img.copy(QRect(int(off_x * dpr), int(off_y * dpr),
                                  int(vw * dpr), int(vh * dpr)))
            crop.setDevicePixelRatio(dpr)
            if size is not None:
                size.setWidth(crop.width())
                size.setHeight(crop.height())
            return crop

    class _StyledBackground(QObject):
        """`KdeBackground.source` — the URL of the styled background for the
        view's current geometry. Re-emitted on resize and on a palette or style
        change, which is every reason the image could go stale."""

        changed = Signal()

        def __init__(self, view, window, parent=None):
            super().__init__(parent)
            self._view = view
            self._window = window
            self._serial = 0
            view.installEventFilter(self)
            window.installEventFilter(self)

        def eventFilter(self, obj, ev):
            if ev.type() in (QEvent.Resize, QEvent.Move, QEvent.PaletteChange,
                             QEvent.ApplicationPaletteChange, QEvent.StyleChange):
                self.refresh()
            return False

        def refresh(self):
            self._serial += 1
            self.changed.emit()

        @Property(str, notify=changed)
        def source(self):
            win = self._window
            view = self._view
            off = view.mapTo(win, QPoint(0, 0))
            dpr = view.devicePixelRatioF() or 1.0
            return (f"image://kdebg/{win.width()},{win.height()},"
                    f"{off.x()},{off.y()},{view.width()},{view.height()},{dpr}"
                    f"#{self._serial}")

    return _BgProvider, _StyledBackground


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

            # THE VIEW IS OPAQUE, AND THE STYLE'S BACKGROUND IS DRAWN INSIDE IT.
            #
            # The obvious way to get the window's styled background — Oxygen's
            # gradient — behind this QML is to make the widget transparent and
            # let the parent show through. That does not work on this stack, and
            # it fails in a way no offscreen render can catch, because
            # `QWidget.grab()` re-renders through a fresh backing store while
            # the bug lives in the live one. Two rounds of it on his session:
            #
            #   * `WA_TranslucentBackground` + transparent clearColor — the
            #     attribute also flips WA_NoSystemBackground on (measured), so
            #     the area is never filled: content smears frame to frame and
            #     the pixels keep alpha 0.
            #   * transparent clearColor ALONE — same hole. The region is not
            #     repainted at all: other windows dragged over it leave trails
            #     *inside* it, and it is absent from screenshots entirely.
            #
            # So we stop asking for transparency. The widget stays opaque, and
            # the QML paints the real styled background itself, from an image
            # the STYLE renders (`_StyledBackground` below): a proxy top-level
            # QWidget with WA_StyledBackground, rendered into a QImage, cropped
            # to this view's rectangle within the window. Verified pixel-exact
            # against a real QMainWindow's own painted background — 0 differing
            # samples across the window. It is still Oxygen's own code drawing
            # its own gradient, and it still lines up seamlessly with the
            # menubar and toolbar above it, because it is a crop of the same
            # window-sized rendering.
            # AND THE QML HALF WEARS THE SAME PALETTE. Qt Quick Controls inside
            # a QQuickWidget do not inherit QApplication's palette on their own:
            # rendered offscreen against his dark scheme, the window came out
            # dark with light-grey spin boxes and near-black labels on it —
            # every control drawn from Qt's default light palette while the
            # widgets around them were correct. Handing the view the app's
            # palette propagates it down the QML item tree.
            from PySide6.QtWidgets import QApplication
            self.view.setPalette(QApplication.palette())
            # Not transparent (see above) — but not Qt's default WHITE either:
            # anything the styled background image does not cover for a frame
            # should read as the window, not as a flash.
            self.view.setClearColor(QApplication.palette().window().color())
            self.window.setCentralWidget(self.view)

            # The styled background, as an image provider plus the object QML
            # binds to for its URL. Installed here, before any QML loads, so the
            # app's own `engine()`/`context()` calls see them already there.
            provider_cls, bg_cls = _build_background_classes()
            self.view.engine().addImageProvider("kdebg", provider_cls())
            self.background = bg_cls(self.view, self.window)
            self.view.rootContext().setContextProperty("KdeBackground", self.background)

            self._toolbar = None
            self._status = None
            self._status_label = None
            self._status_right = None
            self._right_prop = "statusRight"
            self._progress = None
            self._status_timer = None
            self._line_prop = "statusLine"
            self._progress_prop = "statusProgress"
            self._actions = {}      # id -> QAction
            self._groups = {}       # group name -> QActionGroup (radio sets)
            self._docks = {}        # ident -> (QDockWidget, view, bg, item, comp)
            self._dialogs = {}      # ident -> (QDialog, view, bg, item, comp)
            self._hooks = {}        # button id -> a python answer to it
            self._dock_actions = [] # their toggleViewAction()s, for the View menu
            self._menu_order = []
            # First build decides whether the toolbar shows at all; after that
            # its visibility belongs to the user (Settings -> Show Toolbar).
            self._chrome_restored = False
            self._state_restored = False
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
            self._restore_state()
            self.window.show()
            return self.window.windowHandle()

        # ------------------------------------------------------- window state
        # A KDE program comes back the way it was left, and with docks that is
        # not optional: a panel dragged to the other edge, floated or closed has
        # to still be there next launch or the arranging was for nothing.
        # `saveState()` covers dock placement, float state, dock tabbing, the
        # splitter between dock and central widget, and toolbar visibility in
        # one blob — keyed on each widget's objectName, which is why `dock()`
        # and `_ensure_toolbar()` set one.
        def _settings(self):
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
            return QSettings("nixdesk", QApplication.applicationName() or "app")

        def _restore_state(self):
            if self._state_restored:
                return
            self._state_restored = True
            from PySide6.QtWidgets import QApplication
            # A HARNESS MUST NOT WRITE HIS WINDOW STATE. Every selftest runs
            # offscreen at a fixed size, and saving that on the way out would
            # hand him back a window the size of a test the next time he opened
            # the app — the same rule as everything else under
            # "Testing without interfering with the user".
            if QApplication.instance().platformName() == "offscreen":
                return
            st = self._settings()
            geom = st.value("window/geometry")
            state = st.value("window/state")
            if geom is not None:
                self.window.restoreGeometry(geom)
            if state is not None:
                # Version 1: bumped only if the chrome is renamed out from under
                # a saved blob, which Qt then ignores rather than misapplying.
                self.window.restoreState(state, 1)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._save_state)

        def _save_state(self):
            st = self._settings()
            st.setValue("window/geometry", self.window.saveGeometry())
            st.setValue("window/state", self.window.saveState(1))
            st.sync()

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
                # A QML `property var` arrives as a QJSValue, which is not
                # iterable in Python — same trap as `_entries` below.
                menu_order = root.property("menuOrder")
                if hasattr(menu_order, "toVariant"):
                    menu_order = menu_order.toVariant()
            self._menu_order = [str(m) for m in (menu_order or [])]
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
            # `actions` — the app's COMPLETE table — where it has one, because a
            # menubar is the complete set; `tbButtons` is the subset the
            # titlebar column has cells for and is all an app without the
            # bigger table publishes.
            raw = self._root.property("actions")
            if raw is None or (hasattr(raw, "isUndefined") and raw.isUndefined()):
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
            entries = self._entries()

            # THE CHROME WIDGETS FIRST, the menus second: the Settings menu
            # carries "Show Toolbar"/"Show Statusbar", which need something to
            # toggle.
            self._ensure_toolbar()
            self._ensure_status()

            bar = self.window.menuBar()
            bar.clear()
            # Not `self._actions.clear()` — a QAction is reused across rebuilds
            # so a menu row and a toolbar row are the SAME object and their
            # checked/enabled state can never disagree. Clearing here made every
            # rebuild mint new ones and leak the old shortcuts.

            # A separator belongs to the group of the row BEFORE it, which is
            # what carries the app's own grouping (generate/cancel | open) into
            # the menus. One that ends up at a group boundary is trimmed off
            # again by `_trim`.
            groups, cur = {}, None
            for e in entries:
                if e is None:
                    if cur is not None:
                        groups[cur].append(None)
                    continue
                g = str(e.get("menu", "") or "")
                if not g:
                    continue
                cur = g
                groups.setdefault(g, []).append(e)
            groups = {g: self._trim(items) for g, items in groups.items()}

            for g in self._order(groups):
                menu = bar.addMenu(MENU_TITLE.get(g, "&" + g.capitalize()))
                items = groups.get(g, [])
                prev_sep = True
                for e in items:
                    if e is None:
                        menu.addSeparator()
                        prev_sep = True
                        continue
                    menu.addAction(self._action_for(e))
                    prev_sep = False
                # THE VERBS EVERY KDE PROGRAM HAS, wherever the app's own array
                # did not provide them. Quit closes File the way it does in
                # every other window on this desktop; the two view toggles and
                # About are what a program with a name in the taskbar is
                # expected to answer for. All take the platform's standard
                # shortcut rather than a literal.
                if g == "file":
                    if not prev_sep:
                        menu.addSeparator()
                    menu.addAction(self._quit_action())
                elif g == "view" and self._dock_actions:
                    if not prev_sep:
                        menu.addSeparator()
                    for a in self._dock_actions:
                        menu.addAction(a)
                elif g == "settings":
                    if not prev_sep:
                        menu.addSeparator()
                    menu.addAction(self._toggle_action("toolbar"))
                    menu.addAction(self._toggle_action("statusbar"))
                elif g == "help":
                    menu.addAction(self._about_action())
                    menu.addAction(self._about_qt_action())

            # The toolbar: the app's own choice, `bar: true` per entry. A KDE
            # program's toolbar is its primary verbs, not everything it can do —
            # the menus are the complete set.
            tb = self._toolbar
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
            # A trailing separator is a line under the last row with nothing
            # after it — the toolbar's `bar:` filter makes one whenever the
            # table's last group is menu-only, as painter's Settings row is.
            acts = tb.actions()
            while acts and acts[-1].isSeparator():
                tb.removeAction(acts.pop())
            if not self._chrome_restored:
                tb.setVisible(bool(tb.actions()))
                self._chrome_restored = True
            self._sync_toggles()

        @staticmethod
        def _trim(items):
            """Drop leading, trailing and doubled separators — a menu's rows
            come from a filter over one flat table, so any of the three can be
            left behind by a row that went to a different menu."""
            out = []
            for e in items:
                if e is None and (not out or out[-1] is None):
                    continue
                out.append(e)
            while out and out[-1] is None:
                out.pop()
            return out

        def _order(self, groups):
            """The menus this window will have, in KDE's order. An app's own
            `menuOrder` decides only where its OWN groups sit among the ones
            MENU_ORDER does not name; File stays first and Settings/Help stay
            last regardless, because that is the part a user relies on."""
            named = [g for g in MENU_ORDER if g in groups or g in ("file", "help")]
            extra = [g for g in self._menu_order if g in groups and g not in MENU_ORDER]
            extra += [g for g in groups if g not in MENU_ORDER and g not in extra]
            if not extra:
                return named
            out = []
            for g in named:
                if g == "settings":
                    out.extend(extra)
                    extra = []
                out.append(g)
            return out + extra

        # ------------------------------------------------------------ widgets
        def _ensure_toolbar(self):
            from PySide6.QtWidgets import QToolBar
            if self._toolbar is None:
                tb = QToolBar("main", self.window)
                tb.setMovable(False)
                tb.setObjectName("mainToolBar")
                self.window.addToolBar(tb)
                self._toolbar = tb
            return self._toolbar

        def _ensure_status(self):
            """Dolphin's shape: what is happening on the LEFT, standing facts on
            the RIGHT. A status bar that packs both into one string is a status
            bar you have to read rather than glance at."""
            from PySide6.QtWidgets import QStatusBar, QLabel, QProgressBar
            if self._status is None:
                self._status = QStatusBar(self.window)
                self._status.setSizeGripEnabled(True)
                self._status_label = QLabel("")
                # addWidget, not addPermanentWidget: this is the message area,
                # and it gives way to a transient showMessage() the way every
                # other KDE status bar's does.
                self._status.addWidget(self._status_label, 1)
                self._progress = QProgressBar()
                self._progress.setMaximumWidth(160)
                self._progress.setTextVisible(False)
                self._progress.setVisible(False)
                self._status_right = QLabel("")
                self._status.addPermanentWidget(self._progress)
                self._status.addPermanentWidget(self._status_right)
                self.window.setStatusBar(self._status)
            return self._status

        def _toggle_action(self, which):
            """Show Toolbar / Show Statusbar — checkable, and checked FROM the
            widget rather than from a variable, so the menu cannot claim a bar
            is showing when it is not."""
            key = "__show_" + which
            act = self._actions.get(key)
            if act is None:
                label = "Show &Toolbar" if which == "toolbar" else "Show Status&bar"
                act = QAction(label, self.window)
                act.setCheckable(True)

                def toggled(on, w=which):
                    widget = self._toolbar if w == "toolbar" else self._status
                    if widget is not None:
                        widget.setVisible(on)

                act.toggled.connect(toggled)
                self._actions[key] = act
            return act

        def _sync_toggles(self):
            for which in ("toolbar", "statusbar"):
                act = self._actions.get("__show_" + which)
                widget = self._toolbar if which == "toolbar" else self._status
                if act is None or widget is None:
                    continue
                # isHidden(), not isVisible(): `bind_chrome` runs before
                # `show()`, and a child of an unshown window is not visible
                # however much it is going to be. isHidden() answers the
                # question actually being asked — was this bar switched off.
                act.blockSignals(True)
                act.setChecked(not widget.isHidden())
                act.blockSignals(False)

        def _quit_action(self):
            from PySide6.QtGui import QKeySequence
            act = self._actions.get("__quit")
            if act is None:
                from PySide6.QtWidgets import QApplication
                act = QAction(QIcon.fromTheme("application-exit"), "&Quit", self.window)
                act.setShortcut(QKeySequence.Quit)
                act.setShortcutContext(Qt.ApplicationShortcut)
                act.triggered.connect(QApplication.closeAllWindows)
                self.window.addAction(act)   # so Ctrl+Q works with no menu open
                self._actions["__quit"] = act
            return act

        def _about_action(self):
            act = self._actions.get("__about")
            if act is None:
                from PySide6.QtWidgets import QApplication, QMessageBox
                name = QApplication.applicationName() or "this program"

                def about():
                    QMessageBox.about(
                        self.window, f"About {name}",
                        f"<h3>{name}</h3>"
                        f"<p>Part of this desktop's own set of apps "
                        f"(<code>~/nix/apps/{name}</code>), running its live "
                        f"source.</p>"
                        f"<p>Qt {qt_version()} · style "
                        f"{QApplication.style().objectName()}</p>")

                act = QAction(QIcon.fromTheme("help-about"), f"&About {name}", self.window)
                act.triggered.connect(about)
                self._actions["__about"] = act
            return act

        def _about_qt_action(self):
            act = self._actions.get("__aboutqt")
            if act is None:
                from PySide6.QtWidgets import QApplication
                act = QAction("About &Qt", self.window)
                act.triggered.connect(lambda: QApplication.aboutQt())
                self._actions["__aboutqt"] = act
            return act

        def _action_for(self, e):
            """One QAction per button id, reused across rebuilds so a menu and a
            toolbar row are the same object — check state, enabled state and
            icon can then never disagree between the two."""
            from PySide6.QtGui import QKeySequence
            bid = str(e.get("id", ""))
            act = self._actions.get(bid)
            if act is None:
                act = QAction(self.window)
                act.triggered.connect(lambda _=False, i=bid: self._invoke(i))
                # Added to the window as well as to its menu, so its shortcut
                # works with no menu open — and so it survives a `menuBar.clear()`.
                self.window.addAction(act)
                self._actions[bid] = act
            # A row's label is the button's `menuText` if it has one, else its
            # TOOLTIP — never its two-character titlebar glyph (docs/DESIGN.md §7.6).
            act.setText(str(e.get("menuText") or e.get("tip") or e.get("label") or bid))
            act.setToolTip(str(e.get("tip") or ""))
            icon = str(e.get("icon") or "")
            if icon:
                act.setIcon(QIcon.fromTheme(icon))

            # THE SHORTCUT IS THIS FACE'S ALONE. The app's QML `Shortcut`s stand
            # down under Plasma (two owners of one sequence in one window is an
            # ambiguous shortcut, and Qt answers those by firing NEITHER), so
            # whatever the table says here is what the key does.
            sc = str(e.get("shortcut") or "")
            if sc and act.shortcut().isEmpty():
                if sc.startswith("@"):
                    std = getattr(QKeySequence.StandardKey, sc[1:], None)
                    if std is not None:
                        act.setShortcut(QKeySequence(std))
                else:
                    act.setShortcut(QKeySequence(sc))
                act.setShortcutContext(Qt.WindowShortcut)

            state = int(e.get("state", STATE_NORMAL) or 0)
            act.setEnabled(state != STATE_DISABLED)
            checkable = bool(e.get("checkable")) or state == STATE_LIT or act.isCheckable()
            act.setCheckable(checkable)
            if checkable:
                act.setChecked(state == STATE_LIT)

            # A radio set — `group:` on two or more rows (a pane switcher, a
            # zoom mode). Exclusive, so the pair cannot both be off, which two
            # independent checkboxes can.
            gname = str(e.get("group") or "")
            if gname and act.actionGroup() is None:
                from PySide6.QtGui import QActionGroup
                grp = self._groups.get(gname)
                if grp is None:
                    grp = QActionGroup(self.window)
                    grp.setExclusive(True)
                    self._groups[gname] = grp
                grp.addAction(act)
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
            fn = self._hooks.get(bid)
            if fn is not None:
                fn()
                return
            QMetaObject.invokeMethod(self._root, "tbAction", Q_ARG("QVariant", bid))

        # -------------------------------------------------------------- docks
        def dock(self, ident, title, qml_path, area=None, shortcut=None,
                 sizes=None, props=None):
            """Put a QML file in a real `QDockWidget` beside the central widget.

            This is the half of the Plasma face that makes an app of ours behave
            like Dolphin or Okular rather than merely look like one: the panel
            floats, tabs with another dock, drags to a different edge, and its
            placement is saved with the window. Returns the loaded root ITEM, so
            the caller can hand it whatever it needs (`app`, usually).

            Three things this has to get right, all of them silent when wrong:

            * **One engine, two views.** `QQuickWidget(engine, ...)` shares the
              app's engine, so the dock sees the same `App`, `Theme`, `Prefs`
              and `Gallery` context properties. A QQuickWidget left to make its
              own engine sees none of them and comes up blank, with no error.
            * **Its own styled background.** `KdeBackground` publishes a crop of
              the window's styled rendering for ONE view's rectangle. The dock
              gets its own object in its own child context, or it would draw the
              central widget's crop and the gradient would step at the seam.
            * **The view is opaque**, for the reason in this module's header —
              a transparent QQuickWidget punches a hole in the window.
            """
            from PySide6.QtCore import QUrl
            from PySide6.QtQml import QQmlContext, QQmlComponent
            from PySide6.QtWidgets import QApplication, QDockWidget
            from PySide6.QtQuickWidgets import QQuickWidget

            if area is None:
                area = Qt.RightDockWidgetArea

            view = QQuickWidget(self.view.engine(), None)
            view.setResizeMode(QQuickWidget.SizeRootObjectToView)
            view.setPalette(QApplication.palette())
            view.setClearColor(QApplication.palette().window().color())

            ctx = QQmlContext(self.view.engine().rootContext(), view)
            _, bg_cls = _build_background_classes()
            bg = bg_cls(view, self.window)
            ctx.setContextProperty("KdeBackground", bg)

            url = QUrl.fromLocalFile(str(qml_path))
            comp = QQmlComponent(self.view.engine(), url)
            # createWithInitialProperties, not create-then-setProperty: the
            # pane's bindings are evaluated once at creation, and a pane created
            # with no `app` spends that first pass reading an empty model —
            # which reached painter's registry as a NaN frame count before the
            # assignment landed a tick later.
            item = comp.createWithInitialProperties(dict(props or {}), ctx)
            if item is None:
                raise RuntimeError("dock %r failed to load %s:\n%s"
                                   % (ident, qml_path, comp.errorString()))
            view.setContent(url, comp, item)

            dw = QDockWidget(title, self.window)
            dw.setObjectName("dock_" + ident)   # saveState() keys on this
            dw.setWidget(view)
            dw.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.window.addDockWidget(area, dw)
            if sizes:
                view.setMinimumWidth(int(sizes[0]))
            self._docks[ident] = (dw, view, bg, item, comp)

            # The View menu's "Show <panel>" row is the dock's OWN action, so it
            # cannot disagree with whether the dock is up — including when it is
            # closed with its titlebar [x] rather than from the menu.
            act = dw.toggleViewAction()
            act.setText(title)
            if shortcut:
                from PySide6.QtGui import QKeySequence
                act.setShortcut(QKeySequence(shortcut))
                act.setShortcutContext(Qt.WindowShortcut)
                self.window.addAction(act)
            self._dock_actions.append(act)
            if self._root is not None:      # bind_chrome may not have run yet
                self._rebuild()
            return item

        # ------------------------------------------------------------ dialogs
        def dialog(self, ident, title, qml_path, size=(460, 520), props=None):
            """A modeless QDialog hosting a QML file — "Configure <app>…".

            Built and kept, not rebuilt: reopening returns the same window with
            whatever was scrolled or typed in it still there. Same three rules
            as `dock` (shared engine, own `KdeBackground`, initial properties),
            plus a Close button, because a dialog with no way out but the
            titlebar is not one.
            """
            from PySide6.QtCore import QUrl
            from PySide6.QtQml import QQmlContext, QQmlComponent
            from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout,
                                           QDialogButtonBox)
            from PySide6.QtQuickWidgets import QQuickWidget

            got = self._dialogs.get(ident)
            if got is not None:
                return got[0]

            dlg = QDialog(self.window)
            dlg.setWindowTitle(title)
            dlg.resize(*size)

            view = QQuickWidget(self.view.engine(), dlg)
            view.setResizeMode(QQuickWidget.SizeRootObjectToView)
            view.setPalette(QApplication.palette())
            view.setClearColor(QApplication.palette().window().color())

            ctx = QQmlContext(self.view.engine().rootContext(), view)
            _, bg_cls = _build_background_classes()
            bg = bg_cls(view, dlg)
            ctx.setContextProperty("KdeBackground", bg)

            url = QUrl.fromLocalFile(str(qml_path))
            comp = QQmlComponent(self.view.engine(), url)
            item = comp.createWithInitialProperties(dict(props or {}), ctx)
            if item is None:
                raise RuntimeError("dialog %r failed to load %s:\n%s"
                                   % (ident, qml_path, comp.errorString()))
            view.setContent(url, comp, item)

            box = QDialogButtonBox(QDialogButtonBox.Close, dlg)
            box.rejected.connect(dlg.hide)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 6, 6)
            lay.addWidget(view, 1)
            lay.addWidget(box)

            self._dialogs[ident] = (dlg, view, bg, item, comp)
            return dlg

        def show_dialog(self, ident, *args, **kw):
            dlg = self.dialog(ident, *args, **kw) if args or kw \
                else self._dialogs[ident][0]
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return dlg

        # ------------------------------------------------------- action hooks
        def on_action(self, bid, fn):
            """Answer a button id HERE instead of in the QML.

            One caller so far and one reason: `set` means "slide the settings
            drawer out" under Hyprland and "open Configure painter…" under
            Plasma, and that is a difference in the SHELL, not in the app — so
            it is answered by the shell rather than by a session branch in
            `tbAction`.
            """
            self._hooks[bid] = fn

        # ------------------------------------------------------------- probe
        def dump_chrome(self):
            """The menubar, the toolbar and the statusbar as text.

            The only way to check this face without looking at it: a menu is
            not on screen until it is opened, so no render can show what is in
            one. Prints menu -> row, with the shortcut, and `[x]`/`[ ]` for a
            checkable row and `(disabled)` for a greyed one.
            """
            out = []
            for act in self.window.menuBar().actions():
                menu = act.menu()
                out.append(str(act.text()))
                for a in (menu.actions() if menu is not None else []):
                    if a.isSeparator():
                        out.append("    ---")
                        continue
                    flag = ("[x] " if a.isChecked() else "[ ] ") if a.isCheckable() else ""
                    sc = a.shortcut().toString()
                    out.append("    %s%s%s%s" % (
                        flag, a.text(),
                        ("  " + sc) if sc else "",
                        "" if a.isEnabled() else "  (disabled)"))
            tb = self._toolbar
            out.append("toolbar%s" % ("" if tb is not None and tb.isVisible() else " (hidden)"))
            for a in (tb.actions() if tb is not None else []):
                out.append("    ---" if a.isSeparator() else "    %s%s" % (
                    a.text(), "" if a.isEnabled() else "  (disabled)"))
            st = self._status
            out.append("statusbar: %r | %r%s" % (
                self._status_label.text() if self._status_label is not None else "",
                self._status_right.text() if self._status_right is not None else "",
                "" if st is not None and st.isVisible() else " (hidden)"))
            return "\n".join(out)

        # --------------------------------------------------------- statusbar
        def bind_status(self, line_prop="statusLine", progress_prop="statusProgress",
                        right_prop="statusRight"):
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
            self._right_prop = right_prop
            root = self._root
            if root is None:
                return
            props = [line_prop, progress_prop]
            # The right-hand channel is optional: an app that publishes no
            # `statusRight` gets an empty permanent label and no poll for it.
            if root.property(right_prop) is not None:
                props.append(right_prop)
            else:
                self._right_prop = None
            bound = 0
            for prop in props:
                sig = getattr(root, prop + "Changed", None)
                if sig is not None and hasattr(sig, "connect"):
                    sig.connect(self._pull_status)
                    bound += 1
            if bound < len(props):
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
            if self._right_prop and self._status_right is not None:
                self._status_right.setText(str(root.property(self._right_prop) or ""))

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
            """Nothing to say here any more, deliberately.

            This used to `showMessage("Working…")`, which COVERS the message
            area — so the moment a job started, the status line the app had
            carefully composed was replaced by a word that says less. The
            progress bar is the busy indicator; the line stays the app's."""
            return

    return _KdeShell


def shell(title: str, size=(1280, 900), min_size=(720, 560)):
    """Make the Plasma shell. Call only under `is_plasma()`."""
    cls = _build_shell_class()
    return cls(title, size=size, min_size=min_size)
