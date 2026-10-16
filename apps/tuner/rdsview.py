"""Amber fourteen-segment RDS face, drawn locally without a font dependency."""

import time
import unicodedata

from gi.repository import GLib, Gtk, Pango, PangoCairo

from views import _rounded

# a..h are the perimeter/middle bars; i..n are diagonals and centre uprights.
SEGMENTS = (
    ((.12, .04), (.88, .04)), ((.95, .10), (.95, .43)),
    ((.95, .57), (.95, .90)), ((.12, .96), (.88, .96)),
    ((.05, .57), (.05, .90)), ((.05, .10), (.05, .43)),
    ((.12, .50), (.43, .50)), ((.57, .50), (.88, .50)),
    ((.15, .12), (.43, .42)), ((.50, .10), (.50, .42)),
    ((.85, .12), (.57, .42)), ((.15, .88), (.43, .58)),
    ((.50, .58), (.50, .90)), ((.85, .88), (.57, .58)),
)
GLYPHS = {
    '0': 'abcdef', '1': 'bc', '2': 'abdegh', '3': 'abcdgh', '4': 'bcfgh',
    '5': 'acdfgh', '6': 'acdefgh', '7': 'abc', '8': 'abcdefgh', '9': 'abcdfgh',
    'A': 'abcefgh', 'B': 'abcdhjm', 'C': 'adef', 'D': 'abcdjm',
    'E': 'adefgh', 'F': 'aefgh', 'G': 'acdefh', 'H': 'bcefgh',
    'I': 'adjm', 'J': 'bcde', 'K': 'efkn', 'L': 'def', 'M': 'bcefik',
    'N': 'bcefin', 'O': 'abcdef', 'P': 'abefgh', 'Q': 'abcdefn',
    'R': 'abefghn', 'S': 'acdfgh', 'T': 'ajm', 'U': 'bcdef',
    'V': 'efkl', 'W': 'bcefln', 'X': 'ikln', 'Y': 'ikm', 'Z': 'adkl',
    '-': 'gh', '_': 'd', '/': 'kl', '\\': 'in', '+': 'ghjm',
    '=': 'dgh', '?': 'abhm', ' ': '', '[': 'adef', ']': 'abcd',
    '(': 'ef', ')': 'bc', "'": 'j', '"': 'bj', '!': 'jm',
}


def display_text(text):
    text = text.replace('—', '-').replace('–', '-').replace('’', "'")
    return ''.join(c for c in unicodedata.normalize('NFKD', text.upper())
                   if not unicodedata.combining(c))


class RdsDisplay(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(360, 48)
        self.heading = 'RDS'
        self.text = 'Receiver stopped'
        self.since = time.monotonic()
        self.timer = None
        self.connect('draw', self._draw)
        self.connect('map', self._mapped)
        self.connect('unmap', self._unmapped)
        self.connect('destroy', self._unmapped)
        self.get_accessible().set_name('RDS display')

    def set_message(self, heading, text, detail=None):
        if text != self.text:
            self.since = time.monotonic()
        self.heading, self.text = heading, text
        description = detail or (heading + '\n' + text)
        self.set_tooltip_text(description)
        self.get_accessible().set_description(description)
        self.queue_draw()

    def _mapped(self, *args):
        self.since = time.monotonic()
        if self.timer is None:
            self.timer = GLib.timeout_add(50, self._tick)

    def _unmapped(self, *args):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def _tick(self):
        if self.get_settings().get_property('gtk-enable-animations'):
            self.queue_draw()
        return True

    def _draw(self, widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_rgb(.035, .026, .014)
        _rounded(cr, 0, 0, w, h, 4)
        cr.fill()
        cr.save()
        cr.rectangle(8, 2, max(w - 16, 1), max(h - 4, 1))
        cr.clip()
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription('Ubuntu Mono 8'))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_width(max(w - 16, 1) * Pango.SCALE)
        layout.set_text(self.heading, -1)
        cr.set_source_rgb(.72, .43, .12)
        cr.move_to(9, 2)
        PangoCairo.show_layout(cr, layout)
        _, title_h = layout.get_pixel_size()
        glyph_h = max(14, h - title_h - 10)
        glyph_w = glyph_h * .55
        advance = glyph_w + 5
        text = display_text(self.text)
        available = max(w - 20, 1)
        offset = 0
        if len(text) * advance > available and self.get_settings().get_property('gtk-enable-animations'):
            # A readable opening pause, then a steady car-stereo marquee.
            offset = max(0, time.monotonic() - self.since - 1.5) * 30
            cycle = (len(text) + 4) * advance
            offset %= cycle
            text = text + '    ' + text
        for i, char in enumerate(text):
            x = 10 + i * advance - offset
            if x + advance < 8 or x > w - 8:
                continue
            self._glyph(cr, char, x, title_h + 5, glyph_w, glyph_h)
        cr.restore()
        return True

    @staticmethod
    def _glyph(cr, char, x, y, w, h):
        active = '' if char in '.:,' else GLYPHS.get(char, GLYPHS['?'])
        cr.set_line_width(max(1.1, h * .065))
        for index, (start, end) in enumerate(SEGMENTS):
            lit = chr(ord('a') + index) in active
            cr.set_source_rgba(1, .60, .16, .95 if lit else .055)
            cr.move_to(x + start[0] * w, y + start[1] * h)
            cr.line_to(x + end[0] * w, y + end[1] * h)
            cr.stroke()
        if char in '.:,':
            cr.set_source_rgba(1, .60, .16, .95)
            for dy in ((.32, .72) if char == ':' else (.92,)):
                cr.arc(x + w * .5, y + h * dy, max(1, h * .045), 0, 6.284)
                cr.fill()
