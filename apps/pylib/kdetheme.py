"""KDE session detection and native role access for non-widget exports.

Qt applications use nativepalette.NativePalette, backed by the live native
QApplication palette. No intermediate Theme.qml is generated for Plasma.
Web pages and terminal escape sequences cannot host a Qt palette object;
kde_palette forwards their selected native surface and Selection roles verbatim.
ANSI colours without native equivalents are the only synthesized colour set.
"""

from __future__ import annotations

import colorsys
import os
from pathlib import Path


def kdeglobals_path() -> Path:
    """The KDE colour/font store. `DESK_KDEGLOBALS` retargets it — that is how
    `tools/kdetheme-test.py` renders a whole colour scheme without touching
    his, and it is read on every call so a test can move it after import."""
    return Path(os.environ.get("DESK_KDEGLOBALS")
                or (Path.home() / ".config" / "kdeglobals"))



# Contrast floors, in the terms docs/DESIGN.md §3.1 already states: body text
# clears WCAG-AA 4.5:1, the status ramp clears 3.0:1.
TEXT_RATIO = 4.5
STATUS_RATIO = 3.0

# The twelve tokens every app's Palette knows, in the order they are written.
KEYS = ("bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
        "highlight", "ok", "warn", "crit", "info")


# --------------------------------------------------------------------------- #
#  which session is this
# --------------------------------------------------------------------------- #
def is_plasma() -> bool:
    """True in a KDE Plasma session, false in the Hyprland one.

    `DESK_SESSION=plasma|hypr` overrides, which is how a harness renders either
    look without logging out — the twin of `DESK_SETTINGS` in deskstyle.py.
    The detection itself is the environment Plasma exports to every app it
    launches (and which Hyprland sets to `Hyprland`), never a running-process
    probe: an app is themed by the session that STARTED it, and both can be
    installed at once.
    """
    forced = (os.environ.get("DESK_SESSION") or "").strip().lower()
    if forced in ("plasma", "kde"):
        return True
    if forced in ("hypr", "hyprland", "wal"):
        return False
    desktops = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper().split(":")
    if "KDE" in desktops:
        return True
    if desktops and desktops[0]:
        return False  # a session that named itself, and it is not KDE
    return os.environ.get("KDE_FULL_SESSION", "") == "true"


# --------------------------------------------------------------------------- #
#  kdeglobals
# --------------------------------------------------------------------------- #
def read_ini(path=None) -> dict:
    """`{section: {key: value}}` from a KDE ini file. Hand-rolled rather than
    `configparser`, whose defaults reject duplicate keys and lowercase nothing
    consistently across versions; this file is read on every app start."""
    out: dict = {}
    cur = out.setdefault("", {})
    try:
        text = Path(path or kdeglobals_path()).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = out.setdefault(line[1:-1], {})
        elif "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip()] = v.strip()
    return out


def _rgb(spec, fallback):
    """KDE writes colours as `R,G,B` (occasionally with an alpha field)."""
    if not isinstance(spec, str):
        return fallback
    parts = spec.split(",")
    if len(parts) < 3:
        return fallback
    try:
        return tuple(max(0, min(255, int(float(p)))) for p in parts[:3])
    except ValueError:
        return fallback


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def _lum(rgb) -> float:
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable(fg, bg, floor: float):
    """`fg` moved along its own hue until it clears `floor` against `bg`.

    Value only — the hue and saturation are the KDE scheme's and stay its. On a
    dark background it brightens, on a light one it darkens; if it reaches the
    end of the ramp without clearing the floor the caller decides what to do
    (accent falls back to the text colour, the status ramp keeps its best).
    """
    if _ratio(fg, bg) >= floor:
        return fg
    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in fg))
    up = _lum(bg) < 0.5
    best, best_ratio = fg, _ratio(fg, bg)
    for i in range(1, 21):
        nv = min(1.0, v + i * 0.05) if up else max(0.0, v - i * 0.05)
        cand = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, nv))
        r = _ratio(cand, bg)
        if r > best_ratio:
            best, best_ratio = cand, r
        if r >= floor:
            return cand
    return best


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def kde_palette(ini=None, *, surface="View") -> dict | None:
    """Compatibility role names for consumers that cannot host native widgets.

    Values are verbatim KColorScheme surface/Selection roles. GUI applications use
    nativepalette.NativePalette and QApplication.palette() instead. This path
    serves exported terminal/web text, never a generated application palette.
    Window-backed browser canvases and terminals must request Window explicitly;
    their native Oxygen raster is not painted from the View colour group.
    """
    ini = read_ini() if ini is None else ini
    if surface not in ("View", "Window"):
        raise ValueError("unsupported KDE surface: " + surface)
    view = ini.get("Colors:" + surface, ini.get("Colors:Window"))
    if not view:
        return None
    selection = ini.get("Colors:Selection", view)
    bg = _rgb(view.get("BackgroundNormal"), (255, 255, 255))
    text = _rgb(view.get("ForegroundNormal"), (0, 0, 0))
    secondary = _rgb(view.get("ForegroundInactive"), text)
    return {
        "bg": bg, "bgAlt": _rgb(view.get("BackgroundAlternate"), bg),
        "border": secondary, "accent": text, "dim": secondary,
        "text": text, "textDim": secondary,
        "highlight": _rgb(selection.get("BackgroundNormal"), bg),
        "ok": _rgb(view.get("ForegroundPositive"), text),
        "warn": _rgb(view.get("ForegroundNeutral"), text),
        "crit": _rgb(view.get("ForegroundNegative"), text),
        "info": _rgb(view.get("ForegroundLink"), text),
    }


