"""The receiver face's light: theme colour, glow, and its popup menus' style."""

import ctypes
from pathlib import Path

import cairo
import gi

gi.require_version("PangoFc", "1.0")
from gi.repository import Gtk, PangoCairo, PangoFc


# Lit segments take the GTK theme's selection colour (Ambiance's orange);
# style_faceplate() refreshes it, and the theme setting re-runs that.
LIT = (0.941, 0.467, 0.275)
GHOST = (.13, .13, .13)
GLASS = (.035, .038, .032)

# The face's menus continue the display: same glass, same lit segment type.
CSS = """
#tuner-menu {
    background: #090a08;
    border: 1px solid mix(@lit, #090a08, 0.6);
}
#tuner-menu menuitem {
    font-family: "Tuner Segment";
    font-size: 20px;
    color: @lit;
    text-shadow: 0 0 2px alpha(@lit, 0.85), 0 0 7px alpha(@lit, 0.45);
    padding: 3px 10px;
}
#tuner-menu menuitem:hover { background: mix(@lit, #090a08, 0.8); color: @core; }
#tuner-menu menuitem:disabled { color: mix(@lit, #090a08, 0.55); text-shadow: none; }
#tuner-menu check, #tuner-menu radio { color: @lit; }
"""

_provider = Gtk.CssProvider()


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(round(c * 255) for c in rgb)


def core():
    """A lit segment's centre runs hotter (whiter) than its halo."""
    return tuple(c + (1 - c) * .3 for c in LIT)


def glow(cr, width, fill=False, alpha=1.0):
    """Paint the current path as a lit segment: soft halo under a bright core."""
    r, g, b = LIT
    cap = cr.get_line_cap()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for spread, strength in ((3.4, .07), (2.0, .2)):
        cr.set_line_width(width * spread)
        cr.set_source_rgba(r, g, b, strength * alpha)
        cr.stroke_preserve()
    cr.set_line_cap(cap)
    cr.set_line_width(width)
    cr.set_source_rgba(*core(), alpha)
    cr.fill() if fill else cr.stroke()


def _restyle(widget):
    global LIT
    context = widget.get_style_context()
    for name in ('theme_selected_bg_color', 'selected_bg_color'):
        found, rgba = context.lookup_color(name)
        if found:
            LIT = (rgba.red, rgba.green, rgba.blue)
            break
    css = CSS.replace('@lit', _hex(LIT)).replace('@core', _hex(core()))
    _provider.load_from_data(css.encode())
    widget.queue_draw()


_font_loaded = False


def style_faceplate(widget):
    global _font_loaded
    if not _font_loaded:
        # Fontconfig is already loaded by GTK; register only in this process.
        fc = ctypes.CDLL('libfontconfig.so.1')
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        path = str(Path(__file__).with_name('segment.ttf')).encode()
        if not fc.FcConfigAppFontAddFile(None, path):
            raise RuntimeError('Cannot load Tuner segment font')
        PangoFc.FontMap.config_changed(PangoCairo.FontMap.get_default())
        _font_loaded = True
    _restyle(widget)
    Gtk.StyleContext.add_provider_for_screen(
        widget.get_screen(), _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    widget.get_settings().connect('notify::gtk-theme-name', lambda *a: _restyle(widget))
