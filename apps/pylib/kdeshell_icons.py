"""Icon-theme and QML-selector setup for the shared Plasma application face."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPalette, QPixmap, QPainter, QPainterPath, QPen

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
# Menus and toolbars request small action artwork.  Rendering Oxygen's raster
# icons at 128 and 256 here made every new QAction walk another 327,680 pixels
# in Python before its window could be shown (12.61s for player's first chrome
# build on book).  Qt can scale the 64px rendition for the uncommon larger
# request; eagerly manufacturing those two sizes buys no visible shell detail.
_ICON_SIZES = (16, 22, 32, 48, 64)
_THEMED_CACHE = {}
_DISK_CACHE_VERSION = "2"


def _disk_cache_dir(key) -> Path:
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "kdeshell-icons" / _DISK_CACHE_VERSION / digest


def _disk_cached_icon(key) -> QIcon | None:
    directory = _disk_cache_dir(key)
    out = QIcon()
    modes = (QIcon.Normal, QIcon.Active, QIcon.Selected, QIcon.Disabled)
    paths = [(size, mode, directory / f"{size}-{mode.value}.png")
             for size in _ICON_SIZES for mode in modes]
    if not paths or not all(path.is_file() for _, _, path in paths):
        return None
    for _size, mode, path in paths:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        out.addPixmap(pixmap, mode)
    return out


def _favourite_icon(filled: bool, palette: QPalette) -> QIcon:
    """Player's compact, flat heart; preserve its state in every icon mode."""
    path = QPainterPath()
    path.moveTo(12, 20)
    path.cubicTo(9, 17, 3, 13, 3, 8)
    path.cubicTo(3, 3, 9, 2, 12, 7)
    path.cubicTo(15, 2, 21, 3, 21, 8)
    path.cubicTo(21, 13, 15, 17, 12, 20)
    path.closeSubpath()
    icon = QIcon()
    for size in _ICON_SIZES:
        for mode, group in ((QIcon.Normal, QPalette.Active),
                            (QIcon.Active, QPalette.Active),
                            (QIcon.Selected, QPalette.Active),
                            (QIcon.Disabled, QPalette.Disabled)):
            role = QPalette.Highlight if filled else QPalette.ButtonText
            if mode == QIcon.Selected:
                role = QPalette.HighlightedText
            colour = palette.color(group, role)
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(size / 24, size / 24)
            painter.setPen(QPen(colour, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(colour if filled else Qt.NoBrush)
            painter.drawPath(path)
            painter.end()
            icon.addPixmap(pixmap, mode)
    return icon


def themed_icon(name: str, palette: QPalette | None = None) -> QIcon:
    """Return a selectively palette-coloured freedesktop action icon.

    Only Oxygen's blue is remapped to the applicable palette role. A null lookup
    stays null so the caller keeps Qt's ordinary missing-icon behaviour.
    """
    palette = palette or QGuiApplication.palette()
    if name in ("player-heart-filled", "player-heart-outline"):
        return _favourite_icon(name.endswith("filled"), palette)
    groups_roles = (
        (QPalette.Active, QPalette.ButtonText),
        (QPalette.Active, QPalette.HighlightedText),
        (QPalette.Disabled, QPalette.ButtonText),
    )
    cache_key = (name, QIcon.themeName(), tuple(
        palette.color(group, role).rgba() for group, role in groups_roles))
    cached = _THEMED_CACHE.get(cache_key)
    if cached is not None:
        return QIcon(cached)
    cached = _disk_cached_icon(cache_key)
    if cached is not None:
        _THEMED_CACHE[cache_key] = QIcon(cached)
        return cached

    source = QIcon.fromTheme(name)
    if source.isNull():
        return source
    out = QIcon()
    modes = (
        (QIcon.Normal, QPalette.Active, QPalette.ButtonText),
        (QIcon.Active, QPalette.Active, QPalette.ButtonText),
        (QIcon.Selected, QPalette.Active, QPalette.HighlightedText),
        (QIcon.Disabled, QPalette.Disabled, QPalette.ButtonText),
    )
    directory = _disk_cache_dir(cache_key)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = None
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
            if directory is not None:
                image.save(str(directory / f"{size}-{mode.value}.png"), "PNG")
    # QAction rows reuse names between menus and toolbars, and palette refreshes
    # ask for the same set again.  QIcon copies are implicitly shared, so this
    # avoids repeating the Python pixel walk without retaining image copies.
    if len(_THEMED_CACHE) >= 256:
        _THEMED_CACHE.clear()
    _THEMED_CACHE[cache_key] = QIcon(out)
    return out


def select_plasma_files(engine, extra=()) -> None:
    """Turn on the ``+plasma`` QML file selector for an engine."""
    from PySide6.QtQml import QQmlFileSelector

    # Both arguments are intentional: without the QObject parent Python may
    # collect the selector and silently return the engine to unselected files.
    selector = QQmlFileSelector(engine, engine)
    selector.setExtraSelectors([*extra, "plasma"])
