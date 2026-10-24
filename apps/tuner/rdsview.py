"""Fourteen-segment RDS face, drawn locally in the theme's selection colour."""

import time
import unicodedata

from gi.repository import GLib, Gtk, Pango, PangoCairo

from faceplate import GHOST, glow

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


def cell_text(text, cells, elapsed, animate=True):
    """Characters move between fixed segment cells, never between pixel positions."""
    text = display_text(text)
    if len(text) <= cells or not animate:
        return text[:cells].ljust(cells)
    step = int(max(0, elapsed - 1.5) / .4)
    cycle = text + '    '
    start = step % len(cycle)
    return (cycle + cycle)[start:start + cells]


class RdsDisplay(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(360, 48)
        self.heading = 'RDS'
        self.text = 'Receiver stopped'
        self.since = time.monotonic()
        self.timer = None
        self._scrolling = False
        self._last_step = 0
        self._detail = None
        self.connect('draw', self._draw)
        self.connect('map', self._mapped)
        self.connect('unmap', self._unmapped)
        self.connect('destroy', self._unmapped)
        self.get_accessible().set_name('RDS display')

    def set_message(self, heading, text, detail=None):
        if (heading, text, detail) == (self.heading, self.text, self._detail):
            return
        self._detail = detail
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
            self.timer = GLib.timeout_add(100, self._tick)

    def _unmapped(self, *args):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def _tick(self):
        step = int(max(0, time.monotonic() - self.since - 1.5) / .4)
        if (self._scrolling and step != self._last_step
                and self.get_settings().get_property('gtk-enable-animations')):
            self._last_step = step
            self.queue_draw()
        return True

    def _draw(self, widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.save()
        cr.rectangle(8, 2, max(w - 16, 1), max(h - 4, 1))
        cr.clip()
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription('Tuner Segment 11'))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_width(max(w - 16, 1) * Pango.SCALE)
        layout.set_text(self.heading, -1)
        cr.move_to(9, 2)
        PangoCairo.layout_path(cr, layout)
        glow(cr, .6, fill=True, alpha=.8)
        _, title_h = layout.get_pixel_size()
        glyph_h = max(14, h - title_h - 10)
        glyph_w = glyph_h * .55
        advance = glyph_w + 5
        cells = max(1, int(max(w - 20, 1) / advance))
        self._scrolling = len(display_text(self.text)) > cells
        text = cell_text(self.text, cells, time.monotonic() - self.since,
                         self.get_settings().get_property('gtk-enable-animations'))
        for i, char in enumerate(text):
            self._glyph(cr, char, 10 + i * advance, title_h + 5, glyph_w, glyph_h)
        cr.restore()
        return True

    @staticmethod
    def _glyph(cr, char, x, y, w, h):
        active = '' if char in '.:,' else GLYPHS.get(char, GLYPHS['?'])
        width = max(1.1, h * .065)
        cr.set_line_width(width)
        lit = []
        cr.set_source_rgb(*GHOST)
        for index, (start, end) in enumerate(SEGMENTS):
            if chr(ord('a') + index) in active:
                lit.append((start, end))
                continue
            cr.move_to(x + start[0] * w, y + start[1] * h)
            cr.line_to(x + end[0] * w, y + end[1] * h)
            cr.stroke()
        # Ghosts go down first so no unlit stroke in this cell covers a halo.
        for start, end in lit:
            cr.move_to(x + start[0] * w, y + start[1] * h)
            cr.line_to(x + end[0] * w, y + end[1] * h)
        if lit:
            glow(cr, width)
        if char in '.:,':
            for dy in ((.32, .72) if char == ':' else (.92,)):
                cr.new_sub_path()
                cr.arc(x + w * .5, y + h * dy, max(1, h * .045), 0, 6.284)
            glow(cr, 1, fill=True)
