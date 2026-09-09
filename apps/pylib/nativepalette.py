"""Forward native Qt/KDE colour roles in Plasma; never manufacture a palette.

The wallpaper Palette classes remain the Hyprland implementation. This adapter
reads QApplication's palette on demand, including its disabled roles, and
publishes paletteChanged to QML and Python consumers. KDE semantic colours,
which QPalette does not expose, are read verbatim from their KColorScheme group.
No generated Theme.qml, contrast adjustment, colour mixing, or wallpaper
fallback participates in the Plasma path.
"""
from PySide6.QtCore import QObject, Property, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from kdetheme import is_plasma, read_ini

# Compatibility names describe CONTENT. Chrome must use window/windowText,
# buttons button/buttonText, and selections highlight/highlightedText.
ROLES = {
    "bg": QPalette.Base, "bgAlt": QPalette.AlternateBase,
    "border": QPalette.Mid, "accent": QPalette.Text,
    "dim": QPalette.PlaceholderText, "text": QPalette.Text,
    "textDim": QPalette.PlaceholderText, "highlight": QPalette.Highlight,
    "window": QPalette.Window, "windowText": QPalette.WindowText,
    "base": QPalette.Base, "alternateBase": QPalette.AlternateBase,
    "button": QPalette.Button, "buttonText": QPalette.ButtonText,
    "highlightedText": QPalette.HighlightedText,
    "toolTipBase": QPalette.ToolTipBase, "toolTipText": QPalette.ToolTipText,
    "link": QPalette.Link, "linkVisited": QPalette.LinkVisited,
    "focus": QPalette.Accent,
}
SEMANTIC = {"ok": "ForegroundPositive", "warn": "ForegroundNeutral",
            "crit": "ForegroundNegative", "info": "ForegroundLink"}


class NativePalette(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QGuiApplication.instance()
        if app is None:
            raise RuntimeError("native palette requires a Qt application")
        self._semantic = {}
        self._load()
        app.paletteChanged.connect(self._load)

    def _load(self, *_):
        self._semantic = read_ini().get("Colors:View", {})
        self.changed.emit()
        # Existing browser/metadata consumers use this notification API.
        from kdetheme import _palette_callbacks
        for callback in tuple(_palette_callbacks):
            callback()
        return True

    def _c(self, name):
        palette = QGuiApplication.palette()
        if name == "inactive":
            return palette.color(QPalette.Inactive, QPalette.Text)
        if name == "disabledText":
            return palette.color(QPalette.Disabled, QPalette.Text)
        if name in SEMANTIC:
            raw = self._semantic.get(SEMANTIC[name], "")
            try:
                values = [int(part) for part in raw.split(",")]
                if len(values) == 3 and all(0 <= v <= 255 for v in values):
                    return QColor(*values)
            except ValueError:
                pass
            return palette.color(QPalette.Text)
        return palette.color(ROLES[name])

    def color(self, name):
        return self._c(name).name()

    def hex(self, name):
        return self.color(name)

    @property
    def _colors(self):
        return {name: self.color(name) for name in (*ROLES, *SEMANTIC)}

    native = Property(bool, lambda self: True, constant=True)
    for _name in (*ROLES, *SEMANTIC, "inactive", "disabledText"):
        locals()[_name] = Property(QColor, lambda self, n=_name: self._c(n), notify=changed)
    del _name


def session_palette(wallpaper_class):
    """Select the native implementation before any wallpaper reader is built."""
    class SessionPalette(wallpaper_class):
        def __new__(cls, path, parent=None):
            if is_plasma():
                return NativePalette(parent)
            return super().__new__(cls)
    SessionPalette.__name__ = wallpaper_class.__name__
    SessionPalette.__qualname__ = wallpaper_class.__qualname__
    return SessionPalette
