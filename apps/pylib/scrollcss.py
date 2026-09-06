"""The desktop's scrollbar, as CSS — for the browsers that draw their own.

Chromium never asks Qt or GTK for a scrollbar: it paints its own in Aura, so a
page in Vivaldi (and a page in surfer) is the one surface `qmlcommon/VScroll.qml`
cannot reach. `::-webkit-scrollbar` can, and this builds that sheet from the
same palette every other surface reads — Qt-free, like `chantheme.py` and for
the same reason: Vivaldi wears it through a userscript and a `custom.css`, with
no app and no Qt anywhere in the path.

Two faces, the same rule the rest of the desktop follows (`kdetheme.is_plasma`):

* **Plasma + a gradient KStyle -> Oxygen's own bar**, per docs/DESIGN.md 9.2's
  2026-08-22 rule (in a KDE-chromed window the bar is the STYLE's, not a
  drawing of one). A web page cannot hand the painting to `QStyle`, so this is
  the one place that bar has to be imitated — and the numbers below are
  MEASURED off the real thing rather than picked: `tools/oxygen-scrollbar-probe.py`
  renders a live `QScrollBar` under the Oxygen style offscreen and prints the
  ladder this module reproduces. Re-run it before changing any constant here.
* **Anything else -> the desktop's own variant** (`scrollbarStyle` in the
  panel's `settings.json`: `win31` | `beveled` | `flat`), the same three
  DESIGN.md 9.2 defines and `surfer`'s `scrollbarJs()` already draws: hard 1px
  bevels, no radius, no gradient.

    from scrollcss import build
    css, provenance = build()          # the live session's face
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

import hexcolor
import kdetheme

SETTINGS = Path.home() / ".config" / "quickshell" / "settings.json"
STYLES = ("win31", "beveled", "flat")
DEFAULT_STYLE = "win31"

# Oxygen's own layout, from `oxygenrc` via oxygenstyle.metrics() when it is
# readable and from upstream's kcfg defaults when it is not.
_OXY_FALLBACK = {"scrollWidth": 15, "scrollSubButtons": 1, "scrollAddButtons": 2,
                 "scrollButtonHeight": 14}


def scrollbar_style(path=SETTINGS) -> str:
    """The `scrollbarStyle` pick, read the way deskstyle.py reads it (which
    holds Qt, so it cannot be imported here)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_STYLE
    bar = data.get("scrollbarStyle") if isinstance(data, dict) else None
    return bar if bar in STYLES else DEFAULT_STYLE


# ---- colour helpers ---------------------------------------------------------
# All in `hexcolor.py`, shared with the other injected sheets; the local names
# stay so the rules below read as they were measured.
_rgb, _hex, _lum = hexcolor.rgb, hexcolor.hex_, hexcolor.lum
_scale_l, _mix = hexcolor.scale_l, hexcolor.mix


def _uri(svg):
    return "data:image/svg+xml;charset=utf8," + quote(svg, safe="")


