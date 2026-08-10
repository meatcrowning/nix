#!/usr/bin/env python3
"""Extract a vibrant accent colour from an image and derive the desktop palette
from it. Prints KEY=rrggbb lines for shell eval.

    wal-extract.py IMAGE [--colors N] [--accent RRGGBB|--auto] [--bg pure|tone]
                         [--variant vivid|normal|muted|pastel] [--light|--dark]

Six of the Settings program's Appearance keys land here, and this is the ONLY
place they can: the whole desktop's palette is derived in this file, so a
control that claims to change the palette has to change what this prints.
Unless overridden on the command line the values come straight from
~/.config/quickshell/settings.json (`themeMode`, `accentOverride`,
`paletteColorCount`, `pureBlackBg`, `paletteVariant`, `lightMode`), so Settings
and a hand-run of this script agree. wal-prepare.sh re-runs us whenever that
file is newer than the cached palette, which is what makes the settings apply.

LIGHT vs DARK is an orthogonal polarity axis (`lightMode` / `--light`): dark
(default) is the settled black-background look; light inverts the value ladder
so the background is white and the ink is the dark end of the SAME wallpaper
hue. Both fill the same twelve tokens, so nothing downstream (kitty, kdeglobals,
hyprvtb, the panel) knows which polarity it is drawing.

The palette (full_palette()) reads a WHOLE palette off the wallpaper, always,
filling twelve tokens (so Theme.qml is untouched): the accent stays the primary
vibrant hue, the structural tones (bgAlt/border/dim/highlight) take the
wallpaper's SECONDARY hue, and the status ramp (ok/warn/crit/info) is SAMPLED
from the wallpaper clusters nearest green/amber/red/blue — hue, saturation and
value all taken from the image, the hue clamped to a legible band so each slot
still reads as its state — so the desktop reads as several wallpaper colours,
not shades of one. The manual accent replaces where the accent hue comes FROM,
never the derivation; `--bg tone` puts BG on a rung below BGALT rather than
inventing a colour. The `paletteVariant` picker (vivid | normal | muted | pastel) is a
global chroma/value transform over that generated palette. See
~/nix/docs/DESIGN.md §3.1.2."""
import sys, os, json, colorsys, warnings
from collections import Counter
from PIL import Image

warnings.filterwarnings("ignore")

SETTINGS = os.path.expanduser("~/.config/quickshell/settings.json")
DEFAULTS = {"themeMode": "auto", "accentOverride": "#5c9fcc",
            "paletteColorCount": 16, "pureBlackBg": True,
            "paletteVariant": "pastel", "lightMode": False,
            # Cluster hexes the user clicked OFF in the Settings swatch row —
            # dropped from the derivation (accent scoring, secondary, status
            # sampling), still published in CLUSTERS so the row can re-light
            # them. Keyed by colour, so a wallpaper change naturally resets it:
            # the new image's clusters simply don't match the old hexes.
            "paletteDropped": []}

