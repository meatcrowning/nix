"""Vivaldi's own interface, wearing this desktop's look.

Vivaldi's UI is a Chromium page — `#browser` inside an extension window — and
everything in it draws from about ninety CSS custom properties its theme engine
computes and sets on that element. So the browser can be re-themed the way a
web page is re-themed: define the whole ladder ourselves and the chrome follows,
with no patched build and no source to compile (there is none to compile — the
Chromium layer is only partly published and the Vivaldi layer not at all).

THREE LAYERS, and they are deliberately separable:

* `variables()` — the ~90 colour properties plus the corner radii, derived from
  the live palette. This is the layer that does the actual re-colouring, and it
  is the one least likely to break: the names are the theme engine's own, read
  off a running Vivaldi rather than guessed (`tools/vivaldi-probe.py` dumps
  them over CDP from an isolated instance).
* `relief_css()` — Oxygen's VOCABULARY on the surfaces that have one: gradient
  header/toolbar/statusbar slabs, a raised active tab, a sunken address field,
  bevelled toolbar buttons, 3px corners. This layer names Vivaldi's own class
  names (`#header`, `.toolbar-mainbar`, `.UrlBar-AddressField`,
  `.ToolbarButton-Button`), so a Vivaldi redesign can stale it — it degrades to
  "colours are right, shapes are Vivaldi's", never to a broken window. Drawn
  only when the KStyle actually draws relief (`kdetheme.kde_chrome()`); on the
  Hyprland face DESIGN.md 2's no-gradients rule holds and this is flat.
* `theme()` — the same colours as a Vivaldi THEME entry for `Preferences`, so
  the browser's own light/dark classification (which decides icon polarity and
  a few things CSS cannot reach) agrees with the palette, and so the look
  survives with custom.css switched off.

None of it touches page CONTENT: a site's own colours are its own.
"""
from __future__ import annotations

import hexcolor
import kdetheme

# Oxygen's slab/hole corner. Vivaldi ships 8px, which is the single loudest
# "this is a different toolkit" cue in the window.
RADIUS = 3


def _alpha(colour, percent):
    """Vivaldi's own idiom for a translucent step, kept verbatim so a rule of
    theirs that expects `color-mix` still parses."""
    return "color-mix(in srgb, %s, transparent %d%%)" % (colour, percent)