# ---- the Oxygen face --------------------------------------------------------
# The chevron Oxygen draws on a stepper: a hollow 2px V about 9x6, NOT the solid
# triangle the desktop's own win31 bar uses (probe, rows 276-296).
def _chevron(ink, direction):
    pts = {"up": "1,6 5,2 9,6", "down": "1,2 5,6 9,2",
           "left": "6,1 2,5 6,9", "right": "2,1 6,5 2,9"}[direction]
    return _uri(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="11" '
        'viewBox="0 0 10 11"><polyline points="%s" fill="none" stroke="%s" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        % (pts, ink))


def kde_button(ini=None) -> str | None:
    """`[Colors:Button] BackgroundNormal` as hex — the colour Oxygen's SLIDER
    carries. `kde_palette()` has no token for it (its `bgAlt` is the View/base
    colour, a text field's white) and `kde_chrome()` publishes only the two
    exaggerated stops it derives for imitating a window slab, so the scrollbar
    reads the group itself and applies its own measured ratios."""
    ini = kdetheme.read_ini() if ini is None else ini
    group = ini.get("Colors:Button") or ini.get("Colors:Window")
    if not group:
        return None
    return kdetheme._hex(kdetheme._rgb(group.get("BackgroundNormal"), (58, 51, 58)))


def oxygen_css(pal, metrics=None, button=None) -> str:
    """Oxygen's recessed groove, gradient slider and chevron steppers.

    Every ratio here is measured (see the module docstring). The ladder, on a
    17px bar: 2px of window either side, a 1px darker groove border, a 13px
    groove one notch below the window, and an 11px slider carrying the button
    colour as a top-lit gradient with a 1px light rim.
    """
    m = dict(_OXY_FALLBACK)
    m.update(metrics or {})
    width = max(6, int(m["scrollWidth"]) + 2)          # the style's real extent
    btn_h = max(8, int(m["scrollButtonHeight"]))
    sub, add = int(m["scrollSubButtons"]), int(m["scrollAddButtons"])

    win = pal("bg")
    # The slider carries the BUTTON colour, which is a group of its own — not
    # `bgAlt`, which is the View/base tone a text field wears.
    face = button or pal("bgAlt")
    # Oxygen inks a stepper with the FULL foreground, not a dimmed one (probe:
    # the arrow came back at the palette's text colour exactly), and warms it
    # toward the focus colour under the pointer. That is the one place this
    # sheet departs from DESIGN.md 9.2's dim-idle arrows, deliberately: under
    # Plasma the bar is Oxygen's, not ours.
    ink = pal("text")
    accent = pal("accent")
    ink_hot = _mix(ink, accent, 0.6)

    # groove: window x0.845, except in a scheme too dark to darken further,
    # where Oxygen's shade() gives up and lightens instead (measured at window
    # lightness 0.063: the groove came back LIGHTER, 0.231).
    wl = _lum(win)
    groove = _scale_l(win, 0.845) if wl >= 0.08 else _scale_l(win, 3.7, floor=0.12)
    groove_edge = _scale_l(groove, 0.79)
    top, bottom = _scale_l(face, 0.99), _scale_l(face, 0.93)
    rim = _scale_l(face, 1.25, floor=0.10)             # the slider's 1px light edge
    crown = _scale_l(face, 1.5, floor=0.14)            # and its brighter top line
    rad = width // 2

    hot_top, hot_bottom = _mix(top, accent, 0.30), _mix(bottom, accent, 0.30)
    act_top, act_bottom = _mix(top, accent, 0.55), _mix(bottom, accent, 0.55)

    def slab(a, b):
        return ("background-image:linear-gradient(to bottom,%s,%s)!important;"
                "background-clip:padding-box!important;" % (a, b))

    css = [
        # A site that sets `scrollbar-color` or `scrollbar-width` takes
        # Chromium's standard rendering, which ignores every rule below — so
        # put it back on the webkit path first.
        "*{scrollbar-color:auto!important;scrollbar-width:auto!important}",
        "::-webkit-scrollbar{width:%dpx!important;height:%dpx!important;"
        "background-color:%s!important}" % (width, width, win),
        "::-webkit-scrollbar-corner{background-color:%s!important}" % win,
        # The groove is the TRACK, not the two track-pieces: Oxygen's hole runs
        # unbroken under the slider, and a piece each side would round its ends
        # against the slider instead.
        "::-webkit-scrollbar-track{background-color:%s!important;"
        "background-clip:padding-box!important;border:2px solid transparent!important;"
        "border-radius:%dpx!important;box-shadow:inset 0 0 0 1px %s!important}"
        % (groove, rad, groove_edge),
        "::-webkit-scrollbar-track-piece{background:transparent!important}",
        "::-webkit-scrollbar-thumb{%sborder:3px solid transparent!important;"
        "border-radius:%dpx!important;"
        "box-shadow:inset 0 0 0 1px %s,inset 0 1px 0 %s!important}"
        % (slab(top, bottom), max(2, rad - 1), rim, crown),
        "::-webkit-scrollbar-thumb:hover{%s}" % slab(hot_top, hot_bottom),
        "::-webkit-scrollbar-thumb:active{%s}" % slab(act_top, act_bottom),
    ]

    # The steppers. Oxygen draws no slab under them — just a chevron on the
    # window — and their COUNT is his, out of oxygenrc: one above (sub) and two
    # below (add) by upstream default, which is exactly webkit's single-button
    # start / double-button end shape.
    def button(sel, direction, colour):
        return ("::-webkit-scrollbar-button%s{display:block!important;"
                "height:%dpx!important;width:%dpx!important;"
                "background-color:transparent!important;background-repeat:no-repeat!important;"
                "background-position:center!important;background-image:url(%s)!important}"
                % (sel, btn_h, width, _chevron(colour, direction)))

    shown, hidden = [], []
    for sel, direction, on in (
            (":vertical:start:decrement", "up", sub >= 1),
            (":vertical:start:increment", "down", sub >= 2),
            (":vertical:end:decrement", "up", add >= 2),
            (":vertical:end:increment", "down", add >= 1),
            (":horizontal:start:decrement", "left", sub >= 1),
            (":horizontal:start:increment", "right", sub >= 2),
            (":horizontal:end:decrement", "left", add >= 2),
            (":horizontal:end:increment", "right", add >= 1)):
        if on:
            shown.append((sel, direction))
        else:
            hidden.append(sel)
    if hidden:
        css.append("%s{display:none!important}"
                   % ",".join("::-webkit-scrollbar-button" + s for s in hidden))
    for sel, direction in shown:
        css.append(button(sel, direction, ink))
        css.append(button(sel + ":hover", direction, ink_hot))
        css.append(button(sel + ":active", direction, accent))
    # A stepper's corner piece (webkit draws one where two buttons meet) must
    # not keep the default light square.
    css.append("::-webkit-scrollbar-button:decrement:increment{display:none!important}")
    return "".join(css)


# ---- the desktop's own face -------------------------------------------------
def _triangle(ink, direction):
    """The 9x5 solid pixel-triangle VScroll's Arrow draws — the same geometry
    surfer's `triangleUri()` injects, so the two browsers agree."""
    if direction == "up":
        w, h, pts = 9, 5, "4,0 8,4 0,4"
    elif direction == "down":
        w, h, pts = 9, 5, "0,0 8,0 4,4"
    elif direction == "left":
        w, h, pts = 5, 9, "0,4 4,0 4,8"
    else:
        w, h, pts = 5, 9, "4,4 0,0 0,8"
    return _uri('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
                'viewBox="0 0 %d %d" shape-rendering="crispEdges">'
                '<polygon points="%s" fill="%s"/></svg>' % (w, h, w, h, pts, ink))


def desktop_css(pal, style=DEFAULT_STYLE) -> str:
    """`win31` / `beveled` / `flat` — DESIGN.md 9.2, hard 1px bevels, no radius,
    no gradient, the same ladder surfer draws on a page."""
    dark, track = pal("bg"), pal("bgAlt")
    face, light = pal("border"), pal("dim")
    accent, ink, ink_hot = pal("accent"), pal("textDim"), pal("text")
    width = 16 if style == "win31" else (14 if style == "beveled" else 11)
    raised = ("border-top:1px solid %s!important;border-left:1px solid %s!important;"
              "border-bottom:1px solid %s!important;border-right:1px solid %s!important;"
              % (light, light, dark, dark))
    sunken = ("border-top:1px solid %s!important;border-left:1px solid %s!important;"
              "border-bottom:1px solid %s!important;border-right:1px solid %s!important;"
              % (dark, dark, light, light))
    css = [
        "*{scrollbar-color:auto!important;scrollbar-width:auto!important}",
        "::-webkit-scrollbar{width:%dpx!important;height:%dpx!important;"
        "background-color:%s!important}" % (width, width, track),
        "::-webkit-scrollbar-corner{background-color:%s!important}" % track,
    ]
    if style == "flat":
        css += ["::-webkit-scrollbar-track{background-color:%s!important;border:none!important}" % track,
                "::-webkit-scrollbar-thumb{background-color:%s!important;border:none!important;"
                "border-radius:0!important}" % ink,
                "::-webkit-scrollbar-thumb:hover{background-color:%s!important}" % ink_hot,
                "::-webkit-scrollbar-thumb:active{background-color:%s!important}" % accent,
                "::-webkit-scrollbar-button{display:none!important}"]
        return "".join(css)
    css += ["::-webkit-scrollbar-track{background-color:%s!important;%s}" % (track, sunken),
            "::-webkit-scrollbar-thumb{background-color:%s!important;border-radius:0!important;%s}"
            % (face, raised),
            "::-webkit-scrollbar-thumb:active{background-color:%s!important}" % accent]
    if style != "win31":
        css.append("::-webkit-scrollbar-button{display:none!important}")
        return "".join(css)
    base = ("display:block!important;width:%dpx!important;height:%dpx!important;"
            "background-color:%s!important;background-repeat:no-repeat!important;"
            "background-position:center!important;" % (width, width, face))
    for sel, direction in ((":vertical:start:decrement", "up"),
                           (":vertical:end:increment", "down"),
                           (":horizontal:start:decrement", "left"),
                           (":horizontal:end:increment", "right")):
        css.append("::-webkit-scrollbar-button%s{%s%sbackground-image:url(%s)!important}"
                   % (sel, base, raised, _triangle(ink, direction)))
        css.append("::-webkit-scrollbar-button%s:hover{background-image:url(%s)!important}"
                   % (sel, _triangle(ink_hot, direction)))
        css.append("::-webkit-scrollbar-button%s:active{%sbackground-image:url(%s)!important}"
                   % (sel, sunken, _triangle(accent, direction)))
    css.append("::-webkit-scrollbar-button:vertical:start:increment,"
               "::-webkit-scrollbar-button:vertical:end:decrement,"
               "::-webkit-scrollbar-button:horizontal:start:increment,"
               "::-webkit-scrollbar-button:horizontal:end:decrement{display:none!important}")
    return "".join(css)


# ---- the page wash -----------------------------------------------------------
def page_tint_css(pal) -> str:
    """A live, click-through wash over a foreign page.

    A browser page is not ours to re-layout or re-colour selector by selector.
    The overlay keeps its images, controls and typography intact while carrying
    the current desktop accent over the complete page.  It deliberately belongs
    to the Tampermonkey page sheet, never Vivaldi's own ``custom.css``.
    """
    # ``color`` keeps a light page's value ladder while replacing its hue.  It
    # cannot change a black pixel, though, so a second low-alpha ``screen``
    # layer gives the same live accent a visible presence on dark pages.
    return (
        "html::before{content:\"\"!important;position:fixed!important;inset:0!important;"
        "z-index:2147483646!important;pointer-events:none!important;"
        "background-color:%s!important;mix-blend-mode:color!important;opacity:.18!important}"
        "html::after{content:\"\"!important;position:fixed!important;inset:0!important;"
        "z-index:2147483645!important;pointer-events:none!important;"
        "background-color:%s!important;mix-blend-mode:screen!important;opacity:.10!important}"
        % (pal("accent"), pal("accent"))
    )


# ---- what a caller asks for -------------------------------------------------
def build(source=None, style=None, page=False):
    """(css, provenance) for the requested session face.

    `source` forces `plasma` | `hypr` instead of reading the live session;
    `style` forces one of the three desktop variants.
    """
    import chansource                                 # the palette readers, shared

    plasma = kdetheme.is_plasma() if source is None else (source == "plasma")
    if plasma:
        colors = kdetheme.kde_palette()
        if colors:
            pal = {k: kdetheme._hex(v) for k, v in colors.items()}
            chrome = kdetheme.kde_chrome()
            if chrome:                                 # a gradient KStyle: Oxygen's bar
                metrics = None
                try:
                    import oxygenstyle
                    if oxygenstyle.is_oxygen():
                        metrics = oxygenstyle.metrics()
                except Exception:                      # noqa: BLE001 - kcfg defaults
                    metrics = None
                css = oxygen_css(pal.__getitem__, metrics, kde_button())
                if page:
                    css += page_tint_css(pal.__getitem__)
                return (css, "Oxygen's own bar (%s, %dpx)"
                        % (chrome["style"], (metrics or _OXY_FALLBACK)["scrollWidth"]))
            pick = style or scrollbar_style()
            css = desktop_css(pal.__getitem__, pick)
            if page:
                css += page_tint_css(pal.__getitem__)
            return (css,
                    "the desktop's %s bar, KDE colour scheme" % pick)
    pal = chansource.panel_palette()
    if not pal:
        raise SystemExit("no palette: neither a readable kdeglobals nor %s"
                         % chansource.PANEL_THEME)
    pick = style or scrollbar_style()
    css = desktop_css(pal.__getitem__, pick)
    if page:
        css += page_tint_css(pal.__getitem__)
    return (css,
            "the desktop's %s bar, wallpaper palette" % pick)


if __name__ == "__main__":     # `python3 scrollcss.py` — what this box resolves to
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    text, prov = build()
    sys.stderr.write("from: %s\n" % prov)
    print(text)
