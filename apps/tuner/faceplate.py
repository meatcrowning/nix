"""A segmented receiver face, with native GTK keyboard and control behavior."""

import ctypes
from pathlib import Path

import gi

gi.require_version("PangoFc", "1.0")
from gi.repository import Gtk, PangoCairo, PangoFc


CSS = b"""
#tuner-face {
    background: #090a08;
    color: #ff9929;
    border: 2px solid #302c24;
    border-radius: 3px;
    padding: 8px;
}
#tuner-face * {
    font-family: "Tuner Segment";
    font-size: 17px;
    font-weight: normal;
    color: #ff9929;
    text-shadow: none;
    -gtk-icon-shadow: none;
}
#tuner-face menu { background: #090a08; border: 1px solid #68451f; }
#tuner-face menuitem:hover { background: #30200e; }
#tuner-face toolbar { background: transparent; border: none; box-shadow: none; }
#tuner-face button, #tuner-face entry {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 0;
    box-shadow: none;
    padding: 5px 7px;
}
#tuner-face button:hover, #tuner-face button:focus, #tuner-face entry:focus {
    border-bottom-color: #ff9929;
}
#tuner-face button:checked, #tuner-face button:active {
    background: #30200e;
    border-bottom-color: #ffbb62;
}
#tuner-face button:checked *, #tuner-face button:active * { color: #ffcd80; }
#tuner-face *:disabled { color: #735332; }
#tuner-face entry selection { background: #68451f; color: #ffcd80; }
#tuner-face separator { background: #30281b; min-width: 1px; }
#tuner-face arrow {
    min-width: 12px;
    min-height: 10px;
    -gtk-icon-source: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxMicgaGVpZ2h0PScxMCc+PHBhdGggZD0nTTEgMkw2IDdMMTEgMicgZmlsbD0nbm9uZScgc3Ryb2tlPScjZmY5OTI5JyBzdHJva2Utd2lkdGg9JzInLz48L3N2Zz4=");
}
"""

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
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        widget.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _blocks(widget, cr, fraction, focused=False):
    width, height = widget.get_allocated_width(), widget.get_allocated_height()
    count, gap, inset = 20, 3, 5
    cell = (width - 2 * inset) / count
    lit = round(max(0, min(1, fraction)) * count)
    for index in range(count):
        cr.set_source_rgb(*((1, .60, .16) if index < lit else (.13, .13, .13)))
        cr.rectangle(inset + index * cell, height / 2 - 5, max(1, cell - gap), 10)
        cr.fill()
    if focused:
        cr.set_source_rgb(1, .60, .16)
        cr.rectangle(inset, height / 2 + 9, width - 2 * inset, 1)
        cr.fill()
    return True


class SegmentMeter(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.value = 0
        self.set_size_request(150, 24)
        self.get_accessible().set_name('Signal level')
        self.connect('draw', lambda w, cr: _blocks(w, cr, self.value / 100))

    def set_value(self, value):
        self.value = value
        self.get_accessible().set_description('%g percent' % value)
        self.queue_draw()


class SegmentScale(Gtk.Scale):
    """Keep GTK range input and accessibility; render only discrete lit cells."""
    def __init__(self, adjustment):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        self.set_size_request(160, 28)
        self.connect('draw', self._draw)
        self.get_accessible().set_name('Audio gain')

    def _draw(self, widget, cr):
        adj = self.get_adjustment()
        fraction = (adj.get_value() - adj.get_lower()) / (adj.get_upper() - adj.get_lower())
        return _blocks(self, cr, fraction, self.has_focus())
