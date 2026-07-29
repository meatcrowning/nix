#!/usr/bin/env python3
"""font-demo - a three-way specimen window for the pixel-font decision.

He asked for it in these words:

    "i want you to render a font display example, like how fonts are normally
     demo'd, for all options. basically just open a window that is divided into
     enough sections to display each option, and then ill choose."

So: three columns, same content in each, on his actual screen, in the desktop's
own idiom (docs/DESIGN.md - black bg, the live wal palette, square corners,
NativeRendering + PreferFullHinting + no antialias, pixel sizes).

THIS CHANGES NOTHING ABOUT THE RUNNING DESKTOP. The three faces are loaded
privately with QFontDatabase.addApplicationFont out of ~/.cache/font-demo (built
by build-fonts.py); nothing is written to ~/.local/share/fonts, fontconfig is
untouched, and home/pkgs/desktop/font.nix is not edited. Close the window and
the machine is exactly as it was.

The three candidates - see docs/DESIGN.md S2.3 for why the cmap is the whole
question:

  1. CURRENT             255 cps. 88 codepoints the desktop's own glyph tables
                         want are missing, 43 of them ordinary Latin-1 accented
                         capitals. Each one makes Qt fall back for that single
                         character, which takes the fallback's taller ascent and
                         CLIPS the row under FixedHeight.
  2. MERGED, with U+2026 781 cps. Printable ASCII measured identical to CURRENT
                         at 10/12/15/17/20/24 px (0 differing pixels). Having a
                         real ellipsis, Qt stops substituting three periods, so
                         ~45 Text.elide sites switch to a one-cell glyph.
  3. MERGED, no U+2026   Same, minus the ellipsis, so elision still renders
                         "..." and existing text is literally unchanged.

The only difference between 2 and 3 is that elision, which is why the window
gives it its own row.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Property, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

HERE = Path(__file__).resolve().parent
FONT_DIR = Path(os.environ.get("FONT_DEMO_DIR", Path.home() / ".cache" / "font-demo"))
THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"

# Shipped values from the panel's Theme.qml; used only if it cannot be read.
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120908", "border": "#381a16",
    "accent": "#e69f97", "dim": "#542e2a", "text": "#e69f97",
    "textDim": "#99625c", "highlight": "#210f0d", "warn": "#cc7b72",
    "crit": "#fa7f70", "ok": "#eba39b",
}


class Palette(QObject):
    """The live wallpaper palette, parsed out of the panel's Theme.qml.

    Same regex the six apps use: wal-set.sh writes the colours there as string
    literals, so they can be read without evaluating any QML.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = dict(PALETTE_DEFAULTS)
        try:
            txt = THEME.read_text(encoding="utf-8")
        except OSError:
            return
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            if m.group(1) in self._c:
                self._c[m.group(1)] = m.group(2)

    def _q(self, k):
        return QColor(self._c[k])

    @Property(QColor, notify=changed)
    def bg(self): return self._q("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._q("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._q("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._q("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._q("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._q("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._q("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._q("highlight")
    @Property(QColor, notify=changed)
    def warn(self): return self._q("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._q("crit")
    @Property(QColor, notify=changed)
    def ok(self): return self._q("ok")


class Fonts(QObject):
    """The three candidate families, loaded privately into this process only."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fam = {}
        for key, fname in (("current", "current.ttf"),
                           ("merged", "merged.ttf"),
                           ("noell", "merged-noellipsis.ttf")):
            path = FONT_DIR / fname
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid < 0:
                sys.exit(f"could not load {path} - run build-fonts.py first")
            fams = QFontDatabase.applicationFontFamilies(fid)
            if not fams:
                sys.exit(f"{path} loaded but exposed no family")
            self._fam[key] = fams[0]

    @Property(str, notify=changed)
    def current(self): return self._fam["current"]
    @Property(str, notify=changed)
    def merged(self): return self._fam["merged"]
    @Property(str, notify=changed)
    def noell(self): return self._fam["noell"]


def ensure_fonts():
    """Build the three faces if the cache is cold. Idempotent."""
    need = [f for f in ("current.ttf", "merged.ttf", "merged-noellipsis.ttf")
            if not (FONT_DIR / f).exists()]
    if not need:
        return
    sys.exit(
        "missing " + ", ".join(need) + f" in {FONT_DIR}\n"
        "run tools/font-demo/font-demo.sh, which builds them first"
    )


def main():
    ensure_fonts()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("font-demo")
    app.setDesktopFileName("font-demo")

    palette = Palette()
    fonts = Fonts()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    # Keep python-side references for the process lifetime, or the QObjects are
    # collected and every binding reading them goes null (the classic
    # setContextProperty-GC bug that renders everything black).
    ctx.setContextProperty("Wal", palette)
    ctx.setContextProperty("Fonts", fonts)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        sys.exit("QML failed to load")
    app._keep = (palette, fonts, engine)

    # Self-check hook, for verifying the sheet actually drew without putting it
    # on his screen: FONT_DEMO_GRAB=/path.png renders offscreen, saves, quits.
    # (QT_QPA_PLATFORM=offscreen alongside it.) Never used by the normal launch.
    grab = os.environ.get("FONT_DEMO_GRAB")
    if grab:
        from PySide6.QtCore import QTimer
        from PySide6.QtQuick import QQuickWindow
        import shiboken6

        # rootObjects() hands back a plain QWindow wrapper; cast it back to the
        # QQuickWindow it really is, which is the class that can grab.
        win = shiboken6.wrapInstance(
            shiboken6.getCppPointer(engine.rootObjects()[0])[0], QQuickWindow
        )

        def shoot():
            img = win.grabWindow()
            img.save(grab)
            print(f"grabbed {img.width()}x{img.height()} -> {grab}")
            app.quit()

        QTimer.singleShot(1500, shoot)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