def variables(pal, chrome=None) -> dict:
    """The whole `--color*` ladder from the twelve desktop tokens.

    Vivaldi computes these from four theme colours; we compute them from the
    palette directly, because its derivation assumes its own contrast curve and
    lands somewhere else on a KDE scheme. Lightness steps are MULTIPLIED
    (hexcolor), so the ladder holds in a dark scheme as well as a light one.
    """
    bg, fg = pal("bg"), pal("text")
    view, border = pal("bgAlt"), pal("border")
    accent, highlight = pal("accent"), pal("highlight")

    light = hexcolor.scale_l(bg, 1.06)
    lighter = hexcolor.scale_l(bg, 1.13)
    dark = hexcolor.scale_l(bg, 0.94)
    darker = hexcolor.scale_l(bg, 0.87)
    accent_fg = hexcolor.readable_on(accent, fg, bg)
    highlight_fg = hexcolor.readable_on(highlight, fg, bg)

    v = {
        # ---- surfaces ----
        "colorBg": bg,
        "colorBgLight": light,
        "colorBgLighter": lighter,
        "colorBgLightIntense": lighter,
        "colorBgDark": dark,
        "colorBgDarker": darker,
        "colorBgFaded": darker,
        # "intense" is Vivaldi's elevated surface (white, in its light theme):
        # the scheme's View colour is exactly that role on a KDE palette.
        "colorBgIntense": view,
        "colorBgIntenser": hexcolor.scale_l(view, 1.08),
        "colorBgInverse": hexcolor.scale_l(bg, 0.97),
        "colorBgInverser": hexcolor.scale_l(bg, 0.92),
        "colorBgAlpha": _alpha(bg, 10),
        "colorBgAlphaHeavy": _alpha(bg, 35),
        "colorBgAlphaHeavier": _alpha(bg, 75),
        "colorBgAlphaBlur": bg + "66",
        # ---- ink ----
        "colorFg": fg,
        "colorFgIntense": hexcolor.scale_l(fg, 1.15),
        "colorFgFaded": hexcolor.mix(fg, bg, 0.25),
        "colorFgFadedMore": hexcolor.mix(fg, bg, 0.45),
        "colorFgFadedMost": hexcolor.mix(fg, bg, 0.62),
        "colorFgAlpha": _alpha(fg, 90),
        # ---- frames ----
        "colorBorder": border,
        "colorBorderSubtle": hexcolor.mix(border, bg, 0.5),
        "colorBorderIntense": hexcolor.mix(border, fg, 0.35),
        "colorBorderDisabled": hexcolor.mix(border, bg, 0.7),
        # ---- accent (the window's own colour: tab bar, active tab, focus) ----
        "colorAccentBg": accent,
        "colorAccentBgDark": hexcolor.scale_l(accent, 0.88),
        "colorAccentBgDarker": hexcolor.scale_l(accent, 0.76),
        "colorAccentBgFaded": hexcolor.mix(accent, bg, 0.20),
        "colorAccentBgFadedMore": hexcolor.scale_l(accent, 1.12),
        "colorAccentBgFadedMost": hexcolor.scale_l(accent, 1.25),
        "colorAccentBorder": accent,
        "colorAccentBorderDark": hexcolor.scale_l(accent, 0.92),
        "colorAccentFg": accent_fg,
        "colorAccentFgFaded": hexcolor.mix(accent_fg, accent, 0.35),
        "colorAccentBgAlpha": _alpha(accent, 50),
        "colorAccentBgAlphaHeavy": _alpha(accent, 70),
        "colorAccentBgAlphaBlur": accent + "66",
        "colorAccentFgAlpha": _alpha(accent_fg, 85),
        # ---- selection ----
        "colorHighlightBg": highlight,
        "colorHighlightBgDark": hexcolor.scale_l(highlight, 0.85),
        "colorHighlightBgFaded": hexcolor.scale_l(highlight, 1.2),
        "colorHighlightBgAlpha": _alpha(highlight, 90),
        "colorHighlightFg": highlight_fg,
        "colorHighlightFgAlpha": _alpha(highlight_fg, 50),
        "colorHighlightFgAlphaHeavy": _alpha(highlight_fg, 75),
        # ---- status, from the palette's own three ----
        "colorErrorBg": pal("crit"),
        "colorErrorBgAlpha": _alpha(pal("crit"), 90),
        "colorErrorFg": hexcolor.readable_on(pal("crit"), fg, bg),
        "colorSuccessBg": pal("ok"),
        "colorSuccessBgAlpha": _alpha(pal("ok"), 90),
        "colorSuccessFg": hexcolor.readable_on(pal("ok"), fg, bg),
        "colorWarningBg": pal("warn"),
        "colorWarningBgAlpha": _alpha(pal("warn"), 90),
        "colorWarningFg": hexcolor.readable_on(pal("warn"), fg, bg),
    }

    # The Image* family is what the chrome reads WHERE A BACKGROUND IMAGE would
    # show through (five zones, so a photo can be light at the top and dark at
    # the foot). We set no image, so every zone is simply the surface — left at
    # Vivaldi's defaults they stay light-theme values and put black ink on a
    # dark toolbar.
    for zone in ("", "Top", "Bottom", "Left", "Right", "Center"):
        v["colorImage%sBg" % zone] = bg
        v["colorImage%sBgAlpha" % zone] = _alpha(bg, 45)
        v["colorImage%sBgAlphaHeavy" % zone] = _alpha(bg, 65)
        v["colorImage%sFg" % zone] = fg
        v["colorImage%sFgAlpha" % zone] = _alpha(fg, 40)
        v["colorImage%sFgAlphaHeavy" % zone] = _alpha(fg, 85)

    # Corners. `--radiusRound` is the pill for a genuinely round thing (a
    # badge); it stays.
    v.update({
        "radius": "%dpx" % RADIUS,
        "radiusCap": "%dpx" % RADIUS,
        "radiusHalf": "%dpx" % max(1, RADIUS - 1),
        "radiusRounded": "%dpx" % max(1, RADIUS - 1),
        "radiusRoundedLess": "%dpx" % RADIUS,
        "radiusWindow": "%dpx" % RADIUS,
    })
    return v