# --------------------------------------------------------------------------- #
#  the ANSI sixteen, for the terminals
# --------------------------------------------------------------------------- #
# A terminal needs something the twelve tokens do not carry: six chromatic ANSI
# slots that stay TELLABLE APART. The wal palette has four real hues to spend on
# them, so konsole-theme could map them straight through; a KDE colour scheme
# has no ANSI set at all, and its `ForegroundLink` is very often the accent
# again (Oxygen's is, exactly). Mapping the tokens through anyway pinned that
# one accent into foreground, blue, cyan and white at once, so a Plasma konsole
# drew four slots in one gold and only red/green/yellow broke out — "the colors
# are all wrong in konsole", 2026-08-23.
#
# So under Plasma the ramp is DERIVED rather than borrowed. Each slot has a
# canonical hue; the scheme's own colour takes the slot when it genuinely lives
# in that hue's neighbourhood (and is nearer that hue than any other slot's),
# and the rest are synthesised at the canonical angle wearing the saturation and
# value of the hues the scheme did provide — so the set reads as one family
# rather than as six stock ANSI colours dropped on his desktop. Every slot is
# then contrast-guarded against the terminal background at §3.1's status floor,
# because an unreadable green is not a green.
ANSI_SLOTS = (
    #  name      hue°   the kdeglobals key that may already hold it
    ("red",        2.0, "ForegroundNegative"),
    ("green",    128.0, "ForegroundPositive"),
    ("yellow",    46.0, "ForegroundNeutral"),
    ("blue",     218.0, "ForegroundLink"),
    ("magenta",  298.0, "ForegroundVisited"),
    ("cyan",     186.0, None),
)
ANSI_HUE_TOLERANCE = 46.0   # degrees a scheme colour may sit off its slot
ANSI_MIN_SAT = 0.18         # below this a colour is grey, and names no hue


def _hsv(rgb):
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))


def _from_hsv(h, s, v):
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb((h % 360.0) / 360.0, s, v))


