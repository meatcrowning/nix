"""Where the 4chan re-skin's CSS comes from — one builder, three consumers.

`chantheme.css()` is the SHEET; this is the part that decides which palette it
is built from. Split out of `tools/chan-userscript.py` when the Vivaldi side
stopped being baked-only: the userscript generator, the loopback courier
(`tools/chan-theme-server.py`) and anything else asking for "the current 4chan
sheet" must all answer identically, and a dash in a filename is not importable.

The palette source follows the same rule the apps do (`kdetheme.is_plasma`):
the KDE colour scheme in a Plasma session — with the KStyle's gradients and
bevels on top when the style draws them — and the panel's wallpaper palette in
the Hyprland one, where DESIGN.md §2's "no gradients" holds and the sheet stays
flat.
"""
from __future__ import annotations

import os
import re
import zlib
from pathlib import Path

import chantheme
import kdetheme

PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"

# `readonly property color bg: "#000000"` — the panel's palette literals, the
# same shape every app's Palette parses (and the same one kdetheme writes).
_COLOR = re.compile(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"')


def panel_palette(path=PANEL_THEME) -> dict:
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for name, value in _COLOR.findall(text):
        out.setdefault(name, value[:7])
    return out


def palette(source=None):
    """(twelve-token palette, provenance) for the requested session face.

    Web sheets other than OneeChan need the same live source decision but not
    OneeChan's optional KStyle-relief block.  Keep that decision here so a
    second browser theme cannot quietly diverge from the desktop/4chan source.
    """
    plasma = kdetheme.is_plasma() if source is None else (source == "plasma")
    if plasma:
        colors = kdetheme.kde_palette()
        if colors:
            pal = {k: kdetheme._hex(v) for k, v in colors.items()}
            chrome = kdetheme.kde_chrome()
            style = chrome["style"] if chrome else kdetheme.kde_widget_style()
            return (pal, "KDE colour scheme (%s, %s)"
                    % (style or "unknown style",
                       "with the style's relief" if chrome else "flat style"))
    pal = panel_palette()
    if not pal:
        raise SystemExit("no palette: neither a readable kdeglobals nor %s" % PANEL_THEME)
    return (pal, "panel wallpaper palette (flat, per DESIGN.md §2)")


def build_css(source=None):
    """(OneeChan CSS, provenance) for the requested session face."""
    pal, provenance = palette(source)
    chrome = kdetheme.kde_chrome() if (kdetheme.is_plasma() if source is None
                                       else source == "plasma") else None
    return chantheme.css(pal.__getitem__, chrome), provenance


def stamp(css: str) -> str:
    """The content tag both the courier's ETag and the userscript's @version
    are derived from. Content-derived, never a clock: a rebuild of an unchanged
    palette must not look like a change."""
    return "%d" % (zlib.crc32(css.encode("utf-8")) % 100000)


# 127.0.0.1 only, and the number is duplicated in exactly one other place — the
# baked @connect line of the userscript, which reads it from here at bake time.
PORT = int(os.environ.get("CHAN_THEME_PORT") or 8791)