# Full-mode variant knobs. Each is a global transform over the generated
# palette, NOT a different derivation: the same hues come out, dressed brighter
# or more washed. `light_cap` caps saturation on the light surfaces
# (accent/text/status) — this is the §3.1 "pastel, not fluorescent" cap, which
# `vivid` deliberately opens up because opting into full+vivid is opting out of
# that rule. `accent_v` is the accent's value floor; `struct_mul` scales the
# chroma of the dark structural tones (which glow less, so may carry more);
# `status_s` is the status ramp's saturation.
VARIANTS = {
    # name       light_cap  accent_v  struct_mul  status_s  light_ink  light_ink_v
    # light_ink caps the LIGHT-MODE ink saturation, light_ink_v its value
    # ceiling. They exist because the old formula (max(light_cap, 0.40))
    # collapsed pastel and muted onto the same cap, and a dark-pinned value
    # made even a saturated vivid ink read as generic dark brown — in light
    # mode the variant control visibly did nothing (§10.1). Now: pastel is
    # the settled softly-tinted ink, muted is near-grey ink (a monochrome
    # page), vivid is genuinely coloured ink, lifted enough to show chroma
    # while staying dark enough to read on white.
    "pastel":  {"light_cap": 0.34, "accent_v": 0.92, "struct_mul": 1.00, "status_s": 0.42, "light_ink": 0.40, "light_ink_v": 0.42},
    "muted":   {"light_cap": 0.20, "accent_v": 0.78, "struct_mul": 0.55, "status_s": 0.30, "light_ink": 0.10, "light_ink_v": 0.40},
    "vivid":   {"light_cap": 0.85, "accent_v": 1.00, "struct_mul": 1.45, "status_s": 0.90, "light_ink": 0.85, "light_ink_v": 0.55},
    # `normal` is the plain, un-stylised baseline — every knob sits about
    # halfway between pastel and vivid, so it neither softens the palette the
    # way pastel does nor pushes the chroma the way vivid does. A
    # middle-of-the-road, straightforward rendition of the wallpaper palette.
    # TWO things set it apart from the others, both so its main colour reads as
    # the wallpaper's own colour rather than a neon version of it (§3.1.2):
    #   * `main_dominant` — the accent hue/sat come from the wallpaper's
    #     DOMINANT (most-prevalent) colour, not the vibrant-winner cluster the
    #     other variants use. So a mostly-green wallpaper gives a green main
    #     colour, whatever small vivid speck the scorer would otherwise chase.
    #   * `accent_v` is a legibility FLOOR (0.70), not the near-max 0.96 the
    #     others force. `max(v, 0.70)` lifts a deep dominant colour just enough
    #     to read on pure black and leaves an already-bright one alone — where
    #     0.96 fabricated a fluorescent tint out of a deep forest green.
    "normal":  {"light_cap": 0.55, "accent_v": 0.70, "struct_mul": 1.20, "status_s": 0.65, "light_ink": 0.60, "light_ink_v": 0.48, "main_dominant": True},
}


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


def hue_dist(a, b):
    """Shortest distance between two hues on the [0,1) colour wheel: 0..0.5."""
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def pick_secondary(clusters, ph, ps):
    """The wallpaper's SECONDARY colour for the structural tones: the saturated,
    non-trivial cluster whose hue sits farthest from the accent, so the frames
    read as a different wallpaper colour rather than a darker accent. Falls back
    to the accent hue itself on a monochrome image (then full mode degrades
    gracefully toward the mono look for the structural tones)."""
    best, best_score = None, -1.0
    for (h, s, v, c) in clusters:
        if s < 0.18 or v < 0.06:
            continue
        score = hue_dist(h, ph) * (0.5 + s) * (c ** 0.25)
        if score > best_score:
            best_score, best = score, (h, s)
    return best if best is not None else (ph, ps)


def status_color(anchor, band, clusters, ss, base_v, s_floor, v_floor, light=False):
    """A status colour genuinely SAMPLED from the wallpaper, not a canonical hue
    dressed up. Find the saturated wallpaper cluster nearest the status slot's
    canonical anchor (green/amber/red/blue) and take its hue, saturation AND
    value from that cluster — the hue pulled toward it but CLAMPED to a legible
    band around the anchor (so OK still reads green, CRIT still reads red —
    §3.2/§3.5), and the saturation/value BLENDED with the variant baseline so
    the variant still reads as a global transform and the slot stays legible on
    black. A wallpaper with no colour near the anchor keeps the canonical
    baseline, so full mode degrades gracefully on a wallpaper that lacks a hue.
    Unlike the old fixed-hue-wheel nudge, every wallpaper now yields a visibly
    different ramp because the sampled hue/sat/value all track the image.

    In LIGHT mode `base_v`/`v_floor` are dark targets and `v_floor` reads as a
    value CEILING (so a status slot stays dark enough to read on white) rather
    than the dark-mode floor (dark enough it never sinks into the black panel)."""
    near, near_d = None, 1.0
    for (h, s, v, c) in clusters:
        if s < 0.22 or v < 0.12:
            continue
        d = hue_dist(h, anchor)
        if d < near_d:
            near_d, near = d, (h, s, v)
    if near is None:
        return hsv_hex(anchor, max(ss, s_floor), base_v)
    nh, ns, nv = near
    # Hue: pull toward the sampled cluster, clamped shortest-arc to the band so
    # the slot never leaves its legible colour-coded region of the wheel.
    diff = (nh - anchor + 0.5) % 1.0 - 0.5
    hue = (anchor + max(-band, min(band, diff))) % 1.0
    # Saturation/value: the variant baseline shifted toward the sampled cluster,
    # floored so the state still reads against the black panel.
    sat = max(ss + (ns - ss) * 0.6, s_floor)
    blended = base_v + (nv - base_v) * 0.5
    val = min(blended, v_floor) if light else max(blended, v_floor)
    return hsv_hex(hue, sat, val)


