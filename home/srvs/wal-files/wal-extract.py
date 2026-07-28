#!/usr/bin/env python3
"""Extract a vibrant accent colour from an image and derive a full monochrome
palette from its hue. Prints KEY=rrggbb lines for shell eval.

    wal-extract.py IMAGE [--colors N] [--accent RRGGBB|--auto] [--bg pure|tone]

Four of the Settings program's Appearance keys land here, and this is the ONLY
place they can: the whole desktop's palette is derived in this file, so a
control that claims to change the palette has to change what this prints.
Unless overridden on the command line the values come straight from
~/.config/quickshell/settings.json (`themeMode`, `accentOverride`,
`paletteColorCount`, `pureBlackBg`), so Settings and a hand-run of this script
agree. wal-prepare.sh re-runs us whenever that file is newer than the cached
palette, which is what makes the settings apply.

Every colour still comes off ONE hue through the same value ladder — the
manual accent replaces where the hue comes FROM, never how the ramp is built,
and `--bg tone` puts BG on a rung below BGALT rather than inventing a colour.
See ~/nix/DESIGN.md §3.1."""
import sys, os, json, colorsys, warnings
from collections import Counter
from PIL import Image

warnings.filterwarnings("ignore")

SETTINGS = os.path.expanduser("~/.config/quickshell/settings.json")
DEFAULTS = {"themeMode": "auto", "accentOverride": "#5c9fcc",
            "paletteColorCount": 16, "pureBlackBg": True}


def settings():
    """The Settings program's on-disk model, with the shipped defaults for
    anything missing. Absent/corrupt file = defaults, never a traceback: this
    runs on the wallpaper path and a broken palette is a black desktop."""
    d = dict(DEFAULTS)
    try:
        with open(SETTINGS) as f:
            for k, v in (json.load(f) or {}).items():
                if k in d:
                    d[k] = v
    except Exception:
        pass
    return d


def parse_hex(s):
    """'#rrggbb' or 'rrggbb' (also the 3-digit form) -> (h, s, v), or None."""
    s = (s or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)


def hsv_hex(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return "%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def main():
    cfg = settings()
    args = sys.argv[1:]
    path = None
    colors = None
    accent_hex = None
    manual = cfg["themeMode"] == "manual"
    pure_bg = bool(cfg["pureBlackBg"])
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--colors":
            i += 1; colors = int(args[i])
        elif a == "--accent":
            i += 1; accent_hex = args[i]; manual = True
        elif a == "--auto":
            manual = False
        elif a == "--bg":
            i += 1; pure_bg = (args[i] == "pure")
        else:
            path = a
        i += 1

    if colors is None:
        try:
            colors = int(cfg["paletteColorCount"])
        except (TypeError, ValueError):
            colors = 16
    # PIL's quantizers take 2..256; the Settings slider is 8..32.
    colors = max(2, min(256, colors))
    if accent_hex is None:
        accent_hex = cfg["accentOverride"]

    manual_hsv = parse_hex(accent_hex) if manual else None
    if manual and manual_hsv is None:
        # A manual accent that doesn't parse must not silently become a
        # wallpaper palette — that reads as "the setting did nothing".
        sys.stderr.write("wal-extract: bad accentOverride %r, falling back to "
                         "the wallpaper\n" % (accent_hex,))
    if manual_hsv is not None:
        # Manual mode: the hue comes from the picked colour instead of the
        # image, and nothing below changes. avg_sat is the picked colour's own
        # saturation, so the greyscale guard still applies to a grey pick.
        h, s, v = manual_hsv
        avg_sat = s
    else:
        if path is None:
            sys.stderr.write("usage: wal-extract.py IMAGE [--colors N] "
                             "[--accent RRGGBB] [--bg pure|tone]\n")
            return 2
        img = Image.open(path).convert("RGB")
        img.thumbnail((200, 200))
        # Quantise, then score each cluster by vibrancy * frequency so we pick
        # the colour that "reads" as the wallpaper's accent, not the black
        # background. More clusters = a finer split, so a small vivid area can
        # win a cluster of its own instead of being averaged into a big dull
        # one; that is what `paletteColorCount` buys.
        q = img.quantize(colors=colors, method=Image.FASTOCTREE).convert("RGB")
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
        # Backgrounds are pure black by default and that is a settled decision
        # (DESIGN.md §3.1) — kitty, the Qt/KDE apps and the panel are then all
        # the same black. `pureBlackBg = false` is the opt-out the Settings
        # toggle promises: BG drops to the rung BELOW bgAlt on the same value
        # ladder, so the surface is the wallpaper's darkest tone rather than a
        # colour picked from outside the palette.
        "BG":        "000000" if pure_bg else hsv_hex(h, min(s, 0.55), 0.035),
        # Status colours kept on the accent hue (monochrome look) but varied in
        # brightness so battery/wifi levels still read at a glance. Softened to
        # match the pastel accent — CRIT keeps a little more chroma so an alarm
        # still stands out.
        "OK":        hsv_hex(h, PASTEL, 0.92),
        "WARN":      hsv_hex(h, min(s, 0.44), 0.80),
        "CRIT":      hsv_hex(h, min(s, 0.55), 0.98),
        "INFO":      hsv_hex(h, min(s, 0.34), 0.72),
    }
    # The options this palette was derived under. wal-set.sh evals the file, so
    # this is a comment rather than a KEY=value — it exists so `cat
    # ~/.cache/wal/themes/*.env` says which settings produced the colours when
    # someone is working out why a toggle "did nothing".
    print("# opts: mode=%s colors=%d bg=%s%s"
          % ("manual" if manual_hsv is not None else "auto", colors,
             "pure" if pure_bg else "tone",
             (" accent=%s" % accent_hex) if manual_hsv is not None else ""))
    for k, val in out.items():
        print("%s=%s" % (k, val))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
