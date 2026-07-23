#!/usr/bin/env python3
"""Extract a vibrant accent colour from an image and derive a full monochrome
palette from its hue. Prints KEY=rrggbb lines for shell eval."""
import sys, colorsys, warnings
from collections import Counter
from PIL import Image

warnings.filterwarnings("ignore")


def hsv_hex(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return "%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def main():
    img = Image.open(sys.argv[1]).convert("RGB")
    img.thumbnail((200, 200))
    # Quantise, then score each cluster by vibrancy * frequency so we pick the
    # colour that "reads" as the wallpaper's accent, not the black background.
    q = img.quantize(colors=16, method=Image.FASTOCTREE).convert("RGB")
    counts = Counter(q.getdata())
    best, best_score = None, -1.0
    total = 0.0
    sat_sum = 0.0
    for (r, g, b), cnt in counts.items():
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        sat_sum += s * cnt
        total += cnt
        score = (s ** 1.5) * (v ** 0.5) * cnt
        if score > best_score:
            best_score, best = score, (h, s, v)
    h, s, v = best
    avg_sat = sat_sum / total if total else 0.0
    # A near-greyscale wallpaper (silver/steel gradient, etc.) has no real
    # accent hue — the "winning" pixel is just faintly tinted grey. Forcing
    # saturation up would fabricate a vivid colour (e.g. prussian blue) that
    # doesn't match the wallpaper. So: only enforce a vivid accent when the
    # image is actually colourful; otherwise keep the palette desaturated/grey
    # on whatever faint hue it has, so silver stays silver.
    if avg_sat < 0.15:
        s = min(s, 0.12)   # stay grey/silver
    else:
        s = max(s, 0.55)   # keep a defined hue to derive the palette from

    # Pastel, not fluorescent: a bright surface with high saturation reads as
    # neon on the black panel. Pastels keep the brightness but wash the chroma
    # out, so cap saturation low on the light surfaces (accent/text/status) and
    # push their value up. The dark structural tones (DIM/BORDER/BGALT) sit at
    # low value where high chroma doesn't glow, so they keep more saturation to
    # stay distinguishable. PASTEL folds in the grey/silver case (s already <=
    # 0.12 there, so the cap is a no-op and silver stays silver).
    PASTEL = min(s, 0.34)

    accent = hsv_hex(h, PASTEL, max(v, 0.90))
    out = {
        "ACCENT":    accent,
        # Body text IS the accent colour (not a brighter tint of it), so the
        # panel / runner / OSD text reads as the same red as kitty's foreground
        # and the KDE/Qt apps' normal text — every "focused" surface is one
        # colour. TEXTDIM below still gives an inactive/secondary tier.
        "TEXT":      accent,
        "TEXTDIM":   hsv_hex(h, min(s, 0.40), 0.60),
        "DIM":       hsv_hex(h, min(s, 0.50), 0.33),
        "BORDER":    hsv_hex(h, min(s, 0.60), 0.22),
        "BGALT":     hsv_hex(h, min(s, 0.55), 0.07),
        "HIGHLIGHT": hsv_hex(h, min(s, 0.60), 0.13),
        "BG":        "000000",
        # Status colours kept on the accent hue (monochrome look) but varied in
        # brightness so battery/wifi levels still read at a glance. Softened to
        # match the pastel accent — CRIT keeps a little more chroma so an alarm
        # still stands out.
        "OK":        hsv_hex(h, PASTEL, 0.92),
        "WARN":      hsv_hex(h, min(s, 0.44), 0.80),
        "CRIT":      hsv_hex(h, min(s, 0.55), 0.98),
        "INFO":      hsv_hex(h, min(s, 0.34), 0.72),
    }
    for k, val in out.items():
        print("%s=%s" % (k, val))


if __name__ == "__main__":
    main()