def _hue_gap(a, b) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def kde_ansi(ini=None) -> dict | None:
    """The eight base ANSI colours from the KDE scheme, as `#rrggbb`.

    Keys: black, red, green, yellow, blue, magenta, cyan, white. The bright
    half is the caller's business — konsole derives its own INTENSE tone per
    slot, and kitty is handed a lift toward white — because how "bright" reads
    is a property of the terminal, not of the scheme.
    """
    ini = read_ini() if ini is None else ini
    win = ini.get("Colors:Window")
    if not win:
        return None
    bg = _rgb(win.get("BackgroundNormal"), (0, 0, 0))
    text = _rgb(win.get("ForegroundNormal"), (255, 255, 255))

    # 1. which of the scheme's own colours may keep a slot
    taken: dict = {}
    for name, hue, key in ANSI_SLOTS:
        if not key:
            continue
        c = _rgb(win.get(key), None)
        if c is None:
            continue
        h, s, _v = _hsv(c)
        h *= 360.0
        if s < ANSI_MIN_SAT or _hue_gap(h, hue) > ANSI_HUE_TOLERANCE:
            continue
        # …and only if this really is the slot it is nearest to. Oxygen's link
        # colour IS the gold accent: it is 4° off yellow and 177° off blue, so
        # this is what keeps it out of the blue slot.
        if min(_hue_gap(h, o) for _n, o, _k in ANSI_SLOTS) < _hue_gap(h, hue):
            continue
        taken[name] = c

    # 2. the envelope the synthesised slots wear: what saturation and value the
    #    scheme spends on a hue when it has one. A scheme with no hues at all
    #    (a pure greyscale one) gets a restrained default rather than neon.
    sats = [_hsv(c)[1] for c in taken.values()]
    vals = [_hsv(c)[2] for c in taken.values()]
    sat = sum(sats) / len(sats) if sats else 0.62
    val = sum(vals) / len(vals) if vals else (0.66 if _lum(bg) < 0.5 else 0.45)
    sat = max(0.35, min(0.90, sat))
    val = max(0.30, min(0.95, val))

    out = {"black": bg, "white": text}
    for name, hue, _key in ANSI_SLOTS:
        c = taken.get(name)
        out[name] = _readable(c, bg, STATUS_RATIO) if c else _synth(hue, sat, val, bg)
    return {k: _hex(v) for k, v in out.items()}


def _synth(hue, sat, val, bg):
    """A slot the scheme has no colour for, at `hue`, wearing its envelope.

    Blue and cyan on a dark background are the reason this is not just
    `_readable` over a synthesised colour: a fully saturated blue cannot clear
    the contrast floor by value alone, so the guard drives it to v=1 and the
    result is the fluorescent blue docs/DESIGN.md §3.2 rules out. **Saturation
    is capped as value rises**, which is the same "pastel, not fluorescent"
    trade the wal palette makes — the colour goes pale rather than neon.
    """
    dark = _lum(bg) < 0.5
    best, best_ratio = None, -1.0
    for i in range(0, 21):
        v = min(1.0, val + i * 0.035) if dark else max(0.0, val - i * 0.035)
        s = min(sat, 1.0 - 0.5 * max(0.0, v - 0.6) / 0.4) if dark else min(1.0, sat + i * 0.02)
        cand = _from_hsv(hue, s, v)
        r = _ratio(cand, bg)
        if r > best_ratio:
            best, best_ratio = cand, r
        if r >= STATUS_RATIO:
            return cand
    return best


def kde_font(ini=None):
    """`(family, point_size)` from `kdeglobals [General] font=`, or None.

    The value is a serialised QFont: `Family,pointSize,pixelSize,styleHint,…`,
    where a pointSize of -1 means the size is the *pixel* field instead. Both
    shapes are handled; the caller converts points to pixels at the screen's
    own DPI (see deskstyle.py) rather than assuming 96.
    """
    ini = read_ini() if ini is None else ini
    spec = (ini.get("General") or {}).get("font")
    if not isinstance(spec, str) or "," not in spec:
        return None
    parts = spec.split(",")
    family = parts[0].strip()
    if not family:
        return None
    try:
        pt = float(parts[1])
    except (IndexError, ValueError):
        pt = -1.0
    try:
        px = float(parts[2])
    except (IndexError, ValueError):
        px = -1.0
    if pt > 0:
        return (family, pt, None)
    if px > 0:
        return (family, None, px)
    return (family, 10.0, None)


# --------------------------------------------------------------------------- #
#  the KStyle's chrome: does it gradient, and with what stops
# --------------------------------------------------------------------------- #
# KStyles that paint a vertical window/button gradient rather than flat fills.
# Breeze and Fusion are flat and must stay out of this list — a flat session
# getting gradients is the same bug as a gradient session not getting them.
GRADIENT_STYLES = ("oxygen",)


def kde_widget_style(ini=None) -> str:
    """The active KStyle, lowercased (`""` if unknown).

    `[KDE] widgetStyle` in `kdeglobals`, falling back to
    `kdedefaults/kdeglobals` — a Global Theme (Look and Feel package) records
    the style THERE and leaves the user file's key absent, which is exactly the
    state a stock Oxygen or Breeze session is in.
    """
    ini = read_ini() if ini is None else ini
    style = (ini.get("KDE") or {}).get("widgetStyle")
    if not style:
        d = kdeglobals_path().parent / "kdedefaults" / "kdeglobals"
        style = (read_ini(d).get("KDE") or {}).get("widgetStyle")
    return (style or "").strip().lower()