def full_palette(h, s, v, clusters, pure_bg, variant, light=False):
    """The desktop palette: the accent stays the primary hue, but the
    structural tones take the wallpaper's secondary hue and the status ramp
    takes real colour-coded hues nudged toward the wallpaper. Twelve tokens.
    `variant` (vivid|normal|muted|pastel) is a global transform — see VARIANTS.
    `light` inverts the value ladder onto a white background (dark ink accent,
    light grey structural tints) while keeping the secondary-hue frames and the
    sampled status ramp. docs/DESIGN.md §3.1.2."""
    vp = VARIANTS.get(variant, VARIANTS["pastel"])
    lcap, av, smul, ss = (vp["light_cap"], vp["accent_v"],
                          vp["struct_mul"], vp["status_s"])

    if light:
        h2, s2 = pick_secondary(clusters, h, s)
        # Dark ink accent on white; the variant's chroma character still
        # applies. Cap and value ceiling are the variant's own light_ink /
        # light_ink_v — see VARIANTS for why they are per-variant.
        INK = min(s, vp["light_ink"])
        accent = hsv_hex(h, INK, min(max(v, 0.28), vp["light_ink_v"]))

        def lstruct(cap, val):
            # Light grey tinted with the SECONDARY hue; values are high (near the
            # white bg), the variant free to push chroma since a pale tint at high
            # value does not glow. The cap scales up with a >1 struct_mul (same
            # shape as the dark branch's struct()) so vivid's tints actually get
            # to carry more chroma instead of hitting the pastel ceiling.
            return hsv_hex(h2, min(s2 * smul, cap * (smul if smul > 1 else 1.0)), val)

        return {
            "ACCENT":    accent,
            "TEXT":      accent,
            "TEXTDIM":   hsv_hex(h, min(s, lcap * 1.15), 0.46),
            "DIM":       lstruct(0.30, 0.60),
            "BORDER":    lstruct(0.28, 0.72),
            "BGALT":     lstruct(0.12, 0.94),
            "HIGHLIGHT": lstruct(0.28, 0.85),
            "BG":        "ffffff" if pure_bg else lstruct(0.10, 0.965),
            "OK":        status_color(0.34, 0.10, clusters, ss,            0.55, 0.30, 0.66, True),
            "WARN":      status_color(0.12, 0.05, clusters, ss,            0.60, 0.30, 0.68, True),
            "CRIT":      status_color(0.00, 0.05, clusters, max(ss, 0.65), 0.48, 0.55, 0.56, True),
            "INFO":      status_color(0.57, 0.07, clusters, min(ss, 0.55), 0.56, 0.28, 0.64, True),
        }

    # Light surfaces: accent hue, chroma capped by the variant, value lifted.
    # `min(s, lcap)` so a washed wallpaper is never forced brighter than it is
    # and the greyscale guard (s already clamped upstream) still holds — a
    # silver wallpaper stays silver in every variant.
    LIGHT = min(s, lcap)
    accent = hsv_hex(h, LIGHT, max(v, av))

    # Structural tones: the wallpaper's SECONDARY hue, so frames/insets read as
    # a different wallpaper colour. Low value means chroma doesn't glow, so the
    # variant is free to push it (smul) — clamped in hsv_hex.
    h2, s2 = pick_secondary(clusters, h, s)

    def struct(cap, val):
        return hsv_hex(h2, min(s2 * smul, cap * (1.0 if smul <= 1 else smul)), val)

    # Foreground / background. With pure black ENABLED this is the settled look:
    # #000 background, the accent as the ink. With it DISABLED, dark mode is the
    # exact inverse of light mode — its background is what light mode paints as
    # the FOREGROUND (the dark ink) and its foreground is light mode's paper
    # (near-white). One recursive light-branch call so the two derivations can
    # never drift apart. TEXT tracks the accent so body text stays the accent
    # (§3.1.1). docs/DESIGN.md §3.1.2.
    if pure_bg:
        FG, BG = accent, "000000"
    else:
        lp = full_palette(h, s, v, clusters, False, variant, light=True)
        FG, BG = lp["BG"], lp["ACCENT"]

    # Status ramp: each slot is SAMPLED from the wallpaper cluster nearest its
    # colour-coded anchor (green/amber/red/blue) — hue, saturation and value all
    # taken from the image, the hue clamped to a per-slot legible band (amber and
    # red are narrow; green and blue tolerate a wider pull) so a status colour
    # never stops reading as its state. CRIT keeps a chroma floor so an alarm
    # reads even in the muted variant. See status_color().
    return {
        "ACCENT":    FG,
        "TEXT":      FG,       # body text is still the accent (§3.1.1 focus rule)
        "TEXTDIM":   hsv_hex(h, min(s, lcap * 1.15), 0.60),
        "DIM":       struct(0.50, 0.33),
        "BORDER":    struct(0.60, 0.22),
        "BGALT":     struct(0.55, 0.07),
        "HIGHLIGHT": struct(0.60, 0.13),
        "BG":        BG,
        "OK":        status_color(0.34, 0.10, clusters, ss,             0.90, 0.22, 0.70),
        "WARN":      status_color(0.12, 0.05, clusters, ss,             0.82, 0.22, 0.66),
        "CRIT":      status_color(0.00, 0.05, clusters, max(ss, 0.65),  0.98, 0.55, 0.85),
        "INFO":      status_color(0.57, 0.07, clusters, min(ss, 0.55),  0.74, 0.20, 0.60),
    }


