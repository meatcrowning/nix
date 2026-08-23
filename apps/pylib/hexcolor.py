"""Hex colour arithmetic, Qt-free.

The sheets this desktop injects into browsers it does not own (`chantheme.py`,
`scrollcss.py`, `vivaldichrome.py`) all shade and mix the same palette, and
none of them may import Qt — they run from a plain `python3` with no app, no
QGuiApplication and no browser. `kdetheme.py` has its own copies of some of
this against RGB TUPLES, for the palette it builds; these work on the `#rrggbb`
strings the sheets actually emit.

LIGHTNESS IS MULTIPLIED, NOT OFFSET. Every KDE style shades in HCY, which
compresses as a scheme darkens: a measured sweep of Oxygen across six schemes
(window lightness 0.06 to 1.0) fits a near-constant RATIO and no constant
delta at all. See `tools/oxygen-scrollbar-probe.py`.
"""
from __future__ import annotations

import colorsys


def rgb(hexstr):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hex_(values):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in values)


def lum(hexstr):
    return colorsys.rgb_to_hls(*(c / 255.0 for c in rgb(hexstr)))[1]


def scale_l(hexstr, factor, floor=0.0, ceil=1.0):
    """`hexstr` with its HLS lightness multiplied — hue and saturation kept."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb(hexstr)))
    l = max(floor, min(ceil, l * factor))
    return hex_(tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s)))


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return hex_(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def relative_luminance(hexstr):
    """WCAG relative luminance, for picking a readable foreground."""
    def channel(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb(hexstr))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(background, *candidates):
    """The first candidate that clears 4.5:1 on `background`, else the best of
    black and white — never a foreground he cannot read."""
    for c in candidates:
        if contrast(c, background) >= 4.5:
            return c
    return "#ffffff" if contrast("#ffffff", background) >= contrast("#000000", background) else "#000000"
