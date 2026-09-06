"""Icon-theme and QML-selector setup for the shared Plasma application face."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPalette, QPixmap

from kdetheme import read_ini


def icon_theme_name() -> str:
    """Return the KDE icon theme, falling back from look-and-feel to Breeze."""
    ini = read_ini()
    name = (ini.get("Icons", {}) or {}).get("Theme", "").strip()
    if name:
        return name
    lnf = (ini.get("KDE", {}) or {}).get("LookAndFeelPackage", "").lower()
    return "oxygen" if "oxygen" in lnf else "breeze"


def icon_search_paths() -> list:
    """Return every existing ``icons`` directory named by the XDG data dirs."""
    dirs = []
    home_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.append(home_data)
    dirs += (os.environ.get("XDG_DATA_DIRS")
             or "/usr/local/share:/usr/share").split(":")
    out = []
    for directory in dirs:
        directory = (directory or "").strip()
        if not directory:
            continue
        path = os.path.join(directory, "icons")
        if os.path.isdir(path) and path not in out:
            out.append(path)
    return out


def apply_icon_theme() -> None:
    """Complete Qt's icon setup without overriding the platform theme."""
    have = list(QIcon.themeSearchPaths())
    for path in icon_search_paths():
        if path not in have:
            have.append(path)
    QIcon.setThemeSearchPaths(have)
    if not QIcon.themeName():
        QIcon.setThemeName(icon_theme_name())
    if not QIcon.fallbackThemeName():
        QIcon.setFallbackThemeName("breeze")


# Oxygen's action artwork is raster and deliberately coloured, so its
# FollowsColorScheme=true index flag has nothing drawable to apply a scheme to.
# Replace only Oxygen's blue material band; its highlights, shadows and semantic
# colours survive. The palette is live: kdeshell refreshes these QIcons on every
# ApplicationPaletteChange from the wallpaper scheme writer.
_ICON_SIZES = (16, 22, 32, 48, 64, 128, 256)


def themed_icon(name: str, palette: QPalette | None = None) -> QIcon:
    """Return a selectively palette-coloured freedesktop action icon.

    Only Oxygen's blue is remapped to the applicable palette role. A null lookup
    stays null so the caller keeps Qt's ordinary missing-icon behaviour.
    """
    source = QIcon.fromTheme(name)
    if source.isNull():
        return source
    palette = palette or QGuiApplication.palette()
    out = QIcon()
    modes = (
        (QIcon.Normal, QPalette.Active, QPalette.ButtonText),
        (QIcon.Active, QPalette.Active, QPalette.ButtonText),
        (QIcon.Selected, QPalette.Active, QPalette.HighlightedText),
        (QIcon.Disabled, QPalette.Disabled, QPalette.ButtonText),
    )
    for size in _ICON_SIZES:
        for mode, group, role in modes:
            pixmap = source.pixmap(QSize(size, size), mode)
            if pixmap.isNull():
                continue
            image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
            colour = QColor(palette.color(group, role))
            target_hue, target_sat, _, _ = colour.getHsvF()
            if target_sat <= 0:
                target_hue = 0.0
            for y in range(image.height()):
                for x in range(image.width()):
                    pixel = image.pixelColor(x, y)
                    hue, saturation, value, alpha = pixel.getHsvF()
                    if alpha <= 0 or not (0.50 <= hue <= 0.72 and saturation >= 0.18):
                        continue
                    image.setPixelColor(x, y, QColor.fromHsvF(target_hue, target_sat,
                                                               value, alpha))
            out.addPixmap(QPixmap.fromImage(image), mode)
    return out


def select_plasma_files(engine, extra=()) -> None:
    """Turn on the ``+plasma`` QML file selector for an engine."""
    from PySide6.QtQml import QQmlFileSelector

    # Both arguments are intentional: without the QObject parent Python may
    # collect the selector and silently return the engine to unselected files.
    selector = QQmlFileSelector(engine, engine)
    selector.setExtraSelectors([*extra, "plasma"])