def relief_css(pal, chrome=None) -> str:
    """Oxygen's slabs, bevels and holes on the surfaces that have them.

    Flat when `chrome` is None — the Hyprland face, where DESIGN.md 2 forbids
    gradients — so this returns the same structure either way and only the
    fills differ.
    """
    bg, fg, border = pal("bg"), pal("text"), pal("border")
    view = pal("bgAlt")
    if chrome:
        win_top, win_bottom = chrome["windowTop"], chrome["windowBottom"]
        btn_top, btn_bottom = chrome["buttonTop"], chrome["buttonBottom"]
        head_top, head_bottom = chrome["headerTop"], chrome["headerBottom"]
        bevel, shade = chrome["bevel"], chrome["shade"]
    else:
        win_top = win_bottom = bg
        btn_top = btn_bottom = hexcolor.scale_l(bg, 1.08)
        head_top = head_bottom = bg
        bevel, shade = "rgba(255,255,255,0.06)", "rgba(0,0,0,0.22)"

    def slab(a, b):
        return ("background:%s!important" % a if a == b
                else "background:linear-gradient(to bottom,%s,%s)!important" % (a, b))

    r = "%dpx" % RADIUS
    return "".join([
        # The window's own surfaces: title/tab strip, address bar, status bar.
        "#header,.tabbar-wrapper,#tabs-tabbar-container{%s;box-shadow:inset 0 1px 0 %s!important}"
        % (slab(head_top, head_bottom), bevel),
        ".toolbar-mainbar{%s;border-bottom:1px solid %s!important}" % (slab(win_top, win_bottom), border),
        "#footer,.toolbar-statusbar{%s;border-top:1px solid %s!important}" % (slab(win_top, win_bottom), border),
        "#panels-container{background:%s!important;border-right:1px solid %s!important}" % (bg, border),
        # A tab is a slab: raised and lit when active, recessed and quiet when not.
        ".tab{border-radius:%s!important}" % r,
        ".tab.active,.tab-position.active .tab{%s;border:1px solid %s!important;"
        "box-shadow:inset 0 1px 0 %s,0 1px 2px %s!important}"
        % (slab(btn_top, btn_bottom), border, bevel, shade),
        # THE ACTIVE TAB'S INK. Vivaldi assumes the active tab carries the
        # ACCENT colour and inks its title with the contrast tone it computed
        # for that — with a light accent that is a near-black, and our slab is
        # not the accent, so the title came out invisible on it (measured: ink
        # #2b2317 on a #574936 slab). Say what it is instead of inheriting an
        # assumption. `*` reaches the title span and the close button; svg
        # icons follow currentColor and want the same value anyway.
        ".tab.active,.tab.active *{color:%s!important}"
        % hexcolor.readable_on(btn_top, fg, pal("textDim"), bg),
        ".tab:not(.active){background:%s!important;box-shadow:inset 0 -1px 0 %s!important}"
        % (hexcolor.scale_l(bg, 0.93), shade),
        # The address field is a HOLE, the way every Oxygen text field is.
        ".UrlBar-AddressField{background:%s!important;border:1px solid %s!important;"
        "border-radius:%s!important;box-shadow:inset 0 1px 2px %s!important}"
        % (view, hexcolor.scale_l(border, 0.8), r, shade),
        ".UrlBar-AddressField.focus,.UrlBar-AddressField:focus-within{"
        "border-color:%s!important}" % pal("accent"),
        # Toolbar buttons: nothing until the pointer is on them, then a slab.
        ".ToolbarButton-Button{border-radius:%s!important}" % r,
        ".ToolbarButton-Button:hover{%s;box-shadow:inset 0 1px 0 %s,0 1px 2px %s!important}"
        % (slab(btn_top, btn_bottom), bevel, shade),
        ".ToolbarButton-Button:active,.ToolbarButton-Button.active{"
        "background:%s!important;box-shadow:inset 0 1px 3px %s!important}"
        % (hexcolor.scale_l(bg, 0.9), shade),
        # Menus and popups get the surface and the corner, not the pill.
        ".menu,.menubar,.observer,.dialog,.OmniDropdown,.PanelGroup{"
        "background:%s!important;border-radius:%s!important;border:1px solid %s!important}"
        % (bg, r, border),
        # Ink that Vivaldi hardcodes in a couple of places.
        "#browser{color:%s}" % fg,
    ])