def _shade_l(rgb, d):
    """`rgb` moved `d` along HLS lightness (hue and saturation kept)."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))
    l = max(0.0, min(1.0, l + d))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


# How far each surface's two stops sit either side of its base colour, before
# the scheme's own contrast scaling. Oxygen's real stops come out of
# KColorUtils' HCY shade() against the style's slab ratios, which is not
# reproducible outside the style; these are a deliberate APPROXIMATION of the
# look — light at the top, darker at the foot, strongest on the controls and
# faintest on the window — and the only thing that reads them (surfer's
# OneeChan re-skin) is a web page, where nothing else can draw the real one.
_STOPS = {
    # The middle stop is the Oxygen window's characteristic shaded band.
    # It recovers slightly at the foot instead of fading uniformly top-down.
    "window": (0.045, -0.065, -0.022),
    "panel":  (0.030, -0.042, -0.014),
    "header": (0.060, -0.075, -0.026),
    "button": (0.080, -0.070, -0.038),
}


def kde_chrome(ini=None) -> dict | None:
    """Gradient stops and bevel tones for the active KStyle, or None when the
    style draws flat (or this is not a Plasma session at all).

    The caller gets hex stop pairs per surface plus the two 1px relief tones,
    so it can imitate a KDE window in a medium the style itself cannot paint.
    Everything is derived from the live scheme's own group backgrounds and its
    `[KDE] contrast` (0-10), so it follows a scheme change with no new keys.
    """
    if not is_plasma():
        return None
    ini = read_ini() if ini is None else ini
    if kde_widget_style(ini) not in GRADIENT_STYLES:
        return None
    win = ini.get("Colors:Window")
    if not win:
        return None
    view = ini.get("Colors:View", win)
    button = ini.get("Colors:Button", win)
    try:
        c = max(0.0, min(1.0, float((ini.get("KDE") or {}).get("contrast", 7)) / 10.0))
    except (TypeError, ValueError):
        c = 0.7
    k = 0.55 + 0.65 * c            # contrast=7 -> ~1.0, the stops as written
    bases = {
        "window": _rgb(win.get("BackgroundNormal"), (40, 34, 42)),
        "panel":  _rgb(view.get("BackgroundNormal"), (32, 27, 36)),
        "header": _rgb(win.get("BackgroundNormal"), (40, 34, 42)),
        "button": _rgb(button.get("BackgroundNormal"), (58, 51, 58)),
    }
    out = {}
    for name, base in bases.items():
        up, mid, down = _STOPS[name]
        out[name + "Top"] = _hex(_shade_l(base, up * k))
        out[name + "Mid"] = _hex(_shade_l(base, mid * k))
        out[name + "Bottom"] = _hex(_shade_l(base, down * k))
    # The two relief tones: Oxygen's 1px light bevel along the top of every
    # slab and the shadow under its foot. Alpha, not colour, so they sit over
    # whatever stop they land on.
    out["bevel"] = "rgba(255,255,255,%.2f)" % (0.05 + 0.05 * c)
    out["shade"] = "rgba(0,0,0,%.2f)" % (0.18 + 0.14 * c)
    out["radius"] = 3               # Oxygen's slab/hole corner, in px
    out["style"] = kde_widget_style(ini)
    return out


def kde_motion(ini=None):
    """`(reduceMotion, animSpeed)` from `[KDE] AnimationDurationFactor`.

    KDE's factor multiplies every animation duration, which is exactly what
    `animSpeed` does in `qmlcommon/Motion.qml` — so it maps across with no
    rescaling, and its 0 ("instant") is this desktop's `reduceMotion`.
    """
    ini = read_ini() if ini is None else ini
    raw = (ini.get("KDE") or {}).get("AnimationDurationFactor")
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return (False, 1.0)
    if f <= 0:
        return (True, 1.0)
    return (False, f)


# --------------------------------------------------------------------------- #
#  the generated Theme.qml every app's Palette already knows how to read
# --------------------------------------------------------------------------- #
_palette_callbacks = []


def watch_palette(callback):
    """Subscribe to NativePalette's native application palette notification."""
    if is_plasma() and callback not in _palette_callbacks:
        _palette_callbacks.append(callback)


def theme_source(default):
    """Legacy constructor argument; session_palette selects the implementation.

    Plasma never reads this path. Hyprland reads its wallpaper source directly.
    """
    return default
