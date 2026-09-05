"""Icon-theme and QML-selector setup for the shared Plasma application face."""

from __future__ import annotations

import os

from PySide6.QtGui import QIcon

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


def select_plasma_files(engine, extra=()) -> None:
    """Turn on the ``+plasma`` QML file selector for an engine."""
    from PySide6.QtQml import QQmlFileSelector

    # Both arguments are intentional: without the QObject parent Python may
    # collect the selector and silently return the engine to unselected files.
    selector = QQmlFileSelector(engine, engine)
    selector.setExtraSelectors([*extra, "plasma"])