def css(pal, chrome=None, extra="") -> str:
    """The whole `custom.css` body: the ladder, then the relief, then whatever
    the caller appends (the scrollbar sheet, in practice)."""
    v = variables(pal, chrome)
    block = "".join("  --%s: %s !important;\n" % (k, val) for k, val in sorted(v.items()))
    # Both selectors: the theme engine sets these on #browser, and a few of
    # Vivaldi's own popups mount outside it.
    return (":root,\n#browser,\n#app {\n%s}\n" % block) + relief_css(pal, chrome) + extra


def theme(pal, name="desktop") -> dict:
    """The same colours as a Vivaldi theme entry.

    Vivaldi classifies its own UI as light or dark from `colorBg` — that decides
    icon polarity and a handful of things no stylesheet can reach — so the theme
    has to agree with the palette even though custom.css does the real work.
    """
    return {
        "accentFromPage": False,
        "accentOnWindow": False,
        "accentSaturationLimit": 0.85,
        "alpha": 0.4,
        "backgroundImage": "",
        "backgroundPosition": "stretch",
        "backgroundSource": "",
        "url": "",
        "dimBlurred": False,
        "simpleScrollbar": True,
        "blur": 0,
        "colorAccentBg": pal("accent"),
        "colorBg": pal("bg"),
        "colorFg": pal("text"),
        "colorHighlightBg": pal("highlight"),
        "colorPosition": "unified",
        "colorWindowBg": "",
        "contrast": 0,
        "engineVersion": 1,
        "name": name,
        "preferSystemAccent": False,
        "radius": RADIUS,
        "transparencyTabBar": False,
        "transparencyTabs": False,
        "version": 1,
    }


def build(source=None, extra=""):
    """(css, provenance) for the live session's face."""
    import chansource

    plasma = kdetheme.is_plasma() if source is None else (source == "plasma")
    if plasma:
        colors = kdetheme.kde_palette()
        if colors:
            pal = {k: kdetheme._hex(v) for k, v in colors.items()}
            chrome = kdetheme.kde_chrome()
            return (css(pal.__getitem__, chrome, extra),
                    "KDE colour scheme (%s, %s)"
                    % ((chrome or {}).get("style", kdetheme.kde_widget_style() or "unknown style"),
                       "with the style's relief" if chrome else "flat style"))
    pal = chansource.panel_palette()
    if not pal:
        raise SystemExit("no palette: neither a readable kdeglobals nor %s"
                         % chansource.PANEL_THEME)
    return (css(pal.__getitem__, None, extra),
            "panel wallpaper palette (flat, per DESIGN.md 2)")
