"""A segmented receiver face, with native GTK keyboard and control behavior."""

import base64
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
# Every character on the face is this size, typeset (segment.ttf) or drawn.
SIZE = 20
ROW = SIZE + 4


def cell(height):
    """(x inset, glyph top, glyph width, glyph height, advance) of one
    character, matching segment.ttf's outlines, centred in a row `height` tall."""
    # The font's em box is 900 up / 100 down; a glyph spans 130..830 units
    # vertically and 70..530 across a 600-unit advance.
    return (.07 * SIZE, (height - SIZE) / 2 + .07 * SIZE,
            .46 * SIZE, .70 * SIZE, .60 * SIZE)

CSS = """
#tuner-face {
    background: #090a08;
    color: @lit;
    border: 2px solid #302c24;
    border-radius: 3px;
    padding: 2px 6px;
}
#tuner-face * {
    font-family: "Tuner Segment";
    font-size: @sizepx;
    font-weight: normal;
    color: @lit;
    text-shadow: 0 0 2px alpha(@lit, 0.85), 0 0 7px alpha(@lit, 0.45);
    -gtk-icon-shadow: none;
}
#tuner-face menu { background: #090a08; border: 1px solid mix(@lit, #090a08, 0.6); }
#tuner-face menuitem:hover { background: mix(@lit, #090a08, 0.8); }
#tuner-face toolbar { background: transparent; border: none; box-shadow: none; }
#tuner-face button, #tuner-face entry {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 0;
    box-shadow: none;
    min-height: 0;
    padding: 0 4px;
}
#tuner-face entry { border-bottom-color: mix(@lit, #090a08, 0.7); }
#tuner-face combobox box { min-height: 0; }
#tuner-face scale, #tuner-face scale * {
    min-height: 0;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: none;
}
#tuner-face button:hover, #tuner-face button:focus, #tuner-face entry:focus {
    border-bottom-color: @lit;
}
#tuner-face button:checked, #tuner-face button:active {
    background: mix(@lit, #090a08, 0.8);
    border-bottom-color: @core;
}
#tuner-face button:checked *, #tuner-face button:active * { color: @core; }
#tuner-face *:disabled { color: mix(@lit, #090a08, 0.55); text-shadow: none; }
#tuner-face entry selection { background: mix(@lit, #090a08, 0.6); color: @core; }
#tuner-face separator { background: mix(@lit, #090a08, 0.82); min-width: 1px; }
#tuner-face arrow {
    min-width: 12px;
    min-height: 10px;
    -gtk-icon-source: url("data:image/svg+xml;base64,@arrow");
}
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
    arrow = ("<svg xmlns='http://www.w3.org/2000/svg' width='12' height='10'>"
             "<path d='M1 2L6 7L11 2' fill='none' stroke='%s' stroke-width='2'/></svg>"
             % _hex(LIT))
    css = (CSS.replace('@arrow', base64.b64encode(arrow.encode()).decode())
           .replace('@lit', _hex(LIT)).replace('@core', _hex(core()))
           .replace('@size', str(SIZE)))
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


def _bars(widget, cr, fraction, focused=False):
    """A bargraph in the readouts' own segment cells: two lit bars per character."""
    height = widget.get_allocated_height()
    inset, top, _, glyph_h, advance = cell(height)
    pitch = advance / 2
    count = widget.BARS
    lit = round(max(0, min(1, fraction)) * count)
    bar = pitch * .55
    cr.set_source_rgb(*GHOST)
    for index in range(lit, count):
        cr.rectangle(inset + index * pitch, top, bar, glyph_h)
    cr.fill()
    for index in range(lit):
        cr.rectangle(inset + index * pitch, top, bar, glyph_h)
    if lit:
        glow(cr, 1, fill=True)
    if focused:
        cr.rectangle(inset, top + glyph_h + 2, count * pitch - (pitch - bar), 1)
        glow(cr, 1, fill=True)
    return True


def _bars_width(count):
    inset, _, _, _, advance = cell(ROW)
    return round(2 * inset + count * advance / 2)


class SegmentMeter(Gtk.DrawingArea):
    BARS = 20

    def __init__(self):
        super().__init__()
        self.value = 0
        self.set_size_request(_bars_width(self.BARS), ROW)
        self.get_accessible().set_name('Signal level')
        self.connect('draw', lambda w, cr: _bars(w, cr, self.value / 100))

    def set_value(self, value):
        self.value = value
        self.get_accessible().set_description('%g percent' % value)
        self.queue_draw()


class SegmentScale(Gtk.Scale):
    """Keep GTK range input and accessibility; render only segment bars."""
    BARS = 14

    def __init__(self, adjustment):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        self.set_size_request(_bars_width(self.BARS), ROW)
        self.connect('draw', self._draw)
        self.get_accessible().set_name('Audio gain')

    def _draw(self, widget, cr):
        adj = self.get_adjustment()
        fraction = (adj.get_value() - adj.get_lower()) / (adj.get_upper() - adj.get_lower())
        return _bars(self, cr, fraction, self.has_focus())
