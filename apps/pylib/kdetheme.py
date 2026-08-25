"""The apps' KDE-session half: under Plasma they follow the KDE global theme.

The desktop these apps belong to is the Hyprland one — wallpaper-derived
palette out of the panel's `Theme.qml`, pixel font out of the panel's
`settings.json`, docs/DESIGN.md all the way down. But Plasma 6 is installed
alongside it as a real alternative session (`sys/dsk/plasma.nix`), and in THAT
session the desktop's look is not the panel's: it is whatever KDE global theme
is picked in System Settings, which every other Qt app on the box already
obeys through `kdeglobals`. An app that kept drawing the wal palette there is
the one window that ignores the theme.

So: **the session decides the source, and nothing else changes.**

    Hyprland session   ->  panel Theme.qml  + panel settings.json   (as before)
    Plasma session     ->  ~/.config/kdeglobals                     (this file)

The mechanism is deliberately the *smallest* one that works: every app already
has a `Palette` that parses `property color <name>: "#rrggbb"` literals out of
a file and watches it. Under Plasma this module derives the same twelve tokens
from the KDE colour scheme and writes them into a generated file of exactly
that shape (`~/.cache/deskstyle/kde-Theme.qml`), regenerating it whenever
`kdeglobals` changes. Every app's `Palette`, its watch, and every
`Theme.*` binding downstream are untouched — the only per-app change is which
path `Palette` is handed. Fonts and motion go the same way through
`deskstyle.py`, which asks this module for its values in a Plasma session.

Mapping the twelve tokens onto KDE's roles (docs/DESIGN.md §3 for what each
one means here; `kdeglobals` groups for what each one means there):

    bg        Colors:Window/BackgroundNormal      the window surface
    bgAlt     Colors:View/BackgroundNormal        inset surfaces (lists, fields)
    border    a blend of bg toward the text tone  KDE has no frame-colour key
    accent    Colors:Window/DecorationFocus       the scheme's accent hue
    dim       Colors:Window/ForegroundInactive
    text      Colors:Window/ForegroundNormal
    textDim   Colors:Window/ForegroundInactive
    highlight Colors:Selection/BackgroundNormal
    ok/warn/crit/info   Foreground Positive/Neutral/Negative/Link

`kde_chrome()` goes one step further for the one caller that cannot hand the
painting back to the style at all — surfer's 4chan re-skin, a web page — and
returns the KStyle's gradient stops and relief tones so it can imitate one.
It is None outside a Plasma session and under a flat KStyle, so nothing else
on this desktop ever sees a gradient because of it.

**The accent and the status four are contrast-guarded, and that guard is not
optional.** §3 of the design language makes `accent` body text, and several
apps draw label text in it — while KDE's `DecorationFocus` is designed to be
seen as a *frame*, not read as a paragraph, and some schemes (Oxygen's
`ForegroundPositive`, a 0,109,56 green) are unreadable on their own window
background. A token that fails the ratio is lifted (on a dark background) or
darkened (on a light one) until it clears it, and `accent` falls back to the
plain text colour if it cannot get there at all. Both polarities are handled
because a KDE scheme may be either — the same reason docs/DESIGN.md's own
light mode fills the same twelve tokens.
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


def generated_path() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) \
        / "deskstyle" / "kde-Theme.qml"


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


def kde_palette(ini=None) -> dict | None:
    """The twelve tokens from the live KDE colour scheme, or None if there is
    no readable `kdeglobals` (then the caller keeps the wal palette — a Plasma
    session with no scheme file is not a reason to draw nothing)."""
    ini = read_ini() if ini is None else ini
    win = ini.get("Colors:Window")
    if not win:
        return None
    view = ini.get("Colors:View", win)
    sel = ini.get("Colors:Selection", win)

    bg = _rgb(win.get("BackgroundNormal"), (0, 0, 0))
    text = _rgb(win.get("ForegroundNormal"), (255, 255, 255))
    inactive = _rgb(win.get("ForegroundInactive"), _mix(bg, text, 0.55))
    view_bg = _rgb(view.get("BackgroundNormal"), bg)
    if view_bg == bg:
        view_bg = _rgb(win.get("BackgroundAlternate"), bg)

    # accent: the scheme's focus hue, but it is body text here (§3), so it has
    # to be readable as text or it is not the accent — fall back to the plain
    # foreground rather than ship a colour he cannot read a filename in.
    accent = _rgb(win.get("DecorationFocus"),
                  _rgb(sel.get("BackgroundNormal"), text))
    accent = _readable(accent, bg, TEXT_RATIO)
    if _ratio(accent, bg) < TEXT_RATIO:
        accent = text

    def status(key, fallback):
        return _readable(_rgb(win.get(key), fallback), bg, STATUS_RATIO)

    return {
        "bg": bg,
        "bgAlt": view_bg,
        # KDE has no frame-colour key at all (Breeze derives its frames from
        # the window colours the same way): a quarter of the way from the
        # surface toward the text tone reads as a hairline in both polarities.
        "border": _mix(bg, text, 0.26),
        "accent": accent,
        "dim": inactive,
        "text": text,
        "textDim": inactive,
        "highlight": _rgb(sel.get("BackgroundNormal"), _mix(bg, accent, 0.4)),
        "ok": status("ForegroundPositive", (0, 170, 90)),
        "warn": status("ForegroundNeutral", (200, 160, 60)),
        "crit": status("ForegroundNegative", (220, 70, 60)),
        "info": status("ForegroundLink", accent),
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
    "window": (0.045, -0.022),
    "panel":  (0.030, -0.014),
    "header": (0.060, -0.026),
    "button": (0.080, -0.038),
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
        up, down = _STOPS[name]
        out[name + "Top"] = _hex(_shade_l(base, up * k))
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
def render_qml(colors: dict) -> str:
    lines = [
        "import QtQuick",
        "",
        "// GENERATED by apps/pylib/kdetheme.py from ~/.config/kdeglobals.",
        "// The KDE global theme's colour scheme, in the shape every app's",
        "// Palette already parses. Rewritten whenever kdeglobals changes;",
        "// read only in a Plasma session. Do not edit.",
        "QtObject {",
    ]
    for k in KEYS:
        lines.append('    property color %s: "%s"' % (k, _hex(colors[k])))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_generated(colors: dict, path=None) -> bool:
    """Write the generated file ATOMICALLY, and only when it changed.

    Atomic because the reader is a `QFileSystemWatcher` that also watches the
    directory — a half-written file is a palette of defaults on screen for a
    frame. Unchanged content is not rewritten so a `kdeglobals` touch that
    moved no colour does not repaint every app."""
    path = Path(path or generated_path())
    text = render_qml(colors)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class _Bridge:
    """Keeps the generated file level with `kdeglobals` for the process's life.

    A `QFileSystemWatcher` on the file AND its directory, for the reason
    deskstyle.py states: KDE writes `kdeglobals` by temp-file-and-rename, which
    swaps the inode out from under a file-only watch.
    """

    def __init__(self):
        from PySide6.QtCore import QFileSystemWatcher  # local: the client half
        self._watcher = QFileSystemWatcher()           # of theme_source() may
        self._watcher.fileChanged.connect(self._sync)  # run before any Qt app
        self._watcher.directoryChanged.connect(self._sync)
        self._rewatch()
        self._sync()

    def _rewatch(self):
        have = set(self._watcher.files()) | set(self._watcher.directories())
        kg = kdeglobals_path()
        for p in (str(kg.parent), str(kg)):
            if p not in have and os.path.exists(p):
                self._watcher.addPath(p)

    def _sync(self, *_):
        self._rewatch()
        colors = kde_palette()
        if colors:
            write_generated(colors)


_bridge = None


def theme_source(default):
    """The file this app's `Palette` should read and watch.

    In the Hyprland session that is `default` — the panel's `Theme.qml`, exactly
    as before. In a Plasma session it is the generated KDE palette, kept live
    by a watcher this call installs (and whose reference this module keeps, or
    Python would collect the watcher and the theme would stop following the
    scheme). Falls back to `default` if `kdeglobals` cannot be read at all.

    Call it in `main()` after the QApplication exists, in place of the constant:

        palette = Palette(theme_source(PANEL_THEME))
    """
    global _bridge
    if not is_plasma():
        return default
    colors = kde_palette()
    if not colors:
        return default
    write_generated(colors)
    if _bridge is None:
        try:
            _bridge = _Bridge()
        except Exception:      # no Qt yet / no watcher: the file is still right,
            pass               # it just stops following a live scheme change
    return generated_path()