def main():
    cfg = settings()
    args = sys.argv[1:]
    path = None
    colors = None
    accent_hex = None
    manual = cfg["themeMode"] == "manual"
    pure_bg = bool(cfg["pureBlackBg"])
    variant = str(cfg["paletteVariant"] or "pastel")
    light = bool(cfg["lightMode"])
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
        elif a == "--variant":
            i += 1; variant = args[i]
        elif a == "--light":
            light = True
        elif a == "--dark":
            light = False
        else:
            path = a
        i += 1

    if variant not in VARIANTS:
        variant = "pastel"
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

    # Per-wallpaper: paletteDropped maps the image's (realpath'd) absolute
    # path -> the hexes clicked off for THAT paper, so returning to a
    # wallpaper restores its selection instead of resetting it. Every caller
    # hands us a realpath'd path already (wal-set/wal-prepare both realpath);
    # re-resolving here keeps a hand-run against a symlink consistent. A bare
    # list is the pre-per-paper format and is honoured as-is.
    dropped = set()
    try:
        pd = cfg["paletteDropped"] or {}
        if isinstance(pd, dict):
            lst = pd.get(os.path.realpath(path) if path else "") or []
        elif isinstance(pd, list):
            lst = pd
        else:
            lst = []
        dropped = {str(x).strip().lstrip("#").lower() for x in lst}
    except (TypeError, AttributeError):
        dropped = set()

    # The palette always derives FROM the wallpaper — the accent in auto mode,
    # and the secondary + status hues always (even when the accent hue was
    # picked by hand) — so the image is always read.
    clusters = []
    all_hexes = []    # every cluster, dominant first, dropped ones included
    img_hsv = None    # (h, s, v, avg_sat) from the image's winning cluster
    dom_hsv = None    # (h, s, v) of the most-PREVALENT real colour (normal variant)
    if True:
        if path is None:
            sys.stderr.write("usage: wal-extract.py IMAGE [--colors N] "
                             "[--accent RRGGBB] [--bg pure|tone] "
                             "[--variant vivid|normal|muted|pastel] "
                             "[--light|--dark]\n")
            return 2
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((200, 200))
            # Quantise, then score each cluster by vibrancy * frequency so we
            # pick the colour that "reads" as the wallpaper's accent, not the
            # black background. More clusters = a finer split, so a small vivid
            # area can win a cluster of its own instead of being averaged into a
            # big dull one; that is what `paletteColorCount` buys — and, in full
            # mode, more candidate hues for the secondary and status tones.
            q = img.quantize(colors=colors, method=Image.FASTOCTREE).convert("RGB")
            counts = Counter(q.getdata())
            # Every cluster first (dominant first — the order the Settings
            # swatch row draws), THEN the user's dropped colours come out
            # before anything downstream sees the list. All dropped = the
            # selection is ignored, never a black desktop (and never a silent
            # no-op: the swatch row refuses to un-light the last one).
            allc = sorted(((rgb, cnt) for rgb, cnt in counts.items()),
                          key=lambda x: -x[1])
            all_hexes = ["%02x%02x%02x" % rgb for rgb, _ in allc]
            kept = [(rgb, cnt) for (rgb, cnt), hx in zip(allc, all_hexes)
                    if hx not in dropped]
            if not kept:
                sys.stderr.write("wal-extract: every cluster dropped; "
                                 "ignoring paletteDropped\n")
                kept = allc
            best, best_score = None, -1.0
            dom, dom_cnt = None, -1.0
            total = 0.0
            sat_sum = 0.0
            for (r, g, b), cnt in kept:
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                clusters.append((h, s, v, cnt))
                sat_sum += s * cnt
                total += cnt
                score = (s ** 1.5) * (v ** 0.5) * cnt
                if score > best_score:
                    best_score, best = score, (h, s, v)
                # Most-prevalent cluster that is a real COLOUR (not the near-black
                # background, not a near-grey) — the `normal` variant's main hue.
                # kept is dominant-first, so the first qualifier by count wins.
                if s >= 0.15 and v >= 0.12 and cnt > dom_cnt:
                    dom_cnt, dom = cnt, (h, s, v)
            bh, bs, bv = best
            img_hsv = (bh, bs, bv, sat_sum / total if total else 0.0)
            dom_hsv = dom if dom is not None else (bh, bs, bv)
        except Exception as e:
            # In full+manual we can still proceed with just the picked hue (the
            # structural/status tones then degrade to canonical, no wallpaper
            # nudge). In auto mode there is no fallback — a black desktop is
            # worse than an error.
            if manual_hsv is None:
                sys.stderr.write("wal-extract: cannot read %r: %s\n" % (path, e))
                return 1

    if manual_hsv is not None:
        # Manual mode: the accent hue comes from the picked colour, not the
        # image. avg_sat is the picked colour's own saturation, so the greyscale
        # guard still applies to a grey pick.
        h, s, v = manual_hsv
        avg_sat = s
    else:
        h, s, v, avg_sat = img_hsv

    # The `normal` variant takes its main colour from the wallpaper's DOMINANT
    # colour (most-prevalent real cluster) rather than the vibrancy-scored
    # winner the other variants use — so the accent reads as the wallpaper's
    # own colour, and its low `accent_v` floor (VARIANTS) then lifts a deep
    # dominant just to legibility instead of forcing it fluorescent. Only in
    # auto mode: a hand-picked accent still wins. avg_sat (the image mean) is
    # left as-is so the greyscale guard below still keys on the whole image.
    if (manual_hsv is None and VARIANTS.get(variant, {}).get("main_dominant")
            and dom_hsv is not None):
        h, s, v = dom_hsv

    # A near-greyscale wallpaper (silver/steel gradient, etc.) has no real
    # accent hue — the "winning" pixel is just faintly tinted grey. Forcing
    # saturation up would fabricate a vivid colour (e.g. prussian blue) that
    # doesn't match the wallpaper. So: only enforce a vivid accent when the
    # image is actually colourful; otherwise keep the palette desaturated/grey
    # on whatever faint hue it has, so silver stays silver. (The variant caps
    # in full mode never RAISE saturation, so silver stays silver there too.)
    if avg_sat < 0.15:
        s = min(s, 0.12)   # stay grey/silver
    else:
        s = max(s, 0.55)   # keep a defined hue to derive the palette from

    out = full_palette(h, s, v, clusters, pure_bg, variant, light)
    mode_label = "manual" if manual_hsv is not None else "auto"

    # The options this palette was derived under. wal-set.sh evals the file, so
    # this is a comment rather than a KEY=value — it exists so `cat
    # ~/.cache/wal/themes/*.env` says which settings produced the colours when
    # someone is working out why a toggle "did nothing".
    print("# opts: mode=%s polarity=%s variant=%s colors=%d bg=%s%s"
          % (mode_label, "light" if light else "dark",
             variant, colors,
             "pure" if pure_bg else "tone",
             (" accent=%s" % accent_hex) if manual_hsv is not None else ""))
    # Every quantised cluster, dominant first, dropped ones included — wal-set
    # publishes this to $CACHE/current.clusters for the Settings swatch row.
    print("CLUSTERS=%s" % ",".join(all_hexes))
    for k, val in out.items():
        print("%s=%s" % (k, val))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
